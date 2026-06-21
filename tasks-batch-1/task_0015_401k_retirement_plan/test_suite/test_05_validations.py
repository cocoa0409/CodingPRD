"""Validation precedence, cross-entity state preconditions, temporal-overlap
constraints, and PRD-prose-named business errors.

Difficulty queue A — rule 5 (priority_pair_validation_conflict), rule 7
(cross_entity_state_dependency), rule 8 (resource_temporal_overlap).
Corner queue B — Section: validations.
"""
from test_helpers import (
    api_client,
    TEST_USERS,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    set_clock,
    create_and_activate_plan,
    create_and_enroll_participant,
    create_open_contribution_period,
    close_contribution_period,
    create_requested_loan,
    disburse_loan,
    setup_active_plan_with_enrolled_participant,
    setup_with_disbursed_loan,
    setup_participant_with_seeded_balances,
    setup_rmd_eligible_participant,
    create_loan_payload,
    repay_loan_payload,
    create_rmd_distribution_payload,
    create_contribution_period_payload,
    create_hardship_withdrawal_payload,
    create_participant_payload,
    create_pending_participant,
    get_participant,
)

_ADMIN = TEST_USERS["plan_admin_headers"]


# ─── Difficulty/priority_pair_validation_conflict ────────────────────────────

def test_state_check_beats_loan_limit_on_already_disbursed_loan(api):
    """PRD §2.10: "State eligibility runs fourth; a transition attempted against
    a resource whose current state does not permit it returns `ERR_INVALID_STATE`."
    PRD §2.10: "Business-safety, business-constraint, business-fiscal,
    business-temporal, and business-referential checks follow in that order..."

    A loan already in DISBURSED state hit by a second disburse must surface
    ERR_INVALID_STATE (state, priority 4), never ERR_LOAN_EXCEEDS_LIMIT
    (business-fiscal, lower priority).

    Design: Difficulty/priority_pair_validation_conflict/state_beats_business_fiscal_on_loan_disburse
    """
    _plan, _participant, loan = setup_with_disbursed_loan(
        plan_overrides={"name": "Prio", "match_formula": "TIERED",
                        "vesting_schedule": "GRADED_6"},
        gross_compensation_cents=10_000_000,
        loan_principal_cents=20_000,
    )
    res = api.disburse_loan(loan["id"], _ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_state_check_beats_loan_limit_loan_remains_disbursed_unchanged(api):
    """PRD §2.10: "When more than one validation rule applies to the same
    endpoint, the server evaluates them in a fixed priority order, returning the
    first violated rule and not continuing."

    Because the state check returns before any side-effecting handling, the loan
    that triggered ERR_INVALID_STATE remains in DISBURSED and its version is
    unchanged.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_business_fiscal_on_loan_disburse
    """
    _plan, _participant, loan = setup_with_disbursed_loan(
        plan_overrides={"name": "PrioB", "match_formula": "TIERED",
                        "vesting_schedule": "GRADED_6"},
        gross_compensation_cents=10_000_000,
        loan_principal_cents=20_000,
    )
    v_pre = loan["version"]
    res = api.disburse_loan(loan["id"], _ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    refreshed = get_success_data(api.get_loan(loan["id"], _ADMIN))
    assert refreshed["status"] == "DISBURSED"
    assert refreshed["version"] == v_pre


def test_existence_check_beats_state_on_unknown_loan_id(api):
    """PRD §2.10: "Existence of every path-templated parent runs third and returns
    `ERR_NOT_FOUND` on the first identifier in the path that does not resolve.
    State eligibility runs fourth..."

    A non-existent loan id passed to /loans/{id}/disburse must return
    ERR_NOT_FOUND (existence, priority 3), never ERR_INVALID_STATE.

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_state_on_unknown_loan
    """
    set_clock("2026-06-15T00:00:00Z")
    # Plan ACTIVE doesn't matter; the loan id is the missing entity.
    create_and_activate_plan(name="Existence", match_formula="TIERED",
                             vesting_schedule="CLIFF_3")
    res = api.disburse_loan("00000000-0000-0000-0000-000000000000", _ADMIN)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)


def test_existence_check_beats_state_on_unknown_repay_loan_id(api):
    """PRD §2.10: "Existence of every path-templated parent runs third and returns
    `ERR_NOT_FOUND` on the first identifier in the path that does not resolve."

    The rule is endpoint-agnostic — a missing loan id on /loans/{id}/repay also
    surfaces ERR_NOT_FOUND ahead of any state check.

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_state_on_unknown_loan
    """
    set_clock("2026-06-15T00:00:00Z")
    create_and_activate_plan(name="Existence2", match_formula="TIERED",
                             vesting_schedule="CLIFF_3")
    res = api.repay_loan("00000000-0000-0000-0000-000000000000",
                         repay_loan_payload(1_000), _ADMIN)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)


# ─── Difficulty/cross_entity_state_dependency ───────────────────────────────

def test_contribution_close_rejected_when_plan_frozen(api):
    """PRD §3.1: "While the plan is frozen, any attempt to open a new contribution
    period is rejected because contribution-period creation requires the plan to be
    in `ACTIVE` status."
    PRD §3.3: "Closing requires the plan to be `ACTIVE` and the participant to be
    `ENROLLED` (cross-entity preconditions)..."

    Frozen plan -> close of an OPEN ContributionPeriod returns ERR_INVALID_STATE.

    Design: Difficulty/cross_entity_state_dependency/contribution_close_requires_plan_active
    """
    set_clock("2026-06-15T00:00:00Z")
    plan = create_and_activate_plan(name="CE1", match_formula="TIERED",
                                    vesting_schedule="GRADED_6")
    participant = create_and_enroll_participant(
        plan["id"], full_name="J",
        date_of_birth="1980-06-15T00:00:00Z",
        hire_date="2024-06-15T00:00:00Z",
        annual_compensation_cents=12_000_000,
        deferral_rate_bps=400,
    )
    cp = create_open_contribution_period(participant["id"],
                                          period_end_date="2026-06-15T00:00:00Z",
                                          gross_compensation_cents=500_000)
    get_success_data(api.freeze_plan(plan["id"], _ADMIN))
    res = api.close_contribution_period(cp["id"], _ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_contribution_close_rejected_on_frozen_plan_period_stays_open(api):
    """PRD §3.3: "Closing requires the plan to be `ACTIVE` and the participant to
    be `ENROLLED` (cross-entity preconditions), and on success it runs the
    matching calculation and applies four cascades."

    On rejection the period remains OPEN and no balances are credited to the
    participant (no side effects from a rejected transition).

    Design: Difficulty/cross_entity_state_dependency/contribution_close_requires_plan_active
    """
    set_clock("2026-06-15T00:00:00Z")
    plan = create_and_activate_plan(name="CE1b", match_formula="TIERED",
                                    vesting_schedule="GRADED_6")
    participant = create_and_enroll_participant(
        plan["id"], full_name="J2",
        date_of_birth="1980-06-15T00:00:00Z",
        hire_date="2024-06-15T00:00:00Z",
        annual_compensation_cents=12_000_000,
        deferral_rate_bps=400,
    )
    cp = create_open_contribution_period(participant["id"],
                                          period_end_date="2026-06-15T00:00:00Z",
                                          gross_compensation_cents=500_000)
    get_success_data(api.freeze_plan(plan["id"], _ADMIN))
    res = api.close_contribution_period(cp["id"], _ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    # Period still OPEN; no balance side effect on participant.
    refreshed = get_success_data(api.get_contribution_period(cp["id"], _ADMIN))
    assert refreshed["status"] == "OPEN"
    p = get_participant(participant["id"])
    assert p["employee_balance_cents"] == 0
    assert p["employer_balance_cents"] == 0


def test_loan_disburse_rejected_when_participant_suspended(api):
    """PRD §3.4: "Disbursement requires the plan to be `ACTIVE` and the participant
    to be `ENROLLED` (cross-entity preconditions)."

    Suspended participant -> disburse of REQUESTED loan returns ERR_INVALID_STATE.

    Design: Difficulty/cross_entity_state_dependency/loan_disburse_requires_participant_enrolled
    """
    set_clock("2026-06-15T00:00:00Z")
    plan = create_and_activate_plan(name="CE2", match_formula="TIERED",
                                    vesting_schedule="GRADED_6")
    participant = create_and_enroll_participant(
        plan["id"], full_name="K",
        date_of_birth="1980-06-15T00:00:00Z",
        hire_date="2018-06-15T00:00:00Z",
        annual_compensation_cents=50_000_000,
        deferral_rate_bps=400,
    )
    cp = create_open_contribution_period(participant["id"],
                                          period_end_date="2026-06-15T00:00:00Z",
                                          gross_compensation_cents=10_000_000)
    close_contribution_period(cp["id"])
    loan = create_requested_loan(participant["id"], principal_cents=20_000,
                                 term_months=12, annual_interest_rate_bps=700)
    get_success_data(api.suspend_participant(participant["id"], _ADMIN))
    res = api.disburse_loan(loan["id"], _ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_loan_disburse_rejected_for_suspended_participant_keeps_loan_in_requested(api):
    """PRD §3.4: "Disbursement requires the plan to be `ACTIVE` and the participant
    to be `ENROLLED` (cross-entity preconditions)."

    Because the precondition fails the transition does not run; the loan stays
    in REQUESTED and the participant's outstanding_loan_principal_cents is
    unchanged (no depth-2 reconciliation).

    Design: Difficulty/cross_entity_state_dependency/loan_disburse_requires_participant_enrolled
    """
    set_clock("2026-06-15T00:00:00Z")
    plan = create_and_activate_plan(name="CE2b", match_formula="TIERED",
                                    vesting_schedule="GRADED_6")
    participant = create_and_enroll_participant(
        plan["id"], full_name="K2",
        date_of_birth="1980-06-15T00:00:00Z",
        hire_date="2018-06-15T00:00:00Z",
        annual_compensation_cents=50_000_000,
        deferral_rate_bps=400,
    )
    cp = create_open_contribution_period(participant["id"],
                                          period_end_date="2026-06-15T00:00:00Z",
                                          gross_compensation_cents=10_000_000)
    close_contribution_period(cp["id"])
    loan = create_requested_loan(participant["id"], principal_cents=20_000,
                                 term_months=12, annual_interest_rate_bps=700)
    get_success_data(api.suspend_participant(participant["id"], _ADMIN))
    res = api.disburse_loan(loan["id"], _ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    refreshed_loan = get_success_data(api.get_loan(loan["id"], _ADMIN))
    assert refreshed_loan["status"] == "REQUESTED"
    p = get_participant(participant["id"])
    assert p["outstanding_loan_principal_cents"] == 0


# ─── Difficulty/resource_temporal_overlap ───────────────────────────────────

def test_second_disburse_with_existing_active_loan_returns_already_outstanding(api):
    """PRD §3.4: "the participant must have no other loan whose status is
    `DISBURSED` — the one-loan-at-a-time rule — and a violation is rejected with
    `ERR_LOAN_ALREADY_OUTSTANDING`. This rule also encodes a temporal semantic:
    a loan's active interval runs from disbursement (inclusive) to terminal state
    (exclusive, where terminal means `REPAID` or `DEFAULTED`), and any overlap of
    two active intervals for the same participant is forbidden."

    Design: Difficulty/resource_temporal_overlap/loan_active_interval_overlap_half_open
    """
    _plan, participant, _loan_a = setup_with_disbursed_loan(
        plan_overrides={"name": "OvA", "match_formula": "TIERED",
                        "vesting_schedule": "GRADED_6"},
        gross_compensation_cents=10_000_000,
        loan_principal_cents=10_000,
    )
    loan_b = create_requested_loan(participant["id"], principal_cents=10_000,
                                   term_months=12, annual_interest_rate_bps=700)
    res = api.disburse_loan(loan_b["id"], _ADMIN)
    validate_error(res, ApiErrorId.ERR_LOAN_ALREADY_OUTSTANDING)


def test_active_loan_blocks_second_disburse_first_loan_remains_disbursed(api):
    """PRD §3.4: "the participant must have no other loan whose status is
    `DISBURSED` — the one-loan-at-a-time rule — and a violation is rejected with
    `ERR_LOAN_ALREADY_OUTSTANDING`."

    On rejection the first (already-DISBURSED) loan is unaffected and the
    second loan stays in REQUESTED — no version bump on either side.

    Design: Difficulty/resource_temporal_overlap/loan_active_interval_overlap_half_open
    """
    _plan, participant, loan_a = setup_with_disbursed_loan(
        plan_overrides={"name": "OvAb", "match_formula": "TIERED",
                        "vesting_schedule": "GRADED_6"},
        gross_compensation_cents=10_000_000,
        loan_principal_cents=10_000,
    )
    v_a_pre = loan_a["version"]
    loan_b = create_requested_loan(participant["id"], principal_cents=10_000,
                                   term_months=12, annual_interest_rate_bps=700)
    v_b_pre = loan_b["version"]
    res = api.disburse_loan(loan_b["id"], _ADMIN)
    validate_error(res, ApiErrorId.ERR_LOAN_ALREADY_OUTSTANDING)
    a = get_success_data(api.get_loan(loan_a["id"], _ADMIN))
    b = get_success_data(api.get_loan(loan_b["id"], _ADMIN))
    assert a["status"] == "DISBURSED"
    assert a["version"] == v_a_pre
    assert b["status"] == "REQUESTED"
    assert b["version"] == v_b_pre


def test_second_rmd_in_same_distribution_year_returns_duplicate(api):
    """PRD §3.6: "A second uniqueness rule prevents two distributions covering the
    same year: the pair (`participant_id`, `distribution_year`) is a closed,
    discrete bucket and must be unique across all `RMDDistribution` rows — an
    attempt to create a second distribution for the same participant in the same
    year is rejected with `ERR_DUPLICATE_RMD_YEAR`."

    Design: Difficulty/resource_temporal_overlap/rmd_distribution_year_uniqueness_closed_bucket
    """
    _plan, participant = setup_rmd_eligible_participant(
        plan_overrides={"name": "OvB", "match_formula": "TIERED",
                        "vesting_schedule": "CLIFF_3"},
    )
    get_success_data(api.create_rmd_distribution(
        create_rmd_distribution_payload(participant["id"], distribution_year=2026,
                                        prior_year_end_balance_cents=1_000_000,
                                        rmd_variant="UNIFORM_LIFETIME"),
        _ADMIN,
    ))
    res = api.create_rmd_distribution(
        create_rmd_distribution_payload(participant["id"], distribution_year=2026,
                                        prior_year_end_balance_cents=2_000_000,
                                        rmd_variant="UNIFORM_LIFETIME"),
        _ADMIN,
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_RMD_YEAR)


def test_duplicate_rmd_rejection_leaves_first_rmd_unchanged(api):
    """PRD §3.6: "the pair (`participant_id`, `distribution_year`) is a closed,
    discrete bucket and must be unique across all `RMDDistribution` rows — an
    attempt to create a second distribution for the same participant in the same
    year is rejected with `ERR_DUPLICATE_RMD_YEAR`."

    Because creation is rejected before any row is persisted, the original
    RMDDistribution is left intact — its prior_year_end_balance_cents and
    required_amount_cents are not overwritten by the second request.

    Design: Difficulty/resource_temporal_overlap/rmd_distribution_year_uniqueness_closed_bucket
    """
    _plan, participant = setup_rmd_eligible_participant(
        plan_overrides={"name": "OvBb", "match_formula": "TIERED",
                        "vesting_schedule": "CLIFF_3"},
    )
    first = get_success_data(api.create_rmd_distribution(
        create_rmd_distribution_payload(participant["id"], distribution_year=2026,
                                        prior_year_end_balance_cents=1_000_000,
                                        rmd_variant="UNIFORM_LIFETIME"),
        _ADMIN,
    ))
    assert first["prior_year_end_balance_cents"] == 1_000_000
    first_required = first["required_amount_cents"]
    res = api.create_rmd_distribution(
        create_rmd_distribution_payload(participant["id"], distribution_year=2026,
                                        prior_year_end_balance_cents=2_000_000,
                                        rmd_variant="UNIFORM_LIFETIME"),
        _ADMIN,
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_RMD_YEAR)
    # First RMD must be untouched.
    refreshed = get_success_data(api.get_rmd_distribution(first["id"], _ADMIN))
    assert refreshed["prior_year_end_balance_cents"] == 1_000_000
    assert refreshed["required_amount_cents"] == first_required


# ─── Corner/validations ─────────────────────────────────────────────────────

def test_deferral_limit_exceeded_when_cumulative_above_402g(api):
    """PRD §3.3: "That amount becomes `employee_contribution_cents`, capped further if necessary so that the plan-year cumulative employee deferrals do not exceed `annual_deferral_limit_cents` (the §402(g) cap; closing a period that would breach this cap is rejected with `ERR_DEFERRAL_LIMIT_EXCEEDED`)."

    Plan annual_deferral_limit_cents=10000, period would credit 20000 of
    employee_contribution_cents -> rejection.

    Design: Corner/validations/deferral_limit_exceeded_when_cumulative_above_402g
    """
    set_clock("2026-06-15T00:00:00Z")
    plan = create_and_activate_plan(
        name="Lim", match_formula="TIERED",
        vesting_schedule="CLIFF_3",
        annual_deferral_limit_cents=10_000,
    )
    participant = create_and_enroll_participant(
        plan["id"], full_name="L",
        date_of_birth="1980-06-15T00:00:00Z",
        hire_date="2024-06-15T00:00:00Z",
        annual_compensation_cents=12_000_000,
        deferral_rate_bps=400,
    )
    cp = create_open_contribution_period(participant["id"],
                                          period_end_date="2026-06-15T00:00:00Z",
                                          gross_compensation_cents=500_000)
    res = api.close_contribution_period(cp["id"], _ADMIN)
    validate_error(res, ApiErrorId.ERR_DEFERRAL_LIMIT_EXCEEDED)


def test_loan_exceeds_limit_when_principal_above_50pct_of_vested(api):
    """PRD §3.4: "the loan's `principal_cents` must not exceed the smaller of
    half the participant's vested savings — half of the sum of
    `employee_balance_cents` and `vested_employer_balance_cents`, with a floor
    applied — and the absolute statutory cap of 5,000,000 cents. A loan that
    exceeds this borrowing limit is rejected with `ERR_LOAN_EXCEEDS_LIMIT`."

    yos=2 GRADED_6 -> 40% vested. After one close at gross=500k, deferral=400bps:
    employee_balance=20000, employer_balance=17500, vested_employer=7000.
    vested_total=27000; half=13500. Loan principal=20000 > 13500 -> rejection.

    Design: Corner/validations/loan_exceeds_limit_when_principal_above_50pct_of_vested
    """
    set_clock("2026-06-15T00:00:00Z")
    plan = create_and_activate_plan(name="Lx", match_formula="TIERED",
                                    vesting_schedule="GRADED_6")
    participant = create_and_enroll_participant(
        plan["id"], full_name="Lx",
        date_of_birth="1980-06-15T00:00:00Z",
        hire_date="2024-06-15T00:00:00Z",   # yos=2 -> 40% vested
        annual_compensation_cents=12_000_000,
        deferral_rate_bps=400,
    )
    cp = create_open_contribution_period(participant["id"],
                                          period_end_date="2026-06-15T00:00:00Z",
                                          gross_compensation_cents=500_000)
    close_contribution_period(cp["id"])
    loan = create_requested_loan(participant["id"], principal_cents=20_000,
                                 term_months=12, annual_interest_rate_bps=700)
    res = api.disburse_loan(loan["id"], _ADMIN)
    validate_error(res, ApiErrorId.ERR_LOAN_EXCEEDS_LIMIT)


def test_joint_life_ineligible_when_spouse_gap_5_years(api):
    """PRD §3.6: "the variant is only eligible if the spouse is more than 10 years
    younger than the participant — i.e., the participant's age minus the spouse's
    age must be strictly greater than 10; if the age gap is 10 years or less, the
    request is rejected with `ERR_JOINT_LIFE_INELIGIBLE`."

    Participant 73 at 2026-12-31; spouse 68 at 2026-12-31 -> gap 5 -> rejection.

    Design: Corner/validations/joint_life_ineligible_when_spouse_gap_too_small
    """
    _plan, participant = setup_rmd_eligible_participant(
        plan_overrides={"name": "JLi", "match_formula": "TIERED",
                        "vesting_schedule": "CLIFF_3"},
    )
    res = api.create_rmd_distribution(
        create_rmd_distribution_payload(
            participant["id"], distribution_year=2026,
            prior_year_end_balance_cents=1_000_000,
            rmd_variant="JOINT_LIFE",
            spouse_date_of_birth="1959-01-01T00:00:00Z",  # age 67 at year-end -> gap 6
        ),
        _ADMIN,
    )
    validate_error(res, ApiErrorId.ERR_JOINT_LIFE_INELIGIBLE)


def test_no_hardship_headroom_when_balances_zero(api):
    """PRD §3.5: "The approval transition `REQUESTED → APPROVED` is gated on the
    plan being `ACTIVE`, the participant being in either `ENROLLED` or `SUSPENDED`
    status (cross-entity preconditions), and the maximum hardship amount
    computation producing a strictly positive value — if it does not, the request
    is rejected with `ERR_NO_HARDSHIP_HEADROOM`."

    Participant with zero balances -> max_hardship_amount = max(0, min(0, hard_cap,
    requested)) = 0 -> approve returns ERR_NO_HARDSHIP_HEADROOM.

    Design: Corner/validations/no_hardship_headroom_when_balances_zero
    """
    set_clock("2026-06-15T00:00:00Z")
    plan = create_and_activate_plan(name="NoH", match_formula="TIERED",
                                    vesting_schedule="GRADED_6")
    participant = create_and_enroll_participant(
        plan["id"], full_name="Empty",
        date_of_birth="1981-06-15T00:00:00Z",
        hire_date="2024-06-15T00:00:00Z",
        annual_compensation_cents=12_000_000,
        deferral_rate_bps=400,
    )
    h = get_success_data(api.create_hardship_withdrawal(
        create_hardship_withdrawal_payload(participant["id"],
                                           requested_amount_cents=100_000,
                                           hardship_category="MEDICAL_EXPENSES"),
        _ADMIN,
    ))
    res = api.approve_hardship(h["id"], _ADMIN)
    validate_error(res, ApiErrorId.ERR_NO_HARDSHIP_HEADROOM)
