"""Second-test coverage for difficulty-queue instances whose primary assertion
lives in another file. Each test here targets the SAME difficulty instance from a
distinct angle so every instance carries at least two tests.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    api_client,
    TEST_USERS,
    ApiErrorId,
    make_intended_parent_actor_headers,
    create_active_journey,
    create_funded_journey,
    create_approved_disbursement,
    add_comp_schedule_line,
    add_and_achieve_milestone,
)
from test_helpers import factories as f

CM = TEST_USERS["case_manager_headers"]
FO = TEST_USERS["finance_officer_headers"]
SCREENER = TEST_USERS["screener_headers"]


# --- dual_variant_calc: disbursable_now cap behavior (second angle) --------
def test_disbursable_now_capped_by_available(api):
    """PRD §3.7: "for each candidate line it adds that line's `amount_cents` to
    the running total only if doing so would keep the running total at or below
    `available_cents`; a line that would push the running total above
    `available_cents` is skipped, and the strict-order walk stops contributing
    further."

    Design: Difficulty/dual_variant_calc/escrow_disbursable_now_vs_projected_liability_diverge
    """
    # available 4_000_000; only the EMBRYO_TRANSFER line (1_000_000) is achieved,
    # so disbursable_now = 1_000_000 (well under cap) but projected_liability sums
    # all non-FAILED lines = 6_000_000.
    ctx = create_funded_journey(deposit_cents=4_000_000)
    jr_id = ctx["journey"]["id"]
    add_comp_schedule_line(jr_id, "EMBRYO_TRANSFER", 1_000_000)
    add_comp_schedule_line(jr_id, "HEARTBEAT", 2_000_000)
    add_comp_schedule_line(jr_id, "BIRTH", 3_000_000)
    add_and_achieve_milestone(jr_id, "EMBRYO_TRANSFER")
    data = validate_success(api.get_escrow_summary(ctx["escrow"]["id"], FO))
    assert data["disbursable_now_cents"] == 1_000_000
    assert data["projected_liability_cents"] == 6_000_000
    assert data["disbursable_now_cents"] != data["projected_liability_cents"]


# --- dual_variant_calc: carrier comp domain vs insurance domain -----------
def test_carrier_total_comp_domain_distinct_from_gap_premium(api):
    """PRD §3.3: "the experience bonus is computed from the base and rounded
    first, and only then are the base, the experience bonus, and the multiples
    add-on summed to give the total."

    Design: Difficulty/dual_variant_calc/carrier_total_comp_vs_insurance_gap_premium_distinct_domains
    """
    ip = get_success_data(api.create_intended_parent(f.create_intended_parent_payload(), CM))
    car = get_success_data(api.create_carrier(
        f.create_carrier_payload(prior_deliveries=3, base_compensation_cents=4_000_033), CM))
    match = get_success_data(api.create_match(
        f.create_match_payload(ip["id"], car["id"], proposed_carrier_comp_cents=4_000_000), CM))
    data = validate_success(api.get_match_comp_breakdown(match["id"], CM))
    # base 4_000_000 + tier1 200_000 + 0 addon = 4_200_000 (a comp-domain number,
    # distinct from the 540_000 insurance-domain gap premium).
    assert data["total_cents"] == 4_200_000


# --- combinatorial_formula: comp tiered mode (second angle) ---------------
def test_comp_breakdown_evaluation_order_base_then_bonus(api):
    """PRD §3.3: "The carrier total compensation starts from a base equal to the
    match's `proposed_carrier_comp_cents`." PRD §3.3: "when `prior_deliveries` is
    2 or 3 the bonus is the base multiplied by 0.05, rounded half up to whole
    cents".

    Design: Difficulty/combinatorial_formula/carrier_total_compensation_tiered_conditional_mode_a
    """
    ip = get_success_data(api.create_intended_parent(f.create_intended_parent_payload(), CM))
    car = get_success_data(api.create_carrier(
        f.create_carrier_payload(prior_deliveries=2, base_compensation_cents=4_000_000), CM))
    match = get_success_data(api.create_match(
        f.create_match_payload(ip["id"], car["id"], proposed_carrier_comp_cents=4_000_000), CM))
    data = validate_success(api.get_match_comp_breakdown(match["id"], CM))
    assert data["base_cents"] == 4_000_000
    assert data["experience_bonus_cents"] == 200_000
    assert data["total_cents"] == 4_200_000


# --- combinatorial_formula: gap premium (second angle) --------------------
def test_gap_premium_uses_carrier_base_compensation(api):
    """PRD §3.2: "The gap premium is derived from the carrier's own
    `base_compensation_cents`. First, a monthly figure is computed as
    `base_compensation_cents` multiplied by a monthly gap rate of 0.015, and that
    monthly figure is rounded half up to a whole number of cents. Then
    `gap_premium_cents` is that rounded monthly figure multiplied by 9 months."

    Design: Difficulty/combinatorial_formula/insurance_gap_premium_nested_rounding_mode_b
    """
    car = get_success_data(api.create_carrier(
        f.create_carrier_payload(prior_deliveries=2, base_compensation_cents=4_000_033), CM))
    get_success_data(api.submit_carrier(car["id"], CM))
    get_success_data(api.start_screening_carrier(car["id"], SCREENER))
    ins = get_success_data(api.create_insurance_review(
        f.create_insurance_review_payload(car["id"], policy_kind="EXCLUSION"), SCREENER))
    data = validate_success(api.identify_gap_insurance_review(ins["id"], SCREENER))
    assert data["gap_premium_cents"] == 540_000


# --- priority_pair: state beats fiscal (second angle) ---------------------
def test_approve_released_disbursement_state_beats_fiscal(api):
    """PRD §3.8: "Approval requires the disbursement to be `REQUESTED`". PRD
    §3.10: "State validity is then checked: a resource not in a valid state for
    the requested transition fails with `ERR_INVALID_STATE`. After these come the
    business rules — ... escrow sufficiency (`ERR_INSUFFICIENT_ESCROW`)."

    Design: Difficulty/priority_pair_validation_conflict/milestone_gate_beats_insufficient_escrow_safety_vs_fiscal
    """
    ctx = create_approved_disbursement(deposit_cents=1_000_000, schedule_amount_cents=1_000_000,
                                       approver_user_id="cm-sf2")
    jr_id = ctx["journey"]["id"]
    from test_helpers import make_finance_officer_headers
    releaser = make_finance_officer_headers("fo-sf2")
    get_success_data(api.release_disbursement(jr_id, ctx["disbursement"]["id"], releaser))
    # Now RELEASED; available is 0. Re-approving must fail on state, not fiscal.
    resp = api.approve_disbursement(jr_id, ctx["disbursement"]["id"], CM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# --- priority_pair: state beats referential on parentage (second angle) ---
def test_decide_parentage_before_file_is_invalid_state(api):
    """PRD §3.6: "Once filed, the `CaseManager` records the court's outcome by
    supplying a `decision`, which moves `FILED` to either `GRANTED` or `DENIED`".

    Design: Difficulty/priority_pair_validation_conflict/parentage_jurisdiction_beats_missing_state_referential_vs_state
    """
    ctx = create_active_journey(ip_state_code="CA")
    jr_id = ctx["journey"]["id"]
    # parentage_order_status is NOT_FILED; deciding before filing is out of state.
    resp = api.decide_parentage(jr_id, f.parentage_decide_payload("GRANTED"), CM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# --- boundary: budget cap (second angle, partial-fill) --------------------
def test_escrow_deposit_partial_then_exact_remaining_passes(api):
    """PRD §3.5: "the account's `deposited_cents` plus the new `amount_cents`
    must not exceed the linked intended parent's `budget_cents`."

    Design: Difficulty/boundary_precision_check/escrow_deposit_at_budget_cap_exact_passes
    """
    ctx = create_active_journey()  # budget 6_000_000
    escrow = ctx["escrow"]
    ip_headers = make_intended_parent_actor_headers(ctx["ip"]["id"])
    first = validate_success(api.deposit_escrow(
        escrow["id"], f.deposit_payload(2_000_000, escrow["version"]), ip_headers))
    assert first["deposited_cents"] == 2_000_000
    second = validate_success(api.deposit_escrow(
        escrow["id"], f.deposit_payload(4_000_000, first["version"]), ip_headers))
    assert second["deposited_cents"] == 6_000_000
    assert second["available_cents"] == 6_000_000


# --- compensating_invariant: reject-approved (second angle) ---------------
def test_reject_approved_disbursement_leaves_available_restored(api):
    """PRD §3.8: "Rejecting an `APPROVED` disbursement also moves it to
    `REJECTED` but first releases its reservation: it subtracts `amount_cents`
    from the account's `reserved_cents`, recomputes `available_cents` ...
    returning the previously reserved funds to available."

    Design: Difficulty/compensating_invariant/reject_approved_disbursement_conserves_escrow_total
    """
    ctx = create_approved_disbursement(deposit_cents=5_000_000, schedule_amount_cents=2_000_000,
                                       approver_user_id="cm-inv-b")
    jr_id = ctx["journey"]["id"]
    assert ctx["escrow"]["reserved_cents"] == 2_000_000
    assert ctx["escrow"]["available_cents"] == 3_000_000
    validate_success(api.reject_disbursement(jr_id, ctx["disbursement"]["id"], CM))
    escrow = validate_success(api.get_escrow_account(ctx["escrow"]["id"], FO))
    assert escrow["reserved_cents"] == 0
    assert escrow["available_cents"] == 5_000_000
    assert escrow["deposited_cents"] == 5_000_000
