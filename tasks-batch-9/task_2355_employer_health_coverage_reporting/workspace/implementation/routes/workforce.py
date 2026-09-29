"""Measurement cycles, employees, hours records, employment events, offers."""

from flask import Blueprint

import calc
import lookups as lk
import sync
from auth import READ_ROLES, READ_ROLES_WITH_EMPLOYEE, require_roles
from db import insert, rows, touch
from envelope import created, created_collection, ok
from errors import fail
from guards import listing, single_read
from shapes import (
    body,
    bool_field,
    date_field,
    digits_field,
    enum_field,
    forbid,
    int_field,
    month_list_field,
    order_dates,
    string_field,
    to_date,
)

bp = Blueprint("workforce", __name__)

EMPLOYMENT_TYPES = ("FULL_TIME", "PART_TIME", "VARIABLE_HOUR", "SEASONAL")
LEAVE_TYPES = ("FMLA", "USERRA", "JURY_DUTY", "UNPAID_OTHER")
EVENT_TYPES = ("TERMINATION", "LEAVE_START", "LEAVE_END", "TRANSFER", "REHIRE")
METHODS = ("LOOK_BACK", "MONTHLY")
OFFER_KINDS = (
    "NO_OFFER",
    "MEC_NO_MV",
    "MEC_MV_SELF_ONLY",
    "MEC_MV_SELF_SPOUSE",
    "MEC_MV_SELF_DEP",
    "MEC_MV_FAMILY",
    "MEC_MV_FAMILY_CONDITIONAL_SPOUSE",
    "COBRA_TERMINATED",
    "RETIREE_COVERAGE",
)


# --------------------------------------------------------------------------- #
# MeasurementCycle
# --------------------------------------------------------------------------- #
@bp.post("/measurement-cycles")
def create_cycle():
    require_roles("ComplianceOfficer", "BenefitsAdmin")
    data = body()
    group_member_id = string_field(data, "group_member_id")
    cycle_type = enum_field(data, "cycle_type", ("STANDARD", "INITIAL"))
    measurement_start_date = date_field(data, "measurement_start_date")
    measurement_end_date = date_field(data, "measurement_end_date")
    admin_period_end_date = date_field(data, "admin_period_end_date")
    stability_start_date = date_field(data, "stability_start_date")
    stability_end_date = date_field(data, "stability_end_date")
    employee_id = string_field(data, "employee_id", required=(cycle_type == "INITIAL"))
    if cycle_type == "STANDARD":
        forbid(data, "employee_id", "employee_id is not allowed on a STANDARD cycle.")
    threshold = int_field(
        data, "hours_threshold_monthly", required=False, default=130, minimum=0
    )

    order_dates(
        measurement_start_date,
        measurement_end_date,
        False,
        "measurement_end_date must be on or after measurement_start_date.",
    )
    order_dates(
        measurement_end_date,
        admin_period_end_date,
        False,
        "admin_period_end_date must be on or after measurement_end_date.",
    )
    order_dates(
        admin_period_end_date,
        stability_start_date,
        True,
        "stability_start_date must be strictly after admin_period_end_date.",
    )
    order_dates(
        stability_start_date,
        stability_end_date,
        False,
        "stability_end_date must be on or after stability_start_date.",
    )

    member = lk.find("group_members", group_member_id)
    employee = None
    if employee_id is not None:
        employee = lk.find("employees", employee_id)
        if employee["group_member_id"] != member["id"]:
            fail("ERR_SCOPE_MISMATCH", "That employee does not belong to the named member.")

    new_start = to_date(stability_start_date)
    new_end = to_date(stability_end_date)
    for existing in rows("measurement_cycles"):
        if employee_id is not None:
            same_scope = existing.get("employee_id") == employee_id
        else:
            same_scope = (
                existing.get("employee_id") is None
                and existing["group_member_id"] == group_member_id
            )
        if not same_scope:
            continue
        if new_start <= to_date(existing["stability_end_date"]) and new_end >= to_date(
            existing["stability_start_date"]
        ):
            fail("ERR_STABILITY_PERIOD_OVERLAP", "That stability period overlaps an existing one.")

    record = insert(
        "measurement_cycles",
        {
            "group_member_id": group_member_id,
            "employee_id": employee_id,
            "cycle_type": cycle_type,
            "measurement_start_date": measurement_start_date,
            "measurement_end_date": measurement_end_date,
            "admin_period_end_date": admin_period_end_date,
            "stability_start_date": stability_start_date,
            "stability_end_date": stability_end_date,
            "hours_threshold_monthly": threshold,
        },
    )
    return created(record)


@bp.get("/measurement-cycles")
def list_cycles():
    return listing(
        "measurement_cycles",
        {
            "group_member_id": ("group_member_id", "str"),
            "employee_id": ("employee_id", "str"),
            "cycle_type": ("cycle_type", "str"),
        },
        READ_ROLES,
    )


@bp.get("/measurement-cycles/<identifier>")
def read_cycle(identifier):
    return single_read("measurement_cycles", identifier, READ_ROLES)


# --------------------------------------------------------------------------- #
# Employee
# --------------------------------------------------------------------------- #
@bp.post("/employees")
def create_employee():
    require_roles("BenefitsAdmin")
    data = body()
    group_member_id = string_field(data, "group_member_id")
    full_name = string_field(data, "full_name")
    ssn_last4 = digits_field(data, "ssn_last4", 4)
    hire_date = date_field(data, "hire_date")
    employment_type = enum_field(data, "employment_type", EMPLOYMENT_TYPES)
    is_hourly = bool_field(data, "is_hourly")
    hourly_rate_cents = int_field(
        data, "hourly_rate_cents", required=bool(is_hourly), minimum=0
    )
    monthly_salary_cents = int_field(
        data, "monthly_salary_cents", required=not is_hourly, minimum=0
    )
    w2 = int_field(data, "w2_box1_wages_cents", required=False, default=0, minimum=0)
    override = enum_field(data, "measurement_method_override", METHODS, required=False)

    member = lk.find("group_members", group_member_id)
    record = insert(
        "employees",
        {
            "group_member_id": group_member_id,
            "full_name": full_name,
            "ssn_last4": ssn_last4,
            "hire_date": hire_date,
            "termination_date": None,
            "employment_type": employment_type,
            "employment_status": "ACTIVE",
            "open_leave_type": None,
            "is_hourly": is_hourly,
            "hourly_rate_cents": hourly_rate_cents,
            "monthly_salary_cents": monthly_salary_cents,
            "w2_box1_wages_cents": w2,
            "measurement_method_override": override,
            "effective_measurement_method": override or member["measurement_method"],
            "full_time_months": [],
            "full_time_month_count": 0,
            "measured_average_hours": None,
            "ft_source_by_month": [],
            "last_recomputed_at": None,
        },
    )
    return created(record)


@bp.get("/employees")
def list_employees():
    return listing(
        "employees",
        {
            "group_member_id": ("group_member_id", "str"),
            "employment_status": ("employment_status", "str"),
        },
        READ_ROLES,
    )


@bp.get("/employees/<identifier>")
def read_employee(identifier):
    return single_read("employees", identifier, READ_ROLES_WITH_EMPLOYEE)


@bp.patch("/employees/<employee_id>")
def update_employee(employee_id):
    require_roles("BenefitsAdmin")
    data = body()
    w2 = int_field(data, "w2_box1_wages_cents", required=False, minimum=0)
    hourly = int_field(data, "hourly_rate_cents", required=False, minimum=0)
    salary = int_field(data, "monthly_salary_cents", required=False, minimum=0)
    override_given = "measurement_method_override" in data
    override = enum_field(data, "measurement_method_override", METHODS, required=False)

    employee = lk.find("employees", employee_id)
    if w2 is not None:
        employee["w2_box1_wages_cents"] = w2
    if hourly is not None:
        employee["hourly_rate_cents"] = hourly
    if salary is not None:
        employee["monthly_salary_cents"] = salary
    if override_given:
        employee["measurement_method_override"] = override
    touch(employee)
    sync.resolve_effective_method(employee)
    return ok(employee)


@bp.post("/employees/<employee_id>/full-time-recompute")
def recompute_employee(employee_id):
    require_roles("BenefitsAdmin", "Preparer")
    body()
    employee = lk.find("employees", employee_id)
    season = lk.season_of_employee(employee)
    if season is None:
        fail("ERR_FILING_SEASON_NOT_FOUND", "No filing season governs this employee.")

    forms = lk.forms_of_employee(employee)
    latest = max(forms, key=lambda f: f["_seq"]) if forms else None
    if latest is not None and not lk.is_live(latest):
        fail("ERR_FORM_VOIDED", "The statement this recompute would refresh is voided.")

    sync.resolve_effective_method(employee)
    full_time, sources, average = calc.full_time_determination(employee, season)
    sync.write_employee_full_time(employee, full_time, sources, average)
    form = lk.live_form(employee)
    if form is not None:
        sync.refresh_lines_from_recompute(form, full_time, sources)
    return ok(employee)


# --------------------------------------------------------------------------- #
# HoursRecord
# --------------------------------------------------------------------------- #
@bp.post("/hours-records")
def create_hours():
    require_roles("BenefitsAdmin")
    data = body()
    employee_id = string_field(data, "employee_id")
    measurement_year = int_field(data, "measurement_year", minimum=0)
    months = month_list_field(data, "months")
    hours_of_service = int_field(data, "hours_of_service", minimum=0)
    paid_leave_hours = int_field(data, "paid_leave_hours", required=False, default=0, minimum=0)
    special = int_field(
        data, "special_unpaid_leave_hours", required=False, default=0, minimum=0
    )

    employee = lk.find("employees", employee_id)
    taken = set(
        row["month"]
        for row in lk.hours_of_employee(employee)
        if row["measurement_year"] == measurement_year
    )
    seen = set()
    for month in months:
        if month in taken or month in seen:
            fail("ERR_DUPLICATE_HOURS_MONTH", "An hours row already exists for month %d." % month)
        seen.add(month)

    created_rows = []
    for month in sorted(months):
        created_rows.append(
            insert(
                "hours_records",
                {
                    "employee_id": employee_id,
                    "measurement_year": measurement_year,
                    "month": month,
                    "hours_of_service": hours_of_service,
                    "paid_leave_hours": paid_leave_hours,
                    "special_unpaid_leave_hours": special,
                    "counted_hours": hours_of_service + paid_leave_hours,
                    "excluded_from_denominator": special >= calc.MONTHLY_FT_HOURS_THRESHOLD,
                },
            )
        )
    return created_collection(created_rows)


@bp.get("/hours-records")
def list_hours():
    return listing(
        "hours_records",
        {
            "employee_id": ("employee_id", "str"),
            "measurement_year": ("measurement_year", "int"),
            "month": ("month", "int"),
        },
        READ_ROLES,
    )


@bp.get("/hours-records/<identifier>")
def read_hours(identifier):
    return single_read("hours_records", identifier, READ_ROLES)


# --------------------------------------------------------------------------- #
# EmploymentEvent
# --------------------------------------------------------------------------- #
@bp.post("/employment-events")
def create_event():
    user_id, _role = require_roles("BenefitsAdmin")
    data = body()
    employee_id = string_field(data, "employee_id")
    event_type = enum_field(data, "event_type", EVENT_TYPES)
    effective_date = date_field(data, "effective_date")
    leave_type = enum_field(
        data, "leave_type", LEAVE_TYPES, required=(event_type == "LEAVE_START")
    )
    if event_type != "LEAVE_START":
        forbid(data, "leave_type", "leave_type is only allowed on LEAVE_START.")
    to_group_member_id = string_field(
        data, "to_group_member_id", required=(event_type == "TRANSFER")
    )
    if event_type != "TRANSFER":
        forbid(data, "to_group_member_id", "to_group_member_id is only allowed on TRANSFER.")
    note = string_field(data, "note", required=False)

    employee = lk.find("employees", employee_id)
    target = None
    if to_group_member_id is not None:
        target = lk.find("group_members", to_group_member_id)
        current = lk.member_of_employee(employee)
        if current is None or target["controlled_group_id"] != current["controlled_group_id"]:
            fail("ERR_SCOPE_MISMATCH", "The destination member is in another controlled group.")

    status = employee["employment_status"]
    allowed = {
        "LEAVE_START": ("ACTIVE",),
        "LEAVE_END": ("ON_LEAVE",),
        "TRANSFER": ("ACTIVE",),
        "TERMINATION": ("ACTIVE", "ON_LEAVE"),
        "REHIRE": ("TERMINATED",),
    }[event_type]
    if status not in allowed:
        fail(
            "ERR_EMPLOYMENT_EVENT_NOT_APPLICABLE",
            "%s is not a declared transition out of %s." % (event_type, status),
        )
    if event_type in ("LEAVE_START", "TERMINATION"):
        if to_date(effective_date) < to_date(employee["hire_date"]):
            fail(
                "ERR_EMPLOYMENT_EVENT_NOT_APPLICABLE",
                "effective_date must be on or after the hire date.",
            )
    if event_type == "REHIRE":
        if employee.get("termination_date") is None or to_date(effective_date) <= to_date(
            employee["termination_date"]
        ):
            fail(
                "ERR_EMPLOYMENT_EVENT_NOT_APPLICABLE",
                "effective_date must be strictly after the termination date.",
            )
    if event_type == "TRANSFER":
        if target["id"] == employee["group_member_id"] or target["member_status"] != "ACTIVE":
            fail("ERR_TRANSFER_TARGET_INVALID", "The destination member is not a valid target.")

    if event_type == "LEAVE_START":
        employee["employment_status"] = "ON_LEAVE"
        employee["open_leave_type"] = leave_type
        touch(employee)
    elif event_type == "LEAVE_END":
        employee["employment_status"] = "ACTIVE"
        employee["open_leave_type"] = None
        touch(employee)
        sync.leave_end_cascade(employee)
    elif event_type == "TRANSFER":
        employee["group_member_id"] = target["id"]
        touch(employee)
        sync.resolve_effective_method(employee)
        sync.transfer_cascade(employee, effective_date)
    elif event_type == "TERMINATION":
        employee["employment_status"] = "TERMINATED"
        employee["termination_date"] = effective_date
        employee["open_leave_type"] = None
        touch(employee)
        sync.termination_cascade(employee, effective_date)
    else:  # REHIRE
        break_days = (to_date(effective_date) - to_date(employee["termination_date"])).days
        if break_days >= calc.REHIRE_BREAK_DAYS:
            employee["hire_date"] = effective_date
        employee["termination_date"] = None
        employee["employment_status"] = "ACTIVE"
        touch(employee)

    record = insert(
        "employment_events",
        {
            "employee_id": employee_id,
            "event_type": event_type,
            "effective_date": effective_date,
            "leave_type": leave_type,
            "to_group_member_id": to_group_member_id,
            "note": note,
            "resulting_status": employee["employment_status"],
            "recorded_by_user_id": user_id,
        },
    )
    return created(record)


@bp.get("/employment-events")
def list_events():
    return listing(
        "employment_events",
        {
            "employee_id": ("employee_id", "str"),
            "to_group_member_id": ("to_group_member_id", "str"),
            "event_type": ("event_type", "str"),
        },
        READ_ROLES,
    )


@bp.get("/employment-events/<identifier>")
def read_event(identifier):
    return single_read("employment_events", identifier, READ_ROLES)


# --------------------------------------------------------------------------- #
# CoverageOffer
# --------------------------------------------------------------------------- #
@bp.post("/coverage-offers")
def create_offer():
    require_roles("BenefitsAdmin")
    data = body()
    employee_id = string_field(data, "employee_id")
    offer_kind = enum_field(data, "offer_kind", OFFER_KINDS)
    minimum_value = bool_field(data, "minimum_value")
    lowest_cost = int_field(data, "lowest_cost_self_only_cents", minimum=0)
    start = date_field(data, "effective_start_date")
    end = date_field(data, "effective_end_date")
    offers_spouse = bool_field(data, "offers_spouse", required=False, default=False)
    offers_dependents = bool_field(data, "offers_dependents", required=False, default=False)
    conditional = bool_field(data, "conditional_spouse_offer", required=False, default=False)
    enrolled = bool_field(data, "enrolled", required=False, default=False)
    order_dates(
        start, end, True, "effective_end_date must be strictly after effective_start_date."
    )

    employee = lk.find("employees", employee_id)
    new_start = to_date(start)
    new_end = to_date(end)
    for existing in lk.offers_of_employee(employee):
        if new_start < to_date(existing["effective_end_date"]) and new_end > to_date(
            existing["effective_start_date"]
        ):
            fail("ERR_COVERAGE_OFFER_OVERLAP", "That interval overlaps an existing offer.")

    season = lk.season_of_employee(employee)
    tax_year = season["tax_year"] if season else new_start.year
    record = insert(
        "coverage_offers",
        {
            "employee_id": employee_id,
            "offer_kind": offer_kind,
            "minimum_value": minimum_value,
            "lowest_cost_self_only_cents": lowest_cost,
            "offers_spouse": offers_spouse,
            "offers_dependents": offers_dependents,
            "conditional_spouse_offer": conditional,
            "enrolled": enrolled,
            "effective_start_date": start,
            "effective_end_date": end,
            "covered_months": calc.covered_months_for(start, end, tax_year),
        },
    )
    return created(record)


@bp.get("/coverage-offers")
def list_offers():
    return listing("coverage_offers", {"employee_id": ("employee_id", "str")}, READ_ROLES)


@bp.get("/coverage-offers/<identifier>")
def read_offer(identifier):
    return single_read("coverage_offers", identifier, READ_ROLES)
