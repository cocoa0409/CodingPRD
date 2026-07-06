"""Creator endpoints."""
from flask import Blueprint, request

import db
from clock import clock
from errors import raise_error
from middleware import require_auth, open_endpoint, current_user_id, current_role
from response import ok, created
from services.serialize import serialize

bp = Blueprint("creators", __name__)


def _get_creator_or_404(_id):
    row = db.creators.get(_id)
    if not row:
        raise_error("ERR_NOT_FOUND", f"creator {_id} not found")
    return row


@bp.post("/pod/creators/register")
@open_endpoint(["Anonymous", "Creator", "PlatformAdmin", "FulfillmentPartner"])
def register():
    body = request.get_json(silent=True) or {}
    for field in ("email", "display_name", "payout_country_code"):
        if not isinstance(body.get(field), str) or not body[field]:
            raise_error("ERR_INVALID_REQUEST", f"missing/invalid {field}")
    email = body["email"]
    # Uniqueness check on email.
    for c in db.creators.all():
        if c["email"] == email:
            raise_error("ERR_INVALID_REQUEST", "email already registered")

    row = db.new_common_fields()
    row.update(
        {
            "email": email,
            "display_name": body["display_name"],
            "payout_country_code": body["payout_country_code"],
            "payout_wallet_cents": 0,
            "verification_status": "UNVERIFIED",
            "default_payout_fee_bps": 250,
            "reprint_strike_count": 0,
        }
    )
    db.creators.insert(row)
    return created(serialize(row))


@bp.get("/pod/creators/<cid>")
@require_auth(["Creator", "PlatformAdmin"])
def read_creator(cid):
    row = _get_creator_or_404(cid)
    return ok(serialize(row))


@bp.post("/pod/creators/<cid>/verify")
@require_auth(["PlatformAdmin"])
def verify_creator(cid):
    row = _get_creator_or_404(cid)
    body = request.get_json(silent=True) or {}
    outcome = body.get("outcome")
    if outcome not in ("VERIFIED", "REJECTED", "PENDING"):
        raise_error("ERR_INVALID_REQUEST", "outcome must be VERIFIED, REJECTED, or PENDING")
    row["verification_status"] = outcome
    db.bump(row)
    return ok(serialize(row))
