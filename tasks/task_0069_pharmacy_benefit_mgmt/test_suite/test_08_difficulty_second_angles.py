"""Second-angle coverage for difficulty-design instances: boundary neighbours and
complementary assertions on the same rule (PRD §3.3-§3.7). Each test re-exercises a
distinct observable consequence of its design instance's rule.
"""
from test_helpers import fixtures as fx, validate_error, ApiErrorId
from test_helpers.api_client import api_client
from test_helpers import make_director_headers


# ─── mail_order_copay_single_rounded_product (2nd) ──────────────────────────
def test_mail_order_copay_multiplier_two_and_a_half_rounds_half_up(api):
    """PRD §2.5: "In both cases the result is rounded to a whole number of cents using
    the round-half-up method (a value with a fractional part of exactly one half rounds
    up to the next cent)."
    PRD §3.5: "the copay is that base copay multiplied by the plan's
    `mail_order_copay_multiplier`, rounded half-up to a whole cent"

    Design: Difficulty/combinatorial_formula/mail_order_copay_single_rounded_product_not_summed_fills
    """
    fx.set_clock("2026-04-02T00:00:00.000Z")
    # base TIER_1 copay 1001 * 2.5 = 2502.5 -> round_half_up -> 2503.
    plan = fx.create_plan(deductible_cents=0, oop_max_cents=200000,
                          mail_order_copay_multiplier=2.5,
                          tier_copay_cents={"TIER_1": 1001, "TIER_2": 3500,
                                            "TIER_3": 7000, "SPECIALTY": 25000})
    drug = fx.create_drug(plan["id"], ndc="MD", drug_name="Mail", tier="TIER_1",
                          ingredient_cost_cents=10000)
    m = fx.create_member(plan["id"])
    claim = fx.submit_claim(m["id"], drug["id"], days_supply=90, pharmacy_type="MAIL_ORDER")
    assert claim["adjudication_status"] == "PAID"
    assert claim["member_pay_cents"] == 2503, claim["member_pay_cents"]


# ─── claim_parallel_adjudication_and_rebate_dimensions (2nd) ────────────────
def test_paid_claim_starts_in_accrued_rebate_dimension(api):
    """PRD §3.4: "Every claim begins in `SUBMITTED` and its independent rebate dimension begins at `NONE`."
    PRD §3.7: "A new accrual is created in `PROVISIONAL` status with `clawback_cents` of 0, and the originating claim's independent `rebate_status` dimension is set to `ACCRUED`."

    Design: Difficulty/non_linear_state_machine/claim_parallel_adjudication_and_rebate_dimensions
    """
    fx.set_clock("2026-05-02T00:00:00.000Z")
    plan = fx.create_plan(deductible_cents=0, oop_max_cents=200000)
    fx.create_rebate_agreement(plan["id"], clawback_pct=1.0)
    drug = fx.create_drug(plan["id"], ndc="RB", drug_name="RB", tier="TIER_1",
                          ingredient_cost_cents=10000, rebate_per_fill_cents=4000)
    m = fx.create_member(plan["id"])
    claim = fx.submit_claim(m["id"], drug["id"], days_supply=30, pharmacy_type="RETAIL")
    assert claim["adjudication_status"] == "PAID"
    assert claim["rebate_status"] == "ACCRUED", claim["rebate_status"]


# ─── claim_paid_consumes_pa_last_fill_auto_expires (2nd) ────────────────────
def test_pa_with_two_fills_stays_approved_after_one_claim(api):
    """PRD §3.4: "that authorization's `approved_quantity_remaining` is decremented by one; should the remaining count reach zero, the authorization auto-transitions from `APPROVED` to `EXPIRED` and its version increments."

    Design: Difficulty/transitive_cascade/claim_paid_consumes_pa_last_fill_auto_expires
    """
    fx.set_clock("2026-06-02T00:00:00.000Z")
    plan = fx.create_plan(deductible_cents=0, oop_max_cents=200000)
    drug = fx.create_drug(plan["id"], ndc="PA2", drug_name="PA Drug2", tier="TIER_2",
                          ingredient_cost_cents=30000, pa_required=True)
    m = fx.create_member(plan["id"])
    pa = fx.submit_and_approve_pa(m["id"], drug["id"], submitter_id="U_REV", decider_id="U_DIR",
                                  authorized_fills=2)
    claim = fx.submit_claim(m["id"], drug["id"], days_supply=30, pharmacy_type="RETAIL",
                            prior_auth_id=pa["id"])
    assert claim["adjudication_status"] == "PAID"
    pa_after = fx.get_pa(pa["id"])
    # remaining 1 (not 0) -> stays APPROVED, no auto-expire.
    assert pa_after["approved_quantity_remaining"] == 1, pa_after["approved_quantity_remaining"]
    assert pa_after["status"] == "APPROVED", pa_after["status"]


# ─── claim_reverse_unwinds_copay_card_to_active (2nd) ───────────────────────
def test_copay_card_exhausted_before_reversal(api):
    """PRD §3.5: "On payment, if the claim drew on a copay card, that card's `benefit_used_cents` is recomputed; when it equals the card's `max_benefit_cents` the card's `status` becomes `EXHAUSTED`."

    Design: Difficulty/transitive_cascade/claim_reverse_unwinds_copay_card_to_active
    """
    fx.set_clock("2026-07-02T00:00:00.000Z")
    plan = fx.create_plan(deductible_cents=0, oop_max_cents=200000)
    drug = fx.create_drug(plan["id"], ndc="SP", drug_name="Spec", tier="SPECIALTY",
                          ingredient_cost_cents=200000, is_specialty=True)
    m = fx.create_member(plan["id"])
    card = fx.create_copay_card(m["id"], drug["id"], max_benefit_cents=20000)
    claim = fx.submit_claim(m["id"], drug["id"], days_supply=30, pharmacy_type="SPECIALTY",
                            copay_card_id=card["id"])
    assert claim["adjudication_status"] == "PAID"
    card_mid = fx.get_copay_card(card["id"])
    assert card_mid["benefit_used_cents"] == 20000, card_mid["benefit_used_cents"]
    assert card_mid["status"] == "EXHAUSTED", card_mid["status"]


# ─── segregation_beats_stale_version_on_pa_decide (2nd) ─────────────────────
def test_self_decision_rejected_even_with_correct_version(api):
    """PRD §3.3: "the deciding director's `X-User-ID` must differ from the
    authorization's recorded `submitted_by_user_id` — a reviewer may not have their own
    submission approved by themselves wearing a different hat."
    PRD §3.3: "When the deciding user equals the submitter, the request is rejected with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Difficulty/priority_pair_validation_conflict/segregation_beats_stale_version_on_pa_decide
    """
    plan = fx.create_plan(deductible_cents=0, oop_max_cents=200000)
    drug = fx.create_drug(plan["id"], ndc="X", drug_name="X", tier="TIER_2",
                          ingredient_cost_cents=30000, pa_required=True)
    m = fx.create_member(plan["id"])
    pa = fx.submit_pa(m["id"], drug["id"], submitter_id="U_SELF", authorized_fills=1)
    # Correct version this time; segregation still rejects.
    resp = api_client.decide_prior_authorization(
        pa["id"],
        {"decision": "APPROVE", "expected_prior_authorization_version": pa["version"]},
        make_director_headers("U_SELF"),
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


# ─── inactive_resource_beats_pa_required_on_claim (2nd) ─────────────────────
def test_inactive_drug_beats_pa_required(api):
    """PRD §3.4: "a claim touching a terminated member, an inactive drug, or an archived plan is rejected with `ERR_INACTIVE_RESOURCE`."
    PRD §2.7: "earlier, structural problems mask later, business-specific ones."

    Design: Difficulty/priority_pair_validation_conflict/inactive_resource_beats_pa_required_on_claim
    """
    fx.set_clock("2026-08-02T00:00:00.000Z")
    plan = fx.create_plan(deductible_cents=0, oop_max_cents=200000)
    drug = fx.create_drug(plan["id"], ndc="PAX", drug_name="PA X", tier="TIER_2",
                          ingredient_cost_cents=30000, pa_required=True)
    m = fx.create_member(plan["id"])
    fx.delist_drug(drug["id"])  # drug INACTIVE
    resp = api_client.create_claim(
        {"member_id": m["id"], "formulary_drug_id": drug["id"], "days_supply": 30,
         "pharmacy_type": "RETAIL"},
        fx.PROVIDER,
    )
    validate_error(resp, ApiErrorId.ERR_INACTIVE_RESOURCE.value)


# ─── oop_max_clamp_exact_remaining (2nd) ────────────────────────────────────
def test_oop_clamp_when_already_at_max_member_pays_zero(api):
    """PRD §3.5: "`member_pay_cents` is the smaller of the uncapped responsibility and
    the member's remaining out-of-pocket room."
    PRD §3.5: "the member's remaining out-of-pocket room — the plan's `oop_max_cents`
    minus the member's current `oop_met_cents`, floored at zero"

    Design: Difficulty/boundary_precision_check/oop_max_clamp_exact_remaining
    """
    fx.set_clock("2026-09-02T00:00:00.000Z")
    # oop_max small so the first claim alone reaches it; the second clamps to 0.
    plan = fx.create_plan(deductible_cents=0, oop_max_cents=25000)
    drug = fx.create_drug(plan["id"], ndc="SPEC", drug_name="Spec", tier="SPECIALTY",
                          ingredient_cost_cents=200000, is_specialty=True)
    other = fx.create_drug(plan["id"], ndc="SPEC2", drug_name="Spec2", tier="SPECIALTY",
                           ingredient_cost_cents=200000, is_specialty=True)
    m = fx.create_member(plan["id"])
    first = fx.submit_claim(m["id"], drug["id"], days_supply=30, pharmacy_type="SPECIALTY")
    assert first["member_pay_cents"] == 25000, first["member_pay_cents"]
    member_mid = fx.get_member(m["id"])
    assert member_mid["oop_met_cents"] == 25000
    second = fx.submit_claim(m["id"], other["id"], days_supply=30, pharmacy_type="SPECIALTY")
    # remaining oop room = 0 -> member_pay clamped to 0.
    assert second["member_pay_cents"] == 0, second["member_pay_cents"]


# ─── copay_card_exhausted_zero_remaining_draw (2nd) ─────────────────────────
def test_copay_card_partial_remaining_draws_only_remaining(api):
    """PRD §3.5: "the card's remaining benefit is its `max_benefit_cents` minus its current `benefit_used_cents`, and `copay_card_paid_cents` is the smaller of the claim's `member_pay_cents` and that remaining benefit."

    Design: Difficulty/boundary_precision_check/copay_card_exhausted_zero_remaining_draw
    """
    fx.set_clock("2026-10-02T00:00:00.000Z")
    plan = fx.create_plan(deductible_cents=0, oop_max_cents=500000)
    drug = fx.create_drug(plan["id"], ndc="SP", drug_name="Spec", tier="SPECIALTY",
                          ingredient_cost_cents=200000, is_specialty=True)
    m = fx.create_member(plan["id"])
    # member_pay is the SPECIALTY copay 25000; card remaining 20000 -> draws 20000 exactly.
    card = fx.create_copay_card(m["id"], drug["id"], max_benefit_cents=20000)
    claim = fx.submit_claim(m["id"], drug["id"], days_supply=30, pharmacy_type="SPECIALTY",
                            copay_card_id=card["id"])
    assert claim["member_pay_cents"] == 25000, claim["member_pay_cents"]
    assert claim["copay_card_paid_cents"] == 20000, claim["copay_card_paid_cents"]


# ─── claim_requires_pa_approved_state (2nd) ─────────────────────────────────
def test_claim_pays_once_pa_approved(api):
    """PRD §3.4: "the claim's `prior_auth_id` must reference an `APPROVED` authorization for the very same member and drug with `approved_quantity_remaining` of at least 1"

    Design: Difficulty/cross_entity_state_dependency/claim_requires_pa_approved_state
    """
    fx.set_clock("2026-11-02T00:00:00.000Z")
    plan = fx.create_plan(deductible_cents=0, oop_max_cents=200000)
    drug = fx.create_drug(plan["id"], ndc="PA", drug_name="PA", tier="TIER_2",
                          ingredient_cost_cents=30000, pa_required=True)
    m = fx.create_member(plan["id"])
    pa = fx.submit_and_approve_pa(m["id"], drug["id"], submitter_id="U_REV", decider_id="U_DIR",
                                  authorized_fills=1)
    claim = fx.submit_claim(m["id"], drug["id"], days_supply=30, pharmacy_type="RETAIL",
                            prior_auth_id=pa["id"])
    assert claim["adjudication_status"] == "PAID", claim["adjudication_status"]


# ─── claim_requires_plan_active_state (2nd) ─────────────────────────────────
def test_claim_rejected_when_member_terminated(api):
    """PRD §3.4: "the member must be `ACTIVE`, the drug must be `ACTIVE`, and the plan must be `ACTIVE`; a claim touching a terminated member, an inactive drug, or an archived plan is rejected with `ERR_INACTIVE_RESOURCE`."

    Design: Difficulty/cross_entity_state_dependency/claim_requires_plan_active_state
    """
    fx.set_clock("2026-11-16T00:00:00.000Z")
    plan = fx.create_plan(deductible_cents=0, oop_max_cents=200000)
    drug = fx.create_drug(plan["id"], ndc="Y", drug_name="Y", tier="TIER_1",
                          ingredient_cost_cents=10000)
    m = fx.create_member(plan["id"])
    fx.terminate_member(m["id"])
    resp = api_client.create_claim(
        {"member_id": m["id"], "formulary_drug_id": drug["id"], "days_supply": 30,
         "pharmacy_type": "RETAIL"},
        fx.PROVIDER,
    )
    validate_error(resp, ApiErrorId.ERR_INACTIVE_RESOURCE.value)


# ─── refill_too_soon_supply_window_overlap (2nd) ────────────────────────────
def test_refill_after_window_ends_allowed(api):
    """PRD §3.4: "a new fill whose `fill_date` lands strictly inside an existing window is an overlap and is rejected with `ERR_REFILL_TOO_SOON`, while a new fill stamped exactly at a prior window's `supply_end_date` is adjacent (not overlapping) and is allowed."

    Design: Difficulty/resource_temporal_overlap/refill_too_soon_supply_window_overlap
    """
    fx.set_clock("2026-01-01T00:00:00.000Z")
    plan = fx.create_plan(deductible_cents=0, oop_max_cents=200000)
    drug = fx.create_drug(plan["id"], ndc="Z", drug_name="Z", tier="TIER_1",
                          ingredient_cost_cents=10000)
    m = fx.create_member(plan["id"])
    fx.submit_claim(m["id"], drug["id"], days_supply=30, pharmacy_type="RETAIL")
    fx.set_clock("2026-02-15T00:00:00.000Z")  # well past 2026-01-31 window end
    claim = fx.submit_claim(m["id"], drug["id"], days_supply=30, pharmacy_type="RETAIL")
    assert claim["adjudication_status"] == "PAID", claim["adjudication_status"]


# ─── pa_validity_window_exclusive_upper_bound (2nd) ─────────────────────────
def test_pa_fill_strictly_before_valid_through_allowed(api):
    """PRD §3.4: "the claim's `fill_date` must fall strictly before the authorization's
    `valid_through_date`. The window is half-open — open at the decided instant and
    exclusive at the upper bound"

    Design: Difficulty/resource_temporal_overlap/pa_validity_window_exclusive_upper_bound
    """
    fx.set_clock("2026-02-01T00:00:00.000Z")
    plan = fx.create_plan(deductible_cents=0, oop_max_cents=200000)
    drug = fx.create_drug(plan["id"], ndc="PAW", drug_name="PA W", tier="TIER_2",
                          ingredient_cost_cents=30000, pa_required=True)
    m = fx.create_member(plan["id"])
    pa = fx.submit_and_approve_pa(m["id"], drug["id"], submitter_id="U_REV", decider_id="U_DIR",
                                  authorized_fills=1, valid_through_date="2026-03-01T00:00:00.000Z")
    fx.set_clock("2026-02-28T00:00:00.000Z")  # strictly before upper bound
    claim = fx.submit_claim(m["id"], drug["id"], days_supply=30, pharmacy_type="RETAIL",
                            prior_auth_id=pa["id"])
    assert claim["adjudication_status"] == "PAID", claim["adjudication_status"]


# ─── reverse_restores_member_accumulators_to_zero (2nd) ─────────────────────
def test_reverse_restores_oop_accumulator_to_zero(api):
    """PRD §3.7: "The member's `deductible_met_cents` and `oop_met_cents` are recomputed with this claim excluded (per the chronological reconciliation of §3.6)."

    Design: Difficulty/compensating_invariant/reverse_restores_member_accumulators_to_zero
    """
    fx.set_clock("2026-04-16T00:00:00.000Z")
    plan = fx.create_plan(deductible_cents=0, oop_max_cents=200000)
    drug = fx.create_drug(plan["id"], ndc="T3", drug_name="T3", tier="TIER_3",
                          ingredient_cost_cents=7000)
    m = fx.create_member(plan["id"])
    claim = fx.submit_claim(m["id"], drug["id"], days_supply=30, pharmacy_type="RETAIL")
    assert claim["adjudication_status"] == "PAID"
    member_mid = fx.get_member(m["id"])
    assert member_mid["oop_met_cents"] == 7000  # copay 7000, deductible 0
    fx.reverse_claim(claim["id"])
    member = fx.get_member(m["id"])
    assert member["oop_met_cents"] == 0, member["oop_met_cents"]
    assert member["deductible_met_cents"] == 0, member["deductible_met_cents"]


# ─── reverse_restores_copay_card_benefit_and_pa_fill (2nd) ──────────────────
def test_reverse_restores_pa_fill_count(api):
    """PRD §3.7: "If the claim consumed a prior authorization that has not been expired and consumed elsewhere, the authorization's `approved_quantity_remaining` is incremented by one to restore the consumed fill."

    Design: Difficulty/compensating_invariant/reverse_restores_copay_card_benefit_and_pa_fill
    """
    fx.set_clock("2026-05-16T00:00:00.000Z")
    plan = fx.create_plan(deductible_cents=0, oop_max_cents=500000)
    drug = fx.create_drug(plan["id"], ndc="PAR", drug_name="PA R", tier="TIER_2",
                          ingredient_cost_cents=30000, pa_required=True)
    m = fx.create_member(plan["id"])
    pa = fx.submit_and_approve_pa(m["id"], drug["id"], submitter_id="U_REV", decider_id="U_DIR",
                                  authorized_fills=3)
    claim = fx.submit_claim(m["id"], drug["id"], days_supply=30, pharmacy_type="RETAIL",
                            prior_auth_id=pa["id"])
    assert claim["adjudication_status"] == "PAID"
    pa_mid = fx.get_pa(pa["id"])
    assert pa_mid["approved_quantity_remaining"] == 2
    fx.reverse_claim(claim["id"])
    pa_after = fx.get_pa(pa["id"])
    assert pa_after["approved_quantity_remaining"] == 3, pa_after["approved_quantity_remaining"]
