"""Lead & Healthy-Homes Program API — Flask entry point."""
import os
from datetime import timedelta
from uuid import uuid4

from flask import Flask, request

import store
import calc
from errors import ApiError
from responses import object_response, array_response, error_response, serialize

app = Flask(__name__)

ROLES = {"IntakeCoordinator", "CaseManager", "Inspector", "Contractor", "ProgramAdmin"}
ENUMS = {
    "income_tier": {"EXTREMELY_LOW", "VERY_LOW", "LOW", "MODERATE"},
    "specimen_type": {"VENOUS", "CAPILLARY"},
    "test_kind": {"SCREENING", "DIAGNOSTIC", "FOLLOWUP"},
    "hazard_type": {"PAINT", "DUST", "SOIL", "WATER"},
    "severity": {"LOW", "MODERATE", "HIGH"},
    "unit_status": {"AVAILABLE", "OFFLINE"},
    "cert_action": {"ACTIVATE", "SUSPEND", "REINSTATE", "EXPIRE", "REVOKE"},
}


# ---------------------------------------------------------------------------
# Request-level concurrency guard + envelope error handling.
# ---------------------------------------------------------------------------
@app.before_request
def _acquire_lock():
    store.LOCK.acquire()


@app.teardown_request
def _release_lock(exc):
    try:
        store.LOCK.release()
    except RuntimeError:
        pass


@app.after_request
def _no_keepalive(resp):
    resp.headers["Connection"] = "close"
    return resp


@app.errorhandler(ApiError)
def _handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def _handle_404(e):
    return error_response("ERR_VALIDATION", "Not found", 404)


@app.errorhandler(405)
def _handle_405(e):
    return error_response("ERR_VALIDATION", "Method not allowed", 405)


@app.errorhandler(Exception)
def _handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.message, e.http_status)
    return error_response("ERR_VALIDATION", "Internal error: %s" % e, 500)


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def auth(allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", "Role %s may not perform this operation" % role)
    return uid, role


# ---------------------------------------------------------------------------
# Body / query helpers
# ---------------------------------------------------------------------------
def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", "Request body must be a JSON object")
    return data


def require(data, field):
    if field not in data or data[field] is None:
        raise ApiError("ERR_VALIDATION", "Missing required field: %s" % field)
    return data[field]


def check_enum(value, name):
    if value not in ENUMS[name]:
        raise ApiError("ERR_VALIDATION", "Illegal value for %s" % name)
    return value


def check_str(value, field):
    if not isinstance(value, str) or value == "":
        raise ApiError("ERR_VALIDATION", "Field %s must be a non-empty string" % field)
    return value


def check_number_nonneg(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError("ERR_VALIDATION", "Field %s must be a number" % field)
    if value < 0:
        raise ApiError("ERR_VALIDATION", "Field %s must be >= 0" % field)
    return value


def check_int(value, field, minimum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_VALIDATION", "Field %s must be an integer" % field)
    if minimum is not None and value < minimum:
        raise ApiError("ERR_VALIDATION", "Field %s must be >= %d" % (field, minimum))
    return value


def check_datetime(value, field):
    try:
        store.parse_dt(value)
    except Exception:
        raise ApiError("ERR_VALIDATION", "Field %s must be an ISO 8601 datetime" % field)
    return value


def check_date(value, field):
    try:
        store.parse_date(value)
    except Exception:
        raise ApiError("ERR_VALIDATION", "Field %s must be an ISO 8601 date" % field)
    return value


def pagination():
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_VALIDATION", "limit must be in [1, 100]")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_VALIDATION", "offset must be >= 0")
    return limit, offset


def list_result(rows, limit, offset):
    rows = sorted(rows, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))
    total = len(rows)
    page = rows[offset:offset + limit]
    return array_response([serialize(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Existence helpers
# ---------------------------------------------------------------------------
def lookup(coll, id_, err_id):
    ent = store.DB[coll].get(id_)
    if ent is None:
        raise ApiError(err_id)
    return ent


# ---------------------------------------------------------------------------
# Entity build / mutate helpers
# ---------------------------------------------------------------------------
def new_entity(coll, fields, common=True):
    eid = str(uuid4())
    ts = store.now_ts()
    ent = {"id": eid}
    ent.update(fields)
    ent["created_at"] = ts
    if common:
        ent["updated_at"] = ts
        ent["version"] = 1
    ent["_seq"] = store.next_seq()
    store.DB[coll][eid] = ent
    return ent


def bump(ent):
    ent["updated_at"] = store.now_ts()
    ent["version"] = ent.get("version", 1) + 1


def recompute_available(fund):
    fund["available_cents"] = fund["total_budget_cents"] - fund["reserved_cents"] - fund["spent_cents"]


# ===========================================================================
# Child
# ===========================================================================
@app.route("/api/v1/children", methods=["POST"])
def create_child():
    auth({"IntakeCoordinator", "ProgramAdmin"})
    data = body()
    full_name = check_str(require(data, "full_name"), "full_name")
    dob = check_str(require(data, "date_of_birth"), "date_of_birth")
    guardian = check_str(require(data, "guardian_name"), "guardian_name")
    dwelling_id = check_str(require(data, "primary_dwelling_id"), "primary_dwelling_id")
    income_tier = check_enum(require(data, "income_tier"), "income_tier")
    medicaid = data.get("medicaid_enrolled", False)
    if not isinstance(medicaid, bool):
        raise ApiError("ERR_VALIDATION", "medicaid_enrolled must be a boolean")
    ent = new_entity("children", {
        "full_name": full_name,
        "date_of_birth": dob,
        "guardian_name": guardian,
        "primary_dwelling_id": dwelling_id,
        "medicaid_enrolled": medicaid,
        "income_tier": income_tier,
    })
    return object_response(serialize(ent), 201)


@app.route("/api/v1/children", methods=["GET"])
def list_children():
    auth({"IntakeCoordinator", "CaseManager", "Inspector", "ProgramAdmin"})
    limit, offset = pagination()
    rows = list(store.DB["children"].values())
    dwelling = request.args.get("primary_dwelling_id")
    if dwelling is not None:
        rows = [r for r in rows if r["primary_dwelling_id"] == dwelling]
    return list_result(rows, limit, offset)


@app.route("/api/v1/children/<id_>", methods=["GET"])
def get_child(id_):
    auth({"IntakeCoordinator", "CaseManager", "Inspector", "ProgramAdmin"})
    ent = lookup("children", id_, "ERR_CHILD_NOT_FOUND")
    return object_response(serialize(ent))


@app.route("/api/v1/children/<id_>/blood-lead-tests", methods=["GET"])
def list_child_tests(id_):
    auth({"IntakeCoordinator", "CaseManager", "Inspector", "ProgramAdmin"})
    limit, offset = pagination()
    lookup("children", id_, "ERR_CHILD_NOT_FOUND")
    rows = [t for t in store.DB["blood_lead_tests"].values() if t["child_id"] == id_]
    return list_result(rows, limit, offset)


# ===========================================================================
# BloodLeadTest
# ===========================================================================
def _recompute_confirmed_reference(case, child_id):
    candidates = [t for t in store.DB["blood_lead_tests"].values()
                  if t["child_id"] == child_id
                  and t["specimen_type"] == "VENOUS"
                  and t["test_kind"] in ("SCREENING", "DIAGNOSTIC")]
    if not candidates:
        return
    max_bll = max(t["bll_ug_dl"] for t in candidates)
    case["reference_bll_ug_dl"] = max_bll
    case["reference_basis"] = "CONFIRMED"
    case["priority_class"] = calc.priority_class(max_bll)
    bump(case)


def _apply_medical_followup(case, bll):
    below = calc._to_decimal(bll) < calc.BLL_CASE_THRESHOLD_UG_DL
    ms = case["medical_status"]
    new = ms
    if below:
        if ms == "ELEVATED":
            new = "MONITORING"
        elif ms == "MONITORING":
            new = "RESOLVED"
    else:
        if ms == "MONITORING":
            new = "ELEVATED"
    if new != ms:
        case["medical_status"] = new
        bump(case)


@app.route("/api/v1/blood-lead-tests", methods=["POST"])
def create_blood_lead_test():
    auth({"IntakeCoordinator"})
    data = body()
    child_id = check_str(require(data, "child_id"), "child_id")
    bll = check_number_nonneg(require(data, "bll_ug_dl"), "bll_ug_dl")
    specimen = check_enum(require(data, "specimen_type"), "specimen_type")
    kind = check_enum(require(data, "test_kind"), "test_kind")
    collected_at = check_datetime(require(data, "collected_at"), "collected_at")
    lookup("children", child_id, "ERR_CHILD_NOT_FOUND")

    ent = new_entity("blood_lead_tests", {
        "child_id": child_id,
        "bll_ug_dl": bll,
        "specimen_type": specimen,
        "test_kind": kind,
        "collected_at": collected_at,
        "result_class": calc.result_class(bll),
    }, common=False)

    # Downstream effects on non-terminal cases of this child.
    active_cases = [c for c in store.DB["cases"].values()
                    if c["child_id"] == child_id
                    and c["case_status"] not in ("CLOSED", "WITHDRAWN")]
    for case in active_cases:
        if specimen == "VENOUS" and kind in ("SCREENING", "DIAGNOSTIC"):
            _recompute_confirmed_reference(case, child_id)
        elif specimen == "VENOUS" and kind == "FOLLOWUP":
            _apply_medical_followup(case, bll)

    return object_response(serialize(ent), 201)


# ===========================================================================
# Dwelling
# ===========================================================================
@app.route("/api/v1/dwellings", methods=["POST"])
def create_dwelling():
    auth({"IntakeCoordinator", "ProgramAdmin"})
    data = body()
    street = check_str(require(data, "street_address"), "street_address")
    year_built = check_int(require(data, "year_built"), "year_built")
    owner = check_str(require(data, "owner_name"), "owner_name")
    jurisdiction = check_str(require(data, "jurisdiction"), "jurisdiction")
    unit_designation = data.get("unit_designation", None)
    if unit_designation is not None and not isinstance(unit_designation, str):
        raise ApiError("ERR_VALIDATION", "unit_designation must be a string or null")
    ent = new_entity("dwellings", {
        "street_address": street,
        "unit_designation": unit_designation,
        "year_built": year_built,
        "owner_name": owner,
        "jurisdiction": jurisdiction,
        "pre_1978": year_built < 1978,
    })
    return object_response(serialize(ent), 201)


# ===========================================================================
# Case
# ===========================================================================
@app.route("/api/v1/cases", methods=["POST"])
def create_case():
    auth({"IntakeCoordinator"})
    data = body()
    child_id = check_str(require(data, "child_id"), "child_id")
    dwelling_id = check_str(require(data, "dwelling_id"), "dwelling_id")
    qualifying_test_id = check_str(require(data, "qualifying_test_id"), "qualifying_test_id")
    # Existence, left-to-right.
    child = lookup("children", child_id, "ERR_CHILD_NOT_FOUND")
    lookup("dwellings", dwelling_id, "ERR_DWELLING_NOT_FOUND")
    test = lookup("blood_lead_tests", qualifying_test_id, "ERR_TEST_NOT_FOUND")
    # Domain gate (priority 9): mismatch first, then threshold.
    if test["child_id"] != child_id:
        raise ApiError("ERR_QUALIFYING_TEST_MISMATCH",
                       "Qualifying test does not belong to this child")
    if calc._to_decimal(test["bll_ug_dl"]) < calc.BLL_CASE_THRESHOLD_UG_DL:
        raise ApiError("ERR_BLL_BELOW_THRESHOLD",
                       "Qualifying test BLL is below the case-opening threshold")
    ref = test["bll_ug_dl"]
    ent = new_entity("cases", {
        "child_id": child_id,
        "dwelling_id": dwelling_id,
        "qualifying_test_id": qualifying_test_id,
        "case_status": "OPEN",
        "medical_status": "ELEVATED",
        "reference_bll_ug_dl": ref,
        "reference_basis": "PROVISIONAL",
        "priority_class": calc.priority_class(ref),
        "income_tier": child["income_tier"],
        "open_hazard_count": 0,
        "controlled_hazard_count": 0,
        "total_hazard_count": 0,
    })
    return object_response(serialize(ent), 201)


@app.route("/api/v1/cases/<id_>", methods=["GET"])
def get_case(id_):
    auth({"IntakeCoordinator", "CaseManager", "Inspector", "ProgramAdmin"})
    ent = lookup("cases", id_, "ERR_CASE_NOT_FOUND")
    return object_response(serialize(ent))


@app.route("/api/v1/cases", methods=["GET"])
def list_cases():
    auth({"IntakeCoordinator", "CaseManager", "Inspector", "ProgramAdmin"})
    limit, offset = pagination()
    rows = list(store.DB["cases"].values())
    for f in ("child_id", "dwelling_id", "qualifying_test_id", "case_status"):
        val = request.args.get(f)
        if val is not None:
            rows = [r for r in rows if r[f] == val]
    return list_result(rows, limit, offset)


def _void_order(order, actor_cascade=True):
    """Void an order and run its compensating cascade."""
    case = store.DB["cases"].get(order["case_id"])
    investigation_id = order["investigation_id"]
    # revert CONTROLLED hazards of the source investigation to OPEN
    reverted = 0
    for hf in store.DB["hazard_findings"].values():
        if hf["investigation_id"] == investigation_id and hf["control_status"] == "CONTROLLED":
            hf["control_status"] = "OPEN"
            bump(hf)
            reverted += 1
    order["status"] = "VOID"
    bump(order)
    if case is not None and reverted:
        case["controlled_hazard_count"] -= reverted
        case["open_hazard_count"] += reverted
        case["total_hazard_count"] = case["open_hazard_count"] + case["controlled_hazard_count"]
        bump(case)
    # cancel non-terminal remediation projects of this order (releases reservations)
    for proj in store.DB["remediation_projects"].values():
        if proj["order_id"] == order["id"] and proj["status"] in ("PROPOSED", "APPROVED", "IN_PROGRESS"):
            _cancel_project(proj)


def _cancel_project(proj):
    had_reservation = proj["status"] in ("APPROVED", "IN_PROGRESS")
    proj["status"] = "CANCELLED"
    bump(proj)
    if had_reservation:
        fund = store.DB["grant_funds"].get(proj["grant_fund_id"])
        if fund is not None:
            fund["reserved_cents"] -= proj["estimated_cost_cents"]
            recompute_available(fund)
            bump(fund)


@app.route("/api/v1/cases/<id_>/withdraw", methods=["POST"])
def withdraw_case(id_):
    auth({"CaseManager"})
    case = lookup("cases", id_, "ERR_CASE_NOT_FOUND")
    if case["case_status"] not in ("OPEN", "INVESTIGATION", "ENFORCEMENT"):
        raise ApiError("ERR_INVALID_STATE", "Case cannot be withdrawn from its current state")
    case["case_status"] = "WITHDRAWN"
    bump(case)
    # fan-out: cancel non-terminal investigations
    for inv in store.DB["investigations"].values():
        if inv["case_id"] == id_ and inv["status"] in ("SCHEDULED", "IN_PROGRESS"):
            inv["status"] = "CANCELLED"
            bump(inv)
    # cascade: void non-terminal orders
    for order in list(store.DB["hazard_control_orders"].values()):
        if order["case_id"] == id_ and order["status"] in ("ISSUED", "IN_REMEDIATION", "CLEARANCE_PENDING"):
            _void_order(order)
    return object_response(serialize(case))


@app.route("/api/v1/cases/<id_>/close", methods=["POST"])
def close_case(id_):
    auth({"CaseManager"})
    case = lookup("cases", id_, "ERR_CASE_NOT_FOUND")
    if case["case_status"] != "ENFORCEMENT":
        raise ApiError("ERR_INVALID_STATE", "Case can only be closed from ENFORCEMENT")
    orders = [o for o in store.DB["hazard_control_orders"].values() if o["case_id"] == id_]
    any_cleared = any(o["status"] == "CLEARED" for o in orders)
    all_terminal = all(o["status"] in ("CLEARED", "VOID") for o in orders)
    if (case["medical_status"] != "RESOLVED"
            or case["open_hazard_count"] != 0
            or not any_cleared
            or not all_terminal):
        raise ApiError("ERR_CASE_NOT_RESOLVABLE", "Case does not satisfy closure preconditions")
    case["case_status"] = "CLOSED"
    bump(case)
    return object_response(serialize(case))


# ===========================================================================
# Inspector
# ===========================================================================
@app.route("/api/v1/inspectors", methods=["POST"])
def create_inspector():
    auth({"ProgramAdmin"})
    data = body()
    full_name = check_str(require(data, "full_name"), "full_name")
    cert = check_str(require(data, "certification_id_number"), "certification_id_number")
    active = data.get("active", True)
    if not isinstance(active, bool):
        raise ApiError("ERR_VALIDATION", "active must be a boolean")
    ent = new_entity("inspectors", {
        "full_name": full_name,
        "certification_id_number": cert,
        "active": active,
    })
    return object_response(serialize(ent), 201)


# ===========================================================================
# EnvironmentalInvestigation
# ===========================================================================
def _windows_overlap(a_start, a_end, b_start, b_end):
    # half-open [start, end): overlap iff a_start < b_end AND a_end > b_start
    return a_start < b_end and a_end > b_start


@app.route("/api/v1/investigations", methods=["POST"])
def create_investigation():
    auth({"CaseManager"})
    data = body()
    case_id = check_str(require(data, "case_id"), "case_id")
    dwelling_id = check_str(require(data, "dwelling_id"), "dwelling_id")
    inspector_id = check_str(require(data, "inspector_id"), "inspector_id")
    scheduled_start = check_datetime(require(data, "scheduled_start"), "scheduled_start")
    scheduled_end = check_datetime(require(data, "scheduled_end"), "scheduled_end")
    case = lookup("cases", case_id, "ERR_CASE_NOT_FOUND")
    lookup("dwellings", dwelling_id, "ERR_DWELLING_NOT_FOUND")
    lookup("inspectors", inspector_id, "ERR_INSPECTOR_NOT_FOUND")
    # state (priority 7)
    if case["case_status"] not in ("OPEN", "INVESTIGATION"):
        raise ApiError("ERR_INVALID_STATE", "Case is not schedulable for investigation")
    # double-booking (priority 13)
    ns = store.parse_dt(scheduled_start)
    ne = store.parse_dt(scheduled_end)
    for inv in store.DB["investigations"].values():
        if inv["inspector_id"] == inspector_id and inv["status"] in ("SCHEDULED", "IN_PROGRESS"):
            es = store.parse_dt(inv["scheduled_start"])
            ee = store.parse_dt(inv["scheduled_end"])
            if _windows_overlap(ns, ne, es, ee):
                raise ApiError("ERR_INSPECTOR_DOUBLE_BOOKED", "Inspector already booked in this window")
    ent = new_entity("investigations", {
        "case_id": case_id,
        "dwelling_id": dwelling_id,
        "inspector_id": inspector_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "status": "SCHEDULED",
        "hazard_finding_count": 0,
        "completed_at": None,
    })
    if case["case_status"] == "OPEN":
        case["case_status"] = "INVESTIGATION"
        bump(case)
    return object_response(serialize(ent), 201)


@app.route("/api/v1/investigations/<id_>", methods=["GET"])
def get_investigation(id_):
    auth({"CaseManager", "Inspector", "ProgramAdmin"})
    ent = lookup("investigations", id_, "ERR_INVESTIGATION_NOT_FOUND")
    return object_response(serialize(ent))


@app.route("/api/v1/investigations", methods=["GET"])
def list_investigations():
    auth({"CaseManager", "Inspector", "ProgramAdmin"})
    limit, offset = pagination()
    rows = list(store.DB["investigations"].values())
    for f in ("case_id", "dwelling_id", "inspector_id", "status"):
        val = request.args.get(f)
        if val is not None:
            rows = [r for r in rows if r[f] == val]
    return list_result(rows, limit, offset)


@app.route("/api/v1/investigations/<id_>/hazard-findings", methods=["GET"])
def list_investigation_findings(id_):
    auth({"CaseManager", "Inspector", "ProgramAdmin"})
    limit, offset = pagination()
    lookup("investigations", id_, "ERR_INVESTIGATION_NOT_FOUND")
    rows = [f for f in store.DB["hazard_findings"].values() if f["investigation_id"] == id_]
    return list_result(rows, limit, offset)


@app.route("/api/v1/investigations/<id_>/findings", methods=["POST"])
def create_finding(id_):
    uid, role = auth({"Inspector"})
    data = body()
    hazard_type = check_enum(require(data, "hazard_type"), "hazard_type")
    location = check_str(require(data, "location"), "location")
    measurement = check_number_nonneg(require(data, "measurement_value"), "measurement_value")
    severity = check_enum(require(data, "severity"), "severity")
    inv = lookup("investigations", id_, "ERR_INVESTIGATION_NOT_FOUND")
    # ownership (priority 5)
    if uid != inv["inspector_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Acting inspector does not own this investigation")
    # state (priority 7)
    if inv["status"] not in ("SCHEDULED", "IN_PROGRESS"):
        raise ApiError("ERR_INVALID_STATE", "Findings cannot be recorded in the investigation's state")
    finding = new_entity("hazard_findings", {
        "investigation_id": id_,
        "hazard_type": hazard_type,
        "location": location,
        "measurement_value": measurement,
        "severity": severity,
        "control_status": "OPEN",
    })
    if inv["status"] == "SCHEDULED":
        inv["status"] = "IN_PROGRESS"
    inv["hazard_finding_count"] += 1
    bump(inv)
    case = store.DB["cases"].get(inv["case_id"])
    if case is not None:
        case["open_hazard_count"] += 1
        case["total_hazard_count"] = case["open_hazard_count"] + case["controlled_hazard_count"]
        bump(case)
    return object_response(serialize(finding), 201)


@app.route("/api/v1/investigations/<id_>/complete", methods=["POST"])
def complete_investigation(id_):
    uid, role = auth({"Inspector"})
    inv = lookup("investigations", id_, "ERR_INVESTIGATION_NOT_FOUND")
    if uid != inv["inspector_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Acting inspector does not own this investigation")
    if inv["status"] not in ("SCHEDULED", "IN_PROGRESS"):
        raise ApiError("ERR_INVALID_STATE", "Investigation cannot be completed from its state")
    inv["status"] = "COMPLETED"
    inv["completed_at"] = store.now_ts()
    bump(inv)
    case = store.DB["cases"].get(inv["case_id"])
    if inv["hazard_finding_count"] >= 1:
        now = store.clock_now()
        deadline = now + timedelta(days=calc.ORDER_COMPLIANCE_DEADLINE_DAYS)
        new_entity("hazard_control_orders", {
            "case_id": inv["case_id"],
            "dwelling_id": inv["dwelling_id"],
            "investigation_id": inv["id"],
            "status": "ISSUED",
            "issued_at": store.render_ts(now),
            "compliance_deadline": store.render_ts(deadline),
            "hazard_count": inv["hazard_finding_count"],
        })
        if case is not None and case["case_status"] == "INVESTIGATION":
            case["case_status"] = "ENFORCEMENT"
            bump(case)
    else:
        if case is not None and case["case_status"] == "INVESTIGATION" and case["medical_status"] == "RESOLVED":
            case["case_status"] = "CLOSED"
            bump(case)
    return object_response(serialize(inv))


# ===========================================================================
# HazardControlOrder
# ===========================================================================
@app.route("/api/v1/hazard-control-orders/<id_>", methods=["GET"])
def get_order(id_):
    auth({"CaseManager", "Inspector", "Contractor", "ProgramAdmin"})
    ent = lookup("hazard_control_orders", id_, "ERR_ORDER_NOT_FOUND")
    return object_response(serialize(ent))


@app.route("/api/v1/hazard-control-orders", methods=["GET"])
def list_orders():
    auth({"CaseManager", "Inspector", "ProgramAdmin"})
    limit, offset = pagination()
    rows = list(store.DB["hazard_control_orders"].values())
    for f in ("case_id", "dwelling_id", "investigation_id", "status"):
        val = request.args.get(f)
        if val is not None:
            rows = [r for r in rows if r[f] == val]
    return list_result(rows, limit, offset)


@app.route("/api/v1/hazard-control-orders/<id_>/clearance-tests", methods=["GET"])
def list_order_clearance_tests(id_):
    auth({"CaseManager", "Inspector", "ProgramAdmin"})
    limit, offset = pagination()
    lookup("hazard_control_orders", id_, "ERR_ORDER_NOT_FOUND")
    rows = [c for c in store.DB["clearance_tests"].values() if c["order_id"] == id_]
    return list_result(rows, limit, offset)


@app.route("/api/v1/hazard-control-orders/<id_>/request-clearance", methods=["POST"])
def request_clearance(id_):
    uid, role = auth({"Contractor"})
    order = lookup("hazard_control_orders", id_, "ERR_ORDER_NOT_FOUND")
    # ownership (priority 5): the contractor of the order's IN_PROGRESS project
    in_progress = [p for p in store.DB["remediation_projects"].values()
                   if p["order_id"] == id_ and p["status"] == "IN_PROGRESS"]
    if in_progress and all(p["contractor_id"] != uid for p in in_progress):
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Acting contractor does not own this order's project")
    # state (priority 7)
    if order["status"] != "IN_REMEDIATION":
        raise ApiError("ERR_INVALID_STATE", "Order is not in remediation")
    order["status"] = "CLEARANCE_PENDING"
    bump(order)
    return object_response(serialize(order))


@app.route("/api/v1/hazard-control-orders/<id_>/void", methods=["POST"])
def void_order(id_):
    auth({"CaseManager"})
    order = lookup("hazard_control_orders", id_, "ERR_ORDER_NOT_FOUND")
    if order["status"] not in ("ISSUED", "IN_REMEDIATION", "CLEARANCE_PENDING", "CLEARED"):
        raise ApiError("ERR_INVALID_STATE", "Order cannot be voided from its state")
    _void_order(order)
    return object_response(serialize(order))


# ===========================================================================
# ClearanceTest
# ===========================================================================
@app.route("/api/v1/clearance-tests", methods=["POST"])
def create_clearance_test():
    uid, role = auth({"Inspector"})
    data = body()
    order_id = check_str(require(data, "order_id"), "order_id")
    floor_v = check_number_nonneg(require(data, "floor_result_ug_ft2"), "floor_result_ug_ft2")
    sill_v = check_number_nonneg(require(data, "sill_result_ug_ft2"), "sill_result_ug_ft2")
    trough_v = check_number_nonneg(require(data, "trough_result_ug_ft2"), "trough_result_ug_ft2")
    order = lookup("hazard_control_orders", order_id, "ERR_ORDER_NOT_FOUND")
    inv = store.DB["investigations"].get(order["investigation_id"])
    # four-eyes (priority 6)
    if inv is not None and uid == inv["inspector_id"]:
        raise ApiError("ERR_SOD_CONFLICT", "Clearance inspector must differ from source investigation inspector")
    # state (priority 7)
    if order["status"] != "CLEARANCE_PENDING":
        raise ApiError("ERR_INVALID_STATE", "Order is not pending clearance")
    passed = calc.clearance_pass(floor_v, sill_v, trough_v)
    ct = new_entity("clearance_tests", {
        "order_id": order_id,
        "cleared_by_inspector_id": uid,
        "floor_result_ug_ft2": floor_v,
        "sill_result_ug_ft2": sill_v,
        "trough_result_ug_ft2": trough_v,
        "evaluated_result": "PASS" if passed else "FAIL",
    }, common=False)
    if passed:
        order["status"] = "CLEARED"
        bump(order)
        case = store.DB["cases"].get(order["case_id"])
        controlled = 0
        for hf in store.DB["hazard_findings"].values():
            if hf["investigation_id"] == order["investigation_id"] and hf["control_status"] == "OPEN":
                hf["control_status"] = "CONTROLLED"
                bump(hf)
                controlled += 1
        if case is not None and controlled:
            case["open_hazard_count"] -= controlled
            case["controlled_hazard_count"] += controlled
            case["total_hazard_count"] = case["open_hazard_count"] + case["controlled_hazard_count"]
            bump(case)
    else:
        order["status"] = "IN_REMEDIATION"
        bump(order)
    return object_response(serialize(ct), 201)


# ===========================================================================
# RelocationUnit
# ===========================================================================
@app.route("/api/v1/relocation-units", methods=["POST"])
def create_relocation_unit():
    auth({"ProgramAdmin"})
    data = body()
    address = check_str(require(data, "address"), "address")
    bedrooms = check_int(require(data, "bedroom_count"), "bedroom_count", minimum=0)
    status = data.get("status", "AVAILABLE")
    if status is None:
        status = "AVAILABLE"
    if status not in ENUMS["unit_status"]:
        raise ApiError("ERR_VALIDATION", "Illegal value for status")
    ent = new_entity("relocation_units", {
        "address": address,
        "bedroom_count": bedrooms,
        "status": status,
    })
    return object_response(serialize(ent), 201)


# ===========================================================================
# RelocationPlacement
# ===========================================================================
@app.route("/api/v1/relocation-placements", methods=["POST"])
def create_relocation_placement():
    auth({"CaseManager"})
    data = body()
    case_id = check_str(require(data, "case_id"), "case_id")
    unit_id = check_str(require(data, "relocation_unit_id"), "relocation_unit_id")
    start_date = check_date(require(data, "start_date"), "start_date")
    end_date = check_date(require(data, "end_date"), "end_date")
    occupant_count = check_int(require(data, "occupant_count"), "occupant_count", minimum=1)
    # existence, left-to-right
    case = lookup("cases", case_id, "ERR_CASE_NOT_FOUND")
    unit = lookup("relocation_units", unit_id, "ERR_UNIT_NOT_FOUND")
    # priority 11: unit availability
    if unit["status"] != "AVAILABLE":
        raise ApiError("ERR_UNIT_UNAVAILABLE", "Relocation unit is not available")
    # priority 12: case not terminal
    if case["case_status"] in ("CLOSED", "WITHDRAWN"):
        raise ApiError("ERR_CASE_NOT_ACTIVE", "Cannot relocate a terminal case")
    # priority 14: overlap within cleaning buffer, closed intervals
    ns = store.parse_date(start_date)
    ne = store.parse_date(end_date)
    buf = timedelta(days=calc.RELOCATION_CLEANING_BUFFER_DAYS)
    for pl in store.DB["relocation_placements"].values():
        if pl["relocation_unit_id"] == unit_id and pl["status"] == "ACTIVE":
            es = store.parse_date(pl["start_date"])
            ee = store.parse_date(pl["end_date"])
            if ns <= ee + buf and ne >= es - buf:
                raise ApiError("ERR_RELOCATION_OVERLAP", "Placement overlaps an active booking within the buffer")
    ent = new_entity("relocation_placements", {
        "case_id": case_id,
        "relocation_unit_id": unit_id,
        "start_date": start_date,
        "end_date": end_date,
        "occupant_count": occupant_count,
        "status": "ACTIVE",
        "actual_end_date": None,
        "reimbursement_cents": 0,
    })
    return object_response(serialize(ent), 201)


@app.route("/api/v1/relocation-placements/<id_>", methods=["GET"])
def get_relocation_placement(id_):
    auth({"CaseManager", "ProgramAdmin"})
    ent = lookup("relocation_placements", id_, "ERR_PLACEMENT_NOT_FOUND")
    return object_response(serialize(ent))


@app.route("/api/v1/relocation-placements", methods=["GET"])
def list_relocation_placements():
    auth({"CaseManager", "ProgramAdmin"})
    limit, offset = pagination()
    rows = list(store.DB["relocation_placements"].values())
    for f in ("case_id", "relocation_unit_id", "status"):
        val = request.args.get(f)
        if val is not None:
            rows = [r for r in rows if r[f] == val]
    return list_result(rows, limit, offset)


@app.route("/api/v1/relocation-placements/<id_>/end", methods=["POST"])
def end_relocation_placement(id_):
    auth({"CaseManager"})
    data = body()
    actual_end = check_date(require(data, "actual_end_date"), "actual_end_date")
    pl = lookup("relocation_placements", id_, "ERR_PLACEMENT_NOT_FOUND")
    if pl["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Placement is not active")
    start = store.parse_date(pl["start_date"])
    end = store.parse_date(actual_end)
    if end < start:
        raise ApiError("ERR_VALIDATION", "actual_end_date must be on or after start_date")
    nights = (end - start).days
    pl["status"] = "ENDED"
    pl["actual_end_date"] = actual_end
    pl["reimbursement_cents"] = calc.relocation_reimbursement(pl["occupant_count"], nights)
    bump(pl)
    return object_response(serialize(pl))


# ===========================================================================
# Contractor
# ===========================================================================
@app.route("/api/v1/contractors", methods=["POST"])
def create_contractor():
    auth({"ProgramAdmin"})
    data = body()
    business_name = check_str(require(data, "business_name"), "business_name")
    rrp = check_str(require(data, "rrp_certification_number"), "rrp_certification_number")
    ent = new_entity("contractors", {
        "business_name": business_name,
        "rrp_certification_number": rrp,
        "certification_status": "PENDING",
        "certification_expires_at": None,
    })
    return object_response(serialize(ent), 201)


@app.route("/api/v1/contractors/<id_>/certification", methods=["POST"])
def contractor_certification(id_):
    auth({"ProgramAdmin"})
    data = body()
    action = require(data, "action")
    if action not in ENUMS["cert_action"]:
        raise ApiError("ERR_VALIDATION", "Illegal value for action")
    expires_at = data.get("expires_at")
    if action == "ACTIVATE":
        if expires_at is None:
            raise ApiError("ERR_VALIDATION", "expires_at is required for ACTIVATE")
        check_datetime(expires_at, "expires_at")
    contractor = lookup("contractors", id_, "ERR_CONTRACTOR_NOT_FOUND")
    status = contractor["certification_status"]
    transitions = {
        "ACTIVATE": ({"PENDING"}, "ACTIVE"),
        "SUSPEND": ({"ACTIVE"}, "SUSPENDED"),
        "REINSTATE": ({"SUSPENDED"}, "ACTIVE"),
        "EXPIRE": ({"ACTIVE"}, "EXPIRED"),
        "REVOKE": ({"ACTIVE", "SUSPENDED"}, "REVOKED"),
    }
    allowed_from, target = transitions[action]
    if status not in allowed_from:
        raise ApiError("ERR_INVALID_STATE", "Action %s not valid from %s" % (action, status))
    contractor["certification_status"] = target
    if action == "ACTIVATE":
        contractor["certification_expires_at"] = expires_at
    bump(contractor)
    return object_response(serialize(contractor))


# ===========================================================================
# GrantFund
# ===========================================================================
@app.route("/api/v1/grant-funds", methods=["POST"])
def create_grant_fund():
    auth({"ProgramAdmin"})
    data = body()
    fund_name = check_str(require(data, "fund_name"), "fund_name")
    fiscal_year = check_int(require(data, "fiscal_year"), "fiscal_year")
    total_budget = check_int(require(data, "total_budget_cents"), "total_budget_cents", minimum=0)
    ent = new_entity("grant_funds", {
        "fund_name": fund_name,
        "fiscal_year": fiscal_year,
        "total_budget_cents": total_budget,
        "reserved_cents": 0,
        "spent_cents": 0,
        "available_cents": total_budget,
    })
    return object_response(serialize(ent), 201)


@app.route("/api/v1/grant-funds/<id_>", methods=["GET"])
def get_grant_fund(id_):
    auth({"ProgramAdmin", "CaseManager"})
    ent = lookup("grant_funds", id_, "ERR_GRANT_NOT_FOUND")
    return object_response(serialize(ent))


# ===========================================================================
# RemediationProject
# ===========================================================================
@app.route("/api/v1/remediation-projects", methods=["POST"])
def create_remediation_project():
    auth({"CaseManager"})
    data = body()
    order_id = check_str(require(data, "order_id"), "order_id")
    contractor_id = check_str(require(data, "contractor_id"), "contractor_id")
    grant_fund_id = check_str(require(data, "grant_fund_id"), "grant_fund_id")
    order = lookup("hazard_control_orders", order_id, "ERR_ORDER_NOT_FOUND")
    lookup("contractors", contractor_id, "ERR_CONTRACTOR_NOT_FOUND")
    lookup("grant_funds", grant_fund_id, "ERR_GRANT_NOT_FOUND")
    if order["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE", "Project may only be proposed against an ISSUED order")
    ent = new_entity("remediation_projects", {
        "order_id": order_id,
        "contractor_id": contractor_id,
        "grant_fund_id": grant_fund_id,
        "status": "PROPOSED",
        "estimated_cost_cents": 0,
        "final_cost_cents": None,
        "line_items": [],
    })
    return object_response(serialize(ent), 201)


@app.route("/api/v1/remediation-projects/<id_>", methods=["GET"])
def get_remediation_project(id_):
    auth({"CaseManager", "Contractor", "ProgramAdmin"})
    ent = lookup("remediation_projects", id_, "ERR_PROJECT_NOT_FOUND")
    return object_response(serialize(ent))


@app.route("/api/v1/remediation-projects", methods=["GET"])
def list_remediation_projects():
    auth({"CaseManager", "Contractor", "ProgramAdmin"})
    limit, offset = pagination()
    rows = list(store.DB["remediation_projects"].values())
    for f in ("order_id", "contractor_id", "grant_fund_id", "status"):
        val = request.args.get(f)
        if val is not None:
            rows = [r for r in rows if r[f] == val]
    return list_result(rows, limit, offset)


@app.route("/api/v1/remediation-projects/<id_>/approve", methods=["POST"])
def approve_remediation_project(id_):
    auth({"CaseManager"})
    data = body()
    expected_version = require(data, "expected_grant_fund_version")
    check_int(expected_version, "expected_grant_fund_version", minimum=0)
    proj = lookup("remediation_projects", id_, "ERR_PROJECT_NOT_FOUND")
    order = store.DB["hazard_control_orders"].get(proj["order_id"])
    fund = store.DB["grant_funds"].get(proj["grant_fund_id"])
    case = store.DB["cases"].get(order["case_id"]) if order else None
    # state (priority 7)
    if proj["status"] != "PROPOSED" or order is None or order["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE", "Project or order not in an approvable state")
    # OCC (priority 8)
    if fund is None or expected_version != fund["version"]:
        raise ApiError("ERR_STALE_GRANT_VERSION", "Grant fund version is stale")
    subsidy = calc.grant_subsidy(order["hazard_count"], case["income_tier"])
    # grant sufficient (priority 16)
    if subsidy > fund["available_cents"]:
        raise ApiError("ERR_GRANT_INSUFFICIENT", "Estimated subsidy exceeds available funds")
    proj["status"] = "APPROVED"
    proj["estimated_cost_cents"] = subsidy
    bump(proj)
    fund["reserved_cents"] += subsidy
    recompute_available(fund)
    bump(fund)  # version increment satisfies OCC bump
    return object_response(serialize(proj))


@app.route("/api/v1/remediation-projects/<id_>/start", methods=["POST"])
def start_remediation_project(id_):
    uid, role = auth({"Contractor"})
    proj = lookup("remediation_projects", id_, "ERR_PROJECT_NOT_FOUND")
    # ownership (priority 5)
    if uid != proj["contractor_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Acting contractor does not own this project")
    order = store.DB["hazard_control_orders"].get(proj["order_id"])
    # state (priority 7)
    if proj["status"] != "APPROVED" or order is None or order["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE", "Project or order not in a startable state")
    # contractor certification (priority 10)
    contractor = store.DB["contractors"].get(proj["contractor_id"])
    certified = False
    if contractor is not None and contractor["certification_status"] == "ACTIVE" \
            and contractor["certification_expires_at"] is not None:
        try:
            if store.parse_dt(contractor["certification_expires_at"]) > store.clock_now():
                certified = True
        except Exception:
            certified = False
    if not certified:
        raise ApiError("ERR_CONTRACTOR_NOT_CERTIFIED", "Contractor is not certified and current")
    proj["status"] = "IN_PROGRESS"
    bump(proj)
    order["status"] = "IN_REMEDIATION"
    bump(order)
    return object_response(serialize(proj))


@app.route("/api/v1/remediation-projects/<id_>/complete", methods=["POST"])
def complete_remediation_project(id_):
    uid, role = auth({"Contractor"})
    data = body()
    line_items = require(data, "line_items")
    if not isinstance(line_items, list):
        raise ApiError("ERR_VALIDATION", "line_items must be an array")
    normalized = []
    total = 0
    for item in line_items:
        if not isinstance(item, dict):
            raise ApiError("ERR_VALIDATION", "each line item must be an object")
        amount = item.get("amount_cents")
        check_int(amount, "amount_cents", minimum=0)
        description = item.get("description", "")
        if description is not None and not isinstance(description, str):
            raise ApiError("ERR_VALIDATION", "line item description must be a string")
        normalized.append({"description": description, "amount_cents": amount})
        total += amount
    proj = lookup("remediation_projects", id_, "ERR_PROJECT_NOT_FOUND")
    if uid != proj["contractor_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Acting contractor does not own this project")
    order = store.DB["hazard_control_orders"].get(proj["order_id"])
    if proj["status"] != "IN_PROGRESS" or order is None or order["status"] != "CLEARED":
        raise ApiError("ERR_INVALID_STATE", "Project or order not in a completable state")
    proj["status"] = "COMPLETED"
    proj["line_items"] = normalized
    proj["final_cost_cents"] = total
    bump(proj)
    fund = store.DB["grant_funds"].get(proj["grant_fund_id"])
    if fund is not None:
        fund["reserved_cents"] -= proj["estimated_cost_cents"]
        fund["spent_cents"] += min(proj["estimated_cost_cents"], total)
        recompute_available(fund)
        bump(fund)
    return object_response(serialize(proj))


@app.route("/api/v1/remediation-projects/<id_>/cancel", methods=["POST"])
def cancel_remediation_project(id_):
    auth({"CaseManager"})
    proj = lookup("remediation_projects", id_, "ERR_PROJECT_NOT_FOUND")
    if proj["status"] not in ("PROPOSED", "APPROVED", "IN_PROGRESS"):
        raise ApiError("ERR_INVALID_STATE", "Project cannot be cancelled from its state")
    _cancel_project(proj)
    return object_response(serialize(proj))


# ===========================================================================
# Reporting
# ===========================================================================
@app.route("/api/v1/reports/surveillance", methods=["GET"])
def surveillance_report():
    auth({"ProgramAdmin", "CaseManager"})
    jurisdiction = request.args.get("jurisdiction")
    cases = list(store.DB["cases"].values())
    if jurisdiction is not None:
        cases = [c for c in cases
                 if (store.DB["dwellings"].get(c["dwelling_id"]) or {}).get("jurisdiction") == jurisdiction]
    total_cases = len(cases)
    open_cases = sum(1 for c in cases if c["case_status"] not in ("CLOSED", "WITHDRAWN"))
    class_i = sum(1 for c in cases if c["priority_class"] == "CLASS_I")
    class_ii = sum(1 for c in cases if c["priority_class"] == "CLASS_II")
    class_iii = sum(1 for c in cases if c["priority_class"] == "CLASS_III")
    resolved = sum(1 for c in cases if c["medical_status"] == "RESOLVED")
    total_reserved = sum(f["reserved_cents"] for f in store.DB["grant_funds"].values())
    total_spent = sum(f["spent_cents"] for f in store.DB["grant_funds"].values())
    return object_response({
        "total_cases": total_cases,
        "open_cases": open_cases,
        "class_i_count": class_i,
        "class_ii_count": class_ii,
        "class_iii_count": class_iii,
        "resolved_count": resolved,
        "total_reserved_cents": total_reserved,
        "total_spent_cents": total_spent,
    })


# ===========================================================================
# Logical clock
# ===========================================================================
@app.route("/api/v1/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth({"ProgramAdmin"})
    data = body()
    to_iso = require(data, "to_iso8601")
    try:
        dt = store.parse_dt(to_iso)
    except Exception:
        raise ApiError("ERR_VALIDATION", "to_iso8601 must be an ISO 8601 datetime")
    store.set_clock(dt)
    return object_response({})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
