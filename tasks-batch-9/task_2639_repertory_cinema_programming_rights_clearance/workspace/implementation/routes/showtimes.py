"""Programming the single screen (PRD 3.5) and the booth/box-office dimensions."""
from datetime import datetime, timedelta

from flask import Blueprint

import serialize
from auth import PUBLIC_READ, ROLE_BOX, ROLE_EXEC, ROLE_PROGRAMMER, ROLE_TECH, authorize
from calc import (SLOT_GRANULARITY_MINUTES, compute_block, find_collision, key_covers,
                  slot_score, venue_local_day, venue_local_minutes,
                  weekly_balance_admits)
from cascade import (Ledger, cancel_showtime, refresh_showtime_rollup,
                     void_reserved_orders)
from errors import ApiError
from response import object_response, paged
from store import new_record, now, ordered, touch
from timeutil import from_local_naive, parse_hhmm
from validate import (FORMATS, STRANDS, bad, body, find, insert, must_find, opt_str,
                      query_instant, query_str, req_day, req_enum, req_hhmm, req_id,
                      req_instant, req_int, req_str, rows)
from routes.clearances import lapse_if_lapsed

bp = Blueprint("showtimes", __name__)

SCHEDULE_FIELDS = ("venue_id", "title_id", "booking_id", "clearance_id", "dcp_asset_id")


def require_showtime_state(showtime, condition, message):
    if not condition:
        raise ApiError("ERR_SHOWTIME_INVALID_STATE", message)


def _resolve_common(payload):
    """Schema then existence for the payload both schedulers share."""
    strand = req_enum(payload, "strand", STRANDS)
    series_label = opt_str(payload, "series_label")
    base_price_cents = req_int(payload, "base_price_cents", minimum=0)
    public_sale_opens_at = req_instant(payload, "public_sale_opens_at")
    fmt = req_enum(payload, "format", FORMATS)
    expected_version = req_int(payload, "expected_clearance_version", minimum=0)
    ids = {name: req_id(payload, name) for name in SCHEDULE_FIELDS}
    venue = must_find("venues", ids["venue_id"])
    title = must_find("titles", ids["title_id"])
    booking = must_find("bookings", ids["booking_id"])
    clearance = must_find("clearances", ids["clearance_id"])
    asset = must_find("assets", ids["dcp_asset_id"])
    return {
        "strand": strand,
        "series_label": series_label,
        "base_price_cents": base_price_cents,
        "public_sale_opens_at": public_sale_opens_at,
        "format": fmt,
        "expected_clearance_version": expected_version,
        "venue": venue,
        "title": title,
        "booking": booking,
        "clearance": clearance,
        "asset": asset,
    }


def _check_occ_clearance(clearance, expected):
    if expected != clearance["version"]:
        raise ApiError("ERR_STALE_CLEARANCE_VERSION",
                       "expected_clearance_version %d does not match %d."
                       % (expected, clearance["version"]))


def _check_reference_agreement(ctx):
    venue, title, booking = ctx["venue"], ctx["title"], ctx["booking"]
    clearance, asset = ctx["clearance"], ctx["asset"]
    if clearance["booking_id"] != booking["id"]:
        raise ApiError("ERR_REFERENCE_MISMATCH",
                       "The licence is attached to a different engagement.")
    if clearance["title_id"] != title["id"] or booking["title_id"] != title["id"]:
        raise ApiError("ERR_REFERENCE_MISMATCH",
                       "The licence, the engagement and the screening must name one title.")
    if asset["title_id"] != title["id"]:
        raise ApiError("ERR_REFERENCE_MISMATCH",
                       "The package carries a different title.")
    if booking["venue_id"] != venue["id"] or asset["venue_id"] != venue["id"]:
        raise ApiError("ERR_REFERENCE_MISMATCH",
                       "The screening, its engagement and its package must name one auditorium.")


def _check_rights(ctx):
    """Ladder steps 7 through 10, shared by both schedulers."""
    clearance, venue = ctx["clearance"], ctx["venue"]
    lapse_if_lapsed(clearance, venue)
    if clearance["status"] != "CLEARED":
        raise ApiError("ERR_CLEARANCE_NOT_CLEARED",
                       "A licence in %s cannot carry a screening." % clearance["status"])


def _check_window_covered(ctx, local_date):
    clearance = ctx["clearance"]
    if not (clearance["window_start_date"] <= local_date <= clearance["window_end_date"]):
        raise ApiError("ERR_CLEARANCE_WINDOW_NOT_COVERED",
                       "The screening date lies outside the licensed window.")


def _check_allowance(ctx):
    if ctx["clearance"]["screenings_remaining"] < 1:
        raise ApiError("ERR_SCREENING_ALLOWANCE_EXHAUSTED",
                       "The licence has no screenings remaining.")


def _check_format(ctx):
    fmt, venue, asset, clearance = ctx["format"], ctx["venue"], ctx["asset"], ctx["clearance"]
    if (fmt not in venue["supported_formats"] or fmt != asset["format"]
            or fmt != clearance["source_format"]):
        raise ApiError("ERR_FORMAT_INCOMPATIBLE",
                       "The format must agree with the booth, the package and the licence.")


def _check_engagement_window(ctx, local_date):
    booking = ctx["booking"]
    if not (booking["engagement_start_date"] <= local_date <= booking["engagement_end_date"]):
        raise ApiError("ERR_SHOWTIME_WINDOW_INVALID",
                       "The screening date lies outside the engagement window.")


def _local_time_ok(venue, start_at):
    minutes = venue_local_minutes(venue, start_at)
    return (parse_hhmm(venue["open_local_time"]) <= minutes
            <= parse_hhmm(venue["last_start_local_time"]))


def _create_showtime(ctx, start_at, score, ledger):
    venue, title, clearance, booking = ctx["venue"], ctx["title"], ctx["clearance"], ctx["booking"]
    end_at, blocked_until = compute_block(venue, title, start_at, 0)
    row = new_record(
        venue_id=venue["id"],
        title_id=title["id"],
        booking_id=booking["id"],
        clearance_id=clearance["id"],
        dcp_asset_id=ctx["asset"]["id"],
        strand=ctx["strand"],
        series_label=ctx["series_label"],
        start_at=start_at,
        end_at=end_at,
        blocked_until=blocked_until,
        extra_minutes=0,
        base_price_cents=ctx["base_price_cents"],
        surcharge_cents=0,
        public_sale_opens_at=ctx["public_sale_opens_at"],
        format=ctx["format"],
        status="SCHEDULED",
        sale_status="DRAFT",
        playback_status="UNVERIFIED",
        seats_sold=0,
        seats_available=venue["seat_capacity"] - venue["house_hold_seats"],
        gross_cents=0,
        admissions_count=0,
        slot_score=score,
        cancel_reason=None,
    )
    insert("showtimes", row)
    clearance["screenings_used"] = clearance["screenings_used"] + 1
    clearance["screenings_remaining"] = clearance["screenings_remaining"] - 1
    ledger.mark(clearance)
    booking["scheduled_showtime_count"] = booking["scheduled_showtime_count"] + 1
    ledger.mark(booking)
    return row


@bp.post("/showtimes")
def create_showtime():
    authorize((ROLE_PROGRAMMER,))
    payload = body()
    start_at = req_instant(payload, "start_at")
    ctx = _resolve_common(payload)
    venue, title, booking = ctx["venue"], ctx["title"], ctx["booking"]
    _check_occ_clearance(ctx["clearance"], ctx["expected_clearance_version"])
    if booking["status"] not in ("CONFIRMED", "RUNNING"):
        raise ApiError("ERR_BOOKING_INVALID_STATE",
                       "An engagement in %s cannot carry a screening." % booking["status"])
    _check_rights(ctx)
    local_date = venue_local_day(venue, start_at)
    _check_window_covered(ctx, local_date)
    _check_allowance(ctx)
    _check_format(ctx)
    end_at, blocked_until = compute_block(venue, title, start_at, 0)
    if find_collision(venue["id"], start_at, blocked_until) is not None:
        raise ApiError("ERR_SCREEN_SLOT_CONFLICT",
                       "The candidate screen block collides with another screening.")
    if not _local_time_ok(venue, start_at):
        raise ApiError("ERR_SHOWTIME_WINDOW_INVALID",
                       "The venue-local start time lies outside the operating window.")
    _check_engagement_window(ctx, local_date)
    if start_at < now():
        raise ApiError("ERR_SHOWTIME_WINDOW_INVALID",
                       "A screening may not be scheduled into the past.")
    if not weekly_balance_admits(venue, start_at, ctx["strand"]):
        raise ApiError("ERR_WEEKLY_BALANCE_EXCEEDED",
                       "The ISO-week first-run ceiling refuses this candidate.")
    _check_reference_agreement(ctx)
    ledger = Ledger()
    row = _create_showtime(ctx, start_at, None, ledger)
    ledger.flush()
    return object_response(serialize.showtime(row), 201)


@bp.post("/showtimes/auto-schedule")
def auto_schedule_showtime():
    authorize((ROLE_PROGRAMMER,))
    payload = body()
    target_date = req_day(payload, "target_date")
    earliest = req_hhmm(payload, "earliest_local_time")
    latest = req_hhmm(payload, "latest_local_time")
    ctx = _resolve_common(payload)
    venue, title, booking = ctx["venue"], ctx["title"], ctx["booking"]
    offset = venue["utc_offset_minutes"]
    earliest_minutes = parse_hhmm(earliest)
    latest_minutes = parse_hhmm(latest)
    if latest_minutes < earliest_minutes:
        raise bad("latest_local_time must not be earlier than earliest_local_time.")
    _check_occ_clearance(ctx["clearance"], ctx["expected_clearance_version"])
    if booking["status"] not in ("CONFIRMED", "RUNNING"):
        raise ApiError("ERR_BOOKING_INVALID_STATE",
                       "An engagement in %s cannot carry a screening." % booking["status"])
    _check_rights(ctx)
    _check_window_covered(ctx, target_date)
    _check_allowance(ctx)
    _check_format(ctx)
    _check_engagement_window(ctx, target_date)
    last_instant = from_local_naive(
        datetime.combine(target_date, datetime.min.time()) + timedelta(minutes=latest_minutes),
        offset)
    if last_instant < now():
        raise ApiError("ERR_SHOWTIME_WINDOW_INVALID",
                       "Every candidate slot on that date lies in the past.")
    open_minutes = parse_hhmm(venue["open_local_time"])
    last_start_minutes = parse_hhmm(venue["last_start_local_time"])
    day_start = datetime.combine(target_date, datetime.min.time())
    candidates = []
    minutes = earliest_minutes
    while minutes <= latest_minutes:
        candidate_start = from_local_naive(day_start + timedelta(minutes=minutes), offset)
        minutes += SLOT_GRANULARITY_MINUTES
        if not (open_minutes <= venue_local_minutes(venue, candidate_start) <= last_start_minutes):
            continue
        if candidate_start < now():
            continue
        _end, candidate_blocked = compute_block(venue, title, candidate_start, 0)
        if find_collision(venue["id"], candidate_start, candidate_blocked) is not None:
            continue
        if not weekly_balance_admits(venue, candidate_start, ctx["strand"]):
            continue
        candidates.append((candidate_start, candidate_blocked))
    if not candidates:
        raise ApiError("ERR_NO_ELIGIBLE_SLOT",
                       "No legal quarter-hour slot survives on that date.")
    _check_reference_agreement(ctx)
    best = None
    for candidate_start, candidate_blocked in candidates:
        score = slot_score(venue, candidate_start, candidate_blocked, ctx["strand"])
        if best is None or score > best[0]:
            best = (score, candidate_start)
    ledger = Ledger()
    row = _create_showtime(ctx, best[1], best[0], ledger)
    ledger.flush()
    return object_response(serialize.showtime(row), 201)


@bp.get("/showtimes/<showtime_id>")
def read_showtime(showtime_id):
    authorize(PUBLIC_READ)
    return object_response(serialize.showtime(must_find("showtimes", showtime_id)))


@bp.get("/showtimes")
def list_showtimes():
    authorize(PUBLIC_READ)
    found = rows("showtimes")
    for name in ("venue_id", "title_id", "booking_id", "clearance_id", "dcp_asset_id",
                 "strand", "status"):
        value = query_str(name)
        if value is not None:
            found = [s for s in found if s[name] == value]
    start_from = query_instant("start_from")
    start_to = query_instant("start_to")
    if start_from is not None:
        found = [s for s in found if s["start_at"] >= start_from]
    if start_to is not None:
        found = [s for s in found if s["start_at"] <= start_to]
    return paged(ordered(found), serialize.showtime)


@bp.post("/showtimes/<showtime_id>/verify-playback")
def verify_playback(showtime_id):
    authorize((ROLE_TECH,))
    payload = body()
    result = req_enum(payload, "result", ("PASS", "FAIL"))
    showtime = must_find("showtimes", showtime_id)
    require_showtime_state(showtime, showtime["status"] == "SCHEDULED",
                          "Only a scheduled screening can be booth tested.")
    require_showtime_state(showtime, showtime["playback_status"] == "KEY_PENDING",
                          "The screening's playback dimension is not KEY_PENDING.")
    # Lazily retire stale keys before coverage is evaluated (PRD 3.4).
    candidates = [k for k in rows("keys")
                  if k["dcp_asset_id"] == showtime["dcp_asset_id"]
                  and k["venue_id"] == showtime["venue_id"]]
    for key in candidates:
        if key["status"] == "ISSUED" and key["valid_until"] < now():
            key["status"] = "EXPIRED"
            touch(key)
    asset = find("assets", showtime["dcp_asset_id"])
    if asset is None or asset["status"] != "INGESTED":
        raise ApiError("ERR_DEPENDENCY_STATE_INVALID",
                       "The package must be INGESTED before the booth test.")
    if not any(key_covers(key, showtime) for key in candidates):
        raise ApiError("ERR_NO_COVERING_KDM",
                       "No issued key covers this screening.")
    showtime["playback_status"] = "PLAYBACK_VERIFIED" if result == "PASS" else "PLAYBACK_FAILED"
    touch(showtime)
    return object_response(serialize.showtime(showtime))


@bp.post("/showtimes/<showtime_id>/open-sales")
def open_sales(showtime_id):
    authorize((ROLE_BOX,))
    body()
    showtime = must_find("showtimes", showtime_id)
    require_showtime_state(showtime, showtime["status"] == "SCHEDULED",
                          "Only a scheduled screening can go on sale.")
    require_showtime_state(showtime, showtime["sale_status"] == "DRAFT",
                          "The sale dimension is not DRAFT.")
    booking = find("bookings", showtime["booking_id"])
    if booking is None or booking["status"] not in ("CONFIRMED", "RUNNING"):
        raise ApiError("ERR_DEPENDENCY_STATE_INVALID",
                       "The owning engagement must be CONFIRMED or RUNNING.")
    venue = must_find("venues", showtime["venue_id"])
    seats_sold = showtime["seats_sold"]
    sellable = venue["seat_capacity"] - venue["house_hold_seats"]
    if sellable - seats_sold < 1:
        raise ApiError("ERR_INSUFFICIENT_SEATS", "The screening has no seat available.")
    showtime["sale_status"] = "ON_SALE"
    ledger = Ledger()
    ledger.mark(showtime)
    refresh_showtime_rollup(showtime, ledger)
    ledger.flush()
    return object_response(serialize.showtime(showtime))


@bp.post("/showtimes/<showtime_id>/close-sales")
def close_sales(showtime_id):
    authorize((ROLE_BOX,))
    body()
    showtime = must_find("showtimes", showtime_id)
    require_showtime_state(showtime, showtime["sale_status"] in ("ON_SALE", "SOLD_OUT"),
                           "The sale dimension is not open.")
    ledger = Ledger()
    showtime["sale_status"] = "SALES_CLOSED"
    ledger.mark(showtime)
    void_reserved_orders(showtime, ledger)
    refresh_showtime_rollup(showtime, ledger)
    ledger.flush()
    return object_response(serialize.showtime(showtime))


@bp.post("/showtimes/<showtime_id>/cancel")
def cancel_showtime_endpoint(showtime_id):
    authorize((ROLE_PROGRAMMER, ROLE_BOX, ROLE_EXEC))
    payload = body()
    cancel_reason = req_str(payload, "cancel_reason")
    showtime = must_find("showtimes", showtime_id)
    require_showtime_state(showtime, showtime["status"] == "SCHEDULED",
                          "Only a scheduled screening can be cancelled.")
    ledger = Ledger()
    cancel_showtime(showtime, cancel_reason, ledger)
    for event in ordered(rows("events")):
        if event["showtime_id"] == showtime["id"] and event["status"] in ("PLANNED", "CONFIRMED"):
            event["status"] = "CANCELLED"
            event["cancel_reason"] = cancel_reason
            ledger.mark(event)
    ledger.flush()
    return object_response(serialize.showtime(showtime))


@bp.post("/showtimes/<showtime_id>/complete")
def complete_showtime(showtime_id):
    authorize((ROLE_BOX, ROLE_EXEC))
    body()
    showtime = must_find("showtimes", showtime_id)
    require_showtime_state(showtime, showtime["status"] == "SCHEDULED",
                          "Only a scheduled screening can be completed.")
    require_showtime_state(showtime, showtime["sale_status"] == "SALES_CLOSED",
                          "The box office must be closed first.")
    require_showtime_state(showtime, showtime["playback_status"] == "PLAYBACK_VERIFIED",
                          "The booth test must have passed first.")
    require_showtime_state(showtime, now() >= showtime["end_at"],
                          "The clock has not reached the screening's end.")
    ledger = Ledger()
    showtime["status"] = "COMPLETED"
    ledger.mark(showtime)
    refresh_showtime_rollup(showtime, ledger)
    booking = find("bookings", showtime["booking_id"])
    if booking is not None and booking["status"] == "CONFIRMED":
        booking["status"] = "RUNNING"
        ledger.mark(booking)
    ledger.flush()
    return object_response(serialize.showtime(showtime))
