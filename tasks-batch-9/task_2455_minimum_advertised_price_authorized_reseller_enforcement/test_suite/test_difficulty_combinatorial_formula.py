"""Formulas whose result depends on the order in which their steps are applied:
per-component rounding before the residual, and tier selection before the
increment it will itself change.
"""
from prd_bench_local_runner.testing import validate_paginated

from test_helpers import BCM_HEADERS, api_client
from test_helpers.assertions import (
    allocate_bundle,
    assert_same_instant,
    deviation_pct,
    score_delta,
    tier_rate_for_score,
)
from test_helpers.factories import bundle_component
from test_helpers.fixtures import (
    assess_chargeback,
    capture_observation,
    create_confirmed_trace,
    create_distributor,
    create_product,
    create_published_policy,
    evaluate_observation,
    pin_clock,
    read_chargeback,
    read_distributor,
)

CLOCK_AUG_01 = "2026-08-01T00:00:00Z"
CLOCK_AUG_10 = "2026-08-10T00:00:00Z"
OBSERVED_AUG_05 = "2026-08-05T00:00:00Z"

BUNDLE_TOTAL = 10000
BUNDLE_COMPONENTS = [
    bundle_component("SKU-A", 4000),
    bundle_component("SKU-B", 4000),
    bundle_component("SKU-C", 4000),
]


# --------------------------------------------------------------------------- #
# Instance 1 — bundle allocation rounds each share, then hands over the residual
# --------------------------------------------------------------------------- #
def _setup_bundle_listings():
    """Two identical bundle listings observed against two of the bundle's members."""
    pin_clock(CLOCK_AUG_01)
    policy = create_published_policy()
    product_a = create_product(
        policy["id"], sku="SKU-A", msrp_cents=4000, standard_map_floor_cents=3400
    )
    product_c = create_product(
        policy["id"], sku="SKU-C", msrp_cents=4000, standard_map_floor_cents=3400
    )
    pin_clock(CLOCK_AUG_10)
    observations = {}
    evaluations = {}
    for key, product in (("a", product_a), ("c", product_c)):
        observations[key] = capture_observation(
            product["id"],
            channel="RETAILER_SITE",
            listed_price_cents=BUNDLE_TOTAL,
            observed_at=OBSERVED_AUG_05,
            is_bundle=True,
            bundle_total_price_cents=BUNDLE_TOTAL,
            bundle_components=BUNDLE_COMPONENTS,
            listing_url=f"https://retailer.example/bundle-{key}",
        )
        evaluations[key] = evaluate_observation(observations[key]["id"])
    return {
        "policy": policy,
        "product_a": product_a,
        "product_c": product_c,
        "observations": observations,
        "evaluations": evaluations,
    }


def test_bundle_shares_are_rounded_per_component_with_the_residual_on_the_last():
    """Equal-MSRP components tie-break on sku ascending and the last absorbs the drift.

    PRD: "The last component in the ordering receives the residual: the advertised
    bundle price minus the running total of every earlier share."

    Design: Difficulty/combinatorial_formula/bundle_allocation_round_per_component_then_residual
    """
    world = _setup_bundle_listings()
    expected = allocate_bundle(BUNDLE_TOTAL, BUNDLE_COMPONENTS)
    assert expected == {"SKU-A": 3333, "SKU-B": 3333, "SKU-C": 3334}
    assert sum(expected.values()) == BUNDLE_TOTAL

    assert world["evaluations"]["a"]["allocated_component_price_cents"] == expected["SKU-A"]
    assert world["evaluations"]["c"]["allocated_component_price_cents"] == expected["SKU-C"]


def test_the_allocated_share_and_not_the_bundle_price_drives_the_deviation():
    """The share belonging to the observed sku becomes the effective advertised price.

    PRD: "The observation's `allocated_component_price_cents` is the share belonging
    to the component whose `sku` matches the observed product's `sku`."

    Design: Difficulty/combinatorial_formula/bundle_allocation_round_per_component_then_residual
    """
    world = _setup_bundle_listings()
    evaluation_a = world["evaluations"]["a"]
    evaluation_c = world["evaluations"]["c"]

    assert evaluation_a["effective_advertised_price_cents"] == 3333
    assert evaluation_a["effective_map_floor_cents"] == 3400
    assert evaluation_a["floor_source"] == "STANDARD"
    assert evaluation_a["deviation_cents"] == 67
    assert evaluation_a["deviation_pct"] == deviation_pct(3400, 67)

    assert evaluation_c["effective_advertised_price_cents"] == 3334
    assert evaluation_c["deviation_cents"] == 66
    assert evaluation_c["deviation_pct"] == deviation_pct(3400, 66) == 0.0194

    assert evaluation_a["evaluation_status"] == "EVALUATED_BREACH"
    assert evaluation_c["evaluation_status"] == "EVALUATED_BREACH"


def test_an_unmatched_bundle_breach_opens_no_violation():
    """With no matched reseller there is nobody to notice, so no violation is opened.

    PRD: "If `matched_reseller_id` is null, **no** violation row is created at all:
    there is nobody under contract to notice, `unauthorized_seller_confirmed` remains
    false, and the breach is instead routed into the test-purchase workflow of §3.8."

    Design: Difficulty/combinatorial_formula/bundle_allocation_round_per_component_then_residual
    """
    world = _setup_bundle_listings()
    for key in ("a", "c"):
        evaluation = world["evaluations"][key]
        assert evaluation["violation_id"] is None
        assert evaluation["unauthorized_seller_confirmed"] is False
        rows, meta = validate_paginated(
            api_client.list_violations(
                BCM_HEADERS, params={"observation_id": world["observations"][key]["id"]}
            )
        )
        assert meta["total_count"] == 0
        assert rows == []


# --------------------------------------------------------------------------- #
# Instance 2 — the chargeback tier is read from the pre-increment score
# --------------------------------------------------------------------------- #
def _setup_two_traced_units():
    """One distributor with two independently traced units of the same lot."""
    pin_clock(CLOCK_AUG_01)
    policy = create_published_policy()
    product = create_product(policy["id"], serialization_enabled=True)
    distributor = create_distributor(
        legal_name="Northwind Tiered Accountability", annual_chargeback_cap_cents=5_000_000
    )
    pin_clock(CLOCK_AUG_10)
    first_purchase, _first_unit, _obs = create_confirmed_trace(
        product["id"], distributor["id"], serial_number="SN-10", lot_code="LOT-B"
    )
    second_purchase, _second_unit, _obs2 = create_confirmed_trace(
        product["id"], distributor["id"], serial_number="SN-11", lot_code="LOT-B"
    )
    return {
        "product": product,
        "distributor": distributor,
        "first_purchase": first_purchase,
        "second_purchase": second_purchase,
    }


def test_the_first_chargeback_is_priced_from_a_zero_pre_event_score():
    """A distributor with no history is billed at the lowest tier.

    PRD: "The `tier_rate_cents_per_unit` is 2500 cents when that pre-event score is
    strictly below 10.0, 4000 cents when it is at or above 10.0 but strictly below
    25.0, and 6000 cents when it is at or above 25.0 — twenty-five, forty and sixty
    dollars a unit, with both tier boundaries inclusive at the lower bound."

    Design: Difficulty/combinatorial_formula/chargeback_tier_priced_from_pre_increment_diversion_score
    """
    world = _setup_two_traced_units()
    before = read_distributor(world["distributor"]["id"])
    assert before["diversion_score"] == 0

    chargeback = assess_chargeback(
        world["distributor"]["id"], world["first_purchase"]["id"], diverted_units=4
    )
    assert chargeback["status"] == "ASSESSED"
    assert chargeback["tier_rate_cents_per_unit"] == tier_rate_for_score(0) == 2500
    assert chargeback["amount_cents"] == 2500 * 4 == 10000
    assert chargeback["score_delta_applied"] == score_delta(4) == 10.0
    assert chargeback["dispute_rounds"] == 0


def test_the_second_chargeback_is_priced_before_its_own_increment_lands():
    """Tier selection reads the score as it stood before this event's delta.

    PRD: "Evaluating the tier *after* the increment would price the very first
    chargeback one tier too high, which is why the order is fixed."

    Design: Difficulty/combinatorial_formula/chargeback_tier_priced_from_pre_increment_diversion_score
    """
    world = _setup_two_traced_units()
    first = assess_chargeback(
        world["distributor"]["id"], world["first_purchase"]["id"], diverted_units=4
    )

    midway = read_distributor(world["distributor"]["id"])
    assert midway["diversion_score"] == 10.0

    second = assess_chargeback(
        world["distributor"]["id"], world["second_purchase"]["id"], diverted_units=2
    )
    assert second["tier_rate_cents_per_unit"] == tier_rate_for_score(10.0) == 4000
    assert second["amount_cents"] == 4000 * 2 == 8000
    assert second["score_delta_applied"] == score_delta(2) == 5.0

    # The earlier row keeps the tier its own pre-event score justified.
    first_again = read_chargeback(first["id"])
    assert first_again["tier_rate_cents_per_unit"] == 2500


def test_both_assessments_accumulate_into_the_ledgers_and_re_derive_standing():
    """Balance, score and standing all move once per assessment, in the pinned order.

    PRD: "Only after both figures are fixed is the distributor's state moved, and in
    this order: `amount_cents` is added to `chargeback_balance_cents`, then
    `score_delta_applied` is added to the pre-event score to give the new
    `diversion_score`, then `standing` is re-derived from that new score — `GOOD` when
    it is strictly below 10.0, `PROBATION` when it is at or above 10.0 but strictly
    below 25.0, and `SUSPENDED` when it is at or above 25.0."

    Design: Difficulty/combinatorial_formula/chargeback_tier_priced_from_pre_increment_diversion_score
    """
    world = _setup_two_traced_units()
    assess_chargeback(world["distributor"]["id"], world["first_purchase"]["id"], diverted_units=4)
    assess_chargeback(world["distributor"]["id"], world["second_purchase"]["id"], diverted_units=2)

    distributor = read_distributor(world["distributor"]["id"])
    assert distributor["chargeback_balance_cents"] == 10000 + 8000 == 18000
    assert distributor["diversion_score"] == 15.0
    assert distributor["standing"] == "PROBATION"
    assert_same_instant(
        distributor["probation_entered_at"], CLOCK_AUG_10, "probation_entered_at"
    )
    assert distributor["shipped_units_total"] == 2
