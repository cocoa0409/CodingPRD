"""Mileage reports (PRD 3.5, 3.8)."""
from flask import Blueprint, g, request

import domain
import settlement_service
from calc import month_bounds
from envelope import ok, ok_list
from errors import ApiError, invalid_state, not_found
from http_util import get_body, parse_pagination, require_roles, v_int, v_month, v_str
from store import db, new_entity, touch

bp_mileage = Blueprint("mileage", __name__)

READ_ROLES = (
    "SystemAdmin", "LeaseAdmin", "FleetPlanner", "BillingAnalyst",
    "ComplianceOfficer", "LesseeRep",
)


def _load_report(report_id):
    r = db.reports.get(report_id)
    if r is None:
        raise not_found("ERR_REPORT_NOT_FOUND", f"Mileage report {report_id} not found")
    return r


def _owner_lessee_id(report):
    a = db.assignments.get(report["lease_assignment_id"])
    return domain.lessee_id_of_assignment(a) if a else None


@bp_mileage.route("/mileage-reports", methods=["POST"])
@require_roles("LesseeRep")
def create_report():
    body = get_body()
    railcar_id = v_str(body, "railcar_id")
    assignment_id = v_str(body, "lease_assignment_id")
    month = v_month(body, "report_month")
    loaded = v_int(body, "loaded_miles", min=0)
    empty = v_int(body, "empty_miles", min=0)

    car = db.railcars.get(railcar_id)
    if car is None:
        raise not_found("ERR_RAILCAR_NOT_FOUND", f"Railcar {railcar_id} not found")
    assignment = db.assignments.get(assignment_id)
    if assignment is None:
        raise not_found("ERR_ASSIGNMENT_NOT_FOUND", f"Lease assignment {assignment_id} not found")

    # priority 3: ownership — the report's assignment must belong to the caller's lessee
    domain.check_lessee_ownership(domain.lessee_id_of_assignment(assignment))

    # priority 10: report_month must be a month the assignment was on lease
    on = assignment["actual_on_lease_date"]
    off = assignment["actual_off_lease_date"]
    first, last = month_bounds(month)
    on_lease_that_month = on is not None and last >= on and (off is None or first < off)
    if not on_lease_that_month:
        raise ApiError(
            "ERR_REPORT_MONTH_MISMATCH", 422,
            "report_month is not a month the assignment was on lease",
        )

    # priority 11: one non-DISPUTED report per (railcar, report_month)
    for r in db.reports.values():
        if (
            r["railcar_id"] == railcar_id
            and r["report_month"] == month
            and r["status"] != "DISPUTED"
        ):
            raise ApiError(
                "ERR_DUPLICATE_REPORT_MONTH", 409,
                "A non-DISPUTED report already exists for this railcar and month",
            )

    report = new_entity(
        {
            "railcar_id": railcar_id,
            "lease_assignment_id": assignment_id,
            "report_month": month,
            "loaded_miles": loaded,
            "empty_miles": empty,
            "validated_loaded_miles": None,
            "validated_empty_miles": None,
            "status": "SUBMITTED",
        }
    )
    db.reports[report["id"]] = report
    return ok(domain.serialize_report(report), status=201)


@bp_mileage.route("/mileage-reports", methods=["GET"])
@require_roles(*READ_ROLES)
def list_reports():
    limit, offset = parse_pagination()
    items = sorted(db.reports.values(), key=lambda r: (r["created_at"], r["_created_seq"]))
    if g.user_role == "LesseeRep":
        items = [r for r in items if _owner_lessee_id(r) == g.user_id]
    railcar_id = request.args.get("railcar_id")
    assignment_id = request.args.get("lease_assignment_id")
    month = request.args.get("report_month")
    status = request.args.get("status")
    if railcar_id is not None:
        items = [r for r in items if r["railcar_id"] == railcar_id]
    if assignment_id is not None:
        items = [r for r in items if r["lease_assignment_id"] == assignment_id]
    if month is not None:
        items = [r for r in items if r["report_month"] == month]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([domain.serialize_report(r) for r in page], limit, offset, total)


@bp_mileage.route("/mileage-reports/<report_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_report(report_id):
    r = _load_report(report_id)
    domain.check_lessee_ownership(_owner_lessee_id(r))
    return ok(domain.serialize_report(r))


@bp_mileage.route("/mileage-reports/<report_id>/validate", methods=["POST"])
@require_roles("BillingAnalyst")
def validate_report(report_id):
    r = _load_report(report_id)
    body = get_body()
    corr_loaded = v_int(body, "validated_loaded_miles", required=False, min=0)
    corr_empty = v_int(body, "validated_empty_miles", required=False, min=0)
    if r["status"] != "SUBMITTED":
        raise invalid_state(f"Mileage report in status {r['status']} cannot be validated")

    prev_counted = (r["validated_loaded_miles"] or 0) + (r["validated_empty_miles"] or 0)
    new_loaded = corr_loaded if corr_loaded is not None else r["loaded_miles"]
    new_empty = corr_empty if corr_empty is not None else r["empty_miles"]
    r["validated_loaded_miles"] = new_loaded
    r["validated_empty_miles"] = new_empty
    r["status"] = "VALIDATED"
    touch(r)

    # calc_cumulative_miles_conservation: contribute only the delta
    car = db.railcars.get(r["railcar_id"])
    if car is not None:
        car["cumulative_miles"] += (new_loaded + new_empty) - prev_counted
        touch(car)

    # recompute every PROVISIONAL statement for (assignment, report_month)
    for s in db.statements.values():
        if (
            s["lease_assignment_id"] == r["lease_assignment_id"]
            and s["statement_month"] == r["report_month"]
            and s["status"] == "PROVISIONAL"
        ):
            settlement_service.apply_provisional(s)
            touch(s)
    return ok(domain.serialize_report(r))


@bp_mileage.route("/mileage-reports/<report_id>/dispute", methods=["POST"])
@require_roles("BillingAnalyst")
def dispute_report(report_id):
    r = _load_report(report_id)
    body = get_body()
    v_str(body, "reason")
    if r["status"] != "VALIDATED":
        raise invalid_state(f"Mileage report in status {r['status']} cannot be disputed")
    r["status"] = "DISPUTED"
    touch(r)
    return ok(domain.serialize_report(r))


@bp_mileage.route("/mileage-reports/<report_id>/resubmit", methods=["POST"])
@require_roles("LesseeRep")
def resubmit_report(report_id):
    r = _load_report(report_id)
    domain.check_lessee_ownership(_owner_lessee_id(r))
    body = get_body()
    loaded = v_int(body, "loaded_miles", min=0)
    empty = v_int(body, "empty_miles", min=0)
    if r["status"] != "DISPUTED":
        raise invalid_state(f"Mileage report in status {r['status']} cannot be resubmitted")
    r["loaded_miles"] = loaded
    r["empty_miles"] = empty
    # validated_* deliberately retained until a fresh validation lands
    r["status"] = "SUBMITTED"
    touch(r)
    return ok(domain.serialize_report(r))
