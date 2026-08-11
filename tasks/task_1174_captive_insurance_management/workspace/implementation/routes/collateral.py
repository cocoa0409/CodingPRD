"""CollateralPosting routes."""
from __future__ import annotations

from flask import Blueprint, request

import db
from clock import fmt_ts
from errors import ApiError
from middleware import require_roles
from response import ok, paginate
from services import constants as C
from services.audit import log
from services.core import (
    body,
    collateral_effective_value,
    collateral_haircut,
    get_captive,
    get_collateral,
    get_fronting,
    get_program,
    parse_dt_field,
    recompute_captive_ledger,
    recompute_fronting_collateral,
    req_enum,
    req_num,
    req_str,
    stamp_new,
    touch,
)

bp = Blueprint("collateral", __name__)

READ_ROLES = ("CaptiveManager", "Underwriter")


def _chain(captiveId, programId, frontingId):
    captive = get_captive(captiveId)
    program = get_program(captive, programId)
    fronting = get_fronting(program, frontingId)
    return captive, program, fronting


@bp.post("/api/captives/<captiveId>/programs/<programId>/fronting/<frontingId>/collateral")
def create_collateral(captiveId, programId, frontingId):
    user_id, role = require_roles("CaptiveManager")
    captive, program, fronting = _chain(captiveId, programId, frontingId)
    data = body()
    ctype = req_enum(data, "collateral_type", C.COLLATERAL_TYPES)
    amount = req_num(data, "amount_cents")
    posted = parse_dt_field(data, "posted_date")
    expiry = parse_dt_field(data, "expiry_date")
    if expiry <= posted:
        raise ApiError("ERR_INVALID_COLLATERAL_DATES",
                       "Collateral expiry date must be after posted date")
    institution = req_str(data, "issuing_institution")

    haircut = collateral_haircut(captive, ctype)
    effective = collateral_effective_value(captive, ctype, amount)

    col = stamp_new()
    col.update({
        "fronting_arrangement_id": frontingId,
        "program_id": programId,
        "captive_id": captiveId,
        "collateral_type": ctype,
        "amount_cents": int(amount),
        "posted_date": fmt_ts(posted),
        "expiry_date": fmt_ts(expiry),
        "issuing_institution": institution,
        "verification_status": "PENDING_VERIFICATION",
        "haircut_pct": haircut,
        "effective_value_cents": effective,
    })
    db.collaterals[col["id"]] = col
    log(captiveId, "STATE_CHANGE", "CollateralPosting", col["id"], role,
        user_id, "Collateral posting created pending verification", None,
        "PENDING_VERIFICATION")
    return ok(col, 201)


@bp.get("/api/captives/<captiveId>/programs/<programId>/fronting/<frontingId>/collateral")
def list_collateral(captiveId, programId, frontingId):
    require_roles(*READ_ROLES)
    _chain(captiveId, programId, frontingId)
    items = sorted(
        [c for c in db.collaterals.values()
         if c["fronting_arrangement_id"] == frontingId],
        key=lambda e: e["created_at"])
    page, meta = paginate(items, request.args)
    return ok(page, 200, meta)


@bp.get("/api/captives/<captiveId>/programs/<programId>/fronting/<frontingId>/collateral/<collateralId>")
def get_collateral_route(captiveId, programId, frontingId, collateralId):
    require_roles(*READ_ROLES)
    _, _, fronting = _chain(captiveId, programId, frontingId)
    return ok(get_collateral(fronting, collateralId), 200)


@bp.post("/api/captives/<captiveId>/programs/<programId>/fronting/<frontingId>/collateral/<collateralId>/verify")
def verify_collateral(captiveId, programId, frontingId, collateralId):
    user_id, role = require_roles("CaptiveManager")
    captive, _, fronting = _chain(captiveId, programId, frontingId)
    col = get_collateral(fronting, collateralId)
    prev = col["verification_status"]
    col["verification_status"] = "VERIFIED"
    touch(col)
    recompute_fronting_collateral(fronting)
    touch(fronting)
    recompute_captive_ledger(captive)
    log(captiveId, "STATE_CHANGE", "CollateralPosting", collateralId, role,
        user_id, "Collateral posting verified", prev, "VERIFIED")
    return ok(col, 200)
