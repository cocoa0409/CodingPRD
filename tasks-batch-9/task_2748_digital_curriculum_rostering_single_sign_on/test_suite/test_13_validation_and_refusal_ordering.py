"""
Validation and the order in which the service refuses work.

The district's rules never fire in a convenient order — they fire in one fixed
order, and the request that breaks several of them at once must be told about the
first one only. These tests pin the refusals that matter to the people using the
system: a child added to the wrong building, a schedule change dated outside the
term, a chair that a pending departure has not freed, a password judged against
the child's own building policy, a building administrator reaching outside its own
building, a malformed body arriving with a stale concurrency token, a term whose
add/drop cutoff falls outside its own dates, and a seat re-cut that would either
oversell the licence or strand seats already in use.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_success,
)

from test_helpers import api_errors as errors
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.assertions import assert_account_axes
from test_helpers.types import (
    AddDropClass,
    GradeBand,
    IdentityStatus,
    PasswordState,
    RosterStatus,
    SeatStatus,
    TermState,
)


def test_child_cannot_be_added_to_a_section_in_a_different_building(api):
    """A Southmeadow child belongs in a Southmeadow section, not a Northside one.

    On an add "the student and the section must belong to the same building,
    comparing the student's `school_id` to the section's `school_id`, else
    `ERR_SCHOOL_MISMATCH`". Nothing earlier on the ladder is broken here — the term
    is `ACTIVE`, the child is `ENROLLED`, the date sits inside the term window and
    the child holds no other row to clash with — so the coherence rule is the one
    that fires, and the foreign section's roster is left untouched. Repeating the
    add against the child's own building succeeds, and because "a request whose
    effective date equals the clock date lands `ACTIVE`", both counters move to one.

    Design: Corner/validations/cross_entity_building_coherence_on_enrollment
    """
    fx.set_clock(api, c.CLOCK_IN_WINDOW)
    term = fx.create_active_term(api)
    northside = fx.create_school(api, grade_band=GradeBand.ELEMENTARY)
    southmeadow = fx.create_school(api, grade_band=GradeBand.ELEMENTARY)
    northside_teacher = fx.create_teacher(api, northside["id"])
    northside_section = fx.create_section(
        api, northside["id"], term["id"],
        primary_teacher_id=northside_teacher["id"], period_index=1, max_seats=10,
    )
    southmeadow_section = fx.create_section(
        api, southmeadow["id"], term["id"], period_index=1, max_seats=10,
    )
    child = fx.create_student(api, southmeadow["id"], grade_level=3)

    validate_error(
        api.create_enrollment(
            f.enrollment_payload(northside_section["id"], child["id"], "2026-08-20"),
            users.ROSTER_OPERATOR,
        ),
        errors.ERR_SCHOOL_MISMATCH,
        422,
    )
    foreign_section = validate_success(
        api.get_section(northside_section["id"], users.ROSTER_OPERATOR), 200
    )
    assert foreign_section["active_enrollment_count"] == 0

    enrollment = fx.create_enrollment(
        api, southmeadow_section["id"], child["id"], "2026-08-20"
    )
    assert enrollment["roster_status"] == RosterStatus.ACTIVE

    own_section = validate_success(
        api.get_section(southmeadow_section["id"], users.ROSTER_OPERATOR), 200
    )
    assert own_section["active_enrollment_count"] == 1
    enrolled_child = validate_success(
        api.get_student(child["id"], users.ROSTER_OPERATOR), 200
    )
    assert enrolled_child["active_enrollment_count"] == 1


def test_add_dated_after_the_term_is_refused_but_the_last_day_is_admitted(api):
    """A January start date is nonsense for a term that ends in December; the last day is not.

    "The `requested_effective_date` must fall inside the section's term window,
    from `start_date` through `end_date` inclusive, else
    `ERR_EFFECTIVE_DATE_OUT_OF_TERM`." The final day of the term is therefore
    admitted, and because it is still in the future the row "stays `PENDING_ADD`
    until a publish picks it up", with an `effective_date` "stamped from
    `requested_effective_date`" and an `add_drop_class` of `LATE_ADD` since the
    stamped date is past the add/drop cutoff.

    Design: Corner/validations/temporal_effective_date_out_of_term_rejected
    """
    world = fx.district_with_active_term(api, clock=c.CLOCK_IN_WINDOW)
    teacher = fx.create_teacher(api, world["school_id"])
    section = fx.create_section(
        api, world["school_id"], world["term_id"],
        primary_teacher_id=teacher["id"], max_seats=10,
    )
    child = fx.create_student(api, world["school_id"], grade_level=3)

    validate_error(
        api.create_enrollment(
            f.enrollment_payload(section["id"], child["id"], "2027-01-05"),
            users.ROSTER_OPERATOR,
        ),
        errors.ERR_EFFECTIVE_DATE_OUT_OF_TERM,
        422,
    )

    last_day_add = fx.create_enrollment(
        api, section["id"], child["id"], c.TERM_END_DATE
    )
    assert last_day_add["roster_status"] == RosterStatus.PENDING_ADD
    assert last_day_add["effective_date"] == "2026-12-18"
    assert last_day_add["add_drop_class"] == AddDropClass.LATE_ADD


def test_pending_departure_does_not_free_a_chair_but_the_drop_itself_does(api):
    """A child who leaves at the end of September is still occupying a desk in August.

    "The section must have a free physical seat: its `active_enrollment_count` must
    be strictly less than its `max_seats`, else `ERR_SECTION_AT_CAPACITY`", and that
    count "includes `PENDING_ADD` and `ACTIVE` rows but not `PENDING_DROP` or
    `DROPPED` ones, so a pending drop does not free a chair". A future-dated drop
    leaves the departing row `PENDING_DROP`, which does take it
    out of the section's count, so the third child who was turned away moments
    earlier now fits — and the departing row is still on file, three rows in all.

    Design: Corner/validations/aggregate_section_capacity_excludes_pending_drop
    """
    world = fx.district_with_active_term(api, clock=c.CLOCK_IN_WINDOW)
    teacher = fx.create_teacher(api, world["school_id"])
    section = fx.create_section(
        api, world["school_id"], world["term_id"],
        primary_teacher_id=teacher["id"], max_seats=2,
    )
    children = fx.create_students(api, world["school_id"], 3, grade_level=3)

    first_row = fx.create_enrollment(api, section["id"], children[0]["id"], "2026-08-20")
    fx.create_enrollment(api, section["id"], children[1]["id"], "2026-08-20")
    full_section = validate_success(
        api.get_section(section["id"], users.ROSTER_OPERATOR), 200
    )
    assert full_section["active_enrollment_count"] == 2

    validate_error(
        api.create_enrollment(
            f.enrollment_payload(section["id"], children[2]["id"], "2026-08-20"),
            users.ROSTER_OPERATOR,
        ),
        errors.ERR_SECTION_AT_CAPACITY,
        409,
    )

    departing = fx.drop_enrollment(api, first_row["id"], "2026-09-30")
    assert departing["roster_status"] == RosterStatus.PENDING_DROP
    freed_section = validate_success(
        api.get_section(section["id"], users.ROSTER_OPERATOR), 200
    )
    assert freed_section["active_enrollment_count"] == 1

    admitted = fx.create_enrollment(
        api, section["id"], children[2]["id"], "2026-08-20"
    )
    assert admitted["roster_status"] == RosterStatus.ACTIVE
    refilled_section = validate_success(
        api.get_section(section["id"], users.ROSTER_OPERATOR), 200
    )
    assert refilled_section["active_enrollment_count"] == 2

    rows = validate_success(
        api.list_enrollments(users.ROSTER_OPERATOR, section_id=section["id"], limit=100),
        200,
    )
    assert len(rows) == 3


def test_password_complexity_is_judged_against_the_child_s_own_building_policy(api):
    """The same all-lower-case password fails at Northside and passes at Southmeadow.

    Password policy is carried "per building rather than centrally, because a K–2
    primary school and a comprehensive high school do not tolerate the same rules",
    and the complexity rung reads "when the subject building's
    `password_requires_mixed_case` is true, `new_password` contains at least one
    lower-case and at least one upper-case letter, else `ERR_PASSWORD_COMPLEXITY`".
    A refused set leaves the identity exactly where it was, still awaiting
    provisioning on its temporary credential. The building that switched mixed case
    off accepts the very same password, which "advances `identity_status` to
    `PROVISIONED`", sets `password_state` to `USER_SET`, resets the failed-login
    tally and carries the account forward by the building's 180-day maximum age.

    Design: Corner/validations/conditional_password_complexity_depends_on_subject_building
    """
    fx.set_clock(api, c.CLOCK_IN_WINDOW)
    term = fx.create_active_term(api)
    strict_building = fx.create_school(api, grade_band=GradeBand.ELEMENTARY)
    relaxed_building = fx.create_school(
        api, grade_band=GradeBand.ELEMENTARY, password_requires_mixed_case=False
    )
    strict_child = fx.create_student(api, strict_building["id"], grade_level=3)
    relaxed_child = fx.create_student(api, relaxed_building["id"], grade_level=3)

    vendor_app = fx.create_vendor_app(
        api, term["id"], total_seats=4, grade_band_scope=[GradeBand.ELEMENTARY]
    )
    vendor_app = fx.activate_license(api, vendor_app["id"])
    strict_allocation = fx.allocation_for_school(
        api, vendor_app["id"], strict_building["id"]
    )
    relaxed_allocation = fx.allocation_for_school(
        api, vendor_app["id"], relaxed_building["id"]
    )
    strict_account = fx.provision_account(
        api, strict_allocation["id"],
        vendor_app_id=vendor_app["id"], student_id=strict_child["id"],
    )
    relaxed_account = fx.provision_account(
        api, relaxed_allocation["id"],
        vendor_app_id=vendor_app["id"], student_id=relaxed_child["id"],
    )

    validate_error(
        api.set_password(
            strict_account["id"],
            f.password_set_payload(c.LOWERCASE_ONLY_PASSWORD),
            users.IDENTITY_ADMIN,
        ),
        errors.ERR_PASSWORD_COMPLEXITY,
        422,
    )
    refused = fx.read_account(api, strict_account["id"])
    assert_account_axes(
        refused,
        seat_status=SeatStatus.RESERVED,
        identity_status=IdentityStatus.PENDING_PROVISION,
        password_state=PasswordState.TEMP_SET,
    )

    accepted = fx.set_account_password(
        api, relaxed_account["id"], c.LOWERCASE_ONLY_PASSWORD
    )
    assert_account_axes(
        accepted,
        seat_status=SeatStatus.RESERVED,
        identity_status=IdentityStatus.PROVISIONED,
        password_state=PasswordState.USER_SET,
    )
    assert accepted["failed_login_count"] == 0
    assert accepted["password_expires_at"] == "2027-02-16T00:00:00.000Z"


def test_short_all_lower_case_password_reports_its_length_not_its_complexity(api):
    """A four-character password is rejected for being short, not for lacking capitals.

    The ladder settles this explicitly: "the supplied `new_password` is at least as
    long as the subject building's `min_password_length`, else
    `ERR_PASSWORD_TOO_SHORT`", and only then "when the subject building's
    `password_requires_mixed_case` is true ... else `ERR_PASSWORD_COMPLEXITY`;
    because length is checked at rung 23, a short all-lower-case password reports
    `ERR_PASSWORD_TOO_SHORT` and not `ERR_PASSWORD_COMPLEXITY`". A refused set
    writes nothing at all, so `last_password_set_at` is still null, and a compliant
    password then carries the identity to `PROVISIONED`.

    Design: Corner/validations/password_length_beats_complexity_ordering
    """
    world = fx.seated_account(api, total_seats=4)

    validate_error(
        api.set_password(
            world["account_id"],
            f.password_set_payload("ab7c"),
            users.IDENTITY_ADMIN,
        ),
        errors.ERR_PASSWORD_TOO_SHORT,
        422,
    )
    untouched = fx.read_account(api, world["account_id"])
    assert_account_axes(
        untouched,
        seat_status=SeatStatus.RESERVED,
        identity_status=IdentityStatus.PENDING_PROVISION,
        password_state=PasswordState.TEMP_SET,
    )
    assert untouched["last_password_set_at"] is None

    accepted = fx.set_account_password(api, world["account_id"], c.VALID_PASSWORD)
    assert_account_axes(
        accepted,
        identity_status=IdentityStatus.PROVISIONED,
        password_state=PasswordState.USER_SET,
    )


def test_building_admin_reaching_outside_its_building_is_told_it_is_out_of_scope(api):
    """A Northside administrator learns nothing about seats it does not administer.

    A `BuildingLicenseAdmin` "may therefore re-cut the seat allocation of its own
    building and no other", and the ladder places that scope binding in the
    authorization tier — "(3) Scope binding for the two scoped roles, else
    `ERR_SCOPE_VIOLATION` — this guards exactly five operations: ... re-cutting a
    building allocation" — ahead of the existence tier, where "(5) Path identifiers
    resolve left to right, else the matching not-found error". A probe at an
    unknown allocation and a probe at a sibling building therefore both answer out
    of scope rather than not found, neither writes anything, and the licence's own
    version does not move until the administrator re-cuts its own building.

    Design: Corner/validations/scope_violation_beats_existence_on_building_allocation_patch
    """
    world = fx.licensed_district(
        api,
        buildings=[{"student_count": 1}, {"student_count": 1}],
        total_seats=4,
    )
    own_building_id, sibling_building_id = world["school_ids"]
    own_allocation = world["allocations_by_school"][own_building_id]
    sibling_allocation = world["allocations_by_school"][sibling_building_id]
    assert own_allocation["allocated_seats"] == 2
    assert sibling_allocation["allocated_seats"] == 2

    building_admin = users.building_license_admin(own_building_id)
    observed_version = fx.vendor_app_version(api, world["vendor_app_id"])

    validate_error(
        api.update_building_allocation(
            NON_EXISTENT_UUID,
            f.allocation_patch(1, observed_version),
            building_admin,
        ),
        errors.ERR_SCOPE_VIOLATION,
        403,
    )
    validate_error(
        api.update_building_allocation(
            sibling_allocation["id"],
            f.allocation_patch(1, observed_version),
            building_admin,
        ),
        errors.ERR_SCOPE_VIOLATION,
        403,
    )
    assert fx.read_allocation(api, sibling_allocation["id"])["allocated_seats"] == 2
    assert fx.vendor_app_version(api, world["vendor_app_id"]) == observed_version

    recut = validate_success(
        api.update_building_allocation(
            own_allocation["id"],
            f.allocation_patch(1, observed_version),
            building_admin,
        ),
        200,
    )
    assert recut["allocated_seats"] == 1

    licence = fx.read_vendor_app(api, world["vendor_app_id"])
    assert licence["unallocated_seats"] == 1
    assert licence["version"] == observed_version + 1


def test_malformed_provisioning_body_is_reported_before_its_stale_seat_token(api):
    """A body naming a parent as the subject is malformed first and out of date second.

    Provisioning "carries ... a `subject_type` of either `STUDENT` or `TEACHER`",
    and the ladder screens the request shape in the existence tier — "(6) Request
    shape, else `ERR_INVALID_REQUEST`; this applies to every write" — one tier ahead
    of concurrency, where "(8) `expected_vendor_app_version` matches the governing
    licence's `version`, else `ERR_STALE_VENDOR_APP_VERSION`". A request that is both
    malformed and holding an out-of-date view of the licence must therefore be told
    its body is wrong. Repair only the body and the same token now reports itself
    stale, and neither attempt consumes a seat.

    Design: Corner/validations/invalid_request_beats_stale_version_on_app_account_create
    """
    world = fx.licensed_building(api, student_count=1, total_seats=4)
    stale_version = fx.vendor_app_version(api, world["vendor_app_id"])

    validate_success(
        api.update_vendor_app(
            world["vendor_app_id"],
            f.vendor_app_patch(total_seats=5),
            users.VENDOR_INTEGRATION_MANAGER,
        ),
        200,
    )
    assert fx.vendor_app_version(api, world["vendor_app_id"]) == stale_version + 1

    validate_error(
        api.create_app_account(
            f.app_account_payload(
                world["allocation_id"], stale_version,
                student_id=world["student_id"], subject_type="PARENT",
            ),
            users.IDENTITY_ADMIN,
        ),
        errors.ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api.create_app_account(
            f.app_account_payload(
                world["allocation_id"], stale_version,
                student_id=world["student_id"],
            ),
            users.IDENTITY_ADMIN,
        ),
        errors.ERR_STALE_VENDOR_APP_VERSION,
        412,
    )

    assert fx.accounts_of_allocation(api, world["allocation_id"]) == []
    assert fx.read_allocation(api, world["allocation_id"])["consumed_seats"] == 0


def test_term_cutoff_outside_its_own_dates_is_refused_and_the_start_date_is_allowed(api):
    """A term cannot close its add/drop window before it opens or after it ends.

    "The three dates must be ordered so that the start is on or before the cutoff
    and the cutoff is on or before the end; a term whose dates violate that ordering
    is refused with `ERR_TERM_DATE_ORDER`." Both floors are inclusive, so a cutoff
    a week past the end date and a cutoff nine days before the start date are both
    refused, while a cutoff landing exactly on the start date is admitted — and
    "terms are created in `PLANNED` state". The two refusals persist nothing, so the
    district is left holding exactly one term.

    Design: Corner/validations/term_date_order_rejected
    """
    fx.set_clock(api, c.CLOCK_BEFORE_TERM)

    validate_error(
        api.create_term(
            f.term_payload(add_drop_cutoff_date="2026-12-25"), users.ROSTER_OPERATOR
        ),
        errors.ERR_TERM_DATE_ORDER,
        422,
    )
    validate_error(
        api.create_term(
            f.term_payload(add_drop_cutoff_date="2026-08-01"), users.ROSTER_OPERATOR
        ),
        errors.ERR_TERM_DATE_ORDER,
        422,
    )

    term = validate_success(
        api.create_term(
            f.term_payload(add_drop_cutoff_date=c.TERM_START_DATE),
            users.ROSTER_OPERATOR,
        ),
        201,
    )
    assert term["state"] == TermState.PLANNED
    assert term["add_drop_cutoff_date"] == "2026-08-10"

    persisted = validate_success(api.list_terms(users.ROSTER_OPERATOR, limit=100), 200)
    assert len(persisted) == 1


def test_seat_recut_may_neither_oversell_the_licence_nor_strand_a_seat_in_use(api):
    """Seats already in a child's hands cannot be reclaimed by arithmetic.

    A re-cut is bounded on both sides: "a re-cut upward must keep the sum of
    `allocated_seats` plus the sum of `borrowed_seats` across all of that licence's
    allocations no greater than the licence's `total_seats`, else
    `ERR_ALLOCATION_EXCEEDS_LICENSE`. A re-cut downward must leave `allocated_seats`
    no lower than that building's own `consumed_seats`, because seats already in use
    cannot be reclaimed by arithmetic, else `ERR_ALLOCATION_BELOW_CONSUMED`." The
    one value that satisfies both bounds is admitted, and "on success the
    allocation's `allocated_seats` is overwritten ... and the licence's
    `unallocated_seats` is recomputed with the licence's own `version` incremented as
    well" — so only the successful re-cut moves the version.

    Design: Corner/validations/building_allocation_patch_stays_inside_license_and_above_consumed
    """
    world = fx.licensed_district(
        api,
        buildings=[{"student_count": 1}, {"student_count": 1}],
        total_seats=4,
    )
    recut_building_id = world["school_ids"][0]
    allocation = world["allocations_by_school"][recut_building_id]
    assert allocation["allocated_seats"] == 2

    seated_child = world["students_by_school"][recut_building_id][0]
    fx.provision_account(
        api, allocation["id"],
        vendor_app_id=world["vendor_app_id"], student_id=seated_child["id"],
    )
    observed_version = fx.vendor_app_version(api, world["vendor_app_id"])

    validate_error(
        api.update_building_allocation(
            allocation["id"],
            f.allocation_patch(3, observed_version),
            users.DATA_GOVERNANCE_OFFICER,
        ),
        errors.ERR_ALLOCATION_EXCEEDS_LICENSE,
        409,
    )
    validate_error(
        api.update_building_allocation(
            allocation["id"],
            f.allocation_patch(0, observed_version),
            users.DATA_GOVERNANCE_OFFICER,
        ),
        errors.ERR_ALLOCATION_BELOW_CONSUMED,
        409,
    )
    assert fx.vendor_app_version(api, world["vendor_app_id"]) == observed_version

    recut = validate_success(
        api.update_building_allocation(
            allocation["id"],
            f.allocation_patch(1, observed_version),
            users.DATA_GOVERNANCE_OFFICER,
        ),
        200,
    )
    assert recut["allocated_seats"] == 1
    assert recut["consumed_seats"] == 1

    licence = fx.read_vendor_app(api, world["vendor_app_id"])
    assert licence["unallocated_seats"] == 1
    assert licence["version"] == observed_version + 1
