from flask import Blueprint

from db import DB, stamp_new, touch
from errors import ERR_REPORT_ALREADY_EXISTS, invalid_state, not_found, raise_err, validation
from middleware import (
    as_array,
    as_enum,
    as_number,
    as_string,
    authenticate,
    get_json_body,
    require_customer_ownership,
    require_roles,
)
from response import success_list, success_object
from routes.repair_orders import get_ro_or_404

bp = Blueprint("inspection_reports", __name__)

RECOMMENDED_ACTIONS = ["REPAIR", "REPLACE", "RETURN_UNREPAIRED"]


@bp.route("/repair-orders/<rid>/inspection-reports", methods=["POST"])
def create_report(rid):
    caller = authenticate()
    body = get_json_body()
    require_roles(caller, ["Inspector"])
    ro = get_ro_or_404(rid)
    findings_summary = as_string(body, "findings_summary")
    recommended_action = as_enum(body, "recommended_action", RECOMMENDED_ACTIONS)
    estimated_labor_hours = as_number(body, "estimated_labor_hours")
    part_lines = as_array(body, "part_lines")
    for line in part_lines:
        if not isinstance(line, dict):
            validation("part_lines entries must be objects")
        if not isinstance(line.get("part_id"), str):
            validation("part_lines entries require part_id")
        qty = line.get("quantity")
        if isinstance(qty, bool) or not isinstance(qty, (int, float)) or qty <= 0:
            validation("part_lines entries require a positive quantity")

    if ro["status"] != "IN_INSPECTION":
        invalid_state("Repair order is not in IN_INSPECTION")
    for existing in DB.inspection_reports.values():
        if existing["repair_order_id"] == ro["id"]:
            raise_err(ERR_REPORT_ALREADY_EXISTS, "This repair order already has an inspection report")

    report = stamp_new(
        {
            "repair_order_id": ro["id"],
            "findings_summary": findings_summary,
            "recommended_action": recommended_action,
            "estimated_labor_hours": estimated_labor_hours,
            "part_lines": part_lines,
            "report_status": "DRAFT",
            "inspector_id": caller.user_id,
        }
    )
    DB.inspection_reports[report["id"]] = report
    return success_object(report, status=201)


@bp.route("/repair-orders/<rid>/inspection-reports", methods=["GET"])
def list_reports(rid):
    caller = authenticate()
    ro = get_ro_or_404(rid)
    require_customer_ownership(caller, ro["customer_id"])
    items = sorted(
        (r for r in DB.inspection_reports.values() if r["repair_order_id"] == ro["id"]),
        key=lambda r: (r["created_at"], r["id"]),
    )
    return success_list(items, limit=len(items) if items else 10, offset=0, total_count=len(items))


@bp.route("/inspection-reports/<iid>/finalize", methods=["POST"])
def finalize_report(iid):
    caller = authenticate()
    get_json_body()
    require_roles(caller, ["Inspector"])
    report = DB.inspection_reports.get(iid)
    if report is None:
        not_found("Inspection report not found")
    if report["report_status"] != "DRAFT":
        invalid_state("Inspection report is already FINALIZED")
    ro = DB.repair_orders.get(report["repair_order_id"])
    if ro is None:
        not_found("Repair order not found")
    if ro["status"] != "IN_INSPECTION":
        invalid_state("Repair order is not in IN_INSPECTION")
    report["report_status"] = "FINALIZED"
    touch(report)
    ro["status"] = "QUOTE_IN_PROGRESS"
    touch(ro)
    return success_object(report)
