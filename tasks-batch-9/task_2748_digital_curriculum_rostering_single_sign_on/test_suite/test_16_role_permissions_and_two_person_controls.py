"""
Who may act, on whose licence, and never alone.

The district runs five roles over one rostering pipeline, and the boundaries
between them are deliberately uneven: the identity administrator owns the single
sign-on axis and nothing on the roster axis, the SIS steward owns every roster
row yet may not mint an account against it, a vendor integration manager is
fenced inside the licences it registered, a building administrator sees the money
view of a licence but never the student-level feed, and the two most consequential
acts of the whole service — activating a licence and publishing a roster — are
refused when the same human tries to do both halves.

These tests exercise those boundaries against a live service over HTTP.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as errors
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.constants import (
    CLOCK_IN_WINDOW,
    STANDARD_PRICE_PER_SEAT_CENTS,
    VALID_PASSWORD,
)
from test_helpers.types import (
    EnrollmentState,
    GradeBand,
    IdentityStatus,
    MeetingDay,
    PasswordState,
    RenewalBasis,
    RosterStatus,
    SyncHealth,
    SyncRunState,
    VendorAppStatus,
)


def test_identity_administrator_may_neither_open_a_section_nor_withdraw_a_student(api):
    """The single sign-on administrator is powerless on the roster axis.

    Section creation is a `RosterOperator` operation and recording a withdrawal is
    a `DataGovernanceOfficer` operation; the contract refuses a request whose
    `X-User-Role` "is not among the roles the target endpoint admits" with
    `ERR_ROLE_NOT_PERMITTED` (HTTP 403), and that check sits at rung 2 of the
    refusal ladder, ahead of every existence and state rule. The refusal is
    therefore about the role and nothing else: the identical section body from a
    `RosterOperator` is accepted, and the refused withdrawal leaves the student
    `ENROLLED`.

    Design: Corner/rbac/identity_admin_cannot_perform_roster_operator_and_governance_exclusives
    """
    world = fx.district_with_active_term(api, clock=CLOCK_IN_WINDOW)
    student = fx.create_student(api, world["school_id"], grade_level=4)

    section_body = f.section_payload(
        world["school_id"],
        world["term_id"],
        period_index=3,
        meeting_days=list(MeetingDay.MWF),
        max_seats=5,
    )

    refused_section = api.create_section(section_body, users.IDENTITY_ADMIN)
    validate_error(refused_section, errors.ERR_ROLE_NOT_PERMITTED, 403)

    refused_withdrawal = api.withdraw_student(
        student["id"],
        f.withdrawal_payload("2026-08-20"),
        users.IDENTITY_ADMIN,
    )
    validate_error(refused_withdrawal, errors.ERR_ROLE_NOT_PERMITTED, 403)

    still_enrolled = validate_success(api.get_student(student["id"], users.ROSTER_OPERATOR))
    assert still_enrolled["enrollment_state"] == EnrollmentState.ENROLLED
    assert still_enrolled["withdrawal_effective_date"] is None

    accepted_section = api.create_section(section_body, users.ROSTER_OPERATOR)
    created = validate_success(accepted_section, 201)
    assert created["school_id"] == world["school_id"]
    assert created["term_id"] == world["term_id"]

    rows, meta = validate_paginated(api.list_sections(users.ROSTER_OPERATOR))
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [created["id"]]


def test_sis_steward_may_read_an_app_account_but_never_provision_or_reset_one(api):
    """Identity provisioning is fenced off from the roster steward that feeds it.

    Provisioning an account and setting its password are both `IdentityAdmin`
    operations — the contract calls that role "the only role that may set an
    account password, which is also the act that advances the identity axis from
    `PENDING_PROVISION` to `PROVISIONED`" — so a `RosterOperator` is refused with
    `ERR_ROLE_NOT_PERMITTED` (HTTP 403) on both. Because the role check is rung 2
    it fires ahead of the one-seat-per-subject rule at rung 38 that would also
    have refused this duplicate subject. Reading the same account stays shared
    with every role.

    Design: Corner/rbac/roster_operator_cannot_provision_or_password_set_app_accounts
    """
    world = fx.seated_account(
        api,
        clock=CLOCK_IN_WINDOW,
        grade_level=4,
        total_seats=4,
        price_per_seat_cents=STANDARD_PRICE_PER_SEAT_CENTS,
    )
    licence_version = fx.vendor_app_version(api, world["vendor_app_id"])

    refused_provision = api.create_app_account(
        f.app_account_payload(
            world["allocation_id"], licence_version, student_id=world["student_id"]
        ),
        users.ROSTER_OPERATOR,
    )
    validate_error(refused_provision, errors.ERR_ROLE_NOT_PERMITTED, 403)

    refused_password = api.set_password(
        world["account_id"], f.password_set_payload(VALID_PASSWORD), users.ROSTER_OPERATOR
    )
    validate_error(refused_password, errors.ERR_ROLE_NOT_PERMITTED, 403)

    shared_read = validate_success(
        api.get_app_account(world["account_id"], users.ROSTER_OPERATOR)
    )
    assert shared_read["id"] == world["account_id"]
    assert shared_read["password_state"] == PasswordState.TEMP_SET
    assert shared_read["identity_status"] == IdentityStatus.PENDING_PROVISION

    accepted_password = validate_success(
        api.set_password(
            world["account_id"],
            f.password_set_payload(VALID_PASSWORD),
            users.IDENTITY_ADMIN,
        )
    )
    assert accepted_password["password_state"] == PasswordState.USER_SET
    assert accepted_password["identity_status"] == IdentityStatus.PROVISIONED


def test_a_second_vendor_manager_is_locked_out_of_a_licence_it_did_not_register(api):
    """A vendor integration manager reaches only the licences it registered itself.

    The contract binds an operator acting as `VendorIntegrationManager` "to exactly
    those licenses whose `created_by_user_id` equals its `X-User-ID`", and states
    that "amending a license, reading a license's roster feed, reading a license's
    renewal summary, and posting usage telemetry for an account under that license
    are all refused with `ERR_SCOPE_VIOLATION` when the governing license was
    registered by somebody else". Registering a brand-new licence "always passes
    this check, because that is the act which establishes the binding", and the
    registering manager's own amendment lands, so the licence was patchable all
    along.

    Design: Corner/rbac/vendor_integration_manager_cannot_touch_foreign_license
    """
    world = fx.licensed_building(
        api,
        clock=CLOCK_IN_WINDOW,
        student_count=0,
        total_seats=4,
        price_per_seat_cents=STANDARD_PRICE_PER_SEAT_CENTS,
    )
    vendor_app_id = world["vendor_app_id"]

    foreign_patch = api.update_vendor_app(
        vendor_app_id, f.vendor_app_patch(total_seats=9), users.VENDOR_INTEGRATION_MANAGER_2
    )
    validate_error(foreign_patch, errors.ERR_SCOPE_VIOLATION, 403)

    unchanged = validate_success(api.get_vendor_app(vendor_app_id, users.ROSTER_OPERATOR))
    assert unchanged["total_seats"] == 4
    assert unchanged["created_by_user_id"] == users.VENDOR_INTEGRATION_MANAGER_ID

    foreign_feed = api.get_roster_feed(vendor_app_id, users.VENDOR_INTEGRATION_MANAGER_2)
    validate_error(foreign_feed, errors.ERR_SCOPE_VIOLATION, 403)

    foreign_renewal = api.get_renewal_summary(
        vendor_app_id, users.VENDOR_INTEGRATION_MANAGER_2
    )
    validate_error(foreign_renewal, errors.ERR_SCOPE_VIOLATION, 403)

    own_registration = validate_success(
        api.create_vendor_app(
            f.vendor_app_payload(
                world["term_id"],
                total_seats=2,
                price_per_seat_cents=800,
                grade_band_scope=[GradeBand.ELEMENTARY],
            ),
            users.VENDOR_INTEGRATION_MANAGER_2,
        ),
        201,
    )
    assert own_registration["created_by_user_id"] == users.VENDOR_INTEGRATION_MANAGER_2_ID

    own_patch = validate_success(
        api.update_vendor_app(
            vendor_app_id,
            f.vendor_app_patch(total_seats=9),
            users.VENDOR_INTEGRATION_MANAGER,
        )
    )
    assert own_patch["total_seats"] == 9


def test_building_administrator_sees_the_money_view_but_not_the_vendor_roster_feed(api):
    """A building licence administrator is kept out of the student-level feed.

    The roster feed is published to the `RosterOperator`, the
    `DataGovernanceOfficer` and the licence's own `VendorIntegrationManager`;
    `BuildingLicenseAdmin` is absent from that list, so the read is refused with
    `ERR_ROLE_NOT_PERMITTED` (HTTP 403) at rung 2, before any scope reasoning. The
    renewal summary, by contrast, names `BuildingLicenseAdmin` among its readers
    and answers with "the `vendor_app_id`, the `basis` in force" — the default
    basis being `final`, "the renewal decision of record" — and every ordinary
    collection read stays shared with all five roles.

    Design: Corner/rbac/building_license_admin_cannot_read_roster_feed
    """
    world = fx.licensed_building(
        api,
        clock=CLOCK_IN_WINDOW,
        student_count=0,
        total_seats=4,
        price_per_seat_cents=STANDARD_PRICE_PER_SEAT_CENTS,
    )
    building_admin = users.building_license_admin(world["school_id"])

    refused_feed = api.get_roster_feed(world["vendor_app_id"], building_admin)
    validate_error(refused_feed, errors.ERR_ROLE_NOT_PERMITTED, 403)

    renewal = validate_success(
        api.get_renewal_summary(world["vendor_app_id"], building_admin)
    )
    assert renewal["vendor_app_id"] == world["vendor_app_id"]
    assert renewal["basis"] == RenewalBasis.FINAL

    rows, meta = validate_paginated(
        api.list_building_allocations(building_admin, vendor_app_id=world["vendor_app_id"])
    )
    assert meta["total_count"] == 1
    assert rows[0]["school_id"] == world["school_id"]


def test_identity_administrator_is_out_of_both_computed_vendor_reads(api):
    """The administrator that mints the seats may not read the figures built from them.

    Neither computed read admits `IdentityAdmin`: the renewal summary is published
    to the `RosterOperator`, the `DataGovernanceOfficer`, the
    `BuildingLicenseAdmin` and the licence's own `VendorIntegrationManager`, and
    the roster feed to the first, second and fourth of those, so both answer
    `ERR_ROLE_NOT_PERMITTED` (HTTP 403) for the identity administrator. Its own
    account collection stays open to it, and the same renewal summary read as a
    `RosterOperator` succeeds — the figures were available, just not to that role.

    Design: Corner/rbac/identity_admin_cannot_read_renewal_summary
    """
    world = fx.licensed_building(
        api,
        clock=CLOCK_IN_WINDOW,
        student_count=0,
        total_seats=4,
        price_per_seat_cents=STANDARD_PRICE_PER_SEAT_CENTS,
    )

    refused_renewal = api.get_renewal_summary(world["vendor_app_id"], users.IDENTITY_ADMIN)
    validate_error(refused_renewal, errors.ERR_ROLE_NOT_PERMITTED, 403)

    refused_feed = api.get_roster_feed(world["vendor_app_id"], users.IDENTITY_ADMIN)
    validate_error(refused_feed, errors.ERR_ROLE_NOT_PERMITTED, 403)

    _rows, meta = validate_paginated(
        api.list_app_accounts(users.IDENTITY_ADMIN, subject_type="STUDENT")
    )
    assert meta["total_count"] == 0

    permitted_renewal = validate_success(
        api.get_renewal_summary(world["vendor_app_id"], users.ROSTER_OPERATOR)
    )
    assert permitted_renewal["vendor_app_id"] == world["vendor_app_id"]


def test_the_operator_who_registered_a_licence_cannot_also_activate_it(api):
    """Activation is a two-person control on the human, not on the role.

    The contract requires the activating officer to be "necessarily somebody other
    than the operator recorded in `created_by_user_id`, else
    `ERR_SEGREGATION_OF_DUTIES`", and places that check in the authorization tier
    "ahead of any state or existence check". Putting on the governance hat with the
    same `X-User-ID` therefore changes nothing: the licence stays `DRAFT`, its
    purchased seats stay unallocated, and only an independent officer's activation
    splits the seats across the eligible buildings.

    Design: Corner/rbac/license_creator_cannot_activate_own_license
    """
    shared_person = "shared-001"
    as_manager = users.headers_for_role(
        users.ROLE_VENDOR_INTEGRATION_MANAGER, shared_person
    )
    as_same_officer = users.headers_for_role(
        users.ROLE_DATA_GOVERNANCE_OFFICER, shared_person
    )

    fx.set_clock(api, CLOCK_IN_WINDOW)
    school = fx.create_school(api)
    term = fx.create_active_term(api)
    vendor_app = fx.create_vendor_app(
        api,
        term["id"],
        total_seats=4,
        price_per_seat_cents=STANDARD_PRICE_PER_SEAT_CENTS,
        headers=as_manager,
    )
    assert vendor_app["created_by_user_id"] == shared_person

    refused = api.activate_license(vendor_app["id"], as_same_officer)
    validate_error(refused, errors.ERR_SEGREGATION_OF_DUTIES, 403)

    still_draft = validate_success(api.get_vendor_app(vendor_app["id"], users.ROSTER_OPERATOR))
    assert still_draft["status"] == VendorAppStatus.DRAFT
    assert still_draft["activated_by_user_id"] is None
    assert still_draft["version"] == 1

    _rows, meta = validate_paginated(
        api.list_building_allocations(users.ROSTER_OPERATOR, vendor_app_id=vendor_app["id"])
    )
    assert meta["total_count"] == 0

    activated = validate_success(
        api.activate_license(vendor_app["id"], users.DATA_GOVERNANCE_OFFICER)
    )
    assert activated["status"] == VendorAppStatus.ACTIVE
    assert activated["activated_by_user_id"] == users.DATA_GOVERNANCE_OFFICER_ID

    rows, meta = validate_paginated(
        api.list_building_allocations(users.ROSTER_OPERATOR, vendor_app_id=vendor_app["id"])
    )
    assert meta["total_count"] == 1
    assert rows[0]["school_id"] == school["id"]
    assert rows[0]["allocated_seats"] == 4


def test_the_operator_who_opened_a_sync_run_cannot_also_publish_it(api):
    """Publishing a roster is the second two-person control, keyed on the run's initiator.

    The contract makes publish "a `DataGovernanceOfficer` action on a run that must
    be `TRANSFORMED`, by an officer whose `X-User-ID` differs from the run's
    `initiated_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`)", evaluated in the
    authorization tier before any state check. The refused publish moves nothing:
    the run stays `TRANSFORMED` with a null `published_by_user_id` and the pending
    add is untouched. An independent officer's publish stamps `published_at` with
    the logical clock instant and returns the licence's `sync_health` to `OK`, while
    an add "whose requested date is still in the future stays `PENDING_ADD` and is
    simply skipped by this publish".

    Design: Corner/rbac/sync_run_initiator_cannot_publish_own_run
    """
    initiator = "shared-002"
    as_initiator = users.headers_for_role(users.ROLE_ROSTER_OPERATOR, initiator)
    as_same_officer = users.headers_for_role(
        users.ROLE_DATA_GOVERNANCE_OFFICER, initiator
    )

    fx.set_clock(api, CLOCK_IN_WINDOW)
    school = fx.create_school(api)
    term = fx.create_active_term(api)
    teacher = fx.create_teacher(api, school["id"])
    section = fx.create_section(
        api,
        school["id"],
        term["id"],
        primary_teacher_id=teacher["id"],
        period_index=3,
        meeting_days=list(MeetingDay.MWF),
        max_seats=5,
    )
    student = fx.create_student(api, school["id"], grade_level=4)
    vendor_app = fx.create_vendor_app(
        api,
        term["id"],
        total_seats=4,
        price_per_seat_cents=STANDARD_PRICE_PER_SEAT_CENTS,
    )
    fx.activate_license(api, vendor_app["id"])
    enrollment = fx.create_enrollment(api, section["id"], student["id"], "2026-10-01")
    assert enrollment["roster_status"] == RosterStatus.PENDING_ADD

    run = fx.open_sync_run(api, vendor_app["id"], headers=as_initiator)
    assert run["initiated_by_user_id"] == initiator
    transformed = fx.transform_run(api, run["id"])
    assert transformed["state"] == SyncRunState.TRANSFORMED

    refused = api.publish_sync_run(run["id"], as_same_officer)
    validate_error(refused, errors.ERR_SEGREGATION_OF_DUTIES, 403)

    held_back = validate_success(api.get_sync_run(run["id"], users.ROSTER_OPERATOR))
    assert held_back["state"] == SyncRunState.TRANSFORMED
    assert held_back["published_by_user_id"] is None
    assert held_back["published_at"] is None

    untouched = validate_success(api.get_enrollment(enrollment["id"], users.ROSTER_OPERATOR))
    assert untouched["roster_status"] == RosterStatus.PENDING_ADD

    published = validate_success(
        api.publish_sync_run(run["id"], users.DATA_GOVERNANCE_OFFICER)
    )
    assert published["state"] == SyncRunState.PUBLISHED
    assert published["published_by_user_id"] == users.DATA_GOVERNANCE_OFFICER_ID
    assert published["published_at"] == "2026-08-20T00:00:00.000Z"

    licence = validate_success(api.get_vendor_app(vendor_app["id"], users.ROSTER_OPERATOR))
    assert licence["sync_health"] == SyncHealth.OK

    future_add = validate_success(api.get_enrollment(enrollment["id"], users.ROSTER_OPERATOR))
    assert future_add["roster_status"] == RosterStatus.PENDING_ADD


def test_both_district_roles_may_amend_a_building_policy_while_the_vendor_role_may_not(api):
    """Amending a building's password policy is the one write both district roles hold.

    The contract publishes `PATCH /rostering/schools/{school_id}` to the
    `RosterOperator` and the `DataGovernanceOfficer` only, and states that "a later
    amendment may rewrite any of these five values or close the building, and each
    amendment increments the building's `version`". Consecutive amendments from the
    two district roles therefore both land on the same counter, while the
    vendor-facing role is refused with `ERR_ROLE_NOT_PERMITTED` (HTTP 403) and
    leaves the version where it was.

    Design: Corner/rbac/school_patch_shared_between_operator_and_governance
    """
    fx.set_clock(api, CLOCK_IN_WINDOW)
    school = fx.create_school(api)
    assert school["version"] == 1

    by_operator = validate_success(
        api.update_school(
            school["id"],
            f.school_policy_patch(min_password_length=11),
            users.ROSTER_OPERATOR,
        )
    )
    assert by_operator["min_password_length"] == 11
    assert by_operator["version"] == 2

    by_officer = validate_success(
        api.update_school(
            school["id"],
            f.school_policy_patch(password_max_age_days=90),
            users.DATA_GOVERNANCE_OFFICER,
        )
    )
    assert by_officer["password_max_age_days"] == 90
    assert by_officer["min_password_length"] == 11
    assert by_officer["version"] == 3

    refused = api.update_school(
        school["id"],
        f.school_policy_patch(min_password_length=8),
        users.VENDOR_INTEGRATION_MANAGER,
    )
    validate_error(refused, errors.ERR_ROLE_NOT_PERMITTED, 403)

    unchanged = validate_success(api.get_school(school["id"], users.ROSTER_OPERATOR))
    assert unchanged["min_password_length"] == 11
    assert unchanged["version"] == 3
