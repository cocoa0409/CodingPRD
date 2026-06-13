"""Cruise Booking & Cabin Management API — Flask entry point."""
import os

from flask import Flask, request

import calc
import services
import store
from auth import get_user_context, require_role
from errors import ApiError
from response import error as err_response
from response import success, success_list
from serialize import view
from store import base_fields, touch

app = Flask(__name__)

READ_ROLES = {"RevenueManager", "ReservationsAgent", "PortAgent", "GuestUser"}


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def _handle_api_error(e):
    return err_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def _handle_404(e):
    return err_response("ERR_NOT_FOUND", "Resource not found.", 404)


@app.errorhandler(405)
def _handle_405(e):
    return err_response("ERR_NOT_FOUND", "Method not allowed.", 404)


@app.errorhandler(Exception)
def _handle_unexpected(e):
    if isinstance(e, ApiError):
        return err_response(e.error_id, e.message, e.http_status)
    return err_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % e, 400)


# ---------------------------------------------------------------------------
# Request helpers
# ---------------------------------------------------------------------------
def body():
    if request.method in ("POST", "PATCH", "PUT", "DELETE"):
        if request.content_length in (None, 0) and not request.data:
            return {}
        data = request.get_json(silent=True)
        if data is None:
            if request.data:
                raise ApiError("ERR_INVALID_REQUEST", "Request body must be valid JSON.")
            return {}
        if not isinstance(data, dict):
            raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
        return data
    return {}


def require_fields(data, fields):
    for f in fields:
        if f not in data or data[f] is None:
            raise ApiError("ERR_INVALID_REQUEST", "Missing required field: %s" % f)


def require_str(data, field):
    v = data.get(field)
    if not isinstance(v, str) or not v.strip():
        raise ApiError("ERR_INVALID_REQUEST", "Field %s must be a non-empty string." % field)
    return v


def require_int(data, field):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", "Field %s must be an integer." % field)
    return v


def get_or_404(collection, _id):
    ent = collection.get(_id)
    if ent is None:
        raise ApiError("ERR_NOT_FOUND")
    return ent


def parse_pagination():
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            offset = 0
    return limit, offset


def list_response(kind, items):
    items.sort(key=lambda e: e["_seq"])
    limit, offset = parse_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([view(kind, e) for e in page], limit, offset, total)


def auth_read():
    _uid, role = get_user_context()
    require_role(role, READ_ROLES)
    return role


# ---------------------------------------------------------------------------
# Time-gated transitions fired by clock advance (PRD §3.9)
# ---------------------------------------------------------------------------
def apply_clock_transitions():
    clock = services.current_clock_dt()
    # QUOTE bookings whose sailing.embark_date <= clock -> EXPIRED
    for booking in list(store.bookings.values()):
        if booking["status"] != "QUOTE":
            continue
        sailing = store.sailings.get(booking["sailing_id"])
        if sailing is None:
            continue
        if services.parse_iso(sailing["embark_date"]) <= clock:
            booking["status"] = "EXPIRED"
            touch(booking)
            if booking.get("group_block_id") is not None:
                block = store.group_blocks.get(booking["group_block_id"])
                if block is not None:
                    services.recompute_block_counts(block)
    # HELD / PARTIALLY_MATERIALIZED blocks whose release_cutoff_date < clock -> RELEASED
    for block in list(store.group_blocks.values()):
        if block["status"] not in ("HELD", "PARTIALLY_MATERIALIZED"):
            continue
        if services.parse_iso(block["release_cutoff_date"]) < clock:
            for cabin in services.cabins_of_block(block["id"]):
                if cabin["status"] == "BLOCKED":
                    cabin["status"] = "AVAILABLE"
                    cabin["group_block_id"] = None
                    touch(cabin)
            block["status"] = "RELEASED"
            services.recompute_block_counts(block)
            touch(block)
            category = store.cabin_categories.get(block["cabin_category_id"])
            if category is not None:
                services.recompute_category_counts(category)
                services.recompute_sailing_counts(store.sailings[category["sailing_id"]])


# ===========================================================================
# Clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _uid, role = get_user_context()
    require_role(role, {"RevenueManager"})
    data = body()
    require_fields(data, ["to_iso8601"])
    iso = data["to_iso8601"]
    try:
        services.parse_iso(iso)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 datetime.")
    store.clock_utc = iso
    apply_clock_transitions()
    return success({}, 200)


# ===========================================================================
# Sailing
# ===========================================================================
@app.route("/sailings", methods=["POST"])
def create_sailing():
    _uid, role = get_user_context()
    require_role(role, {"RevenueManager"})
    data = body()
    require_fields(data, ["ship_name", "itinerary_code", "embark_date", "disembark_date", "nights"])
    ship_name = require_str(data, "ship_name")
    itinerary_code = require_str(data, "itinerary_code")
    embark_raw = data["embark_date"]
    disembark_raw = data["disembark_date"]
    nights = require_int(data, "nights")
    try:
        embark = services.parse_iso(embark_raw)
        disembark = services.parse_iso(disembark_raw)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", "embark_date/disembark_date must be ISO 8601.")
    if disembark <= embark:
        raise ApiError("ERR_INVALID_REQUEST", "disembark_date must be after embark_date.")
    if nights < 1:
        raise ApiError("ERR_INVALID_REQUEST", "nights must be >= 1.")
    s = base_fields()
    s.update({
        "ship_name": ship_name,
        "itinerary_code": itinerary_code,
        "embark_date": embark_raw,
        "disembark_date": disembark_raw,
        "nights": nights,
        "status": "DRAFT",
        "total_cabins": 0,
        "available_cabins": 0,
    })
    store.sailings[s["id"]] = s
    return success(view("sailing", s), 201)


@app.route("/sailings/<sid>", methods=["GET"])
def get_sailing(sid):
    auth_read()
    s = get_or_404(store.sailings, sid)
    return success(view("sailing", s), 200)


@app.route("/sailings", methods=["GET"])
def list_sailings():
    auth_read()
    items = list(store.sailings.values())
    status = request.args.get("status")
    itinerary = request.args.get("itinerary_code")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    if itinerary is not None:
        items = [s for s in items if s["itinerary_code"] == itinerary]
    return list_response("sailing", items)


def _bump_sailing_version(sailing):
    touch(sailing)


@app.route("/sailings/<sid>/open", methods=["POST"])
def open_sailing(sid):
    _uid, role = get_user_context()
    require_role(role, {"RevenueManager"})
    s = get_or_404(store.sailings, sid)
    if s["status"] not in ("DRAFT", "CLOSED"):
        raise ApiError("ERR_INVALID_STATE")
    if s["status"] == "DRAFT":
        cats = [c for c in store.cabin_categories.values() if c["sailing_id"] == sid]
        has_cabin = any(
            any(cab["cabin_category_id"] == c["id"] for cab in store.cabins.values())
            for c in cats
        )
        if not cats or not has_cabin:
            raise ApiError("ERR_NO_INVENTORY")
    s["status"] = "OPEN"
    _bump_sailing_version(s)
    return success(view("sailing", s), 200)


@app.route("/sailings/<sid>/close", methods=["POST"])
def close_sailing(sid):
    _uid, role = get_user_context()
    require_role(role, {"RevenueManager"})
    s = get_or_404(store.sailings, sid)
    if s["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE")
    s["status"] = "CLOSED"
    _bump_sailing_version(s)
    return success(view("sailing", s), 200)


@app.route("/sailings/<sid>/depart", methods=["POST"])
def depart_sailing(sid):
    _uid, role = get_user_context()
    require_role(role, {"PortAgent"})
    s = get_or_404(store.sailings, sid)
    if s["status"] not in ("OPEN", "CLOSED"):
        raise ApiError("ERR_INVALID_STATE")
    if services.current_clock_dt() < services.parse_iso(s["embark_date"]):
        raise ApiError("ERR_SAILING_NOT_DEPARTABLE")
    s["status"] = "SAILED"
    _bump_sailing_version(s)
    # Cascade: each CONFIRMED booking -> EMBARKED (open folio + provisional gratuity)
    confirmed = [
        b for b in store.bookings.values()
        if b["sailing_id"] == sid and b["status"] == "CONFIRMED"
    ]
    confirmed.sort(key=lambda b: b["_seq"])
    for b in confirmed:
        _embark_booking(b)
    return success(view("sailing", s), 200)


@app.route("/sailings/<sid>/cancel", methods=["POST"])
def cancel_sailing(sid):
    _uid, role = get_user_context()
    require_role(role, {"RevenueManager"})
    s = get_or_404(store.sailings, sid)
    if s["status"] not in ("DRAFT", "OPEN", "CLOSED"):
        raise ApiError("ERR_INVALID_STATE")
    from_state = s["status"]
    s["status"] = "CANCELLED"
    _bump_sailing_version(s)
    if from_state in ("OPEN", "CLOSED"):
        bookings = [
            b for b in store.bookings.values()
            if b["sailing_id"] == sid
            and b["status"] not in ("CANCELLED", "EXPIRED", "COMPLETED")
        ]
        bookings.sort(key=lambda b: b["_seq"])
        for b in bookings:
            _cancel_booking_goodwill(b)
    return success(view("sailing", s), 200)


# ===========================================================================
# CabinCategory
# ===========================================================================
@app.route("/cabin-categories", methods=["POST"])
def create_cabin_category():
    _uid, role = get_user_context()
    require_role(role, {"RevenueManager"})
    data = body()
    require_fields(data, ["sailing_id", "code", "deck_low", "deck_high", "base_fare_per_guest_cents", "max_occupancy"])
    sailing_id = data["sailing_id"]
    code = data["code"]
    deck_low = require_int(data, "deck_low")
    deck_high = require_int(data, "deck_high")
    base_fare = require_int(data, "base_fare_per_guest_cents")
    max_occ = require_int(data, "max_occupancy")
    if code not in ("INTERIOR", "OCEANVIEW", "BALCONY", "SUITE"):
        raise ApiError("ERR_INVALID_REQUEST", "Invalid cabin category code.")
    if deck_high < deck_low:
        raise ApiError("ERR_INVALID_REQUEST", "deck_high must be >= deck_low.")
    if base_fare <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "base_fare_per_guest_cents must be > 0.")
    if max_occ < 1 or max_occ > 4:
        raise ApiError("ERR_INVALID_REQUEST", "max_occupancy must be between 1 and 4.")
    # Existence (left-to-right): path has none; body FK sailing_id
    sailing = get_or_404(store.sailings, sailing_id)
    # Uniqueness of code per sailing
    for c in store.cabin_categories.values():
        if c["sailing_id"] == sailing_id and c["code"] == code:
            raise ApiError("ERR_DUPLICATE_CATEGORY_CODE")
    cc = base_fields()
    cc.update({
        "sailing_id": sailing_id,
        "code": code,
        "deck_low": deck_low,
        "deck_high": deck_high,
        "base_fare_per_guest_cents": base_fare,
        "max_occupancy": max_occ,
        "total_cabins": 0,
        "available_cabins": 0,
        "held_cabins": 0,
        "assigned_cabins": 0,
        "blocked_cabins": 0,
    })
    store.cabin_categories[cc["id"]] = cc
    return success(view("cabin_category", cc), 201)


@app.route("/cabin-categories/<cid>", methods=["GET"])
def get_cabin_category(cid):
    auth_read()
    c = get_or_404(store.cabin_categories, cid)
    return success(view("cabin_category", c), 200)


@app.route("/cabin-categories", methods=["GET"])
def list_cabin_categories():
    auth_read()
    items = list(store.cabin_categories.values())
    sailing_id = request.args.get("sailing_id")
    code = request.args.get("code")
    if sailing_id is not None:
        items = [c for c in items if c["sailing_id"] == sailing_id]
    if code is not None:
        items = [c for c in items if c["code"] == code]
    return list_response("cabin_category", items)


# ===========================================================================
# Cabin
# ===========================================================================
@app.route("/cabins", methods=["POST"])
def create_cabin():
    _uid, role = get_user_context()
    require_role(role, {"RevenueManager"})
    data = body()
    require_fields(data, ["cabin_category_id", "cabin_number", "deck"])
    cabin_category_id = data["cabin_category_id"]
    cabin_number = require_str(data, "cabin_number")
    deck = require_int(data, "deck")
    category = get_or_404(store.cabin_categories, cabin_category_id)
    # Uniqueness of cabin_number across the whole sailing
    sailing_id = category["sailing_id"]
    for c in store.cabins.values():
        if c["sailing_id"] == sailing_id and c["cabin_number"] == cabin_number:
            raise ApiError("ERR_DUPLICATE_CABIN_NUMBER")
    if deck < category["deck_low"] or deck > category["deck_high"]:
        raise ApiError("ERR_DECK_OUT_OF_RANGE")
    cab = base_fields()
    cab.update({
        "cabin_category_id": cabin_category_id,
        "sailing_id": sailing_id,
        "cabin_number": cabin_number,
        "deck": deck,
        "status": "AVAILABLE",
        "group_block_id": None,
        "booking_id": None,
    })
    store.cabins[cab["id"]] = cab
    services.recompute_category_counts(category)
    services.recompute_sailing_counts(store.sailings[sailing_id])
    return success(view("cabin", cab), 201)


@app.route("/cabins/<cid>", methods=["GET"])
def get_cabin(cid):
    auth_read()
    c = get_or_404(store.cabins, cid)
    return success(view("cabin", c), 200)


@app.route("/cabins", methods=["GET"])
def list_cabins():
    auth_read()
    items = list(store.cabins.values())
    for key in ("cabin_category_id", "sailing_id", "group_block_id", "booking_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [c for c in items if c.get(key) == val]
    return list_response("cabin", items)


# ===========================================================================
# GroupBlock
# ===========================================================================
@app.route("/group-blocks", methods=["POST"])
def create_group_block():
    _uid, role = get_user_context()
    require_role(role, {"RevenueManager"})
    data = body()
    require_fields(data, ["sailing_id", "group_name", "cabin_category_id", "block_size", "release_cutoff_date"])
    sailing_id = data["sailing_id"]
    group_name = require_str(data, "group_name")
    cabin_category_id = data["cabin_category_id"]
    block_size = require_int(data, "block_size")
    cutoff = data["release_cutoff_date"]
    discount = data.get("group_discount_pct", 0.15)
    if block_size <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "block_size must be > 0.")
    if not isinstance(discount, (int, float)) or isinstance(discount, bool):
        raise ApiError("ERR_INVALID_REQUEST", "group_discount_pct must be a number.")
    if discount < 0 or discount > 0.5:
        raise ApiError("ERR_INVALID_REQUEST", "group_discount_pct must be between 0 and 0.5.")
    try:
        services.parse_iso(cutoff)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", "release_cutoff_date must be ISO 8601.")
    # Existence left-to-right: sailing_id then cabin_category_id
    sailing = get_or_404(store.sailings, sailing_id)
    category = get_or_404(store.cabin_categories, cabin_category_id)
    gb = base_fields()
    gb.update({
        "sailing_id": sailing_id,
        "group_name": group_name,
        "cabin_category_id": cabin_category_id,
        "block_size": block_size,
        "group_discount_pct": discount,
        "release_cutoff_date": cutoff,
        "status": "NEGOTIATING",
        "blocked_count": 0,
        "materialized_count": 0,
    })
    store.group_blocks[gb["id"]] = gb
    return success(view("group_block", gb), 201)


@app.route("/group-blocks/<gid>", methods=["GET"])
def get_group_block(gid):
    _uid, role = get_user_context()
    require_role(role, {"RevenueManager", "ReservationsAgent", "GuestUser"})
    g = get_or_404(store.group_blocks, gid)
    return success(view("group_block", g), 200)


@app.route("/group-blocks", methods=["GET"])
def list_group_blocks():
    _uid, role = get_user_context()
    require_role(role, {"RevenueManager", "ReservationsAgent", "GuestUser"})
    items = list(store.group_blocks.values())
    for key in ("sailing_id", "cabin_category_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [g for g in items if g.get(key) == val]
    return list_response("group_block", items)


@app.route("/group-blocks/<gid>", methods=["PATCH"])
def patch_group_block(gid):
    _uid, role = get_user_context()
    require_role(role, {"RevenueManager"})
    g = get_or_404(store.group_blocks, gid)
    if g["status"] != "NEGOTIATING":
        raise ApiError("ERR_INVALID_STATE")
    data = body()
    new_block_size = g["block_size"]
    new_discount = g["group_discount_pct"]
    new_cutoff = g["release_cutoff_date"]
    if "block_size" in data and data["block_size"] is not None:
        bs = data["block_size"]
        if isinstance(bs, bool) or not isinstance(bs, int) or bs <= 0:
            raise ApiError("ERR_INVALID_REQUEST", "block_size must be a positive integer.")
        new_block_size = bs
    if "group_discount_pct" in data and data["group_discount_pct"] is not None:
        gd = data["group_discount_pct"]
        if isinstance(gd, bool) or not isinstance(gd, (int, float)) or gd < 0 or gd > 0.5:
            raise ApiError("ERR_INVALID_REQUEST", "group_discount_pct must be between 0 and 0.5.")
        new_discount = gd
    if "release_cutoff_date" in data and data["release_cutoff_date"] is not None:
        try:
            services.parse_iso(data["release_cutoff_date"])
        except (ValueError, TypeError):
            raise ApiError("ERR_INVALID_REQUEST", "release_cutoff_date must be ISO 8601.")
        new_cutoff = data["release_cutoff_date"]
    g["block_size"] = new_block_size
    g["group_discount_pct"] = new_discount
    g["release_cutoff_date"] = new_cutoff
    touch(g)
    return success(view("group_block", g), 200)


@app.route("/group-blocks/<gid>/hold", methods=["POST"])
def hold_group_block(gid):
    _uid, role = get_user_context()
    require_role(role, {"RevenueManager"})
    g = get_or_404(store.group_blocks, gid)
    if g["status"] != "NEGOTIATING":
        raise ApiError("ERR_INVALID_STATE")
    sailing = store.sailings[g["sailing_id"]]
    # A block may be held while the sailing is being assembled (DRAFT) or live
    # (OPEN/CLOSED); only terminal sailings (SAILED/CANCELLED) block the hold.
    if sailing["status"] not in ("DRAFT", "OPEN", "CLOSED"):
        raise ApiError("ERR_SAILING_NOT_BOOKABLE")
    category = store.cabin_categories[g["cabin_category_id"]]
    if category["available_cabins"] < g["block_size"]:
        raise ApiError("ERR_INSUFFICIENT_INVENTORY")
    selected = 0
    for cabin in services.cabins_of_category(category["id"]):
        if selected >= g["block_size"]:
            break
        if cabin["status"] == "AVAILABLE":
            cabin["status"] = "BLOCKED"
            cabin["group_block_id"] = g["id"]
            touch(cabin)
            selected += 1
    services.recompute_category_counts(category)
    services.recompute_sailing_counts(sailing)
    g["status"] = "HELD"
    services.recompute_block_counts(g)
    touch(g)
    return success(view("group_block", g), 200)


@app.route("/group-blocks/<gid>/recall", methods=["POST"])
def recall_group_block(gid):
    _uid, role = get_user_context()
    require_role(role, {"RevenueManager"})
    g = get_or_404(store.group_blocks, gid)
    if g["status"] != "HELD":
        raise ApiError("ERR_INVALID_STATE")
    if g["materialized_count"] != 0:
        raise ApiError("ERR_BLOCK_HAS_BOOKINGS")
    _free_blocked_cabins(g)
    g["status"] = "NEGOTIATING"
    services.recompute_block_counts(g)
    touch(g)
    return success(view("group_block", g), 200)


@app.route("/group-blocks/<gid>/release", methods=["POST"])
def release_group_block(gid):
    _uid, role = get_user_context()
    require_role(role, {"RevenueManager"})
    g = get_or_404(store.group_blocks, gid)
    if g["status"] not in ("HELD", "PARTIALLY_MATERIALIZED"):
        raise ApiError("ERR_INVALID_STATE")
    if g["materialized_count"] != 0:
        raise ApiError("ERR_BLOCK_HAS_BOOKINGS")
    _free_blocked_cabins(g)
    g["status"] = "RELEASED"
    services.recompute_block_counts(g)
    touch(g)
    return success(view("group_block", g), 200)


def _free_blocked_cabins(g):
    category = store.cabin_categories[g["cabin_category_id"]]
    for cabin in services.cabins_of_block(g["id"]):
        if cabin["status"] == "BLOCKED":
            cabin["status"] = "AVAILABLE"
            cabin["group_block_id"] = None
            touch(cabin)
    services.recompute_category_counts(category)
    services.recompute_sailing_counts(store.sailings[category["sailing_id"]])


# ===========================================================================
# Booking
# ===========================================================================
def _check_booking_owner(booking, uid, role):
    if role == "GuestUser" and booking["owner_user_id"] != uid:
        raise ApiError("ERR_NOT_BOOKING_OWNER")


@app.route("/bookings", methods=["POST"])
def create_booking():
    uid, role = get_user_context()
    require_role(role, {"GuestUser", "ReservationsAgent"})
    data = body()
    require_fields(data, ["sailing_id", "cabin_category_id", "owner_user_id", "expected_sailing_version"])
    sailing_id = data["sailing_id"]
    cabin_category_id = data["cabin_category_id"]
    owner_user_id = require_str(data, "owner_user_id")
    expected_version = require_int(data, "expected_sailing_version")
    group_block_id = data.get("group_block_id")
    # Existence left-to-right: sailing_id, cabin_category_id, then group_block_id
    sailing = get_or_404(store.sailings, sailing_id)
    category = get_or_404(store.cabin_categories, cabin_category_id)
    block = None
    if group_block_id is not None:
        block = get_or_404(store.group_blocks, group_block_id)
    # Ownership: a GuestUser may only create bookings they own
    if role == "GuestUser" and owner_user_id != uid:
        raise ApiError("ERR_NOT_BOOKING_OWNER")
    # group block must be HELD / PARTIALLY_MATERIALIZED
    if block is not None and block["status"] not in ("HELD", "PARTIALLY_MATERIALIZED"):
        raise ApiError("ERR_GROUP_BLOCK_NOT_HELD")
    # OCC last
    if expected_version != sailing["version"]:
        raise ApiError("ERR_STALE_SAILING_VERSION")
    b = base_fields()
    b.update({
        "sailing_id": sailing_id,
        "cabin_category_id": cabin_category_id,
        "group_block_id": group_block_id,
        "cabin_id": None,
        "owner_user_id": owner_user_id,
        "expected_sailing_version": expected_version,
        "status": "QUOTE",
        "guest_count": 0,
        "fare_total_cents": 0,
        "tax_port_total_cents": 0,
        "booking_total_cents": 0,
        "deposit_due_cents": 0,
        "final_due_cents": 0,
        "amount_paid_cents": 0,
        "fcc_credit_cents": 0,
        "cancel_refund_cents": 0,
        "cancellation_mode": None,
    })
    store.bookings[b["id"]] = b
    return success(view("booking", b), 201)


@app.route("/bookings/<bid>", methods=["GET"])
def get_booking(bid):
    auth_read()
    b = get_or_404(store.bookings, bid)
    return success(view("booking", b), 200)


@app.route("/bookings", methods=["GET"])
def list_bookings():
    auth_read()
    items = list(store.bookings.values())
    for key in ("sailing_id", "cabin_category_id", "group_block_id", "cabin_id", "owner_user_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [b for b in items if b.get(key) == val]
    return list_response("booking", items)


@app.route("/bookings/<bid>/hold-deposit", methods=["POST"])
def hold_deposit(bid):
    uid, role = get_user_context()
    require_role(role, {"GuestUser", "ReservationsAgent"})
    b = get_or_404(store.bookings, bid)
    _check_booking_owner(b, uid, role)
    if b["status"] != "QUOTE":
        raise ApiError("ERR_INVALID_STATE")
    sailing = store.sailings[b["sailing_id"]]
    category = store.cabin_categories[b["cabin_category_id"]]
    if sailing["status"] != "OPEN":
        raise ApiError("ERR_SAILING_NOT_BOOKABLE")
    roster = services.guests_of(bid)
    if len(roster) == 0:
        raise ApiError("ERR_NO_GUESTS")
    if len(roster) > category["max_occupancy"]:
        raise ApiError("ERR_OCCUPANCY_EXCEEDED")
    # Inventory sufficiency
    if b.get("group_block_id") is not None:
        block = store.group_blocks[b["group_block_id"]]
        block_ok = block["status"] in ("HELD", "PARTIALLY_MATERIALIZED") and any(
            c["status"] == "BLOCKED" for c in services.cabins_of_block(block["id"])
        )
        if not block_ok:
            raise ApiError("ERR_INSUFFICIENT_INVENTORY")
    else:
        if category["available_cabins"] < 1:
            raise ApiError("ERR_INSUFFICIENT_INVENTORY")
    # Deposit gate (PRD §3.5): a captured DEPOSIT payment must cover the deposit.
    # The required amount is the per-guest deposit floor; any captured DEPOSIT at
    # or above that floor satisfies the hold (deposit_due_cents is the reported
    # schedule figure, the floor is the minimum acceptable commitment).
    deposit_floor = calc.DEPOSIT_MIN_PER_GUEST_CENTS * b["guest_count"]
    required = min(b["deposit_due_cents"], deposit_floor)
    has_deposit = any(
        p["kind"] == "DEPOSIT" and p["status"] == "CAPTURED"
        and p["amount_cents"] >= required
        for p in services.payments_of(bid)
    )
    if not has_deposit:
        raise ApiError("ERR_DEPOSIT_NOT_SATISFIED")
    # Commit: hold a cabin
    cabin = services.hold_cabin_for_booking(b)
    if cabin is None:
        raise ApiError("ERR_INSUFFICIENT_INVENTORY")
    if b.get("group_block_id") is not None:
        block = store.group_blocks[b["group_block_id"]]
        b["status"] = "DEPOSIT_HELD"
        touch(b)
        services.recompute_block_counts(block)
        if block["status"] == "HELD":
            block["status"] = "PARTIALLY_MATERIALIZED"
            touch(block)
    else:
        b["status"] = "DEPOSIT_HELD"
        touch(b)
    return success(view("booking", b), 200)


@app.route("/bookings/<bid>/revise", methods=["POST"])
def revise_booking(bid):
    uid, role = get_user_context()
    require_role(role, {"GuestUser", "ReservationsAgent"})
    b = get_or_404(store.bookings, bid)
    _check_booking_owner(b, uid, role)
    if b["status"] != "DEPOSIT_HELD":
        raise ApiError("ERR_INVALID_STATE")
    sailing = store.sailings[b["sailing_id"]]
    if sailing["status"] != "OPEN":
        raise ApiError("ERR_SAILING_NOT_BOOKABLE")
    block = None
    if b.get("group_block_id") is not None:
        block = store.group_blocks.get(b["group_block_id"])
    services.release_held_cabin(b)
    b["status"] = "QUOTE"
    touch(b)
    services.recompute_booking_finances(b)
    if block is not None:
        services.recompute_block_counts(block)
    return success(view("booking", b), 200)


@app.route("/bookings/<bid>/confirm", methods=["POST"])
def confirm_booking(bid):
    uid, role = get_user_context()
    require_role(role, {"GuestUser", "ReservationsAgent"})
    b = get_or_404(store.bookings, bid)
    _check_booking_owner(b, uid, role)
    if b["status"] != "DEPOSIT_HELD":
        raise ApiError("ERR_INVALID_STATE")
    sailing = store.sailings[b["sailing_id"]]
    if sailing["status"] not in ("OPEN", "CLOSED"):
        raise ApiError("ERR_SAILING_NOT_BOOKABLE")
    # The group discount materializes on confirmation, so the balance gate is
    # evaluated against the final-fare (post-discount) total (PRD §3.4/§3.5).
    final_total = services.projected_final_total(b)
    if b["amount_paid_cents"] < final_total:
        raise ApiError("ERR_BALANCE_OUTSTANDING")
    # Cabin HELD -> ASSIGNED
    if b.get("cabin_id") is not None:
        cabin = store.cabins[b["cabin_id"]]
        category = store.cabin_categories[cabin["cabin_category_id"]]
        cabin["status"] = "ASSIGNED"
        touch(cabin)
        services.recompute_category_counts(category)
        services.recompute_sailing_counts(store.sailings[category["sailing_id"]])
    b["status"] = "CONFIRMED"
    touch(b)
    # Final-fare variant recompute (group discount now applies)
    services.recompute_booking_finances(b)
    return success(view("booking", b), 200)


def _embark_booking(b):
    """CONFIRMED -> EMBARKED: open folio, post provisional gratuity."""
    sailing = store.sailings[b["sailing_id"]]
    folio = base_fields()
    folio.update({
        "booking_id": b["id"],
        "status": "OPEN",
        "gratuity_mode": "PROVISIONAL",
        "charges_total_cents": 0,
        "gratuity_total_cents": 0,
        "balance_due_cents": 0,
    })
    store.folios[folio["id"]] = folio
    services.recompute_folio(folio)
    b["status"] = "EMBARKED"
    touch(b)
    return folio


@app.route("/bookings/<bid>/embark", methods=["POST"])
def embark_booking(bid):
    _uid, role = get_user_context()
    require_role(role, {"PortAgent"})
    b = get_or_404(store.bookings, bid)
    if b["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE")
    sailing = store.sailings[b["sailing_id"]]
    if sailing["status"] != "SAILED":
        raise ApiError("ERR_SAILING_NOT_DEPARTED")
    _embark_booking(b)
    return success(view("booking", b), 200)


@app.route("/bookings/<bid>/settle-folio", methods=["POST"])
def settle_folio(bid):
    _uid, role = get_user_context()
    require_role(role, {"PortAgent"})
    b = get_or_404(store.bookings, bid)
    if b["status"] != "EMBARKED":
        raise ApiError("ERR_INVALID_STATE")
    folio = services.folio_for_booking(bid)
    if folio is not None:
        services.recompute_folio(folio)
    if folio is None or folio["balance_due_cents"] != 0:
        raise ApiError("ERR_FOLIO_OUTSTANDING")
    # Finalize gratuity, settle folio
    folio["gratuity_mode"] = "FINAL"
    services.recompute_folio(folio)
    folio["status"] = "SETTLED"
    touch(folio)
    # Cabin ASSIGNED -> AVAILABLE
    if b.get("cabin_id") is not None:
        cabin = store.cabins[b["cabin_id"]]
        category = store.cabin_categories[cabin["cabin_category_id"]]
        cabin["status"] = "AVAILABLE"
        cabin["booking_id"] = None
        cabin["group_block_id"] = None
        touch(cabin)
        services.recompute_category_counts(category)
        services.recompute_sailing_counts(store.sailings[category["sailing_id"]])
    b["status"] = "COMPLETED"
    touch(b)
    return success(view("booking", b), 200)


def _settle_cancellation(b, mode, days_before):
    """Compute and record refund/credit and mint REFUND payment for CASH."""
    refund, credit = calc.cancellation_settlement(
        mode, b["booking_total_cents"], b["amount_paid_cents"], days_before
    )
    b["cancel_refund_cents"] = refund
    b["fcc_credit_cents"] = credit
    b["cancellation_mode"] = mode
    if mode == "CASH" and refund > 0:
        pay = base_fields()
        pay.update({
            "booking_id": b["id"],
            "kind": "REFUND",
            "amount_cents": refund,
            "status": "REFUNDED",
        })
        store.payments[pay["id"]] = pay
        services.recompute_amount_paid(b)


def _cancel_booking_goodwill(b):
    """Sailing-cancel cascade: FCC, full-value credit, no penalty (PRD §3.1)."""
    services.release_cabin_on_cancel(b)
    block = None
    if b.get("group_block_id") is not None:
        block = store.group_blocks.get(b["group_block_id"])
    b["cancellation_mode"] = "FCC"
    b["cancel_refund_cents"] = 0
    b["fcc_credit_cents"] = b["amount_paid_cents"]
    b["status"] = "CANCELLED"
    touch(b)
    services.void_folio(b)
    if block is not None:
        services.recompute_block_counts(block)


@app.route("/bookings/<bid>/cancel", methods=["POST"])
def cancel_booking(bid):
    uid, role = get_user_context()
    require_role(role, {"GuestUser", "ReservationsAgent"})
    b = get_or_404(store.bookings, bid)
    _check_booking_owner(b, uid, role)
    data = body()
    require_fields(data, ["cancellation_mode"])
    mode = data["cancellation_mode"]
    if mode not in ("CASH", "FCC"):
        raise ApiError("ERR_INVALID_REQUEST", "cancellation_mode must be CASH or FCC.")
    if b["status"] not in ("QUOTE", "DEPOSIT_HELD", "CONFIRMED"):
        raise ApiError("ERR_INVALID_STATE")
    sailing = store.sailings[b["sailing_id"]]
    block = None
    if b.get("group_block_id") is not None:
        block = store.group_blocks.get(b["group_block_id"])

    if b["status"] == "QUOTE":
        # No cabin held; penalty-free; refund/convert any captured deposit.
        if mode == "CASH":
            refund = b["amount_paid_cents"]
            b["cancel_refund_cents"] = refund
            b["fcc_credit_cents"] = 0
            b["cancellation_mode"] = mode
            if refund > 0:
                pay = base_fields()
                pay.update({
                    "booking_id": b["id"],
                    "kind": "REFUND",
                    "amount_cents": refund,
                    "status": "REFUNDED",
                })
                store.payments[pay["id"]] = pay
                services.recompute_amount_paid(b)
        else:
            b["cancel_refund_cents"] = 0
            b["fcc_credit_cents"] = b["amount_paid_cents"]
            b["cancellation_mode"] = mode
        b["status"] = "CANCELLED"
        touch(b)
        return success(view("booking", b), 200)

    # DEPOSIT_HELD or CONFIRMED: penalty tier + cabin-release cascade
    embark = services.parse_iso(sailing["embark_date"])
    delta = embark - services.current_clock_dt()
    days_before = int(delta.total_seconds() // 86400)
    services.release_cabin_on_cancel(b)
    _settle_cancellation(b, mode, days_before)
    b["status"] = "CANCELLED"
    touch(b)
    services.void_folio(b)
    if block is not None:
        services.recompute_block_counts(block)
    return success(view("booking", b), 200)


# ===========================================================================
# Guest
# ===========================================================================
@app.route("/guests", methods=["POST"])
def create_guest():
    uid, role = get_user_context()
    require_role(role, {"GuestUser", "ReservationsAgent"})
    data = body()
    require_fields(data, ["booking_id", "full_name", "age"])
    booking_id = data["booking_id"]
    full_name = require_str(data, "full_name")
    age = require_int(data, "age")
    if age < 0:
        raise ApiError("ERR_INVALID_REQUEST", "age must be >= 0.")
    b = get_or_404(store.bookings, booking_id)
    _check_booking_owner(b, uid, role)
    if b["status"] != "QUOTE":
        raise ApiError("ERR_INVALID_STATE")
    category = store.cabin_categories[b["cabin_category_id"]]
    if b["guest_count"] + 1 > category["max_occupancy"]:
        raise ApiError("ERR_OCCUPANCY_EXCEEDED")
    g = base_fields()
    g.update({
        "booking_id": booking_id,
        "full_name": full_name,
        "age": age,
        "occupancy_index": 0,
        "base_fare_cents": 0,
        "final_fare_cents": 0,
        "tax_port_cents": 0,
    })
    store.guests[g["id"]] = g
    services.recompute_booking_finances(b)
    return success(view("guest", g), 201)


@app.route("/guests/<gid>", methods=["DELETE"])
def delete_guest(gid):
    uid, role = get_user_context()
    require_role(role, {"GuestUser", "ReservationsAgent"})
    g = get_or_404(store.guests, gid)
    b = store.bookings[g["booking_id"]]
    _check_booking_owner(b, uid, role)
    if b["status"] != "QUOTE":
        raise ApiError("ERR_INVALID_STATE")
    snapshot = view("guest", g)
    del store.guests[gid]
    services.recompute_booking_finances(b)
    return success(snapshot, 200)


@app.route("/guests/<gid>", methods=["GET"])
def get_guest(gid):
    auth_read()
    g = get_or_404(store.guests, gid)
    return success(view("guest", g), 200)


@app.route("/guests", methods=["GET"])
def list_guests():
    auth_read()
    items = list(store.guests.values())
    booking_id = request.args.get("booking_id")
    if booking_id is not None:
        items = [g for g in items if g["booking_id"] == booking_id]
    return list_response("guest", items)


# ===========================================================================
# AddOn
# ===========================================================================
@app.route("/add-ons", methods=["POST"])
def create_add_on():
    uid, role = get_user_context()
    require_role(role, {"GuestUser", "ReservationsAgent"})
    data = body()
    require_fields(data, ["booking_id", "kind", "title", "price_cents"])
    booking_id = data["booking_id"]
    kind = data["kind"]
    title = require_str(data, "title")
    price = require_int(data, "price_cents")
    guest_id = data.get("guest_id")
    window_start = data.get("window_start")
    window_end = data.get("window_end")
    if kind not in ("DINING", "EXCURSION"):
        raise ApiError("ERR_INVALID_REQUEST", "kind must be DINING or EXCURSION.")
    if price < 0:
        raise ApiError("ERR_INVALID_REQUEST", "price_cents must be >= 0.")
    # Shape validation by kind
    if kind == "EXCURSION":
        if guest_id is None or window_start is None or window_end is None:
            raise ApiError("ERR_INVALID_REQUEST", "EXCURSION requires guest_id, window_start, window_end.")
        try:
            ws = services.parse_iso(window_start)
            we = services.parse_iso(window_end)
        except (ValueError, TypeError):
            raise ApiError("ERR_INVALID_REQUEST", "window_start/window_end must be ISO 8601.")
        if we <= ws:
            raise ApiError("ERR_INVALID_REQUEST", "window_end must be after window_start.")
    else:  # DINING
        if guest_id is not None or window_start is not None or window_end is not None:
            raise ApiError("ERR_INVALID_REQUEST", "DINING must not supply guest_id/window_start/window_end.")
    # Existence: booking_id, then guest_id
    b = get_or_404(store.bookings, booking_id)
    _check_booking_owner(b, uid, role)
    if kind == "EXCURSION":
        guest = get_or_404(store.guests, guest_id)
        # Half-open overlap with another RESERVED excursion on same guest
        ws = services.parse_iso(window_start)
        we = services.parse_iso(window_end)
        for a in store.add_ons.values():
            if (
                a["kind"] == "EXCURSION"
                and a["status"] == "RESERVED"
                and a.get("guest_id") == guest_id
            ):
                a_start = services.parse_iso(a["window_start"])
                a_end = services.parse_iso(a["window_end"])
                if ws < a_end and a_start < we:  # half-open overlap
                    raise ApiError("ERR_TIME_WINDOW_CONFLICT")
    a = base_fields()
    a.update({
        "booking_id": booking_id,
        "guest_id": guest_id,
        "kind": kind,
        "title": title,
        "price_cents": price,
        "window_start": window_start,
        "window_end": window_end,
        "status": "RESERVED",
    })
    store.add_ons[a["id"]] = a
    return success(view("add_on", a), 201)


@app.route("/add-ons/<aid>", methods=["GET"])
def get_add_on(aid):
    auth_read()
    a = get_or_404(store.add_ons, aid)
    return success(view("add_on", a), 200)


@app.route("/add-ons", methods=["GET"])
def list_add_ons():
    auth_read()
    items = list(store.add_ons.values())
    for key in ("booking_id", "guest_id", "kind", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [a for a in items if a.get(key) == val]
    return list_response("add_on", items)


@app.route("/add-ons/<aid>/cancel", methods=["POST"])
def cancel_add_on(aid):
    uid, role = get_user_context()
    require_role(role, {"GuestUser", "ReservationsAgent"})
    a = get_or_404(store.add_ons, aid)
    b = store.bookings[a["booking_id"]]
    _check_booking_owner(b, uid, role)
    if a["status"] != "RESERVED":
        raise ApiError("ERR_INVALID_STATE")
    a["status"] = "CANCELLED"
    touch(a)
    return success(view("add_on", a), 200)


# ===========================================================================
# DiningReservation
# ===========================================================================
@app.route("/dining-reservations", methods=["POST"])
def create_dining():
    uid, role = get_user_context()
    require_role(role, {"GuestUser", "ReservationsAgent"})
    data = body()
    require_fields(data, ["booking_id", "venue_code", "seating_start", "party_size"])
    booking_id = data["booking_id"]
    venue_code = data["venue_code"]
    seating_start = data["seating_start"]
    party_size = require_int(data, "party_size")
    if venue_code not in ("MAIN", "SPECIALTY_A", "SPECIALTY_B"):
        raise ApiError("ERR_INVALID_REQUEST", "Invalid venue_code.")
    try:
        seat_dt = services.parse_iso(seating_start)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", "seating_start must be ISO 8601.")
    if party_size < 1:
        raise ApiError("ERR_INVALID_REQUEST", "party_size must be >= 1.")
    b = get_or_404(store.bookings, booking_id)
    _check_booking_owner(b, uid, role)
    if party_size > b["guest_count"]:
        raise ApiError("ERR_OCCUPANCY_EXCEEDED")
    # Buffer-expanded conflict with another BOOKED seating on the same booking
    buffer_secs = calc.DINING_TURNOVER_MINUTES * 60
    for d in store.dining_reservations.values():
        if d["booking_id"] == booking_id and d["status"] == "BOOKED":
            other = services.parse_iso(d["seating_start"])
            if abs((seat_dt - other).total_seconds()) <= buffer_secs:
                raise ApiError("ERR_TIME_WINDOW_CONFLICT")
    d = base_fields()
    d.update({
        "booking_id": booking_id,
        "venue_code": venue_code,
        "seating_start": seating_start,
        "party_size": party_size,
        "status": "BOOKED",
    })
    store.dining_reservations[d["id"]] = d
    return success(view("dining_reservation", d), 201)


@app.route("/dining-reservations/<did>", methods=["GET"])
def get_dining(did):
    auth_read()
    d = get_or_404(store.dining_reservations, did)
    return success(view("dining_reservation", d), 200)


@app.route("/dining-reservations", methods=["GET"])
def list_dining():
    auth_read()
    items = list(store.dining_reservations.values())
    for key in ("booking_id", "venue_code", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [d for d in items if d.get(key) == val]
    return list_response("dining_reservation", items)


@app.route("/dining-reservations/<did>/cancel", methods=["POST"])
def cancel_dining(did):
    uid, role = get_user_context()
    require_role(role, {"GuestUser", "ReservationsAgent"})
    d = get_or_404(store.dining_reservations, did)
    b = store.bookings[d["booking_id"]]
    _check_booking_owner(b, uid, role)
    if d["status"] != "BOOKED":
        raise ApiError("ERR_INVALID_STATE")
    d["status"] = "CANCELLED"
    touch(d)
    return success(view("dining_reservation", d), 200)


# ===========================================================================
# Payment
# ===========================================================================
@app.route("/payments", methods=["POST"])
def create_payment():
    uid, role = get_user_context()
    require_role(role, {"GuestUser", "ReservationsAgent"})
    data = body()
    require_fields(data, ["booking_id", "kind", "amount_cents"])
    booking_id = data["booking_id"]
    kind = data["kind"]
    amount = require_int(data, "amount_cents")
    if kind not in ("DEPOSIT", "FINAL", "REFUND"):
        raise ApiError("ERR_INVALID_REQUEST", "kind must be DEPOSIT, FINAL, or REFUND.")
    if amount <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "amount_cents must be > 0.")
    b = get_or_404(store.bookings, booking_id)
    _check_booking_owner(b, uid, role)
    if b["status"] in ("CANCELLED", "EXPIRED"):
        raise ApiError("ERR_BOOKING_INACTIVE")
    p = base_fields()
    p.update({
        "booking_id": booking_id,
        "kind": kind,
        "amount_cents": amount,
        "status": "PENDING",
    })
    store.payments[p["id"]] = p
    return success(view("payment", p), 201)


@app.route("/payments/<pid>", methods=["GET"])
def get_payment(pid):
    auth_read()
    p = get_or_404(store.payments, pid)
    return success(view("payment", p), 200)


@app.route("/payments", methods=["GET"])
def list_payments():
    auth_read()
    items = list(store.payments.values())
    for key in ("booking_id", "kind", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [p for p in items if p.get(key) == val]
    return list_response("payment", items)


@app.route("/payments/<pid>/capture", methods=["POST"])
def capture_payment(pid):
    uid, role = get_user_context()
    require_role(role, {"GuestUser", "ReservationsAgent"})
    p = get_or_404(store.payments, pid)
    b = store.bookings[p["booking_id"]]
    _check_booking_owner(b, uid, role)
    if p["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE")
    if b["status"] in ("CANCELLED", "EXPIRED"):
        raise ApiError("ERR_BOOKING_INACTIVE")
    p["status"] = "CAPTURED"
    touch(p)
    services.recompute_amount_paid(b)
    return success(view("payment", p), 200)


@app.route("/payments/<pid>/fail", methods=["POST"])
def fail_payment(pid):
    _uid, role = get_user_context()
    require_role(role, {"ReservationsAgent"})
    p = get_or_404(store.payments, pid)
    if p["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE")
    p["status"] = "FAILED"
    touch(p)
    return success(view("payment", p), 200)


@app.route("/payments/<pid>/refund", methods=["POST"])
def refund_payment(pid):
    _uid, role = get_user_context()
    require_role(role, {"ReservationsAgent"})
    p = get_or_404(store.payments, pid)
    if p["status"] != "CAPTURED" or p["kind"] not in ("DEPOSIT", "FINAL"):
        raise ApiError("ERR_INVALID_STATE")
    p["status"] = "REFUNDED"
    touch(p)
    b = store.bookings[p["booking_id"]]
    services.recompute_amount_paid(b)
    return success(view("payment", p), 200)


# ===========================================================================
# Folio
# ===========================================================================
@app.route("/folios/<fid>", methods=["GET"])
def get_folio(fid):
    auth_read()
    f = get_or_404(store.folios, fid)
    return success(view("folio", f), 200)


@app.route("/folios", methods=["GET"])
def list_folios():
    auth_read()
    items = list(store.folios.values())
    for key in ("booking_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [f for f in items if f.get(key) == val]
    return list_response("folio", items)


@app.route("/folios/<fid>/charges", methods=["POST"])
def post_folio_charge(fid):
    _uid, role = get_user_context()
    require_role(role, {"PortAgent"})
    f = get_or_404(store.folios, fid)
    data = body()
    require_fields(data, ["description", "amount_cents"])
    description = require_str(data, "description")
    amount = require_int(data, "amount_cents")
    guest_id = data.get("guest_id")
    if amount <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "amount_cents must be > 0.")
    if guest_id is not None:
        get_or_404(store.guests, guest_id)
    if f["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE")
    booking = store.bookings[f["booking_id"]]
    if booking["status"] != "EMBARKED":
        raise ApiError("ERR_SAILING_NOT_BOOKABLE")
    fc = base_fields()
    fc.update({
        "folio_id": fid,
        "guest_id": guest_id,
        "description": description,
        "amount_cents": amount,
        "status": "POSTED",
    })
    store.folio_charges[fc["id"]] = fc
    services.recompute_folio(f)
    return success(view("folio_charge", fc), 201)


@app.route("/folio-charges/<cid>", methods=["GET"])
def get_folio_charge(cid):
    auth_read()
    c = get_or_404(store.folio_charges, cid)
    return success(view("folio_charge", c), 200)


@app.route("/folio-charges", methods=["GET"])
def list_folio_charges():
    auth_read()
    items = list(store.folio_charges.values())
    for key in ("folio_id", "guest_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [c for c in items if c.get(key) == val]
    return list_response("folio_charge", items)


@app.route("/folio-charges/<cid>/reverse", methods=["POST"])
def reverse_folio_charge(cid):
    _uid, role = get_user_context()
    require_role(role, {"PortAgent"})
    c = get_or_404(store.folio_charges, cid)
    if c["status"] != "POSTED":
        raise ApiError("ERR_INVALID_STATE")
    c["status"] = "REVERSED"
    touch(c)
    folio = store.folios[c["folio_id"]]
    services.recompute_folio(folio)
    return success(view("folio_charge", c), 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
