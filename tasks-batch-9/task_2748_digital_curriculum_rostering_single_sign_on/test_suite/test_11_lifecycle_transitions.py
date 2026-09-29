"""
Lifecycle transitions across the school year: terms opening and rolling over,
enrollments landing and winding down, licences activating and pausing, seats and
identities moving on their own two axes, and the rostering pipeline advancing run
by run.

Each test drives one transition to a boundary — the second attempt at a one-shot
act, the day after a window closes, the cascade that reaches four hops outward —
and pins the states, counters and refusals the district may observe afterwards.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as errors
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.assertions import (
    assert_account_axes,
    assert_common_fields,
    assert_ids_equal,
    assert_seat_counters,
)
from test_helpers.types import (
    AddDropClass,
    ErrorCategory,
    ErrorQueueItemStatus,
    ErrorSeverity,
    GradeBand,
    IdentityStatus,
    OveragePolicy,
    PasswordState,
    RosterHealth,
    RosterStatus,
    RunType,
    SeatStatus,
    SectionStatus,
    SyncHealth,
    SyncRunState,
    TermState,
    VendorAppStatus,
)


def _licensed_section_with_seated_student(api, set_password=False):
    """
    One building inside an ACTIVE Fall term: a teacher-matched section with one
    student added inside the add/drop window, and a licence whose activation gave
    the building four seats, one of which that student now holds.
    """
    world = fx.rostered_section(
        api,
        clock=c.CLOCK_IN_WINDOW,
        student_count=1,
        grade_level=4,
        period_index=3,
        max_seats=5,
        effective_date=c.CLOCK_IN_WINDOW[:10],
    )
    vendor_app = fx.create_vendor_app(
        api,
        world["term_id"],
        total_seats=4,
        grade_band_scope=[GradeBand.ELEMENTARY],
        overage_policy=OveragePolicy.BLOCK,
    )
    world["vendor_app"] = fx.activate_license(api, vendor_app["id"])
    world["vendor_app_id"] = vendor_app["id"]
    allocation = fx.allocation_for_school(api, vendor_app["id"], world["school_id"])
    world["allocation"] = allocation
    world["allocation_id"] = allocation["id"]
    account = fx.provision_account(
        api,
        allocation["id"],
        vendor_app_id=vendor_app["id"],
        student_id=world["student_id"],
    )
    if set_password:
        account = fx.set_account_password(api, account["id"])
    world["account"] = account
    world["account_id"] = account["id"]
    return world


def _run_held_by_an_unmatched_teacher(api, spare_teachers=0):
    """
    A licensed building whose only section has no teacher of record, with one
    enrolled student, and a sync run transformed into HELD by the resulting
    blocking triage item.
    """
    world = fx.district_with_active_term(api, clock=c.CLOCK_STARTUP_DEFAULT)
    world["spare_teachers"] = [
        fx.create_teacher(api, world["school_id"]) for _ in range(spare_teachers)
    ]
    section = fx.create_section(
        api,
        world["school_id"],
        world["term_id"],
        period_index=3,
        max_seats=5,
    )
    world["section"] = section
    world["section_id"] = section["id"]
    student = fx.create_student(api, world["school_id"], grade_level=4)
    world["student"] = student
    world["student_id"] = student["id"]

    fx.set_clock(api, c.CLOCK_IN_WINDOW)
    world["enrollment"] = fx.create_enrollment(
        api, section["id"], student["id"], c.CLOCK_IN_WINDOW[:10]
    )

    vendor_app = fx.create_vendor_app(
        api,
        world["term_id"],
        total_seats=4,
        grade_band_scope=[GradeBand.ELEMENTARY],
    )
    world["vendor_app"] = fx.activate_license(api, vendor_app["id"])
    world["vendor_app_id"] = vendor_app["id"]

    run = fx.open_sync_run(api, vendor_app["id"], run_type=RunType.FULL)
    world["run"] = fx.transform_run(api, run["id"])
    world["run_id"] = run["id"]
    return world


def test_a_term_still_being_planned_cannot_be_rolled_over(api):
    """A term that never opened for scheduling cannot be closed down for the summer.

    A term "is born in state PLANNED with a null archived_access_expires_at", and
    rollover "requires the term to be ACTIVE, else ERR_TERM_NOT_ACTIVE" — the
    state precondition being checked ahead of the calendar window. The refused
    attempt leaves the term exactly as it was, still PLANNED at version 1 with no
    archived-access deadline computed.

    Design: Corner/state_machines/term_initial_state_is_planned_and_rollover_from_planned_rejected
    """
    fx.set_clock(api, c.CLOCK_STARTUP_DEFAULT)
    term = fx.create_term(api)

    assert term["state"] == TermState.PLANNED
    assert term["archived_access_expires_at"] is None
    assert_common_fields(term, "term", expected_version=1)

    fx.set_clock(api, "2026-12-20T00:00:00Z")
    validate_error(
        api.rollover_term(term["id"], users.DATA_GOVERNANCE_OFFICER),
        errors.ERR_TERM_NOT_ACTIVE,
        409,
    )

    unchanged = validate_success(
        api.get_term(term["id"], users.ROSTER_OPERATOR), 200
    )
    assert unchanged["state"] == TermState.PLANNED
    assert unchanged["archived_access_expires_at"] is None
    assert unchanged["version"] == 1


def test_a_term_may_be_opened_on_its_last_day_but_not_the_day_after(api):
    """The district may still open a term on its closing day, never once it has ended.

    Activation "requires the clock date to be on or before the term's end_date — a
    term that has already ended cannot be opened, and the attempt is refused with
    ERR_TERM_WINDOW_CLOSED". Opening a term takes state "from PLANNED to ACTIVE and
    increments the term's version", so the boundary is exact: at 23:59:59 on
    18 December 2026 the term opens, and one day later an identical term does not.

    Design: Corner/state_machines/term_activate_after_end_date_rejected
    """
    fx.set_clock(api, c.CLOCK_STARTUP_DEFAULT)
    on_time = fx.create_term(api)
    too_late = fx.create_term(api)

    fx.set_clock(api, "2026-12-18T23:59:59Z")
    opened = validate_success(
        api.activate_term(on_time["id"], users.ROSTER_OPERATOR), 200
    )
    assert opened["state"] == TermState.ACTIVE
    assert opened["version"] == 2

    fx.set_clock(api, c.CLOCK_AFTER_TERM_END)
    validate_error(
        api.activate_term(too_late["id"], users.ROSTER_OPERATOR),
        errors.ERR_TERM_WINDOW_CLOSED,
        422,
    )

    unchanged = validate_success(
        api.get_term(too_late["id"], users.ROSTER_OPERATOR), 200
    )
    assert unchanged["state"] == TermState.PLANNED
    assert unchanged["version"] == 1


def test_an_add_dated_tomorrow_waits_while_an_add_dated_today_takes_effect(api):
    """An add for tomorrow is scheduled but not yet honoured; an add for today is live at once.

    A new enrollment is created "with roster_status of PENDING_ADD"; then, "when
    requested_effective_date is on or before the clock date, the row advances from
    PENDING_ADD to ACTIVE in the same request". The boundary is exact: "a request
    whose effective date equals the clock date lands ACTIVE, and a request one day
    in the future stays PENDING_ADD until a publish picks it up". Both dates are on
    or before the add/drop cutoff, so both rows are classified IN_WINDOW, and both
    count towards the section's active_enrollment_count.

    Design: Corner/state_machines/enrollment_future_dated_add_stays_pending_add
    """
    world = fx.district_with_active_term(api, clock=c.CLOCK_STARTUP_DEFAULT)
    teacher = fx.create_teacher(api, world["school_id"])
    section = fx.create_section(
        api,
        world["school_id"],
        world["term_id"],
        primary_teacher_id=teacher["id"],
        period_index=3,
        max_seats=5,
    )
    today_student, tomorrow_student = fx.create_students(
        api, world["school_id"], 2, grade_level=4
    )

    fx.set_clock(api, c.CLOCK_IN_WINDOW)

    landed = validate_success(
        api.create_enrollment(
            f.enrollment_payload(section["id"], today_student["id"], "2026-08-20"),
            users.ROSTER_OPERATOR,
        ),
        201,
    )
    assert landed["roster_status"] == RosterStatus.ACTIVE
    assert landed["effective_date"] == "2026-08-20"
    assert landed["add_drop_class"] == AddDropClass.IN_WINDOW
    assert landed["drop_effective_date"] is None

    waiting = validate_success(
        api.create_enrollment(
            f.enrollment_payload(
                section["id"], tomorrow_student["id"], "2026-08-21"
            ),
            users.ROSTER_OPERATOR,
        ),
        201,
    )
    assert waiting["roster_status"] == RosterStatus.PENDING_ADD
    assert waiting["effective_date"] == "2026-08-21"
    assert waiting["add_drop_class"] == AddDropClass.IN_WINDOW

    section_now = validate_success(
        api.get_section(section["id"], users.ROSTER_OPERATOR), 200
    )
    assert section_now["active_enrollment_count"] == 2

    live_rows, live_meta = validate_paginated(
        api.list_enrollments(
            users.ROSTER_OPERATOR,
            section_id=section["id"],
            roster_status=RosterStatus.ACTIVE,
        )
    )
    assert live_meta["total_count"] == 1
    assert_ids_equal(live_rows, [landed["id"]], "live enrollments")


def test_a_second_drop_request_on_the_same_enrollment_is_refused(api):
    """Once a drop is on the books, the district cannot re-date it with a second request.

    Drops are accepted only "against an enrollment that is PENDING_ADD or ACTIVE; a
    row that is already PENDING_DROP or DROPPED cannot be dropped again and yields
    ERR_ENROLLMENT_NOT_DROPPABLE". A post-dated drop on an ACTIVE row "records
    drop_effective_date and moves roster_status to PENDING_DROP: no seat is
    released and no refund is issued yet", and the refused second attempt leaves
    that recorded date untouched.

    Design: Corner/state_machines/enrollment_drop_twice_rejected
    """
    world = fx.rostered_section(
        api,
        clock=c.CLOCK_IN_WINDOW,
        student_count=1,
        grade_level=4,
        period_index=3,
        max_seats=5,
        effective_date="2026-08-20",
    )
    enrollment = world["enrollment"]
    assert enrollment["roster_status"] == RosterStatus.ACTIVE

    pending = validate_success(
        api.drop_enrollment(
            enrollment["id"], f.drop_payload("2026-09-30"), users.ROSTER_OPERATOR
        ),
        200,
    )
    assert pending["roster_status"] == RosterStatus.PENDING_DROP
    assert pending["drop_effective_date"] == "2026-09-30"

    validate_error(
        api.drop_enrollment(
            enrollment["id"], f.drop_payload("2026-10-15"), users.ROSTER_OPERATOR
        ),
        errors.ERR_ENROLLMENT_NOT_DROPPABLE,
        409,
    )

    unchanged = validate_success(
        api.get_enrollment(enrollment["id"], users.ROSTER_OPERATOR), 200
    )
    assert unchanged["roster_status"] == RosterStatus.PENDING_DROP
    assert unchanged["drop_effective_date"] == "2026-09-30"


def test_a_licence_can_only_be_activated_once(api):
    """A licence's seats are split across the district exactly once, never twice.

    "Activation requires license status of DRAFT, else
    ERR_VENDOR_APP_ALREADY_ACTIVATED." The first activation "moves status from
    DRAFT to ACTIVE, stamps activated_by_user_id with the activating officer's
    X-User-ID, increments the license's version, and splits the purchased seats
    across the district's eligible buildings, creating one building allocation per
    eligible building"; the refused second attempt must not re-split anything, so
    the single allocation still holds all four seats and the licence stays at
    version 2.

    Design: Corner/state_machines/vendor_app_activate_license_twice_rejected
    """
    world = fx.district_with_active_term(api, clock=c.CLOCK_STARTUP_DEFAULT)
    fx.create_student(api, world["school_id"], grade_level=4)
    vendor_app = fx.create_vendor_app(
        api,
        world["term_id"],
        total_seats=4,
        grade_band_scope=[GradeBand.ELEMENTARY],
        overage_policy=OveragePolicy.BLOCK,
    )
    assert vendor_app["status"] == VendorAppStatus.DRAFT

    activated = validate_success(
        api.activate_license(vendor_app["id"], users.DATA_GOVERNANCE_OFFICER), 200
    )
    assert activated["status"] == VendorAppStatus.ACTIVE
    assert activated["activated_by_user_id"] == users.DATA_GOVERNANCE_OFFICER_ID
    assert activated["version"] == 2
    assert_seat_counters(activated, consumed_seats=0, unallocated_seats=0)

    validate_error(
        api.activate_license(vendor_app["id"], users.DATA_GOVERNANCE_OFFICER),
        errors.ERR_VENDOR_APP_ALREADY_ACTIVATED,
        409,
    )

    allocations = fx.list_allocations(api, vendor_app["id"])
    assert len(allocations) == 1
    assert allocations[0]["allocated_seats"] == 4
    assert allocations[0]["school_id"] == world["school_id"]

    unchanged = fx.read_vendor_app(api, vendor_app["id"])
    assert unchanged["status"] == VendorAppStatus.ACTIVE
    assert unchanged["version"] == 2


def test_a_suspended_licence_provisions_nothing_and_resumes_cleanly(api):
    """Pausing a licence freezes new provisioning without disturbing the seats already held.

    "An ACTIVE license may be suspended, which moves it to SUSPENDED: while
    suspended, new account provisioning is refused with ERR_VENDOR_APP_NOT_ACTIVE,
    but every existing account keeps its seat_status and its identity_status
    untouched. A SUSPENDED license may be resumed back to ACTIVE, and this loop is
    legal and repeatable... Both transitions increment the license's version." On
    the way back "the allocation guard is re-evaluated", and because the four
    allocated seats still fit the purchased four, the resume is accepted and the
    second student can be provisioned.

    Design: Corner/state_machines/vendor_app_suspend_then_reactivate_cycle
    """
    world = fx.district_with_active_term(api, clock=c.CLOCK_STARTUP_DEFAULT)
    first_student, second_student = fx.create_students(
        api, world["school_id"], 2, grade_level=4
    )
    vendor_app = fx.create_vendor_app(
        api,
        world["term_id"],
        total_seats=4,
        grade_band_scope=[GradeBand.ELEMENTARY],
    )
    active = fx.activate_license(api, vendor_app["id"])
    allocation = fx.allocation_for_school(
        api, vendor_app["id"], world["school_id"]
    )
    held_account = fx.provision_account(
        api,
        allocation["id"],
        vendor_app_id=vendor_app["id"],
        student_id=first_student["id"],
    )

    suspended = validate_success(
        api.update_vendor_app(
            vendor_app["id"],
            f.vendor_app_patch(status=VendorAppStatus.SUSPENDED),
            users.DATA_GOVERNANCE_OFFICER,
        ),
        200,
    )
    assert suspended["status"] == VendorAppStatus.SUSPENDED
    assert suspended["version"] > active["version"]

    validate_error(
        api.create_app_account(
            f.app_account_payload(
                allocation["id"],
                suspended["version"],
                student_id=second_student["id"],
            ),
            users.IDENTITY_ADMIN,
        ),
        errors.ERR_VENDOR_APP_NOT_ACTIVE,
        409,
    )

    still_seated = fx.read_account(api, held_account["id"])
    assert_account_axes(
        still_seated,
        seat_status=SeatStatus.RESERVED,
        identity_status=IdentityStatus.PENDING_PROVISION,
    )

    resumed = validate_success(
        api.update_vendor_app(
            vendor_app["id"],
            f.vendor_app_patch(status=VendorAppStatus.ACTIVE),
            users.DATA_GOVERNANCE_OFFICER,
        ),
        200,
    )
    assert resumed["status"] == VendorAppStatus.ACTIVE
    assert resumed["version"] == suspended["version"] + 1
    assert fx.read_allocation(api, allocation["id"])["allocated_seats"] == 4

    second_account = validate_success(
        api.create_app_account(
            f.app_account_payload(
                allocation["id"],
                resumed["version"],
                student_id=second_student["id"],
            ),
            users.IDENTITY_ADMIN,
        ),
        201,
    )
    assert second_account["student_id"] == second_student["id"]
    assert fx.read_vendor_app(api, vendor_app["id"])["consumed_seats"] == 2


def test_usage_reports_of_no_minutes_leave_the_seat_merely_reserved(api):
    """A licensed seat nobody has actually used stays reserved, however often the vendor reports in.

    "When the reported active_minutes is greater than zero and the seat axis is
    still RESERVED, the seat advances to ACTIVE... A report of zero active_minutes
    leaves seat_status exactly where it was." The report still lands: the account's
    "active_minutes_total grows by the reported active_minutes, its session_count
    grows by the reported sessions, and its last_activity_date is overwritten with
    the reported activity_date". Telemetry never touches the identity axis, so the
    identity remains PENDING_PROVISION with its temporary password intact.

    Design: Corner/state_machines/app_account_record_usage_zero_minutes_leaves_seat_reserved
    """
    world = fx.seated_account(
        api, clock=c.CLOCK_IN_WINDOW, grade_level=4, total_seats=4
    )
    account_id = world["account_id"]
    assert_account_axes(
        world["account"],
        seat_status=SeatStatus.RESERVED,
        identity_status=IdentityStatus.PENDING_PROVISION,
        password_state=PasswordState.TEMP_SET,
    )

    first = validate_success(
        api.record_usage(
            account_id,
            f.usage_payload("2026-08-19", 0, session_count=1),
            users.IDENTITY_ADMIN,
        ),
        200,
    )
    assert_account_axes(
        first,
        seat_status=SeatStatus.RESERVED,
        identity_status=IdentityStatus.PENDING_PROVISION,
        password_state=PasswordState.TEMP_SET,
    )
    assert first["active_minutes_total"] == 0
    assert first["session_count"] == 1
    assert first["last_activity_date"] == "2026-08-19"

    second = validate_success(
        api.record_usage(
            account_id,
            f.usage_payload("2026-08-20", 0, session_count=2),
            users.IDENTITY_ADMIN,
        ),
        200,
    )
    assert_account_axes(
        second,
        seat_status=SeatStatus.RESERVED,
        identity_status=IdentityStatus.PENDING_PROVISION,
        password_state=PasswordState.TEMP_SET,
    )
    assert second["active_minutes_total"] == 0
    assert second["session_count"] == 3
    assert second["last_activity_date"] == "2026-08-20"

    reserved, meta = validate_paginated(
        api.list_app_accounts(
            users.IDENTITY_ADMIN,
            building_allocation_id=world["allocation_id"],
            seat_status=SeatStatus.RESERVED,
        )
    )
    assert meta["total_count"] == 1
    assert_ids_equal(reserved, [account_id], "reserved seats")


def test_a_seat_given_back_cannot_be_given_back_twice(api):
    """A refunded seat is returned to the pool once; a second release attempt is refused.

    Releasing a seat moves "the seat axis from RESERVED or ACTIVE to RELEASED (a
    second attempt on an already-released seat is ERR_SEAT_ALREADY_RELEASED),
    refunded_charge_cents is set to the account's seat_charge_cents when the clock
    date is on or before the term's add_drop_cutoff_date... the owning allocation's
    consumed_seats is decremented by one and the license's consumed_seats,
    unallocated_seats, committed_charge_cents... are recomputed". Because
    "identity_status is deliberately left alone", the identity stays exactly where
    it was, and committed money nets to zero once the full seat charge is refunded.

    Design: Corner/state_machines/app_account_release_twice_rejected
    """
    world = fx.seated_account(
        api, clock=c.CLOCK_IN_WINDOW, grade_level=4, total_seats=4
    )
    account_id = world["account_id"]
    assert world["account"]["seat_charge_cents"] == c.STANDARD_PRICE_PER_SEAT_CENTS
    assert world["account"]["refunded_charge_cents"] == 0

    released = validate_success(
        api.release_seat(account_id, users.IDENTITY_ADMIN), 200
    )
    assert_account_axes(
        released,
        seat_status=SeatStatus.RELEASED,
        identity_status=IdentityStatus.PENDING_PROVISION,
    )
    assert released["refunded_charge_cents"] == c.STANDARD_PRICE_PER_SEAT_CENTS

    validate_error(
        api.release_seat(account_id, users.IDENTITY_ADMIN),
        errors.ERR_SEAT_ALREADY_RELEASED,
        409,
    )

    unchanged = fx.read_account(api, account_id)
    assert unchanged["seat_status"] == SeatStatus.RELEASED
    assert unchanged["refunded_charge_cents"] == c.STANDARD_PRICE_PER_SEAT_CENTS

    assert fx.read_allocation(api, world["allocation_id"])["consumed_seats"] == 0
    assert_seat_counters(
        fx.read_vendor_app(api, world["vendor_app_id"]),
        consumed_seats=0,
        committed_charge_cents=0,
    )


def test_opening_a_fresh_run_supersedes_the_held_one_and_dismisses_its_triage(api):
    """A new extract pre-empts the run it replaces, clearing that run's triage queue.

    "Opening a run is also an act of pre-emption: every other run of the same
    license sitting in EXTRACTED, TRANSFORMED or HELD becomes SUPERSEDED, and each
    of those runs' OPEN triage items becomes DISMISSED with resolution_note set to
    `run superseded` and with resolved_by_user_id left null, after which those runs'
    blocking_error_count and advisory_error_count recompute to zero. A SUPERSEDED
    run is inert: transforming it, publishing it, or resolving one of its items is
    refused with ERR_SYNC_RUN_SUPERSEDED."

    Design: Corner/state_machines/sync_run_superseded_by_newer_run_dismisses_items_and_rejects_transform
    """
    world = _run_held_by_an_unmatched_teacher(api)
    held = world["run"]
    assert held["state"] == SyncRunState.HELD
    assert held["blocking_error_count"] == 1

    items = fx.queue_items(
        api, held["id"], category=ErrorCategory.UNMATCHED_TEACHER
    )
    assert len(items) == 1
    item = items[0]
    assert item["status"] == ErrorQueueItemStatus.OPEN

    newer = validate_success(
        api.create_sync_run(
            f.sync_run_payload(world["vendor_app_id"], run_type=RunType.DELTA),
            users.ROSTER_OPERATOR,
        ),
        201,
    )
    assert newer["state"] == SyncRunState.EXTRACTED

    superseded = fx.read_run(api, held["id"])
    assert superseded["state"] == SyncRunState.SUPERSEDED
    assert superseded["blocking_error_count"] == 0
    assert superseded["advisory_error_count"] == 0

    dismissed = validate_success(
        api.get_error_queue_item(item["id"], users.DATA_GOVERNANCE_OFFICER), 200
    )
    assert dismissed["status"] == ErrorQueueItemStatus.DISMISSED
    assert dismissed["resolution_note"] == "run superseded"
    assert dismissed["resolved_by_user_id"] is None

    validate_error(
        api.transform_sync_run(held["id"], users.ROSTER_OPERATOR),
        errors.ERR_SYNC_RUN_SUPERSEDED,
        409,
    )

    stale_runs, meta = validate_paginated(
        api.list_sync_runs(
            users.ROSTER_OPERATOR,
            vendor_app_id=world["vendor_app_id"],
            state=SyncRunState.SUPERSEDED,
        )
    )
    assert meta["total_count"] == 1
    assert_ids_equal(stale_runs, [held["id"]], "superseded runs")


def test_a_roster_cannot_be_published_before_it_has_been_transformed(api):
    """The district cannot hand a vendor a roster that has not been through transformation.

    "Publishing... is a DataGovernanceOfficer action on a run that must be
    TRANSFORMED (ERR_SYNC_RUN_STATE_INVALID)", and a freshly opened run "is created
    in EXTRACTED... with published_at and published_by_user_id null and
    transform_count zero". The refusal leaves the run exactly where it was, with no
    publication stamps written and the licence's sync_health untouched.

    Design: Corner/state_machines/sync_run_publish_from_extracted_rejected
    """
    world = fx.licensed_building(
        api,
        clock=c.CLOCK_IN_WINDOW,
        student_count=1,
        grade_level=4,
        total_seats=4,
    )
    run = fx.open_sync_run(api, world["vendor_app_id"], run_type=RunType.FULL)
    assert run["state"] == SyncRunState.EXTRACTED
    assert run["initiated_by_user_id"] == users.ROSTER_OPERATOR_ID

    validate_error(
        api.publish_sync_run(run["id"], users.DATA_GOVERNANCE_OFFICER),
        errors.ERR_SYNC_RUN_STATE_INVALID,
        409,
    )

    unchanged = fx.read_run(api, run["id"])
    assert unchanged["state"] == SyncRunState.EXTRACTED
    assert unchanged["published_at"] is None
    assert unchanged["published_by_user_id"] is None
    assert unchanged["transform_count"] == 0
    assert unchanged["transformed_at"] is None

    assert fx.read_vendor_app(api, world["vendor_app_id"])["sync_health"] == (
        SyncHealth.OK
    )


def test_retiring_a_section_drops_its_roster_and_gives_the_seat_back(api):
    """Cancelling a class winds down its enrollments and refunds the licensed seat behind them.

    "Retiring a section by moving status to CANCELLED takes every enrollment of
    that section that is not already DROPPED to DROPPED, and each of those drops
    runs the same seat-release cascade described in §3.4." That cascade releases
    the student's account because the drop leaves the student with no remaining
    enrollment feeding this licence, sets "refunded_charge_cents to the account's
    seat_charge_cents when drop_effective_date is on or before the term's
    add_drop_cutoff_date", decrements the allocation's consumed_seats and
    recomputes the licence counters — while "identity_status is deliberately left
    alone", so the identity axis does not move.

    Design: Corner/state_machines/section_cancel_cascades_enrollments_and_releases_seats
    """
    world = _licensed_section_with_seated_student(api)

    cancelled = validate_success(
        api.update_section(
            world["section_id"],
            f.section_patch(status=SectionStatus.CANCELLED),
            users.ROSTER_OPERATOR,
        ),
        200,
    )
    assert cancelled["status"] == SectionStatus.CANCELLED
    assert cancelled["active_enrollment_count"] == 0
    assert cancelled["version"] > world["section"]["version"]

    enrollment = validate_success(
        api.get_enrollment(world["enrollment_id"], users.ROSTER_OPERATOR), 200
    )
    assert enrollment["roster_status"] == RosterStatus.DROPPED

    account = fx.read_account(api, world["account_id"])
    assert_account_axes(
        account,
        seat_status=SeatStatus.RELEASED,
        identity_status=IdentityStatus.PENDING_PROVISION,
    )
    assert account["refunded_charge_cents"] == c.STANDARD_PRICE_PER_SEAT_CENTS

    assert fx.read_allocation(api, world["allocation_id"])["consumed_seats"] == 0
    assert_seat_counters(
        fx.read_vendor_app(api, world["vendor_app_id"]),
        consumed_seats=0,
        committed_charge_cents=0,
        unallocated_seats=0,
    )


def test_summer_rollover_archives_the_class_and_parks_the_identity(api):
    """Rolling the year over archives the class, drops its roster and suspends the identity.

    Rollover sets "archived_access_expires_at... to the term's end_date plus its
    archive_retention_days, anchored at 00:00:00.000Z on that date"; every ACTIVE
    section of the term "becomes ARCHIVED"; every enrollment of those sections
    "becomes DROPPED with drop_effective_date stamped with the term's end_date"; and
    each drop releases the seat "with refunded_charge_cents set by the standard
    refund rule" — zero here, because 18 December falls after the add/drop cutoff —
    "and sets identity_status to SUSPENDED. Summer suspension is not
    deprovisioning: the identity is parked, not destroyed, password_state is left
    exactly as it was."

    Design: Corner/state_machines/term_rollover_archives_sections_and_suspends_identities
    """
    world = _licensed_section_with_seated_student(api, set_password=True)
    assert world["account"]["password_state"] == PasswordState.USER_SET

    fx.set_clock(api, "2026-12-18T09:00:00Z")
    rolled = validate_success(
        api.rollover_term(world["term_id"], users.DATA_GOVERNANCE_OFFICER), 200
    )
    assert rolled["state"] == TermState.ROLLED_OVER
    assert rolled["archived_access_expires_at"] == c.TERM_ARCHIVED_ACCESS_EXPIRES_AT
    assert rolled["version"] > world["term"]["version"]

    section = validate_success(
        api.get_section(world["section_id"], users.ROSTER_OPERATOR), 200
    )
    assert section["status"] == SectionStatus.ARCHIVED

    enrollment = validate_success(
        api.get_enrollment(world["enrollment_id"], users.ROSTER_OPERATOR), 200
    )
    assert enrollment["roster_status"] == RosterStatus.DROPPED
    assert enrollment["drop_effective_date"] == c.TERM_END_DATE

    account = fx.read_account(api, world["account_id"])
    assert_account_axes(
        account,
        seat_status=SeatStatus.RELEASED,
        identity_status=IdentityStatus.SUSPENDED,
        password_state=PasswordState.USER_SET,
    )
    assert account["refunded_charge_cents"] == 0

    assert fx.read_allocation(api, world["allocation_id"])["consumed_seats"] == 0
    assert_seat_counters(
        fx.read_vendor_app(api, world["vendor_app_id"]),
        consumed_seats=0,
        committed_charge_cents=c.STANDARD_PRICE_PER_SEAT_CENTS,
    )


def test_a_summer_password_reset_brings_a_parked_identity_back(api):
    """A password set after the summer suspension reactivates the identity without a new seat.

    A password set moves the identity axis "from SUSPENDED to PROVISIONED when the
    account is being reactivated after a summer suspension; password_state becomes
    USER_SET, failed_login_count is reset to zero, last_password_set_at is stamped
    with the clock instant, and password_expires_at is recomputed as
    last_password_set_at plus the subject building's password_max_age_days" — 180
    days by default. "The seat axis is not touched by a password set — which is
    precisely why password setting is exempt from the released-seat rung of §2.7 and
    a summer-suspended identity whose seat has already gone back can still be
    reactivated."

    Design: Corner/state_machines/app_account_password_set_after_rollover_reactivates_identity
    """
    world = _licensed_section_with_seated_student(api, set_password=True)

    fx.set_clock(api, "2026-12-18T09:00:00Z")
    fx.rollover_term(api, world["term_id"])
    suspended = fx.read_account(api, world["account_id"])
    assert_account_axes(
        suspended,
        seat_status=SeatStatus.RELEASED,
        identity_status=IdentityStatus.SUSPENDED,
        password_state=PasswordState.USER_SET,
    )

    reactivated = validate_success(
        api.set_password(
            world["account_id"],
            f.password_set_payload("SummerReset2027"),
            users.IDENTITY_ADMIN,
        ),
        200,
    )

    assert_account_axes(
        reactivated,
        seat_status=SeatStatus.RELEASED,
        identity_status=IdentityStatus.PROVISIONED,
        password_state=PasswordState.USER_SET,
    )
    assert reactivated["failed_login_count"] == 0
    assert reactivated["last_password_set_at"] == "2026-12-18T09:00:00.000Z"
    assert reactivated["password_expires_at"] == "2027-06-16T09:00:00.000Z"
    assert reactivated["refunded_charge_cents"] == 0

    assert fx.read_allocation(api, world["allocation_id"])["consumed_seats"] == 0


def test_an_unmatched_teacher_can_only_be_triaged_once(api):
    """Once a replacement teacher has been attached, the same triage item cannot be reworked.

    Attaching a replacement requires that "the item must have status of OPEN and
    category of UNMATCHED_TEACHER, else ERR_ERROR_QUEUE_ITEM_NOT_OPEN". On success
    "the subject section's primary_teacher_id is set to the replacement and its
    roster_health returns to OK, and the item moves from OPEN to RESOLVED_MATCHED
    with resolved_by_user_id stamped from the officer's X-User-ID, resolved_at
    stamped with the clock instant and resolution_note recorded when one was
    supplied. The run's blocking_error_count is recomputed — but the run stays
    HELD."

    Design: Corner/state_machines/error_queue_item_resolve_match_after_resolution_rejected
    """
    world = _run_held_by_an_unmatched_teacher(api, spare_teachers=2)
    first_choice, second_choice = world["spare_teachers"]
    held = world["run"]
    assert held["state"] == SyncRunState.HELD
    assert held["blocking_error_count"] == 1

    items = fx.queue_items(
        api,
        held["id"],
        category=ErrorCategory.UNMATCHED_TEACHER,
        status=ErrorQueueItemStatus.OPEN,
    )
    assert len(items) == 1
    item = items[0]
    assert item["severity"] == ErrorSeverity.BLOCKING
    assert item["subject_section_id"] == world["section_id"]

    resolved = validate_success(
        api.resolve_match(
            item["id"],
            f.resolve_match_payload(
                first_choice["id"], resolution_note="teacher of record confirmed"
            ),
            users.DATA_GOVERNANCE_OFFICER,
        ),
        200,
    )
    assert resolved["status"] == ErrorQueueItemStatus.RESOLVED_MATCHED
    assert resolved["resolved_by_user_id"] == users.DATA_GOVERNANCE_OFFICER_ID
    assert resolved["resolved_at"] == "2026-08-20T00:00:00.000Z"
    assert resolved["resolution_note"] == "teacher of record confirmed"

    validate_error(
        api.resolve_match(
            item["id"],
            f.resolve_match_payload(second_choice["id"]),
            users.DATA_GOVERNANCE_OFFICER,
        ),
        errors.ERR_ERROR_QUEUE_ITEM_NOT_OPEN,
        409,
    )

    section = validate_success(
        api.get_section(world["section_id"], users.ROSTER_OPERATOR), 200
    )
    assert section["primary_teacher_id"] == first_choice["id"]
    assert section["roster_health"] == RosterHealth.OK

    still_held = fx.read_run(api, held["id"])
    assert still_held["state"] == SyncRunState.HELD
    assert still_held["blocking_error_count"] == 0
