"""KeyHandoff routes."""
from __future__ import annotations

from flask import Blueprint, request

import db
import response
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_KEY_HANDOFF_EXISTS,
)
from middleware import require_auth
from services.common import (
    bump,
    get_json_body,
    new_common_fields,
    optional_str,
    paginate,
    parse_pagination,
    require_enum,
    require_str,
    sorted_by_created_at,
)
from services.lookup import (
    fk_booking,
    get_key_handoff_or_404,
    key_handoff_for_booking,
)

bp = Blueprint("key_handoffs", __name__)


_METHODS = {"LOCKBOX", "IN_PERSON", "SMART_LOCK"}
_STATUSES = {"PENDING", "RECEIVED", "RETURNED", "LOST"}


def kh_to_dict(k: dict) -> dict:
    return {
        "id": k["id"],
        "booking_id": k["booking_id"],
        "method": k["method"],
        "status": k["status"],
        "lockbox_code": k["lockbox_code"],
        "received_at": k["received_at"],
        "created_at": k["created_at"],
        "updated_at": k["updated_at"],
        "version": k["version"],
    }


@bp.post("/api/v1/key-handoffs")
@require_auth(roles=["Owner"])
def create_kh():
    body = get_json_body()
    booking_id = require_str(body, "booking_id")
    method = require_enum(body, "method", _METHODS)
    lockbox_code = None
    if method == "LOCKBOX":
        if "lockbox_code" in body and body["lockbox_code"] is not None:
            if not isinstance(body["lockbox_code"], str):
                raise ApiError(ERR_INVALID_REQUEST, "lockbox_code must be a string.")
            lockbox_code = body["lockbox_code"]
    else:
        if "lockbox_code" in body and body["lockbox_code"] is not None:
            # PRD says null otherwise; we silently ignore (the field would be null)
            lockbox_code = None

    booking = fk_booking(booking_id)
    # Must be CONFIRMED
    if booking["status"] != "CONFIRMED":
        raise ApiError(ERR_INVALID_STATE, "Booking must be CONFIRMED to create a KeyHandoff.")
    if key_handoff_for_booking(booking_id) is not None:
        raise ApiError(ERR_KEY_HANDOFF_EXISTS, "A KeyHandoff already exists for this Booking.")

    with db.lock:
        kh = {
            **new_common_fields(),
            "booking_id": booking_id,
            "method": method,
            "status": "PENDING",
            "lockbox_code": lockbox_code,
            "received_at": None,
        }
        db.key_handoffs[kh["id"]] = kh
    return response.ok(kh_to_dict(kh), status=201)


@bp.get("/api/v1/key-handoffs/<kid>")
@require_auth(roles=["Owner", "Sitter", "PlatformAdmin"])
def get_kh(kid: str):
    k = get_key_handoff_or_404(kid)
    return response.ok(kh_to_dict(k))


@bp.get("/api/v1/key-handoffs")
@require_auth(roles=["Owner", "Sitter", "PlatformAdmin"])
def list_kh():
    limit, offset = parse_pagination()
    booking_id = request.args.get("booking_id")
    status_filter = request.args.get("status")

    items = list(db.key_handoffs.values())
    if booking_id is not None:
        items = [k for k in items if k["booking_id"] == booking_id]
    if status_filter is not None:
        if status_filter not in _STATUSES:
            raise ApiError(ERR_INVALID_REQUEST, f"Invalid status filter: {status_filter}")
        items = [k for k in items if k["status"] == status_filter]
    items = sorted_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return response.list_ok([kh_to_dict(k) for k in page], limit, offset, total)


@bp.post("/api/v1/key-handoffs/<kid>/receive")
@require_auth(roles=["Sitter"])
def receive_kh(kid: str):
    kh = get_key_handoff_or_404(kid)
    if kh["status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE, "KeyHandoff must be PENDING to receive.")
    booking = db.bookings.get(kh["booking_id"])
    if booking is None or booking["status"] != "CONFIRMED":
        raise ApiError(ERR_INVALID_STATE, "Associated Booking must be CONFIRMED.")
    with db.lock:
        kh["status"] = "RECEIVED"
        kh["received_at"] = db.fmt_ts(db.utcnow())
        bump(kh)
        booking["status"] = "KEY_RECEIVED"
        bump(booking)
    return response.ok(kh_to_dict(kh))
