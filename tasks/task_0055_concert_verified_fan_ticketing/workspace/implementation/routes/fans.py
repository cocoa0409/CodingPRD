"""Fan routes (PRD §3.1)."""
from __future__ import annotations

from flask import Blueprint, request, g

import db
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_NOT_RESOURCE_OWNER,
    ERR_INVALID_STATE,
    ERR_FAN_FLAGGED,
)
from middleware import require_auth, get_json_body
from response import ok_object, ok_array, paginate_params, slice_page
from services.common import get_or_404, require_str, sorted_by_creation
from services import calculations

bp = Blueprint("fans", __name__)


@bp.post("/fans")
def register_fan():
    require_auth(["Anonymous"])()
    body = get_json_body()
    email = require_str(body, "email")
    full_name = require_str(body, "full_name")
    device_fingerprint = require_str(body, "device_fingerprint")

    # email unique across all fans
    for other in db.fans.values():
        if other.get("email") == email:
            raise APIError(ERR_INVALID_REQUEST, 400, "email must be unique")

    fan = db.stamp_common(
        {
            "email": email,
            "full_name": full_name,
            "device_fingerprint": device_fingerprint,
            "risk_score": 0,
            "verification_status": "UNVERIFIED",
            "completed_purchase_count": 0,
        }
    )
    db.fans[fan["id"]] = fan
    fan["risk_score"] = calculations.bot_risk_score(fan)
    return ok_object(fan, 201)


@bp.post("/fans/<fid>/verify")
def verify_fan(fid):
    require_auth(["Fan"])()
    fan = get_or_404(db.fans, fid, "Fan")

    # ownership: acting Fan must be this fan
    if g.user_id != fan["id"]:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Not the owner of this fan")

    # state gate: verify is only defined from UNVERIFIED
    if fan["verification_status"] != "UNVERIFIED":
        # FLAGGED is caught by the flag bar at priority 6, but per PRD §3.1 a
        # verify from any non-UNVERIFIED status is ERR_INVALID_STATE. FLAGGED is
        # also a non-UNVERIFIED state; priority 5 (state) precedes priority 6
        # (flag bar) per PRD §2.9, so report ERR_INVALID_STATE here.
        raise APIError(ERR_INVALID_STATE, 409, "Verify only valid from UNVERIFIED")

    if fan["risk_score"] >= calculations.BOT_FLAG_THRESHOLD:
        fan["verification_status"] = "FLAGGED"
    else:
        fan["verification_status"] = "VERIFIED"
    db.bump(fan)
    return ok_object(fan, 200)


@bp.get("/fans/<fid>")
def get_fan(fid):
    require_auth(["Anonymous", "Fan", "PromoterAdmin"])()
    fan = get_or_404(db.fans, fid, "Fan")
    return ok_object(fan, 200)


@bp.get("/fans")
def list_fans():
    require_auth(["PromoterAdmin"])()
    limit, offset = paginate_params(request.args)
    email = request.args.get("email")
    vstatus = request.args.get("verification_status")

    items = list(db.fans.values())
    if email is not None:
        items = [f for f in items if f.get("email") == email]
    if vstatus is not None:
        items = [f for f in items if f.get("verification_status") == vstatus]
    items = sorted_by_creation(items)
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total)
