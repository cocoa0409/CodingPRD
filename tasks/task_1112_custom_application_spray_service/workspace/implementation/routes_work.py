"""Work order routes: intake, scheduling gauntlet, reschedule (OCC), start/resume/
complete/cancel/close. Gate evaluation follows PRD §2.9 precedence and the §3.4/§3.5
narrative orders."""

from datetime import timedelta
from decimal import Decimal
from flask import Blueprint, request

from store import store
from util import (require_roles, get_body, req_str, req_int, req_pos_num, req_dt,
                  opt_bool, ok, paginate, now, dec, round_1dp, ceil_int,
                  validation_error, not_found, forbidden, invalid_state, conflict,
                  ApiError)
from domain import (new_mutable, serialize, touch, validate_actual_lines,
                    tank_mix_verdicts, provisional_amount_cents,
                    latest_observation, observation_fresh, envelope_passes,
                    field_time_conflict, applicator_time_conflict,
                    find_application_record, find_invoice, RINSE_FRACTION)

bp = Blueprint("work_orders", __name__, url_prefix="/api")


def _mix_categories(rx):
    return {store.products[l["product_id"]]["category"] for l in rx["lines"]}


def _check_buffer_gate(rx, field):
    for l in rx["lines"]:
        p = store.products[l["product_id"]]
        if p["required_buffer_ft"] > field["buffer_clearance_ft"]:
            raise conflict("ERR_BUFFER_VIOLATION",
                           "product %s required_buffer_ft exceeds the field's clearance" % p["id"])


def _check_tank_mix_gate(rx, uses_adjuvant):
    has_incompatible, has_conditional = tank_mix_verdicts(
        [l["product_id"] for l in rx["lines"]])
    if has_incompatible:
        raise conflict("ERR_INCOMPATIBLE_TANK_MIX",
                       "a line pair carries verdict INCOMPATIBLE")
    if has_conditional and not uses_adjuvant:
        raise conflict("ERR_ADJUVANT_REQUIRED",
                       "a CONDITIONAL pair requires uses_adjuvant=true")


def _check_applicator_license(applicator, scheduled_end, rx):
    if applicator["status"] != "ACTIVE":
        raise conflict("ERR_APPLICATOR_NOT_ACTIVE", "assigned applicator is not ACTIVE")
    if applicator["license_expires_on"] < scheduled_end:
        raise conflict("ERR_LICENSE_EXPIRED",
                       "license expires before scheduled_end")
    needed = _mix_categories(rx)
    if not needed.issubset(set(applicator["license_categories"])):
        raise conflict("ERR_LICENSE_CATEGORY_MISSING",
                       "applicator license does not cover every product category in the tank mix")


def _check_calibration_gate(equipment, scheduled_end):
    if (equipment["status"] != "AVAILABLE"
            or equipment["calibration_valid_until"] is None
            or equipment["calibration_valid_until"] < scheduled_end):
        raise conflict("ERR_CALIBRATION_OVERDUE",
                       "equipment is not AVAILABLE with calibration valid through scheduled_end")


def _check_window_gate(rx, ss, se):
    if ss < rx["valid_from"] or se > rx["valid_to"]:
        raise conflict("ERR_OUTSIDE_APPLICATION_WINDOW",
                       "scheduled window must sit inside the prescription validity window")


# ---------------------------------------------------------------------------
# Intake
# ---------------------------------------------------------------------------

@bp.post("/work-orders")
def create_work_order():
    uid, role = require_roles("Grower", "Dispatcher")
    body = get_body()
    customer_id = req_str(body, "customer_id")
    field_id = req_str(body, "field_id")
    prescription_id = req_str(body, "prescription_id")
    acres = req_pos_num(body, "acres_to_treat")
    if role == "Grower" and customer_id != uid:
        raise forbidden("a Grower may create work orders only for their own customer_id")
    if customer_id not in store.customers:
        raise not_found("customer not found")
    field = store.fields.get(field_id)
    if field is None:
        raise not_found("field not found")
    if prescription_id not in store.prescriptions:
        raise not_found("prescription not found")
    if dec(acres) > dec(field["acres"]):
        raise conflict("ERR_ACREAGE_EXCEEDED",
                       "acres_to_treat exceeds the field's total acres")
    w = new_mutable({
        "customer_id": customer_id,
        "field_id": field_id,
        "prescription_id": prescription_id,
        "acres_to_treat": acres,
        "applicator_id": None,
        "equipment_id": None,
        "scheduled_start": None,
        "scheduled_end": None,
        "uses_adjuvant": False,
        "status": "DRAFT",
        "started_at": None,
        "completed_at": None,
        "estimated_total_cents": None,
        "rinsate_generated_gal": Decimal("0"),
        "rinsate_balance_gal": Decimal("0"),
    })
    store.work_orders[w["id"]] = w
    return ok(serialize("work_order", w), 201)


@bp.get("/work-orders/<wo_id>")
def get_work_order(wo_id):
    require_roles("Grower", "Dispatcher", "Applicator", "ComplianceOfficer", "CoopAdmin")
    w = store.work_orders.get(wo_id)
    if w is None:
        raise not_found("work order not found")
    return ok(serialize("work_order", w))


@bp.get("/work-orders")
def list_work_orders():
    require_roles("Grower", "Dispatcher", "Applicator", "ComplianceOfficer", "CoopAdmin")
    items = sorted(store.work_orders.values(), key=lambda w: (w["created_at"], w["_seq"]))
    for param in ("customer_id", "field_id", "prescription_id",
                  "applicator_id", "equipment_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [w for w in items if w[param] == v]
    return paginate([serialize("work_order", w) for w in items])


# ---------------------------------------------------------------------------
# Scheduling gauntlet
# ---------------------------------------------------------------------------

@bp.post("/work-orders/<wo_id>/schedule")
def schedule_work_order(wo_id):
    require_roles("Dispatcher")
    body = get_body()
    applicator_id = req_str(body, "applicator_id")
    equipment_id = req_str(body, "equipment_id")
    ss = req_dt(body, "scheduled_start")
    se = req_dt(body, "scheduled_end")
    uses_adjuvant = opt_bool(body, "uses_adjuvant", False)
    if not ss < se:
        raise validation_error("scheduled_start must be strictly before scheduled_end")
    w = store.work_orders.get(wo_id)
    if w is None:
        raise not_found("work order not found")
    applicator = store.applicators.get(applicator_id)
    if applicator is None:
        raise not_found("applicator not found")
    equipment = store.equipment.get(equipment_id)
    if equipment is None:
        raise not_found("equipment not found")
    # state gates
    if w["status"] != "DRAFT":
        raise invalid_state("only a DRAFT work order can be scheduled")
    rx = store.prescriptions[w["prescription_id"]]
    if rx["status"] != "APPROVED":
        raise conflict("ERR_PRESCRIPTION_NOT_APPROVED",
                       "the referenced prescription is not APPROVED")
    if applicator["status"] != "ACTIVE":
        raise conflict("ERR_APPLICATOR_NOT_ACTIVE", "assigned applicator is not ACTIVE")
    # regulatory safety gates
    _check_applicator_license(applicator, se, rx)
    field = store.fields[w["field_id"]]
    _check_buffer_gate(rx, field)
    _check_tank_mix_gate(rx, uses_adjuvant)
    # temporal gates
    _check_window_gate(rx, ss, se)
    if field_time_conflict(w["field_id"], ss, se):
        raise conflict("ERR_FIELD_TIME_CONFLICT",
                       "another scheduled/in-progress work order overlaps this field window")
    if applicator_time_conflict(applicator_id, ss, se):
        raise conflict("ERR_APPLICATOR_TIME_CONFLICT",
                       "another scheduled/in-progress work order overlaps within the travel buffer")
    _check_calibration_gate(equipment, se)
    # fiscal gate
    customer = store.customers[w["customer_id"]]
    estimated = provisional_amount_cents(w, customer, rx)
    if customer["outstanding_cents"] + estimated > customer["credit_limit_cents"]:
        raise conflict("ERR_CREDIT_LIMIT_EXCEEDED",
                       "outstanding balance plus estimated total exceeds the credit limit")
    # apply
    w["applicator_id"] = applicator_id
    w["equipment_id"] = equipment_id
    w["scheduled_start"] = ss
    w["scheduled_end"] = se
    w["uses_adjuvant"] = uses_adjuvant
    w["estimated_total_cents"] = estimated
    w["status"] = "SCHEDULED"
    touch(w)
    return ok(serialize("work_order", w))


@bp.post("/work-orders/<wo_id>/reschedule")
def reschedule_work_order(wo_id):
    require_roles("Dispatcher")
    body = get_body()
    ss = req_dt(body, "scheduled_start")
    se = req_dt(body, "scheduled_end")
    expected = req_int(body, "expected_work_order_version")
    has_app = "applicator_id" in body and body["applicator_id"] is not None
    has_eq = "equipment_id" in body and body["equipment_id"] is not None
    if has_app and not isinstance(body["applicator_id"], str):
        raise validation_error("applicator_id must be a string")
    if has_eq and not isinstance(body["equipment_id"], str):
        raise validation_error("equipment_id must be a string")
    uses_adjuvant = opt_bool(body, "uses_adjuvant", None)
    if not ss < se:
        raise validation_error("scheduled_start must be strictly before scheduled_end")
    w = store.work_orders.get(wo_id)
    if w is None:
        raise not_found("work order not found")
    new_app = None
    if has_app:
        new_app = store.applicators.get(body["applicator_id"])
        if new_app is None:
            raise not_found("applicator not found")
    new_eq = None
    if has_eq:
        new_eq = store.equipment.get(body["equipment_id"])
        if new_eq is None:
            raise not_found("equipment not found")
    if w["status"] != "SCHEDULED":
        raise invalid_state("only a SCHEDULED work order can be rescheduled")
    # OCC: reschedule is legitimate repeatedly, so staleness is the only basis
    if expected != w["version"]:
        raise ApiError("ERR_STALE_VERSION",
                       "expected_work_order_version does not match the work order's current version",
                       412)
    rx = store.prescriptions[w["prescription_id"]]
    eff_app_id = new_app["id"] if new_app is not None else w["applicator_id"]
    # window and overlap gates re-run for the new window
    _check_window_gate(rx, ss, se)
    if field_time_conflict(w["field_id"], ss, se, exclude_id=w["id"]):
        raise conflict("ERR_FIELD_TIME_CONFLICT",
                       "another scheduled/in-progress work order overlaps this field window")
    if applicator_time_conflict(eff_app_id, ss, se, exclude_id=w["id"]):
        raise conflict("ERR_APPLICATOR_TIME_CONFLICT",
                       "another scheduled/in-progress work order overlaps within the travel buffer")
    # reassignment gates re-run only for replaced resources
    if new_app is not None:
        _check_applicator_license(new_app, se, rx)
    if new_eq is not None:
        _check_calibration_gate(new_eq, se)
    # apply
    w["scheduled_start"] = ss
    w["scheduled_end"] = se
    if new_app is not None:
        w["applicator_id"] = new_app["id"]
    if new_eq is not None:
        w["equipment_id"] = new_eq["id"]
    if uses_adjuvant is not None:
        w["uses_adjuvant"] = uses_adjuvant
    touch(w)
    return ok(serialize("work_order", w))


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

@bp.post("/work-orders/<wo_id>/start")
def start_work_order(wo_id):
    uid, _role = require_roles("Applicator")
    w = store.work_orders.get(wo_id)
    if w is None:
        raise not_found("work order not found")
    if w["applicator_id"] != uid:
        raise forbidden("only the assigned applicator may start this work order")
    if w["status"] != "SCHEDULED":
        raise invalid_state("only a SCHEDULED work order can be started")
    t = now()
    if t > w["scheduled_end"]:
        raise conflict("ERR_OUTSIDE_APPLICATION_WINDOW",
                       "the current time is past scheduled_end")
    field = store.fields[w["field_id"]]
    if field["rei_until"] is not None and t < field["rei_until"]:
        raise conflict("ERR_REI_ACTIVE", "the field's re-entry interval is still in effect")
    obs = latest_observation()
    if obs is None or not observation_fresh(obs, t):
        raise conflict("ERR_OBSERVATION_STALE",
                       "the latest weather observation is older than 60 minutes")
    rx = store.prescriptions[w["prescription_id"]]
    if not envelope_passes(rx, obs):
        raise conflict("ERR_WEATHER_WINDOW_VIOLATION",
                       "the latest observation is outside the mix weather envelope")
    applicator = store.applicators.get(w["applicator_id"])
    if applicator is None or applicator["status"] != "ACTIVE":
        raise conflict("ERR_APPLICATOR_NOT_ACTIVE", "assigned applicator is not ACTIVE")
    if applicator["license_expires_on"] < t:
        raise conflict("ERR_LICENSE_EXPIRED", "the applicator's license has expired")
    w["started_at"] = t
    w["status"] = "IN_PROGRESS"
    touch(w)
    return ok(serialize("work_order", w))


@bp.post("/work-orders/<wo_id>/resume")
def resume_work_order(wo_id):
    uid, _role = require_roles("Applicator")
    w = store.work_orders.get(wo_id)
    if w is None:
        raise not_found("work order not found")
    if w["applicator_id"] != uid:
        raise forbidden("only the assigned applicator may resume this work order")
    if w["status"] != "WEATHER_HOLD":
        raise invalid_state("only a WEATHER_HOLD work order can be resumed")
    obs = latest_observation()
    if obs is None or not observation_fresh(obs):
        raise conflict("ERR_OBSERVATION_STALE",
                       "the latest weather observation is older than 60 minutes")
    rx = store.prescriptions[w["prescription_id"]]
    if not envelope_passes(rx, obs):
        raise conflict("ERR_WEATHER_WINDOW_VIOLATION",
                       "the latest observation is outside the mix weather envelope")
    w["status"] = "IN_PROGRESS"
    touch(w)
    return ok(serialize("work_order", w))


@bp.post("/work-orders/<wo_id>/complete")
def complete_work_order(wo_id):
    uid, _role = require_roles("Applicator")
    w = store.work_orders.get(wo_id)
    if w is None:
        raise not_found("work order not found")
    if w["applicator_id"] != uid:
        raise forbidden("only the assigned applicator may complete this work order")
    rx = store.prescriptions[w["prescription_id"]]
    lines = validate_actual_lines(get_body().get("lines"), rx)
    if w["status"] != "IN_PROGRESS":
        raise invalid_state("only an IN_PROGRESS work order can be completed")
    t = now()
    w["completed_at"] = t
    w["status"] = "COMPLETED"
    # exactly one ApplicationRecord per work order, born SUBMITTED
    rec = new_mutable({
        "work_order_id": w["id"],
        "applicator_id": w["applicator_id"],
        "lines": lines,
        "started_at": w["started_at"],
        "completed_at": t,
        "status": "SUBMITTED",
        "returned_note": None,
        "certified_by_user_id": None,
    })
    store.application_records[rec["id"]] = rec
    # field REI lockout: advances to the later value, never earlier
    field = store.fields[w["field_id"]]
    max_rei = max(store.products[l["product_id"]]["rei_hours"] for l in rx["lines"])
    new_rei = t + timedelta(hours=max_rei)
    if field["rei_until"] is None or new_rei > field["rei_until"]:
        field["rei_until"] = new_rei
    touch(field)
    # rinsate generation: ceil loads * tank capacity * 2% per load, 1 decimal
    equipment = store.equipment[w["equipment_id"]]
    total_mix = dec(w["acres_to_treat"]) * dec(rx["carrier_gpa"])
    loads = ceil_int(total_mix / dec(equipment["tank_capacity_gal"]))
    generated = round_1dp(dec(loads) * dec(equipment["tank_capacity_gal"]) * RINSE_FRACTION)
    w["rinsate_generated_gal"] = generated
    w["rinsate_balance_gal"] = generated
    # DRAFT invoice with the provisional amount (prescribed rates)
    customer = store.customers[w["customer_id"]]
    inv = new_mutable({
        "work_order_id": w["id"],
        "provisional_amount_cents": provisional_amount_cents(w, customer, rx),
        "final_amount_cents": None,
        "status": "DRAFT",
    })
    store.invoices[inv["id"]] = inv
    touch(w)
    return ok(serialize("work_order", w))


@bp.post("/work-orders/<wo_id>/cancel")
def cancel_work_order(wo_id):
    uid, role = require_roles("Grower", "Dispatcher")
    w = store.work_orders.get(wo_id)
    if w is None:
        raise not_found("work order not found")
    if role == "Grower" and w["customer_id"] != uid:
        raise forbidden("a Grower may cancel only their own work orders")
    if w["status"] not in ("DRAFT", "SCHEDULED"):
        raise invalid_state("only a DRAFT or SCHEDULED work order can be cancelled")
    w["status"] = "CANCELLED"
    touch(w)
    return ok(serialize("work_order", w))


@bp.post("/work-orders/<wo_id>/close")
def close_work_order(wo_id):
    require_roles("Dispatcher")
    w = store.work_orders.get(wo_id)
    if w is None:
        raise not_found("work order not found")
    if w["status"] != "COMPLETED":
        raise invalid_state("only a COMPLETED work order can be closed")
    rec = find_application_record(w["id"])
    if rec is None or rec["status"] != "CERTIFIED":
        raise conflict("ERR_RECORD_NOT_CERTIFIED",
                       "the application record is not CERTIFIED")
    if w["rinsate_balance_gal"] != 0:
        raise conflict("ERR_RINSATE_BALANCE_OPEN",
                       "rinsate_balance_gal has not been disposed down to zero")
    inv = find_invoice(w["id"])
    if inv is None or inv["status"] not in ("PAID", "VOIDED"):
        raise conflict("ERR_INVOICE_UNSETTLED",
                       "the invoice is neither PAID nor VOIDED")
    w["status"] = "CLOSED"
    touch(w)
    return ok(serialize("work_order", w))
