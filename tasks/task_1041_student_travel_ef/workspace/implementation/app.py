"""Student Travel EF API — Flask implementation.

Every route traces to a PRD sentence. In-memory store only; empty on boot.
"""

import os
from datetime import datetime

from flask import Flask, request, g, jsonify

import calc
import store
from store import DB, base_fields, touch, now_iso, new_request_id, UTC, ONE_DAY
from errors import (
    ApiError, fail,
    ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED, ERR_VALIDATION,
    ERR_TOUR_NOT_FOUND, ERR_GROUP_LEADER_NOT_FOUND, ERR_DEPARTURE_NOT_FOUND,
    ERR_ENROLLMENT_NOT_FOUND, ERR_PAYMENT_PLAN_NOT_FOUND, ERR_PERMISSION_FORM_NOT_FOUND,
    ERR_ROOMING_NOT_FOUND, ERR_SUPPLIER_NOT_FOUND, ERR_SUPPLIER_BOOKING_NOT_FOUND,
    ERR_CHAPERONE_NOT_FOUND,
    ERR_INVALID_STATE, ERR_DEPARTURE_NOT_OPEN, ERR_ENROLLMENT_CLOSED, ERR_DEPARTURE_FULL,
    ERR_ROOM_FULL, ERR_ROOMING_GENDER_MISMATCH, ERR_DOCS_INCOMPLETE,
    ERR_SUPPLIER_DOUBLE_BOOKED, ERR_CHAPERONE_UNAVAILABLE, ERR_GUARANTEE_NOT_MET,
    ERR_NOT_ENOUGH_CHAPERONES, ERR_PAYMENT_EXCEEDS_BALANCE, ERR_REBOOK_TARGET_INVALID,
    ERR_STALE_VERSION,
)

app = Flask(__name__)

ROLES = {"Operator", "GroupLeader", "Traveler"}
GENDERS = {"MALE", "FEMALE", "NONBINARY"}
ADDONS = {"SINGLE_ROOM", "EXCURSION", "STEM_LAB"}
INSURANCE_TIERS = {"BASIC", "PREMIUM"}
SERVICE_TYPES = {"HOTEL", "BUS", "GUIDE", "FLIGHT"}
ROOM_TYPES = {"DOUBLE": 2, "TRIPLE": 3, "QUAD": 4}
CHAPERONE_ROLE_TYPES = {"TEACHER", "ADULT"}
PAYMENT_KINDS = {"DEPOSIT", "INSTALLMENT", "REFUND", "PENALTY_RETAINED"}
NON_CANCELLED_LIFECYCLE = {"PENDING", "CONFIRMED", "TRAVELING", "COMPLETED"}

EXEMPT_PATHS = {"/health", "/"}


# =========================================================================
# Response envelope
# =========================================================================
def _meta(extra=None):
    m = {"api_request_id": new_request_id(), "api_request_timestamp": now_iso()}
    if extra:
        m.update(extra)
    return m


def ok(data, status=200, list_meta=None):
    rtype = "array" if isinstance(data, list) else "object"
    body = {"meta": _meta(list_meta), "response_type": rtype, "data": data}
    return jsonify(body), status


def err_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


@app.errorhandler(ApiError)
def _handle_api_error(e):
    return err_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def _nf(e):
    return err_response("ERR_NOT_FOUND", "Resource not found.", 404)


@app.errorhandler(405)
def _mna(e):
    return err_response("ERR_INVALID_STATE", "Method not allowed.", 405)


@app.errorhandler(Exception)
def _unhandled(e):
    if isinstance(e, ApiError):
        return _handle_api_error(e)
    return err_response("ERR_INTERNAL", "Internal server error: %s" % e, 500)


# =========================================================================
# Authentication (before every request)
# =========================================================================
@app.before_request
def _authenticate():
    if request.path in EXEMPT_PATHS:
        return None
    role = request.headers.get("X-User-Role")
    if role not in ROLES:
        return err_response(ERR_UNAUTHENTICATED[0], "Missing or invalid X-User-Role.", 401)
    g.role = role
    g.uid = request.headers.get("X-User-ID")
    return None


def require_roles(*allowed):
    if g.role not in allowed:
        fail(ERR_UNAUTHORIZED, "Role %s may not perform this operation." % g.role)


def gl_owns(departure):
    if g.role == "GroupLeader" and departure.get("group_leader_id") != g.uid:
        fail(ERR_UNAUTHORIZED, "GroupLeader does not own this departure.")


def tr_owns(enrollment):
    if g.role == "Traveler" and enrollment.get("id") != g.uid:
        fail(ERR_UNAUTHORIZED, "Traveler may act only on their own enrollment.")


# =========================================================================
# Body / query helpers
# =========================================================================
def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        fail(ERR_VALIDATION, "Request body must be a JSON object.")
    return data


def req_field(data, name):
    if name not in data or data[name] is None:
        fail(ERR_VALIDATION, "Missing required field: %s" % name)
    return data[name]


def as_str(value, name):
    if not isinstance(value, str):
        fail(ERR_VALIDATION, "Field %s must be a string." % name)
    return value


def as_int(value, name, minimum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        fail(ERR_VALIDATION, "Field %s must be an integer." % name)
    if minimum is not None and value < minimum:
        fail(ERR_VALIDATION, "Field %s must be >= %s." % (name, minimum))
    return value


def as_bool(value, name):
    if not isinstance(value, bool):
        fail(ERR_VALIDATION, "Field %s must be a boolean." % name)
    return value


def as_enum(value, name, allowed):
    if value not in allowed:
        fail(ERR_VALIDATION, "Field %s must be one of %s." % (name, sorted(allowed)))
    return value


def parse_dt(value, name):
    if not isinstance(value, str):
        fail(ERR_VALIDATION, "Field %s must be an ISO 8601 string." % name)
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        fail(ERR_VALIDATION, "Field %s is not a valid ISO 8601 datetime." % name)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def pagination():
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    if limit is None:
        limit = 10
    else:
        try:
            limit = int(limit)
        except (ValueError, TypeError):
            fail(ERR_VALIDATION, "limit must be an integer.")
        if limit < 1 or limit > 100:
            fail(ERR_VALIDATION, "limit must be between 1 and 100.")
    if offset is None:
        offset = 0
    else:
        try:
            offset = int(offset)
        except (ValueError, TypeError):
            fail(ERR_VALIDATION, "offset must be an integer.")
        if offset < 0:
            fail(ERR_VALIDATION, "offset must be >= 0.")
    return limit, offset


def paginate(items):
    """items already sorted by created_at asc."""
    limit, offset = pagination()
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta


def sorted_by_created(records):
    return sorted(records, key=lambda r: r["created_at"])


# =========================================================================
# Existence resolvers
# =========================================================================
def get_tour(tid):
    r = DB.tours.get(tid)
    if r is None:
        fail(ERR_TOUR_NOT_FOUND, "Tour not found.")
    return r


def get_leader(lid):
    r = DB.group_leaders.get(lid)
    if r is None:
        fail(ERR_GROUP_LEADER_NOT_FOUND, "Group leader not found.")
    return r


def get_departure(did):
    r = DB.departures.get(did)
    if r is None:
        fail(ERR_DEPARTURE_NOT_FOUND, "Departure not found.")
    return r


def get_enrollment(eid):
    r = DB.enrollments.get(eid)
    if r is None:
        fail(ERR_ENROLLMENT_NOT_FOUND, "Enrollment not found.")
    return r


def get_plan(pid):
    r = DB.payment_plans.get(pid)
    if r is None:
        fail(ERR_PAYMENT_PLAN_NOT_FOUND, "Payment plan not found.")
    return r


def get_form(fid):
    r = DB.permission_forms.get(fid)
    if r is None:
        fail(ERR_PERMISSION_FORM_NOT_FOUND, "Permission form not found.")
    return r


def get_rooming(rid):
    r = DB.rooming_assignments.get(rid)
    if r is None:
        fail(ERR_ROOMING_NOT_FOUND, "Rooming assignment not found.")
    return r


def get_supplier(sid):
    r = DB.suppliers.get(sid)
    if r is None:
        fail(ERR_SUPPLIER_NOT_FOUND, "Supplier not found.")
    return r


def get_booking(bid):
    r = DB.supplier_bookings.get(bid)
    if r is None:
        fail(ERR_SUPPLIER_BOOKING_NOT_FOUND, "Supplier booking not found.")
    return r


def get_chaperone(cid):
    r = DB.chaperones.get(cid)
    if r is None:
        fail(ERR_CHAPERONE_NOT_FOUND, "Chaperone not found.")
    return r


# =========================================================================
# Derived-field reconciliation
# =========================================================================
def enrollments_of(dep_id):
    return [e for e in DB.enrollments.values() if e["departure_id"] == dep_id]


def active_plan_of(enr_id):
    for p in DB.payment_plans.values():
        if p["enrollment_id"] == enr_id and p["status"] in ("ACTIVE", "PAID"):
            return p
    return None


def payments_of(plan_id):
    return [p for p in DB.payments.values() if p["payment_plan_id"] == plan_id]


def recompute_plan_amounts(plan):
    paid = 0
    refunded = 0
    for pay in payments_of(plan["id"]):
        if pay["kind"] in ("DEPOSIT", "INSTALLMENT"):
            paid += pay["amount_cents"]
        elif pay["kind"] == "REFUND":
            paid -= pay["amount_cents"]
            refunded += pay["amount_cents"]
    plan["amount_paid_cents"] = paid
    plan["amount_refunded_cents"] = refunded


def recompute_departure(dep):
    dep_id = dep["id"]
    enrs = enrollments_of(dep_id)
    active = sum(1 for e in enrs if e["lifecycle_status"] != "CANCELLED")
    paid = sum(1 for e in enrs
               if e["payment_status"] == "PAID_IN_FULL" and e["lifecycle_status"] != "CANCELLED")
    free = calc.free_spots(paid, dep["chaperone_ratio"])
    dep["active_enrollment_count"] = active
    dep["paid_in_full_count"] = paid
    dep["free_spots_earned"] = free
    dep["available_seats"] = dep["capacity"] - active - free
    touch(dep)


def recompute_leader(leader):
    total = 0
    for dep in DB.departures.values():
        if dep["group_leader_id"] == leader["id"]:
            total += dep["free_spots_earned"] * dep["price_per_traveler_cents"]
    leader["free_spot_credit_cents"] = total
    touch(leader)


def recompute_departure_and_leader(dep):
    recompute_departure(dep)
    leader = DB.group_leaders.get(dep["group_leader_id"])
    if leader is not None:
        recompute_leader(leader)


# =========================================================================
# Serialization (records are already public-field dicts)
# =========================================================================
def out(rec):
    return dict(rec)


# =========================================================================
# Tours
# =========================================================================
@app.post("/tours")
def create_tour():
    require_roles("Operator")
    data = body()
    name = as_str(req_field(data, "name"), "name")
    destination = as_str(req_field(data, "destination"), "destination")
    nights = as_int(req_field(data, "nights"), "nights", minimum=1)
    base_price = as_int(req_field(data, "base_price_cents"), "base_price_cents", minimum=0)
    rec = base_fields()
    rec.update({"name": name, "destination": destination, "nights": nights,
                "base_price_cents": base_price})
    DB.tours[rec["id"]] = rec
    return ok(out(rec), 201)


@app.get("/tours/<tid>")
def fetch_tour(tid):
    require_roles("Operator", "GroupLeader")
    return ok(out(get_tour(tid)))


# =========================================================================
# Group leaders
# =========================================================================
@app.post("/group-leaders")
def create_leader():
    require_roles("Operator")
    data = body()
    full_name = as_str(req_field(data, "full_name"), "full_name")
    email = as_str(req_field(data, "email"), "email")
    school = as_str(req_field(data, "school_name"), "school_name")
    rec = base_fields()
    rec.update({"full_name": full_name, "email": email, "school_name": school,
                "free_spot_credit_cents": 0})
    DB.group_leaders[rec["id"]] = rec
    return ok(out(rec), 201)


@app.get("/group-leaders/<lid>")
def fetch_leader(lid):
    require_roles("Operator", "GroupLeader")
    rec = get_leader(lid)
    if g.role == "GroupLeader" and rec["id"] != g.uid:
        fail(ERR_UNAUTHORIZED, "GroupLeader may only view their own record.")
    return ok(out(rec))


# =========================================================================
# Departures
# =========================================================================
@app.post("/departures")
def create_departure():
    require_roles("Operator")
    data = body()
    tour_id = as_str(req_field(data, "tour_id"), "tour_id")
    group_leader_id = as_str(req_field(data, "group_leader_id"), "group_leader_id")
    get_tour(tour_id)
    get_leader(group_leader_id)
    depart_date = parse_dt(req_field(data, "depart_date"), "depart_date")
    return_date = parse_dt(req_field(data, "return_date"), "return_date")
    enrollment_deadline = parse_dt(req_field(data, "enrollment_deadline"), "enrollment_deadline")
    early_bird_cutoff = parse_dt(req_field(data, "early_bird_cutoff"), "early_bird_cutoff")
    capacity = as_int(req_field(data, "capacity"), "capacity", minimum=1)
    price = as_int(req_field(data, "price_per_traveler_cents"), "price_per_traveler_cents", minimum=0)
    min_to_guarantee = as_int(req_field(data, "min_to_guarantee"), "min_to_guarantee", minimum=1)
    ratio = data.get("chaperone_ratio")
    if ratio is None:
        ratio = calc.DEFAULT_CHAPERONE_RATIO
    else:
        ratio = as_int(ratio, "chaperone_ratio", minimum=1)
    rec = base_fields()
    rec.update({
        "tour_id": tour_id,
        "group_leader_id": group_leader_id,
        "depart_date": store.iso_from_dt(depart_date),
        "return_date": store.iso_from_dt(return_date),
        "enrollment_deadline": store.iso_from_dt(enrollment_deadline),
        "early_bird_cutoff": store.iso_from_dt(early_bird_cutoff),
        "capacity": capacity,
        "price_per_traveler_cents": price,
        "min_to_guarantee": min_to_guarantee,
        "chaperone_ratio": ratio,
        "status": "DRAFT",
        "active_enrollment_count": 0,
        "paid_in_full_count": 0,
        "free_spots_earned": 0,
        "available_seats": 0,
        # internal datetime cache (not serialized-out separately; strings above are public)
        "_depart_dt": depart_date,
        "_return_dt": return_date,
        "_deadline_dt": enrollment_deadline,
        "_earlybird_dt": early_bird_cutoff,
    })
    DB.departures[rec["id"]] = rec
    return ok(_dep_public(rec), 201)


def _dep_public(dep):
    d = {k: v for k, v in dep.items() if not k.startswith("_")}
    return d


@app.get("/departures/<did>")
def fetch_departure(did):
    require_roles("Operator", "GroupLeader")
    dep = get_departure(did)
    gl_owns(dep)
    return ok(_dep_public(dep))


@app.get("/departures")
def list_departures():
    require_roles("Operator", "GroupLeader")
    tour_id = request.args.get("tour_id")
    group_leader_id = request.args.get("group_leader_id")
    items = list(DB.departures.values())
    if g.role == "GroupLeader":
        items = [d for d in items if d["group_leader_id"] == g.uid]
    if tour_id is not None:
        items = [d for d in items if d["tour_id"] == tour_id]
    if group_leader_id is not None:
        items = [d for d in items if d["group_leader_id"] == group_leader_id]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return ok([_dep_public(d) for d in page], 200, meta)


@app.get("/departures/<did>/summary")
def departure_summary(did):
    require_roles("Operator", "GroupLeader")
    dep = get_departure(did)
    gl_owns(dep)
    enrs = enrollments_of(did)
    active = sum(1 for e in enrs if e["lifecycle_status"] != "CANCELLED")
    paid = sum(1 for e in enrs
               if e["payment_status"] == "PAID_IN_FULL" and e["lifecycle_status"] != "CANCELLED")
    provisional_paying = sum(1 for e in enrs if e["lifecycle_status"] in ("PENDING", "CONFIRMED"))
    ratio = dep["chaperone_ratio"]
    price = dep["price_per_traveler_cents"]
    prov_free = calc.free_spots(provisional_paying, ratio)
    final_free = calc.free_spots(paid, ratio)
    summary = {
        "active_enrollment_count": active,
        "paid_in_full_count": paid,
        "provisional_free_spots": prov_free,
        "final_free_spots": final_free,
        "provisional_credit_cents": prov_free * price,
        "final_credit_cents": final_free * price,
        "available_seats": dep["capacity"] - active - final_free,
    }
    return ok(summary)


@app.post("/departures/<did>/open")
def open_departure(did):
    require_roles("Operator")
    dep = get_departure(did)
    if dep["status"] != "DRAFT":
        fail(ERR_INVALID_STATE, "Departure is not DRAFT.")
    if dep["group_leader_id"] not in DB.group_leaders:
        fail(ERR_GROUP_LEADER_NOT_FOUND, "Group leader not found.")
    if dep["capacity"] < 1:
        fail(ERR_VALIDATION, "capacity must be >= 1.")
    dep["status"] = "OPEN"
    dep["available_seats"] = dep["capacity"] - dep["active_enrollment_count"] - dep["free_spots_earned"]
    touch(dep)
    return ok(_dep_public(dep))


@app.post("/departures/<did>/guarantee")
def guarantee_departure(did):
    require_roles("Operator")
    dep = get_departure(did)
    if dep["status"] != "OPEN":
        fail(ERR_INVALID_STATE, "Departure is not OPEN.")
    enrs = enrollments_of(did)
    active = sum(1 for e in enrs if e["lifecycle_status"] != "CANCELLED")
    if active < dep["min_to_guarantee"]:
        fail(ERR_GUARANTEE_NOT_MET, "Active enrollment count below minimum to guarantee.")
    confirmed_chaperones = sum(1 for c in DB.chaperones.values()
                               if c["departure_id"] == did and c["status"] == "CONFIRMED")
    import math as _m
    required = _m.ceil(active / dep["chaperone_ratio"])
    if confirmed_chaperones < required:
        fail(ERR_NOT_ENOUGH_CHAPERONES, "Not enough confirmed chaperones.")
    dep["status"] = "GUARANTEED"
    recompute_departure_and_leader(dep)
    return ok(_dep_public(dep))


@app.post("/departures/<did>/depart")
def depart_departure(did):
    require_roles("Operator")
    dep = get_departure(did)
    if dep["status"] != "GUARANTEED":
        fail(ERR_INVALID_STATE, "Departure is not GUARANTEED.")
    if DB.clock_now() < dep["_depart_dt"]:
        fail(ERR_INVALID_STATE, "Logical clock is before depart_date.")
    dep["status"] = "DEPARTED"
    touch(dep)
    at_return = DB.clock_now() >= dep["_return_dt"]
    for e in enrollments_of(did):
        if e["lifecycle_status"] == "CONFIRMED":
            e["lifecycle_status"] = "TRAVELING"
            touch(e)
        if at_return and e["lifecycle_status"] == "TRAVELING":
            e["lifecycle_status"] = "COMPLETED"
            touch(e)
    return ok(_dep_public(dep))


@app.post("/departures/<did>/cancel")
def cancel_departure(did):
    require_roles("Operator")
    dep = get_departure(did)
    status = dep["status"]
    if status == "DRAFT":
        dep["status"] = "CANCELLED"
        touch(dep)
        return ok(_dep_public(dep))
    if status not in ("OPEN", "GUARANTEED"):
        fail(ERR_INVALID_STATE, "Departure cannot be cancelled from state %s." % status)
    # full-refund cascade
    for e in enrollments_of(did):
        if e["lifecycle_status"] == "CANCELLED":
            continue
        _cancel_enrollment_cascade(e, dep, reason="DEPARTURE_CANCELLED", force_full_refund=True)
    dep["status"] = "CANCELLED"
    recompute_departure_and_leader(dep)
    return ok(_dep_public(dep))


# =========================================================================
# Enrollment services
# =========================================================================
def _cancel_enrollment_cascade(enr, dep, reason, force_full_refund):
    """Cancel an enrollment and run its refund cascade. Does NOT recompute the
    departure/leader (caller does that once)."""
    enr["lifecycle_status"] = "CANCELLED"
    enr["cancel_reason"] = reason
    plan = active_plan_of(enr["id"])
    if plan is not None:
        plan["status"] = "REFUND_DUE"
        touch(plan)
        amount_paid = plan["amount_paid_cents"]
        if force_full_refund:
            refund = amount_paid
        else:
            days = calc.days_before(dep["_depart_dt"], DB.clock_now())
            pct = calc.refund_pct_str(days, enr["insurance_opted"], enr.get("insurance_tier"))
            refund = calc.refund_amount(amount_paid, pct)
        refund = min(refund, amount_paid) if amount_paid >= 0 else refund
        penalty = amount_paid - min(refund, amount_paid)
        if refund > 0:
            _append_payment(plan, refund, "REFUND", memo="refund on cancellation")
        if penalty > 0:
            _append_payment(plan, penalty, "PENALTY_RETAINED", memo="penalty retained")
        recompute_plan_amounts(plan)
        plan["status"] = "REFUNDED"
        touch(plan)
        enr["payment_status"] = "REFUNDED"
    touch(enr)


def _append_payment(plan, amount_cents, kind, memo=None):
    rec = {"id": store.new_id(), "created_at": now_iso(),
           "payment_plan_id": plan["id"], "amount_cents": amount_cents,
           "kind": kind, "memo": memo}
    DB.payments[rec["id"]] = rec
    return rec


@app.post("/enrollments")
def create_enrollment():
    require_roles("Operator", "GroupLeader")
    data = body()
    departure_id = as_str(req_field(data, "departure_id"), "departure_id")
    dep = get_departure(departure_id)
    gl_owns(dep)
    traveler_name = as_str(req_field(data, "traveler_name"), "traveler_name")
    traveler_dob = parse_dt(req_field(data, "traveler_dob"), "traveler_dob")
    traveler_gender = as_enum(req_field(data, "traveler_gender"), "traveler_gender", GENDERS)
    add_ons = data.get("add_ons", [])
    if add_ons is None:
        add_ons = []
    if not isinstance(add_ons, list):
        fail(ERR_VALIDATION, "add_ons must be an array.")
    for a in add_ons:
        as_enum(a, "add_ons", ADDONS)
    insurance_opted = data.get("insurance_opted", False)
    if insurance_opted is None:
        insurance_opted = False
    as_bool(insurance_opted, "insurance_opted")
    insurance_tier = data.get("insurance_tier")
    if insurance_opted:
        insurance_tier = as_enum(req_field(data, "insurance_tier"), "insurance_tier", INSURANCE_TIERS)
    else:
        insurance_tier = None
    # business gates
    if DB.clock_now() > dep["_deadline_dt"]:
        fail(ERR_ENROLLMENT_CLOSED, "Enrollment deadline has passed.")
    if dep["available_seats"] < 1:
        fail(ERR_DEPARTURE_FULL, "No available seats.")
    is_early_bird = DB.clock_now() <= dep["_earlybird_dt"]
    price = calc.enrollment_price(dep["price_per_traveler_cents"], is_early_bird,
                                  add_ons, insurance_opted, insurance_tier)
    rec = base_fields()
    rec.update({
        "departure_id": departure_id,
        "traveler_name": traveler_name,
        "traveler_dob": store.iso_from_dt(traveler_dob),
        "traveler_gender": traveler_gender,
        "add_ons": list(add_ons),
        "insurance_opted": insurance_opted,
        "insurance_tier": insurance_tier,
        "price_locked_cents": price,
        "lifecycle_status": "PENDING",
        "payment_status": "UNPAID",
        "doc_complete": False,
        "cancel_reason": None,
    })
    DB.enrollments[rec["id"]] = rec
    recompute_departure_and_leader(dep)
    return ok(out(rec), 201)


@app.get("/enrollments/<eid>")
def fetch_enrollment(eid):
    require_roles("Operator", "GroupLeader", "Traveler")
    enr = get_enrollment(eid)
    tr_owns(enr)
    gl_owns(get_departure(enr["departure_id"]))
    return ok(out(enr))


@app.post("/enrollments/<eid>/confirm")
def confirm_enrollment(eid):
    require_roles("Operator", "GroupLeader")
    enr = get_enrollment(eid)
    dep = get_departure(enr["departure_id"])
    gl_owns(dep)
    if enr["lifecycle_status"] != "PENDING":
        fail(ERR_INVALID_STATE, "Enrollment is not PENDING.")
    if dep["status"] not in ("OPEN", "GUARANTEED"):
        fail(ERR_DEPARTURE_NOT_OPEN, "Parent departure is not OPEN or GUARANTEED.")
    plan = active_plan_of(eid)
    paid = plan["amount_paid_cents"] if plan else 0
    deposit = plan["deposit_cents"] if plan else calc.DEPOSIT_CENTS
    if paid < deposit:
        fail(ERR_INVALID_STATE, "Deposit has not been received.")
    enr["lifecycle_status"] = "CONFIRMED"
    touch(enr)
    return ok(out(enr))


@app.post("/enrollments/<eid>/cancel")
def cancel_enrollment(eid):
    require_roles("Operator", "GroupLeader", "Traveler")
    enr = get_enrollment(eid)
    dep = get_departure(enr["departure_id"])
    tr_owns(enr)
    gl_owns(dep)
    if enr["lifecycle_status"] not in ("PENDING", "CONFIRMED"):
        fail(ERR_INVALID_STATE, "Enrollment cannot be cancelled from its current state.")
    _cancel_enrollment_cascade(enr, dep, reason="TRAVELER_REQUEST", force_full_refund=False)
    recompute_departure_and_leader(dep)
    return ok(out(enr))


@app.post("/enrollments/<eid>/rebook")
def rebook_enrollment(eid):
    require_roles("Operator", "GroupLeader")
    enr = get_enrollment(eid)
    src_dep = get_departure(enr["departure_id"])
    gl_owns(src_dep)
    data = body()
    target_departure_id = as_str(req_field(data, "target_departure_id"), "target_departure_id")
    target = get_departure(target_departure_id)
    gl_owns(target)
    if enr["lifecycle_status"] != "CONFIRMED":
        fail(ERR_INVALID_STATE, "Only a CONFIRMED enrollment may be rebooked.")
    if target["status"] not in ("OPEN", "GUARANTEED") or target["available_seats"] < 1:
        fail(ERR_REBOOK_TARGET_INVALID, "Rebook target is not open with an available seat.")
    old_plan = active_plan_of(eid)
    carried = old_plan["amount_paid_cents"] if old_plan else 0
    # cancel source enrollment (no penalty; full transfer)
    enr["lifecycle_status"] = "CANCELLED"
    enr["cancel_reason"] = "REBOOK"
    if old_plan is not None:
        old_plan["status"] = "REFUND_DUE"
        touch(old_plan)
        if carried > 0:
            _append_payment(old_plan, carried, "REFUND", memo="rebook transfer")
        recompute_plan_amounts(old_plan)
        old_plan["status"] = "REFUNDED"
        touch(old_plan)
        enr["payment_status"] = "REFUNDED"
    touch(enr)
    # new enrollment on target
    is_early_bird = DB.clock_now() <= target["_earlybird_dt"]
    price = calc.enrollment_price(target["price_per_traveler_cents"], is_early_bird,
                                  enr["add_ons"], enr["insurance_opted"], enr.get("insurance_tier"))
    new_enr = base_fields()
    new_enr.update({
        "departure_id": target_departure_id,
        "traveler_name": enr["traveler_name"],
        "traveler_dob": enr["traveler_dob"],
        "traveler_gender": enr["traveler_gender"],
        "add_ons": list(enr["add_ons"]),
        "insurance_opted": enr["insurance_opted"],
        "insurance_tier": enr.get("insurance_tier"),
        "price_locked_cents": price,
        "lifecycle_status": "PENDING",
        "payment_status": "UNPAID",
        "doc_complete": False,
        "cancel_reason": None,
    })
    DB.enrollments[new_enr["id"]] = new_enr
    # new active plan, transfer funds via mirrored payment
    dep_c = old_plan["deposit_cents"] if old_plan else calc.DEPOSIT_CENTS
    inst_c = old_plan["installment_count"] if old_plan else 1
    new_plan = base_fields()
    financed = price - dep_c
    new_plan.update({
        "enrollment_id": new_enr["id"],
        "total_cents": price,
        "deposit_cents": dep_c,
        "installment_count": inst_c,
        "installment_amounts": calc.installment_split(financed, inst_c),
        "amount_paid_cents": 0,
        "amount_refunded_cents": 0,
        "status": "ACTIVE",
    })
    DB.payment_plans[new_plan["id"]] = new_plan
    if carried > 0:
        _append_payment(new_plan, carried, "DEPOSIT", memo="rebook transfer")
    recompute_plan_amounts(new_plan)
    _settle_payment_status(new_enr, new_plan)
    # recompute both departures / leaders
    recompute_departure_and_leader(src_dep)
    recompute_departure_and_leader(target)
    return ok(out(new_enr))


@app.get("/enrollments/<eid>/refund-quote")
def refund_quote(eid):
    require_roles("Operator", "GroupLeader", "Traveler")
    enr = get_enrollment(eid)
    dep = get_departure(enr["departure_id"])
    tr_owns(enr)
    gl_owns(dep)
    days = calc.days_before(dep["_depart_dt"], DB.clock_now())
    pct = calc.refund_pct_str(days, enr["insurance_opted"], enr.get("insurance_tier"))
    plan = active_plan_of(eid)
    amount_paid = plan["amount_paid_cents"] if plan else 0
    provisional = calc.refund_amount(enr["price_locked_cents"], pct)
    final = calc.refund_amount(amount_paid, pct)
    return ok({
        "provisional_refund_cents": provisional,
        "final_refund_cents": final,
        "refund_pct": float(pct),
        "days_before": days,
    })


@app.get("/enrollments/<eid>/payment-plan")
def list_enrollment_plans(eid):
    require_roles("Operator", "GroupLeader", "Traveler")
    enr = get_enrollment(eid)
    tr_owns(enr)
    gl_owns(get_departure(enr["departure_id"]))
    items = sorted_by_created([p for p in DB.payment_plans.values() if p["enrollment_id"] == eid])
    page, meta = paginate(items)
    return ok([out(p) for p in page], 200, meta)


@app.get("/enrollments/<eid>/permission-form")
def list_enrollment_forms(eid):
    require_roles("Operator", "GroupLeader", "Traveler")
    enr = get_enrollment(eid)
    tr_owns(enr)
    gl_owns(get_departure(enr["departure_id"]))
    items = sorted_by_created([f for f in DB.permission_forms.values() if f["enrollment_id"] == eid])
    page, meta = paginate(items)
    return ok([out(f) for f in page], 200, meta)


# =========================================================================
# Payment plans & payments
# =========================================================================
@app.post("/payment-plans")
def create_payment_plan():
    require_roles("Operator", "GroupLeader")
    data = body()
    enrollment_id = as_str(req_field(data, "enrollment_id"), "enrollment_id")
    enr = get_enrollment(enrollment_id)
    dep = get_departure(enr["departure_id"])
    gl_owns(dep)
    installment_count = as_int(req_field(data, "installment_count"), "installment_count", minimum=1)
    expected_version = as_int(req_field(data, "expected_enrollment_version"),
                              "expected_enrollment_version", minimum=0)
    deposit = data.get("deposit_cents")
    if deposit is None:
        deposit = calc.DEPOSIT_CENTS
    else:
        deposit = as_int(deposit, "deposit_cents", minimum=0)
    # OCC (evaluated last)
    if expected_version != enr["version"]:
        fail(ERR_STALE_VERSION, "expected_enrollment_version does not match current version.")
    total = enr["price_locked_cents"]
    prior = active_plan_of(enrollment_id)
    carried = 0
    if prior is not None:
        carried = prior["amount_paid_cents"]
        prior["status"] = "SUPERSEDED"
        touch(prior)
    financed = total - deposit
    plan = base_fields()
    plan.update({
        "enrollment_id": enrollment_id,
        "total_cents": total,
        "deposit_cents": deposit,
        "installment_count": installment_count,
        "installment_amounts": calc.installment_split(financed, installment_count),
        "amount_paid_cents": 0,
        "amount_refunded_cents": 0,
        "status": "ACTIVE",
    })
    DB.payment_plans[plan["id"]] = plan
    if carried > 0:
        _append_payment(plan, carried, "DEPOSIT", memo="carried forward from superseded plan")
    recompute_plan_amounts(plan)
    # creating a plan advances enrollment.version by 1
    touch(enr)
    _settle_payment_status(enr, plan)
    return ok(out(plan), 201)


@app.get("/payment-plans/<pid>")
def fetch_plan(pid):
    require_roles("Operator", "GroupLeader", "Traveler")
    plan = get_plan(pid)
    enr = DB.enrollments.get(plan["enrollment_id"])
    if enr is not None:
        tr_owns(enr)
        gl_owns(get_departure(enr["departure_id"]))
    return ok(out(plan))


@app.get("/payment-plans/<pid>/payments")
def list_plan_payments(pid):
    require_roles("Operator", "GroupLeader", "Traveler")
    plan = get_plan(pid)
    enr = DB.enrollments.get(plan["enrollment_id"])
    if enr is not None:
        tr_owns(enr)
        gl_owns(get_departure(enr["departure_id"]))
    items = sorted_by_created(payments_of(pid))
    page, meta = paginate(items)
    return ok([out(p) for p in page], 200, meta)


def _settle_payment_status(enr, plan):
    """Advance enrollment.payment_status and plan status from paid totals,
    running the paid-in-full cascade when full payment is reached."""
    paid = plan["amount_paid_cents"]
    total = plan["total_cents"]
    if enr["payment_status"] in ("REFUNDED",):
        return
    if paid >= total and total >= 0:
        if plan["status"] == "ACTIVE":
            plan["status"] = "PAID"
            touch(plan)
        if enr["payment_status"] != "PAID_IN_FULL":
            enr["payment_status"] = "PAID_IN_FULL"
            touch(enr)
            dep = DB.departures.get(enr["departure_id"])
            if dep is not None:
                recompute_departure_and_leader(dep)
    elif paid > 0:
        if enr["payment_status"] in ("UNPAID", "PARTIAL"):
            if enr["payment_status"] != "PARTIAL":
                enr["payment_status"] = "PARTIAL"
                touch(enr)


@app.post("/payments")
def create_payment():
    require_roles("Operator", "GroupLeader", "Traveler")
    data = body()
    plan_id = as_str(req_field(data, "payment_plan_id"), "payment_plan_id")
    plan = get_plan(plan_id)
    enr = DB.enrollments.get(plan["enrollment_id"])
    if enr is not None:
        tr_owns(enr)
        gl_owns(get_departure(enr["departure_id"]))
    amount = as_int(req_field(data, "amount_cents"), "amount_cents", minimum=1)
    kind = data.get("kind", "INSTALLMENT")
    if kind is None:
        kind = "INSTALLMENT"
    as_enum(kind, "kind", PAYMENT_KINDS)
    memo = data.get("memo")
    if memo is not None and not isinstance(memo, str):
        fail(ERR_VALIDATION, "memo must be a string.")
    if plan["status"] != "ACTIVE":
        fail(ERR_INVALID_STATE, "Payment plan is not ACTIVE.")
    if kind in ("DEPOSIT", "INSTALLMENT"):
        remaining = plan["total_cents"] - plan["amount_paid_cents"]
        if amount > remaining:
            fail(ERR_PAYMENT_EXCEEDS_BALANCE, "Payment exceeds remaining balance.")
    rec = _append_payment(plan, amount, kind, memo=memo)
    recompute_plan_amounts(plan)
    touch(plan)
    if enr is not None:
        _settle_payment_status(enr, plan)
    return ok(out(rec), 201)


# =========================================================================
# Permission forms
# =========================================================================
@app.post("/permission-forms")
def create_form():
    require_roles("Operator", "GroupLeader", "Traveler")
    data = body()
    enrollment_id = as_str(req_field(data, "enrollment_id"), "enrollment_id")
    enr = get_enrollment(enrollment_id)
    tr_owns(enr)
    gl_owns(get_departure(enr["departure_id"]))
    passport_number = as_str(req_field(data, "passport_number"), "passport_number")
    passport_expiry = parse_dt(req_field(data, "passport_expiry"), "passport_expiry")
    guardian_consent = as_bool(req_field(data, "guardian_consent"), "guardian_consent")
    medical_notes = data.get("medical_notes")
    if medical_notes is not None:
        as_str(medical_notes, "medical_notes")
    dietary = data.get("dietary")
    if dietary is not None:
        as_str(dietary, "dietary")
    rec = base_fields()
    rec.update({
        "enrollment_id": enrollment_id,
        "passport_number": passport_number,
        "passport_expiry": store.iso_from_dt(passport_expiry),
        "guardian_consent": guardian_consent,
        "medical_notes": medical_notes,
        "dietary": dietary,
        "status": "DRAFT",
    })
    DB.permission_forms[rec["id"]] = rec
    return ok(out(rec), 201)


@app.get("/permission-forms/<fid>")
def fetch_form(fid):
    require_roles("Operator", "GroupLeader", "Traveler")
    form = get_form(fid)
    enr = DB.enrollments.get(form["enrollment_id"])
    if enr is not None:
        tr_owns(enr)
        gl_owns(get_departure(enr["departure_id"]))
    return ok(out(form))


@app.post("/permission-forms/<fid>/submit")
def submit_form(fid):
    require_roles("Operator", "GroupLeader", "Traveler")
    form = get_form(fid)
    enr = DB.enrollments.get(form["enrollment_id"])
    if enr is not None:
        tr_owns(enr)
        gl_owns(get_departure(enr["departure_id"]))
    if form["status"] not in ("DRAFT", "CHANGES_REQUESTED"):
        fail(ERR_INVALID_STATE, "Form cannot be submitted from state %s." % form["status"])
    if form["guardian_consent"] is not True:
        fail(ERR_INVALID_STATE, "guardian_consent must be true to submit.")
    if not form["passport_number"] or not form["passport_expiry"]:
        fail(ERR_INVALID_STATE, "passport_number and passport_expiry must be present.")
    form["status"] = "SUBMITTED"
    touch(form)
    return ok(out(form))


@app.post("/permission-forms/<fid>/review")
def review_form(fid):
    require_roles("Operator")
    form = get_form(fid)
    data = body()
    decision = as_enum(req_field(data, "decision"), "decision", {"APPROVE", "REQUEST_CHANGES"})
    review_notes = data.get("review_notes")
    if review_notes is not None:
        as_str(review_notes, "review_notes")
    if form["status"] != "SUBMITTED":
        fail(ERR_INVALID_STATE, "Form is not SUBMITTED.")
    if decision == "APPROVE":
        form["status"] = "APPROVED"
        touch(form)
        enr = DB.enrollments.get(form["enrollment_id"])
        if enr is not None and not enr["doc_complete"]:
            enr["doc_complete"] = True
            touch(enr)
    else:
        form["status"] = "CHANGES_REQUESTED"
        touch(form)
    return ok(out(form))


# =========================================================================
# Chaperones
# =========================================================================
@app.post("/chaperones")
def create_chaperone():
    require_roles("Operator", "GroupLeader")
    data = body()
    departure_id = as_str(req_field(data, "departure_id"), "departure_id")
    dep = get_departure(departure_id)
    gl_owns(dep)
    full_name = as_str(req_field(data, "full_name"), "full_name")
    email = as_str(req_field(data, "email"), "email")
    role_type = data.get("role_type", "ADULT")
    if role_type is None:
        role_type = "ADULT"
    as_enum(role_type, "role_type", CHAPERONE_ROLE_TYPES)
    # cross-departure availability buffer (1 day)
    new_start = dep["_depart_dt"]
    new_end = dep["_return_dt"]
    for c in DB.chaperones.values():
        if c["email"] != email or c["status"] != "CONFIRMED":
            continue
        if c["departure_id"] == departure_id:
            continue
        other = DB.departures.get(c["departure_id"])
        if other is None:
            continue
        o_start = other["_depart_dt"]
        o_end = other["_return_dt"]
        if new_start <= o_end + ONE_DAY and o_start <= new_end + ONE_DAY:
            fail(ERR_CHAPERONE_UNAVAILABLE, "Chaperone unavailable within rest buffer.")
    rec = base_fields()
    rec.update({
        "departure_id": departure_id,
        "full_name": full_name,
        "email": email,
        "role_type": role_type,
        "status": "CONFIRMED",
    })
    DB.chaperones[rec["id"]] = rec
    return ok(out(rec), 201)


@app.get("/chaperones/<cid>")
def fetch_chaperone(cid):
    require_roles("Operator", "GroupLeader")
    c = get_chaperone(cid)
    gl_owns(get_departure(c["departure_id"]))
    return ok(out(c))


# =========================================================================
# Rooming assignments
# =========================================================================
@app.post("/rooming-assignments")
def create_rooming():
    require_roles("Operator", "GroupLeader")
    data = body()
    departure_id = as_str(req_field(data, "departure_id"), "departure_id")
    dep = get_departure(departure_id)
    gl_owns(dep)
    room_label = as_str(req_field(data, "room_label"), "room_label")
    room_type = as_enum(req_field(data, "room_type"), "room_type", set(ROOM_TYPES.keys()))
    room_gender = as_enum(req_field(data, "room_gender"), "room_gender", GENDERS)
    rec = base_fields()
    rec.update({
        "departure_id": departure_id,
        "room_label": room_label,
        "room_type": room_type,
        "room_gender": room_gender,
        "capacity": ROOM_TYPES[room_type],
        "member_enrollment_ids": [],
        "status": "DRAFT",
    })
    DB.rooming_assignments[rec["id"]] = rec
    return ok(out(rec), 201)


@app.get("/rooming-assignments/<rid>")
def fetch_rooming(rid):
    require_roles("Operator", "GroupLeader")
    r = get_rooming(rid)
    gl_owns(get_departure(r["departure_id"]))
    return ok(out(r))


@app.post("/rooming-assignments/<rid>/members")
def add_room_member(rid):
    require_roles("Operator", "GroupLeader")
    room = get_rooming(rid)
    gl_owns(get_departure(room["departure_id"]))
    data = body()
    enrollment_id = as_str(req_field(data, "enrollment_id"), "enrollment_id")
    enr = get_enrollment(enrollment_id)
    # gender (priority 7) before room-full (priority 11)
    if enr["traveler_gender"] != room["room_gender"]:
        fail(ERR_ROOMING_GENDER_MISMATCH, "Traveler gender does not match room gender.")
    if len(room["member_enrollment_ids"]) >= room["capacity"]:
        fail(ERR_ROOM_FULL, "Room is full.")
    room["member_enrollment_ids"].append(enrollment_id)
    touch(room)
    return ok(out(room))


@app.post("/rooming-assignments/<rid>/finalize")
def finalize_rooming(rid):
    require_roles("Operator", "GroupLeader")
    room = get_rooming(rid)
    gl_owns(get_departure(room["departure_id"]))
    if room["status"] != "DRAFT":
        fail(ERR_INVALID_STATE, "Room is not DRAFT.")
    members = room["member_enrollment_ids"]
    if len(members) < 1:
        fail(ERR_INVALID_STATE, "Room must have at least one member to finalize.")
    # docs (priority 6)
    for mid in members:
        enr = DB.enrollments.get(mid)
        if enr is None or not enr["doc_complete"]:
            fail(ERR_DOCS_INCOMPLETE, "A member lacks an approved permission form.")
    # gender (priority 7)
    for mid in members:
        enr = DB.enrollments.get(mid)
        if enr["traveler_gender"] != room["room_gender"]:
            fail(ERR_ROOMING_GENDER_MISMATCH, "A member's gender does not match the room.")
    # capacity (priority 11)
    if len(members) > room["capacity"]:
        fail(ERR_ROOM_FULL, "Room exceeds capacity.")
    room["status"] = "FINALIZED"
    touch(room)
    return ok(out(room))


# =========================================================================
# Suppliers & supplier bookings
# =========================================================================
@app.post("/suppliers")
def create_supplier():
    require_roles("Operator")
    data = body()
    name = as_str(req_field(data, "name"), "name")
    service_type = as_enum(req_field(data, "service_type"), "service_type", SERVICE_TYPES)
    city = as_str(req_field(data, "city"), "city")
    rec = base_fields()
    rec.update({"name": name, "service_type": service_type, "city": city})
    DB.suppliers[rec["id"]] = rec
    return ok(out(rec), 201)


@app.get("/suppliers/<sid>")
def fetch_supplier(sid):
    require_roles("Operator")
    return ok(out(get_supplier(sid)))


@app.get("/suppliers/<sid>/bookings")
def list_supplier_bookings(sid):
    require_roles("Operator")
    get_supplier(sid)
    items = sorted_by_created([b for b in DB.supplier_bookings.values() if b["supplier_id"] == sid])
    page, meta = paginate(items)
    return ok([_booking_public(b) for b in page], 200, meta)


def _booking_public(b):
    return {k: v for k, v in b.items() if not k.startswith("_")}


@app.post("/supplier-bookings")
def create_supplier_booking():
    require_roles("Operator")
    data = body()
    departure_id = as_str(req_field(data, "departure_id"), "departure_id")
    dep = get_departure(departure_id)
    supplier_id = as_str(req_field(data, "supplier_id"), "supplier_id")
    get_supplier(supplier_id)
    start = parse_dt(req_field(data, "service_window_start"), "service_window_start")
    end = parse_dt(req_field(data, "service_window_end"), "service_window_end")
    room_block = as_int(req_field(data, "room_block"), "room_block", minimum=1)
    cost = as_int(req_field(data, "cost_cents"), "cost_cents", minimum=0)
    # half-open overlap on same supplier vs non-cancelled bookings
    for b in DB.supplier_bookings.values():
        if b["supplier_id"] != supplier_id or b["status"] == "CANCELLED":
            continue
        if start < b["_end_dt"] and b["_start_dt"] < end:
            fail(ERR_SUPPLIER_DOUBLE_BOOKED, "Supplier window overlaps an existing booking.")
    rec = base_fields()
    rec.update({
        "departure_id": departure_id,
        "supplier_id": supplier_id,
        "service_window_start": store.iso_from_dt(start),
        "service_window_end": store.iso_from_dt(end),
        "room_block": room_block,
        "cost_cents": cost,
        "status": "HELD",
        "_start_dt": start,
        "_end_dt": end,
    })
    DB.supplier_bookings[rec["id"]] = rec
    return ok(_booking_public(rec), 201)


@app.get("/supplier-bookings/<bid>")
def fetch_supplier_booking(bid):
    require_roles("Operator")
    return ok(_booking_public(get_booking(bid)))


@app.post("/supplier-bookings/<bid>/confirm")
def confirm_supplier_booking(bid):
    require_roles("Operator")
    b = get_booking(bid)
    if b["status"] != "HELD":
        fail(ERR_INVALID_STATE, "Booking is not HELD.")
    dep = DB.departures.get(b["departure_id"])
    if dep is None or dep["status"] != "GUARANTEED":
        fail(ERR_INVALID_STATE, "Parent departure is not GUARANTEED.")
    b["status"] = "CONFIRMED"
    touch(b)
    return ok(_booking_public(b))


@app.post("/supplier-bookings/<bid>/cancel")
def cancel_supplier_booking(bid):
    require_roles("Operator")
    b = get_booking(bid)
    if b["status"] != "HELD":
        fail(ERR_INVALID_STATE, "Booking is not HELD.")
    b["status"] = "CANCELLED"
    touch(b)
    return ok(_booking_public(b))


# =========================================================================
# Departure-scoped list endpoints
# =========================================================================
@app.get("/departures/<did>/enrollments")
def list_departure_enrollments(did):
    require_roles("Operator", "GroupLeader")
    dep = get_departure(did)
    gl_owns(dep)
    items = sorted_by_created(enrollments_of(did))
    page, meta = paginate(items)
    return ok([out(e) for e in page], 200, meta)


@app.get("/departures/<did>/chaperones")
def list_departure_chaperones(did):
    require_roles("Operator", "GroupLeader")
    dep = get_departure(did)
    gl_owns(dep)
    items = sorted_by_created([c for c in DB.chaperones.values() if c["departure_id"] == did])
    page, meta = paginate(items)
    return ok([out(c) for c in page], 200, meta)


@app.get("/departures/<did>/rooming")
def list_departure_rooming(did):
    require_roles("Operator", "GroupLeader")
    dep = get_departure(did)
    gl_owns(dep)
    items = sorted_by_created([r for r in DB.rooming_assignments.values() if r["departure_id"] == did])
    page, meta = paginate(items)
    return ok([out(r) for r in page], 200, meta)


@app.get("/departures/<did>/supplier-bookings")
def list_departure_supplier_bookings(did):
    require_roles("Operator")
    get_departure(did)
    items = sorted_by_created([b for b in DB.supplier_bookings.values() if b["departure_id"] == did])
    page, meta = paginate(items)
    return ok([_booking_public(b) for b in page], 200, meta)


# =========================================================================
# Logical clock
# =========================================================================
@app.post("/_clock/set_current_utc")
def set_clock():
    require_roles("Operator")
    data = body()
    to_iso = parse_dt(req_field(data, "to_iso8601"), "to_iso8601")
    DB.clock = to_iso
    return ok({})


# clock accessor bound onto DB for convenience
def _clock_now():
    return DB.clock


DB.clock_now = _clock_now


# =========================================================================
# Health / readiness (unauthenticated)
# =========================================================================
@app.get("/health")
def health():
    return jsonify({"status": "ok"}), 200


@app.get("/")
def root():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
