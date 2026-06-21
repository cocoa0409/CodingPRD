"""IMEOrder endpoints (PRD §3.9). Window-conflict on create; SoD on complete."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_INVALID_STATE,
    ERR_IME_WINDOW_CONFLICT,
    ERR_SEGREGATION_OF_DUTIES,
)
from middleware import require_auth, get_json_body, current_user_id
from response import ok_object, ok_array, paginate_params, sort_and_page
from services.validation import require_str, require_datetime
from services import reserve as reserve_svc
from routes._common import get_claim, get_ime_order

bp = Blueprint("ime_orders", __name__)

NON_TERMINAL_IME = {"SCHEDULED"}


def _reserve_set_by(claim_id: str):
    r = reserve_svc.reserve_for_claim(claim_id)
    return r.get("reserve_set_by") if r else None


@bp.post("/ime-orders")
def create_ime_order():
    require_auth(["ClaimsAdjuster"])()
    body = get_json_body()

    claim_id = require_str(body, "claim_id")
    get_claim(claim_id)

    start_dt = require_datetime(body, "scheduled_start")
    end_dt = require_datetime(body, "scheduled_end")
    examiner_name = require_str(body, "examiner_name")

    # Window conflict (priority 10): no overlap with a non-terminal IME for the
    # same claim (half-open intervals; touching endpoints do not overlap).
    for other in db.ime_orders.values():
        if other["claim_id"] != claim_id or other["status"] not in NON_TERMINAL_IME:
            continue
        o_start = db.parse_iso_dt(other["scheduled_start"])
        o_end = db.parse_iso_dt(other["scheduled_end"])
        if start_dt < o_end and o_start < end_dt:
            raise APIError(ERR_IME_WINDOW_CONFLICT, 409,
                           "IME window overlaps another non-terminal IME for this claim")

    ime = {
        "claim_id": claim_id,
        "scheduled_start": body["scheduled_start"],
        "scheduled_end": body["scheduled_end"],
        "examiner_name": examiner_name,
        "status": "SCHEDULED",
    }
    db.stamp_common(ime)
    db.ime_orders[ime["id"]] = ime
    return ok_object(ime, 201)


@bp.get("/ime-orders/<rid>")
def get_ime_order_route(rid):
    require_auth(["PlatformAdmin", "ClaimsAdjuster", "MedicalReviewer"])()
    return ok_object(get_ime_order(rid), 200)


@bp.get("/claims/<rid>/ime-orders")
def list_claim_ime_orders(rid):
    require_auth(["PlatformAdmin", "ClaimsAdjuster", "MedicalReviewer"])()
    get_claim(rid)
    limit, offset = paginate_params(request.args)
    items = [i for i in db.ime_orders.values() if i["claim_id"] == rid]
    page, total = sort_and_page(items, limit, offset)
    return ok_array(page, limit, offset, total, 200)


@bp.post("/ime-orders/<rid>/complete")
def complete_ime_order(rid):
    require_auth(["MedicalReviewer"])()
    ime = get_ime_order(rid)

    # Segregation of duties (priority 3): the reserve-setter may not complete it.
    if current_user_id() == _reserve_set_by(ime["claim_id"]):
        raise APIError(ERR_SEGREGATION_OF_DUTIES, 403,
                       "The reserve-setter may not complete this claim's IME")

    if ime["status"] != "SCHEDULED":
        raise APIError(ERR_INVALID_STATE, 409,
                       f"Cannot complete an IME in status {ime['status']}")
    now = db.get_current_utc_dt()
    start = db.parse_iso_dt(ime["scheduled_start"])
    if now < start:
        raise APIError(ERR_INVALID_STATE, 409,
                       "IME cannot be completed before its scheduled_start")
    ime["status"] = "COMPLETED"
    db.bump(ime)
    return ok_object(ime, 200)


@bp.post("/ime-orders/<rid>/no-show")
def no_show_ime_order(rid):
    require_auth(["MedicalReviewer"])()
    ime = get_ime_order(rid)
    if ime["status"] != "SCHEDULED":
        raise APIError(ERR_INVALID_STATE, 409,
                       f"Cannot mark no-show an IME in status {ime['status']}")
    now = db.get_current_utc_dt()
    end = db.parse_iso_dt(ime["scheduled_end"])
    if now < end:
        raise APIError(ERR_INVALID_STATE, 409,
                       "IME cannot be marked no-show before its scheduled_end")
    ime["status"] = "NO_SHOW"
    db.bump(ime)
    return ok_object(ime, 200)


@bp.post("/ime-orders/<rid>/cancel")
def cancel_ime_order(rid):
    require_auth(["ClaimsAdjuster"])()
    ime = get_ime_order(rid)
    if ime["status"] != "SCHEDULED":
        raise APIError(ERR_INVALID_STATE, 409,
                       f"Cannot cancel an IME in status {ime['status']}")
    ime["status"] = "CANCELLED"
    db.bump(ime)
    return ok_object(ime, 200)
