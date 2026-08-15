"""Lease assignments (PRD 3.4, 3.6): placement gates, tariff pinning,
delivery, return, settlement."""
from datetime import timedelta

from flask import Blueprint, request

import domain
from calc import proration
from envelope import ok, ok_list
from errors import ApiError, invalid_state, not_found
from http_util import COMMODITIES, get_body, parse_pagination, require_roles, v_date, v_enum, v_str
from store import db, new_entity, next_seq, today, touch

bp_assignments = Blueprint("assignments", __name__)

LIST_ROLES = (
    "SystemAdmin", "LeaseAdmin", "FleetPlanner", "MaintenanceController",
    "BillingAnalyst", "ComplianceOfficer",
)
READ_ROLES = LIST_ROLES + ("LesseeRep",)


def _load_assignment(assignment_id):
    a = db.assignments.get(assignment_id)
    if a is None:
        raise not_found("ERR_ASSIGNMENT_NOT_FOUND", f"Lease assignment {assignment_id} not found")
    return a


def _certified_bridge_exists(car, planned):
    """A CERTIFIED cleaning created after the car's last return bridging
    last_commodity -> planned_commodity (PRD 2.10)."""
    for c in db.cleanings.values():
        if (
            c["railcar_id"] == car["id"]
            and c["status"] == "CERTIFIED"
            and c["prior_commodity"] == car["last_commodity"]
            and c["next_commodity"] == planned
            and c["_created_seq"] > car.get("_last_return_seq", 0)
        ):
            return True
    return False


@bp_assignments.route("/lease-assignments", methods=["POST"])
@require_roles("FleetPlanner")
def create_assignment():
    body = get_body()
    lease_id = v_str(body, "lease_id")
    railcar_id = v_str(body, "railcar_id")
    planned = v_enum(body, "planned_commodity", COMMODITIES)
    start = v_date(body, "scheduled_start")
    end = v_date(body, "scheduled_end")

    # existence of body foreign keys
    lease = domain.load_lease(lease_id)  # applies lazy EXPIRED evaluation
    car = db.railcars.get(railcar_id)
    if car is None:
        raise not_found("ERR_RAILCAR_NOT_FOUND", f"Railcar {railcar_id} not found")

    # priority 7: cross-entity state gates
    if lease["status"] != "ACTIVE":
        raise ApiError("ERR_LEASE_NOT_ACTIVE", 409, "Lease is not ACTIVE")
    lessee = db.lessees.get(lease["lessee_id"])
    if lessee is None or lessee["status"] != "ACTIVE":
        raise ApiError("ERR_LESSEE_NOT_ACTIVE", 409, "Lessee is not ACTIVE")
    if car["status"] != "AVAILABLE":
        raise ApiError("ERR_RAILCAR_NOT_AVAILABLE", 409, "Railcar is not AVAILABLE")

    # priority 8: fleet safety gates (age, posture, commodity) in this order
    if domain.car_age(car) >= 50:
        raise ApiError(
            "ERR_AGE_LIMIT_EXCEEDED", 422,
            f"Car age {domain.car_age(car)} meets or exceeds the 50-year interchange limit",
        )
    domain.recompute_posture(car)
    if car["compliance_posture"] == "NON_COMPLIANT":
        raise ApiError(
            "ERR_TANK_CAR_NONCOMPLIANT", 422,
            "Railcar compliance_posture is NON_COMPLIANT",
        )
    commodity_change = planned != car["last_commodity"] and car["last_commodity"] != "NONE"
    if commodity_change and not _certified_bridge_exists(car, planned):
        raise ApiError(
            "ERR_COMMODITY_INCOMPATIBLE", 422,
            "Commodity change without a CERTIFIED cleaning since the car's last return",
        )

    # priority 9: tariff coverage at scheduled_start (pinned snapshot)
    hire = domain.tariff_at(car["car_type"], "CAR_HIRE_BASE", start)
    credit = domain.tariff_at(car["car_type"], "MILEAGE_CREDIT", start)
    if hire is None or credit is None:
        raise ApiError(
            "ERR_TARIFF_NOT_FOUND", 422,
            "No CAR_HIRE_BASE or MILEAGE_CREDIT tariff covering scheduled_start for this car type",
        )

    # priority 10: temporal sanity
    if end < start:
        raise ApiError(
            "ERR_INVALID_DATE_RANGE", 422,
            "scheduled_end must be on or after scheduled_start",
        )
    if start < lease["start_date"] or end > lease["end_date"]:
        raise ApiError(
            "ERR_OUTSIDE_LEASE_TERM", 422,
            "Assignment window falls outside the lease term",
        )
    for other in db.assignments.values():
        if other["railcar_id"] != car["id"] or other["status"] not in (
            "SCHEDULED", "ON_LEASE", "RETURNED",
        ):
            continue
        if start <= other["scheduled_end"] and other["scheduled_start"] <= end:
            raise ApiError(
                "ERR_ASSIGNMENT_OVERLAP", 422,
                "Window overlaps another SCHEDULED/ON_LEASE/RETURNED assignment on this railcar",
            )
    if commodity_change:
        earlier = [
            a
            for a in db.assignments.values()
            if a["railcar_id"] == car["id"]
            and a["status"] in ("SCHEDULED", "ON_LEASE", "RETURNED", "SETTLED")
            and a["scheduled_end"] <= start
        ]
        if earlier:
            prev = max(earlier, key=lambda a: (a["scheduled_end"], a["_created_seq"]))
            if start < prev["scheduled_end"] + timedelta(days=3):
                raise ApiError(
                    "ERR_CLEANING_BUFFER_VIOLATION", 422,
                    "Commodity change requires scheduled_start >= previous scheduled_end + 3 days",
                )

    # priority 12: fiscal gate
    if lessee["outstanding_balance_cents"] > lessee["credit_limit_cents"]:
        raise ApiError(
            "ERR_CREDIT_LIMIT_EXCEEDED", 422,
            "Lessee outstanding balance exceeds its credit limit",
        )

    assignment = new_entity(
        {
            "lease_id": lease_id,
            "railcar_id": railcar_id,
            "planned_commodity": planned,
            "scheduled_start": start,
            "scheduled_end": end,
            "actual_on_lease_date": None,
            "actual_off_lease_date": None,
            "pinned_car_hire_daily_cents": hire["unit_rate_cents"],
            "pinned_mileage_credit_cents": credit["unit_rate_cents"],
            "billable_days": None,
            "final_rent_cents": None,
            "termination_fee_cents": None,
            "cancellation_reason": None,
            "status": "SCHEDULED",
        }
    )
    db.assignments[assignment["id"]] = assignment
    return ok(domain.serialize_assignment(assignment), status=201)


@bp_assignments.route("/lease-assignments", methods=["GET"])
@require_roles(*LIST_ROLES)
def list_assignments():
    limit, offset = parse_pagination()
    items = sorted(db.assignments.values(), key=lambda a: (a["created_at"], a["_created_seq"]))
    lease_id = request.args.get("lease_id")
    railcar_id = request.args.get("railcar_id")
    status = request.args.get("status")
    if lease_id is not None:
        items = [a for a in items if a["lease_id"] == lease_id]
    if railcar_id is not None:
        items = [a for a in items if a["railcar_id"] == railcar_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([domain.serialize_assignment(a) for a in page], limit, offset, total)


@bp_assignments.route("/lease-assignments/<assignment_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_assignment(assignment_id):
    a = _load_assignment(assignment_id)
    domain.check_lessee_ownership(domain.lessee_id_of_assignment(a))
    return ok(domain.serialize_assignment(a))


@bp_assignments.route("/lease-assignments/<assignment_id>/deliver", methods=["POST"])
@require_roles("FleetPlanner")
def deliver_assignment(assignment_id):
    a = _load_assignment(assignment_id)
    if a["status"] != "SCHEDULED":
        raise invalid_state(f"Assignment in status {a['status']} cannot be delivered")
    car = db.railcars.get(a["railcar_id"])
    if car is None or car["status"] != "AVAILABLE":
        raise ApiError("ERR_RAILCAR_NOT_AVAILABLE", 409, "Railcar is not AVAILABLE")
    a["status"] = "ON_LEASE"
    a["actual_on_lease_date"] = today()
    touch(a)
    car["status"] = "ON_LEASE"
    touch(car)
    return ok(domain.serialize_assignment(a))


@bp_assignments.route("/lease-assignments/<assignment_id>/return", methods=["POST"])
@require_roles("FleetPlanner")
def return_assignment(assignment_id):
    a = _load_assignment(assignment_id)
    if a["status"] != "ON_LEASE":
        raise invalid_state(f"Assignment in status {a['status']} cannot be returned")
    car = db.railcars.get(a["railcar_id"])
    if car is None or car["status"] != "ON_LEASE":
        raise ApiError(
            "ERR_RAILCAR_NOT_AVAILABLE", 409,
            "Railcar is not ON_LEASE (it may still be IN_SHOP)",
        )
    a["status"] = "RETURNED"
    a["actual_off_lease_date"] = today()
    touch(a)
    car["status"] = "AVAILABLE"
    car["last_commodity"] = a["planned_commodity"]
    touch(car)
    car["_last_return_seq"] = next_seq()
    # cascade: open the damage-inspection loop with a DRAFT assessment
    assessment = new_entity(
        {
            "lease_assignment_id": a["id"],
            "railcar_id": car["id"],
            "line_items": None,
            "total_assessed_cents": None,
            "lessee_liable_cents": None,
            "status": "DRAFT",
        }
    )
    db.assessments[assessment["id"]] = assessment
    return ok(domain.serialize_assignment(a))


@bp_assignments.route("/lease-assignments/<assignment_id>/settle", methods=["POST"])
@require_roles("BillingAnalyst")
def settle_assignment(assignment_id):
    a = _load_assignment(assignment_id)
    if a["status"] != "RETURNED":
        raise ApiError(
            "ERR_ASSIGNMENT_NOT_RETURNED", 409,
            "Settle requires the assignment to be RETURNED",
        )
    open_repairs = [
        r
        for r in db.repairs.values()
        if r["lease_assignment_id"] == a["id"]
        and r["status"] in ("UNDER_REVIEW", "REVISION_REQUESTED", "APPROVED", "IN_PROGRESS")
    ]
    if open_repairs:
        raise ApiError(
            "ERR_OPEN_REPAIR_ORDERS", 409,
            "A repair authorization on this assignment is still open",
        )
    assessments = [
        d for d in db.assessments.values() if d["lease_assignment_id"] == a["id"]
    ]
    if any(d["status"] not in ("FINALIZED", "INVOICED", "PAID") for d in assessments):
        raise ApiError(
            "ERR_DAMAGE_ASSESSMENT_OPEN", 409,
            "A damage assessment on this assignment is still DRAFT, SUBMITTED, or DISPUTED",
        )
    if any(d["status"] == "INVOICED" for d in assessments):
        raise ApiError(
            "ERR_OUTSTANDING_BALANCE", 422,
            "An INVOICED-but-unpaid damage assessment blocks settle",
        )
    lease = domain.load_lease(a["lease_id"])
    shop_repairs = [
        r
        for r in db.repairs.values()
        if r["lease_assignment_id"] == a["id"]
        and r["status"] == "COMPLETED"
        and r["requires_shop"] is True
    ]
    billable, rent, fee = proration(a, shop_repairs, lease, lease["early_termination_fee_cents"])
    a["billable_days"] = billable
    a["final_rent_cents"] = rent
    a["termination_fee_cents"] = fee
    a["status"] = "SETTLED"
    touch(a)
    lessee = db.lessees.get(lease["lessee_id"])
    if lessee is not None:
        domain.balance_add(lessee, rent + fee)
    return ok(domain.serialize_assignment(a))


@bp_assignments.route("/lease-assignments/<assignment_id>/cancel", methods=["POST"])
@require_roles("FleetPlanner")
def cancel_assignment(assignment_id):
    a = _load_assignment(assignment_id)
    if a["status"] != "SCHEDULED":
        raise invalid_state(f"Assignment in status {a['status']} cannot be cancelled")
    a["status"] = "CANCELLED"
    a["cancellation_reason"] = "LESSEE_REQUEST"
    touch(a)
    return ok(domain.serialize_assignment(a))
