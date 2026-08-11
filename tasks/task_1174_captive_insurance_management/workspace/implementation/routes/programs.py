"""InsuranceProgram routes."""
from __future__ import annotations

from flask import Blueprint, request

import db
from clock import fmt_ts, now
from errors import ApiError
from middleware import require_roles
from response import ok, paginate
from services import constants as C
from services.audit import log
from services.core import (
    body,
    get_captive,
    get_program,
    opt_bool,
    parse_dt_field,
    recompute_captive_ledger,
    recompute_program_loss_ratio,
    req_enum,
    req_num,
    req_str,
    stamp_new,
    touch,
    touch_captive,
)

bp = Blueprint("programs", __name__)

READ_ROLES = ("CaptiveManager", "Underwriter", "Actuary", "ClaimsAdjuster")


def _check_overlap(captive_id, lob, start, end):
    """No overlap with existing programs for the same line of business."""
    for p in db.programs.values():
        if p["captive_id"] != captive_id or p["line_of_business"] != lob:
            continue
        if p["program_status"] in ("CLOSED", "CANCELLED"):
            continue
        from clock import parse_ts
        p_start = parse_ts(p["policy_period_start"])
        p_end = parse_ts(p["policy_period_end"])
        if p_start is None or p_end is None:
            continue
        if start < p_end and end > p_start:
            raise ApiError(
                "ERR_POLICY_PERIOD_OVERLAP",
                "Policy period overlaps with existing program for same line of business")


@bp.post("/api/captives/<captiveId>/programs")
def create_program(captiveId):
    user_id, role = require_roles("Underwriter")
    captive = get_captive(captiveId)
    data = body()

    # OCC: expected_captive_version must match the captive's current version.
    expected = data.get("expected_captive_version")
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError("ERR_INVALID_REQUEST",
                       "expected_captive_version is required and must be an integer")
    if expected != captive["version"]:
        raise ApiError("ERR_STALE_VERSION",
                       "Expected version does not match current version; resource has been modified")

    name = req_str(data, "program_name")
    lob = req_enum(data, "line_of_business", C.LINES_OF_BUSINESS)
    start = parse_dt_field(data, "policy_period_start")
    end = parse_dt_field(data, "policy_period_end")
    if end <= start:
        raise ApiError("ERR_INVALID_POLICY_PERIOD",
                       "Policy period end must be after policy period start")
    aggregate = req_num(data, "aggregate_limit_cents")
    per_occ = req_num(data, "per_occurrence_limit_cents")
    attachment = req_num(data, "attachment_point_cents")
    budget = req_num(data, "premium_budget_cents")
    fronting_required = opt_bool(data, "fronting_required", False)

    _check_overlap(captiveId, lob, start, end)

    program = stamp_new()
    program.update({
        "captive_id": captiveId,
        "program_name": name,
        "line_of_business": lob,
        "policy_period_start": fmt_ts(start),
        "policy_period_end": fmt_ts(end),
        "aggregate_limit_cents": int(aggregate),
        "per_occurrence_limit_cents": int(per_occ),
        "attachment_point_cents": int(attachment),
        "premium_budget_cents": int(budget),
        "premium_allocated_cents": 0,
        "claims_incurred_cents": 0,
        "claims_paid_cents": 0,
        "loss_ratio": 0.0,
        "program_status": "DRAFT",
        "coverage_status": "UNBOUND",
        "fronting_required": fronting_required,
    })
    db.programs[program["id"]] = program
    touch_captive(captive)  # creating a program increments captive version
    log(captiveId, "STATE_CHANGE", "InsuranceProgram", program["id"], role,
        user_id, "Insurance program created in DRAFT", None, "DRAFT")
    return ok(program, 201)


@bp.get("/api/captives/<captiveId>/programs")
def list_programs(captiveId):
    require_roles(*READ_ROLES)
    get_captive(captiveId)
    items = sorted(
        [p for p in db.programs.values() if p["captive_id"] == captiveId],
        key=lambda e: e["created_at"])
    page, meta = paginate(items, request.args)
    return ok(page, 200, meta)


@bp.get("/api/captives/<captiveId>/programs/<programId>")
def get_program_route(captiveId, programId):
    require_roles(*READ_ROLES)
    captive = get_captive(captiveId)
    return ok(get_program(captive, programId), 200)


@bp.post("/api/captives/<captiveId>/programs/<programId>/quote")
def quote_program(captiveId, programId):
    user_id, role = require_roles("Underwriter")
    captive = get_captive(captiveId)
    program = get_program(captive, programId)
    if program["program_status"] != "DRAFT":
        raise ApiError("ERR_PROGRAM_NOT_DRAFT",
                       "Program must be in DRAFT state")
    if captive["status"] not in ("CAPITALIZED", "ACTIVE"):
        raise ApiError("ERR_CAPTIVE_NOT_OPERATIONAL",
                       "Captive entity must be in CAPITALIZED or ACTIVE state")
    prev = program["program_status"]
    program["program_status"] = "QUOTED"
    program["coverage_status"] = "UNBOUND"
    touch(program)
    log(captiveId, "STATE_CHANGE", "InsuranceProgram", programId, role,
        user_id, "Program quoted", prev, "QUOTED")
    return ok(program, 200)


@bp.post("/api/captives/<captiveId>/programs/<programId>/bind")
def bind_program(captiveId, programId):
    user_id, role = require_roles("Underwriter")
    captive = get_captive(captiveId)
    program = get_program(captive, programId)
    if program["program_status"] != "QUOTED":
        raise ApiError("ERR_PROGRAM_NOT_QUOTED",
                       "Program must be in QUOTED state")
    fronting = None
    if program.get("fronting_required"):
        for fr in db.frontings.values():
            if fr["program_id"] == programId and fr["status"] not in (
                    "TERMINATED", "EXPIRED"):
                fronting = fr
                break
        ready = fronting is not None and fronting["status"] in (
            "COLLATERAL_POSTED", "ACTIVE")
        if not ready:
            raise ApiError("ERR_FRONTING_NOT_READY",
                           "Fronting arrangement must be in COLLATERAL_POSTED or later state")
    prev = program["program_status"]
    program["program_status"] = "BOUND"
    program["coverage_status"] = "BOUND"
    touch(program)
    log(captiveId, "STATE_CHANGE", "InsuranceProgram", programId, role,
        user_id, "Program bound", prev, "BOUND")
    return ok(program, 200)


@bp.post("/api/captives/<captiveId>/programs/<programId>/activate")
def activate_program(captiveId, programId):
    user_id, role = require_roles("Underwriter")
    captive = get_captive(captiveId)
    program = get_program(captive, programId)
    if program["program_status"] != "BOUND":
        raise ApiError("ERR_PROGRAM_NOT_BOUND",
                       "Program must be in BOUND state")
    if captive["status"] != "ACTIVE":
        raise ApiError("ERR_CAPTIVE_NOT_ACTIVE",
                       "Captive entity must be in ACTIVE state")
    if captive.get("solvency_status") == "BREACH":
        raise ApiError("ERR_SOLVENCY_BREACH",
                       "Solvency ratio is below breach threshold")
    from clock import parse_ts
    start = parse_ts(program["policy_period_start"])
    if start is not None and now() < start:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Policy period has not started")
    prev = program["program_status"]
    program["program_status"] = "IN_FORCE"
    program["coverage_status"] = "BOUND"
    touch(program)
    recompute_captive_ledger(captive)  # ledger sync: total_premium_written
    log(captiveId, "STATE_CHANGE", "InsuranceProgram", programId, role,
        user_id, "Program activated (IN_FORCE)", prev, "IN_FORCE")
    return ok(program, 200)


@bp.post("/api/captives/<captiveId>/programs/<programId>/enter-runoff")
def enter_runoff_program(captiveId, programId):
    user_id, role = require_roles("Underwriter")
    captive = get_captive(captiveId)
    program = get_program(captive, programId)
    if program["program_status"] != "IN_FORCE":
        raise ApiError("ERR_PROGRAM_NOT_IN_FORCE",
                       "Program must be in IN_FORCE state")
    prev = program["program_status"]
    program["program_status"] = "RUN_OFF"
    program["coverage_status"] = "EXPIRED"
    touch(program)
    log(captiveId, "STATE_CHANGE", "InsuranceProgram", programId, role,
        user_id, "Program entered run-off", prev, "RUN_OFF")
    return ok(program, 200)


@bp.post("/api/captives/<captiveId>/programs/<programId>/close")
def close_program(captiveId, programId):
    user_id, role = require_roles("Underwriter")
    captive = get_captive(captiveId)
    program = get_program(captive, programId)
    if program["program_status"] != "RUN_OFF":
        raise ApiError("ERR_PROGRAM_NOT_IN_RUNOFF",
                       "Program must be in RUN_OFF state")
    open_claims = [c for c in db.claims.values()
                   if c["program_id"] == programId
                   and c["claim_status"] not in C.CLAIM_TERMINAL_STATES]
    if open_claims:
        raise ApiError("ERR_OPEN_CLAIMS_EXIST",
                       "Open claims exist; cannot close program")
    unfiled = [r for r in db.reserves.values()
               if r["program_id"] == programId
               and r["status"] not in ("CERTIFIED", "FILED", "SUPERSEDED")]
    if unfiled:
        raise ApiError("ERR_UNFILED_RESERVES_EXIST",
                       "Unfiled reserves exist; cannot close program")
    prev = program["program_status"]
    program["program_status"] = "CLOSED"
    touch(program)
    recompute_program_loss_ratio(program)
    recompute_captive_ledger(captive)
    log(captiveId, "STATE_CHANGE", "InsuranceProgram", programId, role,
        user_id, "Program closed; premium allocation reconciliation finalised",
        prev, "CLOSED")
    return ok(program, 200)


@bp.post("/api/captives/<captiveId>/programs/<programId>/cancel")
def cancel_program(captiveId, programId):
    user_id, role = require_roles("Underwriter")
    captive = get_captive(captiveId)
    program = get_program(captive, programId)
    if program["program_status"] not in ("DRAFT", "QUOTED"):
        raise ApiError("ERR_PROGRAM_NOT_CANCELLABLE",
                       "Program must be in DRAFT or QUOTED state")
    prev = program["program_status"]
    program["program_status"] = "CANCELLED"
    touch(program)
    # Cascade: provisional allocations -> CANCELLED
    for alloc in db.allocations.values():
        if alloc["program_id"] == programId and alloc["status"] == "PROVISIONAL":
            alloc["status"] = "CANCELLED"
            touch(alloc)
    recompute_captive_ledger(captive)
    log(captiveId, "STATE_CHANGE", "InsuranceProgram", programId, role,
        user_id, "Program cancelled; provisional allocations cancelled", prev,
        "CANCELLED")
    return ok(program, 200)
