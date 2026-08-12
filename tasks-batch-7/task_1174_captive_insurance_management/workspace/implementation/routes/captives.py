"""CaptiveEntity routes: CRUD + lifecycle transitions."""
from __future__ import annotations

from flask import Blueprint, request

import db
from clock import now, now_iso
from errors import ApiError
from middleware import require_roles
from response import ok, paginate
from services import constants as C
from services.audit import log
from services.core import (
    adjust_governance,
    body,
    get_captive,
    opt_str,
    parse_dt_field,
    recompute_captive_ledger,
    release_fronting_collateral,
    req_enum,
    req_num,
    req_str,
    stamp_new,
    touch,
    touch_captive,
)

bp = Blueprint("captives", __name__)

ALL_ROLES = (
    "CaptiveManager", "DomicileRegulator", "Underwriter", "Actuary",
    "ClaimsAdjuster", "BoardDirector", "TaxAdvisor",
)

CLAIM_TERMINAL = set(C.CLAIM_TERMINAL_STATES)


def _captive_view(captive: dict) -> dict:
    return captive


@bp.post("/api/captives")
def create_captive():
    user_id, role = require_roles("CaptiveManager")
    data = body()
    name = req_str(data, "captive_name")
    domicile = req_enum(data, "domicile_jurisdiction", C.DOMICILES)
    formation = parse_dt_field(data, "formation_date")
    cap_amount = req_num(data, "capitalization_amount")
    tax_class = data.get("tax_classification")
    if tax_class is None:
        tax_class = "MICRO_CAPTIVE_831B"
    elif tax_class not in C.TAX_CLASSIFICATIONS:
        raise ApiError("ERR_INVALID_REQUEST",
                       f"tax_classification must be one of {C.TAX_CLASSIFICATIONS}")

    captive = stamp_new()
    captive.update({
        "captive_name": name,
        "domicile_jurisdiction": domicile,
        "formation_date": now_iso() if formation is None else _fmt(formation),
        "capitalization_amount": int(cap_amount),
        "capital_minimum_required": C.CAPITAL_MINIMUM_REQUIRED.get(domicile, 0),
        # Born solvent: initial solvency reflects posted capitalization.
        "solvency_ratio": 100.0,
        "solvency_status": "ADEQUATE",
        "admitted_assets": 0,
        "total_reserves_held": 0,
        "total_premium_written": 0,
        "governance_score": C.GOVERNANCE_SCORE_INITIAL,
        "status": "FORMATION_PENDING",
        "tax_classification": tax_class,
        "risk_distribution_score": 0.0,
    })
    db.captives[captive["id"]] = captive
    # NB: no solvency recompute at creation — PRD: born with solvency_status
    # ADEQUATE (initial); recomputation happens on ledger-moving events only.
    log(captive["id"], "STATE_CHANGE", "CaptiveEntity", captive["id"], role,
        user_id, f"Captive entity created in FORMATION_PENDING", None,
        "FORMATION_PENDING")
    return ok(_captive_view(captive), 201)


def _fmt(dt):
    from clock import fmt_ts
    return fmt_ts(dt)


@bp.get("/api/captives")
def list_captives():
    require_roles(*ALL_ROLES)
    items = sorted(db.captives.values(), key=lambda e: e["created_at"])
    page, meta = paginate(items, request.args)
    return ok([_captive_view(c) for c in page], 200, meta)


@bp.get("/api/captives/<captiveId>")
def get_captive_route(captiveId):
    require_roles(*ALL_ROLES)
    return ok(_captive_view(get_captive(captiveId)), 200)


@bp.post("/api/captives/<captiveId>/activate")
def activate_captive(captiveId):
    user_id, role = require_roles("CaptiveManager")
    captive = get_captive(captiveId)
    if captive["status"] != "CAPITALIZED":
        raise ApiError("ERR_CAPTIVE_NOT_CAPITALIZED",
                       "Captive entity must be in CAPITALIZED state")
    bound_states = ("BOUND", "IN_FORCE", "RUN_OFF", "CLOSED")
    has_bound = any(
        p["captive_id"] == captiveId and p["program_status"] in bound_states
        for p in db.programs.values())
    if not has_bound:
        raise ApiError("ERR_NO_BOUND_PROGRAM",
                       "At least one bound program must exist for captive activation")
    if captive.get("solvency_status") == "BREACH":
        raise ApiError("ERR_SOLVENCY_BREACH",
                       "Solvency ratio is below breach threshold")
    prev = captive["status"]
    captive["status"] = "ACTIVE"
    touch_captive(captive)
    log(captiveId, "STATE_CHANGE", "CaptiveEntity", captiveId, role, user_id,
        "Captive activated", prev, "ACTIVE")
    return ok(_captive_view(captive), 200)


@bp.post("/api/captives/<captiveId>/suspend")
def suspend_captive(captiveId):
    user_id, role = require_roles("DomicileRegulator")
    captive = get_captive(captiveId)
    if captive["status"] != "ACTIVE":
        raise ApiError("ERR_CAPTIVE_NOT_ACTIVE",
                       "Captive entity must be in ACTIVE state")
    grounds = (captive.get("solvency_status") == "BREACH"
               or int(captive.get("governance_score", 100)) < C.GOVERNANCE_SCORE_SUSPENSION_FLOOR)
    if not grounds:
        raise ApiError("ERR_NO_SUSPENSION_GROUNDS",
                       "No suspension grounds: solvency breach or governance score below 40 required")
    prev = captive["status"]
    captive["status"] = "SUSPENDED"
    # Cascade: IN_FORCE programs -> RUN_OFF
    for program in db.programs.values():
        if program["captive_id"] == captiveId and program["program_status"] == "IN_FORCE":
            program["program_status"] = "RUN_OFF"
            program["coverage_status"] = "EXPIRED"
            touch(program)
    # Cascade: ACTIVE fronting arrangements -> TERMINATED (release collateral)
    for fronting in db.frontings.values():
        if fronting["captive_id"] == captiveId and fronting["status"] == "ACTIVE":
            fronting["status"] = "TERMINATED"
            release_fronting_collateral(fronting)
            touch(fronting)
    recompute_captive_ledger(captive)
    touch_captive(captive)
    log(captiveId, "STATE_CHANGE", "CaptiveEntity", captiveId, role, user_id,
        "Captive suspended; programs cascaded to RUN_OFF, fronting terminated",
        prev, "SUSPENDED")
    return ok(_captive_view(captive), 200)


@bp.post("/api/captives/<captiveId>/reinstate")
def reinstate_captive(captiveId):
    user_id, role = require_roles("DomicileRegulator")
    captive = get_captive(captiveId)
    if captive["status"] != "SUSPENDED":
        raise ApiError("ERR_CAPTIVE_NOT_SUSPENDED",
                       "Captive entity must be in SUSPENDED state")
    if captive.get("solvency_status") == "BREACH":
        raise ApiError("ERR_SOLVENCY_BREACH",
                       "Solvency ratio is below breach threshold")
    if int(captive.get("governance_score", 100)) < C.GOVERNANCE_SCORE_SUSPENSION_FLOOR:
        raise ApiError("ERR_GOVERNANCE_SCORE_TOO_LOW",
                       "Governance score below minimum threshold for reinstatement")
    prev = captive["status"]
    captive["status"] = "ACTIVE"
    touch_captive(captive)
    log(captiveId, "STATE_CHANGE", "CaptiveEntity", captiveId, role, user_id,
        "Captive reinstated", prev, "ACTIVE")
    return ok(_captive_view(captive), 200)


@bp.post("/api/captives/<captiveId>/dissolve")
def dissolve_captive(captiveId):
    user_id, role = require_roles("CaptiveManager", "DomicileRegulator")
    captive = get_captive(captiveId)
    if captive["status"] == "ACTIVE":
        # CaptiveManager branch: no IN_FORCE/BOUND programs, claims terminal,
        # reserves filed.
        active_programs = [p for p in db.programs.values()
                           if p["captive_id"] == captiveId
                           and p["program_status"] in ("IN_FORCE", "BOUND")]
        if active_programs:
            raise ApiError("ERR_ACTIVE_PROGRAMS_EXIST",
                           "Active programs exist; cannot dissolve captive")
        open_claims = [c for c in db.claims.values()
                       if c["captive_id"] == captiveId
                       and c["claim_status"] not in CLAIM_TERMINAL]
        if open_claims:
            raise ApiError("ERR_OPEN_CLAIMS_EXIST",
                           "Open claims exist; cannot dissolve captive")
        unfiled = [r for r in db.reserves.values()
                   if r["captive_id"] == captiveId and r["status"] != "FILED"]
        if unfiled:
            raise ApiError("ERR_UNFILED_RESERVES_EXIST",
                           "Unfiled reserves exist; cannot dissolve captive")
    elif captive["status"] == "SUSPENDED":
        # DomicileRegulator branch: all claims terminal.
        open_claims = [c for c in db.claims.values()
                       if c["captive_id"] == captiveId
                       and c["claim_status"] not in CLAIM_TERMINAL]
        if open_claims:
            raise ApiError("ERR_OPEN_CLAIMS_EXIST",
                           "Open claims exist; cannot dissolve captive")
    else:
        # Not ACTIVE or SUSPENDED: no valid dissolution branch.
        raise ApiError("ERR_CAPTIVE_NOT_ACTIVE",
                       "Captive entity must be in ACTIVE or SUSPENDED state to dissolve")

    prev = captive["status"]
    captive["status"] = "DISSOLVED"
    # Cascade: remaining programs -> CLOSED
    for program in db.programs.values():
        if program["captive_id"] == captiveId and program["program_status"] not in (
                "CLOSED", "CANCELLED"):
            program["program_status"] = "CLOSED"
            program["coverage_status"] = "EXPIRED"
            touch(program)
    # Cascade: all collateral postings -> RELEASED
    for col in db.collaterals.values():
        if col["captive_id"] == captiveId and col["verification_status"] != "RELEASED":
            col["verification_status"] = "RELEASED"
            touch(col)
    recompute_captive_ledger(captive)
    touch_captive(captive)
    log(captiveId, "STATE_CHANGE", "CaptiveEntity", captiveId, role, user_id,
        "Captive dissolved; programs closed, collateral released", prev,
        "DISSOLVED")
    return ok(_captive_view(captive), 200)
