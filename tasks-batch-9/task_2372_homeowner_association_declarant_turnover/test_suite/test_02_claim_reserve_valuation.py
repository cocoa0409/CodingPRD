"""Defect claim reserves: the valuation basis, the fee tier and the claim pool."""

from typing import Any, Dict

import pytest
from test_helpers import (
    CLAIM_ACTION_RESERVE,
    ERR_CLAIM_RESERVE_INSUFFICIENT,
    VALUATION_BASIS_DIMINUTION,
    VALUATION_BASIS_REPAIR_COST,
    ApiClient,
    assert_claim_pool_conserved,
    assert_claim_reserve_breakdown,
    build_conveyed_component,
    claim_action_payload,
    do_claim_notice,
    do_claim_reserve,
    do_claim_withdraw,
    make_transition_committee_headers,
    read_association,
    seed_association,
    seed_defect_claim,
    validate_error,
    validate_success,
)

# ─── Birch Commons: sibling claims, opposite valuation bases ───────────


@pytest.fixture
def birch_commons(api: ApiClient) -> Dict[str, Any]:
    """Two noticed claims carrying an identical pair of damage figures."""
    association = seed_association(
        api,
        name="Birch Commons",
        total_planned_lots=24,
        turnover_threshold_pct=75.00,
        fixed_turnover_date="2027-06-01T00:00:00Z",
        statute_of_repose_years=8,
        reserve_pool_cents=500000,
        reserve_claim_pool_cents=5000000,
        declarant_monthly_subsidy_cents=100000,
    )
    component = build_conveyed_component(
        api,
        association["id"],
        effective_date="2020-06-15T00:00:00Z",
        name="Parking Structure",
        category="STRUCTURE",
        replacement_cost_cents=9000000,
        useful_life_years=40,
        effective_age_years=6,
        promised_completion_date="2020-06-01T00:00:00Z",
    )
    claims = []
    for bay in ("bay 3", "bay 4"):
        claim = seed_defect_claim(
            api,
            association["id"],
            component["id"],
            defect_summary=f"Post-tension slab cracking, {bay}",
            repair_cost_estimate_cents=2400000,
            diminution_value_cents=1500000,
        )
        claims.append(do_claim_notice(api, claim["id"], association["id"]))
    return {"association": association, "component": component, "claims": claims}


class TestValuationBasisSelectsTheSubtotal:
    """The basis chosen at RESERVE time decides both the subtotal and the tier."""

    def test_repair_cost_basis_lands_in_the_nine_percent_tier(
        self, api: ApiClient, birch_commons: Dict[str, Any]
    ) -> None:
        """REPAIR_COST takes the repair estimate as the subtotal.

        "That choice selects `reserve_subtotal_cents`: the claim's
        `repair_cost_estimate_cents` under `REPAIR_COST`, or its
        `diminution_value_cents` under `DIMINUTION`."

        Design: Difficulty/dual_variant_calc/claim_reserve_repair_cost_vs_diminution_variant_divergence
        """
        association_id = birch_commons["association"]["id"]
        claim = do_claim_reserve(
            api,
            birch_commons["claims"][0]["id"],
            association_id,
            VALUATION_BASIS_REPAIR_COST,
        )

        assert claim["status"] == "RESERVED"
        assert claim["valuation_basis"] == VALUATION_BASIS_REPAIR_COST
        assert_claim_reserve_breakdown(claim, subtotal=2400000, fee=216000, reserved=2616000)

    def test_diminution_basis_drops_the_same_claim_into_the_twelve_percent_tier(
        self, api: ApiClient, birch_commons: Dict[str, Any]
    ) -> None:
        """The two bases select different tiers from the same claim row.

        "The tier rate is twelve percent while the subtotal is below 2,000,000
        cents, nine percent while it is below 10,000,000 cents, and six percent
        at or above that — each tier bound including its lower edge and
        excluding its upper."

        Design: Difficulty/dual_variant_calc/claim_reserve_repair_cost_vs_diminution_variant_divergence
        """
        association_id = birch_commons["association"]["id"]
        repair_claim = do_claim_reserve(
            api,
            birch_commons["claims"][0]["id"],
            association_id,
            VALUATION_BASIS_REPAIR_COST,
        )
        diminution_claim = do_claim_reserve(
            api,
            birch_commons["claims"][1]["id"],
            association_id,
            VALUATION_BASIS_DIMINUTION,
        )

        assert_claim_reserve_breakdown(
            repair_claim, subtotal=2400000, fee=216000, reserved=2616000
        )
        assert_claim_reserve_breakdown(
            diminution_claim, subtotal=1500000, fee=180000, reserved=1680000
        )
        assert diminution_claim["valuation_basis"] == VALUATION_BASIS_DIMINUTION
        assert diminution_claim["status"] == "RESERVED"

        association = read_association(api, association_id)
        assert association["reserve_claim_committed_cents"] == 4296000
        assert association["reserve_claim_available_cents"] == 704000
        assert_claim_pool_conserved(association)


# ─── Dunmore Village: the tier trap window ─────────────────────────────


@pytest.fixture
def dunmore_village(api: ApiClient) -> Dict[str, Any]:
    """A noticed claim whose subtotal is under the tier ceiling but whose total is over."""
    association = seed_association(
        api,
        name="Dunmore Village",
        total_planned_lots=40,
        turnover_threshold_pct=50.00,
        fixed_turnover_date="2028-01-01T00:00:00Z",
        statute_of_repose_years=8,
        reserve_pool_cents=800000,
        reserve_claim_pool_cents=3000000,
        declarant_monthly_subsidy_cents=90000,
    )
    component = build_conveyed_component(
        api,
        association["id"],
        effective_date="2021-04-02T00:00:00Z",
        name="Pool Deck",
        category="AMENITY",
        replacement_cost_cents=3000000,
        useful_life_years=15,
        effective_age_years=5,
        promised_completion_date="2021-04-01T00:00:00Z",
    )
    claim = seed_defect_claim(
        api,
        association["id"],
        component["id"],
        defect_summary="Pool deck delamination",
        repair_cost_estimate_cents=1950000,
        diminution_value_cents=1100000,
    )
    claim = do_claim_notice(api, claim["id"], association["id"])
    return {"association": association, "claim": claim}


class TestFeeTierComesFromTheSubtotal:
    """Tier selection happens before the fee is added, never after."""

    def test_tier_is_selected_from_the_subtotal_alone(
        self, api: ApiClient, dunmore_village: Dict[str, Any]
    ) -> None:
        """A subtotal of 1,950,000 stays in the twelve percent tier.

        "The evaluation order from there is pinned and normative: first the
        subtotal, then the fee tier **selected from the subtotal alone**, then
        the fee, then the total."

        Design: Difficulty/combinatorial_formula/claim_fee_tier_selected_from_subtotal_not_from_total
        """
        association_id = dunmore_village["association"]["id"]
        claim = do_claim_reserve(
            api,
            dunmore_village["claim"]["id"],
            association_id,
            VALUATION_BASIS_REPAIR_COST,
        )

        assert_claim_reserve_breakdown(claim, subtotal=1950000, fee=234000, reserved=2184000)
        assert claim["litigation_admin_fee_cents"] != 175500, (
            "Re-selecting the tier from the 2,184,000 total would report 175,500"
        )

    def test_the_committed_pool_reflects_the_subtotal_tier_figure(
        self, api: ApiClient, dunmore_village: Dict[str, Any]
    ) -> None:
        """The association commits the subtotal plus the twelve percent fee.

        "`litigation_admin_fee_cents` is the subtotal multiplied by that rate,
        rounded half up to whole cents, and `reserved_amount_cents` is the
        subtotal plus the fee."

        Design: Difficulty/combinatorial_formula/claim_fee_tier_selected_from_subtotal_not_from_total
        """
        association_id = dunmore_village["association"]["id"]
        do_claim_reserve(
            api,
            dunmore_village["claim"]["id"],
            association_id,
            VALUATION_BASIS_REPAIR_COST,
        )

        association = read_association(api, association_id)
        assert association["reserve_claim_committed_cents"] == 2184000
        assert association["reserve_claim_available_cents"] == 816000
        assert_claim_pool_conserved(association)


# ─── Vellum Commons: reserve, refuse, release, re-reserve ──────────────


@pytest.fixture
def vellum_commons(api: ApiClient) -> Dict[str, Any]:
    """Two noticed claims against a 3,000,000 cent claim pool."""
    association = seed_association(
        api,
        name="Vellum Commons",
        total_planned_lots=24,
        turnover_threshold_pct=66.67,
        fixed_turnover_date="2027-04-01T00:00:00Z",
        statute_of_repose_years=8,
        reserve_pool_cents=200000,
        reserve_claim_pool_cents=3000000,
        declarant_monthly_subsidy_cents=42000,
    )
    component = build_conveyed_component(
        api,
        association["id"],
        effective_date="2024-02-01T00:00:00Z",
        name="Retaining Wall",
        category="STRUCTURE",
        replacement_cost_cents=2600000,
        useful_life_years=30,
        effective_age_years=2,
        promised_completion_date="2024-02-01T00:00:00Z",
    )
    claim_a = seed_defect_claim(
        api,
        association["id"],
        component["id"],
        defect_summary="Wall tilt at panel 4",
        repair_cost_estimate_cents=1950000,
        diminution_value_cents=1100000,
    )
    claim_b = seed_defect_claim(
        api,
        association["id"],
        component["id"],
        defect_summary="Weep hole blockage",
        repair_cost_estimate_cents=850000,
        diminution_value_cents=400000,
    )
    do_claim_notice(api, claim_a["id"], association["id"])
    do_claim_notice(api, claim_b["id"], association["id"])
    return {"association": association, "claim_a": claim_a, "claim_b": claim_b}


class TestClaimPoolIsConserved:
    """Committed plus available equals the pool after every step."""

    def test_a_reserve_that_does_not_fit_the_pool_is_refused_and_moves_nothing(
        self, api: ApiClient, vellum_commons: Dict[str, Any]
    ) -> None:
        """The second claim needs 952,000 against 816,000 available.

        "`reserved_amount_cents` must be less than or equal to the
        association's `reserve_claim_available_cents`, with equality allowed;
        anything larger is `ERR_CLAIM_RESERVE_INSUFFICIENT`, evaluated after
        every other check on the request."

        Design: Difficulty/compensating_invariant/claim_reserve_release_conserves_the_association_claim_pool
        """
        association_id = vellum_commons["association"]["id"]
        committee = make_transition_committee_headers(association_id)

        do_claim_reserve(
            api, vellum_commons["claim_a"]["id"], association_id, VALUATION_BASIS_REPAIR_COST
        )
        after_first = read_association(api, association_id)
        assert after_first["reserve_claim_committed_cents"] == 2184000
        assert after_first["reserve_claim_available_cents"] == 816000
        assert_claim_pool_conserved(after_first)

        validate_error(
            api.defect_claim_action(
                vellum_commons["claim_b"]["id"],
                claim_action_payload(
                    CLAIM_ACTION_RESERVE, valuation_basis=VALUATION_BASIS_REPAIR_COST
                ),
                committee,
            ),
            ERR_CLAIM_RESERVE_INSUFFICIENT,
        )

        after_refusal = read_association(api, association_id)
        assert after_refusal["reserve_claim_committed_cents"] == 2184000, (
            "A refused reserve commits nothing"
        )
        assert_claim_pool_conserved(after_refusal)

    def test_withdrawal_returns_the_committed_amount_fee_included(
        self, api: ApiClient, vellum_commons: Dict[str, Any]
    ) -> None:
        """The compensating release restores the pool to the cent.

        "After every forward-and-compensating pair,
        `reserve_claim_committed_cents` plus `reserve_claim_available_cents`
        still equals `reserve_claim_pool_cents`."

        Design: Difficulty/compensating_invariant/claim_reserve_release_conserves_the_association_claim_pool
        """
        association_id = vellum_commons["association"]["id"]
        committee = make_transition_committee_headers(association_id)

        do_claim_reserve(
            api, vellum_commons["claim_a"]["id"], association_id, VALUATION_BASIS_REPAIR_COST
        )
        validate_error(
            api.defect_claim_action(
                vellum_commons["claim_b"]["id"],
                claim_action_payload(
                    CLAIM_ACTION_RESERVE, valuation_basis=VALUATION_BASIS_REPAIR_COST
                ),
                committee,
            ),
            ERR_CLAIM_RESERVE_INSUFFICIENT,
        )

        withdrawn = do_claim_withdraw(
            api, vellum_commons["claim_a"]["id"], association_id
        )
        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["reserved_amount_cents"] == 0

        released = read_association(api, association_id)
        assert released["reserve_claim_committed_cents"] == 0
        assert released["reserve_claim_available_cents"] == 3000000
        assert_claim_pool_conserved(released)

        reserved_b = validate_success(
            api.defect_claim_action(
                vellum_commons["claim_b"]["id"],
                claim_action_payload(
                    CLAIM_ACTION_RESERVE, valuation_basis=VALUATION_BASIS_REPAIR_COST
                ),
                committee,
            )
        )
        assert reserved_b["status"] == "RESERVED"
        assert_claim_reserve_breakdown(
            reserved_b, subtotal=850000, fee=102000, reserved=952000
        )

        final = read_association(api, association_id)
        assert final["reserve_claim_committed_cents"] == 952000
        assert final["reserve_claim_available_cents"] == 2048000
        assert_claim_pool_conserved(final)
