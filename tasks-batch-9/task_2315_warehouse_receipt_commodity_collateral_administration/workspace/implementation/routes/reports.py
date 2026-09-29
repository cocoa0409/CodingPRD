"""Position reports: drafting, submission and examination (§3.7)."""

from flask import Blueprint

import calc
import model
from core import (authenticate, body, fail, invalid, new_row, now_iso, opt_str,
                  req_date, req_enum, req_int, req_str, respond_object, store,
                  touch)
from listing import list_response

bp = Blueprint("reports", __name__)

READ_ROLES = ("StateRegulator", "WarehouseOperator")
RESULTS = ("PASS", "DEFICIENT", "CRITICAL")


@bp.post("/position-reports")
def create_report():
    caller = authenticate(("WarehouseOperator",))
    data = body()

    raw_warehouse = data.get("warehouse_id")
    if isinstance(raw_warehouse, str) and raw_warehouse != caller.user_id:
        model.not_owner()

    warehouse_id = req_str(data, "warehouse_id")
    period_start = req_date(data, "period_start_date")
    period_end = req_date(data, "period_end_date")
    as_of = req_date(data, "as_of_date")
    if period_end < period_start:
        invalid("period_end_date", "must not precede period_start_date")
    if as_of < period_start or as_of > period_end:
        invalid("as_of_date", "must fall inside the reporting period")

    model.get_warehouse(warehouse_id)
    if warehouse_id != caller.user_id:
        model.not_owner()

    for other in model.warehouse_reports(warehouse_id):
        if other["report_state"] not in ("DRAFT", "UNDER_EXAMINATION",
                                        "ACCEPTED"):
            continue
        if (period_start <= other["_period_end"]
                and other["_period_start"] <= period_end):
            fail("ERR_REPORT_PERIOD_OVERLAP", 409)

    row = new_row()
    row.update({
        "warehouse_id": warehouse_id,
        "period_start_date": period_start.isoformat(),
        "period_end_date": period_end.isoformat(),
        "as_of_date": as_of.isoformat(),
        "_period_start": period_start,
        "_period_end": period_end,
        "reported_physical_bushels": None,
        "reported_obligation_bushels": None,
        "obligation_bushels": None,
        "system_physical_bushels": None,
        "sound_physical_bushels": None,
        "position_variance_bushels": None,
        "count_discrepancy_bushels": None,
        "obligation_misstatement_bushels": None,
        "examination_tolerance_bushels": None,
        "examination_required": None,
        "report_state": "DRAFT",
        "revision_count": 0,
        "examination_result": None,
        "examined_by_user_id": None,
        "findings_note": None,
        "submitted_at": None,
    })
    store.reports[row["id"]] = row
    return respond_object(model.report_out(row), 201)


@bp.get("/position-reports")
def list_reports():
    authenticate(READ_ROLES)
    return list_response(list(store.reports.values()),
                         ("warehouse_id", "report_state", "examination_result"),
                         model.report_out)


@bp.get("/position-reports/<report_id>")
def read_report(report_id):
    caller = authenticate(READ_ROLES)
    report = model.get_report(report_id)
    model.require_operator_warehouse(caller, report["warehouse_id"])
    return respond_object(model.report_out(report))


@bp.post("/position-reports/<report_id>/submit")
def submit_report(report_id):
    caller = authenticate(("WarehouseOperator",))
    report = model.get_report(report_id)
    model.require_operator_warehouse(caller, report["warehouse_id"])
    data = body()
    reported_physical = req_int(data, "reported_physical_bushels", minimum=0)
    reported_obligation = req_int(data, "reported_obligation_bushels", minimum=0)

    state = report["report_state"]
    if state not in ("DRAFT", "REJECTED"):
        fail("ERR_INVALID_STATE", 409)

    warehouse_id = report["warehouse_id"]
    obligation = model.obligation_bushels(warehouse_id)
    system_physical = model.system_physical_bushels(warehouse_id)
    sound_physical = model.sound_physical_bushels(warehouse_id)
    variance = sound_physical - obligation
    count_discrepancy = reported_physical - system_physical
    misstatement = reported_obligation - obligation
    tolerance = calc.examination_tolerance(obligation)
    required = (abs(variance) > tolerance or abs(count_discrepancy) > tolerance
                or abs(misstatement) > tolerance)

    if required:
        for other in model.warehouse_reports(warehouse_id):
            if (other["id"] != report_id
                    and other["report_state"] == "UNDER_EXAMINATION"):
                fail("ERR_INVALID_STATE", 409)

    report.update({
        "reported_physical_bushels": reported_physical,
        "reported_obligation_bushels": reported_obligation,
        "obligation_bushels": obligation,
        "system_physical_bushels": system_physical,
        "sound_physical_bushels": sound_physical,
        "position_variance_bushels": variance,
        "count_discrepancy_bushels": count_discrepancy,
        "obligation_misstatement_bushels": misstatement,
        "examination_tolerance_bushels": tolerance,
        "examination_required": required,
        "submitted_at": now_iso(),
    })
    if state == "REJECTED":
        report["revision_count"] = report["revision_count"] + 1
    if required:
        report["report_state"] = "UNDER_EXAMINATION"
        report["examination_result"] = None
        report["examined_by_user_id"] = None
        report["findings_note"] = None
    else:
        report["report_state"] = "ACCEPTED"
        report["examination_result"] = "PASS"
        report["examined_by_user_id"] = None
        report["findings_note"] = None
    touch(report)
    return respond_object(model.report_out(report))


@bp.post("/position-reports/<report_id>/examine")
def examine_report(report_id):
    caller = authenticate(("StateRegulator",))
    report = model.get_report(report_id)
    warehouse = store.warehouses[report["warehouse_id"]]

    if (warehouse["licensed_by_user_id"] is not None
            and caller.user_id == warehouse["licensed_by_user_id"]):
        fail("ERR_SEGREGATION_OF_DUTIES", 403)

    data = body()
    result = req_enum(data, "result", RESULTS)
    findings = opt_str(data, "findings_note")

    if report["report_state"] != "UNDER_EXAMINATION":
        fail("ERR_INVALID_STATE", 409)

    report["examination_result"] = result
    report["examined_by_user_id"] = caller.user_id
    report["findings_note"] = findings
    report["report_state"] = "ACCEPTED" if result == "PASS" else "REJECTED"
    touch(report)

    if result == "CRITICAL":
        if warehouse["license_state"] == "LICENSED":
            warehouse["license_state"] = "SUSPENDED"
        model.reject_weighed_tickets(warehouse["id"], "LICENSE_SUSPENDED")
        touch(warehouse)
    elif result == "DEFICIENT":
        touch(warehouse)

    return respond_object(model.report_out(report))
