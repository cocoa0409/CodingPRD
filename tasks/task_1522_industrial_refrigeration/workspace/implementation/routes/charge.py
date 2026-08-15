"""Charge ledger: append-only postings, per-line rounding, solvency guard,
OCC on Facility.version, and the threshold-crossing cascade (PRD 2.6, 3.2)."""
from flask import Blueprint

import calc
import envelope
from errors import ApiError
from guards import (
    ALL_ROLES,
    apply_filters,
    body_row,
    endpoint,
    occ,
    operator_employee,
    opt_present,
    paginate,
    pagination,
    path_row,
    req_enum,
    req_number,
    req_string,
)
from serialize import adjustment_out
from store import db, sorted_rows, touch
from util import add_days, round_tenth, ZERO

bp = Blueprint("charge", __name__)

CREATE_SCHEMA = (
    frozenset(
        [
            "facility_id",
            "system_id",
            "adjustment_type",
            "quantity_lbs",
            "reason",
            "expected_facility_version",
        ]
    ),
    frozenset(
        ["facility_id", "adjustment_type", "quantity_lbs", "reason", "expected_facility_version"]
    ),
)

AUTO_AUDIT_DUE_DAYS = 1095


@bp.post("/psm/charge-adjustments")
@endpoint(["Operator"], schema=CREATE_SCHEMA)
def post_adjustment(ctx):
    # step 0 -- payload values
    adjustment_type = req_enum(ctx.body, "adjustment_type")
    quantity = req_number(ctx.body, "quantity_lbs")
    reason = req_string(ctx.body, "reason")
    # step 2 -- entity-backed identity: Operator X-User-ID is an Employee.id
    employee = operator_employee(ctx)
    # step 3 -- existence
    facility = body_row(ctx.body, "facilities", "facility_id")
    system = None
    if opt_present(ctx.body, "system_id"):
        system = body_row(ctx.body, "systems", "system_id")
    # step 4 -- OCC on Facility.version
    occ(ctx, "expected_facility_version", facility)
    # step 9 -- cross-facility referential integrity
    if system is not None and system["facility_id"] != facility["id"]:
        raise ApiError("ERR_CROSS_FACILITY_REFERENCE")
    # step 10 -- fiscal: positive quantity, then ledger solvency
    if quantity <= ZERO:
        raise ApiError("ERR_QUANTITY_NOT_POSITIVE")
    rounded = round_tenth(quantity)  # per-line rounding pinned at posting
    prior_total = calc.book_total(facility["id"])
    if adjustment_type == "REMOVE" and prior_total - rounded < ZERO:
        raise ApiError("ERR_CHARGE_NEGATIVE")
    prior_posture = calc.charge_posture(prior_total, facility["threshold_lbs"])

    row = db.create(
        "charge_adjustments",
        {
            "facility_id": facility["id"],
            "system_id": system["id"] if system else None,
            "adjustment_type": adjustment_type,
            "quantity_lbs": quantity,
            "rounded_lbs": rounded,
            "reason": reason,
            "posted_by_employee_id": employee["id"],
        },
        common=False,  # append-only event: id + created_at only
    )
    # every successful posting increments Facility.version by exactly 1
    touch(facility)

    # threshold cascade (PRD 3.2): BELOW -> AT_OR_ABOVE flips psm_program_status
    # (sticky) and auto-creates an AUTO_THRESHOLD audit due +1095 days.
    new_total = prior_total + rounded if adjustment_type == "ADD" else prior_total - rounded
    new_posture = calc.charge_posture(new_total, facility["threshold_lbs"])
    if prior_posture == "BELOW_THRESHOLD" and new_posture == "AT_OR_ABOVE_THRESHOLD":
        facility["psm_program_status"] = "REQUIRED"
        crossing_at = db.now()
        db.create(
            "compliance_audits",
            {
                "facility_id": facility["id"],
                "scheduled_start_at": crossing_at,
                "due_at": add_days(crossing_at, AUTO_AUDIT_DUE_DAYS),
                "lead_auditor": None,
                "origin": "AUTO_THRESHOLD",
                "status": "SCHEDULED",
                "findings_count": None,
            },
        )
    return envelope.created(adjustment_out(row))


@bp.get("/psm/charge-adjustments/<adjustment_id>")
@endpoint(ALL_ROLES)
def get_adjustment(ctx, adjustment_id):
    return envelope.ok(adjustment_out(path_row("charge_adjustments", adjustment_id)))


@bp.get("/psm/charge-adjustments")
@endpoint(ALL_ROLES)
def list_adjustments(ctx):
    limit, offset = pagination(ctx)
    rows = sorted_rows(db.charge_adjustments.values())
    rows = apply_filters(
        rows,
        ctx,
        [
            ("facility_id", "facility_id", None),
            ("system_id", "system_id", None),
            ("posted_by_employee_id", "posted_by_employee_id", None),
            ("adjustment_type", "adjustment_type", ("ADD", "REMOVE")),
        ],
    )
    total = len(rows)
    return envelope.listing(
        [adjustment_out(r) for r in paginate(rows, limit, offset)], limit, offset, total
    )
