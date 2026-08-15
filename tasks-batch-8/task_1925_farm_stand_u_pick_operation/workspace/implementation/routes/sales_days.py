"""SalesDay endpoints (PRD §3.3, §3.8) including close-day / close-weather cascades."""

from datetime import datetime, timedelta

from flask import Blueprint, request

import db
import domain
from errors import (
    raise_err,
    ERR_DATE_OUTSIDE_SEASON,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_OUTSIDE_WINDOW_HOURS,
    ERR_SALES_DAY_EXISTS,
    ERR_SEASON_NOT_ACTIVE,
)
from helpers import (
    check_no_undeclared,
    get_body,
    ok_object,
    paginate,
    req_date,
    req_enum,
    req_int,
    req_str,
    require,
    round_half_up_div,
)

bp = Blueprint("sales_days", __name__)

FM = ("FarmManager",)
READERS = ("FarmManager", "GateStaff", "FieldStaff")
DAY_TYPES = ("WEEKDAY", "WEEKEND")


@bp.post("/farm/sales-days")
def create_sales_day():
    require(FM)
    body = get_body()
    check_no_undeclared(
        body, {"season_id", "date", "day_type", "parking_capacity", "staff_on_duty"}
    )
    season_id = req_str(body, "season_id")
    date = req_date(body, "date")
    day_type = req_enum(body, "day_type", DAY_TYPES)
    parking_capacity = req_int(body, "parking_capacity", min_value=0)
    staff_on_duty = req_int(body, "staff_on_duty", min_value=0)
    season = db.seasons.get(season_id)
    if season is None:
        raise_err(ERR_NOT_FOUND, "season_id does not resolve")
    # Tier 10: per-season date uniqueness, then season-range check.
    if domain.sales_day_for(season_id, date) is not None:
        raise_err(ERR_SALES_DAY_EXISTS, "A SalesDay already exists for this season and date")
    if not (season["start_date"] <= date <= season["end_date"]):
        raise_err(ERR_DATE_OUTSIDE_SEASON, "SalesDay date is outside the season range")
    day = domain.new_entity()
    day.update(
        {
            "season_id": season_id,
            "date": date,
            "day_type": day_type,
            "parking_capacity": parking_capacity,
            "staff_on_duty": staff_on_duty,
            "status": "PLANNED",
            "closed_at_time": None,
        }
    )
    db.sales_days[day["id"]] = day
    return ok_object(domain.serialize_sales_day(day), 201)


@bp.get("/farm/sales-days/<did>")
def get_sales_day(did):
    require(READERS)
    day = db.sales_days.get(did)
    if day is None:
        raise_err(ERR_NOT_FOUND, "SalesDay not found")
    return ok_object(domain.serialize_sales_day(day))


@bp.get("/farm/sales-days")
def list_sales_days():
    require(READERS)
    items = list(db.sales_days.values())
    season_id = request.args.get("season_id")
    if season_id is not None:
        items = [d for d in items if d["season_id"] == season_id]
    date = request.args.get("date")
    if date is not None:
        items = [d for d in items if d["date"] == date]
    status = request.args.get("status")
    if status is not None:
        items = [d for d in items if d["status"] == status]
    return paginate(items, domain.serialize_sales_day)


@bp.post("/farm/sales-days/<did>/open-day")
def open_day(did):
    require(FM)
    day = db.sales_days.get(did)
    if day is None:
        raise_err(ERR_NOT_FOUND, "SalesDay not found")
    if day["status"] != "PLANNED":
        raise_err(ERR_INVALID_STATE, "Only a PLANNED SalesDay can be opened")
    season = db.seasons.get(day["season_id"])
    if season is None or season["status"] != "ACTIVE":
        raise_err(ERR_SEASON_NOT_ACTIVE, "Season is not ACTIVE")
    if db.logical_date_str() != day["date"]:
        raise_err(ERR_OUTSIDE_WINDOW_HOURS, "Logical clock date does not match the SalesDay date")
    day["status"] = "OPEN"
    # Rotation sweep: rested fields whose rest ended on or before today return
    # to DORMANT (comparison inclusive).
    for f in db.fields.values():
        if (
            f["season_id"] == day["season_id"]
            and f["status"] == "ROTATION_REST"
            and f["rest_until"] is not None
            and f["rest_until"] <= day["date"]
        ):
            f["status"] = "DORMANT"
            f["rest_until"] = None
            domain.touch(f)
    domain.touch(day)
    return ok_object(domain.serialize_sales_day(day))


def _void_provisional_lines(session):
    for l in domain.session_lines(session):
        if l["status"] == "PROVISIONAL":
            l["status"] = "VOIDED"
            domain.touch(l)
            field = db.fields.get(l["field_id"])
            if field is not None:
                domain.touch(field)


def _force_checkout(session, mode, weather_refund_amount=0):
    """Shared force-checkout mechanics for DAY_END_FORCED and WEATHER_FORCED."""
    final_total, bundle_discount = domain.checkout_settlement(session)
    session["final_total_cents"] = final_total
    session["bundle_discount_cents"] = bundle_discount
    _void_provisional_lines(session)
    # Every still-BOOKED booking releases. WEATHER_FORCED folds the face value
    # of today's bookings into the weather refund; DAY_END never refunds.
    for b in domain.session_bookings(session):
        if b["status"] == "BOOKED":
            domain.release_booking(b, refund=False)
    if weather_refund_amount > 0:
        domain.apply_refund(session, weather_refund_amount)
    session["visit_status"] = "CHECKED_OUT"
    session["checkout_mode"] = mode
    domain.touch(session)


@bp.post("/farm/sales-days/<did>/close-day")
def close_day(did):
    require(FM)
    day = db.sales_days.get(did)
    if day is None:
        raise_err(ERR_NOT_FOUND, "SalesDay not found")
    if day["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE, "Only an OPEN SalesDay can be closed")
    day["status"] = "CLOSED_NORMAL"
    # Sweep 1: on-site sessions force-check-out (DAY_END_FORCED, no refund).
    on_site = sorted(
        (
            s
            for s in domain.sessions_on_day(day)
            if s["visit_status"] in ("CHECKED_IN", "FIELD_ACTIVE")
        ),
        key=lambda s: (s["created_at"], s["_seq"]),
    )
    for s in on_site:
        _force_checkout(s, "DAY_END_FORCED")
    # Sweep 2: OPEN windows of the date close.
    for w in domain.windows_on_date(day["season_id"], day["date"]):
        if w["status"] == "OPEN":
            w["status"] = "CLOSED"
            domain.touch(w)
    # Sweep 3: PICKED_OUT fields of the season enter ROTATION_REST.
    rest_until = (
        datetime.strptime(day["date"], "%Y-%m-%d") + timedelta(days=domain.FIELD_REST_DAYS)
    ).strftime("%Y-%m-%d")
    for f in db.fields.values():
        if f["season_id"] == day["season_id"] and f["status"] == "PICKED_OUT":
            f["status"] = "ROTATION_REST"
            f["rest_until"] = rest_until
            domain.touch(f)
    domain.touch(day)
    return ok_object(domain.serialize_sales_day(day))


@bp.post("/farm/sales-days/<did>/close-weather")
def close_weather(did):
    require(FM)
    day = db.sales_days.get(did)
    if day is None:
        raise_err(ERR_NOT_FOUND, "SalesDay not found")
    if day["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE, "Only an OPEN SalesDay can be weather-closed")
    closed_at = db.logical_hhmm_str()
    day["status"] = "CLOSED_WEATHER"
    day["closed_at_time"] = closed_at
    # Hop 1: every SCHEDULED or OPEN window of the date cancels (WEATHER).
    for w in domain.windows_on_date(day["season_id"], day["date"]):
        if w["status"] in ("SCHEDULED", "OPEN"):
            w["status"] = "CANCELLED"
            w["cancel_reason"] = "WEATHER"
            domain.touch(w)
    # Refund tier from closed_at_time.
    if closed_at < "12:00":
        refund_pct = 10000
    elif closed_at < "15:00":
        refund_pct = 5000
    else:
        refund_pct = 0
    # Hop 2+3: each cancelled window's on-site sessions force-check out with
    # WEATHER_FORCED; PROVISIONAL lines void; weather refund applied oldest
    # first (paid basis — the session's pinned policy, never repriced).
    on_site = sorted(
        (
            s
            for s in domain.sessions_on_day(day)
            if s["visit_status"] in ("CHECKED_IN", "FIELD_ACTIVE")
        ),
        key=lambda s: (s["created_at"], s["_seq"]),
    )
    for s in on_site:
        policy = db.pricing_policies.get(s["pricing_policy_id"])
        container_component = 0
        if policy is not None:
            container_component = policy["container_fee_cents"] * s["container_count"]
        admission_component_paid = s["admission_charge_cents"] - container_component
        admission_refund = round_half_up_div(
            admission_component_paid * refund_pct, domain.BPS_DENOMINATOR
        )
        has_finalized = any(
            l["status"] == "FINALIZED" for l in domain.session_lines(s)
        )
        container_refund = 0 if has_finalized else container_component
        addon_refund = sum(
            b["booked_value_cents"]
            for b in domain.session_bookings(s)
            if b["status"] == "BOOKED" and b["booking_date"] == day["date"]
        )
        weather_refund_total = admission_refund + container_refund + addon_refund
        _force_checkout(s, "WEATHER_FORCED", weather_refund_amount=weather_refund_total)
    # Hop 3 (tail): every remaining BOOKED booking dated on the closure date
    # releases with a face-value refund — even for sessions already checked out.
    for b in list(db.addon_bookings.values()):
        if b["status"] == "BOOKED" and b["booking_date"] == day["date"]:
            domain.release_booking(b, refund=True)
    domain.touch(day)
    return ok_object(domain.serialize_sales_day(day))
