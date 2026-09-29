"""Consultant reads, termination, reinstatement and administrative rank overrides."""

from flask import Blueprint

from common import (
    clock_str,
    opt_str,
    pagination,
    paginate,
    parse_dt,
    plus_days,
    q_bool,
    q_enum,
    q_str,
    raw_body,
    req_enum,
    req_str,
    touch,
)
from db import db
from errors import ApiError
from middleware import auth, own_consultant
from response import ok, ok_list
from services import consultant_ops, planlib
from services.genealogy import by_created
from services.lookup import fetch

bp = Blueprint("consultants", __name__)

CONSULTANT_STATUSES = ("ACTIVE", "PROBATION", "SUSPENDED", "INACTIVE", "TERMINATED")
TERMINATION_REASONS = ("VOLUNTARY", "ADMINISTRATIVE", "DISCIPLINARY")

READ_ROLES = [
    "Consultant",
    "ComplianceOfficer",
    "CommissionAnalyst",
    "FinanceController",
    "LegalReviewer",
    "PlatformAdmin",
]


@bp.get("/consultants")
def list_consultants():
    auth(READ_ROLES)
    limit, offset = pagination()
    filters = {
        "compensation_plan_id": q_str("compensation_plan_id"),
        "enrollment_application_id": q_str("enrollment_application_id"),
        "sponsor_consultant_id": q_str("sponsor_consultant_id"),
        "reassigned_from_sponsor_consultant_id": q_str("reassigned_from_sponsor_consultant_id"),
        "status": q_enum("status", CONSULTANT_STATUSES),
        "rank_code": q_str("rank_code"),
    }
    payout_hold = q_bool("payout_hold")

    rows = by_created(list(db.consultants.values()))
    for field, value in filters.items():
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    if payout_hold is not None:
        rows = [r for r in rows if r["payout_hold"] is payout_hold]
    page, total = paginate(rows, limit, offset)
    return ok_list(page, total, limit, offset)


@bp.get("/consultants/<consultant_id>")
def read_consultant(consultant_id):
    auth(READ_ROLES)
    own_consultant(consultant_id)
    return ok(fetch("consultant", consultant_id))


@bp.post("/consultants/<consultant_id>/terminate")
def terminate_consultant(consultant_id):
    auth(["ComplianceOfficer", "PlatformAdmin"])
    body = raw_body()
    reason = req_enum(body, "termination_reason", TERMINATION_REASONS)

    consultant = fetch("consultant", consultant_id)
    if consultant["status"] == "TERMINATED":
        raise ApiError("ERR_CONSULTANT_ALREADY_TERMINATED")
    if consultant_ops.approved_run_blocks_termination(consultant):
        raise ApiError("ERR_APPROVED_RUN_BLOCKS_TERMINATION")

    consultant_ops.terminate(consultant, reason)
    return ok(consultant)


@bp.post("/consultants/<consultant_id>/reinstate")
def reinstate_consultant(consultant_id):
    auth(["ComplianceOfficer"])
    body = raw_body()
    opt_str(body, "reinstatement_note")

    consultant = fetch("consultant", consultant_id)
    if consultant["status"] != "TERMINATED":
        raise ApiError("ERR_CONSULTANT_NOT_TERMINATED")

    plan = db.plans.get(consultant["compensation_plan_id"])
    terminated_at = parse_dt(consultant.get("terminated_at") or "")
    now = parse_dt(clock_str())
    if plan is not None and terminated_at is not None:
        deadline = plus_days(terminated_at, plan["reinstatement_window_days"])
        if now is not None and now > deadline:
            raise ApiError("ERR_REINSTATEMENT_WINDOW_EXPIRED")
    if int(consultant["clawback_balance_cents"]) != 0:
        raise ApiError("ERR_CLAWBACK_OUTSTANDING")
    for case in db.cases.values():
        if case["consultant_id"] == consultant["id"] and case["status"] in (
            "OPEN",
            "UNDER_REVIEW",
            "APPEALED",
        ):
            raise ApiError("ERR_OPEN_CASE_BLOCKS_REINSTATEMENT")

    consultant_ops.reinstate(consultant)
    return ok(consultant)


@bp.post("/consultants/<consultant_id>/rank-adjustment")
def rank_adjustment(consultant_id):
    auth(["PlatformAdmin"])
    body = raw_body()
    rank_code = req_str(body, "rank_code", min_len=1)
    opt_str(body, "adjustment_reason")

    consultant = fetch("consultant", consultant_id)
    if consultant["status"] in ("SUSPENDED", "TERMINATED"):
        raise ApiError("ERR_CONSULTANT_NOT_ADJUSTABLE")
    plan = db.plans.get(consultant["compensation_plan_id"])
    rung = planlib.rung_by_code(plan, rank_code) if plan else None
    if rung is None:
        raise ApiError("ERR_RANK_CODE_UNKNOWN")

    consultant["rank_code"] = rung["rank_code"]
    consultant["rank_order"] = rung["rank_order"]
    consultant["rank_source"] = "ADMIN_ADJUSTED"
    consultant["consecutive_qualified_count"] = 0
    consultant["grace_periods_used"] = 0
    touch(consultant)
    return ok(consultant)
