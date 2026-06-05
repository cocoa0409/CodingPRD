"""Restaurant POS & Table Management API — entry point + all routes.

In-memory only. NO entity seeding at startup. Boots clean every process.
"""
import os

from flask import Flask

import db
import errors
import logic
import serialize
from common import (
    get_body, require_fields, require_str, require_int, require_enum,
    optional_int, must_exist, paginate, stamp_create, touch,
)
from middleware import require_auth
from response import success, error as error_response

app = Flask(__name__)

ROLES_ALL = ["Manager", "Server", "Host", "KitchenStaff"]


# ===========================================================================
# Error handling
# ===========================================================================
@app.errorhandler(errors.ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_404(_e):
    return error_response(errors.ERR_NOT_FOUND, "Resource not found.", 404)


@app.errorhandler(405)
def handle_405(_e):
    return error_response(errors.ERR_NOT_FOUND, "Method not allowed.", 404)


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, errors.ApiError):
        return handle_api_error(err)
    return error_response("ERR_INTERNAL", str(err), 500)


# ===========================================================================
# Helpers
# ===========================================================================
def list_response(collection, serializer, predicate=None):
    rows = list(collection.values())
    if predicate is not None:
        rows = [r for r in rows if predicate(r)]
    page, pagination = paginate(rows)
    data = [serializer(r) for r in page]
    return success(data, http_status=200, is_list=True, pagination=pagination)


def filter_eq(field):
    from flask import request
    val = request.args.get(field)
    return val


# ===========================================================================
# Bootstrap / config
# ===========================================================================
@app.route("/restaurants", methods=["POST"])
@require_auth(["Manager"])
def create_restaurant():
    body = get_body()
    require_fields(body, "name", "tax_rate_bps")
    name = require_str(body, "name")
    tax_rate_bps = require_int(body, "tax_rate_bps", minimum=0, maximum=2000)
    large_party_threshold = optional_int(body, "large_party_threshold", 8, minimum=2)
    auto_gratuity_bps = optional_int(body, "auto_gratuity_bps", 2000, minimum=0, maximum=5000)
    comp_cap_bps = optional_int(body, "comp_cap_bps", 10000, minimum=0, maximum=10000)
    min_rest_minutes = optional_int(body, "min_rest_minutes", 0, minimum=0)

    rec = {
        "name": name,
        "tax_rate_bps": tax_rate_bps,
        "large_party_threshold": large_party_threshold,
        "auto_gratuity_bps": auto_gratuity_bps,
        "comp_cap_bps": comp_cap_bps,
        "min_rest_minutes": min_rest_minutes,
        "current_utc": db.EPOCH,
    }
    stamp_create(rec, db.EPOCH)
    db.restaurants[rec["id"]] = rec
    return success(serialize.restaurant(rec), 201)


@app.route("/restaurants/<rid>", methods=["GET"])
@require_auth(ROLES_ALL)
def get_restaurant(rid):
    rec = must_exist(db.restaurants, rid)
    return success(serialize.restaurant(rec), 200)


@app.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    # Bootstrap operation — exempt from auth headers (PRD §2.1).
    body = get_body()
    require_fields(body, "restaurant_id", "to_iso8601")
    rest = must_exist(db.restaurants, body["restaurant_id"])
    to_iso = body["to_iso8601"]
    if not isinstance(to_iso, str):
        raise errors.invalid_request("to_iso8601 must be an ISO 8601 string.")
    try:
        new_clock = db.parse_iso(to_iso)
    except Exception:
        raise errors.invalid_request("to_iso8601 is not a valid ISO 8601 timestamp.")
    rest["current_utc"] = new_clock
    touch(rest, new_clock)
    return success(serialize.restaurant(rest), 200)


# ===========================================================================
# Menu items / 86
# ===========================================================================
@app.route("/menu-items", methods=["POST"])
@require_auth(["Manager"])
def create_menu_item():
    body = get_body()
    require_fields(body, "restaurant_id", "name", "station",
                   "base_price_cents", "happy_hour_price_cents",
                   "initial_available_count")
    rest = must_exist(db.restaurants, body["restaurant_id"])
    name = require_str(body, "name")
    station = require_enum(body, "station", {"GRILL", "FRY", "SAUTE", "COLD", "BAR", "EXPO"})
    base = require_int(body, "base_price_cents", minimum=0)
    happy = require_int(body, "happy_hour_price_cents", minimum=0)
    if happy > base:
        raise errors.invalid_request("happy_hour_price_cents must be <= base_price_cents.")
    initial = require_int(body, "initial_available_count", minimum=0)

    rec = {
        "restaurant_id": rest["id"],
        "name": name,
        "station": station,
        "base_price_cents": base,
        "happy_hour_price_cents": happy,
        "initial_available_count": initial,
        "available_count": initial,
    }
    stamp_create(rec, rest["current_utc"])
    db.menu_items[rec["id"]] = rec
    return success(serialize.menu_item(rec), 201)


@app.route("/menu-items/<rid>", methods=["GET"])
@require_auth(ROLES_ALL)
def get_menu_item(rid):
    rec = must_exist(db.menu_items, rid)
    return success(serialize.menu_item(rec), 200)


@app.route("/menu-items", methods=["GET"])
@require_auth(ROLES_ALL)
def list_menu_items():
    restaurant_id = filter_eq("restaurant_id")

    def pred(r):
        return restaurant_id is None or r["restaurant_id"] == restaurant_id

    return list_response(db.menu_items, serialize.menu_item, pred)


# ===========================================================================
# Happy-hour windows
# ===========================================================================
@app.route("/happy-hour-windows", methods=["POST"])
@require_auth(["Manager"])
def create_happy_hour_window():
    body = get_body()
    require_fields(body, "restaurant_id", "day_of_week", "start_minute", "end_minute")
    rest = must_exist(db.restaurants, body["restaurant_id"])
    dow = require_int(body, "day_of_week", minimum=1, maximum=7)
    start = require_int(body, "start_minute", minimum=0)
    end = require_int(body, "end_minute", minimum=0, maximum=1440)
    if not (start < end):
        raise errors.invalid_request("start_minute must be < end_minute.")

    rec = {
        "restaurant_id": rest["id"],
        "day_of_week": dow,
        "start_minute": start,
        "end_minute": end,
    }
    stamp_create(rec, rest["current_utc"])
    db.happy_hour_windows[rec["id"]] = rec
    return success(serialize.happy_hour_window(rec), 201)


@app.route("/happy-hour-windows/<rid>", methods=["GET"])
@require_auth(["Manager", "Server"])
def get_happy_hour_window(rid):
    rec = must_exist(db.happy_hour_windows, rid)
    return success(serialize.happy_hour_window(rec), 200)


@app.route("/happy-hour-windows", methods=["GET"])
@require_auth(["Manager", "Server"])
def list_happy_hour_windows():
    restaurant_id = filter_eq("restaurant_id")

    def pred(r):
        return restaurant_id is None or r["restaurant_id"] == restaurant_id

    return list_response(db.happy_hour_windows, serialize.happy_hour_window, pred)


# ===========================================================================
# Tables
# ===========================================================================
@app.route("/tables", methods=["POST"])
@require_auth(["Manager"])
def create_table():
    body = get_body()
    require_fields(body, "restaurant_id", "table_number", "capacity")
    rest = must_exist(db.restaurants, body["restaurant_id"])
    table_number = require_str(body, "table_number")
    capacity = require_int(body, "capacity", minimum=1)

    rec = {
        "restaurant_id": rest["id"],
        "table_number": table_number,
        "capacity": capacity,
        "occupancy_status": "AVAILABLE",
    }
    stamp_create(rec, rest["current_utc"])
    db.dining_tables[rec["id"]] = rec
    return success(serialize.dining_table(rec), 201)


@app.route("/tables/<rid>", methods=["GET"])
@require_auth(["Manager", "Server", "Host"])
def get_table(rid):
    rec = must_exist(db.dining_tables, rid)
    return success(serialize.dining_table(rec), 200)


@app.route("/tables", methods=["GET"])
@require_auth(["Manager", "Server", "Host"])
def list_tables():
    restaurant_id = filter_eq("restaurant_id")

    def pred(r):
        return restaurant_id is None or r["restaurant_id"] == restaurant_id

    return list_response(db.dining_tables, serialize.dining_table, pred)


@app.route("/tables/<rid>/buss", methods=["POST"])
@require_auth(["Host"])
def buss_table(rid):
    body = get_body()
    table = must_exist(db.dining_tables, rid)
    require_fields(body, "expected_table_version")
    expected = require_int(body, "expected_table_version")
    # priority 5: state
    if table["occupancy_status"] != "DIRTY":
        raise errors.invalid_state("Table must be DIRTY to buss.")
    # priority 6: OCC
    if expected != table["version"]:
        raise errors.ApiError(errors.ERR_STALE_TABLE_VERSION, 412,
                              "expected_table_version does not match the table version.")

    rest = db.restaurants[table["restaurant_id"]]
    clock = rest["current_utc"]

    # Link 1: DIRTY -> AVAILABLE, version += 1
    table["occupancy_status"] = "AVAILABLE"
    touch(table, clock)  # increments version

    # Link 2 + 3: promote head waitlist entry that fits this table's capacity
    candidates = [w for w in db.waitlist_entries.values()
                  if w["restaurant_id"] == table["restaurant_id"]
                  and w["status"] == "WAITING"
                  and w["party_size"] <= table["capacity"]]
    if candidates:
        candidates.sort(key=lambda w: (w["quoted_at"], w["_seq"]))
        head = candidates[0]
        # promote
        head["status"] = "PROMOTED"
        # create seating
        seat = {
            "restaurant_id": table["restaurant_id"],
            "table_id": table["id"],
            "waitlist_entry_id": head["id"],
            "party_size": head["party_size"],
            "status": "OPEN",
            "seated_at": clock,
            "cleared_at": None,
        }
        stamp_create(seat, clock)
        db.seatings[seat["id"]] = seat
        # table back to SEATED
        table["occupancy_status"] = "SEATED"
        touch(table, clock)
        # entry -> SEATED, seating_id set
        head["seating_id"] = seat["id"]
        head["status"] = "SEATED"
        touch(head, clock)

    return success(serialize.dining_table(table), 200)


# ===========================================================================
# Waitlist
# ===========================================================================
@app.route("/waitlist", methods=["POST"])
@require_auth(["Host"])
def create_waitlist():
    body = get_body()
    require_fields(body, "restaurant_id", "party_name", "party_size")
    rest = must_exist(db.restaurants, body["restaurant_id"])
    party_name = require_str(body, "party_name")
    party_size = require_int(body, "party_size", minimum=1)

    rec = {
        "restaurant_id": rest["id"],
        "party_name": party_name,
        "party_size": party_size,
        "status": "WAITING",
        "quoted_at": rest["current_utc"],
        "seating_id": None,
    }
    stamp_create(rec, rest["current_utc"])
    db.waitlist_entries[rec["id"]] = rec
    return success(serialize.waitlist_entry(rec), 201)


@app.route("/waitlist/<rid>", methods=["GET"])
@require_auth(["Manager", "Host"])
def get_waitlist(rid):
    rec = must_exist(db.waitlist_entries, rid)
    return success(serialize.waitlist_entry(rec), 200)


@app.route("/waitlist", methods=["GET"])
@require_auth(["Manager", "Host"])
def list_waitlist():
    restaurant_id = filter_eq("restaurant_id")
    status = filter_eq("status")
    seating_id = filter_eq("seating_id")

    def pred(r):
        if restaurant_id is not None and r["restaurant_id"] != restaurant_id:
            return False
        if status is not None and r["status"] != status:
            return False
        if seating_id is not None and r["seating_id"] != seating_id:
            return False
        return True

    return list_response(db.waitlist_entries, serialize.waitlist_entry, pred)


@app.route("/waitlist/<rid>/cancel", methods=["POST"])
@require_auth(["Host"])
def cancel_waitlist(rid):
    rec = must_exist(db.waitlist_entries, rid)
    if rec["status"] != "WAITING":
        raise errors.invalid_state("Only a WAITING entry can be cancelled.")
    rec["status"] = "CANCELLED"
    rest = db.restaurants[rec["restaurant_id"]]
    touch(rec, rest["current_utc"])
    return success(serialize.waitlist_entry(rec), 200)


# ===========================================================================
# Seatings
# ===========================================================================
@app.route("/seatings", methods=["POST"])
@require_auth(["Host"])
def create_seating():
    body = get_body()
    require_fields(body, "restaurant_id", "table_id", "party_size")
    # existence left-to-right: restaurant_id, table_id, then optional waitlist_entry_id
    rest = must_exist(db.restaurants, body["restaurant_id"])
    table = must_exist(db.dining_tables, body["table_id"])
    waitlist_entry_id = body.get("waitlist_entry_id")
    entry = None
    if waitlist_entry_id is not None:
        entry = must_exist(db.waitlist_entries, waitlist_entry_id)
    party_size = require_int(body, "party_size", minimum=1)

    # priority 5: state — table must be AVAILABLE and no OPEN seating references it
    if table["occupancy_status"] != "AVAILABLE":
        raise errors.invalid_state("Table is not AVAILABLE for seating.")
    if any(s["table_id"] == table["id"] and s["status"] == "OPEN"
           for s in db.seatings.values()):
        raise errors.invalid_state("Table already has an OPEN seating.")

    # priority 7: business_referential — capacity + same restaurant
    if table["restaurant_id"] != rest["id"]:
        raise errors.ApiError(errors.ERR_CAPACITY_EXCEEDED, 409,
                              "Table does not belong to this restaurant.")
    if party_size > table["capacity"]:
        raise errors.ApiError(errors.ERR_CAPACITY_EXCEEDED, 409,
                              "party_size exceeds table capacity.")

    # priority 12: business_temporal — half-open interval overlap on this table
    clock = rest["current_utc"]
    new_start = clock
    new_end = None  # OPEN => unbounded for now
    for s in db.seatings.values():
        if s["table_id"] != table["id"]:
            continue
        s_start = s["seated_at"]
        s_end = s["cleared_at"]  # may be None (OPEN)
        if _intervals_overlap_halfopen(new_start, new_end, s_start, s_end):
            raise errors.ApiError(errors.ERR_TABLE_DOUBLE_BOOKED, 409,
                                  "Seating interval overlaps an existing seating on this table.")

    rec = {
        "restaurant_id": rest["id"],
        "table_id": table["id"],
        "waitlist_entry_id": waitlist_entry_id,
        "party_size": party_size,
        "status": "OPEN",
        "seated_at": clock,
        "cleared_at": None,
    }
    stamp_create(rec, clock)
    db.seatings[rec["id"]] = rec

    # table AVAILABLE -> SEATED
    table["occupancy_status"] = "SEATED"
    touch(table, clock)

    # if waitlist_entry cited, that entry -> SEATED
    if entry is not None:
        entry["seating_id"] = rec["id"]
        entry["status"] = "SEATED"
        touch(entry, clock)

    return success(serialize.seating(rec), 201)


def _intervals_overlap_halfopen(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap. None end == open-ended (+inf)."""
    import datetime as _dt
    far = _dt.datetime.max.replace(tzinfo=_dt.timezone.utc)
    ae = a_end if a_end is not None else far
    be = b_end if b_end is not None else far
    return a_start < be and b_start < ae


@app.route("/seatings/<rid>", methods=["GET"])
@require_auth(["Manager", "Server", "Host"])
def get_seating(rid):
    rec = must_exist(db.seatings, rid)
    return success(serialize.seating(rec), 200)


@app.route("/seatings", methods=["GET"])
@require_auth(["Manager", "Server", "Host"])
def list_seatings():
    restaurant_id = filter_eq("restaurant_id")
    table_id = filter_eq("table_id")
    waitlist_entry_id = filter_eq("waitlist_entry_id")

    def pred(r):
        if restaurant_id is not None and r["restaurant_id"] != restaurant_id:
            return False
        if table_id is not None and r["table_id"] != table_id:
            return False
        if waitlist_entry_id is not None and r["waitlist_entry_id"] != waitlist_entry_id:
            return False
        return True

    return list_response(db.seatings, serialize.seating, pred)


@app.route("/seatings/<rid>/clear", methods=["POST"])
@require_auth(["Host"])
def clear_seating(rid):
    rec = must_exist(db.seatings, rid)
    if rec["status"] != "OPEN":
        raise errors.invalid_state("Seating must be OPEN to clear.")
    # every check on this seating must be CLOSED or VOID
    for c in logic.checks_for_seating(rec["id"]):
        if c["status"] not in ("CLOSED", "VOID"):
            raise errors.invalid_state("All checks on the seating must be CLOSED or VOID.")

    rest = db.restaurants[rec["restaurant_id"]]
    clock = rest["current_utc"]
    rec["status"] = "CLEARED"
    rec["cleared_at"] = clock
    touch(rec, clock)

    # owning table SEATED -> DIRTY
    table = db.dining_tables.get(rec["table_id"])
    if table is not None:
        table["occupancy_status"] = "DIRTY"
        touch(table, clock)

    return success(serialize.seating(rec), 200)


# ===========================================================================
# Staff members
# ===========================================================================
@app.route("/staff-members", methods=["POST"])
@require_auth(["Manager"])
def create_staff_member():
    body = get_body()
    require_fields(body, "restaurant_id", "name", "role", "tip_weight_bps")
    rest = must_exist(db.restaurants, body["restaurant_id"])
    name = require_str(body, "name")
    role = require_enum(body, "role", {"SERVER", "BARTENDER", "BUSSER"})
    tip_weight_bps = require_int(body, "tip_weight_bps", minimum=0)

    rec = {
        "restaurant_id": rest["id"],
        "name": name,
        "role": role,
        "tip_weight_bps": tip_weight_bps,
    }
    stamp_create(rec, rest["current_utc"])
    db.staff_members[rec["id"]] = rec
    return success(serialize.staff_member(rec), 201)


@app.route("/staff-members/<rid>", methods=["GET"])
@require_auth(["Manager", "Server"])
def get_staff_member(rid):
    rec = must_exist(db.staff_members, rid)
    return success(serialize.staff_member(rec), 200)


@app.route("/staff-members", methods=["GET"])
@require_auth(["Manager"])
def list_staff_members():
    restaurant_id = filter_eq("restaurant_id")

    def pred(r):
        return restaurant_id is None or r["restaurant_id"] == restaurant_id

    return list_response(db.staff_members, serialize.staff_member, pred)


# ===========================================================================
# Staff shifts
# ===========================================================================
@app.route("/staff-shifts", methods=["POST"])
@require_auth(["Manager"])
def create_staff_shift():
    body = get_body()
    require_fields(body, "restaurant_id", "staff_id", "business_date",
                   "clock_in_minute", "clock_out_minute")
    rest = must_exist(db.restaurants, body["restaurant_id"])
    staff = must_exist(db.staff_members, body["staff_id"])
    business_date = require_str(body, "business_date")
    clock_in = require_int(body, "clock_in_minute", minimum=0)
    clock_out = require_int(body, "clock_out_minute", minimum=0, maximum=1440)
    if not (clock_in < clock_out):
        raise errors.invalid_request("clock_in_minute must be < clock_out_minute.")

    # priority 13: shift overlap (closed interval expanded by min_rest_minutes)
    buffer = rest["min_rest_minutes"]
    new_lo = clock_in - buffer
    new_hi = clock_out + buffer
    for sh in db.staff_shifts.values():
        if sh["staff_id"] != staff["id"]:
            continue
        if sh["business_date"] != business_date:
            continue
        # closed intervals touch/overlap test: expanded new vs existing closed
        if new_lo <= sh["clock_out_minute"] and sh["clock_in_minute"] <= new_hi:
            raise errors.ApiError(errors.ERR_SHIFT_OVERLAP, 409,
                                  "Shift overlaps another shift of this staff member that day.")

    hours_x100 = _round_half_up_div((clock_out - clock_in) * 100, 60)

    rec = {
        "restaurant_id": rest["id"],
        "staff_id": staff["id"],
        "business_date": business_date,
        "clock_in_minute": clock_in,
        "clock_out_minute": clock_out,
        "hours_worked_x100": hours_x100,
    }
    stamp_create(rec, rest["current_utc"])
    db.staff_shifts[rec["id"]] = rec
    return success(serialize.staff_shift(rec), 201)


def _round_half_up_div(numerator, denominator):
    """round_half_up(numerator / denominator) for non-negative integers."""
    from decimal import Decimal, ROUND_HALF_UP
    return int((Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))


@app.route("/staff-shifts/<rid>", methods=["GET"])
@require_auth(["Manager"])
def get_staff_shift(rid):
    rec = must_exist(db.staff_shifts, rid)
    return success(serialize.staff_shift(rec), 200)


@app.route("/staff-shifts", methods=["GET"])
@require_auth(["Manager"])
def list_staff_shifts():
    restaurant_id = filter_eq("restaurant_id")
    staff_id = filter_eq("staff_id")
    business_date = filter_eq("business_date")

    def pred(r):
        if restaurant_id is not None and r["restaurant_id"] != restaurant_id:
            return False
        if staff_id is not None and r["staff_id"] != staff_id:
            return False
        if business_date is not None and r["business_date"] != business_date:
            return False
        return True

    return list_response(db.staff_shifts, serialize.staff_shift, pred)


# ===========================================================================
# Checks
# ===========================================================================
def _new_check_record(rest, seating_id, server_staff_id, party_size, clock):
    rec = {
        "restaurant_id": rest["id"],
        "seating_id": seating_id,
        "server_staff_id": server_staff_id,
        "party_size": party_size,
        "status": "OPEN",
        "provisional_subtotal_cents": 0,
        "final_subtotal_cents": None,
        "comp_total_cents": 0,
        "auto_gratuity_cents": 0,
        "tax_cents": 0,
        "total_due_cents": 0,
        "amount_paid_cents": 0,
        "tip_cents": 0,
    }
    stamp_create(rec, clock)
    return rec


@app.route("/checks", methods=["POST"])
@require_auth(["Server"])
def create_check():
    body = get_body()
    require_fields(body, "restaurant_id", "seating_id", "server_staff_id", "party_size")
    rest = must_exist(db.restaurants, body["restaurant_id"])
    seating = must_exist(db.seatings, body["seating_id"])
    server = must_exist(db.staff_members, body["server_staff_id"])
    party_size = require_int(body, "party_size", minimum=1)

    rec = _new_check_record(rest, seating["id"], server["id"], party_size, rest["current_utc"])
    db.checks[rec["id"]] = rec
    return success(serialize.check(rec), 201)


@app.route("/checks/<rid>", methods=["GET"])
@require_auth(["Manager", "Server"])
def get_check(rid):
    rec = must_exist(db.checks, rid)
    return success(serialize.check(rec), 200)


@app.route("/checks", methods=["GET"])
@require_auth(["Manager", "Server"])
def list_checks():
    restaurant_id = filter_eq("restaurant_id")
    seating_id = filter_eq("seating_id")
    server_staff_id = filter_eq("server_staff_id")
    status = filter_eq("status")

    def pred(r):
        if restaurant_id is not None and r["restaurant_id"] != restaurant_id:
            return False
        if seating_id is not None and r["seating_id"] != seating_id:
            return False
        if server_staff_id is not None and r["server_staff_id"] != server_staff_id:
            return False
        if status is not None and r["status"] != status:
            return False
        return True

    return list_response(db.checks, serialize.check, pred)


@app.route("/checks/<rid>/present", methods=["POST"])
@require_auth(["Server"])
def present_check(rid):
    rec = must_exist(db.checks, rid)
    if rec["status"] != "OPEN":
        raise errors.invalid_state("Check must be OPEN to present.")
    # no course on this check may still be BUILDING
    for c in logic.courses_for_check(rec["id"]):
        if c["status"] == "BUILDING":
            raise errors.invalid_state("All courses must be fired before presenting.")

    rest = db.restaurants[rec["restaurant_id"]]
    clock = rest["current_utc"]
    final_sub = logic.final_subtotal(rec)
    rec["final_subtotal_cents"] = final_sub
    rec["status"] = "PRESENTED"
    logic.resolve_check_totals(rec, final_sub)
    touch(rec, clock)
    return success(serialize.check(rec), 200)


@app.route("/checks/<rid>/reopen", methods=["POST"])
@require_auth(["Server"])
def reopen_check(rid):
    rec = must_exist(db.checks, rid)
    if rec["status"] != "PRESENTED":
        raise errors.invalid_state("Check must be PRESENTED to reopen.")
    if rec["amount_paid_cents"] != 0:
        raise errors.invalid_state("Cannot reopen a check with settled payments.")

    rest = db.restaurants[rec["restaurant_id"]]
    clock = rest["current_utc"]
    rec["status"] = "OPEN"
    rec["final_subtotal_cents"] = None
    logic.recompute_check_open(rec)
    touch(rec, clock)
    return success(serialize.check(rec), 200)


@app.route("/checks/<rid>/close", methods=["POST"])
@require_auth(["Server"])
def close_check(rid):
    rec = must_exist(db.checks, rid)
    if rec["status"] != "PRESENTED":
        raise errors.invalid_state("Check must be PRESENTED to close.")
    if rec["amount_paid_cents"] < rec["total_due_cents"]:
        raise errors.ApiError(errors.ERR_UNDERPAID, 409,
                              "amount_paid_cents is less than total_due_cents.")

    rest = db.restaurants[rec["restaurant_id"]]
    clock = rest["current_utc"]
    rec["status"] = "CLOSED"
    touch(rec, clock)

    # contribute tip to the day's pool (create if absent)
    business_date = db.iso_ms(clock)[:10]  # YYYY-MM-DD from current_utc
    _contribute_to_pool(rest, business_date, rec["tip_cents"], clock)

    return success(serialize.check(rec), 200)


def _contribute_to_pool(rest, business_date, tip_cents, clock):
    pool = None
    for p in db.tip_pools.values():
        if p["restaurant_id"] == rest["id"] and p["business_date"] == business_date:
            pool = p
            break
    if pool is None:
        pool = {
            "restaurant_id": rest["id"],
            "business_date": business_date,
            "distribution_mode": "EVEN_BY_HOURS",
            "status": "ACCUMULATING",
            "pooled_cents": 0,
            "distributed_cents": 0,
        }
        stamp_create(pool, clock)
        db.tip_pools[pool["id"]] = pool
    pool["pooled_cents"] += tip_cents
    touch(pool, clock)


@app.route("/checks/<rid>/void", methods=["POST"])
@require_auth(["Manager"])
def void_check(rid):
    rec = must_exist(db.checks, rid)
    if rec["status"] not in ("OPEN", "PRESENTED"):
        raise errors.invalid_state("Check must be OPEN or PRESENTED to void.")
    if rec["amount_paid_cents"] != 0:
        raise errors.invalid_state("Cannot void a check with settled payments.")

    rest = db.restaurants[rec["restaurant_id"]]
    clock = rest["current_utc"]

    # void every non-VOIDED order item on the check; restore each count
    for oi in logic.items_for_check(rec):
        if oi["status"] == "VOIDED":
            continue
        # only fired/served/comped lines hold a consumed portion; restore those
        if oi["status"] in ("FIRED", "SERVED", "COMPED"):
            mi = db.menu_items.get(oi["menu_item_id"])
            if mi is not None:
                mi["available_count"] += oi["quantity"]
                touch(mi, clock)
        oi["status"] = "VOIDED"
        touch(oi, clock)

    rec["status"] = "VOID"
    touch(rec, clock)
    return success(serialize.check(rec), 200)


@app.route("/checks/<rid>/split", methods=["POST"])
@require_auth(["Server"])
def split_check(rid):
    body = get_body()
    rec = must_exist(db.checks, rid)
    require_fields(body, "n")
    n = require_int(body, "n")
    # priority 14: invalid split (422) — 2 <= n <= party_size
    if not (2 <= n <= rec["party_size"]):
        raise errors.ApiError(errors.ERR_INVALID_SPLIT, 422,
                              "split count n must satisfy 2 <= n <= party_size.")

    rest = db.restaurants[rec["restaurant_id"]]
    clock = rest["current_utc"]
    total = rec["total_due_cents"]
    base = total // n
    remainder = total - base * n

    children = []
    for i in range(n):
        assigned = base + (1 if i < remainder else 0)
        child = _new_check_record(rest, rec["seating_id"], rec["server_staff_id"],
                                  rec["party_size"], clock)
        child["total_due_cents"] = assigned
        db.checks[child["id"]] = child
        children.append(child)

    data = [serialize.check(c) for c in children]
    return success(data, 201, is_list=True)


# ===========================================================================
# Courses
# ===========================================================================
@app.route("/courses", methods=["POST"])
@require_auth(["Server"])
def create_course():
    body = get_body()
    require_fields(body, "restaurant_id", "check_id", "course_number")
    rest = must_exist(db.restaurants, body["restaurant_id"])
    chk = must_exist(db.checks, body["check_id"])
    course_number = require_int(body, "course_number", minimum=1)

    rec = {
        "restaurant_id": rest["id"],
        "check_id": chk["id"],
        "course_number": course_number,
        "status": "BUILDING",
        "fired_at": None,
    }
    stamp_create(rec, rest["current_utc"])
    db.courses[rec["id"]] = rec
    return success(serialize.course(rec), 201)


@app.route("/courses/<rid>", methods=["GET"])
@require_auth(["Manager", "Server", "KitchenStaff"])
def get_course(rid):
    rec = must_exist(db.courses, rid)
    return success(serialize.course(rec), 200)


@app.route("/courses", methods=["GET"])
@require_auth(["Manager", "Server", "KitchenStaff"])
def list_courses():
    restaurant_id = filter_eq("restaurant_id")
    check_id = filter_eq("check_id")

    def pred(r):
        if restaurant_id is not None and r["restaurant_id"] != restaurant_id:
            return False
        if check_id is not None and r["check_id"] != check_id:
            return False
        return True

    return list_response(db.courses, serialize.course, pred)


@app.route("/courses/<rid>/fire", methods=["POST"])
@require_auth(["Server"])
def fire_course(rid):
    rec = must_exist(db.courses, rid)
    chk = db.checks.get(rec["check_id"])
    # priority 5: state — course BUILDING and check OPEN
    if rec["status"] != "BUILDING":
        raise errors.invalid_state("Course must be BUILDING to fire.")
    if chk is None or chk["status"] != "OPEN":
        raise errors.invalid_state("Owning check must be OPEN to fire a course.")

    pending = [oi for oi in logic.items_for_course(rec["id"]) if oi["status"] == "PENDING"]
    # priority 8 (ERR_ITEM_86) vs priority 9 (ERR_EMPTY_COURSE):
    # scaffold lists 86 (priority 8) before empty-course (priority 9).
    # The 86 guard requires PENDING items to evaluate; with zero pending items
    # there is nothing to 86, so empty-course is the applicable failure.
    if not pending:
        raise errors.ApiError(errors.ERR_EMPTY_COURSE, 409,
                              "Course has no PENDING order items to fire.")
    # 86 guard: every pending item's menu item must have available_count >= quantity
    for oi in pending:
        mi = db.menu_items[oi["menu_item_id"]]
        if mi["available_count"] < oi["quantity"]:
            raise errors.ApiError(errors.ERR_ITEM_86, 409,
                                  "A pending item exceeds the menu item's available count (86'd).")

    rest = db.restaurants[rec["restaurant_id"]]
    clock = rest["current_utc"]
    in_window = logic.fired_at_in_window(rest["id"], clock)

    rec["fired_at"] = clock
    rec["status"] = "FIRED"
    touch(rec, clock)

    for oi in pending:
        mi = db.menu_items[oi["menu_item_id"]]
        unit_price = mi["happy_hour_price_cents"] if in_window else mi["base_price_cents"]
        oi["unit_price_cents"] = unit_price
        oi["line_subtotal_cents"] = logic.line_value(oi, unit_price)
        oi["status"] = "FIRED"
        mi["available_count"] -= oi["quantity"]
        touch(mi, clock)
        touch(oi, clock)

    logic.recompute_check_open(chk)
    touch(chk, clock)
    return success(serialize.course(rec), 200)


# ===========================================================================
# Order items
# ===========================================================================
@app.route("/order-items", methods=["POST"])
@require_auth(["Server"])
def create_order_item():
    body = get_body()
    require_fields(body, "restaurant_id", "course_id", "menu_item_id", "quantity")
    rest = must_exist(db.restaurants, body["restaurant_id"])
    course = must_exist(db.courses, body["course_id"])
    mi = must_exist(db.menu_items, body["menu_item_id"])
    quantity = require_int(body, "quantity", minimum=1)

    rec = {
        "restaurant_id": rest["id"],
        "course_id": course["id"],
        "menu_item_id": mi["id"],
        "quantity": quantity,
        "status": "PENDING",
        "unit_price_cents": 0,
        "line_subtotal_cents": 0,
        "comp_amount_cents": 0,
    }
    stamp_create(rec, rest["current_utc"])
    db.order_items[rec["id"]] = rec
    return success(serialize.order_item(rec), 201)


@app.route("/order-items/<rid>", methods=["GET"])
@require_auth(["Manager", "Server", "KitchenStaff"])
def get_order_item(rid):
    rec = must_exist(db.order_items, rid)
    return success(serialize.order_item(rec), 200)


@app.route("/order-items", methods=["GET"])
@require_auth(["Manager", "Server", "KitchenStaff"])
def list_order_items():
    restaurant_id = filter_eq("restaurant_id")
    course_id = filter_eq("course_id")
    menu_item_id = filter_eq("menu_item_id")
    status = filter_eq("status")

    def pred(r):
        if restaurant_id is not None and r["restaurant_id"] != restaurant_id:
            return False
        if course_id is not None and r["course_id"] != course_id:
            return False
        if menu_item_id is not None and r["menu_item_id"] != menu_item_id:
            return False
        if status is not None and r["status"] != status:
            return False
        return True

    return list_response(db.order_items, serialize.order_item, pred)


def _check_for_order_item(oi):
    course = db.courses.get(oi["course_id"])
    if course is None:
        return None
    return db.checks.get(course["check_id"])


@app.route("/order-items/<rid>/serve", methods=["POST"])
@require_auth(["KitchenStaff"])
def serve_order_item(rid):
    rec = must_exist(db.order_items, rid)
    if rec["status"] != "FIRED":
        raise errors.invalid_state("Order item must be FIRED to serve.")
    chk = _check_for_order_item(rec)
    clock = db.restaurants[rec["restaurant_id"]]["current_utc"]
    rec["status"] = "SERVED"
    touch(rec, clock)
    return success(serialize.order_item(rec), 200)


@app.route("/order-items/<rid>/void", methods=["POST"])
@require_auth(["Manager"])
def void_order_item(rid):
    rec = must_exist(db.order_items, rid)
    if rec["status"] not in ("FIRED", "SERVED"):
        raise errors.invalid_state("Order item must be FIRED or SERVED to void.")
    chk = _check_for_order_item(rec)
    if chk is None or chk["status"] not in ("OPEN", "PRESENTED"):
        raise errors.invalid_state("Owning check must be OPEN or PRESENTED to void an item.")

    rest = db.restaurants[rec["restaurant_id"]]
    clock = rest["current_utc"]

    # restore the 86-count
    mi = db.menu_items.get(rec["menu_item_id"])
    if mi is not None:
        mi["available_count"] += rec["quantity"]
        touch(mi, clock)

    rec["status"] = "VOIDED"
    touch(rec, clock)

    # recompute the owning check's totals (line drops out)
    _recompute_check_after_line_change(chk, clock)
    return success(serialize.order_item(rec), 200)


@app.route("/order-items/<rid>/comp", methods=["POST"])
@require_auth(["Manager"])
def comp_order_item(rid):
    rec = must_exist(db.order_items, rid)
    if rec["status"] not in ("FIRED", "SERVED"):
        raise errors.invalid_state("Order item must be FIRED or SERVED to comp.")
    chk = _check_for_order_item(rec)
    if chk is None or chk["status"] not in ("OPEN", "PRESENTED"):
        raise errors.invalid_state("Owning check must be OPEN or PRESENTED to comp an item.")

    rest = db.restaurants[rec["restaurant_id"]]
    clock = rest["current_utc"]

    # comp-cap fiscal guard: resulting comp_total must not exceed the cap
    base_subtotal = logic.base_subtotal_for_check(chk)
    existing_comp = sum(oi["comp_amount_cents"] for oi in logic.items_for_check(chk)
                        if oi["status"] == "COMPED")
    prospective_comp = existing_comp + rec["line_subtotal_cents"]
    cap = logic.comp_cap_for_check(chk, base_subtotal)
    if prospective_comp > cap:
        raise errors.ApiError(errors.ERR_COMP_CAP_EXCEEDED, 409,
                              "Comp would exceed the comp cap.")

    rec["comp_amount_cents"] = rec["line_subtotal_cents"]
    rec["status"] = "COMPED"
    # COMP does NOT restore available_count (portion consumed)
    touch(rec, clock)

    _recompute_check_after_line_change(chk, clock)
    return success(serialize.order_item(rec), 200)


def _recompute_check_after_line_change(chk, clock):
    """Recompute totals after a void/comp. While OPEN use provisional; while
    PRESENTED keep the locked final subtotal but re-resolve downstream money."""
    if chk["status"] == "PRESENTED" and chk["final_subtotal_cents"] is not None:
        # provisional still tracks gross lines; keep it current too
        chk["provisional_subtotal_cents"] = logic.provisional_subtotal(chk)
        logic.resolve_check_totals(chk, chk["final_subtotal_cents"])
    else:
        logic.recompute_check_open(chk)
    touch(chk, clock)


# ===========================================================================
# Item modifiers
# ===========================================================================
@app.route("/item-modifiers", methods=["POST"])
@require_auth(["Server"])
def create_item_modifier():
    body = get_body()
    require_fields(body, "restaurant_id", "order_item_id", "name", "surcharge_cents")
    rest = must_exist(db.restaurants, body["restaurant_id"])
    oi = must_exist(db.order_items, body["order_item_id"])
    name = require_str(body, "name")
    surcharge = require_int(body, "surcharge_cents", minimum=0)

    rec = {
        "restaurant_id": rest["id"],
        "order_item_id": oi["id"],
        "name": name,
        "surcharge_cents": surcharge,
    }
    stamp_create(rec, rest["current_utc"], versioned=False)
    db.item_modifiers[rec["id"]] = rec
    return success(serialize.item_modifier(rec), 201)


@app.route("/item-modifiers/<rid>", methods=["GET"])
@require_auth(["Manager", "Server", "KitchenStaff"])
def get_item_modifier(rid):
    rec = must_exist(db.item_modifiers, rid)
    return success(serialize.item_modifier(rec), 200)


@app.route("/item-modifiers", methods=["GET"])
@require_auth(["Manager", "Server", "KitchenStaff"])
def list_item_modifiers():
    restaurant_id = filter_eq("restaurant_id")
    order_item_id = filter_eq("order_item_id")

    def pred(r):
        if restaurant_id is not None and r["restaurant_id"] != restaurant_id:
            return False
        if order_item_id is not None and r["order_item_id"] != order_item_id:
            return False
        return True

    return list_response(db.item_modifiers, serialize.item_modifier, pred)


# ===========================================================================
# Payments
# ===========================================================================
@app.route("/payments", methods=["POST"])
@require_auth(["Server"])
def create_payment():
    body = get_body()
    require_fields(body, "restaurant_id", "check_id", "amount_cents", "tip_cents", "method")
    rest = must_exist(db.restaurants, body["restaurant_id"])
    chk = must_exist(db.checks, body["check_id"])
    amount = require_int(body, "amount_cents", minimum=0)
    tip = require_int(body, "tip_cents", minimum=0)
    method = require_enum(body, "method", {"CASH", "CARD", "GIFT"})

    rec = {
        "restaurant_id": rest["id"],
        "check_id": chk["id"],
        "amount_cents": amount,
        "tip_cents": tip,
        "method": method,
        "status": "SETTLED",
    }
    clock = rest["current_utc"]
    stamp_create(rec, clock)
    db.payments[rec["id"]] = rec

    logic.recompute_payment_aggregates(chk)
    touch(chk, clock)
    return success(serialize.payment(rec), 201)


@app.route("/payments/<rid>", methods=["GET"])
@require_auth(["Manager", "Server"])
def get_payment(rid):
    rec = must_exist(db.payments, rid)
    return success(serialize.payment(rec), 200)


@app.route("/payments", methods=["GET"])
@require_auth(["Manager", "Server"])
def list_payments():
    restaurant_id = filter_eq("restaurant_id")
    check_id = filter_eq("check_id")

    def pred(r):
        if restaurant_id is not None and r["restaurant_id"] != restaurant_id:
            return False
        if check_id is not None and r["check_id"] != check_id:
            return False
        return True

    return list_response(db.payments, serialize.payment, pred)


@app.route("/payments/<rid>/void", methods=["POST"])
@require_auth(["Manager"])
def void_payment(rid):
    rec = must_exist(db.payments, rid)
    if rec["status"] != "SETTLED":
        raise errors.invalid_state("Payment must be SETTLED to void.")
    chk = db.checks.get(rec["check_id"])
    if chk is None or chk["status"] not in ("OPEN", "PRESENTED"):
        raise errors.invalid_state("Owning check must be OPEN or PRESENTED to void a payment.")

    rest = db.restaurants[rec["restaurant_id"]]
    clock = rest["current_utc"]
    rec["status"] = "VOIDED"
    touch(rec, clock)

    logic.recompute_payment_aggregates(chk)
    touch(chk, clock)
    return success(serialize.payment(rec), 200)


# ===========================================================================
# Tip pools
# ===========================================================================
@app.route("/tip-pools", methods=["POST"])
@require_auth(["Manager"])
def create_tip_pool():
    body = get_body()
    require_fields(body, "restaurant_id", "business_date")
    rest = must_exist(db.restaurants, body["restaurant_id"])
    business_date = require_str(body, "business_date")
    distribution_mode = body.get("distribution_mode")
    if distribution_mode is None:
        distribution_mode = "EVEN_BY_HOURS"
    else:
        distribution_mode = require_enum(body, "distribution_mode",
                                         {"EVEN_BY_HOURS", "WEIGHTED_BY_ROLE"})

    rec = {
        "restaurant_id": rest["id"],
        "business_date": business_date,
        "distribution_mode": distribution_mode,
        "status": "ACCUMULATING",
        "pooled_cents": 0,
        "distributed_cents": 0,
    }
    stamp_create(rec, rest["current_utc"])
    db.tip_pools[rec["id"]] = rec
    return success(serialize.tip_pool(rec), 201)


@app.route("/tip-pools/<rid>", methods=["GET"])
@require_auth(["Manager"])
def get_tip_pool(rid):
    rec = must_exist(db.tip_pools, rid)
    return success(serialize.tip_pool(rec), 200)


@app.route("/tip-pools", methods=["GET"])
@require_auth(["Manager"])
def list_tip_pools():
    restaurant_id = filter_eq("restaurant_id")
    business_date = filter_eq("business_date")

    def pred(r):
        if restaurant_id is not None and r["restaurant_id"] != restaurant_id:
            return False
        if business_date is not None and r["business_date"] != business_date:
            return False
        return True

    return list_response(db.tip_pools, serialize.tip_pool, pred)


@app.route("/tip-pools/<rid>/distribute", methods=["POST"])
@require_auth(["Manager"])
def distribute_tip_pool(rid):
    pool = must_exist(db.tip_pools, rid)
    if pool["status"] != "ACCUMULATING":
        raise errors.invalid_state("Tip pool must be ACCUMULATING to distribute.")

    rest = db.restaurants[pool["restaurant_id"]]
    clock = rest["current_utc"]

    shifts = [s for s in db.staff_shifts.values()
              if s["restaurant_id"] == pool["restaurant_id"]
              and s["business_date"] == pool["business_date"]]
    # priority 15: pool empty — needs pooled_cents > 0 AND >= 1 shift
    if pool["pooled_cents"] <= 0 or not shifts:
        raise errors.ApiError(errors.ERR_POOL_EMPTY, 409,
                              "Pool has no tips or no staff shifts to distribute to.")

    shifts.sort(key=lambda s: s["_seq"])  # created_at ASC

    # weights
    if pool["distribution_mode"] == "EVEN_BY_HOURS":
        weights = [s["hours_worked_x100"] for s in shifts]
    else:  # WEIGHTED_BY_ROLE
        weights = []
        for s in shifts:
            staff = db.staff_members.get(s["staff_id"])
            tw = staff["tip_weight_bps"] if staff else 0
            weights.append(s["hours_worked_x100"] * tw)

    pooled = pool["pooled_cents"]
    total_weight = sum(weights)
    amounts = _waterfall_allocate(pooled, weights, shifts, total_weight)

    for s, amt in zip(shifts, amounts):
        alloc = {
            "restaurant_id": pool["restaurant_id"],
            "tip_pool_id": pool["id"],
            "staff_shift_id": s["id"],
            "amount_cents": amt,
        }
        stamp_create(alloc, clock, versioned=False)
        db.tip_allocations[alloc["id"]] = alloc

    pool["distributed_cents"] = sum(amounts)
    pool["status"] = "DISTRIBUTED"
    touch(pool, clock)
    return success(serialize.tip_pool(pool), 200)


def _waterfall_allocate(pooled, weights, shifts, total_weight):
    """Floor each raw share, then hand out remainder cents by descending
    fractional part (tie-break created_at ASC == _seq ASC)."""
    from decimal import Decimal
    if total_weight == 0:
        # No weighted basis; give everything to the first shift (created_at ASC).
        amounts = [0] * len(shifts)
        if amounts:
            amounts[0] = pooled
        return amounts

    raws = [Decimal(pooled) * Decimal(w) / Decimal(total_weight) for w in weights]
    floors = [int(r // 1) for r in raws]
    remainder = pooled - sum(floors)

    # order indices by (frac DESC, _seq ASC)
    fracs = [(raws[i] - floors[i], shifts[i]["_seq"], i) for i in range(len(shifts))]
    fracs.sort(key=lambda t: (-t[0], t[1]))
    for k in range(remainder):
        idx = fracs[k][2]
        floors[idx] += 1
    return floors


# ===========================================================================
# Tip allocations
# ===========================================================================
@app.route("/tip-allocations/<rid>", methods=["GET"])
@require_auth(["Manager"])
def get_tip_allocation(rid):
    rec = must_exist(db.tip_allocations, rid)
    return success(serialize.tip_allocation(rec), 200)


@app.route("/tip-allocations", methods=["GET"])
@require_auth(["Manager"])
def list_tip_allocations():
    restaurant_id = filter_eq("restaurant_id")
    tip_pool_id = filter_eq("tip_pool_id")
    staff_shift_id = filter_eq("staff_shift_id")

    def pred(r):
        if restaurant_id is not None and r["restaurant_id"] != restaurant_id:
            return False
        if tip_pool_id is not None and r["tip_pool_id"] != tip_pool_id:
            return False
        if staff_shift_id is not None and r["staff_shift_id"] != staff_shift_id:
            return False
        return True

    return list_response(db.tip_allocations, serialize.tip_allocation, pred)


# ===========================================================================
# Main
# ===========================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
