"""Worked shifts, their closing and declaration, and service-charge events."""

from flask import Blueprint

import calc
import cascades
import serial
from auth import ALL_ROLES, authorize, check_shift_scope, scope_shifts
from envelope import object_response
from errors import ApiError, invalid
from serial import apply_filters, paged, view
from store import db, day_of, fmt_date, instant, parse_instant, stamp_new, touch
from validators import f, parse_body, parse_query

bp = Blueprint("shifts", __name__)

TIME_STATUSES = {"OPEN", "CLOSED", "VOIDED"}
DECLARATION_STATUSES = {"UNDECLARED", "DECLARED", "AMENDED"}
CHARGE_STATUSES = {"RECORDED", "ALLOCATED", "VOIDED"}
TREATMENTS = {"WAGES", "TIPS"}


def find_assignment(employee_id, job_role_id, business_date):
    """The assignment of that employee and role whose interval holds the day."""
    for row in cascades.rows("role_assignments"):
        if row["employee_id"] != employee_id or row["job_role_id"] != job_role_id:
            continue
        if row["effective_from"] > business_date:
            continue
        if row["effective_to"] is not None and row["effective_to"] < business_date:
            continue
        return row
    return None


def next_day(business_date):
    from datetime import timedelta

    return (parse_instant(business_date) + timedelta(days=1)).strftime(
        "%Y-%m-%dT00:00:00.000Z"
    )


# ---------------------------------------------------------------------------
# POST /shifts
# ---------------------------------------------------------------------------

SHIFT_SPEC = [
    f("employee_id", "id", True),
    f("location_id", "id", True),
    f("job_role_id", "id", True),
    f("pay_period_id", "id", True),
    f("business_date", "date", True),
    f("start_at", "instant", True),
    f("end_at", "instant", True),
    f("side_work_minutes", "int", False, min=0, default=0),
    f("max_continuous_side_work_minutes", "int", False, min=0, default=0),
    f("gross_sales_cents", "int", False, min=0, default=0),
    f("charged_sales_cents", "int", False, min=0, default=0),
    f("cc_processing_fee_bps", "int", False, min=0, max=1000, default=0),
]


@bp.post("/shifts")
def create_shift():
    authorize(["ShiftManager", "PayrollPreparer"])
    body, _present = parse_body(SHIFT_SPEC)
    start = instant(body["start_at"])
    end = instant(body["end_at"])
    if end <= start:
        raise invalid("Field 'end_at' must be strictly after 'start_at'.")
    scheduled_minutes = int((end - start).total_seconds() // 60)

    # rung 5, in entity declaration order
    employee = db.employees.get(body["employee_id"])
    if employee is None:
        raise ApiError("ERR_EMPLOYEE_NOT_FOUND")
    location = db.locations.get(body["location_id"])
    if location is None:
        raise ApiError("ERR_LOCATION_NOT_FOUND")
    job_role = db.job_roles.get(body["job_role_id"])
    if job_role is None:
        raise ApiError("ERR_RECORD_NOT_FOUND")
    period = db.pay_periods.get(body["pay_period_id"])
    if period is None:
        raise ApiError("ERR_PAY_PERIOD_NOT_FOUND")

    if period["status"] != "OPEN":                                   # rung 12
        raise ApiError("ERR_PAY_PERIOD_NOT_OPEN")

    if body["side_work_minutes"] > 0 and not job_role["side_work_eligible"]:
        raise ApiError("ERR_SIDE_WORK_NOT_ELIGIBLE")                 # rung 30

    if find_assignment(                                              # rung 31
        employee["id"], job_role["id"], body["business_date"]
    ) is None:
        raise ApiError("ERR_NO_ACTIVE_ROLE_ASSIGNMENT")

    if (                                                             # rung 32
        location["id"] != employee["location_id"]
        or location["id"] != period["location_id"]
    ):
        raise ApiError("ERR_EMPLOYEE_LOCATION_MISMATCH")

    for other in cascades.rows("shifts"):                            # rung 38
        if other["employee_id"] != employee["id"]:
            continue
        if other["time_status"] == "VOIDED":
            continue
        if start < instant(other["end_at"]) and instant(other["start_at"]) < end:
            raise ApiError("ERR_SHIFT_OVERLAP")

    clock = instant(db.now())
    if day_of(body["business_date"]) > day_of(db.now()) or end > clock:  # rung 41
        raise ApiError("ERR_SHIFT_FUTURE_DATE")

    if not cascades.date_in_period(period, body["business_date"]):   # rung 42
        raise ApiError("ERR_BUSINESS_DATE_OUT_OF_PERIOD")
    permitted = (body["business_date"], next_day(body["business_date"]))
    for stamp in (body["start_at"], body["end_at"]):
        if fmt_date(day_of(stamp)) not in permitted:
            raise ApiError("ERR_BUSINESS_DATE_OUT_OF_PERIOD")

    if (                                                             # rung 44
        employee["separation_date"] is not None
        and body["business_date"] > employee["separation_date"]
    ):
        raise ApiError("ERR_EMPLOYEE_SEPARATED")

    if (                                                             # rung 45
        body["side_work_minutes"] > scheduled_minutes
        or body["max_continuous_side_work_minutes"] > body["side_work_minutes"]
    ):
        raise ApiError("ERR_SIDE_WORK_EXCEEDS_SHIFT")

    if body["charged_sales_cents"] > body["gross_sales_cents"]:      # rung 51
        raise ApiError("ERR_CHARGED_SALES_EXCEED_GROSS_SALES")

    record = {
        "employee_id": employee["id"],
        "location_id": location["id"],
        "job_role_id": job_role["id"],
        "pay_period_id": period["id"],
        "shift_tip_pool_id": None,
        "business_date": body["business_date"],
        "start_at": body["start_at"],
        "end_at": body["end_at"],
        "scheduled_minutes": scheduled_minutes,
        "side_work_minutes": body["side_work_minutes"],
        "max_continuous_side_work_minutes": body["max_continuous_side_work_minutes"],
        "non_tip_credit_minutes": 0,
        "tip_credit_eligible_minutes": 0,
        "gross_sales_cents": body["gross_sales_cents"],
        "charged_sales_cents": body["charged_sales_cents"],
        "cc_processing_fee_bps": body["cc_processing_fee_bps"],
        "declared_cash_tips_cents": 0,
        "declared_charged_tips_cents": 0,
        "declaration_count": 0,
        "time_status": "OPEN",
        "declaration_status": "UNDECLARED",
        "pool_contribution_cents": 0,
        "retained_tips_cents": 0,
        "shift_tip_credit_cents": 0,
    }
    stamp_new(record)
    db.shifts[record["id"]] = record
    return object_response(view(record, serial.SHIFT), 201)


@bp.get("/shifts/<shift_id>")
def read_shift(shift_id):
    actor = authorize(ALL_ROLES)
    record = db.shifts.get(shift_id)
    if record is None:
        raise ApiError("ERR_SHIFT_NOT_FOUND")
    check_shift_scope(actor, record)
    return object_response(view(record, serial.SHIFT))


@bp.get("/shifts")
def list_shifts():
    actor = authorize(ALL_ROLES)
    filters, limit, offset = parse_query(
        [
            f("employee_id", "id"),
            f("location_id", "id"),
            f("job_role_id", "id"),
            f("pay_period_id", "id"),
            f("shift_tip_pool_id", "id"),
            f("business_date", "date"),
            f("time_status", "enum", domain=TIME_STATUSES),
            f("declaration_status", "enum", domain=DECLARATION_STATUSES),
        ]
    )
    rows = apply_filters(cascades.rows("shifts"), filters)
    rows = scope_shifts(actor, rows)
    return paged(rows, serial.SHIFT, limit, offset)


# ---------------------------------------------------------------------------
# close, declare-tips, void
# ---------------------------------------------------------------------------

@bp.post("/shifts/<shift_id>/close")
def close_shift(shift_id):
    authorize(["ShiftManager", "PayrollPreparer"])
    parse_body([])
    shift = db.shifts.get(shift_id)
    if shift is None:
        raise ApiError("ERR_SHIFT_NOT_FOUND")

    if shift["time_status"] != "OPEN":                                # rung 8
        raise ApiError("ERR_SHIFT_NOT_OPEN")
    period = db.pay_periods.get(shift["pay_period_id"])
    if period is None or period["status"] != "OPEN":                  # rung 12
        raise ApiError("ERR_PAY_PERIOD_NOT_OPEN")

    location = db.locations.get(shift["location_id"])
    job_role = db.job_roles.get(shift["job_role_id"])
    assignment = find_assignment(
        shift["employee_id"], shift["job_role_id"], shift["business_date"]
    )
    non_credit, eligible = calc.side_work_classification(
        shift, job_role, assignment, location
    )
    shift["non_tip_credit_minutes"] = non_credit
    shift["tip_credit_eligible_minutes"] = eligible
    shift["time_status"] = "CLOSED"
    touch(shift)
    cascades.recompute_period_shift_rollups(period)
    return object_response(view(shift, serial.SHIFT))


DECLARE_SPEC = [
    f("declared_cash_tips_cents", "int", True, min=0),
    f("declared_charged_tips_cents", "int", True, min=0),
]


@bp.post("/shifts/<shift_id>/declare-tips")
def declare_tips(shift_id):
    actor = authorize(["Employee", "ShiftManager"])
    body, _present = parse_body(DECLARE_SPEC)
    shift = db.shifts.get(shift_id)
    if shift is None:
        raise ApiError("ERR_SHIFT_NOT_FOUND")

    check_shift_scope(actor, shift)                                   # rung 6
    if shift["time_status"] != "CLOSED":                              # rung 9
        raise ApiError("ERR_SHIFT_NOT_CLOSED")
    if shift["shift_tip_pool_id"] is not None:                        # rung 10
        raise ApiError("ERR_SHIFT_ALREADY_POOLED")
    period = db.pay_periods.get(shift["pay_period_id"])
    if period is None or period["status"] != "OPEN":                   # rung 12
        raise ApiError("ERR_PAY_PERIOD_NOT_OPEN")
    if body["declared_charged_tips_cents"] > shift["charged_sales_cents"]:
        raise ApiError("ERR_DECLARED_CHARGED_TIPS_EXCEED_CHARGED_SALES")  # rung 50

    shift["declared_cash_tips_cents"] = body["declared_cash_tips_cents"]
    shift["declared_charged_tips_cents"] = body["declared_charged_tips_cents"]
    shift["declaration_count"] = shift["declaration_count"] + 1
    shift["declaration_status"] = (
        "DECLARED" if shift["declaration_status"] == "UNDECLARED" else "AMENDED"
    )
    shift["retained_tips_cents"] = (
        shift["declared_cash_tips_cents"]
        + shift["declared_charged_tips_cents"]
        - shift["pool_contribution_cents"]
    )
    touch(shift)
    return object_response(view(shift, serial.SHIFT))


@bp.post("/shifts/<shift_id>/void")
def void_shift(shift_id):
    authorize(["PayrollPreparer"])
    parse_body([f("reason", "str")])
    shift = db.shifts.get(shift_id)
    if shift is None:
        raise ApiError("ERR_SHIFT_NOT_FOUND")

    pool_id = shift["shift_tip_pool_id"]                              # rung 10
    if pool_id is not None:
        pool = db.pools.get(pool_id)
        if pool is None or pool["contribution_status"] != "REVERSED":
            raise ApiError("ERR_SHIFT_ALREADY_POOLED")

    was_closed = shift["time_status"] == "CLOSED"
    shift["time_status"] = "VOIDED"
    shift["non_tip_credit_minutes"] = 0
    shift["tip_credit_eligible_minutes"] = 0
    shift["retained_tips_cents"] = 0
    touch(shift)

    period = db.pay_periods.get(shift["pay_period_id"])
    if period is not None:
        if was_closed and period["status"] in ("COMPUTED", "APPROVED"):
            cascades.server_reopen(period)
        else:
            cascades.recompute_period_shift_rollups(period)
    return object_response(view(shift, serial.SHIFT))


# ---------------------------------------------------------------------------
# service-charge events
# ---------------------------------------------------------------------------

CHARGE_SPEC = [
    f("location_id", "id", True),
    f("business_date", "date", True),
    f("amount_cents", "int", True, min=0),
    f("description", "str", False),
    f("treatment_override", "enum", False, domain=TREATMENTS),
]


@bp.post("/service-charges")
def create_service_charge():
    authorize(["PayrollPreparer", "ShiftManager"])
    body, _present = parse_body(CHARGE_SPEC)

    location = db.locations.get(body["location_id"])                  # rung 5
    if location is None:
        raise ApiError("ERR_LOCATION_NOT_FOUND")

    if day_of(body["business_date"]) > day_of(db.now()):              # rung 41
        raise ApiError("ERR_SHIFT_FUTURE_DATE")
    if body["amount_cents"] <= 0:                                     # rung 51
        raise ApiError("ERR_CHARGED_SALES_EXCEED_GROSS_SALES")

    record = {
        "location_id": location["id"],
        "allocated_pool_id": None,
        "allocated_pay_period_id": None,
        "business_date": body["business_date"],
        "amount_cents": body["amount_cents"],
        "description": body["description"],
        "treatment_override": body["treatment_override"],
        "treatment": body["treatment_override"]
        or location["service_charge_treatment"],
        "status": "RECORDED",
    }
    stamp_new(record)
    db.service_charges[record["id"]] = record
    return object_response(view(record, serial.SERVICE_CHARGE), 201)


@bp.get("/service-charges/<service_charge_id>")
def read_service_charge(service_charge_id):
    authorize(ALL_ROLES)
    record = db.service_charges.get(service_charge_id)
    if record is None:
        raise ApiError("ERR_RECORD_NOT_FOUND")
    return object_response(view(record, serial.SERVICE_CHARGE))


@bp.get("/service-charges")
def list_service_charges():
    authorize(ALL_ROLES)
    filters, limit, offset = parse_query(
        [
            f("location_id", "id"),
            f("allocated_pool_id", "id"),
            f("allocated_pay_period_id", "id"),
            f("business_date", "date"),
            f("status", "enum", domain=CHARGE_STATUSES),
            f("treatment", "enum", domain=TREATMENTS),
        ]
    )
    rows = apply_filters(cascades.rows("service_charges"), filters)
    return paged(rows, serial.SERVICE_CHARGE, limit, offset)


@bp.post("/service-charges/<service_charge_id>/void")
def void_service_charge(service_charge_id):
    authorize(["PayrollPreparer"])
    parse_body([f("reason", "str")])
    charge = db.service_charges.get(service_charge_id)
    if charge is None:
        raise ApiError("ERR_RECORD_NOT_FOUND")

    pool = db.pools.get(charge["allocated_pool_id"]) if charge["allocated_pool_id"] else None
    if charge["allocated_pool_id"] is not None:
        if pool is None or pool["distribution_status"] != "PENDING":
            raise ApiError("ERR_POOL_ALREADY_DISTRIBUTED")

    was_allocated = charge["status"] == "ALLOCATED"
    period = db.pay_periods.get(charge["allocated_pay_period_id"] or "")

    charge["status"] = "VOIDED"
    charge["allocated_pool_id"] = None
    charge["allocated_pay_period_id"] = None
    touch(charge)

    if was_allocated:
        if pool is not None:
            pool["service_charge_tips_cents"] -= charge["amount_cents"]
            pool["net_pool_cents"] -= charge["amount_cents"]
            touch(pool)
            location = db.locations.get(pool["location_id"])
            if location is not None:
                cascades.recompute_location_pending(location)
        if period is not None:
            cascades.invalidate_period(period)
    return object_response(view(charge, serial.SERVICE_CHARGE))
