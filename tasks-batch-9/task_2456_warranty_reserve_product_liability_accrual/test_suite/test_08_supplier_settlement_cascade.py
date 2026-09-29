"""The five-hop cascade set off by settling one supplier recovery claim.

PRD §3.7: "It then runs a five-hop cascade in order."
"""

from test_helpers import (
    assert_recovery,
    close_recovery,
    create_failure_mode,
    create_family,
    create_period,
    create_recovery,
    create_supplier,
    read_recovery,
    read_supplier,
)


def _build_world(api):
    """SUP-2 downgraded to LOW by a write-off, then two live asserted claims."""
    period = create_period(api, "2026-Q3", "2026-07-01", "2026-09-30")
    supplier = create_supplier(
        api,
        supplier_code="SUP-2",
        name="Northline Components AB",
        credit_rating="AAA",
        annual_purchase_volume_cents=1000000000,
        contractual_recovery_cap_bps=5000,
    )
    family = create_family(
        api,
        family_code="FAM-N",
        name="Nordic Dishwasher Platform",
        launch_date="2023-05-01",
        base_warranty_months=24,
        standard_cost_per_claim_cents=16000,
        reserve_cap_cents=80000000,
    )
    mode = create_failure_mode(
        api,
        family["id"],
        mode_code="FM-N-PUMP",
        description="Supplied circulation pump seizure",
        severity="FUNCTIONAL",
        cost_per_claim_cents=16000,
        supplier_id=supplier["id"],
    )

    written_off = create_recovery(
        api, supplier["id"], mode["id"], asserted_amount_cents=9000000
    )
    assert_recovery(api, written_off["id"])
    close_recovery(api, written_off["id"], outcome="WRITTEN_OFF")
    assert read_supplier(api, supplier["id"])["collectability_rating"] == "LOW"

    first = create_recovery(api, supplier["id"], mode["id"], asserted_amount_cents=10000000)
    assert_recovery(api, first["id"])
    second = create_recovery(api, supplier["id"], mode["id"], asserted_amount_cents=4000000)
    assert_recovery(api, second["id"])
    assert read_supplier(api, supplier["id"])["open_recovery_asset_cents"] == 3500000

    return {
        "period": period,
        "supplier": supplier,
        "failure_mode": mode,
        "written_off": written_off,
        "first": first,
        "second": second,
    }


def test_hop_one_revalues_the_settled_row_under_the_contractual_floor(api):
    """The settled row snapshots the rating that was in force when it settled.

    PRD §3.7: "**Hop one** writes the supplied `settled_amount_cents`, writes the
    selected booking period into `settled_period_id`, switches `valuation_variant`
    to `CONTRACTUAL_FLOOR`, and recomputes `recognized_recovery_cents` under that
    variant." PRD §3.7 defines that variant as "the lesser of the contractual
    ceiling and `settled_amount_cents`", and the supplier's 500000000-cent ceiling
    does not bind. The rating snapshot is taken before hop three moves the rating.

    Design: Difficulty/transitive_cascade/supplier_settlement_cascades_five_hops_into_sibling_recovery_revaluation
    """
    world = _build_world(api)

    settled = close_recovery(
        api, world["first"]["id"], outcome="SETTLED", settled_amount_cents=8000000
    )

    assert settled["status"] == "SETTLED"
    assert settled["settled_amount_cents"] == 8000000
    assert settled["recognized_recovery_cents"] == 8000000
    assert settled["valuation_variant"] == "CONTRACTUAL_FLOOR"
    assert settled["settled_period_id"] == world["period"]["id"]
    assert settled["collectability_rating_at_valuation"] == "LOW"


def test_hops_two_and_three_lift_the_supplier_rating_by_one_notch(api):
    """A partial realization record earns back exactly one notch.

    PRD §3.7: "**Hop two**, because the row has left the open set and entered
    `SETTLED`, recomputes the supplier's `open_recovery_asset_cents`,
    `realized_recovery_cents` and `closed_recovery_count`. **Hop three**, because
    `closed_recovery_count` and `realized_recovery_cents` changed, recomputes the
    supplier's `realization_bps` and `collectability_rating`." With 8000000
    realized against 9000000 written off the ratio rounds to 4706 basis points, and
    PRD §3.7: "when `realization_bps` is at least 4000 the base rating is downgraded
    by one notch" takes the AAA base of `HIGH` to `MEDIUM`.

    Design: Difficulty/transitive_cascade/supplier_settlement_cascades_five_hops_into_sibling_recovery_revaluation
    """
    world = _build_world(api)

    close_recovery(api, world["first"]["id"], outcome="SETTLED", settled_amount_cents=8000000)

    supplier = read_supplier(api, world["supplier"]["id"])
    assert supplier["realized_recovery_cents"] == 8000000
    assert supplier["closed_recovery_count"] == 2
    assert supplier["realization_bps"] == 4706
    assert supplier["collectability_rating"] == "MEDIUM"


def test_hop_four_revalues_the_sibling_claim_nobody_addressed(api):
    """An untouched ASSERTED claim moves because the rating moved upstream.

    PRD §3.7: "**Hop four**, because the supplier's `collectability_rating` may have
    changed in hop three, re-values every *other* recovery claim of the same supplier
    whose status is `ASSERTED` or `NEGOTIATION` under the `EXPECTED_VALUE` variant,
    updating each row's `recognized_recovery_cents` and
    `collectability_rating_at_valuation`". At `MEDIUM` the 6000-bps weighting takes
    the sibling's 4000000-cent assertion from 1000000 to 2400000 cents, while the
    written-off row is outside the re-valued set and PRD §3.7 pins it: "When a claim's
    status is `WRITTEN_OFF`, `recognized_recovery_cents` is 0 outright."

    Design: Difficulty/transitive_cascade/supplier_settlement_cascades_five_hops_into_sibling_recovery_revaluation
    """
    world = _build_world(api)
    assert read_recovery(api, world["second"]["id"])["recognized_recovery_cents"] == 1000000

    close_recovery(api, world["first"]["id"], outcome="SETTLED", settled_amount_cents=8000000)

    sibling = read_recovery(api, world["second"]["id"])
    assert sibling["recognized_recovery_cents"] == 2400000
    assert sibling["collectability_rating_at_valuation"] == "MEDIUM"
    assert sibling["status"] == "ASSERTED"
    assert sibling["asserted_amount_cents"] == 4000000

    assert read_recovery(api, world["written_off"]["id"])["recognized_recovery_cents"] == 0


def test_hop_five_recomputes_the_open_recovery_asset_after_the_revaluation(api):
    """The live receivable is restated once more at the end of the chain.

    PRD §3.7: "**Hop five**, because hop four changed those rows' recognized figures,
    recomputes the supplier's `open_recovery_asset_cents` once more." PRD §3.7 also
    pins what does not move: "`gross_asserted_recovery_cents` is the sum of
    `asserted_amount_cents` over that supplier's recovery claims whose status is
    `ASSERTED`, `NEGOTIATION`, `SETTLED` or `WRITTEN_OFF`" — all three claims, 23000000
    cents in total.

    Design: Difficulty/transitive_cascade/supplier_settlement_cascades_five_hops_into_sibling_recovery_revaluation
    """
    world = _build_world(api)

    close_recovery(api, world["first"]["id"], outcome="SETTLED", settled_amount_cents=8000000)

    supplier = read_supplier(api, world["supplier"]["id"])
    assert supplier["open_recovery_asset_cents"] == 2400000
    assert supplier["gross_asserted_recovery_cents"] == 23000000
    assert supplier["written_off_recovery_cents"] == 9000000
