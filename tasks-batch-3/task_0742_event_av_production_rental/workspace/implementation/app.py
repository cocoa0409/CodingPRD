"""Event AV & Production Rental API — Flask application.

In-memory only; the store is wiped on every process boot (start.sh is relaunched
before every test). No entity data is ever seeded at startup.
"""
import os
from datetime import date, timedelta

from flask import Flask, request, jsonify

import store
from store import (
    ApiError, new_record, touch, public,
    envelope_object, envelope_array, envelope_error,
    clock_now, set_clock, fmt_iso,
)
import calc
from calc import (
    parse_date, parse_dt, billable_days,
    equipment_line_charge, crew_assignment_cost,
    volume_discount, rush_surcharge, deposit_required,
    TURNAROUND_MINUTES,
)

app = Flask(__name__)

ROLES = {"AccountManager", "WarehouseManager", "CrewChief", "Client"}


# ===========================================================================
# Auth / RBAC (§2.1, §2.7)
# ===========================================================================
def authorize(allowed):
    role = request.headers.get("X-User-Role")
    if not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or unknown X-User-Role")
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN", 403, "Role not permitted for this operation")
    uid = request.headers.get("X-User-ID")
    return role, uid


def client_guard(role, uid, owner_customer_id):
    """Entity-backed Client may act only on resources it owns (§2.1)."""
    if role == "Client" and owner_customer_id != uid:
        raise ApiError("ERR_FORBIDDEN", 403, "Client may act only on its own resources")


# ===========================================================================
# Body validation helpers (§2.7 step 4 -> ERR_VALIDATION)
# ===========================================================================
def _bad(msg):
    raise ApiError("ERR_VALIDATION", 422, msg)


def get_body():
    return request.get_json(silent=True) or {}


def v_str(b, name, required=True, default=None):
    if name not in b or b[name] is None:
        if required:
            _bad("Missing required field: " + name)
        return default
    if not isinstance(b[name], str):
        _bad(name + " must be a string")
    return b[name]


def v_int(b, name, required=True, default=None, minv=None):
    if name not in b or b[name] is None:
        if required:
            _bad("Missing required field: " + name)
        return default
    v = b[name]
    if isinstance(v, bool) or not isinstance(v, int):
        _bad(name + " must be an integer")
    if minv is not None and v < minv:
        _bad(name + " must be >= " + str(minv))
    return v


def v_num(b, name, required=True, default=None, minv=None, gt=None):
    if name not in b or b[name] is None:
        if required:
            _bad("Missing required field: " + name)
        return default
    v = b[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _bad(name + " must be a number")
    if minv is not None and v < minv:
        _bad(name + " must be >= " + str(minv))
    if gt is not None and not v > gt:
        _bad(name + " must be > " + str(gt))
    return v


def v_bool(b, name, default=False):
    if name not in b or b[name] is None:
        return default
    if not isinstance(b[name], bool):
        _bad(name + " must be a boolean")
    return b[name]


def v_enum(b, name, choices, required=True, default=None):
    v = v_str(b, name, required, default)
    if v is None:
        return default
    if v not in choices:
        _bad(name + " must be one of " + ", ".join(choices))
    return v


def v_date(b, name, required=True, default=None):
    s = v_str(b, name, required, default)
    if s is None:
        return default
    try:
        date.fromisoformat(s)
    except (ValueError, TypeError):
        _bad(name + " must be an ISO date (YYYY-MM-DD)")
    return s


def v_datetime(b, name, required=True, default=None):
    s = v_str(b, name, required, default)
    if s is None:
        return default
    try:
        parse_dt(s)
    except (ValueError, TypeError):
        _bad(name + " must be an ISO 8601 datetime")
    return s


# ===========================================================================
# Lookup helpers (existence -> ERR_NOT_FOUND, §2.7 step 3)
# ===========================================================================
def find(coll, rid):
    rec = coll.get(rid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Resource not found: " + str(rid))
    return rec


def order_children(coll, order_id):
    return [r for r in coll.values() if r.get("order_id") == order_id]


# ===========================================================================
# Derived-field reconciliation (§2.9)
# ===========================================================================
def recompute_deposit(order):
    oid = order["id"]
    held = captured = refunded = released = 0
    for e in store.deposit_ledger.values():
        if e["order_id"] != oid:
            continue
        t = e["entry_type"]
        if t == "HOLD":
            held += e["amount_cents"]
        elif t == "CAPTURE":
            captured += e["amount_cents"]
        elif t == "REFUND":
            refunded += e["amount_cents"]
        elif t == "RELEASE":
            released += e["amount_cents"]
    order["deposit_held_cents"] = held
    order["deposit_captured_cents"] = captured
    order["deposit_refunded_cents"] = refunded
    order["deposit_released_cents"] = released
    order["deposit_outstanding_cents"] = held - captured - refunded - released


def recompute_damage(order):
    oid = order["id"]
    open_reps = [d for d in store.damage_reports.values()
                 if d["order_id"] == oid and d["status"] in ("FILED", "ASSESSED")]
    order["open_damage_count"] = len(open_reps)
    order["deposit_at_risk_cents"] = sum(d["assessed_cost_cents"] for d in open_reps)


def recompute_coi(order):
    oid = order["id"]
    order["has_approved_coi"] = any(
        c["order_id"] == oid and c["status"] == "APPROVED"
        for c in store.certificates.values())


def recompute_sub_rental_cost(order):
    oid = order["id"]
    order["sub_rental_cost_cents"] = sum(
        s["cost_cents"] for s in store.sub_rentals.values()
        if s["order_id"] == oid and s["status"] in ("CONFIRMED", "RETURNED"))


def add_ledger(order_id, entry_type, amount, note=None, damage_report_id=None):
    e = new_record({
        "order_id": order_id,
        "damage_report_id": damage_report_id,
        "entry_type": entry_type,
        "amount_cents": amount,
        "note": note,
    }, common=False)
    store.deposit_ledger[e["id"]] = e
    return e


# ===========================================================================
# Availability (§3.2 / equipment_availability)
# ===========================================================================
def sub_in_capacity(equipment_id):
    return sum(s["qty"] for s in store.sub_rentals.values()
               if s["equipment_id"] == equipment_id
               and s["direction"] == "SUB_IN" and s["status"] == "CONFIRMED")


def peak_reserved(equipment_id, s, e, exclude_id=None):
    relevant = [r for r in store.reservations.values()
                if r["equipment_id"] == equipment_id
                and r["status"] in ("HELD", "CHECKED_OUT")
                and r["id"] != exclude_id]
    if not relevant:
        return 0
    day = parse_date(s)
    last = parse_date(e)
    peak = 0
    while day <= last:
        cnt = 0
        for r in relevant:
            if parse_date(r["reserve_start_date"]) <= day <= parse_date(r["reserve_end_date"]):
                cnt += r["qty"]
        if cnt > peak:
            peak = cnt
        day += timedelta(days=1)
    return peak


# ===========================================================================
# Pricing passes (§3.6 provisional / §3.9 final)
# ===========================================================================
def run_pricing(order, final):
    oid = order["id"]
    eq_sub = 0
    for r in order_children(store.reservations, oid):
        if r["status"] == "RELEASED":
            continue
        eq = store.equipment[r["equipment_id"]]
        units = r["checked_out_qty"] if final else r["qty"]
        charge = equipment_line_charge(eq["daily_rate_cents"], units,
                                       r["billable_days"], r["is_standby"])
        r["line_charge_cents"] = charge
        eq_sub += charge
    order["equipment_subtotal_cents"] = eq_sub

    crew_sub = 0
    for a in order_children(store.crew_assignments, oid):
        if a["status"] == "CANCELLED":
            continue
        m = store.crew_members[a["crew_member_id"]]
        hours = a["actual_hours"] if final else a["scheduled_hours"]
        cost = crew_assignment_cost(m["hourly_rate_cents"], hours, a["assignment_role"])
        a["assignment_cost_cents"] = cost
        crew_sub += cost
    order["crew_subtotal_cents"] = crew_sub

    subtotal = eq_sub + crew_sub
    if final:
        subtotal += order["sub_rental_cost_cents"]
    vd = volume_discount(subtotal)
    order["volume_discount_cents"] = vd
    discounted = subtotal - vd

    if final:
        grand = discounted + order["rush_surcharge_cents"]
        order["final_total_cents"] = grand
        order["pricing_variant"] = "FINAL"
    else:
        rush = rush_surcharge(discounted, clock_now(), order["event_start_date"])
        order["rush_surcharge_cents"] = rush
        order["quote_total_cents"] = discounted + rush
        order["pricing_variant"] = "PROVISIONAL"


# ===========================================================================
# Pagination (§2.3)
# ===========================================================================
def paginate_and_respond(items):
    items = sorted(items, key=lambda r: r["_seq"])  # created_at ascending
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
        offset = int(raw_offset) if raw_offset is not None else 0
    except (ValueError, TypeError):
        raise ApiError("ERR_PAGINATION_INVALID", 400, "limit/offset must be integers")
    if limit < 1 or limit > 100 or offset < 0:
        raise ApiError("ERR_PAGINATION_INVALID", 400, "limit in [1,100], offset >= 0")
    total = len(items)
    page = items[offset:offset + limit]
    has_more = offset + limit < total
    data = [public(r) for r in page]
    return jsonify(envelope_array(data, limit, offset, total, has_more)), 200


def obj(rec, code=200):
    return jsonify(envelope_object(public(rec))), code


# ===========================================================================
# Error handlers
# ===========================================================================
@app.errorhandler(ApiError)
def handle_api_error(err):
    return jsonify(envelope_error(err.error_id, err.message)), err.http_status


@app.errorhandler(404)
def handle_404(err):
    return jsonify(envelope_error("ERR_NOT_FOUND", "Resource not found")), 404


@app.errorhandler(405)
def handle_405(err):
    return jsonify(envelope_error("ERR_NOT_FOUND", "Method not allowed")), 405


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return handle_api_error(err)
    return jsonify(envelope_error("ERR_INTERNAL", str(err))), 500


# ===========================================================================
# Logical clock (§2.6)
# ===========================================================================
@app.post("/_clock/set_current_utc")
def clock_set():
    authorize({"AccountManager", "WarehouseManager", "CrewChief"})
    b = get_body()
    iso = v_str(b, "to_iso8601")
    try:
        dt = parse_dt(iso)
    except (ValueError, TypeError):
        _bad("to_iso8601 must be an ISO 8601 datetime")
    set_clock(dt)
    return jsonify(envelope_object({"current_utc": fmt_iso(clock_now())})), 200


# ===========================================================================
# Customer (§3.1)
# ===========================================================================
@app.post("/customers")
def create_customer():
    authorize({"AccountManager"})
    b = get_body()
    rec = new_record({
        "name": v_str(b, "name"),
        "contact_email": v_str(b, "contact_email"),
        "credit_limit_cents": v_int(b, "credit_limit_cents", minv=0),
    })
    store.customers[rec["id"]] = rec
    return obj(rec, 201)


@app.get("/customers/<rid>")
def get_customer(rid):
    role, uid = authorize({"AccountManager", "WarehouseManager", "CrewChief", "Client"})
    rec = find(store.customers, rid)
    client_guard(role, uid, rec["id"])
    return obj(rec)


# ===========================================================================
# Venue (§3.1)
# ===========================================================================
@app.post("/venues")
def create_venue():
    authorize({"AccountManager"})
    b = get_body()
    rec = new_record({
        "name": v_str(b, "name"),
        "address": v_str(b, "address"),
        "dock_type": v_enum(b, "dock_type",
                            {"STREET_LEVEL", "LOADING_DOCK", "FREIGHT_ELEVATOR"},
                            required=False, default="STREET_LEVEL"),
        "required_coverage_cents": v_int(b, "required_coverage_cents", minv=0),
    })
    store.venues[rec["id"]] = rec
    return obj(rec, 201)


@app.get("/venues/<rid>")
def get_venue(rid):
    authorize({"AccountManager", "WarehouseManager", "CrewChief", "Client"})
    return obj(find(store.venues, rid))


# ===========================================================================
# EquipmentItem (§3.1)
# ===========================================================================
@app.post("/equipment")
def create_equipment():
    authorize({"WarehouseManager"})
    b = get_body()
    rec = new_record({
        "name": v_str(b, "name"),
        "category": v_enum(b, "category", {"SOUND", "LIGHTING", "STAGING", "LED"}),
        "total_units": v_int(b, "total_units", minv=1),
        "daily_rate_cents": v_int(b, "daily_rate_cents", minv=0),
        "replacement_value_cents": v_int(b, "replacement_value_cents", minv=0),
        "requires_operator": v_bool(b, "requires_operator", default=False),
    })
    store.equipment[rec["id"]] = rec
    return obj(rec, 201)


@app.get("/equipment/<rid>")
def get_equipment(rid):
    authorize({"AccountManager", "WarehouseManager", "CrewChief", "Client"})
    return obj(find(store.equipment, rid))


@app.get("/equipment/<rid>/availability")
def get_availability(rid):
    authorize({"AccountManager", "WarehouseManager", "CrewChief", "Client"})
    eq = find(store.equipment, rid)
    start = request.args.get("start_date")
    end = request.args.get("end_date")
    for label, val in (("start_date", start), ("end_date", end)):
        if val is not None:
            try:
                date.fromisoformat(val)
            except (ValueError, TypeError):
                _bad(label + " must be an ISO date (YYYY-MM-DD)")

    relevant = [r for r in store.reservations.values()
                if r["equipment_id"] == rid and r["status"] in ("HELD", "CHECKED_OUT")]
    horizon_start = min((r["reserve_start_date"] for r in relevant), default=None)
    horizon_end = max((r["reserve_end_date"] for r in relevant), default=None)
    s = start if start is not None else horizon_start
    e = end if end is not None else horizon_end

    effective = eq["total_units"] + sub_in_capacity(rid)
    if s is None or e is None:
        peak = 0
    else:
        peak = peak_reserved(rid, s, e)
    available = effective - peak
    data = {
        "available_units": available,
        "effective_units": effective,
        "total_units": eq["total_units"],
        "peak_reserved_units": peak,
    }
    return jsonify(envelope_object(data)), 200


# ===========================================================================
# CrewMember (§3.1)
# ===========================================================================
@app.post("/crew-members")
def create_crew_member():
    authorize({"CrewChief"})
    b = get_body()
    rec = new_record({
        "name": v_str(b, "name"),
        "crew_role": v_enum(b, "crew_role", {"TECH", "OPERATOR"}),
        "hourly_rate_cents": v_int(b, "hourly_rate_cents", minv=0),
    })
    store.crew_members[rec["id"]] = rec
    return obj(rec, 201)


@app.get("/crew-members/<rid>")
def get_crew_member(rid):
    authorize({"AccountManager", "WarehouseManager", "CrewChief"})
    return obj(find(store.crew_members, rid))


# ===========================================================================
# RentalOrder (§3.2, §3.6-3.9)
# ===========================================================================
def new_order_fields(customer_id, venue_id, event_name, start, end):
    return {
        "customer_id": customer_id, "venue_id": venue_id,
        "event_name": event_name,
        "event_start_date": start, "event_end_date": end,
        "status": "DRAFT", "pricing_variant": "NONE",
        "equipment_subtotal_cents": 0, "crew_subtotal_cents": 0,
        "sub_rental_cost_cents": 0, "volume_discount_cents": 0,
        "rush_surcharge_cents": 0, "quote_total_cents": 0,
        "final_total_cents": 0, "deposit_required_cents": 0,
        "deposit_held_cents": 0, "deposit_captured_cents": 0,
        "deposit_refunded_cents": 0, "deposit_released_cents": 0,
        "deposit_outstanding_cents": 0, "deposit_at_risk_cents": 0,
        "open_damage_count": 0, "has_approved_coi": False,
        "balance_cents": 0,
    }


@app.post("/rental-orders")
def create_order():
    authorize({"AccountManager"})
    b = get_body()
    customer_id = v_str(b, "customer_id")
    venue_id = v_str(b, "venue_id")
    find(store.customers, customer_id)
    find(store.venues, venue_id)
    event_name = v_str(b, "event_name")
    start = v_date(b, "event_start_date")
    end = v_date(b, "event_end_date")
    if parse_date(end) < parse_date(start):
        _bad("event_end_date must be on or after event_start_date")
    rec = new_record(new_order_fields(customer_id, venue_id, event_name, start, end))
    store.rental_orders[rec["id"]] = rec
    return obj(rec, 201)


@app.get("/rental-orders/<rid>")
def get_order(rid):
    role, uid = authorize({"AccountManager", "WarehouseManager", "CrewChief", "Client"})
    rec = find(store.rental_orders, rid)
    client_guard(role, uid, rec["customer_id"])
    return obj(rec)


@app.get("/rental-orders")
def list_orders():
    role, uid = authorize({"AccountManager", "Client"})
    customer_id = request.args.get("customer_id")
    venue_id = request.args.get("venue_id")
    status = request.args.get("status")
    items = list(store.rental_orders.values())
    if role == "Client":
        items = [o for o in items if o["customer_id"] == uid]
    if customer_id is not None:
        items = [o for o in items if o["customer_id"] == customer_id]
    if venue_id is not None:
        items = [o for o in items if o["venue_id"] == venue_id]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    return paginate_and_respond(items)


def _get_order_for_action(rid):
    return find(store.rental_orders, rid)


@app.post("/rental-orders/<rid>/quote")
def order_quote(rid):
    authorize({"AccountManager"})
    order = _get_order_for_action(rid)
    if order["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Order must be DRAFT to quote")
    held = [r for r in order_children(store.reservations, rid) if r["status"] == "HELD"]
    if not held:
        raise ApiError("ERR_NO_RESERVATIONS", 409, "Order has no HELD reservations")
    run_pricing(order, final=False)
    order["status"] = "QUOTED"
    touch(order)
    return obj(order)


@app.post("/rental-orders/<rid>/revise")
def order_revise(rid):
    authorize({"AccountManager"})
    order = _get_order_for_action(rid)
    if order["status"] != "QUOTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Order must be QUOTED to revise")
    order["status"] = "DRAFT"
    order["pricing_variant"] = "NONE"
    touch(order)
    return obj(order)


def has_valid_coi(order):
    venue = store.venues[order["venue_id"]]
    for c in store.certificates.values():
        if (c["order_id"] == order["id"] and c["status"] == "APPROVED"
                and c["coverage_amount_cents"] >= venue["required_coverage_cents"]
                and parse_date(c["expiry_date"]) > parse_date(order["event_end_date"])):
            return True
    return False


@app.post("/rental-orders/<rid>/confirm")
def order_confirm(rid):
    authorize({"AccountManager"})
    order = _get_order_for_action(rid)
    b = get_body()
    expected = v_int(b, "expected_order_version")
    if order["status"] != "QUOTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Order must be QUOTED to confirm")
    if expected != order["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "expected_order_version is stale")
    if not has_valid_coi(order):
        raise ApiError("ERR_COI_NOT_APPROVED", 409, "No valid approved COI for the order")
    customer = store.customers[order["customer_id"]]
    if order["quote_total_cents"] > customer["credit_limit_cents"]:
        raise ApiError("ERR_CREDIT_LIMIT_EXCEEDED", 409, "quote exceeds credit limit")

    exposure = 0
    for r in order_children(store.reservations, rid):
        if r["status"] == "RELEASED":
            continue
        eq = store.equipment[r["equipment_id"]]
        exposure += eq["replacement_value_cents"] * r["qty"]
    order["deposit_required_cents"] = deposit_required(exposure)
    add_ledger(rid, "HOLD", order["deposit_required_cents"], note="Deposit hold at confirm")
    recompute_deposit(order)
    order["status"] = "CONFIRMED"
    touch(order)
    return obj(order)


@app.post("/rental-orders/<rid>/load-out")
def order_load_out(rid):
    authorize({"WarehouseManager"})
    order = _get_order_for_action(rid)
    if order["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", 409, "Order must be CONFIRMED to load-out")
    order["status"] = "LOADED_OUT"
    touch(order)
    return obj(order)


@app.post("/rental-orders/<rid>/start-event")
def order_start_event(rid):
    authorize({"AccountManager"})
    order = _get_order_for_action(rid)
    if order["status"] != "LOADED_OUT":
        raise ApiError("ERR_INVALID_STATE", 409, "Order must be LOADED_OUT to start event")
    for r in order_children(store.reservations, rid):
        if r["status"] not in ("CHECKED_OUT", "RELEASED"):
            raise ApiError("ERR_RESERVATIONS_NOT_CHECKED_OUT", 409,
                           "A reservation is not yet checked out")
    order["status"] = "IN_EVENT"
    touch(order)
    return obj(order)


@app.post("/rental-orders/<rid>/load-in")
def order_load_in(rid):
    authorize({"WarehouseManager"})
    order = _get_order_for_action(rid)
    if order["status"] != "IN_EVENT":
        raise ApiError("ERR_INVALID_STATE", 409, "Order must be IN_EVENT to load-in")
    for r in order_children(store.reservations, rid):
        if r["status"] == "CHECKED_OUT":
            raise ApiError("ERR_RESERVATIONS_NOT_CHECKED_IN", 409,
                           "A checked-out reservation is not yet checked in")
    order["status"] = "LOADED_IN"
    touch(order)
    return obj(order)


@app.post("/rental-orders/<rid>/settle")
def order_settle(rid):
    authorize({"AccountManager"})
    order = _get_order_for_action(rid)
    if order["status"] != "LOADED_IN":
        raise ApiError("ERR_INVALID_STATE", 409, "Order must be LOADED_IN to settle")
    if not has_valid_coi(order):
        raise ApiError("ERR_COI_NOT_APPROVED", 409, "No valid approved COI for the order")
    for d in order_children(store.damage_reports, rid):
        if d["status"] in ("FILED", "ASSESSED"):
            raise ApiError("ERR_OPEN_DAMAGE_REPORT", 409, "An open damage report remains")
    run_pricing(order, final=True)
    refund = order["deposit_held_cents"] - order["deposit_captured_cents"]
    add_ledger(rid, "REFUND", refund, note="Deposit refund at settle")
    recompute_deposit(order)
    order["balance_cents"] = order["final_total_cents"] + order["deposit_captured_cents"]
    order["status"] = "SETTLED"
    touch(order)
    return obj(order)


@app.post("/rental-orders/<rid>/cancel")
def order_cancel(rid):
    authorize({"AccountManager"})
    order = _get_order_for_action(rid)
    if order["status"] not in ("DRAFT", "QUOTED", "CONFIRMED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Order cannot be cancelled from this state")
    was_confirmed = order["status"] == "CONFIRMED"

    for r in order_children(store.reservations, rid):
        if r["status"] in ("CHECKED_IN", "DAMAGED", "RELEASED"):
            continue
        r["status"] = "RELEASED"
        touch(r)
        for s in store.sub_rentals.values():
            if s.get("reservation_id") == r["id"] and s["status"] == "CONFIRMED":
                s["status"] = "CANCELLED"
                touch(s)
    for a in order_children(store.crew_assignments, rid):
        if a["status"] == "SCHEDULED":
            a["status"] = "CANCELLED"
            touch(a)
    recompute_sub_rental_cost(order)

    if was_confirmed:
        add_ledger(rid, "RELEASE", order["deposit_outstanding_cents"],
                   note="Deposit release on cancel")
        recompute_deposit(order)

    order["status"] = "CANCELLED"
    touch(order)
    return obj(order)


# ===========================================================================
# EquipmentReservation (§3.2)
# ===========================================================================
@app.post("/rental-orders/<rid>/reservations")
def create_reservation(rid):
    authorize({"WarehouseManager"})
    order = find(store.rental_orders, rid)
    b = get_body()
    equipment_id = v_str(b, "equipment_id")
    eq = find(store.equipment, equipment_id)
    qty = v_int(b, "qty", minv=1)
    start = v_date(b, "reserve_start_date")
    end = v_date(b, "reserve_end_date")
    if parse_date(end) < parse_date(start):
        _bad("reserve_end_date must be on or after reserve_start_date")
    is_standby = v_bool(b, "is_standby", default=False)
    if order["status"] not in ("DRAFT", "QUOTED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Reservations require order in DRAFT or QUOTED")

    effective = eq["total_units"] + sub_in_capacity(equipment_id)
    peak = peak_reserved(equipment_id, start, end)
    if peak + qty > effective:
        raise ApiError("ERR_EQUIPMENT_UNAVAILABLE", 409, "Insufficient equipment availability")

    rec = new_record({
        "order_id": rid, "equipment_id": equipment_id, "qty": qty,
        "reserve_start_date": start, "reserve_end_date": end,
        "is_standby": is_standby,
        "billable_days": billable_days(start, end),
        "line_charge_cents": 0, "status": "HELD",
        "checked_out_qty": 0, "lost_units": 0,
    })
    store.reservations[rec["id"]] = rec
    touch(order)
    return obj(rec, 201)


@app.get("/equipment-reservations/<rid>")
def get_reservation(rid):
    role, uid = authorize({"AccountManager", "WarehouseManager", "CrewChief", "Client"})
    rec = find(store.reservations, rid)
    order = store.rental_orders[rec["order_id"]]
    client_guard(role, uid, order["customer_id"])
    return obj(rec)


@app.get("/equipment-reservations")
def list_reservations():
    authorize({"AccountManager", "WarehouseManager"})
    order_id = request.args.get("order_id")
    equipment_id = request.args.get("equipment_id")
    status = request.args.get("status")
    items = list(store.reservations.values())
    if order_id is not None:
        items = [r for r in items if r["order_id"] == order_id]
    if equipment_id is not None:
        items = [r for r in items if r["equipment_id"] == equipment_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return paginate_and_respond(items)


@app.post("/equipment-reservations/<rid>/check-out")
def reservation_check_out(rid):
    authorize({"WarehouseManager"})
    rec = find(store.reservations, rid)
    if rec["status"] != "HELD":
        raise ApiError("ERR_INVALID_STATE", 409, "Reservation must be HELD to check out")
    order = store.rental_orders[rec["order_id"]]
    if order["status"] != "LOADED_OUT":
        raise ApiError("ERR_ORDER_NOT_LOADED_OUT", 409, "Order is not LOADED_OUT")
    rec["checked_out_qty"] = rec["qty"]
    rec["status"] = "CHECKED_OUT"
    touch(rec)
    return obj(rec)


@app.post("/equipment-reservations/<rid>/check-in")
def reservation_check_in(rid):
    authorize({"WarehouseManager"})
    rec = find(store.reservations, rid)
    b = get_body()
    damaged = v_bool(b, "damaged", default=False)
    lost_units = v_int(b, "lost_units", required=False, default=0, minv=0)
    if rec["status"] != "CHECKED_OUT":
        raise ApiError("ERR_INVALID_STATE", 409, "Reservation must be CHECKED_OUT to check in")
    order = store.rental_orders[rec["order_id"]]
    if order["status"] != "IN_EVENT":
        raise ApiError("ERR_INVALID_STATE", 409, "Order must be IN_EVENT to check in")
    if not damaged:
        rec["status"] = "CHECKED_IN"
        touch(rec)
        return obj(rec)
    rec["status"] = "DAMAGED"
    rec["lost_units"] = lost_units
    touch(rec)
    report = new_record({
        "order_id": order["id"], "reservation_id": rec["id"],
        "damaged_units": 0, "lost_units": lost_units, "notes": None,
        "assessed_cost_cents": 0, "captured_cents": 0, "status": "FILED",
    })
    store.damage_reports[report["id"]] = report
    recompute_damage(order)
    touch(order)
    return obj(rec)


@app.post("/equipment-reservations/<rid>/release")
def reservation_release(rid):
    authorize({"WarehouseManager"})
    rec = find(store.reservations, rid)
    if rec["status"] != "HELD":
        raise ApiError("ERR_INVALID_STATE", 409, "Reservation must be HELD to release")
    order = store.rental_orders[rec["order_id"]]
    if order["status"] not in ("DRAFT", "QUOTED", "CONFIRMED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Order state does not admit release")
    rec["status"] = "RELEASED"
    touch(rec)
    for s in store.sub_rentals.values():
        if s.get("reservation_id") == rec["id"] and s["status"] == "CONFIRMED":
            s["status"] = "CANCELLED"
            touch(s)
    recompute_sub_rental_cost(order)
    touch(order)
    return obj(rec)


# ===========================================================================
# CrewAssignment (§3.3)
# ===========================================================================
@app.post("/rental-orders/<rid>/crew-assignments")
def create_crew_assignment(rid):
    authorize({"CrewChief"})
    order = find(store.rental_orders, rid)
    b = get_body()
    crew_member_id = v_str(b, "crew_member_id")
    member = find(store.crew_members, crew_member_id)
    role = v_enum(b, "assignment_role", {"TECH", "OPERATOR"})
    shift_start = v_datetime(b, "shift_start")
    shift_end = v_datetime(b, "shift_end")
    if not parse_dt(shift_end) > parse_dt(shift_start):
        _bad("shift_end must be strictly after shift_start")
    scheduled_hours = v_num(b, "scheduled_hours", gt=0)
    is_standby = v_bool(b, "is_standby", default=False)
    if order["status"] not in ("DRAFT", "QUOTED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Crew require order in DRAFT or QUOTED")

    ns = parse_dt(shift_start)
    ne = parse_dt(shift_end)
    buffer = timedelta(minutes=TURNAROUND_MINUTES)
    for a in store.crew_assignments.values():
        if a["crew_member_id"] != crew_member_id or a["status"] == "CANCELLED":
            continue
        es = parse_dt(a["shift_start"])
        ee = parse_dt(a["shift_end"])
        if not (ns >= ee + buffer or ne <= es - buffer):
            raise ApiError("ERR_CREW_DOUBLE_BOOKED", 409, "Crew member double-booked")

    rec = new_record({
        "order_id": rid, "crew_member_id": crew_member_id,
        "assignment_role": role, "shift_start": shift_start, "shift_end": shift_end,
        "scheduled_hours": scheduled_hours, "is_standby": is_standby,
        "actual_hours": 0, "assignment_cost_cents": 0, "status": "SCHEDULED",
    })
    store.crew_assignments[rec["id"]] = rec
    touch(order)
    return obj(rec, 201)


@app.get("/crew-assignments/<rid>")
def get_crew_assignment(rid):
    authorize({"AccountManager", "WarehouseManager", "CrewChief"})
    return obj(find(store.crew_assignments, rid))


@app.get("/crew-assignments")
def list_crew_assignments():
    authorize({"AccountManager", "CrewChief"})
    order_id = request.args.get("order_id")
    crew_member_id = request.args.get("crew_member_id")
    status = request.args.get("status")
    items = list(store.crew_assignments.values())
    if order_id is not None:
        items = [a for a in items if a["order_id"] == order_id]
    if crew_member_id is not None:
        items = [a for a in items if a["crew_member_id"] == crew_member_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return paginate_and_respond(items)


@app.post("/crew-assignments/<rid>/complete")
def crew_complete(rid):
    authorize({"CrewChief"})
    rec = find(store.crew_assignments, rid)
    b = get_body()
    actual_hours = v_num(b, "actual_hours", minv=0)
    if rec["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Assignment must be SCHEDULED to complete")
    order = store.rental_orders[rec["order_id"]]
    if order["status"] not in ("IN_EVENT", "LOADED_IN"):
        raise ApiError("ERR_INVALID_STATE", 409, "Order must be IN_EVENT or LOADED_IN")
    rec["actual_hours"] = actual_hours
    rec["status"] = "COMPLETED"
    touch(rec)
    return obj(rec)


@app.post("/crew-assignments/<rid>/cancel")
def crew_cancel(rid):
    authorize({"CrewChief"})
    rec = find(store.crew_assignments, rid)
    if rec["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Assignment must be SCHEDULED to cancel")
    rec["status"] = "CANCELLED"
    touch(rec)
    order = store.rental_orders.get(rec["order_id"])
    if order is not None:
        touch(order)
    return obj(rec)


# ===========================================================================
# SubRental (§3.4)
# ===========================================================================
@app.post("/rental-orders/<rid>/sub-rentals")
def create_sub_rental(rid):
    authorize({"WarehouseManager"})
    order = find(store.rental_orders, rid)
    b = get_body()
    equipment_id = v_str(b, "equipment_id")
    find(store.equipment, equipment_id)
    reservation_id = b.get("reservation_id")
    res = None
    if reservation_id is not None:
        if not isinstance(reservation_id, str):
            _bad("reservation_id must be a string")
        res = find(store.reservations, reservation_id)
    direction = v_enum(b, "direction", {"SUB_IN", "CROSS_OUT"},
                       required=False, default="SUB_IN")
    vendor_name = v_str(b, "vendor_name")
    qty = v_int(b, "qty", minv=1)
    cost_cents = v_int(b, "cost_cents", minv=0)
    if res is not None and res["order_id"] != rid:
        raise ApiError("ERR_RESERVATION_ORDER_MISMATCH", 409,
                       "reservation does not belong to the order")
    if order["status"] in ("SETTLED", "CANCELLED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Sub-rentals require a non-terminal order")

    rec = new_record({
        "order_id": rid, "equipment_id": equipment_id,
        "reservation_id": reservation_id, "direction": direction,
        "vendor_name": vendor_name, "qty": qty, "cost_cents": cost_cents,
        "status": "REQUESTED",
    })
    store.sub_rentals[rec["id"]] = rec
    return obj(rec, 201)


@app.get("/sub-rentals/<rid>")
def get_sub_rental(rid):
    authorize({"AccountManager", "WarehouseManager"})
    return obj(find(store.sub_rentals, rid))


@app.get("/sub-rentals")
def list_sub_rentals():
    authorize({"AccountManager", "WarehouseManager"})
    order_id = request.args.get("order_id")
    equipment_id = request.args.get("equipment_id")
    reservation_id = request.args.get("reservation_id")
    status = request.args.get("status")
    items = list(store.sub_rentals.values())
    if order_id is not None:
        items = [s for s in items if s["order_id"] == order_id]
    if equipment_id is not None:
        items = [s for s in items if s["equipment_id"] == equipment_id]
    if reservation_id is not None:
        items = [s for s in items if s.get("reservation_id") == reservation_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    return paginate_and_respond(items)


@app.post("/sub-rentals/<rid>/confirm")
def sub_rental_confirm(rid):
    authorize({"WarehouseManager"})
    rec = find(store.sub_rentals, rid)
    if rec["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Sub-rental must be REQUESTED to confirm")
    order = store.rental_orders[rec["order_id"]]
    if order["status"] not in ("DRAFT", "QUOTED", "CONFIRMED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Order state does not admit confirm")
    rec["status"] = "CONFIRMED"
    touch(rec)
    recompute_sub_rental_cost(order)
    touch(order)
    return obj(rec)


@app.post("/sub-rentals/<rid>/return")
def sub_rental_return(rid):
    authorize({"WarehouseManager"})
    rec = find(store.sub_rentals, rid)
    if rec["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", 409, "Sub-rental must be CONFIRMED to return")
    rec["status"] = "RETURNED"
    touch(rec)
    return obj(rec)


@app.post("/sub-rentals/<rid>/cancel")
def sub_rental_cancel(rid):
    authorize({"WarehouseManager"})
    rec = find(store.sub_rentals, rid)
    if rec["status"] not in ("REQUESTED", "CONFIRMED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Sub-rental cannot be cancelled from this state")
    was_confirmed = rec["status"] == "CONFIRMED"
    rec["status"] = "CANCELLED"
    touch(rec)
    if was_confirmed:
        order = store.rental_orders[rec["order_id"]]
        recompute_sub_rental_cost(order)
        touch(order)
    return obj(rec)


# ===========================================================================
# CertificateOfInsurance (§3.5)
# ===========================================================================
@app.post("/rental-orders/<rid>/certificates-of-insurance")
def create_coi(rid):
    role, uid = authorize({"Client"})
    order = find(store.rental_orders, rid)
    client_guard(role, uid, order["customer_id"])
    b = get_body()
    rec = new_record({
        "order_id": rid,
        "insurer": v_str(b, "insurer"),
        "coverage_amount_cents": v_int(b, "coverage_amount_cents", minv=0),
        "expiry_date": v_date(b, "expiry_date"),
        "status": "SUBMITTED", "reject_reason": None,
    })
    store.certificates[rec["id"]] = rec
    return obj(rec, 201)


@app.get("/certificates-of-insurance/<rid>")
def get_coi(rid):
    role, uid = authorize({"AccountManager", "WarehouseManager", "Client"})
    rec = find(store.certificates, rid)
    order = store.rental_orders[rec["order_id"]]
    client_guard(role, uid, order["customer_id"])
    return obj(rec)


@app.get("/certificates-of-insurance")
def list_coi():
    role, uid = authorize({"AccountManager", "Client"})
    order_id = request.args.get("order_id")
    status = request.args.get("status")
    items = list(store.certificates.values())
    if role == "Client":
        owned = {o["id"] for o in store.rental_orders.values() if o["customer_id"] == uid}
        items = [c for c in items if c["order_id"] in owned]
    if order_id is not None:
        items = [c for c in items if c["order_id"] == order_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return paginate_and_respond(items)


@app.post("/certificates-of-insurance/<rid>/approve")
def coi_approve(rid):
    authorize({"AccountManager"})
    rec = find(store.certificates, rid)
    if rec["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "COI must be SUBMITTED to approve")
    order = store.rental_orders[rec["order_id"]]
    venue = store.venues[order["venue_id"]]
    if rec["coverage_amount_cents"] < venue["required_coverage_cents"]:
        raise ApiError("ERR_COI_INSUFFICIENT_COVERAGE", 409, "Coverage below venue requirement")
    if not parse_date(rec["expiry_date"]) > parse_date(order["event_end_date"]):
        raise ApiError("ERR_COI_EXPIRED", 409, "COI expires on or before event end")
    rec["status"] = "APPROVED"
    touch(rec)
    recompute_coi(order)
    touch(order)
    return obj(rec)


@app.post("/certificates-of-insurance/<rid>/reject")
def coi_reject(rid):
    authorize({"AccountManager"})
    rec = find(store.certificates, rid)
    b = get_body()
    reason = v_str(b, "reason")
    if rec["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "COI must be SUBMITTED to reject")
    rec["status"] = "REJECTED"
    rec["reject_reason"] = reason
    touch(rec)
    return obj(rec)


# ===========================================================================
# DamageReport (§3.8, §3.9)
# ===========================================================================
@app.post("/rental-orders/<rid>/damage-reports")
def create_damage_report(rid):
    authorize({"WarehouseManager"})
    order = find(store.rental_orders, rid)
    b = get_body()
    reservation_id = v_str(b, "reservation_id")
    res = find(store.reservations, reservation_id)
    damaged_units = v_int(b, "damaged_units", required=False, default=0, minv=0)
    lost_units = v_int(b, "lost_units", required=False, default=0, minv=0)
    notes = v_str(b, "notes", required=False, default=None)
    if res["order_id"] != rid:
        raise ApiError("ERR_RESERVATION_ORDER_MISMATCH", 409,
                       "reservation does not belong to the order")
    if order["status"] in ("SETTLED", "CANCELLED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Damage reports require a non-terminal order")

    rec = new_record({
        "order_id": rid, "reservation_id": reservation_id,
        "damaged_units": damaged_units, "lost_units": lost_units, "notes": notes,
        "assessed_cost_cents": 0, "captured_cents": 0, "status": "FILED",
    })
    store.damage_reports[rec["id"]] = rec
    recompute_damage(order)
    touch(order)
    return obj(rec, 201)


@app.get("/damage-reports/<rid>")
def get_damage_report(rid):
    authorize({"AccountManager", "WarehouseManager"})
    return obj(find(store.damage_reports, rid))


@app.get("/damage-reports")
def list_damage_reports():
    authorize({"AccountManager", "WarehouseManager"})
    order_id = request.args.get("order_id")
    reservation_id = request.args.get("reservation_id")
    status = request.args.get("status")
    items = list(store.damage_reports.values())
    if order_id is not None:
        items = [d for d in items if d["order_id"] == order_id]
    if reservation_id is not None:
        items = [d for d in items if d["reservation_id"] == reservation_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    return paginate_and_respond(items)


@app.post("/damage-reports/<rid>/assess")
def damage_assess(rid):
    authorize({"WarehouseManager"})
    rec = find(store.damage_reports, rid)
    b = get_body()
    assessed = v_int(b, "assessed_cost_cents", minv=0)
    if rec["status"] != "FILED":
        raise ApiError("ERR_INVALID_STATE", 409, "Damage report must be FILED to assess")
    rec["assessed_cost_cents"] = assessed
    rec["status"] = "ASSESSED"
    touch(rec)
    order = store.rental_orders[rec["order_id"]]
    recompute_damage(order)
    touch(order)
    return obj(rec)


@app.post("/damage-reports/<rid>/charge")
def damage_charge(rid):
    authorize({"AccountManager"})
    rec = find(store.damage_reports, rid)
    if rec["status"] != "ASSESSED":
        raise ApiError("ERR_INVALID_STATE", 409, "Damage report must be ASSESSED to charge")
    order = store.rental_orders[rec["order_id"]]
    if order["status"] not in ("IN_EVENT", "LOADED_IN"):
        raise ApiError("ERR_INVALID_STATE", 409, "Order must be IN_EVENT or LOADED_IN to charge")
    remaining = (order["deposit_held_cents"] - order["deposit_captured_cents"]
                 - order["deposit_released_cents"])
    capture = min(rec["assessed_cost_cents"], remaining)
    if capture < 0:
        capture = 0
    rec["captured_cents"] = capture
    rec["status"] = "CHARGED"
    touch(rec)
    add_ledger(order["id"], "CAPTURE", capture, note="Damage capture",
               damage_report_id=rec["id"])
    recompute_deposit(order)
    recompute_damage(order)
    touch(order)
    return obj(rec)


@app.post("/damage-reports/<rid>/waive")
def damage_waive(rid):
    authorize({"AccountManager"})
    rec = find(store.damage_reports, rid)
    if rec["status"] != "ASSESSED":
        raise ApiError("ERR_INVALID_STATE", 409, "Damage report must be ASSESSED to waive")
    rec["status"] = "WAIVED"
    touch(rec)
    order = store.rental_orders[rec["order_id"]]
    recompute_damage(order)
    touch(order)
    return obj(rec)


# ===========================================================================
# DepositLedgerEntry (read-only; §2.4)
# ===========================================================================
@app.get("/deposit-ledger/<rid>")
def get_ledger_entry(rid):
    authorize({"AccountManager"})
    return obj(find(store.deposit_ledger, rid))


@app.get("/deposit-ledger")
def list_ledger():
    authorize({"AccountManager"})
    order_id = request.args.get("order_id")
    damage_report_id = request.args.get("damage_report_id")
    items = list(store.deposit_ledger.values())
    if order_id is not None:
        items = [e for e in items if e["order_id"] == order_id]
    if damage_report_id is not None:
        items = [e for e in items if e.get("damage_report_id") == damage_report_id]
    return paginate_and_respond(items)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
