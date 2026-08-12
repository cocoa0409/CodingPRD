"""TPAAssignment routes."""
from __future__ import annotations

from flask import Blueprint, request

import db
from clock import now_iso
from errors import ApiError
from middleware import require_roles
from response import ok, paginate
from services import constants as C
from services.audit import log
from services.core import (
    body,
    get_captive,
    get_claim,
    get_program,
    get_tpa,
    req_enum,
    req_num,
    req_str,
    stamp_new,
    touch,
)

bp = Blueprint("tpa", __name__)

READ_ROLES = ("CaptiveManager", "ClaimsAdjuster")


def _chain(captiveId, programId, claimId):
    captive = get_captive(captiveId)
    program = get_program(captive, programId)
    claim = get_claim(program, claimId)
    return captive, program, claim


@bp.post("/api/captives/<captiveId>/programs/<programId>/claims/<claimId>/tpa")
def create_tpa(captiveId, programId, claimId):
    user_id, role = require_roles("CaptiveManager")
    captive, program, claim = _chain(captiveId, programId, claimId)
    data = body()
    firm = req_str(data, "tpa_firm_name")
    email = req_str(data, "tpa_contact_email")
    authority = req_num(data, "authority_limit_cents")
    fee_structure = req_enum(data, "fee_structure", C.FEE_STRUCTURES)
    fee_amount = req_num(data, "fee_amount_cents")

    tpa = stamp_new()
    tpa.update({
        "claim_id": claimId,
        "tpa_firm_name": firm,
        "tpa_contact_email": email,
        "assignment_date": now_iso(),
        "authority_limit_cents": int(authority),
        "fee_structure": fee_structure,
        "fee_amount_cents": int(fee_amount),
        "performance_score": 100,
        "sla_compliance_pct": 100.0,
        "status": "ACTIVE",
    })
    db.tpas[tpa["id"]] = tpa
    claim["tpa_assigned_id"] = tpa["id"]
    touch(claim)
    log(captiveId, "STATE_CHANGE", "TPAAssignment", tpa["id"], role, user_id,
        "TPA assigned to claim", None, "ACTIVE")
    return ok(tpa, 201)


@bp.get("/api/captives/<captiveId>/programs/<programId>/claims/<claimId>/tpa")
def list_tpas(captiveId, programId, claimId):
    require_roles(*READ_ROLES)
    _chain(captiveId, programId, claimId)
    items = sorted(
        [t for t in db.tpas.values() if t["claim_id"] == claimId],
        key=lambda e: e["created_at"])
    page, meta = paginate(items, request.args)
    return ok(page, 200, meta)


@bp.get("/api/captives/<captiveId>/programs/<programId>/claims/<claimId>/tpa/<tpaId>")
def get_tpa_route(captiveId, programId, claimId, tpaId):
    require_roles(*READ_ROLES)
    _, _, claim = _chain(captiveId, programId, claimId)
    return ok(get_tpa(claim, tpaId), 200)


@bp.post("/api/captives/<captiveId>/programs/<programId>/claims/<claimId>/tpa/<tpaId>/suspend")
def suspend_tpa(captiveId, programId, claimId, tpaId):
    user_id, role = require_roles("CaptiveManager")
    _, _, claim = _chain(captiveId, programId, claimId)
    tpa = get_tpa(claim, tpaId)
    if tpa["status"] != "ACTIVE":
        raise ApiError("ERR_TPA_NOT_ACTIVE",
                       "TPA assignment must be in ACTIVE state")
    grounds = (float(tpa.get("performance_score", 100)) < C.TPA_SUSPENSION_PERFORMANCE_SCORE
               or float(tpa.get("sla_compliance_pct", 100)) < C.TPA_SUSPENSION_SLA_PCT)
    if not grounds:
        raise ApiError("ERR_NO_SUSPENSION_GROUNDS",
                       "TPA performance does not meet suspension criteria")
    prev = tpa["status"]
    tpa["status"] = "SUSPENDED"
    touch(tpa)
    log(captiveId, "STATE_CHANGE", "TPAAssignment", tpaId, role, user_id,
        "TPA suspended; claim flagged for reassignment review", prev,
        "SUSPENDED")
    return ok(tpa, 200)


@bp.post("/api/captives/<captiveId>/programs/<programId>/claims/<claimId>/tpa/<tpaId>/reinstate")
def reinstate_tpa(captiveId, programId, claimId, tpaId):
    user_id, role = require_roles("CaptiveManager")
    _, _, claim = _chain(captiveId, programId, claimId)
    tpa = get_tpa(claim, tpaId)
    if tpa["status"] != "SUSPENDED":
        raise ApiError("ERR_TPA_NOT_SUSPENDED",
                       "TPA assignment must be in SUSPENDED state")
    prev = tpa["status"]
    tpa["status"] = "ACTIVE"
    touch(tpa)
    log(captiveId, "STATE_CHANGE", "TPAAssignment", tpaId, role, user_id,
        "TPA reinstated", prev, "ACTIVE")
    return ok(tpa, 200)


@bp.post("/api/captives/<captiveId>/programs/<programId>/claims/<claimId>/tpa/<tpaId>/terminate")
def terminate_tpa(captiveId, programId, claimId, tpaId):
    user_id, role = require_roles("CaptiveManager")
    _, _, claim = _chain(captiveId, programId, claimId)
    tpa = get_tpa(claim, tpaId)
    if tpa["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_TPA_NOT_TERMINABLE",
                       "TPA assignment must be in ACTIVE or SUSPENDED state")
    prev = tpa["status"]
    tpa["status"] = "TERMINATED"
    touch(tpa)
    if claim.get("tpa_assigned_id") == tpaId:
        claim["tpa_assigned_id"] = None
        touch(claim)
    log(captiveId, "STATE_CHANGE", "TPAAssignment", tpaId, role, user_id,
        "TPA terminated; claim requires new TPA assignment", prev,
        "TERMINATED")
    return ok(tpa, 200)
