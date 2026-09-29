"""The two supplier-recovery valuation variants on one unchanged claim.

PRD §3.7: "An identical asserted amount against an identical supplier therefore
yields a different recognized figure under this variant than it did under
`EXPECTED_VALUE` one transition earlier."
"""

from test_helpers import (
    assert_recovery,
    close_recovery,
    create_failure_mode,
    create_family,
    create_period,
    create_recovery,
    create_supplier,
    read_supplier,
)


def _build_world(api):
    period = create_period(api, "2026-Q3", "2026-07-01", "2026-09-30")
    supplier = create_supplier(
        api,
        supplier_code="SUP-1",
        name="Meridian Controls Ltd",
        credit_rating="AAA",
        annual_purchase_volume_cents=500000000,
        contractual_recovery_cap_bps=2000,
    )
    family = create_family(
        api,
        family_code="FAM-S",
        name="Smart Control Range",
        launch_date="2023-01-01",
        base_warranty_months=24,
        standard_cost_per_claim_cents=15000,
        reserve_cap_cents=50000000,
    )
    mode = create_failure_mode(
        api,
        family["id"],
        mode_code="FM-S-CTRL",
        description="Supplied controller board solder crack",
        severity="FUNCTIONAL",
        cost_per_claim_cents=15000,
        supplier_id=supplier["id"],
    )
    recovery = create_recovery(
        api, supplier["id"], mode["id"], asserted_amount_cents=4000000
    )
    return {
        "period": period,
        "supplier": supplier,
        "failure_mode": mode,
        "recovery": recovery,
    }


def test_expected_value_variant_probability_weights_the_asserted_claim(api):
    """Asserting values the claim at the supplier's collectability weighting.

    PRD §3.7: "It probability-weights the full asserted claim by the supplier's
    collectability: a rating of `HIGH` weights at 9000 basis points, `MEDIUM` at
    6000, `LOW` at 2500, and `IMPAIRED` at 0. Multiply `asserted_amount_cents` by
    that weighting, divide by 10000, round to the nearest integer, and then take
    the lesser of that figure and the contractual ceiling". The AAA supplier rates
    `HIGH`, so 4000000 weights to 3600000 cents, well under the 100000000-cent
    ceiling. PRD §3.7: "Either way, 1 is added to `assert_count`, the
    `valuation_variant` is set to (or remains) `EXPECTED_VALUE`".

    Design: Difficulty/dual_variant_calc/supplier_recovery_expected_value_vs_contractual_floor_valuation
    """
    world = _build_world(api)

    asserted = assert_recovery(api, world["recovery"]["id"])

    assert asserted["status"] == "ASSERTED"
    assert asserted["recognized_recovery_cents"] == 3600000
    assert asserted["valuation_variant"] == "EXPECTED_VALUE"
    assert asserted["collectability_rating_at_valuation"] == "HIGH"
    assert asserted["assert_count"] == 1


def test_contractual_floor_variant_books_the_agreed_settlement_without_weighting(api):
    """Settling drops the probability weighting for the agreed figure.

    PRD §3.7: "It uses the agreed figure with no probability weighting whatsoever:
    `recognized_recovery_cents` is the lesser of the contractual ceiling and
    `settled_amount_cents`." The 2500000-cent settlement is below the
    100000000-cent ceiling, so it is recognized in full — 1100000 cents less than
    the `EXPECTED_VALUE` figure one transition earlier. PRD §3.7: "**Hop one**
    writes the supplied `settled_amount_cents`, writes the selected booking period
    into `settled_period_id`, switches `valuation_variant` to `CONTRACTUAL_FLOOR`".

    Design: Difficulty/dual_variant_calc/supplier_recovery_expected_value_vs_contractual_floor_valuation
    """
    world = _build_world(api)
    asserted = assert_recovery(api, world["recovery"]["id"])
    assert asserted["recognized_recovery_cents"] == 3600000

    settled = close_recovery(
        api, world["recovery"]["id"], outcome="SETTLED", settled_amount_cents=2500000
    )

    assert settled["status"] == "SETTLED"
    assert settled["recognized_recovery_cents"] == 2500000
    assert settled["valuation_variant"] == "CONTRACTUAL_FLOOR"
    assert settled["settled_amount_cents"] == 2500000
    assert settled["settled_period_id"] == world["period"]["id"]
    assert asserted["recognized_recovery_cents"] - settled["recognized_recovery_cents"] == 1100000


def test_settlement_moves_the_recognized_asset_into_realized_recovery(api):
    """The supplier aggregates follow the claim out of the open set.

    PRD §3.7: "`open_recovery_asset_cents` is the sum of
    `recognized_recovery_cents` over claims still in `ASSERTED` or `NEGOTIATION` —
    the live receivable. `realized_recovery_cents` is the sum of
    `recognized_recovery_cents` over claims in `SETTLED`." With one settled claim
    and nothing written off, PRD §3.7: "`realization_bps` is
    `realized_recovery_cents` multiplied by 10000, divided by that denominator,
    rounded to the nearest integer" gives 10000 basis points, and "when
    `realization_bps` is at least 7500 the base rating stands".

    Design: Difficulty/dual_variant_calc/supplier_recovery_expected_value_vs_contractual_floor_valuation
    """
    world = _build_world(api)
    assert_recovery(api, world["recovery"]["id"])
    close_recovery(
        api, world["recovery"]["id"], outcome="SETTLED", settled_amount_cents=2500000
    )

    supplier = read_supplier(api, world["supplier"]["id"])

    assert supplier["gross_asserted_recovery_cents"] == 4000000
    assert supplier["realized_recovery_cents"] == 2500000
    assert supplier["open_recovery_asset_cents"] == 0
    assert supplier["closed_recovery_count"] == 1
    assert supplier["realization_bps"] == 10000
    assert supplier["collectability_rating"] == "HIGH"
