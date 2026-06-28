"""Pricing engine: per-item premium, policy aggregation rounding order, deductible
resolution, and the immediate-consistency of bind.

Design queue A: combinatorial_formula.
Design queue B: entities (computed deductible), endpoints/consistency model.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    assert_policy,
    create_policyholder_payload,
    create_risk_zone_payload,
    create_appraisal_payload,
    create_policy_payload,
    create_scheduled_item_payload,
    TEST_USERS,
    set_clock,
    create_risk_zone,
    create_policyholder,
    create_policy,
    create_scheduled_item,
    create_appraisal,
    setup_quoted_policy_with_item,
)

_UW = TEST_USERS["underwriter_headers"]
_AP = TEST_USERS["appraiser_headers"]


# ─────────────────────────────────────────────────────────────────────────
# Queue A: combinatorial_formula
# ─────────────────────────────────────────────────────────────────────────

def test_watch_premium_tiered_multifactor_chain(api):
    """PRD §3.4: "Begin with a base figure: divide the item's current_value_cents by one
    hundred thousand to obtain the insured value expressed in thousands of dollars, then
    multiply by the rate_per_thousand_cents of the risk zone whose zip_prefix equals the
    first three digits of the item's location_zip; if no risk zone matches that prefix, the
    moderate default band rate is used."
    PRD §3.4: "Multiply again by the coverage multiplier: an ALL_RISK policy applies a
    factor of 1.30, while a NAMED_PERIL policy applies 1.00."
    PRD §3.4: "an item above twenty thousand dollars takes 1.25."
    PRD §3.4: "STANDARD carries 0.92"
    PRD §3.4: "Only then, after the rounding and the floor, add the flat catastrophe
    surcharge: if the item's matched risk zone has catastrophe_loaded true, add fifteen
    hundred cents (fifteen dollars); otherwise add nothing."

    Design: Difficulty/combinatorial_formula/premium_tiered_multifactor_single_item
    """
    set_clock()
    create_risk_zone(zip_prefix="200", risk_band="HIGH",
                     rate_per_thousand_cents=200, catastrophe_loaded=True)
    ph = create_policyholder(email="w@x.com", residence_zip="20001")
    appraisal = create_appraisal(ph["id"], appraised_value_cents=3000000,
                                 effective_date_iso="2026-01-15T00:00:00Z")
    policy = create_policy(ph["id"], coverage_type="ALL_RISK",
                           valuation_basis="AGREED_VALUE", deductible_option="STANDARD")
    item = create_scheduled_item(policy["id"], description="Lux watch", category="WATCH",
                                 location_zip="20001", scheduled_value_cents=3000000,
                                 appraisal_id=appraisal["id"])

    bound = validate_success(api.bind_policy(policy["id"], _UW), 200)
    assert bound["annual_premium_cents"] == 12264, (
        f"expected 12264, got {bound['annual_premium_cents']}"
    )
    assert bound["total_insured_value_cents"] == 3000000

    item_after = validate_success(api.get_scheduled_item(item["id"], _UW), 200)
    assert item_after["current_value_cents"] == 3000000


def test_policy_premium_round_per_item_then_sum(api):
    """PRD §3.4: "The policy's annual_premium_cents aggregates these per-item figures under
    a rounding order that is pinned and must not be reordered. Each item premium is rounded
    to whole cents first, inside the per-item computation above, and only the already-rounded
    per-item figures are summed — this is round-then-sum, explicitly not
    sum-the-raw-figures-then-round."

    Design: Difficulty/combinatorial_formula/premium_round_per_item_then_sum
    """
    set_clock()
    create_risk_zone(zip_prefix="300", risk_band="MODERATE", rate_per_thousand_cents=173)
    create_risk_zone(zip_prefix="301", risk_band="MODERATE", rate_per_thousand_cents=167)
    ph = create_policyholder(email="r@x.com", residence_zip="30001")
    # PRD §3.3: an item whose scheduled_value_cents exceeds ten thousand dollars
    # ($1,000,000c) must carry a valid appraisal at bind. Watch B at 1,030,000c
    # is above threshold and so requires one; Watch A at exactly 1,000,000c does not.
    appraisal_b = create_appraisal(ph["id"], appraised_value_cents=1030000,
                                   effective_date_iso="2026-01-01T00:00:00Z")
    policy = create_policy(ph["id"], coverage_type="ALL_RISK",
                           valuation_basis="AGREED_VALUE", deductible_option="LOW")
    create_scheduled_item(policy["id"], description="Watch A", category="WATCH",
                          location_zip="30001", scheduled_value_cents=1000000)
    create_scheduled_item(policy["id"], description="Watch B", category="WATCH",
                          location_zip="30101", scheduled_value_cents=1030000,
                          appraisal_id=appraisal_b["id"])

    bound = validate_success(api.bind_policy(policy["id"], _UW), 200)
    assert bound["annual_premium_cents"] == 5921, (
        f"round-then-sum should yield 5921 (sum-then-round would give 5920), "
        f"got {bound['annual_premium_cents']}"
    )
    assert bound["total_insured_value_cents"] == 2030000


def test_combinatorial_premium_persisted_on_policy_read(api):
    """PRD §3.4: "an item above twenty thousand dollars takes 1.25." (the value-tier
    multiplier that pins the WATCH premium to 12264 once base, category, coverage,
    deductible-credit and the flat catastrophe surcharge are applied).
    PRD §3.4: "Only then, after the rounding and the floor, add the flat catastrophe
    surcharge: if the item's matched risk zone has catastrophe_loaded true, add fifteen
    hundred cents (fifteen dollars); otherwise add nothing."

    Design: Difficulty/combinatorial_formula/premium_tiered_multifactor_single_item
    """
    set_clock()
    create_risk_zone(zip_prefix="200", risk_band="HIGH",
                     rate_per_thousand_cents=200, catastrophe_loaded=True)
    ph = create_policyholder(email="w2@x.com", residence_zip="20001")
    appraisal = create_appraisal(ph["id"], appraised_value_cents=3000000,
                                 effective_date_iso="2026-01-15T00:00:00Z")
    policy = create_policy(ph["id"], coverage_type="ALL_RISK",
                           valuation_basis="AGREED_VALUE", deductible_option="STANDARD")
    create_scheduled_item(policy["id"], description="Lux watch", category="WATCH",
                          location_zip="20001", scheduled_value_cents=3000000,
                          appraisal_id=appraisal["id"])
    validate_success(api.bind_policy(policy["id"], _UW), 200)

    reread = validate_success(api.get_policy(policy["id"], _UW), 200)
    assert reread["annual_premium_cents"] == 12264


def test_two_item_aggregate_premium_persisted(api):
    """PRD §3.4: "only the already-rounded per-item figures are summed — this is
    round-then-sum, explicitly not sum-the-raw-figures-then-round."
    PRD §3.4: "The policy's total_insured_value_cents is the sum of current_value_cents
    over those same ACTIVE-or-SUSPENDED items."

    Design: Difficulty/combinatorial_formula/premium_round_per_item_then_sum
    """
    set_clock()
    create_risk_zone(zip_prefix="300", risk_band="MODERATE", rate_per_thousand_cents=173)
    create_risk_zone(zip_prefix="301", risk_band="MODERATE", rate_per_thousand_cents=167)
    ph = create_policyholder(email="r2@x.com", residence_zip="30001")
    # PRD §3.3: Watch B at 1,030,000c exceeds the $10,000 appraisal threshold and
    # so must carry a valid appraisal at bind; Watch A at exactly 1,000,000c does not.
    appraisal_b = create_appraisal(ph["id"], appraised_value_cents=1030000,
                                   effective_date_iso="2026-01-01T00:00:00Z")
    policy = create_policy(ph["id"], coverage_type="ALL_RISK",
                           valuation_basis="AGREED_VALUE", deductible_option="LOW")
    create_scheduled_item(policy["id"], description="Watch A", category="WATCH",
                          location_zip="30001", scheduled_value_cents=1000000)
    create_scheduled_item(policy["id"], description="Watch B", category="WATCH",
                          location_zip="30101", scheduled_value_cents=1030000,
                          appraisal_id=appraisal_b["id"])
    validate_success(api.bind_policy(policy["id"], _UW), 200)

    reread = validate_success(api.get_policy(policy["id"], _UW), 200)
    assert reread["annual_premium_cents"] == 5921
    assert reread["total_insured_value_cents"] == 2030000


# ─────────────────────────────────────────────────────────────────────────
# Queue B: entities / consistency
# ─────────────────────────────────────────────────────────────────────────

def test_high_deductible_resolves_to_100000_cents(api):
    """PRD §3.3: "The deductible is resolved from deductible_option into deductible_cents:
    ZERO resolves to zero cents, LOW to twenty-five thousand cents, STANDARD to fifty
    thousand cents, and HIGH to one hundred thousand cents."

    Design: Corner/entities/policy_computed_deductible_cents_from_option
    """
    ctx = setup_quoted_policy_with_item(policy_overrides={"deductible_option": "HIGH"})
    bound = validate_success(api.bind_policy(ctx["policy"]["id"], _UW), 200)
    assert bound["deductible_cents"] == 100000


def test_bind_response_carries_recomputed_premium_immediately(api):
    """PRD §3.3: "Binding is the transition that turns a quote into live coverage, performed
    by an Underwriter and moving coverage_status from QUOTED to BOUND."
    PRD §3.3: "The policy's total_insured_value_cents and annual_premium_cents are then
    recomputed (per the pricing rules in §3.4)."

    Design: Corner/consistency model/bind_changes_visible_same_response
    """
    ctx = setup_quoted_policy_with_item()
    bound = validate_success(api.bind_policy(ctx["policy"]["id"], _UW), 200)
    assert_policy(bound)
    assert bound["coverage_status"] == "BOUND"
    # RING cv 1,000,000, zone rate 300, ALL_RISK, STANDARD -> 3947.
    assert bound["annual_premium_cents"] == 3947
    assert bound["total_insured_value_cents"] == 1000000
