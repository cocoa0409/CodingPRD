"""Clock, appropriations, students, schools, rate schedules and routes (3.1)."""
from flask import Blueprint, g

from cascades import run_lapse_sweep
from common import (
    APPROVAL_STATUSES,
    CLIENT_APPROVAL_STATES,
    DISABILITY_CATEGORIES,
    LRE_SETTINGS,
    account_or_404,
    collection,
    route_or_404,
    schedule_or_404,
    school_or_404,
    single,
    student_or_404,
)
from errors import fail
from middleware import (
    ALL_ROLES,
    FISCAL_OFFICER,
    PARENT_GUARDIAN,
    PLACEMENT_COORDINATOR,
    SYSTEM_ADMIN,
    endpoint,
)
from response import created, ok
from store import db, new_row, now_iso, parse_datetime, public, touch
from validation import (
    get_bool,
    get_cents,
    get_date,
    get_enum,
    get_id,
    get_instant,
    get_int,
    get_str,
    q_bool,
    q_int,
    q_str,
    read_body,
)

clock_bp = Blueprint("clock", __name__)
bp = Blueprint("reference", __name__)


# =========================================================================
# logical clock
# =========================================================================

@endpoint(clock_bp, "POST", "/_clock/set_current_utc", (SYSTEM_ADMIN,))
def set_current_utc():
    body = read_body(("current_utc",))
    instant = get_instant(body, "current_utc")
    db.clock = instant
    run_lapse_sweep()
    return ok({"current_utc": now_iso()})


# =========================================================================
# district fiscal accounts
# =========================================================================

@endpoint(bp, "GET", "/fiscal-accounts", ALL_ROLES)
def list_fiscal_accounts():
    return collection(db.accounts.values(), [("fiscal_year", q_int("fiscal_year"))])


@endpoint(bp, "POST", "/fiscal-accounts", (FISCAL_OFFICER, SYSTEM_ADMIN))
def create_fiscal_account():
    body = read_body(("fiscal_year", "account_code", "authorized_cents"))
    fiscal_year = get_int(body, "fiscal_year", minimum=2020, maximum=2100)
    account_code = get_str(body, "account_code")
    authorized = get_cents(body, "authorized_cents", minimum=0)
    for existing in db.accounts.values():
        if existing["account_code"] == account_code:
            fail("ERR_DUPLICATE_RESOURCE", "account_code is already in use.")
    row = new_row("account", {
        "fiscal_year": fiscal_year,
        "account_code": account_code,
        "authorized_cents": authorized,
        "available_cents": authorized,
        "encumbered_cents": 0,
        "disbursed_cents": 0,
    })
    db.accounts[row["id"]] = row
    return created(public(row))


@endpoint(bp, "GET", "/fiscal-accounts/<account_id>", ALL_ROLES)
def get_fiscal_account(account_id):
    return single(account_or_404(account_id))


# =========================================================================
# students
# =========================================================================

@endpoint(bp, "GET", "/students", ALL_ROLES)
def list_students():
    return collection(db.students.values(), [("high_cost_flag", q_bool("high_cost_flag"))])


@endpoint(bp, "POST", "/students", (PLACEMENT_COORDINATOR, SYSTEM_ADMIN))
def create_student():
    body = read_body((
        "state_student_id", "full_name", "district_of_residence", "disability_category",
        "iep_effective_date", "lre_current_setting", "medicaid_eligible",
        "medicaid_consent_on_file",
    ))
    state_student_id = get_str(body, "state_student_id", min_len=1, max_len=32)
    full_name = get_str(body, "full_name")
    district = get_str(body, "district_of_residence")
    category = get_enum(body, "disability_category", DISABILITY_CATEGORIES)
    iep_date = get_date(body, "iep_effective_date")
    setting = get_enum(body, "lre_current_setting", LRE_SETTINGS)
    medicaid_eligible = get_bool(body, "medicaid_eligible", default=False)
    consent = get_bool(body, "medicaid_consent_on_file", default=False)
    for existing in db.students.values():
        if existing["state_student_id"] == state_student_id:
            fail("ERR_DUPLICATE_RESOURCE", "state_student_id is already in use.")
    row = new_row("student", {
        "state_student_id": state_student_id,
        "full_name": full_name,
        "district_of_residence": district,
        "disability_category": category,
        "iep_effective_date": iep_date.isoformat(),
        "lre_current_setting": setting,
        "medicaid_eligible": medicaid_eligible,
        "medicaid_consent_on_file": consent,
        "placement_status": "NONE",
        "high_cost_flag": False,
        "projected_state_recovery_cents": 0,
    })
    db.students[row["id"]] = row
    return created(public(row))


@endpoint(bp, "GET", "/students/<student_id>", ALL_ROLES)
def get_student(student_id):
    return single(student_or_404(student_id))


@endpoint(bp, "PATCH", "/students/<student_id>/medicaid-consent",
          (PARENT_GUARDIAN, PLACEMENT_COORDINATOR, SYSTEM_ADMIN))
def patch_medicaid_consent(student_id):
    student = student_or_404(student_id)
    body = read_body(("medicaid_eligible", "medicaid_consent_on_file"))
    eligible = get_bool(body, "medicaid_eligible", required=True)
    consent = get_bool(body, "medicaid_consent_on_file", required=True)
    from middleware import check_scope
    check_scope(student)
    student["medicaid_eligible"] = eligible
    student["medicaid_consent_on_file"] = consent
    touch(student)
    return ok(public(student))


# =========================================================================
# approved private schools
# =========================================================================

@endpoint(bp, "GET", "/private-schools", ALL_ROLES)
def list_private_schools():
    return collection(db.schools.values(), [("approval_status", q_str("approval_status"))])


@endpoint(bp, "POST", "/private-schools", (SYSTEM_ADMIN,))
def create_private_school():
    body = read_body((
        "name", "state_approval_id", "approval_status", "residential_capable",
        "medicaid_provider_number",
    ))
    name = get_str(body, "name")
    approval_id = get_str(body, "state_approval_id")
    approval_status = get_enum(body, "approval_status", APPROVAL_STATUSES,
                               required=False, default="PROVISIONAL")
    residential = get_bool(body, "residential_capable", default=False)
    provider_number = get_str(body, "medicaid_provider_number", required=False,
                              default=None, nullable=True)
    for existing in db.schools.values():
        if existing["state_approval_id"] == approval_id:
            fail("ERR_DUPLICATE_RESOURCE", "state_approval_id is already in use.")
    row = new_row("school", {
        "name": name,
        "state_approval_id": approval_id,
        "approval_status": approval_status,
        "residential_capable": residential,
        "medicaid_provider_number": provider_number,
        "active_rate_schedule_id": None,
    })
    db.schools[row["id"]] = row
    return created(public(row))


@endpoint(bp, "GET", "/private-schools/<school_id>", ALL_ROLES)
def get_private_school(school_id):
    return single(school_or_404(school_id))


@endpoint(bp, "PATCH", "/private-schools/<school_id>/approval-status", (SYSTEM_ADMIN,))
def patch_approval_status(school_id):
    school = school_or_404(school_id)
    body = read_body(("approval_status",))
    approval_status = get_enum(body, "approval_status", APPROVAL_STATUSES)
    school["approval_status"] = approval_status
    touch(school)
    return ok(public(school))


# =========================================================================
# tuition rate schedules
# =========================================================================

def recompute_active_schedule(school):
    best = None
    for schedule in db.rate_schedules.values():
        if schedule["school_id"] != school["id"]:
            continue
        if schedule["approval_state"] != "STATE_APPROVED":
            continue
        if best is None or schedule["fiscal_year"] > best["fiscal_year"]:
            best = schedule
    new_pointer = best["id"] if best is not None else None
    changed = school["active_rate_schedule_id"] != new_pointer
    school["active_rate_schedule_id"] = new_pointer
    return changed


@endpoint(bp, "GET", "/tuition-rate-schedules", ALL_ROLES)
def list_rate_schedules():
    return collection(db.rate_schedules.values(), [
        ("school_id", q_str("school_id")),
        ("fiscal_year", q_int("fiscal_year")),
        ("approval_state", q_str("approval_state")),
    ])


@endpoint(bp, "POST", "/tuition-rate-schedules", (FISCAL_OFFICER, SYSTEM_ADMIN))
def create_rate_schedule():
    body = read_body((
        "school_id", "fiscal_year", "day_rate_cents", "residential_rate_cents",
        "service_hourly_rate_cents", "effective_from", "effective_to",
        "approval_state", "expected_school_version",
    ))
    school_id = get_id(body, "school_id")
    fiscal_year = get_int(body, "fiscal_year", minimum=2020, maximum=2100)
    day_rate = get_cents(body, "day_rate_cents", minimum=1)
    residential_rate = get_cents(body, "residential_rate_cents", minimum=0)
    service_rate = get_cents(body, "service_hourly_rate_cents", minimum=0)
    effective_from = get_date(body, "effective_from")
    effective_to = get_date(body, "effective_to")
    approval_state = get_enum(body, "approval_state", CLIENT_APPROVAL_STATES)
    expected_version = get_int(body, "expected_school_version", minimum=0)

    school = school_or_404(school_id)
    if expected_version != school["version"]:
        fail("ERR_STALE_SCHOOL_VERSION")

    row = new_row("rate_schedule", {
        "school_id": school_id,
        "fiscal_year": fiscal_year,
        "day_rate_cents": day_rate,
        "residential_rate_cents": residential_rate,
        "service_hourly_rate_cents": service_rate,
        "effective_from": effective_from.isoformat(),
        "effective_to": effective_to.isoformat(),
        "approval_state": approval_state,
        "superseded_by_schedule_id": None,
    })

    superseded_any = False
    if approval_state == "STATE_APPROVED":
        for incumbent in list(db.rate_schedules.values()):
            if (incumbent["school_id"] == school_id
                    and incumbent["fiscal_year"] == fiscal_year
                    and incumbent["approval_state"] == "STATE_APPROVED"):
                incumbent["approval_state"] = "SUPERSEDED"
                incumbent["superseded_by_schedule_id"] = row["id"]
                touch(incumbent)
                superseded_any = True

    db.rate_schedules[row["id"]] = row
    changed = recompute_active_schedule(school)
    if changed or superseded_any:
        touch(school)
    return created(public(row))


@endpoint(bp, "GET", "/tuition-rate-schedules/<schedule_id>", ALL_ROLES)
def get_rate_schedule(schedule_id):
    return single(schedule_or_404(schedule_id))


# =========================================================================
# transport routes
# =========================================================================

@endpoint(bp, "GET", "/transport-routes", ALL_ROLES)
def list_transport_routes():
    return collection(db.routes.values())


@endpoint(bp, "POST", "/transport-routes", (PLACEMENT_COORDINATOR, SYSTEM_ADMIN))
def create_transport_route():
    body = read_body((
        "route_code", "seat_capacity", "daily_rate_cents",
        "service_window_start_min", "service_window_end_min",
    ))
    route_code = get_str(body, "route_code")
    seat_capacity = get_int(body, "seat_capacity", minimum=1, maximum=24)
    daily_rate = get_cents(body, "daily_rate_cents", minimum=1)
    window_start = get_int(body, "service_window_start_min", minimum=0, maximum=1439)
    window_end = get_int(body, "service_window_end_min", minimum=1, maximum=1440)
    if window_end <= window_start:
        fail("ERR_INVALID_REQUEST",
             "service_window_end_min must be strictly greater than service_window_start_min.")
    for existing in db.routes.values():
        if existing["route_code"] == route_code:
            fail("ERR_DUPLICATE_RESOURCE", "route_code is already in use.")
    row = new_row("route", {
        "route_code": route_code,
        "seat_capacity": seat_capacity,
        "seats_committed": 0,
        "seats_available": seat_capacity,
        "daily_rate_cents": daily_rate,
        "service_window_start_min": window_start,
        "service_window_end_min": window_end,
    })
    db.routes[row["id"]] = row
    return created(public(row))


@endpoint(bp, "GET", "/transport-routes/<route_id>", ALL_ROLES)
def get_transport_route(route_id):
    return single(route_or_404(route_id))
