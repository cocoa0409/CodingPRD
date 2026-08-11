"""FrontingArrangement routes."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import ApiError
from middleware import require_roles
from response import ok, paginate
from services import constants as C
from services.audit import log
from services.core import (
    body,
    compute_collateral_required,
    get_captive,
    get_fronting,
    get_program,
    recompute_captive_ledger,
    recompute_fronting_collateral,
    recompute_fronting_fee,
    release_fronting_collateral,
    req_num,
    req_str,
    stamp_new,
    touch,
)

bp = Blueprint("fronting", __name__)

READ_ROLES = ("CaptiveManager", "Underwriter")


@bp.post("/api/captives/<captiveId>/programs/<programId>/fronting")
def create_fronting(captiveId, programId):
    user_id, role = require_roles("Underwriter")
    captive = get_captive(captiveId)
    program = get_program(captive, programId)
    data = body()
    carrier = req_str(data, "fronting_carrier_name")
    fee_pct = req_num(data, "fronting_fee_pct")
    if fee_pct < C.FRONTING_FEE_MIN or fee_pct > C.FRONTING_FEE_MAX:
        raise ApiError("ERR_INVALID_REQUEST",
                       "fronting_fee_pct must be between 0.01 and 0.15")
    ceded = req_num(data, "reinsurance_ceded_pct")
    if ceded < 0.0 or ceded > 1.0:
        raise ApiError("ERR_INVALID_REQUEST",
                       "reinsurance_ceded_pct must be between 0.0 and 1.0")

    fronting = stamp_new()
    fronting.update({
        "program_id": programId,
        "captive_id": captiveId,
        "fronting_carrier_name": carrier,
        "fronting_fee_pct": fee_pct,
        "collateral_required_cents": 0,
        "collateral_posted_cents": 0,
        "collateral_shortfall_cents": 0,
        "reinsurance_ceded_pct": ceded,
        "fronting_fee_amount_cents": 0,
        "status": "NEGOTIATING",
    })
    db.frontings[fronting["id"]] = fronting
    log(captiveId, "STATE_CHANGE", "FrontingArrangement", fronting["id"], role,
        user_id, "Fronting arrangement created in NEGOTIATING", None,
        "NEGOTIATING")
    return ok(fronting, 201)


@bp.get("/api/captives/<captiveId>/programs/<programId>/fronting")
def list_fronting(captiveId, programId):
    require_roles(*READ_ROLES)
    captive = get_captive(captiveId)
    get_program(captive, programId)
    items = sorted(
        [f for f in db.frontings.values() if f["program_id"] == programId],
        key=lambda e: e["created_at"])
    page, meta = paginate(items, request.args)
    return ok(page, 200, meta)


@bp.get("/api/captives/<captiveId>/programs/<programId>/fronting/<frontingId>")
def get_fronting_route(captiveId, programId, frontingId):
    require_roles(*READ_ROLES)
    captive = get_captive(captiveId)
    program = get_program(captive, programId)
    return ok(get_fronting(program, frontingId), 200)


@bp.post("/api/captives/<captiveId>/programs/<programId>/fronting/<frontingId>/agree-terms")
def agree_terms(captiveId, programId, frontingId):
    user_id, role = require_roles("Underwriter")
    captive = get_captive(captiveId)
    program = get_program(captive, programId)
    fronting = get_fronting(program, frontingId)
    if fronting["status"] != "NEGOTIATING":
        raise ApiError("ERR_FRONTING_NOT_NEGOTIATING",
                       "Fronting arrangement must be in NEGOTIATING state")
    prev = fronting["status"]
    fronting["status"] = "TERMS_AGREED"
    fronting["collateral_required_cents"] = compute_collateral_required(
        program, fronting)
    recompute_fronting_collateral(fronting)
    touch(fronting)
    log(captiveId, "STATE_CHANGE", "FrontingArrangement", frontingId, role,
        user_id, "Fronting terms agreed; collateral requirement computed",
        prev, "TERMS_AGREED")
    return ok(fronting, 200)


@bp.post("/api/captives/<captiveId>/programs/<programId>/fronting/<frontingId>/post-collateral")
def post_collateral(captiveId, programId, frontingId):
    user_id, role = require_roles("CaptiveManager")
    captive = get_captive(captiveId)
    program = get_program(captive, programId)
    fronting = get_fronting(program, frontingId)
    if fronting["status"] != "TERMS_AGREED":
        raise ApiError("ERR_FRONTING_NOT_TERMS_AGREED",
                       "Fronting arrangement must be in TERMS_AGREED state")
    recompute_fronting_collateral(fronting)
    if int(fronting["collateral_posted_cents"]) < int(
            fronting["collateral_required_cents"]):
        raise ApiError("ERR_INSUFFICIENT_COLLATERAL",
                       "Collateral posted is less than collateral required by fronting carrier")
    prev = fronting["status"]
    fronting["status"] = "COLLATERAL_POSTED"
    touch(fronting)
    recompute_captive_ledger(captive)  # admitted_assets ledger sync
    log(captiveId, "STATE_CHANGE", "FrontingArrangement", frontingId, role,
        user_id, "Collateral posted against fronting arrangement", prev,
        "COLLATERAL_POSTED")
    return ok(fronting, 200)


@bp.post("/api/captives/<captiveId>/programs/<programId>/fronting/<frontingId>/activate")
def activate_fronting(captiveId, programId, frontingId):
    user_id, role = require_roles("Underwriter")
    captive = get_captive(captiveId)
    program = get_program(captive, programId)
    fronting = get_fronting(program, frontingId)
    if fronting["status"] != "COLLATERAL_POSTED":
        raise ApiError("ERR_FRONTING_NOT_COLLATERAL_POSTED",
                       "Fronting arrangement must be in COLLATERAL_POSTED state")
    if program["program_status"] != "BOUND":
        raise ApiError("ERR_PROGRAM_NOT_BOUND",
                       "Program must be in BOUND state")
    prev = fronting["status"]
    fronting["status"] = "ACTIVE"
    recompute_fronting_fee(fronting)
    touch(fronting)
    recompute_captive_ledger(captive)
    log(captiveId, "STATE_CHANGE", "FrontingArrangement", frontingId, role,
        user_id, "Fronting arrangement activated; fronting fee computed", prev,
        "ACTIVE")
    return ok(fronting, 200)


@bp.post("/api/captives/<captiveId>/programs/<programId>/fronting/<frontingId>/terminate")
def terminate_fronting(captiveId, programId, frontingId):
    user_id, role = require_roles("Underwriter")
    captive = get_captive(captiveId)
    program = get_program(captive, programId)
    fronting = get_fronting(program, frontingId)
    if fronting["status"] != "ACTIVE":
        raise ApiError("ERR_FRONTING_NOT_ACTIVE",
                       "Fronting arrangement must be in ACTIVE state")
    prev = fronting["status"]
    fronting["status"] = "TERMINATED"
    release_fronting_collateral(fronting)
    touch(fronting)
    # Revert the program to BOUND if it has not yet reached IN_FORCE.
    if program["program_status"] not in ("IN_FORCE", "RUN_OFF", "CLOSED",
                                         "CANCELLED"):
        program["program_status"] = "BOUND"
        touch(program)
    recompute_captive_ledger(captive)
    log(captiveId, "STATE_CHANGE", "FrontingArrangement", frontingId, role,
        user_id, "Fronting arrangement terminated; collateral released", prev,
        "TERMINATED")
    return ok(fronting, 200)
