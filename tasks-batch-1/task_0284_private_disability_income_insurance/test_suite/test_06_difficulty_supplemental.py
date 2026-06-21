"""Supplemental coverage for the deeper compliance scenarios.

A second, distinct-facet test for each deep scenario whose primary test lives in
test_02/test_03/test_04/test_05. Each test here asserts a different observable
outcome (or a different scenario of the same rule), so each scenario carries at
least two executing tests. Every assertion is independently PRD-cited.
"""
from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated, get_success_data,
    TEST_USERS, make_policyholder_headers,
    setup_active_policy, setup_under_review_claim, setup_approved_claim,
    setup_approved_total_with_periods, setup_approved_residual_with_report,
    setup_total_claim_with_period_and_estimated_offset,
    create_insurer, advance_clock, create_occupation_class, create_policyholder,
    create_policy, file_claim, add_income_report, add_offset_award, finalize_offset,
    drive_premium_to_grace, drive_premium_to_default,
)

UW = TEST_USERS["underwriter_headers"]
ADJ = TEST_USERS["claims_adjudicator_headers"]
OPR = TEST_USERS["system_operator_headers"]


# ─── dual_variant_calc ────────────────────────────────

def test_residual_proportionate_variant_pays_loss_fraction(api):
    """PRD §3.9: "the fraction is 0.0 when R is below the minimum loss ratio of
    0.20, is 1.0 (a presumptive total) when R is at or above the presumed-total
    ratio of 0.80, and otherwise equals R itself rounded to four decimal places."

    Design: Difficulty/dual_variant_calc/residual_factor_proportionate_vs_presumptive_total
    """
    book = setup_approved_residual_with_report(
        effective_month=3, current_monthly_income_cents=500000, clock_months=5,
        occ_overrides={"own_occ_window_months_cap": 0},
    )  # ANY_OCC, R=0.50 -> proportionate fraction 0.5
    bp = validate_success(
        api.create_benefit_period(book["claim"]["id"], {"coverage_month": 3}, ADJ), 201
    )
    assert bp["benefit_fraction"] == 0.5
    assert bp["gross_benefit_cents"] == 250000


def test_net_benefit_provisional_before_finalize(api):
    """PRD §3.10: "an ESTIMATED award contributes a provisional offset and a
    FINALIZED award contributes the reconciled offset, which is the source of the
    provisional-versus-final distinction in the net computation."

    Design: Difficulty/dual_variant_calc/net_benefit_provisional_vs_final_offset
    """
    book = setup_total_claim_with_period_and_estimated_offset(
        offset_source="SSDI", monthly_offset_cents=120000, offset_window=(3, 5),
        coverage_month=3, clock_months=5,
    )
    bp = validate_success(api.get_benefit_period(book["benefit_period"]["id"], ADJ), 200)
    assert bp["net_benefit_cents"] == 380000  # provisional: 500000 - 120000


# ─── combinatorial_formula ────────────────────────────

def test_cola_multiplier_capped_at_two_x(api):
    """PRD §3.10: "Otherwise the multiplier compounds the annual rate over the
    elapsed years ... and is then capped at the maximum COLA multiplier of 2.0, so
    escalation can never more than double the base benefit."

    Design: Difficulty/combinatorial_formula/cola_compound_capped_gross_benefit
    """
    insurer = create_insurer()
    advance_clock(insurer["id"], 110)
    occ = create_occupation_class(insurer["id"], code="MED", risk_tier="MEDIUM",
                                  max_benefit_months=600, min_elimination_days=0,
                                  own_occ_window_months_cap=0)
    ph = create_policyholder(insurer["id"], pre_disability_monthly_income_cents=1000000)
    ph_id = ph["id"]
    policy = create_policy(insurer["id"], ph_id, occ["id"], monthly_benefit_cents=500000,
                           benefit_period_months=120, elimination_period_days=90,
                           occupation_definition="ANY_OCC", cola_rider=True,
                           cola_annual_rate=0.10)
    get_success_data(api.activate_policy(policy["id"], UW))
    claim = file_claim(insurer["id"], policy["id"], ph_id, claimed_disability_type="TOTAL")
    get_success_data(api.submit_claim(claim["id"], make_policyholder_headers(ph_id)))
    get_success_data(api.begin_review(claim["id"], ADJ))
    get_success_data(api.approve_claim(claim["id"], ADJ))
    # Keep proofs current up to month 99 (due starts 6, +3 each accept).
    for m in range(6, 100, 3):
        get_success_data(api.create_disability_proof(
            claim["id"], {"attestation_month": m, "still_disabled": True},
            make_policyholder_headers(ph_id),
        ))
    bp = validate_success(api.create_benefit_period(claim["id"], {"coverage_month": 99}, ADJ), 201)
    # years_elapsed = floor((99-3)/12) = 8 ; 1.10^8 ~ 2.1436 capped at 2.0 -> 1000000.
    assert bp["gross_benefit_cents"] == 1000000


def test_net_waterfall_intermediate_gross_and_offset(api):
    """PRD §3.10: "the evaluation order is fixed: the benefit fraction is settled
    first, then the gross benefit, then the offset applied, then the net benefit."

    Design: Difficulty/combinatorial_formula/net_benefit_pinned_evaluation_order_waterfall
    """
    book = setup_approved_residual_with_report(
        effective_month=3, current_monthly_income_cents=500000, clock_months=5,
        occ_overrides={"own_occ_window_months_cap": 0},
    )  # R=0.50 -> fraction 0.5, gross 250000
    cid = book["claim"]["id"]
    add_offset_award(cid, "SSDI", 300000, 3, 5)
    bp = validate_success(api.create_benefit_period(cid, {"coverage_month": 3}, ADJ), 201)
    # gross 250000, offset 300000 -> gross < offset, so the floor governs.
    assert bp["gross_benefit_cents"] == 250000
    assert bp["offset_applied_cents"] == 300000


# ─── non_linear_state_machine ──── (already 2 each in test_02) ──


# ─── transitive_cascade ───────────────────────────────

def test_accrual_recomputes_ledger_gross_total(api):
    """PRD §3.9: "On a successful accrual the policy's benefit_months_consumed
    increases by this period's benefit_fraction, the claim ledger totals are
    recomputed".
    PRD §3.12: "Its total_gross_paid_cents is the sum of gross_benefit_cents over
    the claim's ACCRUED benefit periods".

    Design: Difficulty/transitive_cascade/accrual_drives_ledger_then_exhaustion_depth3
    """
    book = setup_approved_total_with_periods([3], clock_months=5,
                                             policy_overrides={"benefit_period_months": 2})
    cid = book["claim"]["id"]
    get_success_data(api.create_benefit_period(cid, {"coverage_month": 4}, ADJ))
    ledger, _ = validate_paginated(api.get_claim_ledger(cid, ADJ))
    # Both periods ACCRUED at gross 500000 each.
    assert ledger[0]["total_gross_paid_cents"] == 1000000


def test_lapse_cascade_sets_policy_lapsed(api):
    """PRD §3.3: "Entering DEFAULT is consequential: it triggers the lapse cascade,
    in which the policy's lifecycle_status moves from ACTIVE to LAPSED".

    Design: Difficulty/transitive_cascade/premium_default_lapses_policy_then_suspends_claim_depth2
    """
    book = setup_approved_claim(clock_months=5)
    pid = book["policy"]["id"]
    drive_premium_to_grace(pid)
    policy_after = validate_success(api.premium_miss(pid, UW), 200)
    assert policy_after["premium_status"] == "DEFAULT"
    assert policy_after["lifecycle_status"] == "LAPSED"


# ─── compensating_invariant ───────────────────────────

def test_claim_reverse_zeroes_ledger_and_reverses_periods(api):
    """PRD §3.7: "every ACCRUED benefit period on the claim is moved to REVERSED;
    the claim ledger's total_gross_paid_cents, total_net_paid_cents, and
    overpayment_balance_cents are recomputed to 0".

    Design: Difficulty/compensating_invariant/claim_reverse_restores_benefit_months_consumed
    """
    book = setup_approved_total_with_periods([3, 4], clock_months=6)
    cid = book["claim"]["id"]
    bp_ids = [bp["id"] for bp in book["benefit_periods"]]
    get_success_data(api.reverse_claim(cid, ADJ))
    ledger, _ = validate_paginated(api.get_claim_ledger(cid, ADJ))
    assert ledger[0]["total_gross_paid_cents"] == 0
    assert ledger[0]["total_net_paid_cents"] == 0
    for bp_id in bp_ids:
        bp = validate_success(api.get_benefit_period(bp_id, ADJ), 200)
        assert bp["status"] == "REVERSED"


def test_offset_void_restores_benefit_period_net(api):
    """PRD §3.11: "Voiding moves the award to the terminal VOID status (where its
    effective_offset_cents resolves to 0) ... every affected ACCRUED benefit period
    recomputes offset_applied_cents and net_benefit_cents excluding this award".

    Design: Difficulty/compensating_invariant/offset_void_restores_overpayment_balance
    """
    book = setup_total_claim_with_period_and_estimated_offset(
        offset_source="SSDI", monthly_offset_cents=120000, offset_window=(3, 5),
        coverage_month=3, clock_months=5,
    )
    oa_id = book["offset_award"]["id"]
    bp_id = book["benefit_period"]["id"]
    finalize_offset(oa_id, 200000)
    voided = validate_success(api.void_offset_award(oa_id, ADJ), 200)
    assert voided["status"] == "VOID"
    bp = validate_success(api.get_benefit_period(bp_id, ADJ), 200)
    assert bp["offset_applied_cents"] == 0
    assert bp["net_benefit_cents"] == 500000


# ─── cross_entity_state_dependency ────────────────────

def test_approve_rejected_leaves_claim_under_review(api):
    """PRD §3.6: "The policy's lifecycle must be ACTIVE (ERR_POLICY_NOT_ACTIVE)."
    PRD §3.6: "On success the claim moves from UNDER_REVIEW to APPROVED and its
    version increments."

    Design: Difficulty/cross_entity_state_dependency/claim_approve_blocked_by_policy_premium_default
    """
    book = setup_under_review_claim(clock_months=5)
    cid = book["claim"]["id"]
    drive_premium_to_default(book["policy"]["id"])
    validate_error(api.approve_claim(cid, ADJ), "ERR_POLICY_NOT_ACTIVE")
    claim_after = validate_success(api.get_claim(cid, ADJ), 200)
    assert claim_after["status"] == "UNDER_REVIEW"


def test_accrual_rejected_creates_no_benefit_period(api):
    """PRD §3.9: "The parent claim must be APPROVED (otherwise
    ERR_CLAIM_NOT_PAYABLE)."

    Design: Difficulty/cross_entity_state_dependency/benefit_accrual_blocked_by_claim_not_approved
    """
    book = setup_active_policy(clock_months=5)
    claim = file_claim(book["insurer"]["id"], book["policy"]["id"],
                       book["policyholder"]["id"], claimed_disability_type="TOTAL")
    get_success_data(api.submit_claim(claim["id"],
                                      make_policyholder_headers(book["policyholder"]["id"])))
    validate_error(api.create_benefit_period(claim["id"], {"coverage_month": 3}, ADJ),
                   "ERR_CLAIM_NOT_PAYABLE")
    listed, meta = validate_paginated(api.list_claim_benefit_periods(claim["id"], ADJ))
    assert meta["total_count"] == 0


# ─── priority_pair_validation_conflict ────────────────

def test_first_accrual_exhausts_claim_at_cap(api):
    """PRD §3.9: "if the consumed months reach or exceed the contract's
    benefit_period_months the claim transitions from APPROVED to the terminal
    BENEFIT_EXHAUSTED status".

    Design: Difficulty/priority_pair_validation_conflict/payable_constraint_vs_fiscal_on_accrual_constraint_wins
    """
    book = setup_approved_total_with_periods([3], clock_months=6,
                                             policy_overrides={"benefit_period_months": 1})
    claim = validate_success(api.get_claim(book["claim"]["id"], ADJ), 200)
    assert claim["status"] == "BENEFIT_EXHAUSTED"  # consumed 1.0 == cap 1


def test_offset_overlap_rejected_when_claim_approved(api):
    """PRD §3.11: "Only after that gate passes is the window checked for collision:
    the new window may not overlap any existing non-VOID offset award of the same
    offset_source on the claim ... and are rejected with ERR_OFFSET_WINDOW_OVERLAP."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_temporal_overlap_on_offset_create_state_wins
    """
    book = setup_approved_total_with_periods([], clock_months=5)
    cid = book["claim"]["id"]
    add_offset_award(cid, "SSDI", 120000, 3, 5)
    # Claim still APPROVED: state gate passes, so the overlap check governs.
    resp = api.create_offset_award(
        cid, {"offset_source": "SSDI", "monthly_offset_cents": 90000,
              "start_month": 4, "end_month": 6}, ADJ,
    )
    validate_error(resp, "ERR_OFFSET_WINDOW_OVERLAP")


# ─── boundary_precision_check ─────────────────────────

def test_elimination_boundary_succeeds_above_threshold(api):
    """PRD §3.6: "the current month index must be greater than or equal to the
    elimination satisfied month — or the approval is rejected with
    ERR_ELIMINATION_NOT_SATISFIED."

    Design: Difficulty/boundary_precision_check/elimination_satisfied_boundary_ge_on_approve
    """
    book = setup_under_review_claim(clock_months=4,
                                    policy_overrides={"elimination_period_days": 90})
    # elim_sat = 0 + ceil(90/30) = 3 ; current month 4 > 3 -> approve succeeds.
    approved = validate_success(api.approve_claim(book["claim"]["id"], ADJ), 200)
    assert approved["status"] == "APPROVED"


def test_residual_income_loss_ratio_computed_below_floor(api):
    """PRD §3.8: "The system computes the report's income_loss_ratio as the
    pre-disability monthly income minus the current monthly income, divided by the
    pre-disability monthly income, with any negative result floored at 0 and the
    quotient rounded to four decimal places."

    Design: Difficulty/boundary_precision_check/residual_min_loss_ratio_zero_benefit_boundary
    """
    book = setup_approved_residual_with_report(
        effective_month=3, current_monthly_income_cents=850000, clock_months=5,
        occ_overrides={"own_occ_window_months_cap": 0},
    )  # R = (1000000-850000)/1000000 = 0.15
    reports, _ = validate_paginated(api.list_income_reports(book["claim"]["id"], ADJ))
    assert reports[0]["income_loss_ratio"] == 0.15


# ─── resource_temporal_overlap ────────────────────────

def test_offset_touching_collides_from_lower_side(api):
    """PRD §3.11: "because the interval is closed and carries a one-month no-touch
    buffer, two windows that merely touch (the end of one equal to the start of the
    other) collide and are rejected with ERR_OFFSET_WINDOW_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/offset_window_closed_interval_touching_collides
    """
    book = setup_approved_total_with_periods([], clock_months=8)
    cid = book["claim"]["id"]
    add_offset_award(cid, "SSDI", 120000, 5, 7)
    # New [3,5] touches existing [5,7] at month 5.
    resp = api.create_offset_award(
        cid, {"offset_source": "SSDI", "monthly_offset_cents": 90000,
              "start_month": 3, "end_month": 5}, ADJ,
    )
    validate_error(resp, "ERR_OFFSET_WINDOW_OVERLAP")


def test_benefit_period_duplicate_month_collides(api):
    """PRD §3.9: "No other ACCRUED benefit period on the claim may already cover
    this coverage month; a duplicate is rejected with ERR_COVERAGE_MONTH_OCCUPIED."

    Design: Difficulty/resource_temporal_overlap/benefit_period_half_open_consecutive_months_allowed
    """
    book = setup_approved_total_with_periods([3], clock_months=6)
    resp = api.create_benefit_period(book["claim"]["id"], {"coverage_month": 3}, ADJ)
    validate_error(resp, "ERR_COVERAGE_MONTH_OCCUPIED")
