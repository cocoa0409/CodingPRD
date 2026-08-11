"""Service plan fee variants (risk adders, waiver discount, rounding order)
and warranty-claim coverage invariants."""
import pytest

from test_helpers import (
    api_client, TEST_USERS,
    validate_success, validate_error,
    ApiErrorId,
    MODEL_CURVED, MODEL_CURVED_OUTDOOR, MEASURE_CURVED, MEASURE_CURVED_OUTDOOR,
    MODEL_STRAIGHT,
    assert_service_plan, assert_service_plan_cap_invariants,
    set_clock, create_catalog_model, setup_approved_assessment, create_agreement,
    setup_active_agreement, setup_active_agreement_with_refurb_unit,
    setup_active_purchase_past_cooling_off,
    attach_service_plan, file_claim, review_claim, adjudicate_claim,
    get_service_plan, get_warranty_claim, schedule_removal, fresh_crew,
    create_removal_job_payload,
)

COORD = TEST_USERS["install_coordinator_headers"]
CLAIMS = TEST_USERS["claims_adjuster_headers"]


# ---------------------------------------------------------------------------
# Fee divergence: waiver-discounted vs standard variant (all three adders)
# ---------------------------------------------------------------------------

def test_service_plan_fee_waiver_variant_with_all_risk_adders(api):
    """PRD §3.5: "The `monthly_fee_cents` starts from the tier base fee — 2,900
    cents for `BASIC`, 4,900 for `STANDARD`, 7,900 for `PREMIUM` — then adds
    risk adders as additive percentages of that base: 15% when the assessment
    recorded `has_outdoor_exposure`, 20% when the staircase is `CURVED`, and
    10% when the installed unit's `condition_grade` is `REFURB_B` or
    `REFURB_C`."
    PRD §3.5: "When the agreement's `liability_waiver_signed` is true, a
    waiver-discounted variant applies instead: the fee after risk adders is
    multiplied by 0.85 — a 15% discount applied strictly after the adders —
    and then rounded half-up."
    PRD §3.5: "The `coverage_cap_cents` is the tier's lifetime repair cap:
    50,000 cents for `BASIC`, 150,000 for `STANDARD`, and 400,000 for
    `PREMIUM`."

    Design: Difficulty/dual_variant_calc/service_plan_fee_waiver_vs_standard_divergence
    """
    bag = setup_active_agreement_with_refurb_unit(
        model_dict=MODEL_CURVED_OUTDOOR, measure_dict=MEASURE_CURVED_OUTDOOR,
        waiver=True)
    res = api.create_service_plan(bag["agreement"]["id"], {"tier": "PREMIUM"}, COORD)
    plan = validate_success(res, 201)
    assert_service_plan(plan)
    # PREMIUM base 7900, adders 0.15+0.20+0.10 -> 7900*1.45 = 11455,
    # waiver variant -> round_half_up(11455 * 0.85) = 9737.
    assert plan["monthly_fee_cents"] == 9737
    assert plan["coverage_cap_cents"] == 400000
    assert_service_plan_cap_invariants(plan)


def test_service_plan_fee_standard_variant_with_all_risk_adders(api):
    """PRD §3.5: "The `monthly_fee_cents` starts from the tier base fee — 2,900
    cents for `BASIC`, 4,900 for `STANDARD`, 7,900 for `PREMIUM` — then adds
    risk adders as additive percentages of that base: 15% when the assessment
    recorded `has_outdoor_exposure`, 20% when the staircase is `CURVED`, and
    10% when the installed unit's `condition_grade` is `REFURB_B` or
    `REFURB_C`. The result is rounded half-up to a whole cent."

    Design: Difficulty/dual_variant_calc/service_plan_fee_waiver_vs_standard_divergence
    """
    bag = setup_active_agreement_with_refurb_unit(
        model_dict=MODEL_CURVED_OUTDOOR, measure_dict=MEASURE_CURVED_OUTDOOR,
        waiver=False)
    res = api.create_service_plan(bag["agreement"]["id"], {"tier": "PREMIUM"}, COORD)
    plan = validate_success(res, 201)
    # Same risk inputs without the waiver: 7900 * 1.45 = 11455 exactly.
    assert plan["monthly_fee_cents"] == 11455
    assert plan["coverage_cap_cents"] == 400000


# ---------------------------------------------------------------------------
# Nested rounding order: adders first, discount after, final round
# ---------------------------------------------------------------------------

def test_service_plan_fee_no_waiver_rounding(api):
    """PRD §3.5: "The `monthly_fee_cents` starts from the tier base fee — 2,900
    cents for `BASIC`, 4,900 for `STANDARD`, 7,900 for `PREMIUM` — then adds
    risk adders as additive percentages of that base: 15% when the assessment
    recorded `has_outdoor_exposure`, 20% when the staircase is `CURVED`, and
    10% when the installed unit's `condition_grade` is `REFURB_B` or
    `REFURB_C`. The result is rounded half-up to a whole cent."
    PRD §3.5: "The `coverage_cap_cents` is the tier's lifetime repair cap:
    50,000 cents for `BASIC`, 150,000 for `STANDARD`, and 400,000 for
    `PREMIUM`."

    Design: Difficulty/combinatorial_formula/service_plan_fee_nested_rounding_order
    """
    bag = setup_active_agreement_with_refurb_unit(
        model_dict=MODEL_CURVED, measure_dict=MEASURE_CURVED, waiver=False)
    res = api.create_service_plan(bag["agreement"]["id"], {"tier": "STANDARD"}, COORD)
    plan = validate_success(res, 201)
    # STANDARD base 4900, adders 0.20 (curved) + 0.10 (REFURB_B) -> 4900*1.30.
    assert plan["monthly_fee_cents"] == 6370
    assert plan["coverage_cap_cents"] == 150000


def test_service_plan_fee_waiver_discount_applied_after_adders(api):
    """PRD §3.5: "When the agreement's `liability_waiver_signed` is true, a
    waiver-discounted variant applies instead: the fee after risk adders is
    multiplied by 0.85 — a 15% discount applied strictly after the adders —
    and then rounded half-up."
    PRD §2.5: "Wherever a calculation produces a fractional cent, the platform
    rounds half-up to the nearest whole cent at the step the rule specifies"

    Design: Difficulty/combinatorial_formula/service_plan_fee_nested_rounding_order
    """
    bag = setup_active_agreement_with_refurb_unit(
        model_dict=MODEL_CURVED, measure_dict=MEASURE_CURVED, waiver=True)
    res = api.create_service_plan(bag["agreement"]["id"], {"tier": "STANDARD"}, COORD)
    plan = validate_success(res, 201)
    # 4900*1.30 = 6370 after adders; waiver discount: round_half_up(6370*0.85)
    # = round_half_up(5414.5) = 5415.
    assert plan["monthly_fee_cents"] == 5415
    assert plan["coverage_cap_cents"] == 150000


# ---------------------------------------------------------------------------
# Waiver blocks WEAR_AND_TEAR claims
# ---------------------------------------------------------------------------

def test_error_waiver_blocks_wear_and_tear_claim(api):
    """PRD §3.6: "Approval is gated by four fiscal checks: ... if the
    agreement's `liability_waiver_signed` is true and the claim is
    `WEAR_AND_TEAR`, the waiver blocks it with `ERR_WAIVER_BLOCKS_CLAIM`
    (422)"

    Design: Corner/errors/error_waiver_blocks_wear_and_tear_claim
    """
    bag = setup_active_agreement(model_dict=MODEL_STRAIGHT, waiver=True,
                                 tier="PREMIUM")
    claim = file_claim(bag["agreement"]["id"], bag["service_plan"]["id"],
                       claim_kind="WEAR_AND_TEAR", claimed_cents=5000)
    review_claim(claim["id"])
    res = api.adjudicate_warranty_claim(
        claim["id"], {"decision": "APPROVED", "approved_cents": 5000}, CLAIMS)
    validate_error(res, ApiErrorId.ERR_WAIVER_BLOCKS_CLAIM)


# ---------------------------------------------------------------------------
# Coverage cap conservation across pay and removal-denial
# ---------------------------------------------------------------------------

def test_pay_approved_claim_debits_coverage_used(api):
    """PRD §3.6: "Payment then moves an `APPROVED` claim to `PAID`, adds the
    `approved_cents` into the plan's `coverage_used_cents` — the compensating
    invariant that keeps the cap honest — and appends an audit event."
    PRD §3.6: "An approved claim sets its `approved_cents` to the smaller of
    `claimed_cents` and the plan's remaining headroom (`coverage_cap_cents`
    minus `coverage_used_cents`)."

    Design: Difficulty/compensating_invariant/warranty_claim_pay_conserves_coverage_cap
    """
    bag = setup_active_agreement(model_dict=MODEL_STRAIGHT, tier="STANDARD")
    plan = bag["service_plan"]
    assert plan["coverage_used_cents"] == 0

    claim = file_claim(bag["agreement"]["id"], plan["id"], "MECHANICAL", 5000)
    review_claim(claim["id"])
    adjudicate_claim(claim["id"], "APPROVED", approved_cents=5000)
    paid = validate_success(api.pay_warranty_claim(claim["id"], CLAIMS), 200)
    assert paid["status"] == "PAID"

    plan_after = get_service_plan(plan["id"])
    assert plan_after["coverage_used_cents"] == 5000
    assert_service_plan_cap_invariants(plan_after)


def test_removal_denies_approved_unpaid_claim_without_debiting_cap(api):
    """PRD §3.7: "every warranty claim still in `SUBMITTED`, `UNDER_REVIEW`, or
    `APPROVED` is forcibly moved to `DENIED` with its `denial_reason` set to
    `AGREEMENT_REMOVED` — a compensating reversal even for claims already
    approved but not yet paid."
    PRD §3.6: "Payment then moves an `APPROVED` claim to `PAID`, adds the
    `approved_cents` into the plan's `coverage_used_cents` — the compensating
    invariant that keeps the cap honest — and appends an audit event."

    Design: Difficulty/compensating_invariant/warranty_claim_pay_conserves_coverage_cap
    """
    bag = setup_active_purchase_past_cooling_off(tier="STANDARD", region="WEST")
    plan = bag["service_plan"]
    claim = file_claim(bag["agreement"]["id"], plan["id"], "MECHANICAL", 5000)
    review_claim(claim["id"])
    adjudicate_claim(claim["id"], "APPROVED", approved_cents=5000)

    removal = schedule_removal(bag["agreement"]["id"], crew=fresh_crew("CREW-W"))
    validate_success(
        api.complete_removal_job(removal["id"],
                                 {"condition_grade_at_removal": "REFURB_B"},
                                 COORD), 200)

    claim_after = get_warranty_claim(claim["id"])
    assert claim_after["status"] == "DENIED"
    assert claim_after["denial_reason"] == "AGREEMENT_REMOVED"
    plan_after = get_service_plan(plan["id"])
    # The claim never reached PAID, so no debit ever landed on the cap.
    assert plan_after["coverage_used_cents"] == 0
    assert plan_after["status"] == "CANCELLED"
