"""ReturnToWorkOffer endpoints (PRD §3.10). Lazy expiry; window-conflict buffer."""
from __future__ import annotations

from datetime import timedelta
from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_INVALID_STATE,
    ERR_RTW_WINDOW_CONFLICT,
)
from middleware import require_auth, get_json_body
from response import ok_object, ok_array, paginate_params, sort_and_page
from services.validation import require_str, require_int, require_datetime
from services import calculations as calc
from routes._common import (
    get_claim, get_rtw_offer, employer_id_of_claim,
    assert_employer_owns_claim,
)

bp = Blueprint("rtw_offers", __name__)


def _maybe_expire(offer) -> None:
    """OFFERED -> EXPIRED once now >= start_date (PRD §3.10, lazy on read)."""
    if offer["status"] != "OFFERED":
        return
    now = db.get_current_utc_dt()
    start = db.parse_iso_dt(offer["start_date"])
    if now >= start:
        offer["status"] = "EXPIRED"
        db.bump(offer)


@bp.post("/rtw-offers")
def create_rtw_offer():
    require_auth(["Employer"])()
    body = get_json_body()

    claim_id = require_str(body, "claim_id")
    claim = get_claim(claim_id)
    assert_employer_owns_claim(claim)

    # Claim must be LOST_TIME to receive an offer (PRD §3.10).
    if claim["status"] != "LOST_TIME":
        raise APIError(ERR_INVALID_STATE, 409,
                       "RTW offers may only be made against a LOST_TIME claim")

    light_duty = require_int(body, "light_duty_weekly_cents", minimum=0)
    start_dt = require_datetime(body, "start_date")
    end_dt = require_datetime(body, "end_date")

    # RTW window conflict (priority 11): no overlap with an ACCEPTED offer for the
    # same claim, with a BUFFER_DAYS gap after the accepted offer's end_date.
    buffer = timedelta(days=calc.BUFFER_DAYS)
    for other in db.rtw_offers.values():
        if other["claim_id"] != claim_id or other["status"] != "ACCEPTED":
            continue
        o_start = db.parse_iso_dt(other["start_date"])
        o_end = db.parse_iso_dt(other["end_date"])
        if start_dt < (o_end + buffer) and o_start < end_dt:
            raise APIError(ERR_RTW_WINDOW_CONFLICT, 409,
                           "RTW window conflicts with an accepted offer (buffer gap)")

    offer = {
        "claim_id": claim_id,
        "light_duty_weekly_cents": light_duty,
        "start_date": body["start_date"],
        "end_date": body["end_date"],
        "status": "OFFERED",
    }
    db.stamp_common(offer)
    db.rtw_offers[offer["id"]] = offer
    return ok_object(offer, 201)


@bp.get("/rtw-offers/<rid>")
def get_rtw_offer_route(rid):
    require_auth(["PlatformAdmin", "ClaimsAdjuster", "Employer"])()
    offer = get_rtw_offer(rid)
    _maybe_expire(offer)
    claim = db.claims.get(offer["claim_id"])
    if claim is not None:
        assert_employer_owns_claim(claim)
    return ok_object(offer, 200)


@bp.get("/claims/<rid>/rtw-offers")
def list_claim_rtw_offers(rid):
    require_auth(["PlatformAdmin", "ClaimsAdjuster", "Employer"])()
    claim = get_claim(rid)
    assert_employer_owns_claim(claim)
    items = [o for o in db.rtw_offers.values() if o["claim_id"] == rid]
    for o in items:
        _maybe_expire(o)
    limit, offset = paginate_params(request.args)
    page, total = sort_and_page(items, limit, offset)
    return ok_array(page, limit, offset, total, 200)


@bp.post("/rtw-offers/<rid>/accept")
def accept_rtw_offer(rid):
    require_auth(["Employer"])()
    offer = get_rtw_offer(rid)
    claim = db.claims.get(offer["claim_id"])
    if claim is not None:
        assert_employer_owns_claim(claim)
    _maybe_expire(offer)

    if offer["status"] != "OFFERED":
        raise APIError(ERR_INVALID_STATE, 409,
                       f"Cannot accept an offer in status {offer['status']}")
    if claim is None or claim["status"] != "LOST_TIME":
        raise APIError(ERR_INVALID_STATE, 409,
                       "Offer's claim must be LOST_TIME to accept")
    now = db.get_current_utc_dt()
    start = db.parse_iso_dt(offer["start_date"])
    if not (now < start):
        raise APIError(ERR_INVALID_STATE, 409,
                       "Acceptance must precede the light-duty start date")
    offer["status"] = "ACCEPTED"
    db.bump(offer)
    return ok_object(offer, 200)


@bp.post("/rtw-offers/<rid>/decline")
def decline_rtw_offer(rid):
    require_auth(["Employer"])()
    offer = get_rtw_offer(rid)
    claim = db.claims.get(offer["claim_id"])
    if claim is not None:
        assert_employer_owns_claim(claim)
    _maybe_expire(offer)

    if offer["status"] != "OFFERED":
        raise APIError(ERR_INVALID_STATE, 409,
                       f"Cannot decline an offer in status {offer['status']}")
    offer["status"] = "DECLINED"
    db.bump(offer)
    return ok_object(offer, 200)
