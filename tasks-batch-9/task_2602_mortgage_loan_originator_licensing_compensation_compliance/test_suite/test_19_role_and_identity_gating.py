"""Role gating, originator identity and segregation of duties.

Three different rejections guard who may act, and PRD 2.9 keeps them strictly
apart: the role gate (`ERR_ROLE_NOT_PERMITTED`, rule 3) fires before the
entity-backed ownership check (`ERR_ORIGINATOR_IDENTITY_MISMATCH`, rule 4),
and the segregation-of-duties rule (`ERR_SEGREGATION_OF_DUTIES`) is a
business-layer check on two named user ids rather than on a role at all. This
file pins each of the three to the exact identifier the specification names,
and confirms that the shared read surface is open to every role.

Every test builds its own preconditions: the server is restarted with an empty
store before each one, and the logical clock reads exactly
`2026-08-01T00:00:00Z` until a test moves it.
"""
from datetime import datetime

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import CLOCK_STARTUP_INSTANT
from test_helpers.fixtures import (
    create_originator,
    lock_loan,
    request_pricing_exception,
    setup_approved_plan,
    setup_authorized_originator,
    sole_record_for_loan,
    take_loan,
)
from test_helpers.test_users import (
    ANALYST_USER_ID,
    OFFICER_USER_ID,
    admin_headers,
    analyst_headers,
    designer_headers,
    examiner_headers,
    loan_ops_headers,
    make_originator_headers,
    officer_headers,
)
from test_helpers.types import ALL_ROLES

DUAL_ROLE_USER_ID = "user-wearing-two-hats-01"


def _instant(value):
    """Parse an ISO 8601 UTC instant.

    A local helper rather than a test_helpers addition: the framework offers a
    format check (`is_iso8601_timestamp`) but no value comparison, and PRD 2.5
    fixes the wire format at three fractional digits while the instants a test
    supplies are written without them.
    """
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _assign_plan(api, originator_id, plan_id, expected_originator_version, **overrides):
    """Assign an active plan without pinning the success status code.

    A local helper rather than the shared one: PRD 4 leaves the successful
    status of an assignment as a 200 (the response is the updated originator,
    not a new record), and these tests assert on the returned row rather than on
    the status line.
    """
    payload = factories.build_plan_assignment(
        plan_id, expected_originator_version, **overrides
    )
    return get_success_data(api.assign_compensation_plan(originator_id, payload, officer_headers()))


def test_only_loan_operations_may_close_a_locked_loan(api):
    """The owning originator, the licensing desk and the admin are all refused the close.

    PRD 4 names a single role for `POST /loan-applications/{id}/close`
    (LoanOperations) and fixes the consequence: "Where a single role is named, no
    other role may call that endpoint, and an attempt by any other role is
    rejected with `ERR_ROLE_NOT_PERMITTED`."

    PRD 2.1 gives the status: "If the role is well-formed but is not among the
    roles authorised for the endpoint being called, the request is rejected with
    `ERR_ROLE_NOT_PERMITTED` (HTTP 403)." — and for the admin specifically: "It
    deliberately holds no business write authority — it can neither licence an
    originator, approve a plan, close a loan nor decide an exception."

    Design: Corner/rbac/originator_and_admin_cannot_close_a_loan_only_loan_operations_can
    """
    context = setup_authorized_originator(
        api, state_code="CA", sponsorship_effective_at="2026-07-01T00:00:00Z"
    )
    originator_id = context["originator"]["id"]
    plan = setup_approved_plan(
        api,
        base_basis_points=105,
        min_fee_cents=0,
        max_fee_cents=5_000_000,
        volume_tier_enabled=False,
        concession_absorption_enabled=False,
    )
    _assign_plan(
        api,
        originator_id,
        plan["id"],
        context["originator"]["version"],
        effective_from="2026-08-01T00:00:00Z",
        effective_to="2026-12-31T00:00:00Z",
    )
    loan = take_loan(api, originator_id, state_code="CA", requested_amount_cents=5_000_000)
    locked = lock_loan(api, loan["id"], originator_id, locked_amount_cents=5_000_000)
    assert locked["status"] == "LOCKED"

    close_payload = factories.build_loan_close(
        funded_amount_cents=5_000_000,
        funded_at="2026-08-01T00:00:00Z",
        lender_paid_comp_cents=52_500,
        borrower_paid_comp_cents=0,
    )
    refused = (
        ("the owning Originator", make_originator_headers(originator_id)),
        ("the PlatformAdmin", admin_headers()),
        ("the LicensingAnalyst", analyst_headers()),
    )
    for who, headers in refused:
        error = validate_error(
            api.close_loan_application(loan["id"], close_payload, headers),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
        )
        assert error["error_id"] == ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, (
            f"{who} must not be able to close a loan"
        )

    # None of the three refusals moved the file.
    still_locked = validate_success(api.get_loan_application(loan["id"], officer_headers()))
    assert still_locked["status"] == "LOCKED"
    assert still_locked["compensation_status"] == "NOT_APPLICABLE"
    assert still_locked["closed_unit_index"] is None

    closed = validate_success(api.close_loan_application(loan["id"], close_payload, loan_ops_headers()))
    assert closed["status"] == "CLOSED"
    assert closed["authority_flag"] == "VERIFIED"
    assert closed["compensation_status"] == "ACCRUED"
    assert closed["compensation_plan_id"] == plan["id"]
    assert closed["closed_unit_index"] == 1

    # 5,000,000 cents at 105 bps with no tier adder, inside a 0..5,000,000 fee band.
    record = sole_record_for_loan(api, loan["id"])
    assert record["variant"] == "PROVISIONAL"
    assert record["status"] == "ACCRUED"
    assert record["tier_bps_adder"] == 0
    assert record["base_comp_cents"] == 52_500
    assert record["comp_impact_cents"] == 0
    assert record["accrued_cents"] == 52_500
    assert record["paid_cents"] == 0
    assert record["compensation_plan_id"] == plan["id"]
    assert record["originator_id"] == originator_id


def test_an_originator_acting_on_another_originators_records_is_an_identity_mismatch(api):
    """Ownership, not role, is what stops the second originator — and reads are exempt.

    PRD 2.1: "The `Originator` role is different: it is **entity-backed**. When
    `X-User-Role` is `Originator`, `X-User-ID` is the `id` of the acting
    `Originator` row, and every ownership check compares the target resource's
    `originator_id` foreign key to `X-User-ID`. Concretely: when an originator
    takes an application or drafts an advertisement, the `originator_id` in the
    request body must equal `X-User-ID`; and when an originator acts on an
    existing loan application, on a pricing exception, or on an advertisement, the
    originator that owns the path resource must be the caller. A mismatch is
    rejected with `ERR_ORIGINATOR_IDENTITY_MISMATCH` (HTTP 403). This check does
    not apply to the shared read endpoints, which every one of the seven roles may
    call against any resource."

    Design: Corner/rbac/originator_locking_another_originators_loan_returns_identity_mismatch
    """
    owner = setup_authorized_originator(
        api, state_code="CA", sponsorship_effective_at="2026-07-01T00:00:00Z"
    )
    intruder = setup_authorized_originator(
        api, state_code="CA", sponsorship_effective_at="2026-07-01T00:00:00Z"
    )
    owner_id = owner["originator"]["id"]
    intruder_id = intruder["originator"]["id"]
    assert owner_id != intruder_id
    loan = take_loan(api, owner_id, state_code="CA", requested_amount_cents=5_000_000)
    intruder_headers = make_originator_headers(intruder_id)

    # Acting on a path resource it does not own.
    validate_error(
        api.lock_loan_application(
            loan["id"], factories.build_loan_lock(locked_amount_cents=5_000_000), intruder_headers
        ),
        ApiErrorId.ERR_ORIGINATOR_IDENTITY_MISMATCH.value,
    )
    validate_error(
        api.create_pricing_exception(
            loan["id"],
            factories.build_pricing_exception(concession_cents=50_000),
            intruder_headers,
        ),
        ApiErrorId.ERR_ORIGINATOR_IDENTITY_MISMATCH.value,
    )
    # Naming another originator in the request body of a create.
    validate_error(
        api.create_loan_application(
            factories.build_loan_application(owner_id, requested_amount_cents=5_000_000),
            intruder_headers,
        ),
        ApiErrorId.ERR_ORIGINATOR_IDENTITY_MISMATCH.value,
    )

    # The shared reads are exempt: the intruder may read the loan it may not touch.
    read_by_intruder = validate_success(api.get_loan_application(loan["id"], intruder_headers))
    assert read_by_intruder["originator_id"] == owner_id
    assert read_by_intruder["status"] == "TAKEN"
    assert read_by_intruder["locked_amount_cents"] is None

    # The owner's own lock goes through untouched by the three refusals.
    locked = validate_success(
        api.lock_loan_application(
            loan["id"],
            factories.build_loan_lock(locked_amount_cents=5_000_000),
            make_originator_headers(owner_id),
        )
    )
    assert locked["status"] == "LOCKED"
    assert locked["locked_amount_cents"] == 5_000_000

    owned, meta = validate_paginated(
        api.list_loan_applications(officer_headers(), params={"originator_id": owner_id})
    )
    assert meta["total_count"] == 1, "the intruder's create attempt must not have written a row"
    assert owned[0]["id"] == loan["id"]
    _, intruder_meta = validate_paginated(
        api.list_loan_applications(officer_headers(), params={"originator_id": intruder_id})
    )
    assert intruder_meta["total_count"] == 0


def test_a_plan_may_not_be_approved_by_the_user_who_drafted_it(api):
    """One user id in two roles is still one user id: the self-approval is refused.

    PRD 3.3: "It requires that the plan is still `DRAFT`; that
    `prohibited_variable_count` is exactly zero, so that any plan carrying even
    one term-of-the-transaction variable is unapprovable and is rejected with
    `ERR_PROHIBITED_COMP_VARIABLE` (HTTP 422); that the approving `X-User-ID`
    differs from `drafted_by_user_id`, with a self-approval rejected as
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 422); and that the plan has at least one
    declared variable whose `weight_pct` values sum to exactly one hundred, with
    any other total — including a plan with no variables at all — rejected as
    `ERR_PLAN_WEIGHTS_NOT_100` (HTTP 422)."

    PRD 3.3 also fixes the anchor the check reads: "The system stamps
    `drafted_by_user_id` with the drafting designer's `X-User-ID`; that value is
    the anchor for the segregation-of-duties check at approval time."

    Design: Corner/rbac/same_user_id_cannot_draft_and_approve_nor_request_and_decide
    """
    drafted = get_success_data(
        api.create_compensation_plan(
            factories.build_compensation_plan(
                base_basis_points=105, min_fee_cents=0, max_fee_cents=5_000_000
            ),
            designer_headers(DUAL_ROLE_USER_ID),
        ),
        201,
    )
    assert drafted["drafted_by_user_id"] == DUAL_ROLE_USER_ID
    assert drafted["status"] == "DRAFT"
    assert drafted["approved_by_user_id"] is None
    get_success_data(
        api.create_compensation_variable(
            drafted["id"],
            factories.build_compensation_variable(
                variable_type="LOAN_VOLUME_UNITS", weight_pct=100
            ),
            designer_headers(DUAL_ROLE_USER_ID),
        ),
        201,
    )

    # The same user id now presents the ComplianceOfficer role. The role gate
    # passes; the segregation-of-duties check does not.
    validate_error(
        api.create_plan_approval(
            drafted["id"],
            factories.build_plan_decision("APPROVE"),
            officer_headers(DUAL_ROLE_USER_ID),
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
    )

    unchanged = validate_success(api.get_compensation_plan(drafted["id"], officer_headers()))
    assert unchanged["status"] == "DRAFT"
    assert unchanged["approved_by_user_id"] is None

    approved = validate_success(
        api.create_plan_approval(
            drafted["id"], factories.build_plan_decision("APPROVE"), officer_headers()
        )
    )
    assert approved["status"] == "ACTIVE"
    assert approved["approved_by_user_id"] == OFFICER_USER_ID
    assert approved["drafted_by_user_id"] == DUAL_ROLE_USER_ID


def test_a_pricing_exception_may_not_be_decided_by_the_user_who_requested_it(api):
    """The requesting originator's own id, presented as an officer, is refused the decision.

    PRD 3.6: "A missing second approver on an exception that requires one is
    rejected with `ERR_SECOND_APPROVAL_REQUIRED` (HTTP 422); a second approver
    who is the decider or the requester, and equally a decider who is the
    requester, is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 422) — and per
    §2.9 the segregation rejection is reported ahead of the missing-second-approver
    rejection."

    PRD 3.6 also fixes the anchor and the untouched fields: "A filed exception
    starts in `SUBMITTED` with `comp_impact_cents` at `0`, `requested_by_user_id`
    stamped from the filing originator's `X-User-ID`, and `decided_by_user_id`,
    `second_decided_by_user_id`, `decided_at` and `decision_note` all null."

    Design: Corner/rbac/same_user_id_cannot_draft_and_approve_nor_request_and_decide
    """
    context = setup_authorized_originator(
        api, state_code="CA", sponsorship_effective_at="2026-07-01T00:00:00Z"
    )
    originator_id = context["originator"]["id"]
    plan = setup_approved_plan(
        api,
        base_basis_points=105,
        min_fee_cents=0,
        max_fee_cents=5_000_000,
        volume_tier_enabled=False,
        concession_absorption_enabled=False,
    )
    _assign_plan(
        api,
        originator_id,
        plan["id"],
        context["originator"]["version"],
        effective_from="2026-08-01T00:00:00Z",
        effective_to="2026-12-31T00:00:00Z",
    )
    loan = take_loan(api, originator_id, state_code="CA", requested_amount_cents=5_000_000)
    lock_loan(api, loan["id"], originator_id, locked_amount_cents=5_000_000)

    exception = request_pricing_exception(
        api,
        loan["id"],
        originator_id,
        requested_rate_bps=625,
        concession_cents=50_000,
        reason_code="COMPETITIVE_MATCH",
        justification_text=factories.JUSTIFICATION_40,
    )
    assert exception["status"] == "SUBMITTED"
    assert exception["requested_by_user_id"] == originator_id
    assert exception["requires_second_approval"] is False
    assert exception["comp_impact_cents"] == 0
    assert exception["decided_by_user_id"] is None
    assert exception["second_decided_by_user_id"] is None
    assert exception["decided_at"] is None

    # The requester's own user id, this time wearing the officer's role.
    validate_error(
        api.create_pricing_exception_decision(
            exception["id"],
            factories.build_pricing_exception_decision("APPROVE"),
            officer_headers(originator_id),
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
    )

    unchanged = validate_success(api.get_pricing_exception(exception["id"], officer_headers()))
    assert unchanged["status"] == "SUBMITTED"
    assert unchanged["decided_by_user_id"] is None
    assert unchanged["decided_at"] is None

    decided = validate_success(
        api.create_pricing_exception_decision(
            exception["id"],
            factories.build_pricing_exception_decision("APPROVE"),
            officer_headers(),
        )
    )
    assert decided["status"] == "APPROVED"
    assert decided["decided_by_user_id"] == OFFICER_USER_ID
    assert decided["second_decided_by_user_id"] is None
    # The governing plan has concession_absorption_enabled false, so the
    # concession never touches commission.
    assert decided["comp_impact_cents"] == 0
    assert _instant(decided["decided_at"]) == _instant(CLOCK_STARTUP_INSTANT)


def test_every_one_of_the_seven_roles_may_read_the_shared_surface(api):
    """The reads are shared: seven roles, one identical row, and the audit trail open to all.

    PRD 4: "In the table below, the shorthand **All roles** in the authorisation
    column means all seven roles are permitted: `LicensingAnalyst`,
    `CompensationDesigner`, `ComplianceOfficer`, `Originator`, `LoanOperations`,
    `ExaminationCoordinator` and `PlatformAdmin`."

    PRD 2.1 adds that ownership never narrows a read: "This check does not apply
    to the shared read endpoints, which every one of the seven roles may call
    against any resource."

    PRD 2.5 fixes the ordering key the trail exposes: "Its ordering key is
    `sequence_no`, a strictly increasing counter that starts at `1` for the first
    entry the system ever writes and advances by one for each subsequent entry,
    globally across all entity types and all requests."

    Design: Corner/rbac/every_role_can_read_the_shared_originator_and_audit_surface
    """
    context = setup_authorized_originator(
        api, state_code="CA", sponsorship_effective_at="2026-07-01T00:00:00Z"
    )
    originator = context["originator"]
    originator_id = originator["id"]
    licence_id = context["license"]["id"]

    readers = (
        ("LicensingAnalyst", analyst_headers()),
        ("CompensationDesigner", designer_headers()),
        ("ComplianceOfficer", officer_headers()),
        ("Originator", make_originator_headers(originator_id)),
        ("LoanOperations", loan_ops_headers()),
        ("ExaminationCoordinator", examiner_headers()),
        ("PlatformAdmin", admin_headers()),
    )
    assert len(readers) == len(ALL_ROLES) == 7

    for role_name, headers in readers:
        row = validate_success(api.get_originator(originator_id, headers))
        assert row["id"] == originator_id, f"{role_name} must read the same originator"
        assert row["version"] == originator["version"]
        assert row["nmls_unique_id"] == originator["nmls_unique_id"]
        assert row["authorized_state_codes"] == ["CA"]

        licence = validate_success(api.get_license_registration(licence_id, headers))
        assert licence["id"] == licence_id
        assert licence["status"] == "ACTIVE"

        events, meta = validate_paginated(
            api.list_audit_events(
                headers,
                params={"subject_type": "LicenseRegistration", "subject_ref": licence_id},
            )
        )
        assert meta["total_count"] == 1, f"{role_name} must see the activation entry"
        entry = events[0]
        assert entry["event_type"] == "LICENSE_STATUS_CHANGED"
        assert entry["subject_type"] == "LicenseRegistration"
        assert entry["subject_ref"] == licence_id
        assert entry["actor_role"] == "LicensingAnalyst", (
            "the entry records the role that acted, not the role now reading it"
        )
        assert entry["actor_user_id"] == ANALYST_USER_ID
        assert entry["sequence_no"] == 1
        assert "version" not in entry
        assert "updated_at" not in entry

    # The two computed reads are on the same shared surface.
    authority = validate_success(api.get_originator_authority(originator_id, loan_ops_headers()))
    assert authority["originator_id"] == originator_id
    assert authority["authorized_state_codes"] == ["CA"]
    assert _instant(authority["as_of"]) == _instant(CLOCK_STARTUP_INSTANT)

    ce = validate_success(
        api.get_originator_ce_compliance(
            originator_id, admin_headers(), params={"attribution_variant": "MAKEUP_ATTRIBUTION"}
        )
    )
    assert ce["originator_id"] == originator_id
    assert ce["reporting_year"] == 2026
    assert ce["attribution_variant"] == "MAKEUP_ATTRIBUTION"
    assert ce["total_hours"] == 0
    assert ce["ce_satisfied"] is False


def test_clock_and_sweep_are_admin_only_and_the_admin_writes_no_business_row(api):
    """The operator utilities are the admin's alone, and they are all the admin has.

    PRD 2.1: "A `PlatformAdmin` operates the platform: it owns the logical clock
    and the nightly compliance sweep. It deliberately holds no business write
    authority — it can neither licence an originator, approve a plan, close a loan
    nor decide an exception."

    PRD 2.4: "At startup the logical clock reads exactly `2026-08-01T00:00:00Z`,
    and it continues to read that instant until a `PlatformAdmin` moves it; it
    never falls back to real time. Moving the clock is done by supplying a
    `to_iso8601` instant, and the response echoes the new setting as
    `current_utc`. Setting the clock mutates no entity: it changes only what
    subsequent requests observe as "now"."

    PRD 3.9: "The sweep reports what it did so that a caller can verify the epoch
    advance without polling every collection: `swept_at` gives the instant it ran"

    Design: Corner/rbac/clock_and_sweep_are_platform_admin_exclusive_and_admin_holds_no_business_writes
    """
    originator = create_originator(api)
    drafted = get_success_data(
        api.create_compensation_plan(
            factories.build_compensation_plan(base_basis_points=105), designer_headers()
        ),
        201,
    )

    # The admin's two utilities are refused to everybody else.
    validate_error(
        api.set_clock(factories.build_clock("2026-09-01T00:00:00Z"), officer_headers()),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
    )
    validate_error(
        api.run_daily_license_sweep(analyst_headers()),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
    )

    # And the admin is refused every business write, whatever else is wrong with
    # the request: the role gate is rule 3, ahead of every business rule.
    validate_error(
        api.create_license_registration(
            factories.build_license_registration(originator["id"]), admin_headers()
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
    )
    validate_error(
        api.create_plan_approval(
            drafted["id"], factories.build_plan_decision("APPROVE"), admin_headers()
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
    )
    # The mirror image: the licensing desk may not draft a plan either.
    validate_error(
        api.create_compensation_plan(factories.build_compensation_plan(), analyst_headers()),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
    )

    _, licence_meta = validate_paginated(api.list_license_registrations(officer_headers()))
    assert licence_meta["total_count"] == 0, "the admin's filing attempt wrote no licence"
    plans, plan_meta = validate_paginated(api.list_compensation_plans(officer_headers()))
    assert plan_meta["total_count"] == 1, "the analyst's drafting attempt wrote no plan"
    assert plans[0]["id"] == drafted["id"]
    assert plans[0]["status"] == "DRAFT", "the admin's approval attempt did not activate it"
    assert plans[0]["approved_by_user_id"] is None

    # The refused clock call left the clock exactly where it was.
    before_move = validate_success(api.run_daily_license_sweep(admin_headers()))
    assert _instant(before_move["swept_at"]) == _instant(CLOCK_STARTUP_INSTANT)
    for field in (
        "expired_license_ids",
        "relinquished_sponsorship_ids",
        "suspended_loan_ids",
        "opened_investigation_ids",
        "escalated_inquiry_ids",
        "unassigned_originator_ids",
    ):
        assert before_move[field] == []

    moved = validate_success(
        api.set_clock(factories.build_clock("2026-08-02T00:00:00Z"), admin_headers())
    )
    assert _instant(moved["current_utc"]) == _instant("2026-08-02T00:00:00Z")

    after_move = validate_success(api.run_daily_license_sweep(admin_headers()))
    assert _instant(after_move["swept_at"]) == _instant("2026-08-02T00:00:00Z")
    assert after_move["expired_license_ids"] == []
    assert after_move["unassigned_originator_ids"] == []
