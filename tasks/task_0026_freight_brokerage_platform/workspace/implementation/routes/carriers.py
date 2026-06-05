"""Carrier endpoints (PRD §3.1)."""
from __future__ import annotations

import re
from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_MC_USDOT,
    ERR_INVALID_STATE,
    ERR_SAFETY_SCORE_TOO_HIGH,
    ERR_INSURANCE_EXPIRED,
    ERR_UNAUTHORIZED,
)
from middleware import require_auth, get_json_body, current_role, current_user_id
from response import ok_object, ok_array, paginate_params, slice_page, sort_default
from services.validation import (
    require_fields,
    require_string,
    require_enum,
    require_number,
    lookup_path_or_404,
    parse_iso_or_400,
    current_utc_dt,
)
from services.calculations import SAFETY_REJECT_THRESHOLD


bp = Blueprint("carriers", __name__)


MC_RE = re.compile(r"^[0-9]{6,7}$")
USDOT_RE = re.compile(r"^[0-9]{5,8}$")
SMARTWAY_TIERS = {"NONE", "BRONZE", "SILVER", "GOLD"}
REJECTION_REASONS = {"BAD_MC", "BAD_USDOT", "INSURANCE_EXPIRED", "SAFETY_OVER_THRESHOLD"}


@bp.post("/freight/carriers")
def create_carrier():
    require_auth(["BrokerOps"])()
    body = get_json_body()
    require_fields(body, ["legal_name", "mc_number", "usdot_number", "insurance_expiry_utc", "safety_score"])
    require_string(body["legal_name"], "legal_name")
    mc = body["mc_number"]
    dot = body["usdot_number"]
    if not isinstance(mc, str) or not MC_RE.match(mc):
        raise APIError(ERR_INVALID_MC_USDOT, 422, "mc_number must be 6 or 7 digits")
    if not isinstance(dot, str) or not USDOT_RE.match(dot):
        raise APIError(ERR_INVALID_MC_USDOT, 422, "usdot_number must be 5 to 8 digits")
    # Uniqueness across Carrier rows.
    for c in db.carriers.values():
        if c.get("mc_number") == mc:
            raise APIError(ERR_INVALID_MC_USDOT, 422, "mc_number is not unique")
        if c.get("usdot_number") == dot:
            raise APIError(ERR_INVALID_MC_USDOT, 422, "usdot_number is not unique")

    smartway_tier = body.get("smartway_tier", "NONE")
    if smartway_tier is None:
        smartway_tier = "NONE"
    require_enum(smartway_tier, SMARTWAY_TIERS, "smartway_tier")

    expiry = parse_iso_or_400(body["insurance_expiry_utc"], "insurance_expiry_utc")
    safety = require_number(body["safety_score"], "safety_score")
    if safety < 0.0 or safety > 100.0:
        raise APIError(ERR_INVALID_REQUEST, 400, "safety_score must be in [0.0, 100.0]")

    carrier = {
        "legal_name": body["legal_name"],
        "mc_number": mc,
        "usdot_number": dot,
        "smartway_tier": smartway_tier,
        "insurance_expiry_utc": body["insurance_expiry_utc"],
        "qualification_status": "PENDING",
        "safety_score": safety,
        "rejection_reason_code": None,
    }
    db.stamp_common(carrier)
    db.carriers[carrier["id"]] = carrier
    return ok_object(carrier, 201)


@bp.get("/freight/carriers/<cid>")
def get_carrier(cid: str):
    require_auth(["BrokerOps", "Carrier"])()
    carrier = lookup_path_or_404(db.carriers, cid, "Carrier")
    if current_role() == "Carrier" and current_user_id() != cid:
        raise APIError(ERR_UNAUTHORIZED, 403, "Carrier may only view own record")
    return ok_object(carrier, 200)


@bp.get("/freight/carriers")
def list_carriers():
    require_auth(["BrokerOps"])()
    limit, offset = paginate_params(request.args)
    qstatus = request.args.get("qualification_status")
    items = list(db.carriers.values())
    if qstatus:
        items = [c for c in items if c.get("qualification_status") == qstatus]
    items = sort_default(items)
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total, 200)


@bp.post("/freight/carriers/<cid>/qualify")
def qualify_carrier(cid: str):
    require_auth(["BrokerOps"])()
    carrier = lookup_path_or_404(db.carriers, cid, "Carrier")
    # State check
    if carrier.get("qualification_status") != "PENDING":
        raise APIError(ERR_INVALID_STATE, 409, "Carrier must be PENDING to qualify")
    # mc/usdot regex still match (priority above safety/insurance per scaffold)
    if not MC_RE.match(carrier.get("mc_number", "")):
        raise APIError(ERR_INVALID_MC_USDOT, 422, "mc_number invalid")
    if not USDOT_RE.match(carrier.get("usdot_number", "")):
        raise APIError(ERR_INVALID_MC_USDOT, 422, "usdot_number invalid")
    # priority 7: safety score
    if float(carrier.get("safety_score", 0.0)) >= float(SAFETY_REJECT_THRESHOLD):
        raise APIError(ERR_SAFETY_SCORE_TOO_HIGH, 422, "safety_score >= 75.0")
    # priority 8: insurance expiry
    expiry = db.parse_iso_dt(carrier.get("insurance_expiry_utc"))
    if expiry is None or expiry <= current_utc_dt():
        raise APIError(ERR_INSURANCE_EXPIRED, 422, "Insurance expired or missing")

    carrier["qualification_status"] = "QUALIFIED"
    db.bump(carrier)
    return ok_object(carrier, 200)


@bp.post("/freight/carriers/<cid>/reject")
def reject_carrier(cid: str):
    require_auth(["BrokerOps"])()
    carrier = lookup_path_or_404(db.carriers, cid, "Carrier")
    if carrier.get("qualification_status") != "PENDING":
        raise APIError(ERR_INVALID_STATE, 409, "Carrier must be PENDING to reject")
    body = get_json_body()
    require_fields(body, ["reason_code"])
    require_enum(body["reason_code"], REJECTION_REASONS, "reason_code")

    carrier["qualification_status"] = "REJECTED"
    carrier["rejection_reason_code"] = body["reason_code"]
    db.bump(carrier)
    return ok_object(carrier, 200)


@bp.post("/freight/carriers/<cid>/suspend")
def suspend_carrier(cid: str):
    require_auth(["BrokerOps"])()
    carrier = lookup_path_or_404(db.carriers, cid, "Carrier")
    if carrier.get("qualification_status") != "QUALIFIED":
        raise APIError(ERR_INVALID_STATE, 409, "Carrier must be QUALIFIED to suspend")
    carrier["qualification_status"] = "SUSPENDED"
    db.bump(carrier)
    return ok_object(carrier, 200)


@bp.post("/freight/carriers/<cid>/reinstate")
def reinstate_carrier(cid: str):
    require_auth(["BrokerOps"])()
    carrier = lookup_path_or_404(db.carriers, cid, "Carrier")
    if carrier.get("qualification_status") != "SUSPENDED":
        raise APIError(ERR_INVALID_STATE, 409, "Carrier must be SUSPENDED to reinstate")
    expiry = db.parse_iso_dt(carrier.get("insurance_expiry_utc"))
    if expiry is None or expiry <= current_utc_dt():
        raise APIError(ERR_INSURANCE_EXPIRED, 422, "Insurance expired or missing")
    carrier["qualification_status"] = "QUALIFIED"
    db.bump(carrier)
    return ok_object(carrier, 200)
