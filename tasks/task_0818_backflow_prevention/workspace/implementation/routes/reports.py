from flask import Blueprint, request

import store
from auth import authenticate, require_role, deny
from util import ApiError, object_response, array_response, paginate, apply_list, serialize
import validate as v
import services as svc
import lookups as lk

bp = Blueprint("reports", __name__)


@bp.post("/test-reports")
def create_report():
    user_id, role = authenticate()
    require_role(role, {"Tester"})
    body = v.json_object()

    raw_did = body.get("device_id")
    device = lk.get_device(raw_did) if isinstance(raw_did, str) and raw_did else None
    raw_tid = body.get("tester_id")
    tester = lk.get_tester(raw_tid) if isinstance(raw_tid, str) and raw_tid else None

    if tester is not None and tester["id"] != user_id:
        deny()
    if device is None:
        device = lk.get_device(v.req_nonempty_str(body, "device_id"))
    if tester is None:
        tester = lk.get_tester(v.req_nonempty_str(body, "tester_id"))
        if tester["id"] != user_id:
            deny()

    if device["status"] not in ("ACTIVE", "NEEDS_REPAIR"):
        raise ApiError("ERR_DEVICE_NOT_TESTABLE", 409, "device is not testable")

    if tester["status"] != "ACTIVE":
        raise ApiError("ERR_TESTER_NOT_CERTIFIED", 422, "tester is not certified")
    test_date = v.req_datetime(body, "test_date")
    if not (tester["cert_effective_date"] <= test_date <= tester["cert_expiry_date"]):
        raise ApiError("ERR_TESTER_NOT_CERTIFIED", 422, "tester is not certified")

    cv1 = v.req_number(body, "check_valve_1_psid", minimum=0)
    if device["device_type"] == "RP":
        relief = v.req_number(body, "relief_valve_differential_psid", minimum=0)
    else:
        relief = v.opt_number(body, "relief_valve_differential_psid", minimum=0)
    cv2 = v.opt_number(body, "check_valve_2_psid", minimum=0)

    result = svc.compute_test_result(device["device_type"], relief, cv1, cv2)

    report = {
        "device_id": device["id"],
        "tester_id": tester["id"],
        "test_date": test_date,
        "relief_valve_differential_psid": relief,
        "check_valve_1_psid": cv1,
        "check_valve_2_psid": cv2,
        "result": result,
        "status": "SUBMITTED",
        "rejection_reason": None,
    }
    svc.stamp_new(report)
    store.reports[report["id"]] = report
    return object_response(serialize(report), 201)


@bp.get("/test-reports")
def list_reports():
    user_id, role = authenticate()
    require_role(role, {"UtilityAdmin", "Tester"})
    limit, offset = paginate(request.args)

    did = request.args.get("device_id")
    tid = request.args.get("tester_id")
    status = request.args.get("status")
    result = request.args.get("result")

    pool = list(store.reports.values())
    if role == "Tester":
        pool = [r for r in pool if r["tester_id"] == user_id]
    if did is not None:
        pool = [r for r in pool if r["device_id"] == did]
    if tid is not None:
        pool = [r for r in pool if r["tester_id"] == tid]
    if status is not None:
        pool = [r for r in pool if r["status"] == status]
    if result is not None:
        pool = [r for r in pool if r["result"] == result]

    items, total = apply_list(pool, limit, offset)
    return array_response(items, limit, offset, total)


@bp.get("/test-reports/<rid>")
def get_report(rid):
    user_id, role = authenticate()
    require_role(role, {"UtilityAdmin", "Tester"})
    report = lk.get_report(rid)
    if role == "Tester" and report["tester_id"] != user_id:
        deny()
    return object_response(serialize(report))


@bp.post("/test-reports/<rid>/accept")
def accept_report(rid):
    user_id, role = authenticate()
    require_role(role, {"UtilityAdmin"})
    report = lk.get_report(rid)
    if report["status"] != "SUBMITTED":
        raise ApiError("ERR_REPORT_NOT_PENDING", 409, "report is not SUBMITTED")

    report["status"] = "ACCEPTED"
    svc.touch(report)

    device = store.devices[report["device_id"]]
    conn = store.connections[device["service_connection_id"]]

    if report["result"] == "PASS":
        before = svc.begin(conn)
        device["last_pass_date"] = report["test_date"]
        device["next_test_due_date"] = svc.next_due_from(
            report["test_date"], device["test_interval_months"])
        svc.touch(device)
        if not svc.device_is_overdue(device):
            for n in store.notices.values():
                if (n["service_connection_id"] == conn["id"]
                        and n["status"] == "ISSUED" and n["reason"] == "OVERDUE_TEST"):
                    n["status"] = "RESCINDED"
                    svc.touch(n)
        svc.finish(conn, before)
    else:  # FAIL
        before = svc.begin(conn)
        device["status"] = "NEEDS_REPAIR"
        svc.touch(device)
        svc.create_notice(conn, "FAILED_TEST")
        svc.finish(conn, before, extra_increments=1)

    return object_response(serialize(report))


@bp.post("/test-reports/<rid>/reject")
def reject_report(rid):
    user_id, role = authenticate()
    require_role(role, {"UtilityAdmin"})
    report = lk.get_report(rid)
    if report["status"] != "SUBMITTED":
        raise ApiError("ERR_REPORT_NOT_PENDING", 409, "report is not SUBMITTED")
    body = v.json_object()
    reason = v.req_nonempty_str(body, "rejection_reason")
    report["status"] = "REJECTED"
    report["rejection_reason"] = reason
    svc.touch(report)
    return object_response(serialize(report))
