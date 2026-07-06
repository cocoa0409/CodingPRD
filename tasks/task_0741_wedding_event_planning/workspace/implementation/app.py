"""Wedding & Event Planning API — Flask implementation.

Storage is in-memory only (see store.py); the store is empty on every boot.
Validation gate order (PRD 2.7): auth -> role -> ownership -> existence ->
body validation -> interval -> OCC -> state transition -> business rules.
"""
import os
from decimal import Decimal

from flask import Flask, jsonify, request

import store
from store import serialize, touch, new_common
from util import (
    ApiError,
    parse_dt,
    now_iso,
    fmt_dt,
    rhu,
    gen_request_id,
)

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

VALID_ROLES = {"Planner", "Client", "Vendor"}

# --- enum domains ---
PACKAGE_TYPES = {"FULL", "PARTIAL", "DAY_OF"}
VENDOR_CATEGORIES = {"CATERING", "FLORAL", "RENTAL", "PHOTO", "VENUE", "STAFFING", "OTHER"}
ZONES = {"CEREMONY_SPACE", "RECEPTION_HALL", "KITCHEN", "LOADING_DOCK", "SUITE"}
BLOCK_TYPES = {"LOAD_IN", "SETUP", "CEREMONY", "COCKTAIL", "RECEPTION", "TEARDOWN"}
MEAL_CHOICES = {"NONE", "STANDARD", "VEGETARIAN", "VEGAN", "KIDS"}
ROLE_TITLES = {"COORDINATOR", "SERVER", "BARTENDER", "SECURITY", "RUNNER"}
RSVP_TARGETS = {"ACCEPTED", "DECLINED"}

# --- calculation constants ---
FLAT_DAY_OF = 250000
BASE_PARTIAL = 400000
PER_GUEST = 5000
BASE_FULL = 800000
FULL_TIER_1 = 5000000
FULL_TIER_2 = 15000000
DEPOSIT_RATE = Decimal("0.30")
BUFFER_MIN = 30
FAR_DAYS = 90
NEAR_DAYS = 30


# =========================================================================
# Response envelope helpers
# =========================================================================
def _meta(pagination=None):
    m = {
        "api_request_id": gen_request_id(),
        "api_request_timestamp": now_iso(),
    }
    if pagination:
        m.update(pagination)
    return m


def ok(data, status=200, is_list=False, pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": "array" if is_list else "object",
        "data": data,
    }
    return jsonify(body), status


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.status


# =========================================================================
# Auth / body / existence helpers
# =========================================================================
def require_auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in VALID_ROLES:
        raise ApiError("ERR_MISSING_OR_INVALID_HEADERS")
    return uid, role


def authorize(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED")


def get_body():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return {}
    return body


def must_exist(coll, val, err):
    """Existence gate for a single referenced id (skip if absent/None)."""
    if val is None:
        return None
    ent = coll.get(val) if isinstance(val, str) else None
    if ent is None:
        raise ApiError(err)
    return ent


# --- body field validators (raise ERR_VALIDATION) ---
def v_str(body, key, required=True):
    if key not in body or body[key] is None:
        if required:
            raise ApiError("ERR_VALIDATION", f"{key} is required")
        return None
    val = body[key]
    if not isinstance(val, str):
        raise ApiError("ERR_VALIDATION", f"{key} must be a string")
    return val


def v_int(body, key, required=True, minimum=None):
    if key not in body or body[key] is None:
        if required:
            raise ApiError("ERR_VALIDATION", f"{key} is required")
        return None
    val = body[key]
    if isinstance(val, bool) or not isinstance(val, int):
        raise ApiError("ERR_VALIDATION", f"{key} must be an integer")
    if minimum is not None and val < minimum:
        raise ApiError("ERR_VALIDATION", f"{key} must be >= {minimum}")
    return val


def v_enum(body, key, allowed, required=True, default=None):
    if key not in body or body[key] is None:
        if required:
            raise ApiError("ERR_VALIDATION", f"{key} is required")
        return default
    val = body[key]
    if val not in allowed:
        raise ApiError("ERR_VALIDATION", f"{key} is not a valid value")
    return val


def v_dt(body, key, required=True):
    if key not in body or body[key] is None:
        if required:
            raise ApiError("ERR_VALIDATION", f"{key} is required")
        return None, None
    val = body[key]
    try:
        dt = parse_dt(val)
    except Exception:
        raise ApiError("ERR_VALIDATION", f"{key} is not a valid timestamp")
    return val, dt


def get_pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def list_response(coll, filters):
    items = [e for e in coll.values() if all(e.get(k) == val for k, val in filters.items())]
    items.sort(key=lambda e: e["_seq"])
    limit, offset = get_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return ok([serialize(e) for e in page], 200, is_list=True, pagination=pagination)


# =========================================================================
# Calculations
# =========================================================================
def calc_planner_fee(package_type, budget, guest_count):
    if package_type == "DAY_OF":
        return FLAT_DAY_OF
    if package_type == "PARTIAL":
        return BASE_PARTIAL + PER_GUEST * guest_count
    # FULL
    if budget <= FULL_TIER_1:
        rate = Decimal("0.12")
    elif budget <= FULL_TIER_2:
        rate = Decimal("0.15")
    else:
        rate = Decimal("0.18")
    return BASE_FULL + rhu(rate * Decimal(budget))


def calc_deposit_split(contracted):
    deposit = rhu(DEPOSIT_RATE * Decimal(contracted))
    balance = contracted - deposit
    return deposit, balance


def calc_cancellation_fee(planner_fee, event_dt, clock_dt):
    days = (event_dt - clock_dt).days
    if days >= FAR_DAYS:
        rate = Decimal("0.25")
    elif days >= NEAR_DAYS:
        rate = Decimal("0.50")
    else:
        rate = Decimal("1.00")
    return rhu(rate * Decimal(planner_fee))


def calc_staff_labor(rate_cents, start, end):
    minutes = end - start
    return rhu(Decimal(rate_cents * minutes) / Decimal(60))


def recompute_budget(event):
    evid = event["id"]
    ev_bookings = [b for b in store.bookings.values() if b["event_id"] == evid]
    committed = sum(
        b["contracted_cost_cents"]
        for b in ev_bookings
        if b["status"] in ("BOOKED", "COMPLETED")
    )
    projected = sum(
        (b["contracted_cost_cents"] if b["status"] in ("BOOKED", "COMPLETED")
         else b["estimated_cost_cents"])
        for b in ev_bookings
        if b["status"] in ("PROPOSED", "BOOKED", "COMPLETED")
    )
    deposits_due = sum(
        rhu(DEPOSIT_RATE * Decimal(b["contracted_cost_cents"]))
        for b in ev_bookings
        if b["status"] == "BOOKED"
    )
    event["committed_spend_cents"] = committed
    event["projected_spend_cents"] = projected
    event["budget_balance_cents"] = event["total_budget_cents"] - committed
    event["total_deposits_due_cents"] = deposits_due


def recompute_headcount(event):
    evid = event["id"]
    ev_guests = [g for g in store.guests.values() if g["event_id"] == evid]
    event["estimated_headcount"] = sum(
        g["party_size"] for g in ev_guests if g["rsvp_status"] in ("INVITED", "ACCEPTED")
    )
    event["confirmed_headcount"] = sum(
        g["party_size"] for g in ev_guests if g["rsvp_status"] == "ACCEPTED"
    )


# =========================================================================
# Health
# =========================================================================
@app.route("/")
def health():
    return jsonify({"status": "ok"}), 200


# =========================================================================
# Logical clock
# =========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _uid, role = require_auth()
    authorize(role, {"Planner"})
    body = get_body()
    raw, dt = v_dt(body, "to_iso8601")
    store.clock_dt = dt
    store.clock_raw = raw
    # sweep insurance: PENDING/VERIFIED with expiry <= new clock -> EXPIRED
    for coi in store.cois.values():
        if coi["status"] in ("PENDING", "VERIFIED") and coi["_coverage_expiry"] <= dt:
            coi["status"] = "EXPIRED"
            touch(coi)
    return ok({}, 200)


# =========================================================================
# EventProject
# =========================================================================
@app.route("/planning/events", methods=["POST"])
def create_event():
    _uid, role = require_auth()
    authorize(role, {"Planner"})
    body = get_body()
    couple_names = v_str(body, "couple_names")
    event_date_raw, event_date_dt = v_dt(body, "event_date")
    venue_name = v_str(body, "venue_name")
    package_type = v_enum(body, "package_type", PACKAGE_TYPES)
    total_budget = v_int(body, "total_budget_cents", minimum=0)
    guest_estimate = v_int(body, "guest_count_estimate", minimum=0)

    ent = new_common()
    ent.update({
        "couple_names": couple_names,
        "event_date": event_date_raw,
        "_event_date": event_date_dt,
        "venue_name": venue_name,
        "package_type": package_type,
        "total_budget_cents": total_budget,
        "guest_count_estimate": guest_estimate,
        "active_contract_id": None,
        "committed_spend_cents": 0,
        "projected_spend_cents": 0,
        "budget_balance_cents": total_budget,
        "total_deposits_due_cents": 0,
        "estimated_headcount": 0,
        "confirmed_headcount": 0,
        "cancellation_fee_cents": 0,
        "status": "DRAFT",
    })
    store.events[ent["id"]] = ent
    return ok(serialize(ent), 201)


@app.route("/planning/events", methods=["GET"])
def list_events():
    _uid, role = require_auth()
    authorize(role, VALID_ROLES)
    filters = {}
    if request.args.get("status") is not None:
        filters["status"] = request.args.get("status")
    return list_response(store.events, filters)


@app.route("/planning/events/<eid>", methods=["GET"])
def get_event(eid):
    _uid, role = require_auth()
    authorize(role, VALID_ROLES)
    ev = must_exist(store.events, eid, "ERR_EVENT_NOT_FOUND")
    return ok(serialize(ev), 200)


@app.route("/planning/events/<eid>/confirm", methods=["POST"])
def confirm_event(eid):
    _uid, role = require_auth()
    authorize(role, {"Planner"})
    ev = must_exist(store.events, eid, "ERR_EVENT_NOT_FOUND")
    if ev["status"] != "DRAFT":
        raise ApiError("ERR_EVENT_NOT_DRAFT")
    contract = store.contracts.get(ev["active_contract_id"]) if ev["active_contract_id"] else None
    if contract is None or contract["status"] != "COUNTERSIGNED":
        raise ApiError("ERR_CONTRACT_NOT_COUNTERSIGNED")
    ev["status"] = "BOOKING"
    touch(ev)
    return ok(serialize(ev), 200)


@app.route("/planning/events/<eid>/complete", methods=["POST"])
def complete_event(eid):
    _uid, role = require_auth()
    authorize(role, {"Planner"})
    ev = must_exist(store.events, eid, "ERR_EVENT_NOT_FOUND")
    if ev["status"] != "BOOKING":
        raise ApiError("ERR_EVENT_NOT_BOOKING")
    if store.clock_dt < ev["_event_date"]:
        raise ApiError("ERR_EVENT_DATE_NOT_REACHED")
    ev_bookings = [b for b in store.bookings.values() if b["event_id"] == eid]
    if any(b["status"] == "PROPOSED" for b in ev_bookings):
        raise ApiError("ERR_UNRESOLVED_BOOKINGS")
    # cascade: BOOKED bookings -> COMPLETED
    for b in ev_bookings:
        if b["status"] == "BOOKED":
            b["status"] = "COMPLETED"
            touch(b)
    recompute_budget(ev)
    ev["status"] = "COMPLETED"
    touch(ev)
    return ok(serialize(ev), 200)


@app.route("/planning/events/<eid>/cancel", methods=["POST"])
def cancel_event(eid):
    _uid, role = require_auth()
    authorize(role, {"Planner"})
    ev = must_exist(store.events, eid, "ERR_EVENT_NOT_FOUND")
    if ev["status"] not in ("DRAFT", "BOOKING"):
        raise ApiError("ERR_EVENT_NOT_CANCELLABLE")

    contract = store.contracts.get(ev["active_contract_id"]) if ev["active_contract_id"] else None
    planner_fee = contract["planner_fee_cents"] if contract else 0
    fee = calc_cancellation_fee(planner_fee, ev["_event_date"], store.clock_dt)

    # void active contract if present and not already VOID
    if contract is not None and contract["status"] != "VOID":
        contract["status"] = "VOID"
        touch(contract)

    # cascade-cancel non-terminal bookings (voids their scheduled payments)
    for b in [b for b in store.bookings.values() if b["event_id"] == eid]:
        if b["status"] in ("PROPOSED", "BOOKED"):
            b["status"] = "CANCELLED"
            touch(b)
            for p in store.payments.values():
                if p["vendor_booking_id"] == b["id"] and p["status"] == "SCHEDULED":
                    p["status"] = "VOID"
                    touch(p)

    recompute_budget(ev)
    ev["cancellation_fee_cents"] = fee
    ev["status"] = "CANCELLED"
    touch(ev)
    return ok(serialize(ev), 200)


# =========================================================================
# Contract
# =========================================================================
@app.route("/planning/contracts", methods=["POST"])
def create_contract():
    _uid, role = require_auth()
    authorize(role, {"Planner"})
    body = get_body()
    # existence (gate 4) before body validation (gate 5)
    event = must_exist(store.events, body.get("event_id"), "ERR_EVENT_NOT_FOUND")
    v_str(body, "event_id")
    expected = v_int(body, "expected_event_version")
    # OCC (gate 7)
    if expected != event["version"]:
        raise ApiError("ERR_STALE_EVENT_VERSION")

    # supersede prior active contract
    prior = store.contracts.get(event["active_contract_id"]) if event["active_contract_id"] else None
    if prior is not None and prior["status"] != "VOID":
        prior["status"] = "VOID"
        touch(prior)

    fee = calc_planner_fee(
        event["package_type"], event["total_budget_cents"], event["guest_count_estimate"]
    )
    ent = new_common()
    ent.update({
        "event_id": event["id"],
        "package_type": event["package_type"],
        "planner_fee_cents": fee,
        "revision_count": 0,
        "signed_at": None,
        "status": "DRAFT",
    })
    store.contracts[ent["id"]] = ent

    event["active_contract_id"] = ent["id"]
    touch(event)  # increments event version by one
    return ok(serialize(ent), 201)


@app.route("/planning/contracts", methods=["GET"])
def list_contracts():
    _uid, role = require_auth()
    authorize(role, VALID_ROLES)
    filters = {}
    if request.args.get("event_id") is not None:
        filters["event_id"] = request.args.get("event_id")
    return list_response(store.contracts, filters)


@app.route("/planning/contracts/<cid>", methods=["GET"])
def get_contract(cid):
    _uid, role = require_auth()
    authorize(role, VALID_ROLES)
    c = must_exist(store.contracts, cid, "ERR_CONTRACT_NOT_FOUND")
    return ok(serialize(c), 200)


@app.route("/planning/contracts/<cid>/send", methods=["POST"])
def send_contract(cid):
    _uid, role = require_auth()
    authorize(role, {"Planner"})
    c = must_exist(store.contracts, cid, "ERR_CONTRACT_NOT_FOUND")
    if c["status"] != "DRAFT":
        raise ApiError("ERR_CONTRACT_NOT_DRAFT")
    c["status"] = "SENT"
    touch(c)
    return ok(serialize(c), 200)


@app.route("/planning/contracts/<cid>/sign", methods=["POST"])
def sign_contract(cid):
    uid, role = require_auth()
    authorize(role, {"Client"})
    c = must_exist(store.contracts, cid, "ERR_CONTRACT_NOT_FOUND")
    if c["event_id"] != uid:
        raise ApiError("ERR_OWNERSHIP_VIOLATION")
    if c["status"] != "SENT":
        raise ApiError("ERR_CONTRACT_NOT_SENT")
    c["status"] = "SIGNED"
    c["signed_at"] = store.clock_raw
    touch(c)
    return ok(serialize(c), 200)


@app.route("/planning/contracts/<cid>/countersign", methods=["POST"])
def countersign_contract(cid):
    _uid, role = require_auth()
    authorize(role, {"Planner"})
    c = must_exist(store.contracts, cid, "ERR_CONTRACT_NOT_FOUND")
    if c["status"] != "SIGNED":
        raise ApiError("ERR_CONTRACT_NOT_SIGNED")
    c["status"] = "COUNTERSIGNED"
    touch(c)
    return ok(serialize(c), 200)


@app.route("/planning/contracts/<cid>/request-revision", methods=["POST"])
def request_revision(cid):
    uid, role = require_auth()
    authorize(role, {"Client", "Planner"})
    c = must_exist(store.contracts, cid, "ERR_CONTRACT_NOT_FOUND")
    if role == "Client" and c["event_id"] != uid:
        raise ApiError("ERR_OWNERSHIP_VIOLATION")
    if c["status"] != "SENT":
        raise ApiError("ERR_CONTRACT_NOT_SENT")
    c["status"] = "DRAFT"
    c["revision_count"] += 1
    touch(c)
    return ok(serialize(c), 200)


# =========================================================================
# Vendor
# =========================================================================
@app.route("/planning/vendors", methods=["POST"])
def create_vendor():
    _uid, role = require_auth()
    authorize(role, {"Planner"})
    body = get_body()
    name = v_str(body, "name")
    category = v_enum(body, "category", VENDOR_CATEGORIES)
    contact_email = v_str(body, "contact_email")
    ent = new_common()
    ent.update({"name": name, "category": category, "contact_email": contact_email})
    store.vendors[ent["id"]] = ent
    return ok(serialize(ent), 201)


@app.route("/planning/vendors", methods=["GET"])
def list_vendors():
    _uid, role = require_auth()
    authorize(role, VALID_ROLES)
    filters = {}
    if request.args.get("category") is not None:
        filters["category"] = request.args.get("category")
    return list_response(store.vendors, filters)


@app.route("/planning/vendors/<vid>", methods=["GET"])
def get_vendor(vid):
    _uid, role = require_auth()
    authorize(role, VALID_ROLES)
    v = must_exist(store.vendors, vid, "ERR_VENDOR_NOT_FOUND")
    return ok(serialize(v), 200)


# =========================================================================
# COI
# =========================================================================
@app.route("/planning/cois", methods=["POST"])
def create_coi():
    uid, role = require_auth()
    authorize(role, {"Vendor", "Planner"})
    body = get_body()
    # ownership (gate 3) before existence (gate 4) — body-field based
    if role == "Vendor":
        vid = body.get("vendor_id")
        if vid is not None and vid != uid:
            raise ApiError("ERR_OWNERSHIP_VIOLATION")
    vendor = must_exist(store.vendors, body.get("vendor_id"), "ERR_VENDOR_NOT_FOUND")
    v_str(body, "vendor_id")
    policy_number = v_str(body, "policy_number")
    coverage_amount = v_int(body, "coverage_amount_cents", minimum=0)
    expiry_raw, expiry_dt = v_dt(body, "coverage_expiry_date")

    ent = new_common()
    ent.update({
        "vendor_id": vendor["id"],
        "policy_number": policy_number,
        "coverage_amount_cents": coverage_amount,
        "coverage_expiry_date": expiry_raw,
        "_coverage_expiry": expiry_dt,
        "status": "PENDING",
    })
    store.cois[ent["id"]] = ent
    return ok(serialize(ent), 201)


@app.route("/planning/cois", methods=["GET"])
def list_cois():
    _uid, role = require_auth()
    authorize(role, VALID_ROLES)
    filters = {}
    if request.args.get("vendor_id") is not None:
        filters["vendor_id"] = request.args.get("vendor_id")
    return list_response(store.cois, filters)


@app.route("/planning/cois/<coi_id>", methods=["GET"])
def get_coi(coi_id):
    _uid, role = require_auth()
    authorize(role, VALID_ROLES)
    c = must_exist(store.cois, coi_id, "ERR_COI_NOT_FOUND")
    return ok(serialize(c), 200)


@app.route("/planning/cois/<coi_id>/verify", methods=["POST"])
def verify_coi(coi_id):
    _uid, role = require_auth()
    authorize(role, {"Planner"})
    c = must_exist(store.cois, coi_id, "ERR_COI_NOT_FOUND")
    if c["status"] != "PENDING":
        raise ApiError("ERR_COI_NOT_PENDING")
    if not (c["_coverage_expiry"] > store.clock_dt):
        raise ApiError("ERR_COI_EXPIRED")
    c["status"] = "VERIFIED"
    touch(c)
    return ok(serialize(c), 200)


# =========================================================================
# VendorBooking
# =========================================================================
@app.route("/planning/vendor-bookings", methods=["POST"])
def create_booking():
    _uid, role = require_auth()
    authorize(role, {"Planner"})
    body = get_body()
    event = must_exist(store.events, body.get("event_id"), "ERR_EVENT_NOT_FOUND")
    vendor = must_exist(store.vendors, body.get("vendor_id"), "ERR_VENDOR_NOT_FOUND")
    v_str(body, "event_id")
    v_str(body, "vendor_id")
    service_description = v_str(body, "service_description")
    estimated = v_int(body, "estimated_cost_cents", minimum=0)

    ent = new_common()
    ent.update({
        "event_id": event["id"],
        "vendor_id": vendor["id"],
        "service_description": service_description,
        "estimated_cost_cents": estimated,
        "contracted_cost_cents": None,
        "deposit_cents": None,
        "balance_cents": None,
        "status": "PROPOSED",
    })
    store.bookings[ent["id"]] = ent
    recompute_budget(event)
    touch(event)
    return ok(serialize(ent), 201)


@app.route("/planning/vendor-bookings", methods=["GET"])
def list_bookings():
    _uid, role = require_auth()
    authorize(role, VALID_ROLES)
    filters = {}
    if request.args.get("event_id") is not None:
        filters["event_id"] = request.args.get("event_id")
    if request.args.get("vendor_id") is not None:
        filters["vendor_id"] = request.args.get("vendor_id")
    return list_response(store.bookings, filters)


@app.route("/planning/vendor-bookings/<bid>", methods=["GET"])
def get_booking(bid):
    _uid, role = require_auth()
    authorize(role, VALID_ROLES)
    b = must_exist(store.bookings, bid, "ERR_BOOKING_NOT_FOUND")
    return ok(serialize(b), 200)


@app.route("/planning/vendor-bookings/<bid>/book", methods=["POST"])
def book_booking(bid):
    _uid, role = require_auth()
    authorize(role, {"Planner"})
    booking = must_exist(store.bookings, bid, "ERR_BOOKING_NOT_FOUND")
    body = get_body()
    contracted = v_int(body, "contracted_cost_cents", minimum=0)

    # state checks
    if booking["status"] != "PROPOSED":
        raise ApiError("ERR_BOOKING_NOT_PROPOSED")
    event = store.events[booking["event_id"]]
    if event["status"] != "BOOKING":
        raise ApiError("ERR_EVENT_NOT_BOOKING")
    # cross-entity: VERIFIED COI covering the event_date
    has_coi = any(
        c["vendor_id"] == booking["vendor_id"]
        and c["status"] == "VERIFIED"
        and c["_coverage_expiry"] >= event["_event_date"]
        for c in store.cois.values()
    )
    if not has_coi:
        raise ApiError("ERR_COI_NOT_VERIFIED")
    # fiscal guard (checked last)
    if event["committed_spend_cents"] + contracted > event["total_budget_cents"]:
        raise ApiError("ERR_BUDGET_EXCEEDED")

    deposit, balance = calc_deposit_split(contracted)
    booking["contracted_cost_cents"] = contracted
    booking["deposit_cents"] = deposit
    booking["balance_cents"] = balance
    booking["status"] = "BOOKED"
    touch(booking)

    for ptype, amount in (("DEPOSIT", deposit), ("BALANCE", balance)):
        p = new_common()
        p.update({
            "vendor_booking_id": booking["id"],
            "payment_type": ptype,
            "amount_cents": amount,
            "paid_at": None,
            "status": "SCHEDULED",
        })
        store.payments[p["id"]] = p

    recompute_budget(event)
    touch(event)
    return ok(serialize(booking), 200)


@app.route("/planning/vendor-bookings/<bid>/cancel", methods=["POST"])
def cancel_booking(bid):
    _uid, role = require_auth()
    authorize(role, {"Planner"})
    booking = must_exist(store.bookings, bid, "ERR_BOOKING_NOT_FOUND")
    if booking["status"] not in ("PROPOSED", "BOOKED"):
        raise ApiError("ERR_BOOKING_NOT_CANCELLABLE")
    booking["status"] = "CANCELLED"
    touch(booking)
    for p in store.payments.values():
        if p["vendor_booking_id"] == booking["id"] and p["status"] == "SCHEDULED":
            p["status"] = "VOID"
            touch(p)
    event = store.events[booking["event_id"]]
    recompute_budget(event)
    touch(event)
    return ok(serialize(booking), 200)


# =========================================================================
# VendorPayment
# =========================================================================
@app.route("/planning/vendor-payments", methods=["GET"])
def list_payments():
    _uid, role = require_auth()
    authorize(role, VALID_ROLES)
    filters = {}
    if request.args.get("vendor_booking_id") is not None:
        filters["vendor_booking_id"] = request.args.get("vendor_booking_id")
    return list_response(store.payments, filters)


@app.route("/planning/vendor-payments/<pid>", methods=["GET"])
def get_payment(pid):
    _uid, role = require_auth()
    authorize(role, VALID_ROLES)
    p = must_exist(store.payments, pid, "ERR_PAYMENT_NOT_FOUND")
    return ok(serialize(p), 200)


@app.route("/planning/vendor-payments/<pid>/pay", methods=["POST"])
def pay_payment(pid):
    _uid, role = require_auth()
    authorize(role, {"Planner"})
    p = must_exist(store.payments, pid, "ERR_PAYMENT_NOT_FOUND")
    if p["status"] != "SCHEDULED":
        raise ApiError("ERR_PAYMENT_NOT_SCHEDULED")
    p["status"] = "PAID"
    p["paid_at"] = store.clock_raw
    touch(p)
    return ok(serialize(p), 200)


# =========================================================================
# TimelineBlock
# =========================================================================
@app.route("/planning/timeline-blocks", methods=["POST"])
def create_timeline_block():
    _uid, role = require_auth()
    authorize(role, {"Planner"})
    body = get_body()
    event = must_exist(store.events, body.get("event_id"), "ERR_EVENT_NOT_FOUND")
    v_str(body, "event_id")
    label = v_str(body, "label")
    zone = v_enum(body, "zone", ZONES)
    block_type = v_enum(body, "block_type", BLOCK_TYPES)
    start = v_int(body, "start_offset_min", minimum=0)
    end = v_int(body, "end_offset_min", minimum=0)
    # interval well-formedness (gate 6)
    if end <= start:
        raise ApiError("ERR_INVALID_INTERVAL")
    # overlap in same event+zone (half-open)
    for b in store.timeline_blocks.values():
        if b["event_id"] == event["id"] and b["zone"] == zone:
            if start < b["end_offset_min"] and b["start_offset_min"] < end:
                raise ApiError("ERR_TIMELINE_OVERLAP")

    ent = new_common()
    ent.update({
        "event_id": event["id"],
        "label": label,
        "zone": zone,
        "block_type": block_type,
        "start_offset_min": start,
        "end_offset_min": end,
    })
    store.timeline_blocks[ent["id"]] = ent
    return ok(serialize(ent), 201)


@app.route("/planning/timeline-blocks", methods=["GET"])
def list_timeline_blocks():
    _uid, role = require_auth()
    authorize(role, VALID_ROLES)
    filters = {}
    if request.args.get("event_id") is not None:
        filters["event_id"] = request.args.get("event_id")
    if request.args.get("zone") is not None:
        filters["zone"] = request.args.get("zone")
    return list_response(store.timeline_blocks, filters)


@app.route("/planning/timeline-blocks/<blk>", methods=["GET"])
def get_timeline_block(blk):
    _uid, role = require_auth()
    authorize(role, VALID_ROLES)
    b = must_exist(store.timeline_blocks, blk, "ERR_TIMELINE_BLOCK_NOT_FOUND")
    return ok(serialize(b), 200)


# =========================================================================
# Guest
# =========================================================================
@app.route("/planning/guests", methods=["POST"])
def create_guest():
    uid, role = require_auth()
    authorize(role, {"Planner", "Client"})
    body = get_body()
    # ownership (gate 3) before existence — body-field based
    if role == "Client":
        ev_id = body.get("event_id")
        if ev_id is not None and ev_id != uid:
            raise ApiError("ERR_OWNERSHIP_VIOLATION")
    event = must_exist(store.events, body.get("event_id"), "ERR_EVENT_NOT_FOUND")
    v_str(body, "event_id")
    guest_name = v_str(body, "guest_name")
    party_size = v_int(body, "party_size", minimum=1)
    meal_choice = v_enum(body, "meal_choice", MEAL_CHOICES, required=False, default="NONE")

    ent = new_common()
    ent.update({
        "event_id": event["id"],
        "guest_name": guest_name,
        "party_size": party_size,
        "meal_choice": meal_choice,
        "rsvp_status": "INVITED",
    })
    store.guests[ent["id"]] = ent
    recompute_headcount(event)
    touch(event)
    return ok(serialize(ent), 201)


@app.route("/planning/guests", methods=["GET"])
def list_guests():
    _uid, role = require_auth()
    authorize(role, VALID_ROLES)
    filters = {}
    if request.args.get("event_id") is not None:
        filters["event_id"] = request.args.get("event_id")
    if request.args.get("rsvp_status") is not None:
        filters["rsvp_status"] = request.args.get("rsvp_status")
    return list_response(store.guests, filters)


@app.route("/planning/guests/<gid>", methods=["GET"])
def get_guest(gid):
    _uid, role = require_auth()
    authorize(role, VALID_ROLES)
    g = must_exist(store.guests, gid, "ERR_GUEST_NOT_FOUND")
    return ok(serialize(g), 200)


@app.route("/planning/guests/<gid>/rsvp", methods=["POST"])
def rsvp_guest(gid):
    uid, role = require_auth()
    authorize(role, {"Planner", "Client"})
    guest = must_exist(store.guests, gid, "ERR_GUEST_NOT_FOUND")
    if role == "Client" and guest["event_id"] != uid:
        raise ApiError("ERR_OWNERSHIP_VIOLATION")
    body = get_body()
    target = v_enum(body, "rsvp_status", RSVP_TARGETS)
    meal_choice = v_enum(body, "meal_choice", MEAL_CHOICES, required=False, default=None)

    old_status = guest["rsvp_status"]
    guest["rsvp_status"] = target
    if meal_choice is not None:
        guest["meal_choice"] = meal_choice

    # ACCEPTED -> DECLINED unseats
    if old_status == "ACCEPTED" and target == "DECLINED":
        seat = next(
            (s for s in store.seat_assignments.values() if s["guest_id"] == guest["id"]),
            None,
        )
        if seat is not None:
            tbl = store.tables.get(seat["table_id"])
            if tbl is not None:
                tbl["occupied_seats"] -= seat["seats_used"]
                touch(tbl)
            del store.seat_assignments[seat["id"]]

    touch(guest)
    event = store.events.get(guest["event_id"])
    if event is not None:
        recompute_headcount(event)
        touch(event)
    return ok(serialize(guest), 200)


# =========================================================================
# Table
# =========================================================================
@app.route("/planning/tables", methods=["POST"])
def create_table():
    _uid, role = require_auth()
    authorize(role, {"Planner"})
    body = get_body()
    event = must_exist(store.events, body.get("event_id"), "ERR_EVENT_NOT_FOUND")
    v_str(body, "event_id")
    table_label = v_str(body, "table_label")
    capacity = v_int(body, "capacity", minimum=1)

    ent = new_common()
    ent.update({
        "event_id": event["id"],
        "table_label": table_label,
        "capacity": capacity,
        "occupied_seats": 0,
    })
    store.tables[ent["id"]] = ent
    return ok(serialize(ent), 201)


@app.route("/planning/tables", methods=["GET"])
def list_tables():
    _uid, role = require_auth()
    authorize(role, VALID_ROLES)
    filters = {}
    if request.args.get("event_id") is not None:
        filters["event_id"] = request.args.get("event_id")
    return list_response(store.tables, filters)


@app.route("/planning/tables/<tid>", methods=["GET"])
def get_table(tid):
    _uid, role = require_auth()
    authorize(role, VALID_ROLES)
    t = must_exist(store.tables, tid, "ERR_TABLE_NOT_FOUND")
    return ok(serialize(t), 200)


# =========================================================================
# SeatAssignment
# =========================================================================
@app.route("/planning/seat-assignments", methods=["POST"])
def create_seat_assignment():
    _uid, role = require_auth()
    authorize(role, {"Planner"})
    body = get_body()
    # existence left-to-right: event, guest, table
    event = must_exist(store.events, body.get("event_id"), "ERR_EVENT_NOT_FOUND")
    guest = must_exist(store.guests, body.get("guest_id"), "ERR_GUEST_NOT_FOUND")
    table = must_exist(store.tables, body.get("table_id"), "ERR_TABLE_NOT_FOUND")
    # body validation
    v_str(body, "event_id")
    v_str(body, "guest_id")
    v_str(body, "table_id")

    # business checks (PRD 3.5 order)
    if guest["rsvp_status"] != "ACCEPTED":
        raise ApiError("ERR_GUEST_NOT_ACCEPTED")
    if guest["event_id"] != event["id"] or table["event_id"] != event["id"]:
        raise ApiError("ERR_SEAT_EVENT_MISMATCH")
    already = any(s["guest_id"] == guest["id"] for s in store.seat_assignments.values())
    if already:
        raise ApiError("ERR_GUEST_ALREADY_SEATED")
    if table["occupied_seats"] + guest["party_size"] > table["capacity"]:
        raise ApiError("ERR_TABLE_CAPACITY_EXCEEDED")

    seats_used = guest["party_size"]
    ent = new_common()
    ent.update({
        "event_id": event["id"],
        "guest_id": guest["id"],
        "table_id": table["id"],
        "seats_used": seats_used,
    })
    store.seat_assignments[ent["id"]] = ent
    table["occupied_seats"] += seats_used
    touch(table)
    return ok(serialize(ent), 201)


@app.route("/planning/seat-assignments", methods=["GET"])
def list_seat_assignments():
    _uid, role = require_auth()
    authorize(role, VALID_ROLES)
    filters = {}
    for key in ("event_id", "guest_id", "table_id"):
        if request.args.get(key) is not None:
            filters[key] = request.args.get(key)
    return list_response(store.seat_assignments, filters)


@app.route("/planning/seat-assignments/<sid>", methods=["GET"])
def get_seat_assignment(sid):
    _uid, role = require_auth()
    authorize(role, VALID_ROLES)
    s = must_exist(store.seat_assignments, sid, "ERR_SEAT_ASSIGNMENT_NOT_FOUND")
    return ok(serialize(s), 200)


@app.route("/planning/seat-assignments/<sid>", methods=["DELETE"])
def delete_seat_assignment(sid):
    _uid, role = require_auth()
    authorize(role, {"Planner"})
    s = must_exist(store.seat_assignments, sid, "ERR_SEAT_ASSIGNMENT_NOT_FOUND")
    tbl = store.tables.get(s["table_id"])
    if tbl is not None:
        tbl["occupied_seats"] -= s["seats_used"]
        touch(tbl)
    del store.seat_assignments[sid]
    return "", 204


# =========================================================================
# StaffMember
# =========================================================================
@app.route("/planning/staff-members", methods=["POST"])
def create_staff_member():
    _uid, role = require_auth()
    authorize(role, {"Planner"})
    body = get_body()
    event = must_exist(store.events, body.get("event_id"), "ERR_EVENT_NOT_FOUND")
    v_str(body, "event_id")
    staff_name = v_str(body, "staff_name")
    role_title = v_enum(body, "role_title", ROLE_TITLES)
    hourly_rate = v_int(body, "hourly_rate_cents", minimum=0)

    ent = new_common()
    ent.update({
        "event_id": event["id"],
        "staff_name": staff_name,
        "role_title": role_title,
        "hourly_rate_cents": hourly_rate,
    })
    store.staff_members[ent["id"]] = ent
    return ok(serialize(ent), 201)


@app.route("/planning/staff-members", methods=["GET"])
def list_staff_members():
    _uid, role = require_auth()
    authorize(role, VALID_ROLES)
    filters = {}
    if request.args.get("event_id") is not None:
        filters["event_id"] = request.args.get("event_id")
    return list_response(store.staff_members, filters)


@app.route("/planning/staff-members/<smid>", methods=["GET"])
def get_staff_member(smid):
    _uid, role = require_auth()
    authorize(role, VALID_ROLES)
    s = must_exist(store.staff_members, smid, "ERR_STAFF_MEMBER_NOT_FOUND")
    return ok(serialize(s), 200)


# =========================================================================
# StaffAssignment
# =========================================================================
@app.route("/planning/staff-assignments", methods=["POST"])
def create_staff_assignment():
    _uid, role = require_auth()
    authorize(role, {"Planner"})
    body = get_body()
    event = must_exist(store.events, body.get("event_id"), "ERR_EVENT_NOT_FOUND")
    member = must_exist(store.staff_members, body.get("staff_member_id"), "ERR_STAFF_MEMBER_NOT_FOUND")
    v_str(body, "event_id")
    v_str(body, "staff_member_id")
    start = v_int(body, "shift_start_offset_min", minimum=0)
    end = v_int(body, "shift_end_offset_min", minimum=0)
    if end <= start:
        raise ApiError("ERR_INVALID_INTERVAL")
    # double-booking: same staff member within BUFFER minutes
    for a in store.staff_assignments.values():
        if a["staff_member_id"] == member["id"]:
            s2, e2 = a["shift_start_offset_min"], a["shift_end_offset_min"]
            if not (end + BUFFER_MIN <= s2 or e2 + BUFFER_MIN <= start):
                raise ApiError("ERR_STAFF_DOUBLE_BOOKED")

    labor = calc_staff_labor(member["hourly_rate_cents"], start, end)
    ent = new_common()
    ent.update({
        "event_id": event["id"],
        "staff_member_id": member["id"],
        "shift_start_offset_min": start,
        "shift_end_offset_min": end,
        "labor_cost_cents": labor,
    })
    store.staff_assignments[ent["id"]] = ent
    return ok(serialize(ent), 201)


@app.route("/planning/staff-assignments", methods=["GET"])
def list_staff_assignments():
    _uid, role = require_auth()
    authorize(role, VALID_ROLES)
    filters = {}
    if request.args.get("event_id") is not None:
        filters["event_id"] = request.args.get("event_id")
    if request.args.get("staff_member_id") is not None:
        filters["staff_member_id"] = request.args.get("staff_member_id")
    return list_response(store.staff_assignments, filters)


@app.route("/planning/staff-assignments/<said>", methods=["GET"])
def get_staff_assignment(said):
    _uid, role = require_auth()
    authorize(role, VALID_ROLES)
    a = must_exist(store.staff_assignments, said, "ERR_STAFF_ASSIGNMENT_NOT_FOUND")
    return ok(serialize(a), 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
