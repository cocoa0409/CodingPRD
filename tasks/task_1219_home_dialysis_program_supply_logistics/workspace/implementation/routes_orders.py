"""Supply orders and delivery appointments."""
from datetime import timedelta

from flask import Blueprint, request

import db
import errors
import services as svc
from middleware import require_roles, ALL_ROLES, check_patient_ownership
from response import success_obj, success_list, paginate
from routes_programs import body, require_fields, get_or_404

bp = Blueprint("orders", __name__)
S = db.STORES


def _validate_lines(program, lines):
    """lines non-empty; every sku in catalog; every quantity >= 1."""
    if not isinstance(lines, list) or not lines:
        raise errors.err_invalid_request("lines must be a non-empty array")
    catalog = svc.catalog_map(program)
    for line in lines:
        if not isinstance(line, dict):
            raise errors.err_invalid_request("line must be an object")
        sku = line.get("sku")
        qty = line.get("quantity")
        if sku not in catalog:
            raise errors.err_invalid_request(f"unknown sku: {sku}")
        if not isinstance(qty, int) or isinstance(qty, bool) or qty < 1:
            raise errors.err_invalid_request("quantity must be >= 1")


def _recompute_money(order):
    program = get_or_404("dialysis_programs",
                         get_or_404("patients", order["patient_id"])["program_id"])
    (order["provisional_total_units"], order["subtotal_cents"],
     order["handling_fee_cents"], order["discount_cents"],
     order["grand_total_cents"]) = svc.compute_order_money(program, order["lines"])


# ---------------------------------------------------------------------------
# supply orders
# ---------------------------------------------------------------------------

@bp.route("/api/supply-orders", methods=["POST"])
@require_roles("Patient")
def create_order(_user_id, _role):
    p = require_fields(body(), ["patient_id", "order_month", "lines",
                                "expected_patient_version"])
    check_patient_ownership(_user_id, _role, p["patient_id"])
    patient = get_or_404("patients", p["patient_id"])
    if not svc.valid_month(p["order_month"]):
        raise errors.err_invalid_request("order_month must be YYYY-MM")
    program = get_or_404("dialysis_programs", patient["program_id"])
    _validate_lines(program, p["lines"])
    # OCC on patient version (state stage)
    if p["expected_patient_version"] != patient["version"]:
        raise errors.err_stale_version()
    # month not in the past (temporal)
    current_ym = db.now().strftime("%Y-%m")
    if p["order_month"] < current_ym:
        raise errors.ApiError("ERR_ORDER_MONTH_IN_PAST", 422,
                              "order_month before the current clock month")
    # uniqueness: SUBMITTED|APPROVED|CLOSED for same patient+month rejects
    for o in S["supply_orders"].values():
        if (o["patient_id"] == patient["id"] and o["order_month"] == p["order_month"]
                and o["order_status"] in ("SUBMITTED", "APPROVED", "CLOSED")):
            raise errors.ApiError("ERR_MONTH_ORDER_EXISTS", 409,
                                  "An order for this patient+month is already locked")
    # create-with-supersede: existing DRAFT becomes SUPERSEDED
    for o in S["supply_orders"].values():
        if (o["patient_id"] == patient["id"] and o["order_month"] == p["order_month"]
                and o["order_status"] == "DRAFT"):
            o["order_status"] = "SUPERSEDED"
            db.touch(o)
    rec = {
        "patient_id": patient["id"],
        "order_month": p["order_month"],
        "lines": [{"sku": l["sku"], "quantity": l["quantity"]} for l in p["lines"]],
        "standard_allowance_units": None,
        "carried_adjustment_units": None,
        "actualized_units": None,
        "adjustment_units": None,
        "delivered_units_total": 0,
        "review_note": None,
        "order_status": "DRAFT",
        "fulfillment_status": "UNFULFILLED",
    }
    db.stamp_new(rec)
    _recompute_money(rec)
    S["supply_orders"][rec["id"]] = rec
    db.touch(patient)  # order creation increments Patient.version
    return success_obj(rec, 201)


@bp.route("/api/supply-orders/<oid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_order(oid, _user_id, _role):
    return success_obj(get_or_404("supply_orders", oid))


@bp.route("/api/patients/<pid>/supply-orders", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_patient_orders(pid, _user_id, _role):
    get_or_404("patients", pid)
    rows = [o for o in S["supply_orders"].values() if o["patient_id"] == pid]
    month = request.args.get("order_month")
    status = request.args.get("order_status")
    if month:
        rows = [r for r in rows if r["order_month"] == month]
    if status:
        rows = [r for r in rows if r["order_status"] == status]
    rows.sort(key=lambda r: (r["created_at"], r.get("_seq", 0)))
    items, limit, offset, total = paginate(rows, request.args)
    return success_list(items, limit, offset, total)


@bp.route("/api/supply-orders/<oid>", methods=["PATCH"])
@require_roles("Patient")
def patch_order(oid, _user_id, _role):
    order = get_or_404("supply_orders", oid)
    check_patient_ownership(_user_id, _role, order["patient_id"])
    if order["order_status"] not in ("DRAFT", "CHANGES_REQUESTED"):
        raise errors.ApiError("ERR_ORDER_INVALID_STATE", 409,
                              "Order is not DRAFT or CHANGES_REQUESTED")
    p = require_fields(body(), ["lines"])
    program = get_or_404("dialysis_programs",
                         get_or_404("patients", order["patient_id"])["program_id"])
    _validate_lines(program, p["lines"])
    order["lines"] = [{"sku": l["sku"], "quantity": l["quantity"]} for l in p["lines"]]
    _recompute_money(order)
    if order["order_status"] == "CHANGES_REQUESTED":
        order["order_status"] = "DRAFT"
    db.touch(order)
    return success_obj(order)


@bp.route("/api/supply-orders/<oid>/submit", methods=["POST"])
@require_roles("Patient")
def submit_order(oid, _user_id, _role):
    order = get_or_404("supply_orders", oid)
    check_patient_ownership(_user_id, _role, order["patient_id"])
    # gate ladder: state > month > posture > lines > uniqueness > storage > allowance
    if order["order_status"] not in ("DRAFT", "CHANGES_REQUESTED"):
        raise errors.ApiError("ERR_ORDER_INVALID_STATE", 409,
                              "Order is not DRAFT or CHANGES_REQUESTED")
    current_ym = db.now().strftime("%Y-%m")
    if order["order_month"] < current_ym:
        raise errors.ApiError("ERR_ORDER_MONTH_IN_PAST", 422,
                              "order_month before the current clock month")
    patient = get_or_404("patients", order["patient_id"])
    svc.patient_view(patient)
    if patient["posture"] not in ("HOME_READY", "AT_RISK"):
        raise errors.ApiError("ERR_POSTURE_NOT_ORDERABLE", 403,
                              "Posture is not orderable")
    program = get_or_404("dialysis_programs", patient["program_id"])
    _validate_lines(program, order["lines"])
    for o in S["supply_orders"].values():
        if (o["patient_id"] == patient["id"] and o["order_month"] == order["order_month"]
                and o["id"] != order["id"]
                and o["order_status"] in ("SUBMITTED", "APPROVED", "CLOSED")):
            raise errors.ApiError("ERR_MONTH_ORDER_EXISTS", 409,
                                  "Another order for this patient+month is locked")
    # evaluate and store STANDARD allowance + carried adjustment at submit
    standard = (patient["prescription_treatments_per_week"] * svc.WEEKS_PER_MONTH
                * patient["prescription_units_per_treatment"])
    carried = svc.compute_carried_adjustment(patient["id"], order["order_month"])
    order["standard_allowance_units"] = standard
    order["carried_adjustment_units"] = carried
    # storage bound first, then allowance
    if patient["on_hand_units"] + order["provisional_total_units"] > patient["storage_cap_units"]:
        raise errors.ApiError("ERR_STORAGE_CAPACITY_EXCEEDED", 422,
                              "on_hand + provisional exceeds storage capacity")
    if order["provisional_total_units"] > standard + carried:
        raise errors.ApiError("ERR_ALLOWANCE_EXCEEDED", 422,
                              "provisional exceeds allowance + carry")
    order["order_status"] = "SUBMITTED"
    db.touch(order)
    return success_obj(order)


@bp.route("/api/supply-orders/<oid>/review", methods=["POST"])
@require_roles("SupplyCoordinator")
def review_order(oid, _user_id, _role):
    order = get_or_404("supply_orders", oid)
    if order["order_status"] != "SUBMITTED":
        raise errors.ApiError("ERR_ORDER_INVALID_STATE", 409,
                              "Order is not SUBMITTED")
    p = require_fields(body(), ["decision"])
    if p["decision"] not in ("APPROVE", "REQUEST_CHANGES"):
        raise errors.err_invalid_request("decision must be APPROVE or REQUEST_CHANGES")
    order["order_status"] = ("APPROVED" if p["decision"] == "APPROVE"
                             else "CHANGES_REQUESTED")
    if p.get("note") is not None:
        order["review_note"] = p["note"]
    db.touch(order)
    return success_obj(order)


@bp.route("/api/supply-orders/<oid>/cancel", methods=["POST"])
@require_roles("Patient", "SupplyCoordinator")
def cancel_order(oid, _user_id, _role):
    order = get_or_404("supply_orders", oid)
    check_patient_ownership(_user_id, _role, order["patient_id"])
    if order["order_status"] not in ("DRAFT", "SUBMITTED", "CHANGES_REQUESTED", "APPROVED"):
        raise errors.ApiError("ERR_ORDER_INVALID_STATE", 409,
                              "Order state does not allow cancel")
    # SCHEDULED appointments cancelled (DRAFT/SUBMITTED/APPROVED; harmless otherwise)
    for a in S["delivery_appointments"].values():
        if a["supply_order_id"] == oid and a["status"] == "SCHEDULED":
            a["status"] = "CANCELLED"
            db.touch(a)
    order["order_status"] = "CANCELLED"
    db.touch(order)
    return success_obj(order)


@bp.route("/api/supply-orders/<oid>/close", methods=["POST"])
@require_roles("SupplyCoordinator")
def close_order(oid, _user_id, _role):
    order = get_or_404("supply_orders", oid)
    if order["order_status"] != "APPROVED":
        raise errors.ApiError("ERR_ORDER_INVALID_STATE", 409,
                              "Order is not APPROVED")
    _, next_first = svc.month_bounds(order["order_month"])
    if db.now().date() < next_first:
        raise errors.ApiError("ERR_MONTH_NOT_ENDED", 422,
                              "order_month has not fully elapsed")
    for a in S["delivery_appointments"].values():
        if a["supply_order_id"] == oid and a["status"] == "SCHEDULED":
            raise errors.ApiError("ERR_OPEN_APPOINTMENTS_EXIST", 409,
                                  "A SCHEDULED appointment exists for this order")
    actualized = svc.compute_actualized_units(order["patient_id"], order["order_month"])
    order["actualized_units"] = actualized
    order["adjustment_units"] = actualized - (order["standard_allowance_units"] or 0)
    order["order_status"] = "CLOSED"
    db.touch(order)
    return success_obj(order)


# ---------------------------------------------------------------------------
# delivery appointments
# ---------------------------------------------------------------------------

@bp.route("/api/delivery-appointments", methods=["POST"])
@require_roles("SupplyCoordinator")
def create_appointment(_user_id, _role):
    p = require_fields(body(), ["supply_order_id", "window_start", "window_end"])
    order = get_or_404("supply_orders", p["supply_order_id"])
    ws, we = svc.parse_dt(p["window_start"]), svc.parse_dt(p["window_end"])
    if ws is None or we is None:
        raise errors.err_invalid_request("invalid window datetimes")
    duration = (we - ws).total_seconds() / 60
    if not (we > ws) or not (120 <= duration <= 720):
        raise errors.err_invalid_request("window duration must be 120..720 minutes")
    if order["order_status"] != "APPROVED":
        raise errors.ApiError("ERR_ORDER_INVALID_STATE", 409,
                              "Order is not APPROVED")
    for a in S["delivery_appointments"].values():
        if a["supply_order_id"] == order["id"] and a["status"] == "SCHEDULED":
            raise errors.ApiError("ERR_ACTIVE_APPOINTMENT_EXISTS", 409,
                                  "Another SCHEDULED appointment exists for this order")
    if ws < db.now():
        raise errors.ApiError("ERR_SLOT_IN_PAST", 422,
                              "window_start must not be in the past")
    first, next_first = svc.month_bounds(order["order_month"])
    if not (first <= ws.date() < next_first):
        raise errors.ApiError("ERR_APPOINTMENT_OUTSIDE_ORDER_MONTH", 422,
                              "window_start date outside the order month")
    rec = {
        "supply_order_id": order["id"],
        "window_start": db.iso(ws),
        "window_end": db.iso(we),
        "delivered_units": None,
        "failure_reason": None,
        "status": "SCHEDULED",
    }
    db.stamp_new(rec)
    S["delivery_appointments"][rec["id"]] = rec
    return success_obj(rec, 201)


@bp.route("/api/supply-orders/<oid>/delivery-appointments", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_order_appointments(oid, _user_id, _role):
    get_or_404("supply_orders", oid)
    rows = [a for a in S["delivery_appointments"].values()
            if a["supply_order_id"] == oid]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: (r["created_at"], r.get("_seq", 0)))
    items, limit, offset, total = paginate(rows, request.args)
    return success_list(items, limit, offset, total)


@bp.route("/api/delivery-appointments/<aid>/complete", methods=["POST"])
@require_roles("SupplyCoordinator")
def complete_appointment(aid, _user_id, _role):
    appt = get_or_404("delivery_appointments", aid)
    if appt["status"] != "SCHEDULED":
        raise errors.ApiError("ERR_APPOINTMENT_INVALID_STATE", 409,
                              "Appointment is not SCHEDULED")
    p = require_fields(body(), ["delivered_units"])
    units = p["delivered_units"]
    order = get_or_404("supply_orders", appt["supply_order_id"])
    remaining = order["provisional_total_units"] - order["delivered_units_total"]
    if not isinstance(units, int) or isinstance(units, bool) or units < 1 or units > remaining:
        raise errors.ApiError("ERR_DELIVERED_UNITS_INVALID", 422,
                              "delivered_units out of range")
    appt["delivered_units"] = units
    appt["status"] = "DELIVERED"
    db.touch(appt)
    order["delivered_units_total"] += units
    if order["delivered_units_total"] >= order["provisional_total_units"]:
        order["fulfillment_status"] = "DELIVERED"
    else:
        order["fulfillment_status"] = "PARTIALLY_DELIVERED"
    db.touch(order)
    svc.patient_view(get_or_404("patients", order["patient_id"]))
    return success_obj(appt)


@bp.route("/api/delivery-appointments/<aid>/fail", methods=["POST"])
@require_roles("SupplyCoordinator")
def fail_appointment(aid, _user_id, _role):
    appt = get_or_404("delivery_appointments", aid)
    if appt["status"] != "SCHEDULED":
        raise errors.ApiError("ERR_APPOINTMENT_INVALID_STATE", 409,
                              "Appointment is not SCHEDULED")
    p = require_fields(body(), ["failure_reason"])
    if not isinstance(p["failure_reason"], str) or not p["failure_reason"].strip():
        raise errors.err_invalid_request("failure_reason must be non-empty")
    appt["failure_reason"] = p["failure_reason"]
    appt["status"] = "FAILED"
    db.touch(appt)
    return success_obj(appt)


@bp.route("/api/delivery-appointments/<aid>/cancel", methods=["POST"])
@require_roles("SupplyCoordinator")
def cancel_appointment(aid, _user_id, _role):
    appt = get_or_404("delivery_appointments", aid)
    if appt["status"] != "SCHEDULED":
        raise errors.ApiError("ERR_APPOINTMENT_INVALID_STATE", 409,
                              "Appointment is not SCHEDULED")
    appt["status"] = "CANCELLED"
    db.touch(appt)
    return success_obj(appt)
