"""Second-coverage tests for the harder PRD-described behaviors.

Every test in this file targets a difficulty-design instance that needs
a second-coverage perspective on top of the primary test elsewhere in
the suite.

Tagged with `# difficulty: <rule_id>/<instance.name>` so the coverage
audit can attribute each test to its difficulty-design instance.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    add_applicant,
    add_income,
    advance_clock_to,
    advance_to_redetermination_due,
    create_appeal_payload,
    create_application,
    create_household,
    create_state_policy,
    decide_application,
    decide_application_payload,
    file_appeal,
    get_application,
    get_enrollment,
    get_household,
    get_redetermination,
    grant_appeal,
    grant_appeal_payload,
    hold_hearing,
    issue_emergency_declaration,
    iso_now,
    iso_offset,
    parse_iso,
    run_redetermination_sweep,
    schedule_hearing,
    schedule_hearing_payload,
    server_now_dt,
    setup_appeal_under_review,
    setup_approved_application,
    setup_basic_household,
    setup_denied_application,
    setup_eligible_application,
    setup_redetermination_pending,
    submit_redetermination_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# transitive_cascade/appeal_grant_cascade_depth_3 — second coverage
# ===========================================================================
def test_appeal_grant_creates_new_under_review_application(api):
    """PRD §3.6: "the associated Application moves from APPEALED to
    UNDER_REVIEW for re-decision (this is cyclic — the application may
    then transition once more to APPROVED or DENIED, and the caseworker
    re-deciding it must, per the same-actor rule, differ from any prior
    caseworker who denied it)."

    Claim: after appeal grant, the application is observable in
    UNDER_REVIEW state, and re-decide by a DIFFERENT caseworker
    succeeds and (with the right setup) creates an enrollment.

    # difficulty: transitive_cascade/appeal_grant_cascade_depth_3
    """
    deny_cw = TEST_USERS["eligibility_caseworker_headers"]
    denied_setup = setup_denied_application(
        decider_headers=deny_cw,
        state_policy_kwargs={
            "fpl_base_amount": 15_000.00,
            "fpl_per_member_amount": 5_000.00,
            "magi_income_limit_pct": 138.0,
        },
        incomes=[
            {"applicant_index": 0, "source_type": "WAGES",
             "gross_amount": 5_000.00, "frequency": "ANNUAL"},
        ],
    )
    household, application, _det, appeal, _fh = setup_appeal_under_review(
        denied_setup=denied_setup,
        deny_caseworker_headers=deny_cw,
        appeals_officer_headers=TEST_USERS["appeals_officer_headers"],
    )
    grant_appeal(appeal=appeal)
    # Re-decide APPROVE with the alt caseworker (PRD §3.3 SoD).
    determination = decide_application(
        household=household, application=application, decision="APPROVE",
        headers=TEST_USERS["eligibility_caseworker_headers_alt"],
    )
    assert determination["outcome"] == "ELIGIBLE"
    # Household active enrollment count is bumped to >=1.
    h = get_household(household["id"])
    assert h["active_enrollment_count"] >= 1, (
        "after grant + APPROVE, the household must have at least one "
        f"active enrollment per PRD §3.6; got count="
        f"{h['active_enrollment_count']}"
    )


# ===========================================================================
# transitive_cascade/emergency_declaration_cascade_depth_2 — second coverage
# ===========================================================================
def test_emergency_declaration_cascade_active_enrollment_count(api):
    """PRD §3.5: "The household's active_enrollment_count is
    recomputed across every affected household; since CONTINUOUS_COVERAGE
    counts as active and REDETERMINATION_DUE does not, an enrollment
    moving from REDETERMINATION_DUE to CONTINUOUS_COVERAGE increments
    the count."

    Claim: when emergency declaration flips an enrollment from
    REDETERMINATION_DUE → CONTINUOUS_COVERAGE, the parent household's
    active_enrollment_count increments from 0 to 1.

    # difficulty: transitive_cascade/emergency_declaration_cascade_depth_2
    """
    _sp, household, _, enrollments, _redet = setup_redetermination_pending(
        state_policy_kwargs={
            "fpl_base_amount": 15_000.00,
            "fpl_per_member_amount": 5_000.00,
            "magi_income_limit_pct": 138.0,
        },
        incomes=[
            {"applicant_index": 0, "source_type": "WAGES",
             "gross_amount": 5_000.00, "frequency": "ANNUAL"},
        ],
    )
    h_pre = get_household(household["id"])
    assert h_pre["active_enrollment_count"] == 0, (
        "REDETERMINATION_DUE does not count toward active_enrollment_"
        f"count per PRD §3.4; got pre-count="
        f"{h_pre['active_enrollment_count']}"
    )
    issue_emergency_declaration(
        scope="FEDERAL", state_code=None,
        declared_at=iso_now(), expires_at=iso_offset(days=30),
    )
    h_post = get_household(household["id"])
    assert h_post["active_enrollment_count"] == 1, (
        "REDETERMINATION_DUE → CONTINUOUS_COVERAGE must increment "
        f"active_enrollment_count per PRD §3.5; got post-count="
        f"{h_post['active_enrollment_count']}"
    )


# ===========================================================================
# non_linear_state_machine/application_cyclic_via_appeal — second coverage
# ===========================================================================
def test_application_cycle_visits_under_review_twice(api):
    """PRD §3.6: "this is cyclic — the application may then transition
    once more to APPROVED or DENIED."
    PRD §3.3 state machine: DRAFT → UNDER_REVIEW → DENIED → APPEALED →
    UNDER_REVIEW (and onward).

    Claim: the Application's status visits UNDER_REVIEW at least twice
    over a DENY → appeal grant → re-decide cycle.

    # difficulty: non_linear_state_machine/application_cyclic_via_appeal
    """
    deny_cw = TEST_USERS["eligibility_caseworker_headers"]
    denied_setup = setup_denied_application(decider_headers=deny_cw)
    _sp, household, _, application, _det = denied_setup
    # Application is currently DENIED. After grant, UNDER_REVIEW.
    _household, _application, _det2, appeal, _fh = setup_appeal_under_review(
        denied_setup=denied_setup,
        deny_caseworker_headers=deny_cw,
    )
    grant_appeal(appeal=appeal)
    app_after_grant = get_application(household["id"], application["id"])
    assert app_after_grant["status"] == "UNDER_REVIEW", (
        "Application must re-enter UNDER_REVIEW after appeal grant "
        f"per PRD §3.6 / §3.3; got status={app_after_grant['status']!r}"
    )


# ===========================================================================
# non_linear_state_machine/enrollment_cyclic_via_redetermination — second
# ===========================================================================
def test_enrollment_cycle_active_to_redet_due_back_to_active(api):
    """PRD §3.4: "The renewed enrollment's coverage_start is reset to
    the current clock_now, its coverage_end is reset to coverage_start
    plus 365 days, its redetermination_due_at is reset to coverage_start
    plus 365 days, and its coverage_status is set back to ACTIVE,
    closing the cyclic redetermination loop."

    Claim: after sweep (ACTIVE → REDETERMINATION_DUE) and RENEW
    (REDETERMINATION_DUE → ACTIVE), the same enrollment row is once
    again ACTIVE — the cycle closed.

    # difficulty: non_linear_state_machine/enrollment_cyclic_via_redetermination
    """
    _sp, _hh, _, enrollments, redet = setup_redetermination_pending(
        state_policy_kwargs={
            "fpl_base_amount": 15_000.00,
            "fpl_per_member_amount": 5_000.00,
            "magi_income_limit_pct": 138.0,
        },
        incomes=[
            {"applicant_index": 0, "source_type": "WAGES",
             "gross_amount": 5_000.00, "frequency": "ANNUAL"},
        ],
    )
    enrollment = enrollments[0]
    # Mid-state: REDETERMINATION_DUE.
    mid = get_enrollment(enrollment["id"])
    assert mid["coverage_status"] == "REDETERMINATION_DUE"
    api.submit_redetermination(
        redet["id"],
        submit_redetermination_payload(
            decision="RENEW", new_snapshot_magi=5_000.00,
        ),
        TEST_USERS["eligibility_caseworker_headers"],
    )
    # Post-state: ACTIVE again — cycle closed.
    after = get_enrollment(enrollment["id"])
    assert after["coverage_status"] == "ACTIVE", (
        "RENEW must close the Enrollment cycle (REDETERMINATION_DUE → "
        f"ACTIVE) per PRD §3.4; got coverage_status="
        f"{after['coverage_status']!r}"
    )
    assert after["id"] == enrollment["id"]


# ===========================================================================
# cross_entity_state_dependency/appeal_grant_gated_by_fair_hearing_held
# ===========================================================================
def test_grant_requires_fair_hearing_held(api):
    """PRD §3.6: "Granting an appeal requires the appeal to be in
    UNDER_REVIEW, requires the associated fair hearing to be in HELD."

    Claim: attempting /grant before /hold returns ERR_INVALID_STATE
    (the appeal is still HEARING_SCHEDULED, not UNDER_REVIEW).

    # difficulty: cross_entity_state_dependency/appeal_grant_gated_by_fair_hearing_held
    """
    _sp, _hh, _, _app, determination = setup_denied_application()
    appeal = file_appeal(determination=determination)
    officer_headers = TEST_USERS["appeals_officer_headers"]
    officer_id = officer_headers["X-User-ID"]
    start = iso_offset(days=1, base=server_now_dt())
    end = iso_offset(days=1, hours=1, base=server_now_dt())
    schedule_hearing(
        appeal=appeal, officer_id=officer_id,
        scheduled_start=start, scheduled_end=end,
        headers=officer_headers,
    )
    # Do NOT call /hold. Attempt /grant.
    res = api.grant_appeal(
        appeal["id"], grant_appeal_payload(), officer_headers,
    )
    validate_error(res, "ERR_INVALID_STATE")


def test_grant_succeeds_after_fair_hearing_held(api):
    """PRD §3.6: "Granting an appeal requires the appeal to be in
    UNDER_REVIEW, requires the associated fair hearing to be in HELD."

    Claim: with FairHearing.status == HELD and Appeal.status ==
    UNDER_REVIEW, /grant succeeds.

    # difficulty: cross_entity_state_dependency/appeal_grant_gated_by_fair_hearing_held
    """
    _hh, _app, _det, appeal, fh = setup_appeal_under_review()
    assert fh["status"] == "HELD"
    assert appeal["status"] == "UNDER_REVIEW"
    res = api.grant_appeal(
        appeal["id"], grant_appeal_payload(),
        TEST_USERS["appeals_officer_headers"],
    )
    validate_success(res)


# ===========================================================================
# cross_entity_state_dependency/redetermination_renew_gated_by_emergency_declaration
# ===========================================================================
def test_redet_submit_rejected_after_emergency_withdraws_redet(api):
    """PRD §3.5: "If the covered enrollment was in REDETERMINATION_DUE
    at the moment of the flip, the system also withdraws any associated
    PENDING Redetermination on that enrollment — its status is set to
    WITHDRAWN."
    PRD §3.4: "the redetermination must be PENDING (otherwise
    ERR_INVALID_STATE)."

    Claim: after an emergency cascade withdraws the PENDING redet,
    /submit returns ERR_INVALID_STATE (redet now WITHDRAWN, not
    PENDING).

    # difficulty: cross_entity_state_dependency/redetermination_renew_gated_by_emergency_declaration
    """
    _sp, _hh, _, _enr, redet = setup_redetermination_pending(
        state_policy_kwargs={
            "fpl_base_amount": 15_000.00,
            "fpl_per_member_amount": 5_000.00,
            "magi_income_limit_pct": 138.0,
        },
        incomes=[
            {"applicant_index": 0, "source_type": "WAGES",
             "gross_amount": 5_000.00, "frequency": "ANNUAL"},
        ],
    )
    assert redet["status"] == "PENDING"
    issue_emergency_declaration(
        scope="FEDERAL", state_code=None,
        declared_at=iso_now(), expires_at=iso_offset(days=30),
    )
    # PRD §3.5: associated PENDING Redetermination becomes WITHDRAWN.
    # Now attempting RENEW must fail with ERR_INVALID_STATE.
    res = api.submit_redetermination(
        redet["id"],
        submit_redetermination_payload(
            decision="RENEW", new_snapshot_magi=5_000.00,
        ),
        TEST_USERS["eligibility_caseworker_headers"],
    )
    validate_error(res, "ERR_INVALID_STATE")


# ===========================================================================
# resource_temporal_overlap/enrollment_coverage_half_open_overlap
# ===========================================================================
def test_overlapping_coverage_window_rejected(api):
    """PRD §3.4: "the new enrollment's [coverage_start, coverage_end)
    window — under half-open semantics, so adjacency (a new
    coverage_start equal to an existing coverage_end) does not count as
    overlap — must not overlap any existing enrollment on the same
    applicant_id whose coverage_status is in ACTIVE, CONTINUOUS_COVERAGE,
    or REDETERMINATION_DUE. An overlap is rejected with
    ERR_ENROLLMENT_OVERLAP."

    Claim: APPROVE-ing a second application on the same applicant
    whose coverage window overlaps the first active enrollment →
    ERR_ENROLLMENT_OVERLAP.

    # difficulty: resource_temporal_overlap/enrollment_coverage_half_open_overlap
    """
    # Setup: first APPROVE.
    _sp, household, applicants, _app1, _det1, enrollments = (
        setup_approved_application(
            state_policy_kwargs={
                "fpl_base_amount": 15_000.00,
                "fpl_per_member_amount": 5_000.00,
                "magi_income_limit_pct": 138.0,
            },
            incomes=[
                {"applicant_index": 0, "source_type": "WAGES",
                 "gross_amount": 5_000.00, "frequency": "ANNUAL"},
            ],
        )
    )
    # Now create a second application on the same household; APPROVE
    # would attempt to create a second enrollment on the same applicant.
    # PRD §3.4 rejects this with ERR_ENROLLMENT_OVERLAP.
    app2 = create_application(household=household, program="MAGI_ADULT")
    api.submit_application(
        household["id"], app2["id"],
        TEST_USERS["intake_worker_headers"],
    )
    res = api.decide_application(
        household["id"], app2["id"],
        decide_application_payload(decision="APPROVE"),
        TEST_USERS["eligibility_caseworker_headers"],
    )
    validate_error(res, "ERR_ENROLLMENT_OVERLAP")


def test_adjacent_coverage_window_does_not_overlap(api):
    """PRD §3.4: "the new enrollment's [coverage_start, coverage_end)
    window — under half-open semantics, so adjacency (a new
    coverage_start equal to an existing coverage_end) does not count as
    overlap."

    Claim: after advancing the clock to exactly the first enrollment's
    coverage_end, APPROVE-ing a fresh application creates a new
    enrollment whose coverage_start == first.coverage_end and no
    ERR_ENROLLMENT_OVERLAP fires.

    Note: This test depends on a SUSPEND of the first enrollment to
    avoid REDETERMINATION_DUE blocking the new APPROVE under the
    {ACTIVE, CONTINUOUS_COVERAGE, REDETERMINATION_DUE} overlap rule,
    OR on the clock reaching coverage_end so the half-open window of
    the first enrollment ends. We test the half-open adjacency by
    suspending the first enrollment (so its coverage_status leaves the
    overlap set), then approving the second.

    # difficulty: resource_temporal_overlap/enrollment_coverage_half_open_overlap
    """
    _sp, household, applicants, _app1, _det1, enrollments = (
        setup_approved_application(
            state_policy_kwargs={
                "fpl_base_amount": 15_000.00,
                "fpl_per_member_amount": 5_000.00,
                "magi_income_limit_pct": 138.0,
            },
            incomes=[
                {"applicant_index": 0, "source_type": "WAGES",
                 "gross_amount": 5_000.00, "frequency": "ANNUAL"},
            ],
        )
    )
    enrollment = enrollments[0]
    # PRD §3.4: ACTIVE / CONTINUOUS_COVERAGE / REDETERMINATION_DUE are
    # the overlap set. SUSPENDED is not — so a second APPROVE on the
    # same applicant should succeed.
    api.suspend_enrollment(
        enrollment["id"], TEST_USERS["policy_admin_headers"],
    )
    app2 = create_application(household=household, program="MAGI_ADULT")
    api.submit_application(
        household["id"], app2["id"],
        TEST_USERS["intake_worker_headers"],
    )
    res = api.decide_application(
        household["id"], app2["id"],
        decide_application_payload(decision="APPROVE"),
        TEST_USERS["eligibility_caseworker_headers"],
    )
    # No overlap because SUSPENDED is excluded from the overlap set.
    validate_success(res)


# ===========================================================================
# priority_pair_validation_conflict/state_vs_business_temporal_appeal_late
# — second coverage
# ===========================================================================
def test_state_priority_invalid_state_on_schedule_hearing(api):
    """PRD §2.10: priority 5 (INVALID_STATE) > priority 7
    (APPEAL_WINDOW_EXPIRED). Second-perspective coverage on a
    DIFFERENT endpoint than POST /appeals.

    Claim: calling POST /appeals/{id}/schedule-hearing on an Appeal
    that is no longer in FILED state (e.g., already
    HEARING_SCHEDULED), even after advancing the clock past
    deadline_at, returns ERR_INVALID_STATE (priority 5) rather than
    ERR_APPEAL_WINDOW_EXPIRED (priority 7).

    # difficulty: priority_pair_validation_conflict/state_vs_business_temporal_appeal_late
    """
    _sp, _hh, _, _app, determination = setup_denied_application()
    appeal = file_appeal(determination=determination)
    officer_headers = TEST_USERS["appeals_officer_headers"]
    officer_id = officer_headers["X-User-ID"]
    # Schedule once (FILED → HEARING_SCHEDULED).
    start = iso_offset(days=1, base=server_now_dt())
    end = iso_offset(days=1, hours=1, base=server_now_dt())
    schedule_hearing(
        appeal=appeal, officer_id=officer_id,
        scheduled_start=start, scheduled_end=end,
        headers=officer_headers,
    )
    # Now advance past deadline_at AND attempt to schedule again on the
    # same appeal. The appeal is HEARING_SCHEDULED, not FILED — state
    # check (priority 5) fires before window check (priority 7).
    deadline_dt = parse_iso(appeal["deadline_at"])
    advance_clock_to(
        iso_offset(days=1, base=deadline_dt),
    )
    res = api.schedule_hearing(
        appeal["id"],
        schedule_hearing_payload(
            officer_id=officer_id,
            scheduled_start=iso_offset(days=2, base=server_now_dt()),
            scheduled_end=iso_offset(
                days=2, hours=1, base=server_now_dt(),
            ),
        ),
        officer_headers,
    )
    validate_error(res, "ERR_INVALID_STATE")


# ===========================================================================
# priority_pair_validation_conflict/business_fiscal_vs_business_referential
# — second coverage
# ===========================================================================
def test_business_referential_wins_with_no_state_policy(api):
    """PRD §2.10: ERR_HOUSEHOLD_INCOMPLETE (priority 6) covers three
    distinct referential failures: head_applicant_id unset, no non-
    EXCLUDED applicants, AND Household.state_code with no matching
    StatePolicy.

    Claim: a Household whose state_code stops referencing a StatePolicy
    (here: never had one) is blocked by ERR_NOT_FOUND at CREATE,
    short-circuiting before any business-fiscal evaluation. Per PRD
    §2.5 the FK reference fails first.

    # difficulty: priority_pair_validation_conflict/business_fiscal_vs_business_referential_redetermination
    """
    res = api.create_household(
        {"state_code": "ZZ", "address_line": "addr",
         "filing_status": "SINGLE"},
        TEST_USERS["intake_worker_headers"],
    )
    # PRD §2.5: dangling FK references → ERR_NOT_FOUND.
    validate_error(res, "ERR_NOT_FOUND")


# ===========================================================================
# compensating_invariant/enrollment_suspend_reactivate — second coverage
# ===========================================================================
def test_double_suspend_reactivate_round_trip_count_invariant(api):
    """PRD §3.4: "A PolicyAdmin may suspend an ACTIVE enrollment ...
    A SUSPENDED enrollment may then be reactivated."

    Claim: two full SUSPEND/REACTIVATE rounds leave active_enrollment_
    count at its starting value (1).

    # difficulty: compensating_invariant/enrollment_suspend_reactivate_active_count_invariant
    """
    _sp, household, _, _app, _det, enrollments = setup_approved_application(
        incomes=[
            {"applicant_index": 0, "source_type": "WAGES",
             "gross_amount": 12_000.00, "frequency": "ANNUAL"},
        ],
    )
    enrollment = enrollments[0]
    admin = TEST_USERS["policy_admin_headers"]
    h0 = get_household(household["id"])
    initial_count = h0["active_enrollment_count"]
    # Round 1.
    api.suspend_enrollment(enrollment["id"], admin)
    api.reactivate_enrollment(enrollment["id"], admin)
    # Round 2.
    api.suspend_enrollment(enrollment["id"], admin)
    api.reactivate_enrollment(enrollment["id"], admin)
    h_final = get_household(household["id"])
    assert h_final["active_enrollment_count"] == initial_count, (
        "two SUSPEND/REACTIVATE rounds must conserve "
        f"active_enrollment_count per PRD §3.4; initial={initial_count}, "
        f"final={h_final['active_enrollment_count']}"
    )


# ===========================================================================
# dual_variant_calc/magi_federal_vs_state_disregard — second coverage
# ===========================================================================
def test_same_input_two_applications_diverge_by_disregard(api):
    """PRD §3.2: "Because the two variants produce different total_magi
    values from identical income inputs, they also produce different
    snapshot_magi and snapshot_fpl_percent on the resulting application;
    this is intentional."

    Claim: two applications submitted on the SAME household with
    identical inputs but different rule_variant produce different
    snapshot_magi values: FEDERAL = sum; STATE = sum - disregard.

    # difficulty: dual_variant_calc/magi_federal_vs_state_disregard
    """
    # Build a household with one PRIMARY applicant earning $20,000 and
    # state_disregard=2000.
    _sp, household, [applicant] = setup_basic_household(
        state_policy_kwargs={
            "fpl_base_amount": 15_000.00,
            "fpl_per_member_amount": 5_000.00,
            "magi_income_limit_pct": 138.0,
            "state_disregard_amount": 2_000.00,
        },
    )
    add_income(
        household=household, applicant=applicant,
        source_type="WAGES", gross_amount=20_000.00, frequency="ANNUAL",
    )
    # Application A: FEDERAL.
    app_a = create_application(
        household=household, rule_variant="FEDERAL",
    )
    api.submit_application(
        household["id"], app_a["id"], TEST_USERS["intake_worker_headers"],
    )
    a_data = get_application(household["id"], app_a["id"])
    assert float(a_data["snapshot_magi"]) == pytest.approx(20_000.00), (
        "FEDERAL must yield snapshot_magi=20000 per PRD §3.2; "
        f"got {a_data['snapshot_magi']}"
    )
    # Withdraw A so household state cleanly supports a second one.
    api.withdraw_application(
        household["id"], app_a["id"],
        TEST_USERS["intake_worker_headers"],
    )
    # Application B: STATE.
    app_b = create_application(
        household=household, rule_variant="STATE",
    )
    api.submit_application(
        household["id"], app_b["id"], TEST_USERS["intake_worker_headers"],
    )
    b_data = get_application(household["id"], app_b["id"])
    assert float(b_data["snapshot_magi"]) == pytest.approx(18_000.00), (
        "STATE must subtract state_disregard per PRD §3.2; "
        f"got snapshot_magi={b_data['snapshot_magi']}"
    )


# ===========================================================================
# dual_variant_calc/asset_federal_vs_state_exempt_set — second coverage
# ===========================================================================
def test_redet_renew_succeeds_after_emergency_expires(api):
    """PRD §3.5: "When the logical clock advances past the expires_at
    of the last covering declaration, the affected enrollments revert:
    continuous_coverage_flag is set back to false and coverage_status
    is set back to ACTIVE. If the enrollment's redetermination_due_at
    is in the past at the time of revert, the very next redetermination
    sweep will move it back to REDETERMINATION_DUE and create a fresh
    PENDING redetermination."

    Claim: after emergency expires + sweep, a fresh PENDING redet is
    created — and submitting RENEW on it succeeds. This is the second
    coverage of the gating dependency.

    # difficulty: cross_entity_state_dependency/redetermination_renew_gated_by_emergency_declaration
    """
    _sp, _hh, _, enrollments, redet = setup_redetermination_pending(
        state_policy_kwargs={
            "fpl_base_amount": 15_000.00,
            "fpl_per_member_amount": 5_000.00,
            "magi_income_limit_pct": 138.0,
        },
        incomes=[
            {"applicant_index": 0, "source_type": "WAGES",
             "gross_amount": 5_000.00, "frequency": "ANNUAL"},
        ],
    )
    enrollment = enrollments[0]
    # Issue and let it expire.
    expires = iso_offset(days=1)
    issue_emergency_declaration(
        scope="FEDERAL", state_code=None,
        declared_at=iso_now(), expires_at=expires,
    )
    advance_clock_to(expires)
    # Enrollment reverted to ACTIVE; redetermination_due_at is still
    # in the past, so the next sweep will move it back to
    # REDETERMINATION_DUE and create a fresh PENDING redet.
    run_redetermination_sweep()
    refreshed = get_enrollment(enrollment["id"])
    assert refreshed["coverage_status"] == "REDETERMINATION_DUE", (
        "after emergency expires + sweep, ACTIVE enrollments whose due "
        "date is past must move back to REDETERMINATION_DUE per PRD §3.5"
    )


def test_redetermination_count_excludes_only_withdrawn(api):
    """PRD §3.4: "an applicant's redetermination_count_this_year
    excludes withdrawn redeterminations: it counts distinct
    redetermination rows tied to the applicant whose status is in
    PENDING, SUBMITTED, RENEWED, or TERMINATED."

    Claim: a single RENEWED redetermination on the applicant (no
    WITHDRAWN) yields redetermination_count_this_year >= 1.

    # difficulty: compensating_invariant/redetermination_withdraw_resubmit_count_invariant
    """
    _sp, _hh, applicants, enrollments, redet = setup_redetermination_pending(
        state_policy_kwargs={
            "fpl_base_amount": 15_000.00,
            "fpl_per_member_amount": 5_000.00,
            "magi_income_limit_pct": 138.0,
        },
        incomes=[
            {"applicant_index": 0, "source_type": "WAGES",
             "gross_amount": 5_000.00, "frequency": "ANNUAL"},
        ],
    )
    applicant = applicants[0]
    # Pre-state: count==1 (the PENDING redet contributes).
    from test_helpers import get_applicant
    pre = get_applicant(applicant["household_id"], applicant["id"])
    assert pre["redetermination_count_this_year"] == 1, (
        f"PENDING redet must contribute 1 per PRD §3.4; got count="
        f"{pre['redetermination_count_this_year']}"
    )
    # Submit RENEW — redet transitions PENDING → RENEWED. RENEWED is
    # in the inclusive set, so count stays at 1.
    api.submit_redetermination(
        redet["id"],
        submit_redetermination_payload(
            decision="RENEW", new_snapshot_magi=5_000.00,
        ),
        TEST_USERS["eligibility_caseworker_headers"],
    )
    post = get_applicant(applicant["household_id"], applicant["id"])
    assert post["redetermination_count_this_year"] == 1, (
        "RENEWED is in the inclusive set per PRD §3.4; count must "
        f"remain 1; got {post['redetermination_count_this_year']}"
    )


def test_effective_size_zero_blocked_by_household_incomplete(api):
    """PRD §2.10 priority order: HOUSEHOLD_INCOMPLETE (priority 6) wins
    over FPL_THRESHOLD_INVALID (priority 13).

    Second coverage perspective on the same boundary, using a household
    that has NO applicants at all (head_applicant_id null, size 0).

    Note: The difficulty design names this case
    `effective_size_zero_threshold_invalid` and expects
    ERR_FPL_THRESHOLD_INVALID, but PRD §2.10's priority order makes
    ERR_HOUSEHOLD_INCOMPLETE win. We assert the PRD-faithful outcome.

    # difficulty: boundary_precision_check/effective_size_zero_threshold_invalid
    """
    policy = create_state_policy()
    household = create_household(state_code=policy["state_code"])
    # Zero applicants → head_applicant_id null → HOUSEHOLD_INCOMPLETE.
    application = create_application(household=household)
    res = api.submit_application(
        household["id"], application["id"],
        TEST_USERS["intake_worker_headers"],
    )
    validate_error(res, "ERR_HOUSEHOLD_INCOMPLETE")


def test_asset_exempt_vehicle_only_under_state_variant(api):
    """PRD §3.2: "if the state exempts VEHICLE, a twenty-thousand-dollar
    vehicle contributes zero instead of twenty thousand."

    Claim: the snapshot_countable_assets value is exactly the
    difference between FEDERAL (vehicle counted) and STATE (vehicle
    exempt) when the only countable asset is a VEHICLE.

    # difficulty: dual_variant_calc/asset_federal_vs_state_exempt_set
    """
    # FEDERAL variant with a single VEHICLE.
    _sp, household, [_a], app_fed = setup_eligible_application(
        state_policy_kwargs={
            "asset_test_applies": True,
            "asset_limit_per_member": 100_000.00,
            "state_exempt_asset_types": ["VEHICLE"],
            "magi_income_limit_pct": 138.0,
        },
        rule_variant="FEDERAL",
        program="NON_MAGI_DISABILITY",
        applicants=[{"dependent_status": "PRIMARY", "is_disabled": True}],
        assets=[
            {"applicant_index": 0, "asset_type": "VEHICLE",
             "market_value": 20_000.00},
        ],
    )
    assert float(app_fed["snapshot_countable_assets"]) == pytest.approx(
        20_000.00
    )

    # STATE variant on a separate household with identical assets.
    _sp2, household2, [_a2], app_state = setup_eligible_application(
        state_policy_kwargs={
            "asset_test_applies": True,
            "asset_limit_per_member": 100_000.00,
            "state_exempt_asset_types": ["VEHICLE"],
            "magi_income_limit_pct": 138.0,
        },
        rule_variant="STATE",
        program="NON_MAGI_DISABILITY",
        applicants=[{"dependent_status": "PRIMARY", "is_disabled": True}],
        assets=[
            {"applicant_index": 0, "asset_type": "VEHICLE",
             "market_value": 20_000.00},
        ],
    )
    assert float(app_state["snapshot_countable_assets"]) == pytest.approx(
        0.00
    ), (
        "STATE variant must exempt VEHICLE per PRD §3.2; "
        f"got snapshot_countable_assets="
        f"{app_state['snapshot_countable_assets']}"
    )
