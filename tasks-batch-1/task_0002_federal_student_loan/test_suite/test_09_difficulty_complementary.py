"""Complementary tests providing the second test per difficulty-design
instance — each test asserts a distinct facet of the same rule, never
duplicating the original.
"""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    set_clock, create_borrower, create_loan, walk_loan_to_repayment,
    setup_borrower_and_loan_in_repayment,
    setup_discharge_application_under_review,
    setup_idr_certified_borrower_in_repayment,
    setup_loan_with_active_standard_plan,
    create_and_certify_qualifying_employment,
    create_repayment_plan,
    post_payment, post_and_apply_payment,
    make_borrower_headers,
    create_repayment_plan_payload, create_payment_payload,
    TEST_USERS, ApiErrorId,
)


LS = TEST_USERS["loan_servicer_headers"]
CA = TEST_USERS["collections_agent_headers"]


# ─── interest_accrual_chronological_vs_sum_then_round_diverge ──

def test_interest_accrual_15_days_chronological(api):
    """A 15-day half-open interest window at principal=1_111_111 and rate=500
    bps produces a positive accrued_interest_cents value when computed per
    PRD's per-day chronological rounding rule — verifying that mid-window
    days are not skipped.

    PRD §3.3: "Interest accrual is the system's most pervasive computation:
    it runs implicitly on every Loan status transition and explicitly whenever
    the test-driving clock capability advances the server clock."
    PRD §3.3: "Once the window has been fully replayed, last_accrual_date is
    advanced to the current server clock."

    Design: Difficulty/dual_variant_calc/interest_accrual_chronological_vs_sum_then_round_diverge
    """
    set_clock("2026-06-01T00:00:00Z")
    borrower = create_borrower(full_name="Acc15", ssn_last4="0301")
    loan = create_loan(
        borrower["id"], loan_type="DIRECT_UNSUB",
        principal_cents=1_111_111, interest_rate_bps=500,
        disbursement_date="2026-06-01T00:00:00Z",
    )
    walk_loan_to_repayment(loan["id"])
    set_clock("2026-06-16T00:00:00Z")  # +15 days
    loan_after = validate_success(api.get_loan(loan["id"], LS), 200)
    # 15-day window must produce > 0 cents (positive accrual), strictly less
    # than the 30-day result (4560 cents).
    assert loan_after["accrued_interest_cents"] > 0
    assert loan_after["accrued_interest_cents"] < 4560


# ─── combinatorial_formula/idr_payment_mode_a_3_inputs_nonlinear ──

def test_save_alaska_diverges_from_save_ca_same_agi_family(api):
    """SAVE on the same AGI=6_000_000 and family_size=2 produces strictly
    smaller monthly_payment_cents for Alaska (631) than for CA (10513) —
    verifying the state-code input genuinely participates in the formula.

    PRD §3.5: "in the contiguous 48 states, a one-person base of $15,580 (held
    internally as 1558000 cents) and an additional $5,480 (548000 cents) per
    additional family member; in Alaska, a base of $19,470 (1947000 cents) and
    $6,860 (686000 cents) per additional member;"

    Design: Difficulty/combinatorial_formula/idr_payment_mode_a_3_inputs_nonlinear
    """
    # CA borrower → SAVE = 10513 (per scaffold's dual-variant computation).
    bca, lca, _ = setup_idr_certified_borrower_in_repayment(
        clock_iso="2026-06-01T00:00:00Z",
        full_name="CA SAVE", ssn_last4="0302",
        loan_type="DIRECT_UNSUB", principal_cents=3_000_000,
        interest_rate_bps=533,
        disbursement_date="2023-06-01T00:00:00Z",
        agi_cents=6_000_000, family_size=2, state_code="CA",
        income_effective_date="2026-05-01T00:00:00Z",
    )
    ca_save = validate_success(api.create_repayment_plan(
        create_repayment_plan_payload(
            lca["id"], lca["version"],
            plan_type="SAVE", effective_date="2026-06-01T00:00:00Z"),
        LS,
    ), 201)
    assert ca_save["monthly_payment_cents"] == 10513

    # AK borrower → SAVE = 631 (lower due to higher poverty line).
    bak, lak, _ = setup_idr_certified_borrower_in_repayment(
        clock_iso="2026-06-01T00:00:00Z",
        full_name="AK SAVE", ssn_last4="0303",
        loan_type="DIRECT_UNSUB", principal_cents=2_000_000,
        interest_rate_bps=500,
        disbursement_date="2023-06-01T00:00:00Z",
        agi_cents=6_000_000, family_size=2, state_code="AK",
        income_effective_date="2026-05-01T00:00:00Z",
    )
    ak_save = validate_success(api.create_repayment_plan(
        create_repayment_plan_payload(
            lak["id"], lak["version"],
            plan_type="SAVE", effective_date="2026-06-01T00:00:00Z"),
        LS,
    ), 201)
    assert ak_save["monthly_payment_cents"] == 631
    assert ak_save["monthly_payment_cents"] < ca_save["monthly_payment_cents"]


# ─── combinatorial_formula/interest_accrual_mode_b_round_per_day_then_sum_pinned ──

def test_interest_accrual_pinned_does_not_yield_sum_then_round_value(api):
    """A 30-day window must not produce the 4566 value associated with the
    rejected sum-then-round variant, but must equal the pinned 4560.

    PRD §3.3: "the engine does not sum fractional accruals across the window
    and then round at the end — the latter would produce different integer-cent
    results for the same inputs and is not the chosen interpretation."
    PRD §3.3: "The mandated order is essential: per-day rounding occurs before
    summation, status changes mid-window switch subsidy on or off on the
    correct calendar day, and the engine does not sum fractional accruals
    across the window and then round at the end — the latter would produce
    different integer-cent results for the same inputs and is not the chosen
    interpretation."

    Design: Difficulty/combinatorial_formula/interest_accrual_mode_b_round_per_day_then_sum_pinned
    """
    set_clock("2026-06-01T00:00:00Z")
    borrower = create_borrower(full_name="Mod B B", ssn_last4="0304")
    loan = create_loan(
        borrower["id"], loan_type="DIRECT_UNSUB",
        principal_cents=1_111_111, interest_rate_bps=500,
        disbursement_date="2026-06-01T00:00:00Z",
    )
    walk_loan_to_repayment(loan["id"])
    set_clock("2026-07-01T00:00:00Z")
    loan_after = validate_success(api.get_loan(loan["id"], LS), 200)
    assert loan_after["accrued_interest_cents"] == 4560
    assert loan_after["accrued_interest_cents"] != 4566


# ─── non_linear_state_machine/loan_cyclic_repayment_deferment_repayment ──

def test_status_change_log_contains_deferment_request_and_resume(api):
    """After REPAYMENT → DEFERMENT → REPAYMENT, the status-change log
    records the two reason_codes DEFERMENT_REQUEST and RESUME_REPAYMENT.

    PRD §3.4: "A deferment is requested directly against the loan,
    transitioning it from REPAYMENT to DEFERMENT; the resulting StatusChange
    carries reason_code DEFERMENT_REQUEST."
    PRD §3.3: "The two resume transitions are recorded with reason_code
    RESUME_REPAYMENT and share the same capitalization mechanic; from the
    borrower's standpoint, the practical effect is that paused interest
    becomes principal going forward."

    Design: Difficulty/non_linear_state_machine/loan_cyclic_repayment_deferment_repayment
    """
    borrower, loan = setup_borrower_and_loan_in_repayment(
        clock_iso="2026-06-01T00:00:00Z",
        full_name="Cyc2", ssn_last4="0305",
    )
    validate_success(
        api.request_deferment(loan["id"], make_borrower_headers(borrower["id"])),
        200,
    )
    validate_success(api.resume_repayment(loan["id"], LS), 200)

    data, _meta = validate_paginated(api.list_status_changes(loan["id"], LS))
    reasons = [sc["reason_code"] for sc in data]
    assert "DEFERMENT_REQUEST" in reasons
    assert "RESUME_REPAYMENT" in reasons


# ─── non_linear_state_machine/discharge_application_branching_approve_or_deny ──

def test_discharge_deny_branch_keeps_loan_in_repayment(api):
    """Compared to the APPROVE branch (which moves Loan to DISCHARGED), the
    DENY branch terminates the application without touching the parent Loan.

    PRD §3.9: "Denial moves the application from UNDER_REVIEW to DENIED and
    persists any supplied review_notes on the application; the version
    advances and updated_at refreshes."

    Design: Difficulty/non_linear_state_machine/discharge_application_branching_approve_or_deny
    """
    borrower, loan, app = setup_discharge_application_under_review(
        clock_iso="2026-06-01T00:00:00Z",
        is_veteran=True,  # would otherwise be approvable
        discharge_type="VETERAN_TOTAL_DISABILITY",
        full_name="Brn D", ssn_last4="0306",
    )
    res = api.deny_discharge(app["id"], {"review_notes": "denied for review"}, LS)
    denied = validate_success(res, 200)
    assert denied["status"] == "DENIED"

    loan_after = validate_success(api.get_loan(loan["id"], LS), 200)
    assert loan_after["status"] == "REPAYMENT"


# ─── transitive_cascade/discharge_approve_depth3_app_loan_payment ──

def test_discharge_approve_loan_balance_zeroed(api):
    """The middle hop of the depth-3 cascade — when the application transitions
    to APPROVED, the Loan's principal_balance_cents AND accrued_interest_cents
    are both set to zero.

    PRD §3.9: "First, the parent loan transitions from REPAYMENT to DISCHARGED,
    with principal_balance_cents and accrued_interest_cents both being set to
    zero, and a StatusChange is written with reason_code DISCHARGE_APPROVED."

    Design: Difficulty/transitive_cascade/discharge_approve_depth3_app_loan_payment
    """
    borrower, loan, app = setup_discharge_application_under_review(
        clock_iso="2026-06-01T00:00:00Z",
        is_veteran=True, discharge_type="VETERAN_TOTAL_DISABILITY",
        full_name="Csc B", ssn_last4="0307",
        loan_type="DIRECT_UNSUB", principal_cents=500_000,
        interest_rate_bps=500,
    )
    validate_success(api.approve_discharge(
        app["id"],
        {"review_notes": "approved",
         "expected_application_version": app["version"]},
        LS,
    ), 200)
    loan_after = validate_success(api.get_loan(loan["id"], LS), 200)
    assert loan_after["principal_balance_cents"] == 0
    assert loan_after["accrued_interest_cents"] == 0


# ─── transitive_cascade/default_declare_depth2_loan_plan ──

def test_default_cascade_sets_plan_superseded_by_to_null(api):
    """In the cascade-from-default branch, the affected plan's
    superseded_by_plan_id is set to null (statutory supersession), distinct
    from the create-then-activate branch which sets it to the new plan's id.

    PRD §3.8: "The transition also fires a cascade against any RepaymentPlan
    for that loan whose status is ACTIVE: each such plan is moved from ACTIVE
    to SUPERSEDED, has its superseded_by_plan_id set to null to mark the
    supersession as statutory rather than competitive, and has its version
    incremented independently of the loan's increment."

    Design: Difficulty/transitive_cascade/default_declare_depth2_loan_plan
    """
    borrower, loan, plan = setup_loan_with_active_standard_plan(
        clock_iso="2025-06-01T00:00:00Z",
        full_name="Csc D", ssn_last4="0308",
        loan_type="DIRECT_UNSUB", principal_cents=1_000_000,
        interest_rate_bps=500,
        disbursement_date="2025-06-01T00:00:00Z",
        plan_effective_date="2025-06-01T00:00:00Z",
    )
    set_clock("2026-03-10T00:00:00Z")
    validate_success(api.declare_default(loan["id"], CA), 200)
    plan_after = validate_success(api.get_repayment_plan(plan["id"], LS), 200)
    assert plan_after["status"] == "SUPERSEDED"
    assert plan_after.get("superseded_by_plan_id") is None


# ─── priority_pair_validation_conflict ──

def test_invalid_state_returned_when_loan_in_in_school_and_no_delinquency(api):
    """A loan in IN_SCHOOL (wrong state) AND with no delinquency: the state
    check fires (ERR_INVALID_STATE), confirming priority 6 wins over priority
    9 even when business constraint clearly would not pass.

    PRD §2.7: "6. State preconditions of the requested transition
    (ERR_INVALID_STATE)."

    Design: Difficulty/priority_pair_validation_conflict/priority_state_vs_business_safety_default_threshold_wins_over_invalid_state
    """
    set_clock("2026-06-01T00:00:00Z")
    borrower = create_borrower(full_name="StP B", ssn_last4="0309")
    loan = create_loan(
        borrower["id"], loan_type="DIRECT_UNSUB",
        principal_cents=100_000, interest_rate_bps=500,
        disbursement_date="2026-06-01T00:00:00Z",
    )
    validate_success(api.enter_school(loan["id"], LS), 200)
    res = api.declare_default(loan["id"], CA)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_unauthorized_returned_when_borrower_role_targets_nonexistent_resource(api):
    """Two-failure scenario: Borrower role (priority 2 unauthorized) + non-
    existent loan (priority 3 not found). Auth check wins.

    PRD §2.7: "1. Authentication header presence (ERR_UNAUTHENTICATED).
    2. Role authorization under the operation's role matrix (ERR_UNAUTHORIZED).
    3. Existence of any path-referenced Loan (ERR_LOAN_NOT_FOUND)."
    PRD §2.1: "These two checks always run first, before any existence or
    business validation."

    Design: Difficulty/priority_pair_validation_conflict/priority_existence_vs_auth_loan_not_found_wins_over_unauthorized
    """
    from test_helpers import NON_EXISTENT_UUID
    set_clock("2026-06-01T00:00:00Z")
    borrower = create_borrower(full_name="Pa2 B", ssn_last4="0310")
    # Borrower role tries CollectionsAgent-exclusive endpoint on non-existent loan.
    res = api.declare_default(
        NON_EXISTENT_UUID, make_borrower_headers(borrower["id"]))
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED.value)


# ─── boundary_precision_check/boundary_default_threshold_exactly_270_passes ──

def test_default_threshold_writes_default_declaration_status_change(api):
    """After a successful boundary default at delinquency_days==270, a
    StatusChange row carrying reason_code=DEFAULT_DECLARATION is appended.

    PRD §3.8: "The resulting StatusChange carries reason_code
    DEFAULT_DECLARATION."

    Design: Difficulty/boundary_precision_check/boundary_default_threshold_exactly_270_passes
    """
    set_clock("2025-06-01T00:00:00Z")
    borrower = create_borrower(full_name="BdSC", ssn_last4="0311")
    loan = create_loan(
        borrower["id"], loan_type="DIRECT_UNSUB",
        principal_cents=100_000, interest_rate_bps=500,
        disbursement_date="2025-06-01T00:00:00Z",
    )
    walk_loan_to_repayment(loan["id"])
    set_clock("2026-02-26T00:00:00Z")  # 270 days
    validate_success(api.declare_default(loan["id"], CA), 200)

    data, _meta = validate_paginated(api.list_status_changes(loan["id"], LS))
    reasons = [sc["reason_code"] for sc in data]
    assert "DEFAULT_DECLARATION" in reasons


# ─── boundary_precision_check/boundary_pslf_qualifying_employer_interval_closed_at_period_end ──

def test_pslf_count_increments_when_payment_on_period_end_qualifies(api):
    """In addition to the per-payment is_pslf_qualifying flag, the loan's
    aggregate pslf_qualifying_payment_count increments by one after a payment
    posted on period_end is APPLIED.

    PRD §3.7: "The same predicate set determines the is_pslf_qualifying
    boolean stored on each payment at the moment of PENDING to APPLIED
    transition."
    PRD §3.7: "Reads of the count off the loan are guaranteed to reflect the
    latest such recomputation."

    Design: Difficulty/boundary_precision_check/boundary_pslf_qualifying_employer_interval_closed_at_period_end
    """
    # Walk loan to REPAYMENT BEFORE period_end so the payment dated on
    # period_end can satisfy PRD §3.7 predicate 5.
    borrower, loan, _ = setup_loan_with_active_standard_plan(
        clock_iso="2026-01-01T00:00:00Z",
        full_name="BdPC2", ssn_last4="0312",
        loan_type="DIRECT_UNSUB", principal_cents=3_000_000,
        interest_rate_bps=533,
        disbursement_date="2025-01-01T00:00:00Z",
        plan_effective_date="2026-01-01T00:00:00Z",
    )
    create_and_certify_qualifying_employment(
        borrower["id"],
        employer_name="City Hall 2", employer_type="GOVERNMENT",
        period_start="2026-01-01T00:00:00Z",
        period_end="2026-06-30T00:00:00Z",
    )
    set_clock("2026-07-15T00:00:00Z")
    pay = post_payment(loan["id"], borrower["id"],
                       amount_cents=100_000, payment_date="2026-06-30T00:00:00Z")
    validate_success(api.apply_payment(pay["id"], LS), 200)
    loan_after = validate_success(api.get_loan(loan["id"], LS), 200)
    assert loan_after["pslf_qualifying_payment_count"] == 1


# ─── cross_entity_state_dependency/plan_activation_requires_loan_repayment_state ──

def test_plan_activation_on_repayment_loan_succeeds(api):
    """Positive complement: activating a PENDING plan whose parent Loan is in
    REPAYMENT succeeds — confirming the rule is direction-specific (REPAYMENT
    permits, other states reject).

    PRD §3.5: "Activation has three preconditions: the plan must currently be
    PENDING, the parent loan must be in REPAYMENT, and no other plan with the
    same loan_id may already be ACTIVE."

    Design: Difficulty/cross_entity_state_dependency/plan_activation_requires_loan_repayment_state
    """
    borrower, loan = setup_borrower_and_loan_in_repayment(
        clock_iso="2026-06-01T00:00:00Z",
        full_name="XR ok", ssn_last4="0313",
    )
    plan = create_repayment_plan(
        loan["id"], loan["version"],
        plan_type="STANDARD", effective_date="2026-06-01T00:00:00Z",
    )
    res = api.activate_repayment_plan(plan["id"], LS)
    activated = validate_success(res, 200)
    assert activated["status"] == "ACTIVE"


# ─── cross_entity_state_dependency/discharge_approve_pslf_requires_loan_qualifying_count ──

def test_pslf_count_read_off_loan_after_no_qualifying_payments(api):
    """A loan with no qualifying payments returns pslf_qualifying_payment_count
    == 0 — the prerequisite read that the discharge approver consults.

    PRD §3.7: "Public Service Loan Forgiveness depends on the loan's
    pslf_qualifying_payment_count, an integer derived from the borrower's
    payment, employment, and status histories."
    PRD §3.9: "when discharge_type is PSLF, the loan's
    pslf_qualifying_payment_count must be at least 120, and a lower value
    rejects with ERR_PSLF_INSUFFICIENT_PAYMENTS."

    Design: Difficulty/cross_entity_state_dependency/discharge_approve_pslf_requires_loan_qualifying_count
    """
    borrower, loan = setup_borrower_and_loan_in_repayment(
        clock_iso="2026-06-01T00:00:00Z",
        full_name="XR2", ssn_last4="0314",
    )
    loan_now = validate_success(api.get_loan(loan["id"], LS), 200)
    assert loan_now["pslf_qualifying_payment_count"] == 0


# ─── resource_temporal_overlap/qualifying_employment_closed_interval_inclusive_end ──

def test_pslf_payment_on_period_start_also_counts(api):
    """The closed-interval rule is symmetric: a payment dated on period_start
    is also included (closed at both ends).

    PRD §3.7: "Fourth, there must exist a QualifyingEmployment belonging to the
    loan's borrower whose status is CERTIFIED, whose employer_type is either
    GOVERNMENT or NONPROFIT_501C3, and whose employment window (the closed
    interval from period_start to period_end, inclusive at both ends) contains
    p's payment_date."

    Design: Difficulty/resource_temporal_overlap/qualifying_employment_closed_interval_inclusive_end
    """
    # Walk loan to REPAYMENT BEFORE period_start so the payment dated on
    # period_start can satisfy PRD §3.7 predicate 5 (loan in REPAYMENT on
    # payment_date). Then advance clock past payment_date so it is not future.
    borrower, loan, _ = setup_loan_with_active_standard_plan(
        clock_iso="2025-12-01T00:00:00Z",
        full_name="ItvB", ssn_last4="0315",
        loan_type="DIRECT_UNSUB", principal_cents=3_000_000,
        interest_rate_bps=533,
        disbursement_date="2025-01-01T00:00:00Z",
        plan_effective_date="2025-12-01T00:00:00Z",
    )
    create_and_certify_qualifying_employment(
        borrower["id"],
        employer_name="Borough", employer_type="GOVERNMENT",
        period_start="2026-01-01T00:00:00Z",
        period_end="2026-06-30T00:00:00Z",
    )
    # Advance clock to a moment after the intended payment_date.
    set_clock("2026-01-15T00:00:00Z")
    # Payment dated EXACTLY on period_start.
    pay = post_payment(
        loan["id"], borrower["id"],
        amount_cents=100_000, payment_date="2026-01-01T00:00:00Z",
    )
    applied = validate_success(api.apply_payment(pay["id"], LS), 200)
    assert applied["is_pslf_qualifying"] is True


# ─── compensating_invariant/payment_reverse_preserves_total_outstanding_plus_applied ──

def test_payment_reverse_loan_version_bumps(api):
    """Reversing an APPLIED payment increments both Payment.version and
    Loan.version. This is the second axis of the reversal contract.

    PRD §3.6: "Reversal moves the payment to REVERSED, recomputes
    pslf_qualifying_payment_count for the loan (because REVERSED payments are
    excluded from the count), and increments both Payment.version and
    Loan.version."

    Design: Difficulty/compensating_invariant/payment_reverse_preserves_total_outstanding_plus_applied
    """
    borrower, loan = setup_borrower_and_loan_in_repayment(
        clock_iso="2026-06-01T00:00:00Z",
        full_name="RvV", ssn_last4="0316",
        loan_type="DIRECT_UNSUB", principal_cents=1_000_000,
        interest_rate_bps=500,
    )
    pay = post_and_apply_payment(
        loan["id"], borrower["id"],
        amount_cents=50_000, payment_date="2026-06-01T00:00:00Z",
    )
    loan_pre = validate_success(api.get_loan(loan["id"], LS), 200)
    pay_pre_version = pay["version"]

    rev = validate_success(api.reverse_payment(pay["id"], LS), 200)
    loan_post = validate_success(api.get_loan(loan["id"], LS), 200)

    assert rev["status"] == "REVERSED"
    assert rev["version"] > pay_pre_version
    assert loan_post["version"] > loan_pre["version"]


# ─── compensating_invariant/pslf_count_excludes_reversed_payments_invariant ──

def test_pslf_count_returns_to_one_after_second_qualifying_payment_post_reverse(api):
    """After reversing the only qualifying payment (count → 0), posting and
    applying a second qualifying payment moves the count back to 1 —
    confirming the count is purely a function of currently-APPLIED qualifying
    payments.

    PRD §3.7: "The count is recomputed whenever any payment transitions
    between PENDING, APPLIED, and REVERSED; whenever a QualifyingEmployment
    becomes CERTIFIED; and whenever an IncomeCertification becomes CERTIFIED."

    Design: Difficulty/compensating_invariant/pslf_count_excludes_reversed_payments_invariant
    """
    borrower, loan, _ = setup_loan_with_active_standard_plan(
        clock_iso="2026-06-01T00:00:00Z",
        full_name="PsRv", ssn_last4="0317",
        loan_type="DIRECT_UNSUB", principal_cents=3_000_000,
        interest_rate_bps=533,
        disbursement_date="2025-01-01T00:00:00Z",
        plan_effective_date="2025-06-01T00:00:00Z",
    )
    create_and_certify_qualifying_employment(
        borrower["id"],
        employer_name="Dept Q", employer_type="GOVERNMENT",
        period_start="2025-01-01T00:00:00Z",
        period_end="2027-12-31T00:00:00Z",
    )
    pay1 = post_and_apply_payment(
        loan["id"], borrower["id"],
        amount_cents=100_000, payment_date="2026-06-01T00:00:00Z",
    )
    validate_success(api.reverse_payment(pay1["id"], LS), 200)
    loan_zero = validate_success(api.get_loan(loan["id"], LS), 200)
    assert loan_zero["pslf_qualifying_payment_count"] == 0

    post_and_apply_payment(
        loan["id"], borrower["id"],
        amount_cents=100_000, payment_date="2026-06-01T00:00:00Z",
    )
    loan_one = validate_success(api.get_loan(loan["id"], LS), 200)
    assert loan_one["pslf_qualifying_payment_count"] == 1
