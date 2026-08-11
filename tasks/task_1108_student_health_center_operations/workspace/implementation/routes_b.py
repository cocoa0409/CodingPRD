"""Routes part B: encounters (close), prescriptions, medication stocks, lab
orders, disease cases, outbreak investigations, invoices, payments, referrals,
health-fee pools."""
from datetime import timedelta

from flask import Blueprint, request

from store import db, clock, new_entity, bump, by_seq
from helpers import (
    ApiError, require_auth, get_body, envelope_ok, list_response,
    req_present, req_string, req_int, req_enum, opt_enum, err_invalid_request,
    err_not_found, parse_date,
)
from serializers import (
    ser_encounter, ser_prescription, ser_stock, ser_lab_order, ser_case,
    ser_investigation, ser_invoice, ser_payment, ser_referral, ser_pool,
)
import services
from services import (
    recompute_posture, evaluate_outbreak_on_confirm, is_after_hours,
    has_oncall_coverage, open_pool, compute_line_subsidies, debit_pool,
    final_payer_split, rederive_invoice_balance_status,
    VISIT_SUBSIDY_CENTS, REPORT_WINDOW_HOURS,
)

bp_b = Blueprint("routes_b", __name__)

CLEARANCE_OUTCOMES = {"NONE", "CLEARED", "NOT_CLEARED"}
PAYMENT_METHODS = {"CARD", "CASH", "EXTERNAL_REMITTANCE"}
SERVICE_CATEGORIES = {"CONSULT", "PHARMACY", "LAB", "TRAVEL_VACCINE", "SPORTS_FEE"}


def get_or_404(table, entity_id):
    e = db[table].get(entity_id)
    if e is None:
        raise err_not_found("Resource not found: %s" % entity_id)
    return e


def arg(name):
    return request.args.get(name)


def require_open_encounter(eid):
    enc = get_or_404("encounters", eid)
    return enc


# ==========================================================================
# Encounters
# ==========================================================================

@bp_b.route("/shc/encounters", methods=["GET"])
def list_encounters():
    require_auth()
    items = db["encounters"].values()
    if arg("appointment_id") is not None:
        items = [e for e in items if e["appointment_id"] == arg("appointment_id")]
    if arg("student_id") is not None:
        items = [e for e in items if e["student_id"] == arg("student_id")]
    if arg("provider_id") is not None:
        items = [e for e in items if e["provider_id"] == arg("provider_id")]
    if arg("status") is not None:
        items = [e for e in items if e["status"] == arg("status")]
    return list_response(items, ser_encounter)


@bp_b.route("/shc/encounters/<eid>", methods=["GET"])
def get_encounter(eid):
    require_auth()
    return envelope_ok(ser_encounter(get_or_404("encounters", eid)))


@bp_b.route("/shc/encounters/<eid>/close", methods=["POST"])
def close_encounter(eid):
    require_auth({"Clinician"})
    body = get_body()
    clearance = opt_enum(body, "clearance_outcome", CLEARANCE_OUTCOMES)
    enc = get_or_404("encounters", eid)
    if enc["status"] != "OPEN":
        raise ApiError("ERR_ENCOUNTER_NOT_OPEN", 409,
                       "close requires an OPEN encounter")
    # All clinical work must be terminal.
    for rx in db["prescriptions"].values():
        if rx["encounter_id"] == eid and rx["status"] not in ("DISPENSED", "CANCELLED"):
            raise ApiError("ERR_UNRESOLVED_CLINICAL_WORK", 409,
                           "a prescription is not yet terminal")
    for lo in db["lab_orders"].values():
        if lo["encounter_id"] == eid and lo["status"] != "REVIEWED":
            raise ApiError("ERR_UNRESOLVED_CLINICAL_WORK", 409,
                           "a lab order is not yet REVIEWED")
    # Billing coded for chargeable encounters.
    if not enc["fee_covered"]:
        has_invoice = any(i["encounter_id"] == eid for i in db["invoices"].values())
        if not has_invoice:
            raise ApiError("ERR_BILLING_NOT_CODED", 409,
                           "closing a chargeable encounter with no invoice")
    # Clearance: only meaningful for SPORTS_PHYSICAL; CLEARED requires CLEAR posture.
    if clearance is not None and enc["visit_type"] != "SPORTS_PHYSICAL":
        raise err_invalid_request(
            "clearance_outcome is only allowed for SPORTS_PHYSICAL encounters")
    if clearance == "CLEARED":
        student = db["students"][enc["student_id"]]
        if student["compliance_posture"] != "CLEAR":
            raise ApiError("ERR_CLEARANCE_BLOCKED", 403,
                           "clearance_outcome CLEARED requires posture CLEAR")
    now = clock.now()
    enc["status"] = "CLOSED"
    enc["closed_at"] = now
    if clearance is not None:
        enc["clearance_outcome"] = clearance
    bump(enc)
    appt = db["appointments"].get(enc["appointment_id"])
    if appt is not None and appt["status"] == "CHECKED_IN":
        appt["status"] = "COMPLETED"
        bump(appt)
    if enc["fee_covered"]:
        debit_pool(open_pool(), VISIT_SUBSIDY_CENTS)
    return envelope_ok(ser_encounter(enc))


# ==========================================================================
# Pharmacy: prescriptions and medication stocks
# ==========================================================================

@bp_b.route("/shc/encounters/<eid>/prescriptions", methods=["POST"])
def create_prescription(eid):
    require_auth({"Clinician"})
    body = get_body()
    medication_stock_id = req_string(body, "medication_stock_id")
    quantity = req_int(body, "quantity")
    enc = get_or_404("encounters", eid)
    if db["stocks"].get(medication_stock_id) is None:
        raise err_not_found("medication_stock_id does not reference an existing stock")
    if enc["status"] != "OPEN":
        raise ApiError("ERR_ENCOUNTER_NOT_OPEN", 409,
                       "child creation requires an OPEN encounter")
    if quantity <= 0:
        raise ApiError("ERR_INVALID_QUANTITY", 422, "quantity must be > 0")
    rx = new_entity()
    rx.update({
        "encounter_id": eid,
        "medication_stock_id": medication_stock_id,
        "quantity_prescribed": quantity,
        "quantity_dispensed": 0,
        "status": "WRITTEN",
    })
    db["prescriptions"][rx["id"]] = rx
    return envelope_ok(ser_prescription(rx), status=201)


@bp_b.route("/shc/prescriptions", methods=["GET"])
def list_prescriptions():
    require_auth()
    items = db["prescriptions"].values()
    if arg("encounter_id") is not None:
        items = [r for r in items if r["encounter_id"] == arg("encounter_id")]
    if arg("medication_stock_id") is not None:
        items = [r for r in items if r["medication_stock_id"] == arg("medication_stock_id")]
    if arg("status") is not None:
        items = [r for r in items if r["status"] == arg("status")]
    return list_response(items, ser_prescription)


@bp_b.route("/shc/prescriptions/<pid>", methods=["GET"])
def get_prescription(pid):
    require_auth()
    return envelope_ok(ser_prescription(get_or_404("prescriptions", pid)))


@bp_b.route("/shc/prescriptions/<pid>/dispense", methods=["POST"])
def dispense(pid):
    require_auth({"Pharmacist"})
    body = get_body()
    quantity = req_int(body, "quantity")
    rx = get_or_404("prescriptions", pid)
    if rx["status"] not in ("WRITTEN", "PARTIALLY_DISPENSED"):
        raise ApiError("ERR_PRESCRIPTION_NOT_DISPENSABLE", 409,
                       "dispense requires status WRITTEN or PARTIALLY_DISPENSED")
    if quantity <= 0:
        raise ApiError("ERR_INVALID_QUANTITY", 422, "quantity must be > 0")
    remaining = rx["quantity_prescribed"] - rx["quantity_dispensed"]
    if quantity > remaining:
        raise ApiError("ERR_DISPENSE_QUANTITY_EXCEEDS", 422,
                       "dispense quantity exceeds remaining prescribed units")
    stock = db["stocks"][rx["medication_stock_id"]]
    if stock["on_hand"] < quantity:
        raise ApiError("ERR_INSUFFICIENT_STOCK", 409,
                       "dispense quantity exceeds stock on hand")
    rx["quantity_dispensed"] += quantity
    rx["status"] = ("DISPENSED" if rx["quantity_dispensed"] == rx["quantity_prescribed"]
                    else "PARTIALLY_DISPENSED")
    bump(rx)
    stock["on_hand"] -= quantity
    stock["needs_reorder"] = stock["on_hand"] <= stock["reorder_threshold"]
    bump(stock)
    return envelope_ok(ser_prescription(rx))


@bp_b.route("/shc/prescriptions/<pid>/cancel", methods=["POST"])
def cancel_prescription(pid):
    require_auth({"Clinician"})
    get_body()
    rx = get_or_404("prescriptions", pid)
    if rx["status"] != "WRITTEN":
        raise ApiError("ERR_PRESCRIPTION_NOT_CANCELLABLE", 409,
                       "cancel requires status WRITTEN")
    rx["status"] = "CANCELLED"
    bump(rx)
    return envelope_ok(ser_prescription(rx))


@bp_b.route("/shc/medication-stocks", methods=["POST"])
def create_stock():
    require_auth({"Pharmacist"})
    body = get_body()
    medication_code = req_string(body, "medication_code")
    medication_name = req_string(body, "medication_name")
    initial_on_hand = req_int(body, "initial_on_hand")
    reorder_threshold = req_int(body, "reorder_threshold")
    if initial_on_hand < 0:
        raise err_invalid_request("initial_on_hand must be >= 0")
    if reorder_threshold < 0:
        raise err_invalid_request("reorder_threshold must be >= 0")
    for s in db["stocks"].values():
        if s["medication_code"] == medication_code:
            raise ApiError("ERR_DUPLICATE_MEDICATION", 409,
                           "medication_code already exists")
    stock = new_entity()
    stock.update({
        "medication_code": medication_code,
        "medication_name": medication_name,
        "initial_on_hand": initial_on_hand,
        "on_hand": initial_on_hand,
        "reorder_threshold": reorder_threshold,
        "needs_reorder": initial_on_hand <= reorder_threshold,
    })
    db["stocks"][stock["id"]] = stock
    return envelope_ok(ser_stock(stock), status=201)


@bp_b.route("/shc/medication-stocks", methods=["GET"])
def list_stocks():
    require_auth()
    items = db["stocks"].values()
    if arg("medication_code") is not None:
        items = [s for s in items if s["medication_code"] == arg("medication_code")]
    return list_response(items, ser_stock)


@bp_b.route("/shc/medication-stocks/<sid>/restock", methods=["POST"])
def restock(sid):
    require_auth({"Pharmacist"})
    body = get_body()
    quantity = req_int(body, "quantity")
    stock = get_or_404("stocks", sid)
    if quantity <= 0:
        raise ApiError("ERR_INVALID_QUANTITY", 422, "quantity must be > 0")
    stock["on_hand"] += quantity
    stock["needs_reorder"] = stock["on_hand"] <= stock["reorder_threshold"]
    bump(stock)
    return envelope_ok(ser_stock(stock))


# ==========================================================================
# Laboratory orders
# ==========================================================================

@bp_b.route("/shc/encounters/<eid>/lab-orders", methods=["POST"])
def create_lab_order(eid):
    require_auth({"Clinician"})
    body = get_body()
    test_code = req_string(body, "test_code")
    reportable_disease_code = body.get("reportable_disease_code")
    if reportable_disease_code is not None and not isinstance(reportable_disease_code, str):
        raise err_invalid_request("reportable_disease_code must be a string")
    enc = get_or_404("encounters", eid)
    if enc["status"] != "OPEN":
        raise ApiError("ERR_ENCOUNTER_NOT_OPEN", 409,
                       "child creation requires an OPEN encounter")
    order = new_entity()
    order.update({
        "encounter_id": eid,
        "test_code": test_code,
        "reportable_disease_code": reportable_disease_code,
        "status": "ORDERED",
        "result_summary": None,
        "flags_reportable": False,
    })
    db["lab_orders"][order["id"]] = order
    return envelope_ok(ser_lab_order(order), status=201)


@bp_b.route("/shc/encounters/<eid>/lab-orders", methods=["GET"])
def list_encounter_lab_orders(eid):
    require_auth()
    get_or_404("encounters", eid)
    items = [o for o in db["lab_orders"].values() if o["encounter_id"] == eid]
    return list_response(items, ser_lab_order)


@bp_b.route("/shc/lab-orders/<oid>", methods=["GET"])
def get_lab_order(oid):
    require_auth()
    return envelope_ok(ser_lab_order(get_or_404("lab_orders", oid)))


@bp_b.route("/shc/lab-orders/<oid>/collect", methods=["POST"])
def collect_lab_order(oid):
    require_auth({"Nurse"})
    get_body()
    order = get_or_404("lab_orders", oid)
    if order["status"] != "ORDERED":
        raise ApiError("ERR_LAB_ORDER_NOT_ORDERED", 409,
                       "collect requires status ORDERED")
    order["status"] = "SAMPLE_COLLECTED"
    bump(order)
    return envelope_ok(ser_lab_order(order))


@bp_b.route("/shc/lab-orders/<oid>/result", methods=["POST"])
def result_lab_order(oid):
    require_auth({"Nurse"})
    body = get_body()
    result_summary = req_string(body, "result_summary")
    flags_reportable = req_present(body, "flags_reportable")
    if not isinstance(flags_reportable, bool):
        raise err_invalid_request("flags_reportable must be a boolean")
    order = get_or_404("lab_orders", oid)
    if order["status"] != "SAMPLE_COLLECTED":
        raise ApiError("ERR_LAB_ORDER_NOT_COLLECTED", 409,
                       "result requires status SAMPLE_COLLECTED")
    if flags_reportable and not order["reportable_disease_code"]:
        raise ApiError("ERR_REPORTABLE_CODE_REQUIRED", 422,
                       "flags_reportable requires reportable_disease_code on the order")
    order["result_summary"] = result_summary
    order["flags_reportable"] = flags_reportable
    order["status"] = "RESULTED"
    bump(order)
    if flags_reportable:
        enc = db["encounters"][order["encounter_id"]]
        case = new_entity()
        case.update({
            "student_id": enc["student_id"],
            "lab_order_id": order["id"],
            "disease_code": order["reportable_disease_code"],
            "status": "SUSPECTED",
            "confirmed_at": None,
            "reported_at": None,
            "confirmed_by_user_id": None,
            "reported_by_user_id": None,
        })
        db["cases"][case["id"]] = case
    return envelope_ok(ser_lab_order(order))


@bp_b.route("/shc/lab-orders/<oid>/review", methods=["POST"])
def review_lab_order(oid):
    require_auth({"Clinician"})
    get_body()
    order = get_or_404("lab_orders", oid)
    if order["status"] != "RESULTED":
        raise ApiError("ERR_LAB_ORDER_NOT_RESULTED", 409,
                       "review requires status RESULTED")
    order["status"] = "REVIEWED"
    bump(order)
    return envelope_ok(ser_lab_order(order))


# ==========================================================================
# Disease cases and outbreak investigations
# ==========================================================================

@bp_b.route("/shc/disease-cases", methods=["GET"])
def list_cases():
    require_auth()
    items = db["cases"].values()
    if arg("student_id") is not None:
        items = [c for c in items if c["student_id"] == arg("student_id")]
    if arg("disease_code") is not None:
        items = [c for c in items if c["disease_code"] == arg("disease_code")]
    if arg("status") is not None:
        items = [c for c in items if c["status"] == arg("status")]
    return list_response(items, ser_case)


@bp_b.route("/shc/disease-cases/<cid>", methods=["GET"])
def get_case(cid):
    require_auth()
    return envelope_ok(ser_case(get_or_404("cases", cid)))


@bp_b.route("/shc/lab-orders/<oid>/disease-cases", methods=["GET"])
def list_order_cases(oid):
    require_auth()
    get_or_404("lab_orders", oid)
    items = [c for c in db["cases"].values() if c["lab_order_id"] == oid]
    return list_response(items, ser_case)


@bp_b.route("/shc/disease-cases/<cid>/confirm", methods=["POST"])
def confirm_case(cid):
    uid, _ = require_auth({"Clinician"})
    get_body()
    case = get_or_404("cases", cid)
    if case["status"] != "SUSPECTED":
        raise ApiError("ERR_CASE_NOT_CONFIRMABLE", 409,
                       "confirm requires status SUSPECTED")
    now = clock.now()
    case["status"] = "CONFIRMED"
    case["confirmed_at"] = now
    case["confirmed_by_user_id"] = uid
    bump(case)
    evaluate_outbreak_on_confirm(case)
    return envelope_ok(ser_case(case))


@bp_b.route("/shc/disease-cases/<cid>/report", methods=["POST"])
def report_case(cid):
    uid, _ = require_auth({"HealthAdmin"})
    get_body()
    case = get_or_404("cases", cid)
    if case["status"] != "CONFIRMED":
        raise ApiError("ERR_CASE_NOT_REPORTABLE", 409,
                       "report requires status CONFIRMED")
    now = clock.now()
    if now > case["confirmed_at"] + timedelta(hours=REPORT_WINDOW_HOURS):
        raise ApiError("ERR_REPORT_WINDOW_EXPIRED", 403,
                       "report window (24h from confirmation) has expired")
    if uid == case["confirmed_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                       "case reporter must differ from confirmer")
    case["status"] = "REPORTED"
    case["reported_at"] = now
    case["reported_by_user_id"] = uid
    bump(case)
    return envelope_ok(ser_case(case))


@bp_b.route("/shc/disease-cases/<cid>/resolve", methods=["POST"])
def resolve_case(cid):
    require_auth({"Clinician"})
    get_body()
    case = get_or_404("cases", cid)
    if case["status"] not in ("CONFIRMED", "REPORTED"):
        raise ApiError("ERR_CASE_NOT_RESOLVABLE", 409,
                       "resolve requires status CONFIRMED or REPORTED")
    case["status"] = "RESOLVED"
    bump(case)
    return envelope_ok(ser_case(case))


@bp_b.route("/shc/outbreak-investigations", methods=["GET"])
def list_investigations():
    require_auth()
    items = db["investigations"].values()
    if arg("disease_code") is not None:
        items = [i for i in items if i["disease_code"] == arg("disease_code")]
    if arg("status") is not None:
        items = [i for i in items if i["status"] == arg("status")]
    return list_response(items, ser_investigation)


@bp_b.route("/shc/outbreak-investigations/<iid>/contain", methods=["POST"])
def contain_investigation(iid):
    require_auth({"HealthAdmin"})
    get_body()
    inv = get_or_404("investigations", iid)
    if inv["status"] != "ACTIVE":
        raise ApiError("ERR_OUTBREAK_NOT_ACTIVE", 409,
                       "contain requires status ACTIVE")
    inv["status"] = "CONTAINED"
    bump(inv)
    return envelope_ok(ser_investigation(inv))


@bp_b.route("/shc/outbreak-investigations/<iid>/reopen", methods=["POST"])
def reopen_investigation(iid):
    require_auth({"HealthAdmin"})
    get_body()
    inv = get_or_404("investigations", iid)
    if inv["status"] != "CONTAINED":
        raise ApiError("ERR_OUTBREAK_NOT_CONTAINED", 409,
                       "reopen requires status CONTAINED")
    inv["status"] = "ACTIVE"
    bump(inv)
    return envelope_ok(ser_investigation(inv))


@bp_b.route("/shc/outbreak-investigations/<iid>/close", methods=["POST"])
def close_investigation(iid):
    require_auth({"HealthAdmin"})
    get_body()
    inv = get_or_404("investigations", iid)
    if inv["status"] != "CONTAINED":
        raise ApiError("ERR_OUTBREAK_NOT_CONTAINED", 409,
                       "close requires status CONTAINED")
    unresolved = any(
        c["disease_code"] == inv["disease_code"]
        and c["status"] in ("SUSPECTED", "CONFIRMED", "REPORTED")
        for c in db["cases"].values())
    if unresolved:
        raise ApiError("ERR_OUTBREAK_UNRESOLVED_CASES", 409,
                       "unresolved cases exist for this disease_code")
    inv["status"] = "CLOSED"
    bump(inv)
    return envelope_ok(ser_investigation(inv))
