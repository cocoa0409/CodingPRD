"""Chain configuration: units, job roles, employees, assignments, policies."""

from flask import Blueprint

import cascades
from auth import authorize, ALL_ROLES
from calc import FEDERAL_CASH_WAGE_FLOOR_CENTS, FEDERAL_MIN_WAGE_CENTS
from envelope import object_response
from errors import ApiError, invalid
from serial import apply_filters, paged, view
import serial
from store import db, sort_key, stamp_new, touch
from validators import JOB_ROLE_CODE_RE, f, parse_body, parse_query

bp = Blueprint("config", __name__)

STATE_CODES = {"CA", "NY", "TX", "MA"}
CC_FEE_POLICIES = {"PROHIBITED", "ACTUAL_ONLY", "CAPPED_BPS"}
SERVICE_CHARGE_TREATMENTS = {"WAGES", "TIPS"}
TIP_STATUSES = {"TIPPED", "NON_TIPPED"}
POOL_TYPES = {"TIPPED_ONLY", "ALL_NON_MANAGEMENT"}
CONTRIBUTION_BASES = {"TIPS_RECEIVED_PCT", "GROSS_SALES_PCT"}
SHARE_BASES = {"POINTS_ONLY", "HOURS_WEIGHTED_POINTS"}
POLICY_STATUSES = {"DRAFT", "ACTIVE", "SUPERSEDED"}


def intervals_overlap(a_from, a_to, b_from, b_to):
    """Closed date intervals where a null upper bound means unbounded."""
    if a_to is not None and b_from > a_to:
        return False
    if b_to is not None and a_from > b_to:
        return False
    return True


# ---------------------------------------------------------------------------
# locations
# ---------------------------------------------------------------------------

LOCATION_SPEC = [
    f("name", "str", True, min_len=1, max_len=120),
    f("state_code", "enum", True, domain=STATE_CODES),
    f("state_min_wage_cents", "int", True, min=FEDERAL_MIN_WAGE_CENTS),
    f("cash_wage_cents", "int", True),
    f("tip_credit_enabled", "bool", False, default=False),
    f("cc_fee_policy", "enum", True, domain=CC_FEE_POLICIES),
    f("cc_fee_cap_bps", "int", False, min=0, max=1000),
    f("service_charge_treatment", "enum", True, domain=SERVICE_CHARGE_TREATMENTS),
]


@bp.post("/locations")
def create_location():
    authorize(["PayrollAdmin"])
    body, present = parse_body(LOCATION_SPEC)

    applicable = max(FEDERAL_MIN_WAGE_CENTS, body["state_min_wage_cents"])
    cash = body["cash_wage_cents"]
    enabled = bool(body["tip_credit_enabled"])

    # rung 28
    if enabled:
        if cash < FEDERAL_CASH_WAGE_FLOOR_CENTS or cash >= applicable:
            raise ApiError("ERR_CASH_WAGE_BELOW_FLOOR")
    else:
        if cash < FEDERAL_CASH_WAGE_FLOOR_CENTS or cash > applicable:
            raise ApiError("ERR_CASH_WAGE_BELOW_FLOOR")

    # rung 29
    cap = body["cc_fee_cap_bps"]
    if body["cc_fee_policy"] == "CAPPED_BPS":
        if "cc_fee_cap_bps" not in present or cap <= 0:
            raise ApiError("ERR_CC_FEE_CAP_REQUIRED")
    elif "cc_fee_cap_bps" in present:
        raise ApiError("ERR_CC_FEE_CAP_REQUIRED")

    record = {
        "name": body["name"],
        "state_code": body["state_code"],
        "state_min_wage_cents": body["state_min_wage_cents"],
        "cash_wage_cents": cash,
        "tip_credit_enabled": enabled,
        "cc_fee_policy": body["cc_fee_policy"],
        "cc_fee_cap_bps": cap if body["cc_fee_policy"] == "CAPPED_BPS" else None,
        "service_charge_treatment": body["service_charge_treatment"],
        "applicable_min_wage_cents": applicable,
        "max_tip_credit_per_hour_cents": (applicable - cash) if enabled else 0,
        "pending_pool_cents": 0,
    }
    stamp_new(record)
    db.locations[record["id"]] = record
    return object_response(view(record, serial.LOCATION), 201)


@bp.get("/locations/<location_id>")
def read_location(location_id):
    authorize(ALL_ROLES)
    record = db.locations.get(location_id)
    if record is None:
        raise ApiError("ERR_LOCATION_NOT_FOUND")
    return object_response(view(record, serial.LOCATION))


@bp.get("/locations")
def list_locations():
    authorize(ALL_ROLES)
    filters, limit, offset = parse_query(
        [f("state_code", "enum", domain=STATE_CODES)]
    )
    rows = apply_filters(cascades.rows("locations"), filters)
    return paged(rows, serial.LOCATION, limit, offset)


# ---------------------------------------------------------------------------
# job roles
# ---------------------------------------------------------------------------

JOB_ROLE_SPEC = [
    f("code", "str", True, min_len=2, max_len=40),
    f("title", "str", True),
    f("tip_status", "enum", True, domain=TIP_STATUSES),
    f("is_management", "bool", False, default=False),
    f("pool_contribution_pct_bps", "int", False, min=0, max=5000, default=0),
    f("pool_share_points", "int", False, min=0, max=100, default=0),
    f("side_work_eligible", "bool", False, default=False),
]


@bp.post("/job-roles")
def create_job_role():
    authorize(["PayrollAdmin"])
    body, _present = parse_body(JOB_ROLE_SPEC)
    if not JOB_ROLE_CODE_RE.match(body["code"]):
        raise invalid(
            "Field 'code' must be 2 to 40 characters of uppercase letters and underscores."
        )
    management = bool(body["is_management"])
    if management and (
        body["pool_contribution_pct_bps"] != 0 or body["pool_share_points"] != 0
    ):
        raise invalid(
            "A management job role must carry pool_contribution_pct_bps 0 and pool_share_points 0."
        )
    # rung 49
    for existing in db.job_roles.values():
        if existing["code"] == body["code"]:
            raise ApiError("ERR_DUPLICATE_JOB_ROLE_CODE")

    record = {
        "code": body["code"],
        "title": body["title"],
        "tip_status": body["tip_status"],
        "is_management": management,
        "pool_contribution_pct_bps": body["pool_contribution_pct_bps"],
        "pool_share_points": body["pool_share_points"],
        "side_work_eligible": bool(body["side_work_eligible"]),
    }
    stamp_new(record)
    db.job_roles[record["id"]] = record
    return object_response(view(record, serial.JOB_ROLE), 201)


@bp.get("/job-roles/<job_role_id>")
def read_job_role(job_role_id):
    authorize(ALL_ROLES)
    record = db.job_roles.get(job_role_id)
    if record is None:
        raise ApiError("ERR_RECORD_NOT_FOUND")
    return object_response(view(record, serial.JOB_ROLE))


@bp.get("/job-roles")
def list_job_roles():
    authorize(ALL_ROLES)
    filters, limit, offset = parse_query(
        [f("tip_status", "enum", domain=TIP_STATUSES), f("is_management", "bool")]
    )
    rows = apply_filters(cascades.rows("job_roles"), filters)
    return paged(rows, serial.JOB_ROLE, limit, offset)


# ---------------------------------------------------------------------------
# employees
# ---------------------------------------------------------------------------

EMPLOYEE_SPEC = [
    f("location_id", "id", True),
    f("full_name", "str", True),
    f("external_payroll_ref", "str", True),
    f("monthly_tip_baseline_cents", "int", False, min=0, default=0),
    f("separation_date", "date", False),
]


@bp.post("/employees")
def create_employee():
    authorize(["PayrollAdmin"])
    body, _present = parse_body(EMPLOYEE_SPEC)
    if body["location_id"] not in db.locations:
        raise ApiError("ERR_LOCATION_NOT_FOUND")
    record = {
        "location_id": body["location_id"],
        "full_name": body["full_name"],
        "external_payroll_ref": body["external_payroll_ref"],
        "monthly_tip_baseline_cents": body["monthly_tip_baseline_cents"],
        "separation_date": body["separation_date"],
        "trailing_pool_receipts_cents": 0,
    }
    stamp_new(record)
    db.employees[record["id"]] = record
    return object_response(view(record, serial.EMPLOYEE), 201)


@bp.get("/employees/<employee_id>")
def read_employee(employee_id):
    authorize(ALL_ROLES)
    record = db.employees.get(employee_id)
    if record is None:
        raise ApiError("ERR_EMPLOYEE_NOT_FOUND")
    return object_response(view(record, serial.EMPLOYEE))


@bp.get("/employees")
def list_employees():
    authorize(ALL_ROLES)
    filters, limit, offset = parse_query([f("location_id", "id")])
    rows = apply_filters(cascades.rows("employees"), filters)
    return paged(rows, serial.EMPLOYEE, limit, offset)


# ---------------------------------------------------------------------------
# role assignments
# ---------------------------------------------------------------------------

ASSIGNMENT_SPEC = [
    f("employee_id", "id", True),
    f("job_role_id", "id", True),
    f("effective_from", "date", True),
    f("effective_to", "date", False),
    f("tip_credit_notice_acknowledged_at", "instant", False),
    f("is_primary", "bool", False, default=False),
]


@bp.post("/role-assignments")
def create_role_assignment():
    authorize(["PayrollAdmin"])
    body, _present = parse_body(ASSIGNMENT_SPEC)
    if body["effective_to"] is not None and body["effective_to"] < body["effective_from"]:
        raise invalid("Field 'effective_to' may not be before 'effective_from'.")

    # rung 5, in the order the fields are declared on the entity
    employee = db.employees.get(body["employee_id"])
    if employee is None:
        raise ApiError("ERR_EMPLOYEE_NOT_FOUND")
    job_role = db.job_roles.get(body["job_role_id"])
    if job_role is None:
        raise ApiError("ERR_RECORD_NOT_FOUND")

    # rung 40
    for existing in cascades.rows("role_assignments"):
        if existing["employee_id"] != employee["id"]:
            continue
        if existing["job_role_id"] != job_role["id"]:
            continue
        if intervals_overlap(
            body["effective_from"],
            body["effective_to"],
            existing["effective_from"],
            existing["effective_to"],
        ):
            raise ApiError("ERR_ASSIGNMENT_OVERLAP")

    # rung 44
    if (
        employee["separation_date"] is not None
        and body["effective_from"] > employee["separation_date"]
    ):
        raise ApiError("ERR_EMPLOYEE_SEPARATED")

    record = {
        "employee_id": employee["id"],
        "job_role_id": job_role["id"],
        "effective_from": body["effective_from"],
        "effective_to": body["effective_to"],
        "tip_credit_notice_acknowledged_at": body["tip_credit_notice_acknowledged_at"],
        "is_primary": bool(body["is_primary"]),
        "dual_job": False,
    }
    stamp_new(record)
    db.role_assignments[record["id"]] = record

    # the dual-jobs doctrine: flip the flag on both sides of the overlap
    for other in cascades.rows("role_assignments"):
        if other["id"] == record["id"] or other["employee_id"] != employee["id"]:
            continue
        other_role = db.job_roles.get(other["job_role_id"])
        if other_role is None or other_role["tip_status"] == job_role["tip_status"]:
            continue
        if intervals_overlap(
            record["effective_from"],
            record["effective_to"],
            other["effective_from"],
            other["effective_to"],
        ):
            record["dual_job"] = True
            if not other["dual_job"]:
                other["dual_job"] = True
                touch(other)
    return object_response(view(record, serial.ROLE_ASSIGNMENT), 201)


@bp.get("/role-assignments/<role_assignment_id>")
def read_role_assignment(role_assignment_id):
    authorize(ALL_ROLES)
    record = db.role_assignments.get(role_assignment_id)
    if record is None:
        raise ApiError("ERR_RECORD_NOT_FOUND")
    return object_response(view(record, serial.ROLE_ASSIGNMENT))


@bp.get("/role-assignments")
def list_role_assignments():
    authorize(ALL_ROLES)
    filters, limit, offset = parse_query(
        [f("employee_id", "id"), f("job_role_id", "id")]
    )
    rows = apply_filters(cascades.rows("role_assignments"), filters)
    return paged(rows, serial.ROLE_ASSIGNMENT, limit, offset)


# ---------------------------------------------------------------------------
# tip-pool policies
# ---------------------------------------------------------------------------

POLICY_SPEC = [
    f("location_id", "id", True),
    f("pool_type", "enum", True, domain=POOL_TYPES),
    f("contribution_basis", "enum", True, domain=CONTRIBUTION_BASES),
    f("share_basis", "enum", True, domain=SHARE_BASES),
    f("cc_fee_pass_through", "bool", False, default=False),
]


@bp.post("/tip-pool-policies")
def create_policy():
    authorize(["PayrollAdmin"])
    body, _present = parse_body(POLICY_SPEC)
    if body["location_id"] not in db.locations:
        raise ApiError("ERR_LOCATION_NOT_FOUND")
    record = {
        "location_id": body["location_id"],
        "pool_type": body["pool_type"],
        "contribution_basis": body["contribution_basis"],
        "share_basis": body["share_basis"],
        "cc_fee_pass_through": bool(body["cc_fee_pass_through"]),
        "status": "DRAFT",
        "activated_at": None,
    }
    stamp_new(record)
    db.policies[record["id"]] = record
    return object_response(view(record, serial.POLICY), 201)


@bp.get("/tip-pool-policies/<policy_id>")
def read_policy(policy_id):
    authorize(ALL_ROLES)
    record = db.policies.get(policy_id)
    if record is None:
        raise ApiError("ERR_POLICY_NOT_FOUND")
    return object_response(view(record, serial.POLICY))


@bp.get("/tip-pool-policies")
def list_policies():
    authorize(ALL_ROLES)
    filters, limit, offset = parse_query(
        [f("location_id", "id"), f("status", "enum", domain=POLICY_STATUSES)]
    )
    rows = apply_filters(cascades.rows("policies"), filters)
    return paged(rows, serial.POLICY, limit, offset)


@bp.post("/tip-pool-policies/<policy_id>/activate")
def activate_policy(policy_id):
    authorize(["ComplianceOfficer"])
    body, _present = parse_body([f("expected_location_version", "int", True)])
    policy = db.policies.get(policy_id)
    if policy is None:
        raise ApiError("ERR_POLICY_NOT_FOUND")
    location = db.locations.get(policy["location_id"])
    if location is None:
        raise ApiError("ERR_LOCATION_NOT_FOUND")

    if policy["status"] != "DRAFT":                              # rung 11
        raise ApiError("ERR_POLICY_NOT_DRAFT")
    if body["expected_location_version"] != location["version"]:  # rung 23
        raise ApiError("ERR_STALE_LOCATION_VERSION")
    if policy["pool_type"] == "ALL_NON_MANAGEMENT" and location["tip_credit_enabled"]:
        raise ApiError("ERR_POOL_TYPE_REQUIRES_NO_TIP_CREDIT")    # rung 26
    if policy["cc_fee_pass_through"] and location["cc_fee_policy"] == "PROHIBITED":
        raise ApiError("ERR_CC_FEE_DEDUCTION_PROHIBITED")         # rung 27

    incumbents = [
        p
        for p in cascades.rows("policies")
        if p["location_id"] == location["id"]
        and p["status"] == "ACTIVE"
        and p["id"] != policy["id"]
    ]

    policy["status"] = "ACTIVE"
    policy["activated_at"] = db.now()
    touch(policy)

    for incumbent in incumbents:
        incumbent["status"] = "SUPERSEDED"
        touch(incumbent)
        for pool in cascades.rows("pools"):
            if (
                pool["tip_pool_policy_id"] == incumbent["id"]
                and pool["contribution_status"] == "CONTRIBUTED"
                and pool["distribution_status"] == "PENDING"
            ):
                cascades.reverse_pool(pool)

    cascades.recompute_location_pending(location)
    location["version"] = location["version"] + 1
    location["updated_at"] = db.now()
    return object_response(view(policy, serial.POLICY))


# ---------------------------------------------------------------------------
# the logical clock
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    authorize(["PayrollAdmin"])
    body, _present = parse_body([f("current_utc", "instant", True)])
    db.set_clock(body["current_utc"])
    return object_response({})
