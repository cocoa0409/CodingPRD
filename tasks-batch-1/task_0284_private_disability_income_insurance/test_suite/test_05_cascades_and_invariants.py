"""Transitive cascades, conservation invariants under reverse/void, cross-entity
state dependencies, validation-priority conflicts, and the elimination boundary.
"""
from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated, get_success_data,
    TEST_USERS, make_policyholder_headers,
    setup_under_review_claim, setup_approved_claim,
    setup_approved_total_with_periods,
    setup_active_policy,
    setup_total_claim_with_period_and_estimated_offset,
    file_claim, add_offset_award, finalize_offset,
    drive_premium_to_grace, drive_premium_to_default,
)

UW = TEST_USERS["underwriter_headers"]
ADJ = TEST_USERS["claims_adjudicator_headers"]


# ─── Difficulty / transitive_cascade ──────────────────

def test_accrual_drives_ledger_then_exhaustion_depth3(api):
    """PRD §3.9: "On a successful accrual the policy's benefit_months_consumed
    increases by this period's benefit_fraction, the claim ledger totals are
    recomputed, and if the consumed months reach or exceed the contract's
    benefit_period_months the claim transitions from APPROVED to the terminal
    BENEFIT_EXHAUSTED status (incrementing the claim version), after which no
    further benefit periods may accrue."

    Design: Difficulty/transitive_cascade/accrual_drives_ledger_then_exhaustion_depth3
    """
    book = setup_approved_total_with_periods([3], clock_months=5,
                                             policy_overrides={"benefit_period_months": 2})
    cid = book["claim"]["id"]
    pid = book["policy"]["id"]
    bp2 = validate_success(api.create_benefit_period(cid, {"coverage_month": 4}, ADJ), 201)
    assert bp2["gross_benefit_cents"] == 500000
    policy_after = validate_success(api.get_policy(pid, UW), 200)
    assert policy_after["benefit_months_consumed"] == 2.0
    claim_after = validate_success(api.get_claim(cid, ADJ), 200)
    assert claim_after["status"] == "BENEFIT_EXHAUSTED"


def test_premium_default_lapses_policy_then_suspends_claim_depth2(api):
    """PRD §3.3: "Entering DEFAULT is consequential: it triggers the lapse cascade,
    in which the policy's lifecycle_status moves from ACTIVE to LAPSED ... and every
    claim on the policy currently in APPROVED status is swept from APPROVED to
    SUSPENDED so that no new benefit installments may accrue while the policy is
    lapsed."

    Design: Difficulty/transitive_cascade/premium_default_lapses_policy_then_suspends_claim_depth2
    """
    book = setup_approved_claim(clock_months=5)
    pid = book["policy"]["id"]
    cid = book["claim"]["id"]
    drive_premium_to_grace(pid)
    policy_after = validate_success(api.premium_miss(pid, UW), 200)
    assert policy_after["premium_status"] == "DEFAULT"
    assert policy_after["lifecycle_status"] == "LAPSED"
    claim_after = validate_success(api.get_claim(cid, ADJ), 200)
    assert claim_after["status"] == "SUSPENDED"


# ─── Difficulty / compensating_invariant ──────────────

def test_claim_reverse_restores_benefit_months_consumed(api):
    """PRD §3.7: "every ACCRUED benefit period on the claim is moved to REVERSED;
    the claim ledger's total_gross_paid_cents, total_net_paid_cents, and
    overpayment_balance_cents are recomputed to 0; and the policy's
    benefit_months_consumed is decreased by the sum of the benefit_fraction values
    of the reversed periods, honoring the conserved-quantity invariant that
    consumed months track exactly the active installments."

    Design: Difficulty/compensating_invariant/claim_reverse_restores_benefit_months_consumed
    """
    book = setup_approved_total_with_periods([3, 4], clock_months=6)
    cid = book["claim"]["id"]
    pid = book["policy"]["id"]
    before = validate_success(api.get_policy(pid, UW), 200)
    assert before["benefit_months_consumed"] == 2.0
    reversed_claim = validate_success(api.reverse_claim(cid, ADJ), 200)
    assert reversed_claim["status"] == "DENIED"
    after = validate_success(api.get_policy(pid, UW), 200)
    assert after["benefit_months_consumed"] == 0.0


def test_offset_void_restores_overpayment_balance(api):
    """PRD §3.11: "Voiding moves the award to the terminal VOID status ... and the
    ledger's total_net_paid_cents and overpayment_balance_cents return to their
    pre-finalize values — when a previously finalized award is voided, the exact
    overpayment delta that finalize added is subtracted back, honoring the
    conserved-quantity invariant."

    Design: Difficulty/compensating_invariant/offset_void_restores_overpayment_balance
    """
    book = setup_total_claim_with_period_and_estimated_offset(
        offset_source="SSDI", monthly_offset_cents=120000, offset_window=(3, 5),
        coverage_month=3, clock_months=5,
    )
    cid = book["claim"]["id"]
    oa_id = book["offset_award"]["id"]
    bp_id = book["benefit_period"]["id"]
    finalize_offset(oa_id, 200000)
    ledger_after_finalize, _ = validate_paginated(api.get_claim_ledger(cid, ADJ))
    assert ledger_after_finalize[0]["overpayment_balance_cents"] == 80000
    voided = validate_success(api.void_offset_award(oa_id, ADJ), 200)
    assert voided["status"] == "VOID"
    ledger_after_void, _ = validate_paginated(api.get_claim_ledger(cid, ADJ))
    assert ledger_after_void[0]["overpayment_balance_cents"] == 0
    bp_after = validate_success(api.get_benefit_period(bp_id, ADJ), 200)
    assert bp_after["net_benefit_cents"] == 500000  # offset removed


# ─── Difficulty / cross_entity_state_dependency ───────

def test_claim_approve_blocked_by_policy_premium_default(api):
    """PRD §3.6: "The policy's lifecycle must be ACTIVE (ERR_POLICY_NOT_ACTIVE)."

    Design: Difficulty/cross_entity_state_dependency/claim_approve_blocked_by_policy_premium_default
    """
    book = setup_under_review_claim(clock_months=5)
    pid = book["policy"]["id"]
    cid = book["claim"]["id"]
    drive_premium_to_default(pid)  # GRACE -> DEFAULT lapses lifecycle to LAPSED
    resp = api.approve_claim(cid, ADJ)
    validate_error(resp, "ERR_POLICY_NOT_ACTIVE")


def test_benefit_accrual_blocked_by_claim_not_approved(api):
    """PRD §3.9: "The parent claim must be APPROVED (otherwise
    ERR_CLAIM_NOT_PAYABLE)."

    Design: Difficulty/cross_entity_state_dependency/benefit_accrual_blocked_by_claim_not_approved
    """
    book = setup_active_policy(clock_months=5)
    claim = file_claim(book["insurer"]["id"], book["policy"]["id"],
                       book["policyholder"]["id"], claimed_disability_type="TOTAL")
    get_success_data(api.submit_claim(claim["id"],
                                      make_policyholder_headers(book["policyholder"]["id"])))
    resp = api.create_benefit_period(claim["id"], {"coverage_month": 3}, ADJ)
    validate_error(resp, "ERR_CLAIM_NOT_PAYABLE")  # claim SUBMITTED, not APPROVED


# ─── Difficulty / priority_pair_validation_conflict ───

def test_payable_constraint_beats_fiscal_on_exhausted_claim(api):
    """PRD §3.9: "Accrual is gated by a sequence of checks. The parent claim must
    be APPROVED (otherwise ERR_CLAIM_NOT_PAYABLE)."
    PRD §3.9: "Finally, the accrual must not drive the policy's
    benefit_months_consumed beyond its benefit_period_months: a would-exceed
    accrual is rejected with ERR_BENEFIT_PERIOD_WOULD_EXCEED (a 422)".

    Design: Difficulty/priority_pair_validation_conflict/payable_constraint_vs_fiscal_on_accrual_constraint_wins
    """
    book = setup_approved_total_with_periods([3], clock_months=6,
                                             policy_overrides={"benefit_period_months": 1})
    cid = book["claim"]["id"]
    # First accrual consumed 1.0 == cap 1 -> claim auto-exhausted.
    exhausted = validate_success(api.get_claim(cid, ADJ), 200)
    assert exhausted["status"] == "BENEFIT_EXHAUSTED"
    # Second accrual violates both payable (not APPROVED) and would-exceed; the
    # claim-APPROVED gate, stated first in §3.9, wins.
    resp = api.create_benefit_period(cid, {"coverage_month": 4}, ADJ)
    validate_error(resp, "ERR_CLAIM_NOT_PAYABLE")


def test_offset_create_state_gate_beats_window_overlap(api):
    """PRD §3.11: "Creating an offset award requires the parent claim to be
    APPROVED; this parent-state gate is checked first, and a claim not in APPROVED
    is rejected with ERR_CLAIM_NOT_APPROVED. Only after that gate passes is the
    window checked for collision".

    Design: Difficulty/priority_pair_validation_conflict/state_vs_temporal_overlap_on_offset_create_state_wins
    """
    book = setup_approved_total_with_periods([], clock_months=5)
    cid = book["claim"]["id"]
    add_offset_award(cid, "SSDI", 120000, 3, 5)
    get_success_data(api.suspend_claim(cid, ADJ))  # claim now SUSPENDED, not APPROVED
    # New window [4,6] overlaps [3,5], but the state gate fires first.
    resp = api.create_offset_award(
        cid, {"offset_source": "SSDI", "monthly_offset_cents": 90000,
              "start_month": 4, "end_month": 6}, ADJ,
    )
    validate_error(resp, "ERR_CLAIM_NOT_APPROVED")


# ─── Difficulty / boundary_precision_check (elimination) ─

def test_elimination_satisfied_boundary_ge_on_approve(api):
    """PRD §3.6: "The insurer's current_month_index must have reached at least the
    claim's elimination_satisfied_month — that is, the current month index must be
    greater than or equal to the elimination satisfied month — or the approval is
    rejected with ERR_ELIMINATION_NOT_SATISFIED."

    Design: Difficulty/boundary_precision_check/elimination_satisfied_boundary_ge_on_approve
    """
    book = setup_under_review_claim(clock_months=2,
                                    policy_overrides={"elimination_period_days": 90})
    cid = book["claim"]["id"]
    ins_id = book["insurer"]["id"]
    # elim_sat = onset 0 + ceil(90/30) = 3 ; at month 2: 2 < 3 -> rejected.
    resp = api.approve_claim(cid, ADJ)
    validate_error(resp, "ERR_ELIMINATION_NOT_SATISFIED")
    # Advance to month 3 (boundary): 3 >= 3 -> approve succeeds.
    get_success_data(api.advance_clock(ins_id, {"by_months": 1}, TEST_USERS["system_operator_headers"]))
    approved = validate_success(api.approve_claim(cid, ADJ), 200)
    assert approved["status"] == "APPROVED"
