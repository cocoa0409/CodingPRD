"""Event routes incl. lifecycle + advance-queue (PRD §3.2, §3.3)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_STALE_VERSION,
    ERR_ALLOCATION_EXCEEDED,
)
from middleware import require_auth, get_json_body
from response import ok_object, ok_array, paginate_params, slice_page
from services.common import (
    get_or_404,
    require_str,
    require_int,
    optional_int,
    sorted_by_creation,
)
from services import calculations

bp = Blueprint("events", __name__)


@bp.post("/events")
def create_event():
    require_auth(["PromoterAdmin"])()
    body = get_json_body()
    title = require_str(body, "title")
    venue_capacity = require_int(body, "venue_capacity")
    presale_code = require_str(body, "presale_code")
    face_value_cents = require_int(body, "face_value_cents")
    resale_cap_pct = optional_int(body, "resale_cap_pct", 110)

    if venue_capacity <= 0:
        raise APIError(ERR_INVALID_REQUEST, 400, "venue_capacity must be > 0")
    if face_value_cents <= 0:
        raise APIError(ERR_INVALID_REQUEST, 400, "face_value_cents must be > 0")
    if resale_cap_pct < 100:
        raise APIError(ERR_INVALID_REQUEST, 400, "resale_cap_pct must be >= 100")

    event = db.stamp_common(
        {
            "title": title,
            "venue_capacity": venue_capacity,
            "presale_code": presale_code,
            "face_value_cents": face_value_cents,
            "resale_cap_pct": resale_cap_pct,
            "tickets_sold_count": 0,
            "sales_status": "DRAFT",
        }
    )
    db.events[event["id"]] = event
    return ok_object(event, 201)


@bp.get("/events/<eid>")
def get_event(eid):
    require_auth(["Anonymous", "Fan", "PromoterAdmin"])()
    event = get_or_404(db.events, eid, "Event")
    return ok_object(event, 200)


@bp.get("/events")
def list_events():
    require_auth(["Anonymous", "Fan", "PromoterAdmin"])()
    limit, offset = paginate_params(request.args)
    sales_status = request.args.get("sales_status")
    items = list(db.events.values())
    if sales_status is not None:
        items = [e for e in items if e.get("sales_status") == sales_status]
    items = sorted_by_creation(items)
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total)


def _check_event_occ(event, body):
    expected = body.get("expected_event_version")
    if expected is None:
        raise APIError(ERR_INVALID_REQUEST, 400, "Missing expected_event_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise APIError(ERR_INVALID_REQUEST, 400, "expected_event_version must be an integer")
    if expected != event["version"]:
        raise APIError(ERR_STALE_VERSION, 412, "Stale event version")


@bp.post("/events/<eid>/open-presale")
def open_presale(eid):
    require_auth(["PromoterAdmin"])()
    event = get_or_404(db.events, eid, "Event")
    body = get_json_body()
    if event["sales_status"] != "DRAFT":
        raise APIError(ERR_INVALID_STATE, 409, "open-presale only from DRAFT")
    _check_event_occ(event, body)
    # precondition: at least one PriceTier exists for the event
    has_tier = any(t.get("event_id") == eid for t in db.price_tiers.values())
    if not has_tier:
        raise APIError(ERR_INVALID_STATE, 409, "Event has no price tiers")
    event["sales_status"] = "PRESALE"
    db.bump(event)
    return ok_object(event, 200)


@bp.post("/events/<eid>/open-general")
def open_general(eid):
    require_auth(["PromoterAdmin"])()
    event = get_or_404(db.events, eid, "Event")
    body = get_json_body()
    if event["sales_status"] != "PRESALE":
        raise APIError(ERR_INVALID_STATE, 409, "open-general only from PRESALE")
    _check_event_occ(event, body)
    event["sales_status"] = "GENERAL"
    db.bump(event)
    return ok_object(event, 200)


@bp.post("/events/<eid>/close")
def close_event(eid):
    require_auth(["PromoterAdmin"])()
    event = get_or_404(db.events, eid, "Event")
    body = get_json_body()
    if event["sales_status"] not in ("GENERAL", "SOLD_OUT"):
        raise APIError(ERR_INVALID_STATE, 409, "close only from GENERAL or SOLD_OUT")
    _check_event_occ(event, body)
    event["sales_status"] = "CLOSED"
    db.bump(event)
    return ok_object(event, 200)


@bp.post("/events/<eid>/advance-queue")
def advance_queue(eid):
    require_auth(["PromoterAdmin"])()
    event = get_or_404(db.events, eid, "Event")
    body = get_json_body()

    tier_filter = body.get("tier_id")
    if tier_filter is not None and not isinstance(tier_filter, str):
        raise APIError(ERR_INVALID_REQUEST, 400, "tier_id must be a string")
    if tier_filter is not None:
        # referenced tier must exist
        get_or_404(db.price_tiers, tier_filter, "PriceTier")

    max_offers = optional_int(body, "max_offers", None)
    if max_offers is not None and max_offers < 0:
        raise APIError(ERR_INVALID_REQUEST, 400, "max_offers must be >= 0")

    now = db.now_dt()
    touched = []  # queue entries affected (offered or expired), in processing order

    # ---- Step 1: sweep stale OFFERED entries -> EXPIRED ----
    offered = [
        qe
        for qe in db.queue_entries.values()
        if qe.get("event_id") == eid and qe["status"] == "OFFERED"
    ]
    if tier_filter is not None:
        offered = [qe for qe in offered if qe.get("tier_id") == tier_filter]
    offered = sorted_by_creation(offered)
    for qe in offered:
        exp = db.parse_iso_dt(qe.get("offer_expires_at"))
        if exp is not None and now > exp:
            qe["status"] = "EXPIRED"
            db.bump(qe)
            tier = db.price_tiers.get(qe.get("tier_id"))
            if tier is not None:
                tier["reserved_count"] -= qe["requested_qty"]
                db.bump(tier)
            touched.append(qe)

    # ---- Step 2: offer next admittable WAITING entries ----
    # Only when event is in PRESALE or GENERAL.
    if event["sales_status"] in ("PRESALE", "GENERAL"):
        waiting = [
            qe
            for qe in db.queue_entries.values()
            if qe.get("event_id") == eid and qe["status"] == "WAITING"
        ]
        if tier_filter is not None:
            waiting = [qe for qe in waiting if qe.get("tier_id") == tier_filter]
        # Admission order: queue_position ASC (== created_at ASC), never id.
        waiting.sort(key=lambda o: o.get("queue_position", 0))

        offers_made = 0
        for qe in waiting:
            if max_offers is not None and offers_made >= max_offers:
                break
            tier = db.price_tiers.get(qe.get("tier_id"))
            if tier is None:
                continue
            remaining = tier["allocation"] - (tier["reserved_count"] + tier["sold_count"])
            if qe["requested_qty"] <= remaining:
                qe["status"] = "OFFERED"
                offer_dt = db.now_dt()
                exp_ts = offer_dt.timestamp() + calculations.OFFER_WINDOW_SECONDS
                from datetime import datetime, timezone

                exp_dt = datetime.fromtimestamp(exp_ts, tz=timezone.utc)
                qe["offer_expires_at"] = (
                    exp_dt.strftime("%Y-%m-%dT%H:%M:%S.")
                    + f"{exp_dt.microsecond // 1000:03d}Z"
                )
                db.bump(qe)
                tier["reserved_count"] += qe["requested_qty"]
                db.bump(tier)
                touched.append(qe)
                offers_made += 1

    return ok_array(touched, len(touched), 0, len(touched))
