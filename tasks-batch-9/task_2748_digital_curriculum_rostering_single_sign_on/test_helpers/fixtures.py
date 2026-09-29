"""
Composite setup helpers for the Digital Curriculum Rostering & Single Sign-On API.

The runner restarts the service before every test, so each test begins against
an empty database and builds exactly the world it needs. These helpers are the
shared vocabulary for that construction, layered from single-entity creators
through to whole licensed districts and in-flight pipeline runs.

Every helper drives the real API over HTTP; none of them touch storage directly.
Setup calls are validated leniently through get_success_data() so that a broken
precondition fails loudly at the line that caused it.
"""

from prd_bench_local_runner.testing import get_success_data, validate_success

from . import test_users as users
from . import factories as f
from .constants import (
    CLOCK_IN_WINDOW,
    STANDARD_PRICE_PER_SEAT_CENTS,
    VALID_PASSWORD,
)
from .types import (
    GradeBand,
    MeetingDay,
    RunType,
)


# ─────────────────────────────────────────────────────────────────────────────
# Tier 1 — logical clock
# ─────────────────────────────────────────────────────────────────────────────

def set_clock(api, now, headers=None):
    """Move the server's logical UTC clock and return the echoed instant."""
    response = api.set_clock(now, headers or users.ROSTER_OPERATOR)
    return get_success_data(response)


# ─────────────────────────────────────────────────────────────────────────────
# Tier 2 — single-entity creators
# ─────────────────────────────────────────────────────────────────────────────

def create_school(api, grade_band=GradeBand.ELEMENTARY, headers=None, **overrides):
    """Register one building and return the created School."""
    payload = f.school_payload(grade_band=grade_band, **overrides)
    response = api.create_school(payload, headers or users.ROSTER_OPERATOR)
    return get_success_data(response, 201)


def create_term(api, headers=None, **overrides):
    """Create one PLANNED term and return it."""
    payload = f.term_payload(**overrides)
    response = api.create_term(payload, headers or users.ROSTER_OPERATOR)
    return get_success_data(response, 201)


def activate_term(api, term_id, headers=None):
    """Take a term PLANNED -> ACTIVE and return it."""
    response = api.activate_term(term_id, headers or users.ROSTER_OPERATOR)
    return get_success_data(response, 200)


def create_active_term(api, headers=None, **overrides):
    """Create a term and activate it, returning the ACTIVE Term."""
    term = create_term(api, headers=headers, **overrides)
    return activate_term(api, term["id"], headers=headers)


def rollover_term(api, term_id, headers=None):
    """Take a term ACTIVE -> ROLLED_OVER and return it."""
    response = api.rollover_term(term_id, headers or users.DATA_GOVERNANCE_OFFICER)
    return get_success_data(response, 200)


def create_teacher(api, school_id, headers=None, **overrides):
    """Register one teacher and return the created Teacher."""
    payload = f.teacher_payload(school_id, **overrides)
    response = api.create_teacher(payload, headers or users.ROSTER_OPERATOR)
    return get_success_data(response, 201)


def separate_teacher(api, teacher_id, separation_effective_date, headers=None):
    """Record a staff separation and return the Teacher."""
    payload = f.separation_payload(separation_effective_date)
    response = api.separate_teacher(
        teacher_id, payload, headers or users.DATA_GOVERNANCE_OFFICER
    )
    return get_success_data(response, 200)


def create_student(api, school_id, grade_level=3, headers=None, **overrides):
    """Register one student and return the created Student."""
    payload = f.student_payload(school_id, grade_level=grade_level, **overrides)
    response = api.create_student(payload, headers or users.ROSTER_OPERATOR)
    return get_success_data(response, 201)


def create_students(api, school_id, count, grade_level=3, headers=None, **overrides):
    """Register several students in one building and return the list."""
    return [
        create_student(api, school_id, grade_level=grade_level, headers=headers,
                       **overrides)
        for _ in range(count)
    ]


def withdraw_student(api, student_id, withdrawal_effective_date, headers=None):
    """Withdraw a student and return the Student."""
    payload = f.withdrawal_payload(withdrawal_effective_date)
    response = api.withdraw_student(
        student_id, payload, headers or users.DATA_GOVERNANCE_OFFICER
    )
    return get_success_data(response, 200)


def create_section(api, school_id, term_id, primary_teacher_id=None, period_index=1,
                   meeting_days=None, max_seats=30, headers=None, **overrides):
    """Create one section and return it."""
    payload = f.section_payload(
        school_id,
        term_id,
        primary_teacher_id=primary_teacher_id,
        period_index=period_index,
        meeting_days=meeting_days,
        max_seats=max_seats,
        **overrides,
    )
    response = api.create_section(payload, headers or users.ROSTER_OPERATOR)
    return get_success_data(response, 201)


def create_enrollment(api, section_id, student_id, requested_effective_date,
                      headers=None, **overrides):
    """Add a student to a section and return the Enrollment."""
    payload = f.enrollment_payload(
        section_id, student_id, requested_effective_date, **overrides
    )
    response = api.create_enrollment(payload, headers or users.ROSTER_OPERATOR)
    return get_success_data(response, 201)


def drop_enrollment(api, enrollment_id, drop_effective_date, headers=None):
    """Request a drop and return the Enrollment."""
    payload = f.drop_payload(drop_effective_date)
    response = api.drop_enrollment(
        enrollment_id, payload, headers or users.ROSTER_OPERATOR
    )
    return get_success_data(response, 200)


# ─────────────────────────────────────────────────────────────────────────────
# Tier 3 — licences, allocations and reads
# ─────────────────────────────────────────────────────────────────────────────

def create_vendor_app(api, term_id, total_seats=10,
                      price_per_seat_cents=STANDARD_PRICE_PER_SEAT_CENTS,
                      grade_band_scope=None, headers=None, **overrides):
    """Register a DRAFT licence and return it."""
    payload = f.vendor_app_payload(
        term_id,
        total_seats=total_seats,
        price_per_seat_cents=price_per_seat_cents,
        grade_band_scope=grade_band_scope,
        **overrides,
    )
    response = api.create_vendor_app(
        payload, headers or users.VENDOR_INTEGRATION_MANAGER
    )
    return get_success_data(response, 201)


def activate_license(api, vendor_app_id, headers=None):
    """
    Activate a DRAFT licence under the two-person control and return it. The
    activating officer is a different operator from the registering manager.
    """
    response = api.activate_license(
        vendor_app_id, headers or users.DATA_GOVERNANCE_OFFICER
    )
    return get_success_data(response, 200)


def read_vendor_app(api, vendor_app_id, headers=None):
    """Read one licence."""
    response = api.get_vendor_app(vendor_app_id, headers or users.ROSTER_OPERATOR)
    return get_success_data(response, 200)


def vendor_app_version(api, vendor_app_id, headers=None):
    """Read the licence's current version, for an optimistic-concurrency write."""
    return read_vendor_app(api, vendor_app_id, headers)["version"]


def list_allocations(api, vendor_app_id, headers=None, **filters):
    """List a licence's building allocations, ordered by created_at ascending."""
    response = api.list_building_allocations(
        headers or users.ROSTER_OPERATOR, vendor_app_id=vendor_app_id,
        limit=100, **filters
    )
    data, _meta = _paginated(response)
    return data


def allocation_for_school(api, vendor_app_id, school_id, headers=None):
    """The licence's allocation for one building."""
    rows = list_allocations(api, vendor_app_id, headers=headers, school_id=school_id)
    assert rows, (
        f"no building allocation for vendor_app {vendor_app_id} / school {school_id}"
    )
    return rows[0]


def read_allocation(api, allocation_id, headers=None):
    """Read one allocation."""
    response = api.get_building_allocation(
        allocation_id, headers or users.ROSTER_OPERATOR
    )
    return get_success_data(response, 200)


def recut_allocation(api, allocation_id, allocated_seats, vendor_app_id=None,
                     expected_vendor_app_version=None, headers=None):
    """
    Re-cut one building's allocation under optimistic concurrency, reading the
    licence's current version first unless the caller pins one.
    """
    if expected_vendor_app_version is None:
        assert vendor_app_id, "pass vendor_app_id or expected_vendor_app_version"
        expected_vendor_app_version = vendor_app_version(api, vendor_app_id)
    payload = f.allocation_patch(allocated_seats, expected_vendor_app_version)
    response = api.update_building_allocation(
        allocation_id, payload, headers or users.DATA_GOVERNANCE_OFFICER
    )
    return get_success_data(response, 200)


def _paginated(response):
    data = validate_success(response, 200)
    return data, response.json()["meta"]


# ─────────────────────────────────────────────────────────────────────────────
# Tier 4 — app accounts and the identity lifecycle
# ─────────────────────────────────────────────────────────────────────────────

def provision_account(api, allocation_id, vendor_app_id=None, student_id=None,
                      teacher_id=None, expected_vendor_app_version=None,
                      headers=None, **overrides):
    """
    Provision one SSO identity against an allocation, reading the licence's
    current version first unless the caller pins one, and return the AppAccount.
    """
    if expected_vendor_app_version is None:
        assert vendor_app_id, "pass vendor_app_id or expected_vendor_app_version"
        expected_vendor_app_version = vendor_app_version(api, vendor_app_id)
    payload = f.app_account_payload(
        allocation_id,
        expected_vendor_app_version,
        student_id=student_id,
        teacher_id=teacher_id,
        **overrides,
    )
    response = api.create_app_account(payload, headers or users.IDENTITY_ADMIN)
    return get_success_data(response, 201)


def set_account_password(api, account_id, new_password=VALID_PASSWORD, headers=None):
    """Set an account password, advancing the identity axis to PROVISIONED."""
    payload = f.password_set_payload(new_password)
    response = api.set_password(account_id, payload, headers or users.IDENTITY_ADMIN)
    return get_success_data(response, 200)


def provision_provisioned_account(api, allocation_id, vendor_app_id=None,
                                  student_id=None, teacher_id=None,
                                  new_password=VALID_PASSWORD, headers=None,
                                  **overrides):
    """
    Provision an account and immediately set its password, so the identity axis
    is PROVISIONED while the seat axis is still RESERVED.
    """
    account = provision_account(
        api,
        allocation_id,
        vendor_app_id=vendor_app_id,
        student_id=student_id,
        teacher_id=teacher_id,
        headers=headers,
        **overrides,
    )
    return set_account_password(api, account["id"], new_password)


def record_usage(api, account_id, activity_date, active_minutes, headers=None,
                 **overrides):
    """Post one usage report and return the AppAccount."""
    payload = f.usage_payload(activity_date, active_minutes, **overrides)
    response = api.record_usage(account_id, payload, headers or users.IDENTITY_ADMIN)
    return get_success_data(response, 200)


def release_seat(api, account_id, headers=None):
    """Release the seat, leaving the identity axis alone, and return the account."""
    response = api.release_seat(account_id, headers or users.IDENTITY_ADMIN)
    return get_success_data(response, 200)


def deprovision_account(api, account_id, effective_date, headers=None):
    """Deprovision the identity, leaving the seat axis alone."""
    payload = f.deprovision_payload(effective_date)
    response = api.deprovision_account(
        account_id, payload, headers or users.IDENTITY_ADMIN
    )
    return get_success_data(response, 200)


def read_account(api, account_id, headers=None):
    """Read one app account (which re-evaluates password expiry first)."""
    response = api.get_app_account(account_id, headers or users.IDENTITY_ADMIN)
    return get_success_data(response, 200)


def accounts_of_allocation(api, allocation_id, headers=None, **filters):
    """List every app account drawing on one allocation."""
    response = api.list_app_accounts(
        headers or users.IDENTITY_ADMIN, building_allocation_id=allocation_id,
        limit=100, **filters
    )
    data, _meta = _paginated(response)
    return data


# ─────────────────────────────────────────────────────────────────────────────
# Tier 4 — the rostering pipeline
# ─────────────────────────────────────────────────────────────────────────────

def open_sync_run(api, vendor_app_id, run_type=RunType.FULL, headers=None):
    """Extract the source-of-truth roster for a licence and return the SyncRun."""
    payload = f.sync_run_payload(vendor_app_id, run_type=run_type)
    response = api.create_sync_run(payload, headers or users.ROSTER_OPERATOR)
    return get_success_data(response, 201)


def transform_run(api, sync_run_id, headers=None):
    """Transform an extracted run and return the SyncRun."""
    response = api.transform_sync_run(sync_run_id, headers or users.ROSTER_OPERATOR)
    return get_success_data(response, 200)


def publish_run(api, sync_run_id, headers=None):
    """
    Publish a transformed run under the two-person control; the publishing
    officer is a different operator from the run's initiator.
    """
    response = api.publish_sync_run(
        sync_run_id, headers or users.DATA_GOVERNANCE_OFFICER
    )
    return get_success_data(response, 200)


def read_run(api, sync_run_id, headers=None):
    """Read one sync run."""
    response = api.get_sync_run(sync_run_id, headers or users.ROSTER_OPERATOR)
    return get_success_data(response, 200)


def queue_items(api, sync_run_id=None, headers=None, **filters):
    """List triage items, optionally for one run."""
    query = dict(filters)
    if sync_run_id is not None:
        query["sync_run_id"] = sync_run_id
    response = api.list_error_queue_items(
        headers or users.DATA_GOVERNANCE_OFFICER, limit=100, **query
    )
    data, _meta = _paginated(response)
    return data


def resolve_match(api, item_id, replacement_teacher_id, headers=None, **overrides):
    """Triage an unmatched teacher and return the ErrorQueueItem."""
    payload = f.resolve_match_payload(replacement_teacher_id, **overrides)
    response = api.resolve_match(
        item_id, payload, headers or users.DATA_GOVERNANCE_OFFICER
    )
    return get_success_data(response, 200)


def merge_duplicate(api, item_id, surviving_student_id, headers=None, **overrides):
    """Triage a duplicate student and return the ErrorQueueItem."""
    payload = f.merge_duplicate_payload(surviving_student_id, **overrides)
    response = api.merge_duplicate(
        item_id, payload, headers or users.DATA_GOVERNANCE_OFFICER
    )
    return get_success_data(response, 200)


def transformed_run(api, vendor_app_id, run_type=RunType.FULL, headers=None):
    """Open a run and transform it, returning the transformed SyncRun."""
    run = open_sync_run(api, vendor_app_id, run_type=run_type, headers=headers)
    return transform_run(api, run["id"], headers=headers)


# ─────────────────────────────────────────────────────────────────────────────
# Tier 5 — whole worlds
# ─────────────────────────────────────────────────────────────────────────────

def district_with_active_term(api, clock=CLOCK_IN_WINDOW,
                              grade_band=GradeBand.ELEMENTARY, term_overrides=None):
    """
    The district backbone: the logical clock set, one building registered and one
    ACTIVE term open for scheduling.

    Returns {"school", "school_id", "term", "term_id"}.
    """
    if clock is not None:
        set_clock(api, clock)
    school = create_school(api, grade_band=grade_band)
    term = create_active_term(api, **(term_overrides or {}))
    return {
        "school": school,
        "school_id": school["id"],
        "term": term,
        "term_id": term["id"],
    }


def licensed_building(api, clock=CLOCK_IN_WINDOW, grade_band=GradeBand.ELEMENTARY,
                      student_count=1, grade_level=3, total_seats=10,
                      price_per_seat_cents=STANDARD_PRICE_PER_SEAT_CENTS,
                      grade_band_scope=None, term_overrides=None,
                      license_overrides=None, activate=True):
    """
    One building inside one ACTIVE term, holding an ACTIVE licence whose seats
    have been split into a single BuildingAllocation, plus optional students.

    Returns a dict carrying school / term / students / vendor_app / allocation
    together with their ids.
    """
    world = district_with_active_term(
        api, clock=clock, grade_band=grade_band, term_overrides=term_overrides
    )
    world["students"] = create_students(
        api, world["school_id"], student_count, grade_level=grade_level
    )
    world["student_ids"] = [s["id"] for s in world["students"]]
    if world["students"]:
        world["student"] = world["students"][0]
        world["student_id"] = world["students"][0]["id"]

    vendor_app = create_vendor_app(
        api,
        world["term_id"],
        total_seats=total_seats,
        price_per_seat_cents=price_per_seat_cents,
        grade_band_scope=grade_band_scope or [grade_band],
        **(license_overrides or {}),
    )
    world["vendor_app"] = vendor_app
    world["vendor_app_id"] = vendor_app["id"]

    if activate:
        world["vendor_app"] = activate_license(api, vendor_app["id"])
        allocation = allocation_for_school(api, vendor_app["id"], world["school_id"])
        world["allocation"] = allocation
        world["allocation_id"] = allocation["id"]
    return world


def licensed_district(api, buildings, clock=CLOCK_IN_WINDOW, total_seats=10,
                      price_per_seat_cents=STANDARD_PRICE_PER_SEAT_CENTS,
                      grade_band_scope=None, term_overrides=None,
                      license_overrides=None, activate=True):
    """
    Several buildings of stated grade bands and headcounts inside one ACTIVE
    term, under a single licence whose activation splits its seats across every
    eligible building.

    `buildings` is a sequence of dicts, each optionally carrying grade_band,
    student_count and grade_level.

    Returns {"term", "term_id", "schools", "school_ids", "students_by_school",
             "vendor_app", "vendor_app_id", "allocations", "allocations_by_school"}.
    """
    if clock is not None:
        set_clock(api, clock)
    term = create_active_term(api, **(term_overrides or {}))

    schools = []
    students_by_school = {}
    for spec in buildings:
        band = spec.get("grade_band", GradeBand.ELEMENTARY)
        school = create_school(api, grade_band=band)
        schools.append(school)
        students_by_school[school["id"]] = create_students(
            api,
            school["id"],
            spec.get("student_count", 0),
            grade_level=spec.get("grade_level", 3),
        )

    bands = grade_band_scope or sorted(
        {spec.get("grade_band", GradeBand.ELEMENTARY) for spec in buildings}
    )
    vendor_app = create_vendor_app(
        api,
        term["id"],
        total_seats=total_seats,
        price_per_seat_cents=price_per_seat_cents,
        grade_band_scope=list(bands),
        **(license_overrides or {}),
    )

    world = {
        "term": term,
        "term_id": term["id"],
        "schools": schools,
        "school_ids": [s["id"] for s in schools],
        "students_by_school": students_by_school,
        "vendor_app": vendor_app,
        "vendor_app_id": vendor_app["id"],
    }
    if activate:
        world["vendor_app"] = activate_license(api, vendor_app["id"])
        allocations = list_allocations(api, vendor_app["id"])
        world["allocations"] = allocations
        world["allocations_by_school"] = {a["school_id"]: a for a in allocations}
    return world


def rostered_section(api, clock=CLOCK_IN_WINDOW, grade_band=GradeBand.ELEMENTARY,
                     student_count=1, grade_level=3, period_index=1,
                     meeting_days=None, max_seats=30, with_teacher=True,
                     effective_date=None, term_overrides=None):
    """
    One building, one ACTIVE term, one section (optionally teacher-matched) and
    one enrollment per student, added on the given effective date.

    Returns the district dict extended with teacher / section / students /
    enrollments.
    """
    world = district_with_active_term(
        api, clock=clock, grade_band=grade_band, term_overrides=term_overrides
    )
    teacher = None
    if with_teacher:
        teacher = create_teacher(api, world["school_id"])
    world["teacher"] = teacher
    world["teacher_id"] = teacher["id"] if teacher else None

    section = create_section(
        api,
        world["school_id"],
        world["term_id"],
        primary_teacher_id=world["teacher_id"],
        period_index=period_index,
        meeting_days=meeting_days or list(MeetingDay.MWF),
        max_seats=max_seats,
    )
    world["section"] = section
    world["section_id"] = section["id"]

    world["students"] = create_students(
        api, world["school_id"], student_count, grade_level=grade_level
    )
    world["student_ids"] = [s["id"] for s in world["students"]]
    if world["students"]:
        world["student"] = world["students"][0]
        world["student_id"] = world["students"][0]["id"]

    add_date = effective_date or world["term"]["start_date"]
    world["enrollments"] = [
        create_enrollment(api, section["id"], student["id"], add_date)
        for student in world["students"]
    ]
    world["enrollment_ids"] = [e["id"] for e in world["enrollments"]]
    if world["enrollments"]:
        world["enrollment"] = world["enrollments"][0]
        world["enrollment_id"] = world["enrollments"][0]["id"]
    return world


def seated_account(api, clock=CLOCK_IN_WINDOW, grade_band=GradeBand.ELEMENTARY,
                   grade_level=3, total_seats=10,
                   price_per_seat_cents=STANDARD_PRICE_PER_SEAT_CENTS,
                   license_overrides=None, term_overrides=None):
    """
    A licensed building with one student who already holds a provisioned seat:
    seat_status RESERVED, identity_status PENDING_PROVISION, password TEMP_SET.

    Returns the licensed-building dict extended with account / account_id.
    """
    world = licensed_building(
        api,
        clock=clock,
        grade_band=grade_band,
        student_count=1,
        grade_level=grade_level,
        total_seats=total_seats,
        price_per_seat_cents=price_per_seat_cents,
        license_overrides=license_overrides,
        term_overrides=term_overrides,
    )
    account = provision_account(
        api,
        world["allocation_id"],
        vendor_app_id=world["vendor_app_id"],
        student_id=world["student_id"],
    )
    world["account"] = account
    world["account_id"] = account["id"]
    return world
