"""Custom-Exempt Locker API (Flask, in-memory).

Implements PRD.md / SCAFFOLD.yaml for the custom-exempt slaughter & cut-wrap
scheduling domain: capacity days, deposit-backed appointments, animal intake
through fabrication, split-carcass shares, cut sheets, hanging-weight billing,
freezer storage, custom-exempt labeling, and the no-show / abandoned-meat
policies — all evaluated against a controllable logical clock.
"""

import os
import threading
import uuid
from datetime import timedelta
from decimal import Decimal

from flask import Flask, request

import calc
import db
import serializers as ser
from calc import (
    ABANDON_AFTER_DAYS, ABANDON_SURCHARGE_CENTS, CANCEL_FULL_REFUND_DAYS,
    DEPOSIT_WINDOW_HOURS, FREEZER_CAPACITY_UNITS, FREEZER_UNITS_PER_SHARE,
    INTENDED_USES, MAX_GRIND_PCT, MIN_HANG_DAYS, MIN_LEAD_DAYS, SPECIES,
    allocate_deposit_credit, allocate_share_weights, animal_deposit_pool_cents,
    dec, decimal_places_ok, deposit_quote_cents, fmt_ts, get_now, now_ts,
    parse_date, parse_dt, round_lb, slaughter_share_cents, storage_accrued_cents,
    storage_days_stored, tiered_processing_cents, today,
)
from errors import (
    ApiError, ERR_CAPACITY_FULL, ERR_CUT_SHEET_EXISTS, ERR_CUT_SHEET_MISSING,
    ERR_CUSTOMER_BLOCKED, ERR_DEPOSIT_INSUFFICIENT, ERR_DUPLICATE_TAG,
    ERR_FORBIDDEN, ERR_FREEZER_FULL, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_INVOICE_NOT_PAID, ERR_LABEL_NOT_APPROVED, ERR_LEAD_TIME_TOO_SHORT,
    ERR_MIN_HANG_NOT_MET, ERR_NO_SHOW_PREMATURE, ERR_NOT_FOUND,
    ERR_OUTSTANDING_BALANCE, ERR_RESALE_LABEL_FORBIDDEN,
    ERR_SPLIT_NOT_FINALIZED, ERR_SPLIT_OVER_ALLOCATED,
    ERR_SPLIT_UNDER_ALLOCATED, ERR_STALE_VERSION, ERR_UNAUTHENTICATED,
    ERR_YIELD_INFEASIBLE, raise_error,
)
from middleware import ALL_ROLES, STAFF, require_role
from response import error_response, success_array, success_list, success_object

app = Flask(__name__)

PREFIX = "/locker"

# Serialize all request handling: cascades are multi-entity and must be atomic
# with respect to concurrent requests.
_LOCK = threading.RLock()


@app.before_request
def _acquire_lock():
    _LOCK.acquire()


@app.teardown_request
def _release_lock(exc):
    _LOCK.release()


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_404(err):
    return error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(err):
    return error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return handle_api_error(err)
    return error_response("ERR_INVALID_REQUEST", str(err), 400)


# ---------------------------------------------------------------------------
# Payload / validation helpers
# ---------------------------------------------------------------------------

def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise_error(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def check_allowed(data, allowed):
    extra = [k for k in data if k not in allowed]
    if extra:
        raise_error(ERR_INVALID_REQUEST, f"Undeclared field(s): {', '.join(sorted(extra))}")


def req_field(data, field):
    if field not in data or data[field] is None:
        raise_error(ERR_INVALID_REQUEST, f"Missing required field: {field}")
    return data[field]


def req_string(data, field):
    value = req_field(data, field)
    if not isinstance(value, str):
        raise_error(ERR_INVALID_REQUEST, f"Field '{field}' must be a string")
    return value


def req_int(data, field):
    value = req_field(data, field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise_error(ERR_INVALID_REQUEST, f"Field '{field}' must be an integer")
    return value


def req_decimal(data, field):
    return dec(req_field(data, field), field)


def opt_decimal(data, field):
    if field not in data or data[field] is None:
        return None
    return dec(data[field], field)


def opt_string(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    if not isinstance(data[field], str):
        raise_error(ERR_INVALID_REQUEST, f"Field '{field}' must be a string")
    return data[field]


def req_enum(data, field, members):
    value = req_string(data, field)
    if value not in members:
        raise_error(ERR_INVALID_REQUEST, f"Field '{field}' must be one of {', '.join(members)}")
    return value


def parse_pagination():
    raw_limit = request.args.get("limit", "10")
    raw_offset = request.args.get("offset", "0")
    try:
        limit = int(raw_limit)
        offset = int(raw_offset)
    except (ValueError, TypeError):
        raise_error(ERR_INVALID_REQUEST, "limit/offset must be integers")
    if isinstance(limit, bool) or limit < 1 or limit > 100:
        raise_error(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if isinstance(offset, bool) or offset < 0:
        raise_error(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def list_response(entities, serializer, filters):
    """Sort by created_at ascending (creation order), filter, paginate."""
    items = sorted(entities, key=lambda e: e["_seq"])
    out = [serializer(e) for e in items]
    for field, value in filters.items():
        if value is not None:
            out = [o for o in out if str(o.get(field)) == value]
    limit, offset = parse_pagination()
    total = len(out)
    page = out[offset:offset + limit]
    return success_list(page, limit, offset, total)


def get_or_404(store, entity_id, what):
    entity = store.get(entity_id)
    if entity is None:
        raise_error(ERR_NOT_FOUND, f"{what} not found")
    return entity


def stamp_new(entity):
    entity["id"] = str(uuid.uuid4())
    entity["created_at"] = now_ts()
    entity["updated_at"] = entity["created_at"]
    entity["version"] = 1
    entity["_seq"] = db.next_seq()
    return entity


def touch(entity):
    """Every mutation refreshes updated_at and increments version by exactly 1."""
    entity["updated_at"] = now_ts()
    entity["version"] += 1


# ---------------------------------------------------------------------------
# Ownership helpers (PRD §2.1: entity-backed ownership for Customer callers)
# ---------------------------------------------------------------------------

def appointment_of_animal(animal):
    return db.appointments.get(animal["appointment_id"])


def animal_of_share(share):
    return db.animals.get(share["animal_id"])


def require_owns_appointment(user_id, role, appt):
    if role == "Customer" and appt["customer_id"] != user_id:
        raise_error(ERR_FORBIDDEN, "Customer does not own this appointment")


def require_owns_share(user_id, role, share):
    if role == "Customer" and share["owner_customer_id"] != user_id:
        raise_error(ERR_FORBIDDEN, "Customer does not own this share")


def require_owns_animal(user_id, role, animal):
    """A Customer owns an animal via the booking appointment or via a share."""
    if role != "Customer":
        return
    appt = appointment_of_animal(animal)
    if appt is not None and appt["customer_id"] == user_id:
        return
    for s in db.shares.values():
        if s["animal_id"] == animal["id"] and s["owner_customer_id"] == user_id:
            return
    raise_error(ERR_FORBIDDEN, "Customer does not own this animal")


def require_booking_customer_of_share(user_id, role, share):
    """Booking customer (appointment.customer_id) or staff — used for share
    creation/removal, which belong to the booking party, not the share owner."""
    if role != "Customer":
        return
    animal = animal_of_share(share)
    appt = appointment_of_animal(animal) if animal else None
    if appt is None or appt["customer_id"] != user_id:
        raise_error(ERR_FORBIDDEN, "Only the booking customer or staff may do this")


def owned_share_ids(user_id):
    return {s["id"] for s in db.shares.values() if s["owner_customer_id"] == user_id}


# ---------------------------------------------------------------------------
# Cross-entity cascades (PRD §2.9)
# ---------------------------------------------------------------------------

def recompute_invoice_final(inv, now):
    """Pinned as-of-now storage recomputation: persists storage_cents, total,
    and amount_due under the final variant. Does not touch version/updated_at
    by itself — callers fold it into their own mutation."""
    rec = ser.record_of_share(inv["share_id"])
    if rec is None:
        inv["storage_cents"] = 0
    elif rec["status"] == "STORED":
        inv["storage_cents"] = ser.record_accrued_cents(rec, now)
    elif rec["status"] == "PICKED_UP":
        inv["storage_cents"] = storage_accrued_cents(
            storage_days_stored(rec["ready_at_dt"], rec["picked_up_at_dt"]))
    else:  # ABANDONED — frozen at the sweep instant
        inv["storage_cents"] = rec["accrued_fee_cents"]


def charge_customer_strike(customer_id):
    customer = db.customers.get(customer_id)
    if customer is not None:
        customer["no_show_strikes"] += 1
        touch(customer)


def void_animal(animal):
    """Animal EXPECTED -> VOIDED (system cascade). Capacity release is implicit:
    booked_head is derived from appointments still holding the day."""
    animal["status"] = "VOIDED"
    touch(animal)


def bubble_up_animal_complete(animal):
    """READY -> COMPLETE once every share of the animal is terminal."""
    if animal["status"] != "READY":
        return
    shares = [s for s in db.shares.values() if s["animal_id"] == animal["id"]]
    if shares and all(s["status"] in ("PICKED_UP", "FORFEITED") for s in shares):
        animal["status"] = "COMPLETE"
        touch(animal)


def forfeit_share(share, now):
    """CarcassShare READY -> FORFEITED and its downstream cascade."""
    share["status"] = "FORFEITED"
    touch(share)
    inv = ser.invoice_of_share(share["id"])
    if inv is not None and inv["status"] in ("OPEN", "PARTIALLY_PAID"):
        # Invoice (OPEN | PARTIALLY_PAID) -> COLLECTIONS with surcharge; the
        # move to COLLECTIONS charges the owning customer a strike.
        recompute_invoice_final(inv, now)
        inv["surcharge_cents"] = ABANDON_SURCHARGE_CENTS
        inv["status"] = "COLLECTIONS"
        touch(inv)
        charge_customer_strike(share["owner_customer_id"])
    animal = animal_of_share(share)
    if animal is not None:
        bubble_up_animal_complete(animal)


def no_show_cascade(appt):
    """Full no-show cascade (manual mark or run-daily sweep)."""
    for animal in [a for a in db.animals.values() if a["appointment_id"] == appt["id"]]:
        if animal["status"] == "EXPECTED":
            void_animal(animal)
    appt["status"] = "NO_SHOW"
    appt["refund_cents"] = 0  # deposit forfeited; plant retains deposit_paid_cents
    touch(appt)
    charge_customer_strike(appt["customer_id"])


# ===========================================================================
# Logical clock (PRD §2.4)
# ===========================================================================

def set_clock():
    require_role(("PlantManager",))
    data = body()
    check_allowed(data, {"to_iso8601"})
    to_iso = req_field(data, "to_iso8601")
    dt = parse_dt(to_iso, "to_iso8601")
    db.current_utc_iso = fmt_ts(dt)
    return success_object({"current_utc": db.current_utc_iso}, 200)


app.add_url_rule("/_clock/set_current_utc", "set_clock", set_clock, methods=["POST"])
app.add_url_rule(f"{PREFIX}/_clock/set_current_utc", "set_clock_prefixed", set_clock, methods=["POST"])


# ===========================================================================
# Customers
# ===========================================================================

@app.route(f"{PREFIX}/customers", methods=["POST"])
def create_customer():
    require_role(STAFF)
    data = body()
    check_allowed(data, {"name", "phone", "email"})
    name = req_string(data, "name")
    phone = req_string(data, "phone")
    email = req_string(data, "email")
    customer = stamp_new({
        "name": name, "phone": phone, "email": email,
        "no_show_strikes": 0,
    })
    db.customers[customer["id"]] = customer
    return success_object(ser.customer_out(customer), 201)


@app.route(f"{PREFIX}/customers", methods=["GET"])
def list_customers():
    require_role(STAFF)
    return list_response(list(db.customers.values()), ser.customer_out,
                         {"status": request.args.get("status")})


@app.route(f"{PREFIX}/customers/<cid>", methods=["GET"])
def get_customer(cid):
    user_id, role = require_role(ALL_ROLES)
    customer = get_or_404(db.customers, cid, "Customer")
    if role == "Customer" and cid != user_id:
        raise_error(ERR_FORBIDDEN, "Customer may only read their own record")
    return success_object(ser.customer_out(customer), 200)


# ===========================================================================
# Capacity days
# ===========================================================================

@app.route(f"{PREFIX}/capacity-days", methods=["POST"])
def create_capacity_day():
    require_role(("PlantManager",))
    data = body()
    check_allowed(data, {"date", "capacity_head"})
    raw_date = req_field(data, "date")
    date_value = parse_date(raw_date, "date")
    capacity_head = req_int(data, "capacity_head")
    if capacity_head < 1:
        raise_error(ERR_INVALID_REQUEST, "capacity_head must be >= 1")
    for d in db.capacity_days.values():
        if d["date"] == raw_date:
            raise_error(ERR_INVALID_REQUEST, "CapacityDay.date must be unique")
    day = stamp_new({
        "date": raw_date,
        "date_value": date_value,
        "capacity_head": capacity_head,
    })
    db.capacity_days[day["id"]] = day
    return success_object(ser.capacity_day_out(day), 201)


@app.route(f"{PREFIX}/capacity-days", methods=["GET"])
def list_capacity_days():
    require_role(ALL_ROLES)
    filters = {
        "status": request.args.get("status"),
    }
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    items = sorted(db.capacity_days.values(), key=lambda e: e["_seq"])
    if date_from is not None:
        items = [d for d in items if d["date"] >= date_from]
    if date_to is not None:
        items = [d for d in items if d["date"] <= date_to]
    out = [ser.capacity_day_out(d) for d in items]
    if filters["status"] is not None:
        out = [o for o in out if o["status"] == filters["status"]]
    limit, offset = parse_pagination()
    total = len(out)
    return success_list(out[offset:offset + limit], limit, offset, total)


# ===========================================================================
# Appointments
# ===========================================================================

def check_lead_time(day):
    if (day["date_value"] - today()).days < MIN_LEAD_DAYS:
        raise_error(ERR_LEAD_TIME_TOO_SHORT,
                    f"CapacityDay.date must be at least {MIN_LEAD_DAYS} days out")


def check_capacity(day, head_count):
    if ser.day_booked_head(day["id"]) + head_count > day["capacity_head"]:
        raise_error(ERR_CAPACITY_FULL, "CapacityDay has insufficient headroom")


def check_not_blocked(customer):
    if calc.customer_status(customer["no_show_strikes"]) == "BLOCKED":
        raise_error(ERR_CUSTOMER_BLOCKED, "Customer is BLOCKED from new bookings")


def check_no_collections(customer_id):
    owned = owned_share_ids(customer_id)
    for inv in db.invoices.values():
        if inv["share_id"] in owned and inv["status"] == "COLLECTIONS":
            raise_error(ERR_OUTSTANDING_BALANCE,
                        "Customer has an invoice in COLLECTIONS")


@app.route(f"{PREFIX}/appointments", methods=["POST"])
def create_appointment():
    user_id, role = require_role(ALL_ROLES)
    data = body()
    # Ownership (priority 2): a Customer books only for themselves.
    if role == "Customer" and "customer_id" in data and data["customer_id"] != user_id:
        raise_error(ERR_FORBIDDEN, "Customer may only book for themselves")
    # Body FK existence (priority 3).
    customer = None
    if isinstance(data.get("customer_id"), str):
        customer = get_or_404(db.customers, data["customer_id"], "Customer")
    day = None
    if isinstance(data.get("capacity_day_id"), str):
        day = get_or_404(db.capacity_days, data["capacity_day_id"], "CapacityDay")
    # Body well-formedness (priority 3).
    check_allowed(data, {"customer_id", "capacity_day_id", "species", "head_count"})
    if customer is None:
        customer = get_or_404(db.customers, req_string(data, "customer_id"), "Customer")
    if day is None:
        day = get_or_404(db.capacity_days, req_string(data, "capacity_day_id"), "CapacityDay")
    species = req_enum(data, "species", SPECIES)
    head_count = req_int(data, "head_count")
    if head_count < 1:
        raise_error(ERR_INVALID_REQUEST, "head_count must be >= 1")
    # Business constraints (priority 6), then temporal (7), then fiscal (9).
    check_not_blocked(customer)
    check_capacity(day, head_count)
    check_lead_time(day)
    check_no_collections(customer["id"])
    # deposit_quote — variant selected by Customer.status at booking time.
    quote = deposit_quote_cents(calc.customer_status(customer["no_show_strikes"]),
                                species, head_count)
    now = get_now()
    appt = stamp_new({
        "customer_id": customer["id"],
        "capacity_day_id": day["id"],
        "species": species,
        "head_count": head_count,
        "appointment_date": day["date"],
        "deposit_amount_cents": quote,
        "deposit_paid_cents": 0,
        "deposit_due_at_dt": now + timedelta(hours=DEPOSIT_WINDOW_HOURS),
        "refund_cents": 0,
        "status": "PENDING_DEPOSIT",
    })
    db.appointments[appt["id"]] = appt
    return success_object(ser.appointment_out(appt), 201)


@app.route(f"{PREFIX}/appointments", methods=["GET"])
def list_appointments():
    user_id, role = require_role(ALL_ROLES)
    items = list(db.appointments.values())
    if role == "Customer":
        items = [a for a in items if a["customer_id"] == user_id]
    return list_response(items, ser.appointment_out, {
        "customer_id": request.args.get("customer_id"),
        "capacity_day_id": request.args.get("capacity_day_id"),
        "status": request.args.get("status"),
    })


@app.route(f"{PREFIX}/appointments/<aid>", methods=["GET"])
def get_appointment(aid):
    user_id, role = require_role(ALL_ROLES)
    appt = get_or_404(db.appointments, aid, "Appointment")
    require_owns_appointment(user_id, role, appt)
    return success_object(ser.appointment_out(appt), 200)


@app.route(f"{PREFIX}/appointments/<aid>/pay-deposit", methods=["POST"])
def pay_deposit(aid):
    user_id, role = require_role(("Customer",))
    appt = get_or_404(db.appointments, aid, "Appointment")
    require_owns_appointment(user_id, role, appt)
    data = body()
    check_allowed(data, {"amount_cents"})
    amount = req_int(data, "amount_cents")
    if amount < 1:
        raise_error(ERR_INVALID_REQUEST, "amount_cents must be >= 1")
    if appt["status"] != "PENDING_DEPOSIT":
        raise_error(ERR_INVALID_STATE, "Deposit can only be paid while PENDING_DEPOSIT")
    if amount < appt["deposit_amount_cents"] - appt["deposit_paid_cents"]:
        raise_error(ERR_DEPOSIT_INSUFFICIENT, "Payment below the remaining deposit due")
    appt["deposit_paid_cents"] += amount
    appt["status"] = "CONFIRMED"
    touch(appt)
    # Confirming creates one EXPECTED animal per booked head.
    for _ in range(appt["head_count"]):
        animal = stamp_new({
            "appointment_id": appt["id"],
            "tag_id": None,
            "species": appt["species"],
            "live_weight_lbs": None,
            "hanging_weight_lbs": None,
            "received_at_dt": None,
            "slaughtered_at_dt": None,
            "weighed_at_dt": None,
            "status": "EXPECTED",
        })
        db.animals[animal["id"]] = animal
    return success_object(ser.appointment_out(appt), 200)


@app.route(f"{PREFIX}/appointments/<aid>/cancel", methods=["POST"])
def cancel_appointment(aid):
    user_id, role = require_role(ALL_ROLES)
    appt = get_or_404(db.appointments, aid, "Appointment")
    require_owns_appointment(user_id, role, appt)
    data = body()
    check_allowed(data, {"reason"})
    opt_string(data, "reason")
    if appt["status"] == "PENDING_DEPOSIT":
        # Unconditional: refund whatever deposit cash has been received.
        appt["refund_cents"] = appt["deposit_paid_cents"]
    elif appt["status"] == "CONFIRMED":
        animals = [a for a in db.animals.values() if a["appointment_id"] == aid]
        if not all(a["status"] == "EXPECTED" for a in animals):
            raise_error(ERR_INVALID_STATE,
                        "Cannot cancel once any animal has progressed past drop-off")
        # cancel_refund_policy: full refund at >= 7 whole days out, else 0.
        days_before = (parse_date(appt["appointment_date"], "appointment_date") - today()).days
        appt["refund_cents"] = (appt["deposit_paid_cents"]
                                if days_before >= CANCEL_FULL_REFUND_DAYS else 0)
        for animal in animals:
            void_animal(animal)
    else:
        raise_error(ERR_INVALID_STATE, f"Cannot cancel from {appt['status']}")
    appt["status"] = "CANCELLED"
    touch(appt)
    return success_object(ser.appointment_out(appt), 200)


@app.route(f"{PREFIX}/appointments/<aid>/reschedule", methods=["POST"])
def reschedule_appointment(aid):
    user_id, role = require_role(("Customer",))
    appt = get_or_404(db.appointments, aid, "Appointment")
    require_owns_appointment(user_id, role, appt)
    data = body()
    if isinstance(data.get("new_capacity_day_id"), str):
        get_or_404(db.capacity_days, data["new_capacity_day_id"], "CapacityDay")
    check_allowed(data, {"new_capacity_day_id", "expected_appointment_version"})
    new_day = get_or_404(db.capacity_days, req_string(data, "new_capacity_day_id"), "CapacityDay")
    expected_version = req_int(data, "expected_appointment_version")
    if appt["status"] not in ("PENDING_DEPOSIT", "CONFIRMED"):
        raise_error(ERR_INVALID_STATE, f"Cannot reschedule from {appt['status']}")
    if expected_version != appt["version"]:
        raise_error(ERR_STALE_VERSION, "expected_appointment_version is stale")
    check_capacity(new_day, appt["head_count"])
    check_lead_time(new_day)
    # Self-loop: only the reserved day moves; the deposit quote does not change.
    appt["capacity_day_id"] = new_day["id"]
    appt["appointment_date"] = new_day["date"]
    touch(appt)
    return success_object(ser.appointment_out(appt), 200)


@app.route(f"{PREFIX}/appointments/<aid>/no-show", methods=["POST"])
def mark_no_show(aid):
    require_role(STAFF)
    appt = get_or_404(db.appointments, aid, "Appointment")
    data = body()
    check_allowed(data, set())
    if appt["status"] != "CONFIRMED":
        raise_error(ERR_INVALID_STATE, f"Cannot mark no-show from {appt['status']}")
    animals = [a for a in db.animals.values() if a["appointment_id"] == aid]
    if not all(a["status"] == "EXPECTED" for a in animals):
        raise_error(ERR_INVALID_STATE, "Partial drop-off: appointment is live, not abandoned")
    if today() < parse_date(appt["appointment_date"], "appointment_date"):
        raise_error(ERR_NO_SHOW_PREMATURE, "No-show cannot be marked before the appointment date")
    no_show_cascade(appt)
    return success_object(ser.appointment_out(appt), 200)


@app.route(f"{PREFIX}/appointments/<aid>/animals", methods=["GET"])
def list_appointment_animals(aid):
    user_id, role = require_role(ALL_ROLES)
    appt = get_or_404(db.appointments, aid, "Appointment")
    require_owns_appointment(user_id, role, appt)
    items = [a for a in db.animals.values() if a["appointment_id"] == aid]
    return list_response(items, ser.animal_out, {})


# ===========================================================================
# Animals
# ===========================================================================

@app.route(f"{PREFIX}/animals/<aid>", methods=["GET"])
def get_animal(aid):
    user_id, role = require_role(ALL_ROLES)
    animal = get_or_404(db.animals, aid, "Animal")
    require_owns_animal(user_id, role, animal)
    return success_object(ser.animal_out(animal), 200)


@app.route(f"{PREFIX}/animals/<aid>/receive", methods=["POST"])
def receive_animal(aid):
    require_role(STAFF)
    animal = get_or_404(db.animals, aid, "Animal")
    data = body()
    check_allowed(data, {"tag_id", "live_weight_lbs"})
    tag_id = req_string(data, "tag_id")
    live_weight = round_lb(req_decimal(data, "live_weight_lbs"))
    if animal["status"] != "EXPECTED":
        raise_error(ERR_INVALID_STATE, f"Cannot receive from {animal['status']}")
    for other in db.animals.values():
        if other["id"] != aid and other["status"] != "VOIDED" and other["tag_id"] == tag_id:
            raise_error(ERR_DUPLICATE_TAG, "tag_id already used by another animal")
    animal["tag_id"] = tag_id
    animal["live_weight_lbs"] = live_weight
    animal["received_at_dt"] = get_now()
    animal["status"] = "RECEIVED"
    touch(animal)
    # Bubble-up: last EXPECTED animal received -> appointment COMPLETED.
    appt = appointment_of_animal(animal)
    if appt is not None and appt["status"] == "CONFIRMED":
        remaining = [a for a in db.animals.values()
                     if a["appointment_id"] == appt["id"] and a["status"] == "EXPECTED"]
        if not remaining:
            appt["status"] = "COMPLETED"
            touch(appt)
    return success_object(ser.animal_out(animal), 200)


@app.route(f"{PREFIX}/animals/<aid>/slaughter", methods=["POST"])
def slaughter_animal(aid):
    require_role(STAFF)
    animal = get_or_404(db.animals, aid, "Animal")
    data = body()
    check_allowed(data, set())
    if animal["status"] != "RECEIVED":
        raise_error(ERR_INVALID_STATE, f"Cannot slaughter from {animal['status']}")
    animal["slaughtered_at_dt"] = get_now()
    animal["status"] = "SLAUGHTERED"
    touch(animal)
    return success_object(ser.animal_out(animal), 200)


@app.route(f"{PREFIX}/animals/<aid>/weigh", methods=["POST"])
def weigh_animal(aid):
    require_role(STAFF)
    animal = get_or_404(db.animals, aid, "Animal")
    data = body()
    check_allowed(data, {"hanging_weight_lbs"})
    hanging = round_lb(req_decimal(data, "hanging_weight_lbs"))
    if animal["status"] != "SLAUGHTERED":
        raise_error(ERR_INVALID_STATE, f"Cannot weigh from {animal['status']}")
    animal["hanging_weight_lbs"] = hanging
    animal["weighed_at_dt"] = get_now()  # hang-time clock starts here
    animal["status"] = "HANGING"
    touch(animal)
    return success_object(ser.animal_out(animal), 200)


@app.route(f"{PREFIX}/animals/<aid>/start-fabrication", methods=["POST"])
def start_fabrication(aid):
    require_role(STAFF)
    animal = get_or_404(db.animals, aid, "Animal")
    data = body()
    check_allowed(data, set())
    if animal["status"] != "HANGING":
        raise_error(ERR_INVALID_STATE, f"Cannot start fabrication from {animal['status']}")
    shares = sorted((s for s in db.shares.values() if s["animal_id"] == aid),
                    key=lambda s: s["_seq"])
    confirmed = [s for s in shares if s["status"] == "CONFIRMED"]
    total_frac = sum((Decimal(s["share_fraction"]) for s in confirmed), Decimal("0"))
    if not confirmed or total_frac != Decimal("1"):
        raise_error(ERR_SPLIT_NOT_FINALIZED, "Split is not finalized for this animal")
    if get_now() < animal["weighed_at_dt"] + timedelta(days=MIN_HANG_DAYS):
        raise_error(ERR_MIN_HANG_NOT_MET, "Minimum hang time not met")
    sheets = []
    for s in confirmed:
        cs = ser.sheet_of_share(s["id"])
        if cs is None or cs["status"] != "SUBMITTED":
            raise_error(ERR_CUT_SHEET_MISSING,
                        "Every CONFIRMED share needs a SUBMITTED cut sheet")
        sheets.append(cs)
    for cs in sheets:
        cs["status"] = "LOCKED"
        touch(cs)
    animal["status"] = "CUTTING"
    touch(animal)
    return success_object(ser.animal_out(animal), 200)


@app.route(f"{PREFIX}/animals/<aid>/complete-fabrication", methods=["POST"])
def complete_fabrication(aid):
    require_role(STAFF)
    animal = get_or_404(db.animals, aid, "Animal")
    data = body()
    check_allowed(data, set())
    if animal["status"] != "CUTTING":
        raise_error(ERR_INVALID_STATE, f"Cannot complete fabrication from {animal['status']}")
    shares = sorted((s for s in db.shares.values()
                     if s["animal_id"] == aid and s["status"] == "CONFIRMED"),
                    key=lambda s: s["_seq"])
    stored_count = sum(1 for r in db.storage_records.values() if r["status"] == "STORED")
    if stored_count + len(shares) > FREEZER_CAPACITY_UNITS:
        raise_error(ERR_FREEZER_FULL, "Freezer capacity exceeded")
    now = get_now()
    for s in shares:
        s["status"] = "READY"
        touch(s)
        rec = stamp_new({
            "share_id": s["id"],
            "ready_at_dt": now,
            "picked_up_at_dt": None,
            "freezer_units": FREEZER_UNITS_PER_SHARE,
            "days_stored": 0,
            "accrued_fee_cents": 0,
            "status": "STORED",
        })
        db.storage_records[rec["id"]] = rec
        # Invoice recomputed with final-variant totals (storage 0 at ready).
        inv = ser.invoice_of_share(s["id"])
        if inv is not None:
            recompute_invoice_final(inv, now)
    animal["status"] = "READY"
    touch(animal)
    return success_object(ser.animal_out(animal), 200)


# ===========================================================================
# Carcass shares
# ===========================================================================

@app.route(f"{PREFIX}/animals/<aid>/shares", methods=["POST"])
def create_share(aid):
    user_id, role = require_role(ALL_ROLES)
    animal = get_or_404(db.animals, aid, "Animal")
    appt = appointment_of_animal(animal)
    if role == "Customer" and (appt is None or appt["customer_id"] != user_id):
        raise_error(ERR_FORBIDDEN, "Only the booking customer or staff may add shares")
    data = body()
    if isinstance(data.get("owner_customer_id"), str):
        get_or_404(db.customers, data["owner_customer_id"], "Customer")
    check_allowed(data, {"owner_customer_id", "share_fraction", "intended_use"})
    owner = get_or_404(db.customers, req_string(data, "owner_customer_id"), "Customer")
    fraction = req_decimal(data, "share_fraction")
    if fraction <= 0 or fraction > 1 or not decimal_places_ok(fraction, 3):
        raise_error(ERR_INVALID_REQUEST,
                    "share_fraction must be > 0, <= 1.0, with at most 3 decimal places")
    intended_use = req_enum(data, "intended_use", INTENDED_USES)
    existing = [s for s in db.shares.values() if s["animal_id"] == aid]
    allocated = sum((Decimal(s["share_fraction"]) for s in existing), Decimal("0"))
    if allocated + fraction > 1:
        raise_error(ERR_SPLIT_OVER_ALLOCATED, "Share would push the fraction sum above 1.0")
    share = stamp_new({
        "animal_id": aid,
        "owner_customer_id": owner["id"],
        "share_fraction": fraction,
        "intended_use": intended_use,
        "share_hanging_weight_lbs": None,
        "estimated_share_weight_lbs": None,
        "status": "PENDING",
    })
    db.shares[share["id"]] = share
    return success_object(ser.share_out(share), 201)


@app.route(f"{PREFIX}/animals/<aid>/shares/finalize", methods=["POST"])
def finalize_shares(aid):
    require_role(STAFF)
    animal = get_or_404(db.animals, aid, "Animal")
    data = body()
    check_allowed(data, set())
    if animal["status"] != "HANGING":
        raise_error(ERR_INVALID_STATE, "Split can only be finalized while the animal is HANGING")
    shares = sorted((s for s in db.shares.values() if s["animal_id"] == aid),
                    key=lambda s: s["_seq"])
    total_frac = sum((Decimal(s["share_fraction"]) for s in shares), Decimal("0"))
    if total_frac != Decimal("1"):
        raise_error(ERR_SPLIT_UNDER_ALLOCATED, "Share fractions must sum to exactly 1.0")
    pending = [s for s in shares if s["status"] == "PENDING"]
    if not pending:
        raise_error(ERR_INVALID_STATE, "Split is already finalized")
    appt = appointment_of_animal(animal)
    species = animal["species"]
    # share_weight_allocation: per-share round first, residual to the largest.
    allocate_share_weights(shares, animal["hanging_weight_lbs"],
                           animal["live_weight_lbs"], species)
    # deposit_credit_allocation: appointment -> animal pool, then per share.
    pool = animal_deposit_pool_cents(appt, animal)
    credits = allocate_deposit_credit(shares, pool)
    for s, credit in zip(shares, credits):
        s["status"] = "CONFIRMED"
        touch(s)
        est_w = s["estimated_share_weight_lbs"]
        actual_w = s["share_hanging_weight_lbs"]
        slaughter = slaughter_share_cents(species, s["share_fraction"])
        processing = tiered_processing_cents(actual_w, species)
        provisional = tiered_processing_cents(est_w, species) + slaughter - credit
        total = processing + slaughter + 0 - credit  # storage 0, surcharge 0
        invoice = stamp_new({
            "share_id": s["id"],
            "species": species,
            "processing_fee_cents": processing,
            "slaughter_share_cents": slaughter,
            "storage_cents": 0,
            "storage_waived": False,
            "surcharge_cents": 0,
            "deposit_credit_cents": credit,
            "provisional_total_cents": provisional,
            "amount_paid_cents": 0,
            "status": "OPEN",
        })
        db.invoices[invoice["id"]] = invoice
        owner = db.customers.get(s["owner_customer_id"])
        owner_name = owner["name"] if owner else s["owner_customer_id"]
        label = stamp_new({
            "share_id": s["id"],
            "program": "CUSTOM_EXEMPT",
            "label_text": (f"NOT FOR SALE — {owner_name} — {species} carcass share "
                           f"{s['share_fraction']} (animal tag {animal['tag_id']})"),
            "status": "PENDING",
        })
        db.labels[label["id"]] = label
    return success_array([ser.share_out(s) for s in shares], 200)


@app.route(f"{PREFIX}/shares", methods=["GET"])
def list_shares():
    user_id, role = require_role(ALL_ROLES)
    items = list(db.shares.values())
    if role == "Customer":
        items = [s for s in items if s["owner_customer_id"] == user_id]
    return list_response(items, ser.share_out, {
        "animal_id": request.args.get("animal_id"),
        "owner_customer_id": request.args.get("owner_customer_id"),
        "status": request.args.get("status"),
    })


@app.route(f"{PREFIX}/shares/<sid>", methods=["GET"])
def get_share(sid):
    user_id, role = require_role(ALL_ROLES)
    share = get_or_404(db.shares, sid, "CarcassShare")
    require_owns_share(user_id, role, share)
    return success_object(ser.share_out(share), 200)


@app.route(f"{PREFIX}/shares/<sid>", methods=["DELETE"])
def delete_share(sid):
    user_id, role = require_role(ALL_ROLES)
    share = get_or_404(db.shares, sid, "CarcassShare")
    require_booking_customer_of_share(user_id, role, share)
    if share["status"] != "PENDING":
        raise_error(ERR_INVALID_STATE, "Only a PENDING share can be removed")
    del db.shares[sid]
    return success_object({}, 204)


# ===========================================================================
# Cut sheets
# ===========================================================================

def validate_cut_sheet_fields(data, partial):
    """Validate cut-sheet instruction domains; returns dict of values present."""
    values = {}
    if not partial or "grind_pct" in data:
        grind = req_int(data, "grind_pct")
        if grind < 0 or grind > 100:
            raise_error(ERR_INVALID_REQUEST, "grind_pct must be between 0 and 100")
        values["grind_pct"] = grind
    elif "grind_pct" in data:
        values["grind_pct"] = data["grind_pct"]
    if not partial or "package_weight_lbs" in data:
        pkg = req_decimal(data, "package_weight_lbs")
        if pkg < 1:
            raise_error(ERR_INVALID_REQUEST, "package_weight_lbs must be >= 1.0")
        values["package_weight_lbs"] = round_lb(pkg)
    elif "package_weight_lbs" in data:
        values["package_weight_lbs"] = data["package_weight_lbs"]
    if "steak_thickness_in" in data and data["steak_thickness_in"] is not None:
        steak = dec(data["steak_thickness_in"], "steak_thickness_in")
        if steak < Decimal("0.5") or steak > Decimal("2.0"):
            raise_error(ERR_INVALID_REQUEST, "steak_thickness_in must be between 0.5 and 2.0")
        values["steak_thickness_in"] = steak
    elif "steak_thickness_in" in data:
        values["steak_thickness_in"] = None
    if "notes" in data:
        values["notes"] = opt_string(data, "notes", "")
    return values


@app.route(f"{PREFIX}/shares/<sid>/cut-sheet", methods=["POST"])
def create_cut_sheet(sid):
    user_id, role = require_role(("Customer",))
    share = get_or_404(db.shares, sid, "CarcassShare")
    require_owns_share(user_id, role, share)
    data = body()
    check_allowed(data, {"grind_pct", "package_weight_lbs", "steak_thickness_in", "notes"})
    values = validate_cut_sheet_fields(data, partial=False)
    if ser.sheet_of_share(sid) is not None:
        raise_error(ERR_CUT_SHEET_EXISTS, "Share already has a cut sheet")
    sheet = stamp_new({
        "share_id": sid,
        "grind_pct": values["grind_pct"],
        "package_weight_lbs": values["package_weight_lbs"],
        "steak_thickness_in": values.get("steak_thickness_in"),
        "notes": values.get("notes", ""),
        "status": "DRAFT",
    })
    db.cut_sheets[sheet["id"]] = sheet
    return success_object(ser.cut_sheet_out(sheet), 201)


@app.route(f"{PREFIX}/cut-sheets", methods=["GET"])
def list_cut_sheets():
    user_id, role = require_role(ALL_ROLES)
    items = list(db.cut_sheets.values())
    if role == "Customer":
        items = [cs for cs in items if cs["share_id"] in owned_share_ids(user_id)]
    return list_response(items, ser.cut_sheet_out, {
        "share_id": request.args.get("share_id"),
        "status": request.args.get("status"),
    })


@app.route(f"{PREFIX}/cut-sheets/<cid>", methods=["GET"])
def get_cut_sheet(cid):
    user_id, role = require_role(ALL_ROLES)
    sheet = get_or_404(db.cut_sheets, cid, "CutSheet")
    if role == "Customer" and sheet["share_id"] not in owned_share_ids(user_id):
        raise_error(ERR_FORBIDDEN, "Customer does not own this cut sheet")
    return success_object(ser.cut_sheet_out(sheet), 200)


@app.route(f"{PREFIX}/cut-sheets/<cid>/submit", methods=["POST"])
def submit_cut_sheet(cid):
    user_id, role = require_role(("Customer",))
    sheet = get_or_404(db.cut_sheets, cid, "CutSheet")
    if role == "Customer" and sheet["share_id"] not in owned_share_ids(user_id):
        raise_error(ERR_FORBIDDEN, "Customer does not own this cut sheet")
    data = body()
    check_allowed(data, set())
    if sheet["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, f"Cannot submit from {sheet['status']}")
    share = db.shares.get(sheet["share_id"])
    if share is None or share["status"] not in ("PENDING", "CONFIRMED"):
        raise_error(ERR_INVALID_STATE, "Fabrication has begun; instructions are locked")
    if sheet["grind_pct"] > MAX_GRIND_PCT:
        raise_error(ERR_YIELD_INFEASIBLE, f"grind_pct exceeds MAX_GRIND_PCT ({MAX_GRIND_PCT})")
    sheet["status"] = "SUBMITTED"
    touch(sheet)
    return success_object(ser.cut_sheet_out(sheet), 200)


@app.route(f"{PREFIX}/cut-sheets/<cid>/revise", methods=["POST"])
def revise_cut_sheet(cid):
    user_id, role = require_role(("Customer",))
    sheet = get_or_404(db.cut_sheets, cid, "CutSheet")
    if role == "Customer" and sheet["share_id"] not in owned_share_ids(user_id):
        raise_error(ERR_FORBIDDEN, "Customer does not own this cut sheet")
    data = body()
    check_allowed(data, {"expected_cut_sheet_version", "grind_pct",
                         "package_weight_lbs", "steak_thickness_in", "notes"})
    expected_version = req_int(data, "expected_cut_sheet_version")
    values = validate_cut_sheet_fields(data, partial=True)
    if sheet["status"] not in ("DRAFT", "SUBMITTED"):
        raise_error(ERR_INVALID_STATE, f"Cannot revise from {sheet['status']}")
    if expected_version != sheet["version"]:
        raise_error(ERR_STALE_VERSION, "expected_cut_sheet_version is stale")
    for field, value in values.items():
        sheet[field] = value
    if sheet["status"] == "SUBMITTED":
        sheet["status"] = "DRAFT"  # must be submitted anew
    touch(sheet)
    return success_object(ser.cut_sheet_out(sheet), 200)


# ===========================================================================
# Invoices
# ===========================================================================

@app.route(f"{PREFIX}/invoices", methods=["GET"])
def list_invoices():
    user_id, role = require_role(ALL_ROLES)
    items = list(db.invoices.values())
    if role == "Customer":
        items = [inv for inv in items if inv["share_id"] in owned_share_ids(user_id)]
    return list_response(items, ser.invoice_out, {
        "share_id": request.args.get("share_id"),
        "status": request.args.get("status"),
    })


@app.route(f"{PREFIX}/invoices/<iid>", methods=["GET"])
def get_invoice(iid):
    user_id, role = require_role(ALL_ROLES)
    inv = get_or_404(db.invoices, iid, "Invoice")
    if role == "Customer" and inv["share_id"] not in owned_share_ids(user_id):
        raise_error(ERR_FORBIDDEN, "Customer does not own this invoice")
    return success_object(ser.invoice_out(inv), 200)


@app.route(f"{PREFIX}/invoices/<iid>/payments", methods=["POST"])
def record_payment(iid):
    user_id, role = require_role(ALL_ROLES)
    inv = get_or_404(db.invoices, iid, "Invoice")
    if role == "Customer" and inv["share_id"] not in owned_share_ids(user_id):
        raise_error(ERR_FORBIDDEN, "Customer does not own this invoice")
    data = body()
    check_allowed(data, {"amount_cents"})
    amount = req_int(data, "amount_cents")
    if amount < 1:
        raise_error(ERR_INVALID_REQUEST, "amount_cents must be >= 1")
    if inv["status"] not in ("OPEN", "PARTIALLY_PAID", "COLLECTIONS", "PAID"):
        raise_error(ERR_INVALID_STATE, f"Cannot pay an invoice in {inv['status']}")
    # Storage recomputed as-of-now (final variant) before applying the payment.
    recompute_invoice_final(inv, get_now())
    _, _, due = ser.invoice_live_amounts(inv)
    if inv["status"] == "PAID" and due == 0:
        # PAID with a zero balance is terminal and rejects further payments.
        # (Accrual since the last payment reopens a payable balance; the
        # pickup gate in §3.7 depends on that balance being settleable.)
        raise_error(ERR_INVALID_STATE, "Cannot pay an invoice in PAID")
    inv["amount_paid_cents"] += amount
    if amount >= due:
        inv["status"] = "PAID"
    elif inv["status"] in ("OPEN", "PARTIALLY_PAID", "PAID"):
        inv["status"] = "PARTIALLY_PAID"
    # A partial payment on COLLECTIONS leaves it in COLLECTIONS.
    touch(inv)
    return success_object(ser.invoice_out(inv), 200)


@app.route(f"{PREFIX}/invoices/<iid>/waive-storage", methods=["POST"])
def waive_storage(iid):
    require_role(("PlantManager",))
    inv = get_or_404(db.invoices, iid, "Invoice")
    data = body()
    check_allowed(data, set())
    recompute_invoice_final(inv, get_now())
    inv["storage_waived"] = True
    touch(inv)
    return success_object(ser.invoice_out(inv), 200)


# ===========================================================================
# Storage records
# ===========================================================================

@app.route(f"{PREFIX}/storage-records", methods=["GET"])
def list_storage_records():
    user_id, role = require_role(ALL_ROLES)
    items = list(db.storage_records.values())
    if role == "Customer":
        items = [r for r in items if r["share_id"] in owned_share_ids(user_id)]
    return list_response(items, ser.storage_record_out, {
        "share_id": request.args.get("share_id"),
        "status": request.args.get("status"),
    })


@app.route(f"{PREFIX}/storage-records/<rid>", methods=["GET"])
def get_storage_record(rid):
    user_id, role = require_role(ALL_ROLES)
    rec = get_or_404(db.storage_records, rid, "StorageRecord")
    if role == "Customer" and rec["share_id"] not in owned_share_ids(user_id):
        raise_error(ERR_FORBIDDEN, "Customer does not own this storage record")
    return success_object(ser.storage_record_out(rec), 200)


@app.route(f"{PREFIX}/storage-records/<rid>/pickup", methods=["POST"])
def pickup_storage_record(rid):
    require_role(STAFF)
    rec = get_or_404(db.storage_records, rid, "StorageRecord")
    data = body()
    check_allowed(data, set())
    if rec["status"] != "STORED":
        raise_error(ERR_INVALID_STATE, f"Cannot pick up from {rec['status']}")
    share = get_or_404(db.shares, rec["share_id"], "CarcassShare")
    label = ser.label_of_share(rec["share_id"])
    if label is None or label["status"] != "APPROVED":
        raise_error(ERR_LABEL_NOT_APPROVED, "Label is not APPROVED")
    inv = ser.invoice_of_share(rec["share_id"])
    now = get_now()
    if inv is not None:
        # The invoice must stand PAID after as-of-now storage recomputation;
        # unpaid accrual since the last payment still blocks the door.
        recompute_invoice_final(inv, now)
        _, _, due = ser.invoice_live_amounts(inv)
        if inv["status"] != "PAID" or due != 0:
            raise_error(ERR_INVOICE_NOT_PAID, "Invoice is not PAID")
    # Finalize: picked_up_at stamped; invoice storage frozen at this instant.
    rec["picked_up_at_dt"] = now
    rec["days_stored"] = storage_days_stored(rec["ready_at_dt"], now)
    rec["accrued_fee_cents"] = storage_accrued_cents(rec["days_stored"])
    rec["status"] = "PICKED_UP"
    touch(rec)
    if inv is not None:
        inv["storage_cents"] = rec["accrued_fee_cents"]
        touch(inv)
    if share["status"] == "READY":
        share["status"] = "PICKED_UP"
        touch(share)
    animal = animal_of_share(share)
    if animal is not None:
        bubble_up_animal_complete(animal)
    return success_object(ser.storage_record_out(rec), 200)


# ===========================================================================
# Label records
# ===========================================================================

@app.route(f"{PREFIX}/labels", methods=["GET"])
def list_labels():
    user_id, role = require_role(ALL_ROLES)
    items = list(db.labels.values())
    if role == "Customer":
        items = [lbl for lbl in items if lbl["share_id"] in owned_share_ids(user_id)]
    return list_response(items, ser.label_out, {
        "share_id": request.args.get("share_id"),
        "status": request.args.get("status"),
    })


@app.route(f"{PREFIX}/labels/<lid>", methods=["GET"])
def get_label(lid):
    user_id, role = require_role(ALL_ROLES)
    label = get_or_404(db.labels, lid, "LabelRecord")
    if role == "Customer" and label["share_id"] not in owned_share_ids(user_id):
        raise_error(ERR_FORBIDDEN, "Customer does not own this label")
    return success_object(ser.label_out(label), 200)


@app.route(f"{PREFIX}/labels/<lid>/approve", methods=["POST"])
def approve_label(lid):
    require_role(STAFF)
    label = get_or_404(db.labels, lid, "LabelRecord")
    data = body()
    check_allowed(data, set())
    if label["status"] != "PENDING":
        raise_error(ERR_INVALID_STATE, f"Cannot approve from {label['status']}")
    share = db.shares.get(label["share_id"])
    if share is None or share["intended_use"] != "OWNER_USE":
        raise_error(ERR_RESALE_LABEL_FORBIDDEN,
                    "Custom-exempt product labeled NOT FOR SALE may not be resold")
    label["status"] = "APPROVED"
    touch(label)
    return success_object(ser.label_out(label), 200)


# ===========================================================================
# Daily ops checkpoint
# ===========================================================================

@app.route(f"{PREFIX}/ops/run-daily", methods=["POST"])
def run_daily():
    require_role(STAFF)
    data = body()
    check_allowed(data, set())
    now = get_now()
    expired_ids = []
    no_show_ids = []
    abandoned_ids = []
    # Job 1: expire overdue PENDING_DEPOSIT appointments (strictly past due).
    for appt in sorted(db.appointments.values(), key=lambda a: a["_seq"]):
        if appt["status"] == "PENDING_DEPOSIT" and now > appt["deposit_due_at_dt"]:
            appt["status"] = "EXPIRED"
            touch(appt)
            expired_ids.append(appt["id"])
    # Job 2: auto no-show for CONFIRMED appointments whose date has passed
    # with every animal still EXPECTED.
    for appt in sorted(db.appointments.values(), key=lambda a: a["_seq"]):
        if appt["status"] != "CONFIRMED":
            continue
        if today() <= parse_date(appt["appointment_date"], "appointment_date"):
            continue
        animals = [a for a in db.animals.values() if a["appointment_id"] == appt["id"]]
        if animals and all(a["status"] == "EXPECTED" for a in animals):
            no_show_cascade(appt)
            no_show_ids.append(appt["id"])
    # Job 3: abandon storage past the 21-day limit (days_stored >= 22).
    for rec in sorted(db.storage_records.values(), key=lambda r: r["_seq"]):
        if rec["status"] != "STORED":
            continue
        days = storage_days_stored(rec["ready_at_dt"], now)
        if days > ABANDON_AFTER_DAYS:
            rec["days_stored"] = days
            rec["accrued_fee_cents"] = storage_accrued_cents(days)
            rec["status"] = "ABANDONED"
            touch(rec)
            share = db.shares.get(rec["share_id"])
            if share is not None and share["status"] == "READY":
                forfeit_share(share, now)
            abandoned_ids.append(rec["id"])
    return success_object({
        "expired_appointment_ids": expired_ids,
        "no_show_appointment_ids": no_show_ids,
        "abandoned_storage_ids": abandoned_ids,
    }, 200)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
