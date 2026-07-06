"""Drive-In Cinema API — Flask entry point and all routes.

Boots cleanly from a fresh process every time; storage is in-memory only and
starts EMPTY (no seeding). The logical clock resets to 2026-03-01T00:00:00Z on
each boot (clock.py module state).

Validation order is fixed per PRD §2.7:
  auth(401) -> authorization(403) -> ownership(403) -> existence(404)
  -> well-formedness(400) -> state(409) -> OCC(412) -> domain business rules.
"""
import os
from datetime import timedelta

from flask import Flask, request

import db
import clock
import serializers as ser
import calculations as calc
from auth import authenticate, require_role
from entitytools import stamp_new, touch, must_get
from errors import (
    ApiError, err,
    ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_STALE_VERSION,
    ERR_NOT_FOUND, ERR_NOT_RESOURCE_OWNER,
    ERR_SHOWTIME_CONFIG_INVALID, ERR_SHOWTIME_OVERLAP, ERR_RENTAL_CONFLICT,
    ERR_PASS_INVALID, ERR_PASS_EXHAUSTED, ERR_ITEM_UNAVAILABLE,
    ERR_LOT_FULL, ERR_PERSON_CAPACITY_EXCEEDED, ERR_NO_FM_CHANNEL,
    ERR_GATE_CODE_MISMATCH, ERR_CHECKIN_WINDOW_CLOSED, ERR_COMPLETE_TOO_EARLY,
    ERR_SWEEP_TOO_EARLY, ERR_WEATHER_FEATURES_INVALID,
)
from response import ok, created, ok_list, error_response, parse_pagination, paginate
from util import new_gate_code, parse_dt
import validate as v

app = Flask(__name__)

ALL_ROLES = {"PlatformAdmin", "VenueOperator", "GateAttendant", "Patron"}
OCCUPANCY_HOLDING = {"CONFIRMED", "CHECKED_IN", "SCANNED"}


# --------------------------------------------------------------------------- #
# Error handling
# --------------------------------------------------------------------------- #
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", "No such resource.", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", "Method not allowed.", 404)


@app.errorhandler(400)
def handle_400(e):
    return error_response("ERR_INVALID_REQUEST", "Malformed request.", 400)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.message, e.http_status)
    return error_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % e, 400)


def get_body():
    """Parse JSON body leniently; reject non-object bodies."""
    data = request.get_json(silent=True)
    return v.body_dict(data)


# --------------------------------------------------------------------------- #
# Interval helpers
# --------------------------------------------------------------------------- #
def showtime_total_features(st):
    return 2 if st["is_double_feature"] else 1


def showtimes_time_overlap_halfopen(a_start, a_end, b_start, b_end):
    """Half-open [start,end) overlap: a_start < b_end and b_start < a_end."""
    return a_start < b_end and b_start < a_end


def closed_overlap(a_start, a_end, b_start, b_end):
    """Closed [start,end] overlap (shared endpoint collides)."""
    return a_start <= b_end and b_start <= a_end


# --------------------------------------------------------------------------- #
# Catalog: Venues
# --------------------------------------------------------------------------- #
@app.route("/venues", methods=["POST"])
def create_venue():
    _, role = authenticate()
    require_role(role, {"PlatformAdmin"})
    body = get_body()

    name = v.require_str(body, "name")
    timezone_str = body.get("timezone")
    if timezone_str is None:
        timezone_str = "UTC"
    elif not isinstance(timezone_str, str) or timezone_str == "":
        raise err(ERR_INVALID_REQUEST, "timezone must be a non-empty string.")

    pool = v.require(body, "fm_channel_pool")
    if (not isinstance(pool, list) or len(pool) == 0
            or not all(isinstance(f, str) and f for f in pool)
            or len(set(pool)) != len(pool)):
        raise err(ERR_INVALID_REQUEST, "fm_channel_pool must be a non-empty array of distinct strings.")

    turnaround = v.optional_int(body, "turnaround_buffer_minutes", 30, minimum=0)
    grace = v.optional_int(body, "no_show_grace_minutes", 15, minimum=0)

    e = stamp_new({
        "name": name,
        "timezone": timezone_str,
        "fm_channel_pool": list(pool),
        "turnaround_buffer_minutes": turnaround,
        "no_show_grace_minutes": grace,
    })
    db.venues[e["id"]] = e
    return created(ser.venue(e))


@app.route("/venues/<venue_id>", methods=["GET"])
def get_venue(venue_id):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    e = must_get(db.venues, venue_id, "venue")
    return ok(ser.venue(e))


# --------------------------------------------------------------------------- #
# Catalog: Lots
# --------------------------------------------------------------------------- #
@app.route("/lots", methods=["POST"])
def create_lot():
    _, role = authenticate()
    require_role(role, {"PlatformAdmin", "VenueOperator"})
    body = get_body()
    venue_id = v.require_str(body, "venue_id")
    must_get(db.venues, venue_id, "venue")
    name = v.require_str(body, "name")
    stall_count = v.require_int(body, "stall_count", minimum=1)
    person_capacity = v.require_int(body, "person_capacity", minimum=1)

    e = stamp_new({
        "venue_id": venue_id,
        "name": name,
        "stall_count": stall_count,
        "person_capacity": person_capacity,
        "status": "OPEN",
    })
    db.lots[e["id"]] = e
    return created(ser.lot(e))


@app.route("/lots/<lot_id>", methods=["GET"])
def get_lot(lot_id):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    e = must_get(db.lots, lot_id, "lot")
    return ok(ser.lot(e))


@app.route("/lots", methods=["GET"])
def list_lots():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    venue_id = request.args.get("venue_id")
    rows = [e for e in db.lots.values()
            if venue_id is None or e["venue_id"] == venue_id]
    rows = paginate(rows)
    page = rows[offset:offset + limit]
    return ok_list([ser.lot(e) for e in page], len(rows), limit, offset)


# --------------------------------------------------------------------------- #
# Catalog: Films
# --------------------------------------------------------------------------- #
@app.route("/films", methods=["POST"])
def create_film():
    _, role = authenticate()
    require_role(role, {"PlatformAdmin", "VenueOperator"})
    body = get_body()
    title = v.require_str(body, "title")
    runtime = v.require_int(body, "runtime_minutes", minimum=1)
    rating = v.require_enum(body, "rating", {"G", "PG", "PG13", "R"})
    e = stamp_new({
        "title": title,
        "runtime_minutes": runtime,
        "rating": rating,
    }, with_version=False)
    db.films[e["id"]] = e
    return created(ser.film(e))


@app.route("/films/<film_id>", methods=["GET"])
def get_film(film_id):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    e = must_get(db.films, film_id, "film")
    return ok(ser.film(e))


# --------------------------------------------------------------------------- #
# Catalog: Concession Items
# --------------------------------------------------------------------------- #
@app.route("/concession-items", methods=["POST"])
def create_concession_item():
    _, role = authenticate()
    require_role(role, {"PlatformAdmin", "VenueOperator"})
    body = get_body()
    venue_id = v.require_str(body, "venue_id")
    must_get(db.venues, venue_id, "venue")
    name = v.require_str(body, "name")
    unit_price = v.require_int(body, "unit_price_cents", minimum=0)
    tax_rate = v.optional_number(body, "tax_rate", 0, minimum=0)
    if tax_rate >= 1:
        raise err(ERR_INVALID_REQUEST, "tax_rate must be < 1.")
    available = v.optional_bool(body, "available", True)
    e = stamp_new({
        "venue_id": venue_id,
        "name": name,
        "unit_price_cents": unit_price,
        "tax_rate": tax_rate,
        "available": available,
    })
    db.concession_items[e["id"]] = e
    return created(ser.concession_item(e))


@app.route("/concession-items/<item_id>", methods=["GET"])
def get_concession_item(item_id):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    e = must_get(db.concession_items, item_id, "concession item")
    return ok(ser.concession_item(e))


@app.route("/concession-items", methods=["GET"])
def list_concession_items():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    venue_id = request.args.get("venue_id")
    rows = [e for e in db.concession_items.values()
            if venue_id is None or e["venue_id"] == venue_id]
    rows = paginate(rows)
    page = rows[offset:offset + limit]
    return ok_list([ser.concession_item(e) for e in page], len(rows), limit, offset)


# --------------------------------------------------------------------------- #
# Showtimes
# --------------------------------------------------------------------------- #
@app.route("/showtimes", methods=["POST"])
def create_showtime():
    _, role = authenticate()
    require_role(role, {"VenueOperator"})
    body = get_body()

    # Existence (404) — left to right per PRD §2.7.
    venue_id = v.require_str(body, "venue_id")
    venue = must_get(db.venues, venue_id, "venue")
    lot_id = v.require_str(body, "lot_id")
    lot = must_get(db.lots, lot_id, "lot")
    primary_film_id = v.require_str(body, "primary_film_id")
    primary_film = must_get(db.films, primary_film_id, "film")

    # Well-formedness (400).
    is_double = v.optional_bool(body, "is_double_feature", False)
    secondary_film_id = body.get("secondary_film_id")
    start_raw = v.require_str(body, "start_utc")
    start_dt = parse_dt(start_raw)
    pricing_mode = v.require_enum(body, "pricing_mode", {"PER_CAR", "PER_PERSON"})
    base_price = v.require_int(body, "base_price_cents", minimum=0)
    included = v.optional_int(body, "included_occupants", 2, minimum=1)
    per_extra = v.optional_int(body, "per_extra_person_cents", 0, minimum=0)
    df_surcharge = v.optional_int(body, "double_feature_surcharge_cents", 0, minimum=0)

    # Secondary film existence checked when provided (404 before config 422).
    secondary_film = None
    if secondary_film_id is not None:
        if not isinstance(secondary_film_id, str) or secondary_film_id == "":
            raise err(ERR_INVALID_REQUEST, "secondary_film_id must be a string.")
        secondary_film = must_get(db.films, secondary_film_id, "film")

    # Config validity (422) — lot belongs to venue; double-feature/secondary IFF.
    if lot["venue_id"] != venue_id:
        raise err(ERR_SHOWTIME_CONFIG_INVALID, "lot does not belong to venue.")
    if is_double and secondary_film_id is None:
        raise err(ERR_SHOWTIME_CONFIG_INVALID, "double feature requires secondary_film_id.")
    if not is_double and secondary_film_id is not None:
        raise err(ERR_SHOWTIME_CONFIG_INVALID, "single feature must not set secondary_film_id.")

    # Compute end_utc.
    total_minutes = primary_film["runtime_minutes"]
    if is_double:
        total_minutes += secondary_film["runtime_minutes"]
    end_dt = start_dt + timedelta(minutes=total_minutes)

    # Overlap (409): half-open [start,end) extended by turnaround buffer on the
    # same lot vs other SCHEDULED/WEATHER_HOLD showtimes.
    buffer_min = venue["turnaround_buffer_minutes"]
    for other in db.showtimes.values():
        if other["lot_id"] != lot_id:
            continue
        if other["status"] not in {"SCHEDULED", "WEATHER_HOLD"}:
            continue
        # Extend the NEW window by the buffer at its end, and the OTHER window by
        # the buffer at its end, so consecutive showtimes need a clean gap of
        # buffer minutes between end and next start.
        a_start = start_dt
        a_end = end_dt + timedelta(minutes=buffer_min)
        b_start = other["_start_dt"]
        b_end = other["_end_dt"] + timedelta(minutes=buffer_min)
        if showtimes_time_overlap_halfopen(a_start, a_end, b_start, b_end):
            raise err(ERR_SHOWTIME_OVERLAP, "Showtime collides with another on this lot.")

    e = stamp_new({
        "venue_id": venue_id,
        "lot_id": lot_id,
        "primary_film_id": primary_film_id,
        "secondary_film_id": secondary_film_id,
        "is_double_feature": is_double,
        "_start_dt": start_dt,
        "_end_dt": end_dt,
        "pricing_mode": pricing_mode,
        "base_price_cents": base_price,
        "included_occupants": included,
        "per_extra_person_cents": per_extra,
        "double_feature_surcharge_cents": df_surcharge,
        "status": "SCHEDULED",
        "reserved_stall_count": 0,
        "reserved_person_count": 0,
    })
    db.showtimes[e["id"]] = e
    return created(ser.showtime(e))


@app.route("/showtimes/<st_id>", methods=["GET"])
def get_showtime(st_id):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    e = must_get(db.showtimes, st_id, "showtime")
    return ok(ser.showtime(e))


@app.route("/showtimes", methods=["GET"])
def list_showtimes():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    venue_id = request.args.get("venue_id")
    lot_id = request.args.get("lot_id")
    primary_film_id = request.args.get("primary_film_id")
    secondary_film_id = request.args.get("secondary_film_id")
    rows = []
    for e in db.showtimes.values():
        if venue_id is not None and e["venue_id"] != venue_id:
            continue
        if lot_id is not None and e["lot_id"] != lot_id:
            continue
        if primary_film_id is not None and e["primary_film_id"] != primary_film_id:
            continue
        if secondary_film_id is not None and e["secondary_film_id"] != secondary_film_id:
            continue
        rows.append(e)
    rows = paginate(rows)
    page = rows[offset:offset + limit]
    return ok_list([ser.showtime(e) for e in page], len(rows), limit, offset)


# ---- FM channel assignment ---- #
def fm_active_overlapping_frequencies(venue_id, st):
    """Frequencies already held by ACTIVE assignments on time-overlapping
    showtimes of the same venue (PRD §3.9)."""
    busy = set()
    for fa in db.fm_channel_assignments.values():
        if fa["venue_id"] != venue_id:
            continue
        if fa["status"] != "ACTIVE":
            continue
        other = db.showtimes.get(fa["showtime_id"])
        if other is None or other["id"] == st["id"]:
            continue
        if showtimes_time_overlap_halfopen(
                st["_start_dt"], st["_end_dt"], other["_start_dt"], other["_end_dt"]):
            busy.add(fa["frequency"])
    return busy


@app.route("/showtimes/<st_id>/fm-channel", methods=["POST"])
def assign_fm_channel(st_id):
    _, role = authenticate()
    require_role(role, {"VenueOperator"})
    st = must_get(db.showtimes, st_id, "showtime")
    venue = must_get(db.venues, st["venue_id"], "venue")

    busy = fm_active_overlapping_frequencies(st["venue_id"], st)
    chosen = None
    for freq in venue["fm_channel_pool"]:
        if freq not in busy:
            chosen = freq
            break
    if chosen is None:
        raise err(ERR_NO_FM_CHANNEL, "No free FM frequency available.")

    e = stamp_new({
        "showtime_id": st_id,
        "venue_id": st["venue_id"],
        "frequency": chosen,
        "status": "ACTIVE",
    })
    db.fm_channel_assignments[e["id"]] = e
    return created(ser.fm_channel_assignment(e))


@app.route("/showtimes/<st_id>/fm-channel", methods=["GET"])
def list_fm_channel(st_id):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    must_get(db.showtimes, st_id, "showtime")
    limit, offset = parse_pagination(request.args)
    rows = [e for e in db.fm_channel_assignments.values() if e["showtime_id"] == st_id]
    rows = paginate(rows)
    page = rows[offset:offset + limit]
    return ok_list([ser.fm_channel_assignment(e) for e in page], len(rows), limit, offset)


def release_fm_for_showtime(st_id):
    for fa in db.fm_channel_assignments.values():
        if fa["showtime_id"] == st_id and fa["status"] == "ACTIVE":
            fa["status"] = "RELEASED"
            touch(fa)


# ---- Weather events ---- #
@app.route("/showtimes/<st_id>/weather-events", methods=["POST"])
def create_weather_event(st_id):
    _, role = authenticate()
    require_role(role, {"VenueOperator"})
    st = must_get(db.showtimes, st_id, "showtime")
    body = get_body()
    severity = v.require_enum(body, "severity", {"ADVISORY", "CANCELLATION"})
    features_remaining = v.optional_int(body, "features_remaining", 0, minimum=0, maximum=2)

    if severity == "ADVISORY":
        # State (409): permitted only from SCHEDULED.
        if st["status"] != "SCHEDULED":
            raise err(ERR_INVALID_STATE, "Advisory requires a SCHEDULED showtime.")
        we = _record_weather_event(st_id, severity, features_remaining)
        st["status"] = "WEATHER_HOLD"
        touch(st)
        return created(ser.weather_event(we))

    # CANCELLATION.
    if st["status"] not in {"SCHEDULED", "WEATHER_HOLD"}:
        raise err(ERR_INVALID_STATE, "Cancellation requires SCHEDULED or WEATHER_HOLD.")
    total_features = showtime_total_features(st)
    if features_remaining < 0 or features_remaining > total_features:
        raise err(ERR_WEATHER_FEATURES_INVALID,
                  "features_remaining must be within [0, %d]." % total_features)

    we = _record_weather_event(st_id, severity, features_remaining)
    st["status"] = "CANCELLED"
    touch(st)
    _cascade_showtime_cancel(st, features_remaining, total_features)
    release_fm_for_showtime(st_id)
    return created(ser.weather_event(we))


def _record_weather_event(st_id, severity, features_remaining):
    we = stamp_new({
        "showtime_id": st_id,
        "severity": severity,
        "features_remaining": features_remaining,
    }, with_version=False)
    db.weather_events[we["id"]] = we
    return we


@app.route("/showtimes/<st_id>/weather-events", methods=["GET"])
def list_weather_events(st_id):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    must_get(db.showtimes, st_id, "showtime")
    limit, offset = parse_pagination(request.args)
    rows = [e for e in db.weather_events.values() if e["showtime_id"] == st_id]
    rows = paginate(rows)
    page = rows[offset:offset + limit]
    return ok_list([ser.weather_event(e) for e in page], len(rows), limit, offset)


@app.route("/showtimes/<st_id>/clear-weather-hold", methods=["POST"])
def clear_weather_hold(st_id):
    _, role = authenticate()
    require_role(role, {"VenueOperator"})
    st = must_get(db.showtimes, st_id, "showtime")
    if st["status"] != "WEATHER_HOLD":
        raise err(ERR_INVALID_STATE, "Clear requires a WEATHER_HOLD showtime.")
    st["status"] = "SCHEDULED"
    touch(st)
    return ok(ser.showtime(st))


@app.route("/showtimes/<st_id>/complete", methods=["POST"])
def complete_showtime(st_id):
    _, role = authenticate()
    require_role(role, {"VenueOperator"})
    st = must_get(db.showtimes, st_id, "showtime")
    if st["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Complete requires a SCHEDULED showtime.")
    if clock.now() < st["_end_dt"]:
        raise err(ERR_COMPLETE_TOO_EARLY, "Cannot complete before end_utc.")
    st["status"] = "COMPLETED"
    release_fm_for_showtime(st_id)
    touch(st)
    return ok(ser.showtime(st))


@app.route("/showtimes/<st_id>/run-no-show-sweep", methods=["POST"])
def run_no_show_sweep(st_id):
    _, role = authenticate()
    require_role(role, {"VenueOperator", "GateAttendant"})
    st = must_get(db.showtimes, st_id, "showtime")
    venue = must_get(db.venues, st["venue_id"], "venue")
    sweep_time = st["_start_dt"] + timedelta(minutes=venue["no_show_grace_minutes"])
    if clock.now() < sweep_time:
        raise err(ERR_SWEEP_TOO_EARLY, "Sweep before start + grace is not allowed.")

    for resv in db.reservations.values():
        if resv["showtime_id"] != st_id:
            continue
        if resv["occupancy_status"] != "CONFIRMED":
            continue
        resv["occupancy_status"] = "NO_SHOW"
        _release_capacity(st, resv)
        _restore_pass_redemption(resv)
        touch(resv)
    # No version bump or refund on the showtime itself for the sweep.
    return ok(ser.showtime(st))


# --------------------------------------------------------------------------- #
# Capacity / pass reconciliation helpers
# --------------------------------------------------------------------------- #
def _release_capacity(st, resv):
    """Decrement showtime derived counts for a leaving reservation (PRD §2.5)."""
    st["reserved_stall_count"] -= resv["stalls_used"]
    if st["pricing_mode"] == "PER_PERSON":
        st["reserved_person_count"] -= resv["occupant_count"]
    touch(st)


def _restore_pass_redemption(resv):
    if resv["season_pass_id"]:
        sp = db.season_passes.get(resv["season_pass_id"])
        if sp is not None:
            sp["redemptions_used"] -= 1
            touch(sp)


# --------------------------------------------------------------------------- #
# Reservations
# --------------------------------------------------------------------------- #
@app.route("/reservations", methods=["POST"])
def create_reservation():
    user_id, role = authenticate()
    require_role(role, {"Patron"})
    body = get_body()

    # Existence (404) left to right: showtime, then season pass if supplied.
    showtime_id = v.require_str(body, "showtime_id")
    st = must_get(db.showtimes, showtime_id, "showtime")
    season_pass_id = body.get("season_pass_id")
    sp = None
    if season_pass_id is not None:
        if not isinstance(season_pass_id, str) or season_pass_id == "":
            raise err(ERR_INVALID_REQUEST, "season_pass_id must be a string.")
        sp = must_get(db.season_passes, season_pass_id, "season pass")

    # Ownership (403): the supplied patron_id and pass must belong to the caller.
    patron_id = v.require_str(body, "patron_id")
    if patron_id != user_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "patron_id must equal the caller's X-User-ID.")

    # Well-formedness (400).
    occupant_count = v.require_int(body, "occupant_count", minimum=1)
    promo_pct = v.optional_number(body, "promo_pct", 0, minimum=0, maximum=1)
    expected_version = v.require_int(body, "expected_showtime_version")

    lot = must_get(db.lots, st["lot_id"], "lot")

    # OCC (412) — before capacity check (PRD §2.6/§2.7).
    if expected_version != st["version"]:
        raise err(ERR_STALE_VERSION, "Stale showtime version.")

    # Pass validity (422) — ownership, ACTIVE, window, valid_to_utc.
    if sp is not None:
        if sp["patron_id"] != user_id:
            raise err(ERR_NOT_RESOURCE_OWNER, "Season pass not owned by caller.")
        if sp["status"] != "ACTIVE":
            raise err(ERR_PASS_INVALID, "Season pass is not ACTIVE.")
        # PRD §3.4/§3.11: a redemption is valid only when the screening's
        # start_utc is on or before the pass's valid_to_utc. The "validity
        # window" condition is defined entirely by this clause — the PRD
        # states no requirement that the current clock fall within the window.
        if st["_start_dt"] > sp["_valid_to_dt"]:
            raise err(ERR_PASS_INVALID, "Showtime starts after pass.valid_to_utc.")
        # Redemption budget (409).
        if sp["redemptions_used"] >= sp["max_redemptions"]:
            raise err(ERR_PASS_EXHAUSTED, "Season pass redemptions exhausted.")

    # Capacity (409).
    if st["pricing_mode"] == "PER_CAR":
        stalls_used = 1
        if st["reserved_stall_count"] >= lot["stall_count"]:
            raise err(ERR_LOT_FULL, "No stalls available.")
    else:  # PER_PERSON
        stalls_used = 0
        if st["reserved_person_count"] + occupant_count > lot["person_capacity"]:
            raise err(ERR_PERSON_CAPACITY_EXCEEDED, "Person capacity exceeded.")

    amount_due = calc.reservation_pricing(st, occupant_count, promo_pct, sp is not None)

    e = stamp_new({
        "showtime_id": showtime_id,
        "lot_id": st["lot_id"],
        "patron_id": patron_id,
        "occupant_count": occupant_count,
        "season_pass_id": season_pass_id,
        "promo_pct": promo_pct,
        "amount_due_cents": amount_due,
        "amount_paid_cents": 0,
        "stalls_used": stalls_used,
        "gate_code": new_gate_code(),
        "occupancy_status": "CONFIRMED",
        "payment_status": "UNPAID",
    })
    db.reservations[e["id"]] = e

    # Reconcile derived counts + version on the showtime (PRD §2.5/§2.6).
    st["reserved_stall_count"] += stalls_used
    if st["pricing_mode"] == "PER_PERSON":
        st["reserved_person_count"] += occupant_count
    touch(st)
    if sp is not None:
        sp["redemptions_used"] += 1
        touch(sp)

    return created(ser.reservation(e))


def _owner_check_reservation(resv, role, user_id):
    if role == "Patron" and resv["patron_id"] != user_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "Reservation not owned by caller.")


@app.route("/reservations/<resv_id>", methods=["GET"])
def get_reservation(resv_id):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    e = must_get(db.reservations, resv_id, "reservation")
    return ok(ser.reservation(e))


@app.route("/reservations", methods=["GET"])
def list_reservations():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    showtime_id = request.args.get("showtime_id")
    lot_id = request.args.get("lot_id")
    patron_id = request.args.get("patron_id")
    season_pass_id = request.args.get("season_pass_id")
    rows = []
    for e in db.reservations.values():
        if showtime_id is not None and e["showtime_id"] != showtime_id:
            continue
        if lot_id is not None and e["lot_id"] != lot_id:
            continue
        if patron_id is not None and e["patron_id"] != patron_id:
            continue
        if season_pass_id is not None and e["season_pass_id"] != season_pass_id:
            continue
        rows.append(e)
    rows = paginate(rows)
    page = rows[offset:offset + limit]
    return ok_list([ser.reservation(e) for e in page], len(rows), limit, offset)


@app.route("/reservations/<resv_id>/pay", methods=["POST"])
def pay_reservation(resv_id):
    user_id, role = authenticate()
    require_role(role, {"Patron"})
    resv = must_get(db.reservations, resv_id, "reservation")
    _owner_check_reservation(resv, role, user_id)
    if resv["payment_status"] != "UNPAID" or resv["occupancy_status"] != "CONFIRMED":
        raise err(ERR_INVALID_STATE, "Pay requires UNPAID payment and CONFIRMED occupancy.")
    resv["payment_status"] = "PAID"
    resv["amount_paid_cents"] = resv["amount_due_cents"]
    touch(resv)
    return ok(ser.reservation(resv))


@app.route("/reservations/<resv_id>/check-in", methods=["POST"])
def check_in_reservation(resv_id):
    _, role = authenticate()
    require_role(role, {"GateAttendant"})
    resv = must_get(db.reservations, resv_id, "reservation")
    st = must_get(db.showtimes, resv["showtime_id"], "showtime")
    # State (409).
    if (resv["occupancy_status"] != "CONFIRMED"
            or resv["payment_status"] != "PAID"
            or st["status"] != "SCHEDULED"):
        raise err(ERR_INVALID_STATE, "Check-in requires CONFIRMED+PAID and SCHEDULED showtime.")
    # Time window (409): not earlier than 60 minutes before start.
    if clock.now() < st["_start_dt"] - timedelta(minutes=60):
        raise err(ERR_CHECKIN_WINDOW_CLOSED, "Check-in window not yet open.")
    resv["occupancy_status"] = "CHECKED_IN"
    touch(resv)
    return ok(ser.reservation(resv))


@app.route("/reservations/<resv_id>/scan", methods=["POST"])
def scan_reservation(resv_id):
    _, role = authenticate()
    require_role(role, {"GateAttendant"})
    resv = must_get(db.reservations, resv_id, "reservation")
    body = get_body()
    gate_code = v.require_str(body, "gate_code")
    if resv["occupancy_status"] != "CHECKED_IN":
        raise err(ERR_INVALID_STATE, "Scan requires CHECKED_IN occupancy.")
    if gate_code != resv["gate_code"]:
        raise err(ERR_GATE_CODE_MISMATCH, "Gate code does not match.")
    resv["occupancy_status"] = "SCANNED"
    touch(resv)
    return ok(ser.reservation(resv))


@app.route("/reservations/<resv_id>/cancel", methods=["POST"])
def cancel_reservation(resv_id):
    user_id, role = authenticate()
    require_role(role, {"Patron"})
    resv = must_get(db.reservations, resv_id, "reservation")
    _owner_check_reservation(resv, role, user_id)
    body = get_body()
    expected_version = v.require_int(body, "expected_reservation_version")
    st = must_get(db.showtimes, resv["showtime_id"], "showtime")

    # State (409).
    if resv["occupancy_status"] not in {"CONFIRMED", "CHECKED_IN"}:
        raise err(ERR_INVALID_STATE, "Cancel requires CONFIRMED or CHECKED_IN occupancy.")
    if st["status"] not in {"SCHEDULED", "WEATHER_HOLD"}:
        raise err(ERR_INVALID_STATE, "Cancel requires SCHEDULED or WEATHER_HOLD showtime.")
    # OCC (412).
    if expected_version != resv["version"]:
        raise err(ERR_STALE_VERSION, "Stale reservation version.")

    resv["occupancy_status"] = "CANCELLED"
    _release_capacity(st, resv)
    _restore_pass_redemption(resv)

    # Voluntary refund if PAID.
    if resv["payment_status"] == "PAID":
        hours_before = (st["_start_dt"] - clock.now()).total_seconds() / 3600.0
        refund = calc.voluntary_cancel_refund(resv["amount_paid_cents"], hours_before)
        resv["payment_status"] = "REFUNDED"
        _create_refund_record("RESERVATION", "VOLUNTARY_CANCEL", refund,
                              reservation_id=resv["id"])

    # Cascade concession orders (depth-3).
    _cascade_concession_orders(resv["id"], cascade_reason="RESERVATION_CASCADE")

    touch(resv)
    return ok(ser.reservation(resv))


# --------------------------------------------------------------------------- #
# Cascade helpers
# --------------------------------------------------------------------------- #
def _create_refund_record(source_type, reason, amount_cents,
                          reservation_id=None, concession_order_id=None):
    rr = stamp_new({
        "source_type": source_type,
        "reservation_id": reservation_id,
        "concession_order_id": concession_order_id,
        "reason": reason,
        "amount_cents": amount_cents,
    }, with_version=False)
    db.refund_records[rr["id"]] = rr
    return rr


def _cascade_concession_orders(reservation_id, cascade_reason):
    """Cancel any PENDING/PAID concession orders on a reservation; refund PAID ones."""
    for order in db.concession_orders.values():
        if order["reservation_id"] != reservation_id:
            continue
        if order["status"] not in {"PENDING", "PAID"}:
            continue
        was_paid = order["status"] == "PAID"
        order["status"] = "CANCELLED"
        touch(order)
        if was_paid:
            _create_refund_record("CONCESSION_ORDER", cascade_reason,
                                  order["total_cents"],
                                  concession_order_id=order["id"])


def _cascade_showtime_cancel(st, features_remaining, total_features):
    """Cascade a weather CANCELLATION across the showtime's bookings (PRD §3.10)."""
    for resv in db.reservations.values():
        if resv["showtime_id"] != st["id"]:
            continue
        if resv["occupancy_status"] not in OCCUPANCY_HOLDING:
            continue
        resv["occupancy_status"] = "CANCELLED"
        _release_capacity(st, resv)
        _restore_pass_redemption(resv)
        if resv["payment_status"] == "PAID":
            refund = calc.weather_refund(resv["amount_paid_cents"],
                                         features_remaining, total_features)
            resv["payment_status"] = "REFUNDED"
            _create_refund_record("RESERVATION", "WEATHER", refund,
                                  reservation_id=resv["id"])
        touch(resv)
        _cascade_concession_orders(resv["id"], cascade_reason="RESERVATION_CASCADE")


# --------------------------------------------------------------------------- #
# Concession orders
# --------------------------------------------------------------------------- #
@app.route("/reservations/<resv_id>/concession-orders", methods=["POST"])
def create_concession_order(resv_id):
    user_id, role = authenticate()
    require_role(role, {"Patron"})
    resv = must_get(db.reservations, resv_id, "reservation")
    _owner_check_reservation(resv, role, user_id)
    body = get_body()

    lines = v.require(body, "lines")
    if not isinstance(lines, list) or len(lines) == 0:
        raise err(ERR_INVALID_REQUEST, "lines must be a non-empty array.")

    # Validate line structure (400) + resolve items (404 for missing item).
    resolved = []
    for line in lines:
        if not isinstance(line, dict):
            raise err(ERR_INVALID_REQUEST, "Each line must be an object.")
        item_id = line.get("concession_item_id")
        if not isinstance(item_id, str) or item_id == "":
            raise err(ERR_INVALID_REQUEST, "Each line needs a concession_item_id.")
        qty = line.get("qty")
        if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
            raise err(ERR_INVALID_REQUEST, "Each line qty must be an integer >= 1.")
        item = must_get(db.concession_items, item_id, "concession item")
        resolved.append((item, qty))

    # Availability + venue match (409). Resolve reservation's venue via showtime.
    st = db.showtimes.get(resv["showtime_id"])
    resv_venue_id = st["venue_id"] if st is not None else None
    for item, qty in resolved:
        if not item["available"] or item["venue_id"] != resv_venue_id:
            raise err(ERR_ITEM_UNAVAILABLE, "Concession item unavailable for this reservation.")

    priced = [(item["unit_price_cents"], qty, item["tax_rate"]) for item, qty in resolved]
    subtotal, tax, service_fee, total = calc.concession_order_total(priced)

    e = stamp_new({
        "reservation_id": resv_id,
        "lines": [{"concession_item_id": item["id"], "qty": qty} for item, qty in resolved],
        "subtotal_cents": subtotal,
        "tax_cents": tax,
        "service_fee_cents": service_fee,
        "total_cents": total,
        "status": "PENDING",
    })
    db.concession_orders[e["id"]] = e
    return created(ser.concession_order(e))


@app.route("/reservations/<resv_id>/concession-orders", methods=["GET"])
def list_concession_orders(resv_id):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    must_get(db.reservations, resv_id, "reservation")
    limit, offset = parse_pagination(request.args)
    rows = [e for e in db.concession_orders.values() if e["reservation_id"] == resv_id]
    rows = paginate(rows)
    page = rows[offset:offset + limit]
    return ok_list([ser.concession_order(e) for e in page], len(rows), limit, offset)


def _owner_check_order(order, role, user_id):
    if role == "Patron":
        resv = db.reservations.get(order["reservation_id"])
        if resv is None or resv["patron_id"] != user_id:
            raise err(ERR_NOT_RESOURCE_OWNER, "Concession order not owned by caller.")


@app.route("/concession-orders/<order_id>/pay", methods=["POST"])
def pay_concession_order(order_id):
    user_id, role = authenticate()
    require_role(role, {"Patron"})
    order = must_get(db.concession_orders, order_id, "concession order")
    _owner_check_order(order, role, user_id)
    resv = must_get(db.reservations, order["reservation_id"], "reservation")
    if order["status"] != "PENDING":
        raise err(ERR_INVALID_STATE, "Pay requires a PENDING order.")
    if resv["occupancy_status"] not in OCCUPANCY_HOLDING:
        raise err(ERR_INVALID_STATE, "Parent reservation must be CONFIRMED/CHECKED_IN/SCANNED.")
    order["status"] = "PAID"
    touch(order)
    return ok(ser.concession_order(order))


@app.route("/concession-orders/<order_id>/fulfill", methods=["POST"])
def fulfill_concession_order(order_id):
    _, role = authenticate()
    require_role(role, {"GateAttendant"})
    order = must_get(db.concession_orders, order_id, "concession order")
    resv = must_get(db.reservations, order["reservation_id"], "reservation")
    if order["status"] != "PAID":
        raise err(ERR_INVALID_STATE, "Fulfill requires a PAID order.")
    if resv["occupancy_status"] != "SCANNED":
        raise err(ERR_INVALID_STATE, "Parent reservation must be SCANNED to fulfill.")
    order["status"] = "FULFILLED"
    touch(order)
    return ok(ser.concession_order(order))


@app.route("/concession-orders/<order_id>/cancel", methods=["POST"])
def cancel_concession_order(order_id):
    user_id, role = authenticate()
    require_role(role, {"Patron"})
    order = must_get(db.concession_orders, order_id, "concession order")
    _owner_check_order(order, role, user_id)
    if order["status"] not in {"PENDING", "PAID"}:
        raise err(ERR_INVALID_STATE, "Cancel requires PENDING or PAID order.")
    was_paid = order["status"] == "PAID"
    order["status"] = "CANCELLED"
    touch(order)
    if was_paid:
        _create_refund_record("CONCESSION_ORDER", "VOLUNTARY_CANCEL",
                              order["total_cents"], concession_order_id=order["id"])
    return ok(ser.concession_order(order))


# --------------------------------------------------------------------------- #
# Season passes
# --------------------------------------------------------------------------- #
@app.route("/season-passes", methods=["POST"])
def create_season_pass():
    _, role = authenticate()
    require_role(role, {"VenueOperator"})
    body = get_body()
    patron_id = v.require_str(body, "patron_id")
    tier = v.require_enum(body, "tier", {"SILVER", "GOLD"})
    max_redemptions = v.require_int(body, "max_redemptions", minimum=1)
    valid_from = parse_dt(v.require_str(body, "valid_from_utc"))
    valid_to = parse_dt(v.require_str(body, "valid_to_utc"))
    e = stamp_new({
        "patron_id": patron_id,
        "tier": tier,
        "max_redemptions": max_redemptions,
        "redemptions_used": 0,
        "_valid_from_dt": valid_from,
        "_valid_to_dt": valid_to,
        "status": "ACTIVE",
    })
    db.season_passes[e["id"]] = e
    return created(ser.season_pass(e))


@app.route("/season-passes/<pass_id>", methods=["GET"])
def get_season_pass(pass_id):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    e = must_get(db.season_passes, pass_id, "season pass")
    return ok(ser.season_pass(e))


@app.route("/season-passes", methods=["GET"])
def list_season_passes():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    patron_id = request.args.get("patron_id")
    rows = [e for e in db.season_passes.values()
            if patron_id is None or e["patron_id"] == patron_id]
    rows = paginate(rows)
    page = rows[offset:offset + limit]
    return ok_list([ser.season_pass(e) for e in page], len(rows), limit, offset)


@app.route("/season-passes/<pass_id>/revoke", methods=["POST"])
def revoke_season_pass(pass_id):
    _, role = authenticate()
    require_role(role, {"VenueOperator"})
    sp = must_get(db.season_passes, pass_id, "season pass")
    if sp["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Revoke requires an ACTIVE pass.")
    sp["status"] = "REVOKED"
    touch(sp)
    return ok(ser.season_pass(sp))


# --------------------------------------------------------------------------- #
# Private rentals
# --------------------------------------------------------------------------- #
@app.route("/private-rentals", methods=["POST"])
def create_private_rental():
    _, role = authenticate()
    require_role(role, {"VenueOperator"})
    body = get_body()
    venue_id = v.require_str(body, "venue_id")
    must_get(db.venues, venue_id, "venue")
    lot_id = v.require_str(body, "lot_id")
    must_get(db.lots, lot_id, "lot")
    organizer_id = v.require_str(body, "organizer_id")
    start_dt = parse_dt(v.require_str(body, "start_utc"))
    end_dt = parse_dt(v.require_str(body, "end_utc"))
    flat_fee = v.require_int(body, "flat_venue_fee_cents", minimum=0)
    per_hour = v.require_int(body, "per_hour_cents", minimum=0)

    quote = calc.private_rental_quote(flat_fee, per_hour, start_dt, end_dt)

    e = stamp_new({
        "venue_id": venue_id,
        "lot_id": lot_id,
        "organizer_id": organizer_id,
        "_start_dt": start_dt,
        "_end_dt": end_dt,
        "flat_venue_fee_cents": flat_fee,
        "per_hour_cents": per_hour,
        "quote_cents": quote,
        "status": "REQUESTED",
    })
    db.private_rentals[e["id"]] = e
    return created(ser.private_rental(e))


@app.route("/private-rentals/<rental_id>", methods=["GET"])
def get_private_rental(rental_id):
    _, role = authenticate()
    require_role(role, {"PlatformAdmin", "VenueOperator", "GateAttendant"})
    e = must_get(db.private_rentals, rental_id, "private rental")
    return ok(ser.private_rental(e))


@app.route("/private-rentals", methods=["GET"])
def list_private_rentals():
    _, role = authenticate()
    require_role(role, {"PlatformAdmin", "VenueOperator", "GateAttendant"})
    limit, offset = parse_pagination(request.args)
    venue_id = request.args.get("venue_id")
    lot_id = request.args.get("lot_id")
    rows = []
    for e in db.private_rentals.values():
        if venue_id is not None and e["venue_id"] != venue_id:
            continue
        if lot_id is not None and e["lot_id"] != lot_id:
            continue
        rows.append(e)
    rows = paginate(rows)
    page = rows[offset:offset + limit]
    return ok_list([ser.private_rental(e) for e in page], len(rows), limit, offset)


@app.route("/private-rentals/<rental_id>/approve", methods=["POST"])
def approve_private_rental(rental_id):
    _, role = authenticate()
    require_role(role, {"VenueOperator"})
    rental = must_get(db.private_rentals, rental_id, "private rental")
    body = get_body()
    expected_version = v.require_int(body, "expected_private_rental_version")

    # State (409).
    if rental["status"] != "REQUESTED":
        raise err(ERR_INVALID_STATE, "Approve requires a REQUESTED rental.")
    # OCC (412) — before interval-overlap check (PRD §2.6).
    if expected_version != rental["version"]:
        raise err(ERR_STALE_VERSION, "Stale rental version.")

    # Conflict (409): closed whole-lot interval vs APPROVED rentals and active showtimes.
    for other in db.private_rentals.values():
        if other["id"] == rental_id or other["lot_id"] != rental["lot_id"]:
            continue
        if other["status"] != "APPROVED":
            continue
        if closed_overlap(rental["_start_dt"], rental["_end_dt"],
                          other["_start_dt"], other["_end_dt"]):
            raise err(ERR_RENTAL_CONFLICT, "Rental conflicts with an approved rental.")
    for st in db.showtimes.values():
        if st["lot_id"] != rental["lot_id"]:
            continue
        if st["status"] not in {"SCHEDULED", "WEATHER_HOLD"}:
            continue
        if closed_overlap(rental["_start_dt"], rental["_end_dt"],
                          st["_start_dt"], st["_end_dt"]):
            raise err(ERR_RENTAL_CONFLICT, "Rental conflicts with an active showtime.")

    rental["status"] = "APPROVED"
    lot = db.lots.get(rental["lot_id"])
    if lot is not None:
        lot["status"] = "CLOSED"
        touch(lot)
    touch(rental)
    return ok(ser.private_rental(rental))


@app.route("/private-rentals/<rental_id>/reject", methods=["POST"])
def reject_private_rental(rental_id):
    _, role = authenticate()
    require_role(role, {"VenueOperator"})
    rental = must_get(db.private_rentals, rental_id, "private rental")
    if rental["status"] != "REQUESTED":
        raise err(ERR_INVALID_STATE, "Reject requires a REQUESTED rental.")
    rental["status"] = "REJECTED"
    touch(rental)
    return ok(ser.private_rental(rental))


@app.route("/private-rentals/<rental_id>/cancel", methods=["POST"])
def cancel_private_rental(rental_id):
    _, role = authenticate()
    require_role(role, {"VenueOperator"})
    rental = must_get(db.private_rentals, rental_id, "private rental")
    if rental["status"] != "APPROVED":
        raise err(ERR_INVALID_STATE, "Cancel requires an APPROVED rental.")
    rental["status"] = "CANCELLED"
    lot = db.lots.get(rental["lot_id"])
    if lot is not None:
        lot["status"] = "OPEN"
        touch(lot)
    touch(rental)
    return ok(ser.private_rental(rental))


# --------------------------------------------------------------------------- #
# Refund records (read-only)
# --------------------------------------------------------------------------- #
@app.route("/refund-records/<refund_id>", methods=["GET"])
def get_refund_record(refund_id):
    _, role = authenticate()
    require_role(role, {"PlatformAdmin", "VenueOperator", "Patron"})
    e = must_get(db.refund_records, refund_id, "refund record")
    return ok(ser.refund_record(e))


@app.route("/refund-records", methods=["GET"])
def list_refund_records():
    _, role = authenticate()
    require_role(role, {"PlatformAdmin", "VenueOperator", "Patron"})
    limit, offset = parse_pagination(request.args)
    reservation_id = request.args.get("reservation_id")
    concession_order_id = request.args.get("concession_order_id")
    rows = []
    for e in db.refund_records.values():
        if reservation_id is not None and e["reservation_id"] != reservation_id:
            continue
        if concession_order_id is not None and e["concession_order_id"] != concession_order_id:
            continue
        rows.append(e)
    rows = paginate(rows)
    page = rows[offset:offset + limit]
    return ok_list([ser.refund_record(e) for e in page], len(rows), limit, offset)


# --------------------------------------------------------------------------- #
# Logical clock (test-driving)
# --------------------------------------------------------------------------- #
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = authenticate()
    require_role(role, {"PlatformAdmin"})
    body = get_body()
    to_iso = v.require_str(body, "to_iso8601")
    clock.set_now(parse_dt(to_iso))
    return ok({})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
