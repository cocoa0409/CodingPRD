"""BackflowTest and FirePumpTest endpoints."""

from datetime import timedelta

from flask import Blueprint, request

from db import store
from middleware import require_roles, MARSHAL_AND_ADMIN, ROLE_CONTRACTOR_ADMIN
from response import success_object, list_response
from util import get_body, check_unknown_fields, req_str, req_enum, req_datetime, opt_str
from errors import (
    invalid_state, cross_reference_mismatch, license_not_valid,
    pump_coordination_required,
)
from services.core import (
    base_record, public, touch,
    get_system, get_backflow_test, get_pump_test,
    ref_device, ref_technician, ref_event,
    contractor_of_system, property_of_system,
    require_contractor_active, require_property_active,
)
from services import calc

bp = Blueprint("specialty_tests", __name__)

RESULTS = {"PASS", "FAIL"}
PUMP_TEST_KINDS = {"CHURN", "ANNUAL_FLOW"}


def _specialty_gates(sys):
    prop = property_of_system(sys)
    con = contractor_of_system(sys)
    require_contractor_active(con)
    require_property_active(prop)
    if sys["status"] != "IN_SERVICE":
        raise invalid_state("ProtectedSystem is DECOMMISSIONED")
    return prop, con


# ---- BackflowTest ----

@bp.route("/fire-compliance/systems/<sid>/backflow-tests", methods=["POST"])
def create_backflow_test(sid):
    require_roles([ROLE_CONTRACTOR_ADMIN])
    sys = get_system(sid)
    body = get_body()
    check_unknown_fields(body, {"device_id", "tester_technician_id", "tested_at", "result"})
    device_id = req_str(body, "device_id")
    tester_technician_id = req_str(body, "tester_technician_id")
    tested_at = req_datetime(body, "tested_at")
    # body FK existence (4)
    dev = ref_device(device_id)
    tech = ref_technician(tester_technician_id)
    prop, con = _specialty_gates(sys)
    # license validity (7): ACTIVE BACKFLOW license valid on the test date
    if not calc.technician_has_valid_license(tech["id"], "BACKFLOW", tested_at.date()):
        raise license_not_valid("Tester lacks an ACTIVE BACKFLOW license valid past the test date")
    result = req_enum(body, "result", RESULTS)
    # cross-aggregate integrity (15): system category + device membership/type
    if sys["system_category"] != "BACKFLOW":
        raise cross_reference_mismatch("Backflow tests require a BACKFLOW-category system")
    if dev["system_id"] != sys["id"] or dev["device_type"] != "BACKFLOW_ASSEMBLY":
        raise cross_reference_mismatch("device_id must be a BACKFLOW_ASSEMBLY device of this system")

    rec = base_record()
    failed = result == "FAIL"
    rec.update({
        "system_id": sys["id"],
        "device_id": dev["id"],
        "tester_technician_id": tech["id"],
        "tested_at": tested_at,
        "result": result,
        "unpaid_balance_cents": 0,
        "status": "FAILED_OPEN" if failed else "RECORDED",
        "_invoiced_date": None,
    })
    store.backflow_tests[rec["id"]] = rec
    if con is not None:
        calc.recompute_contractor(con)
    return success_object(public(rec), status=201)


@bp.route("/fire-compliance/systems/<sid>/backflow-tests", methods=["GET"])
def list_backflow_tests(sid):
    require_roles(MARSHAL_AND_ADMIN)
    sys = get_system(sid)
    rows = [t for t in store.backflow_tests.values() if t["system_id"] == sys["id"]]
    return list_response(rows, request.args, public)


@bp.route("/fire-compliance/backflow-tests", methods=["GET"])
def list_backflow_tests_cross():
    require_roles(MARSHAL_AND_ADMIN)
    system_id = request.args.get("system_id")
    device_id = request.args.get("device_id")
    tester = request.args.get("tester_technician_id")
    rows = list(store.backflow_tests.values())
    if system_id is not None:
        rows = [t for t in rows if t["system_id"] == system_id]
    if device_id is not None:
        rows = [t for t in rows if t["device_id"] == device_id]
    if tester is not None:
        rows = [t for t in rows if t["tester_technician_id"] == tester]
    return list_response(rows, request.args, public)


@bp.route("/fire-compliance/backflow-tests/<bid>", methods=["GET"])
def fetch_backflow_test(bid):
    require_roles(MARSHAL_AND_ADMIN)
    return success_object(public(get_backflow_test(bid)))


@bp.route("/fire-compliance/backflow-tests/<bid>/invoice", methods=["POST"])
def invoice_backflow_test(bid):
    require_roles([ROLE_CONTRACTOR_ADMIN])
    bt = get_backflow_test(bid)
    # FAIL results are already routed to FAILED_OPEN at creation; invoicing
    # anything but a RECORDED (PASS) row is an invalid state
    if bt["status"] != "RECORDED" or bt["result"] != "PASS":
        raise invalid_state("BackflowTest is not a RECORDED PASS")
    sys = store.systems.get(bt["system_id"])
    prop = property_of_system(sys) if sys else None
    con = contractor_of_system(sys) if sys else None
    require_contractor_active(con)
    require_property_active(prop)

    bt["unpaid_balance_cents"] = calc.BACKFLOW_TEST_FEE_CENTS
    bt["_invoiced_date"] = store.today()
    bt["status"] = "INVOICED"
    touch(bt)
    return success_object(public(bt))


@bp.route("/fire-compliance/backflow-tests/<bid>/record-payment", methods=["POST"])
def record_backflow_payment(bid):
    require_roles([ROLE_CONTRACTOR_ADMIN])
    bt = get_backflow_test(bid)
    if bt["status"] != "INVOICED":
        raise invalid_state("BackflowTest is not INVOICED")
    sys = store.systems.get(bt["system_id"])
    prop = property_of_system(sys) if sys else None
    con = contractor_of_system(sys) if sys else None
    require_contractor_active(con)
    require_property_active(prop)

    # compute the compounded penalty into unpaid_balance_cents, then zero it
    today = store.today()
    due = bt["_invoiced_date"] + timedelta(days=calc.BACKFLOW_PAYMENT_DUE_DAYS)
    months_late = calc.whole_months_between(due, today)
    bt["unpaid_balance_cents"] = calc.backflow_penalty_balance_cents(months_late)
    bt["unpaid_balance_cents"] = 0
    bt["status"] = "PAID"
    touch(bt)
    return success_object(public(bt))


# ---- FirePumpTest ----

@bp.route("/fire-compliance/systems/<sid>/fire-pump-tests", methods=["POST"])
def create_pump_test(sid):
    require_roles([ROLE_CONTRACTOR_ADMIN])
    sys = get_system(sid)
    body = get_body()
    check_unknown_fields(body, {"test_kind", "tester_technician_id", "tested_at", "result", "coordinated_event_id"})
    tester_technician_id = req_str(body, "tester_technician_id")
    tested_at = req_datetime(body, "tested_at")
    coordinated_event_id = opt_str(body, "coordinated_event_id")
    # body FK existence (4)
    tech = ref_technician(tester_technician_id)
    if coordinated_event_id is not None:
        ref_event(coordinated_event_id)
    prop, con = _specialty_gates(sys)
    # license validity (7): ACTIVE PUMP license valid on the test date
    if not calc.technician_has_valid_license(tech["id"], "PUMP", tested_at.date()):
        raise license_not_valid("Tester lacks an ACTIVE PUMP license valid past the test date")
    test_kind = req_enum(body, "test_kind", PUMP_TEST_KINDS)
    result = req_enum(body, "result", RESULTS)
    # cross-aggregate integrity (15): system category
    if sys["system_category"] != "FIRE_PUMP":
        raise cross_reference_mismatch("Fire-pump tests require a FIRE_PUMP-category system")

    rec = base_record()
    failed = result == "FAIL"
    rec.update({
        "system_id": sys["id"],
        "test_kind": test_kind,
        "tester_technician_id": tech["id"],
        "tested_at": tested_at,
        "result": result,
        "coordinated_event_id": coordinated_event_id,
        "status": "FAILED_OPEN" if failed else "RECORDED",
    })
    store.pump_tests[rec["id"]] = rec
    if con is not None:
        calc.recompute_contractor(con)
    return success_object(public(rec), status=201)


@bp.route("/fire-compliance/systems/<sid>/fire-pump-tests", methods=["GET"])
def list_pump_tests(sid):
    require_roles(MARSHAL_AND_ADMIN)
    sys = get_system(sid)
    rows = [t for t in store.pump_tests.values() if t["system_id"] == sys["id"]]
    return list_response(rows, request.args, public)


@bp.route("/fire-compliance/fire-pump-tests", methods=["GET"])
def list_pump_tests_cross():
    require_roles(MARSHAL_AND_ADMIN)
    system_id = request.args.get("system_id")
    tester = request.args.get("tester_technician_id")
    coordinated = request.args.get("coordinated_event_id")
    rows = list(store.pump_tests.values())
    if system_id is not None:
        rows = [t for t in rows if t["system_id"] == system_id]
    if tester is not None:
        rows = [t for t in rows if t["tester_technician_id"] == tester]
    if coordinated is not None:
        rows = [t for t in rows if t["coordinated_event_id"] == coordinated]
    return list_response(rows, request.args, public)


@bp.route("/fire-compliance/fire-pump-tests/<pid>", methods=["GET"])
def fetch_pump_test(pid):
    require_roles(MARSHAL_AND_ADMIN)
    return success_object(public(get_pump_test(pid)))


@bp.route("/fire-compliance/fire-pump-tests/<pid>/attest", methods=["POST"])
def attest_pump_test(pid):
    require_roles([ROLE_CONTRACTOR_ADMIN])
    pt = get_pump_test(pid)
    if pt["status"] != "RECORDED" or pt["result"] != "PASS":
        raise invalid_state("FirePumpTest is not a RECORDED PASS")
    sys = store.systems.get(pt["system_id"])
    prop = property_of_system(sys) if sys else None
    con = contractor_of_system(sys) if sys else None
    require_contractor_active(con)
    require_property_active(prop)
    # ANNUAL_FLOW coordination: the coordinated event must be COMPLETED and
    # cover the same system
    if pt["test_kind"] == "ANNUAL_FLOW":
        ev = store.events.get(pt["coordinated_event_id"]) if pt["coordinated_event_id"] else None
        if ev is None or ev["status"] != "COMPLETED" or ev["system_id"] != pt["system_id"]:
            raise pump_coordination_required(
                "ANNUAL_FLOW requires a COMPLETED coordinated event on the same system")

    pt["status"] = "ATTESTED"
    touch(pt)
    return success_object(public(pt))
