"""Settlement pricing: dual variants, per-line rounding, rebate tiers, OCC."""
import pytest

from test_helpers import (
    ApiErrorId,
    confirm_grading_run,
    contract_payload,
    create_draft_settlement,
    get_success_data,
    grading_submit_payload,
    record_feed_delivery,
    record_production_days,
    set_clock,
    setup_active_contract,
    setup_farm,
    setup_house,
    place_flock,
    setup_laying_flock,
    setup_shipped_lots,
    settlement_payload,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    CONTRACT_MANAGER,
    QA_MANAGER,
    get_contract,
    get_settlement,
    lots_of_run,
    release_allocate_ship,
    run_daily_ops,
)


def _pricing_side(api, farm_name, contract_overrides, market_index_cents):
    """One farm running the full chain: 1000-hen LAYING flock (placed
    2026-01-05, pullet cost 420000c, overhead 12000c/day), 5000 kg of 50c/kg
    feed delivered 2026-07-01, one 2026-07-20 production day (240 eggs,
    118 kg feed), a confirmed all-LARGE grade-A run -> one 20-dozen lot, an
    ACTIVE contract, the lot shipped at clock 2026-07-24, and a DRAFT
    settlement for 2026-07-20..2026-07-26. Returns the draft settlement."""
    farm = setup_farm(name=farm_name, daily_overhead_cents=12000)
    house = setup_house(farm["id"])
    flock = place_flock(house["id"], initial_hen_count=1000, pullet_cost_cents=420000)
    run_daily_ops()  # age 29 weeks -> LAYING at the startup clock
    record_feed_delivery(
        farm["id"], delivered_at="2026-07-01", quantity_kg=5000, cost_per_kg_cents=50
    )
    set_clock("2026-07-24T00:00:00Z")
    record_production_days(
        flock["id"],
        [
            {
                "lay_date": "2026-07-20",
                "eggs_collected": 240,
                "rejected_eggs": 0,
                "feed_issued_kg": 118,
                "mortality_count": 0,
            }
        ],
    )
    run, lots = confirm_grading_run(flock["id"], grade="A", eggs_to_grade=240)
    contract = setup_active_contract(farm["id"], **contract_overrides)
    release_allocate_ship(lots[0]["id"], contract["id"])
    settlement = create_draft_settlement(
        contract["id"], "2026-07-20", "2026-07-26", market_index_cents
    )
    return settlement


class TestSettlementPricingVariants:
    def test_settlement_pricing_market_index_variant(self, api):
        """PRD §3.6: "Under `MARKET_INDEX` the base is the settlement's
        `market_index_cents` plus the contract's `spread_cents`."
        PRD §3.6: "The line's `price_cents_per_dozen` is the base multiplied
        by this multiplier, rounded half-up to a whole number of cents — the
        rounding happens per line, before anything is summed."
        PRD §3.6: "The size premiums are: `JUMBO` 0.20, `XLARGE` 0.10, `LARGE`
        0.0, `MEDIUM` negative 0.05, `SMALL` negative 0.10, and `PEEWEE`
        negative 0.15. The grade uplifts are: `AA` 0.05, `A` 0.0, and `B`
        negative 0.08."
        PRD §3.6: "Step five selects the volume rebate tier from the
        pre-rebate subtotal — never from the final total: a `subtotal_cents`
        of at least 500000 earns a `rebate_pct` of 0.04; at least 100000 earns
        0.02; anything below earns 0."

        Design: Difficulty/dual_variant_calc/settlement_pricing_market_index_vs_cost_plus
        """
        settlement = _pricing_side(
            api,
            "MI Farm",
            {"pricing_model": "MARKET_INDEX", "spread_cents": 5, "margin_pct": 0},
            market_index_cents=140,
        )
        finalized = validate_success(api.finalize_settlement(settlement["id"], CONTRACT_MANAGER))
        assert finalized["pricing_model_used"] == "MARKET_INDEX"
        # base 140 + 5 = 145; multiplier 1 + 0.0 (LARGE) + 0.0 (grade A) + 0 = 1
        assert finalized["lines"][0]["price_cents_per_dozen"] == 145
        assert finalized["lines"][0]["line_amount_cents"] == 2900  # 145 x 20 dozen
        assert finalized["subtotal_cents"] == 2900
        assert finalized["rebate_pct"] == pytest.approx(0)
        assert finalized["total_cents"] == 2900

    def test_settlement_pricing_cost_plus_variant(self, api):
        """PRD §3.6: "Under `COST_PLUS` the base is the `ACTUAL_FIFO` cost per
        dozen of §3.3 computed over the settlement period — recorded on the
        settlement as `cost_per_dozen_cents`, rounded half-up to two decimal
        places — multiplied by one plus the contract's `margin_pct`"
        PRD §3.3: "The cost per dozen is then the sum of feed cents, overhead
        cents, and amortization cents, minus the spent-hen credit, the
        difference multiplied by 12 and divided by `total_eggs`, rounded
        half-up to two decimal places."
        PRD §3.6: "Step six computes `rebate_cents` as the subtotal multiplied
        by `rebate_pct`, rounded half-up to a whole number of cents. Step
        seven sets `total_cents` to `subtotal_cents` minus `rebate_cents`."

        Design: Difficulty/dual_variant_calc/settlement_pricing_market_index_vs_cost_plus
        """
        settlement = _pricing_side(
            api,
            "CP Farm",
            {"pricing_model": "COST_PLUS", "spread_cents": 0, "margin_pct": 0.20},
            market_index_cents=None,
        )
        finalized = validate_success(api.finalize_settlement(settlement["id"], CONTRACT_MANAGER))
        assert finalized["pricing_model_used"] == "COST_PLUS"
        # ACTUAL_FIFO cpd: (5900 feed + 84000 overhead + 7000 amort) x 12 / 240
        assert finalized["cost_per_dozen_cents"] == pytest.approx(4845.00)
        # base 4845 x 1.20 = 5814.0 -> 5814 per dozen
        assert finalized["lines"][0]["price_cents_per_dozen"] == 5814
        assert finalized["lines"][0]["line_amount_cents"] == 116280  # 5814 x 20
        assert finalized["subtotal_cents"] == 116280
        assert finalized["rebate_pct"] == pytest.approx(0.02)
        assert finalized["rebate_cents"] == 2326  # round_half_up(116280 x 0.02)
        assert finalized["total_cents"] == 113954

    def test_settlement_pricing_variants_diverge_on_identical_economics(self, api):
        """PRD §3.6: "`spread_cents` — the cents added to the market index per
        dozen — is zero or more, belongs to `MARKET_INDEX` contracts"
        PRD §3.6: "Under `COST_PLUS` the base is the `ACTUAL_FIFO` cost per
        dozen of §3.3 computed over the settlement period"
        (Byte-identical production economics under the two pricing models must
        bill differently: 2900 vs 113954 total cents.)

        Design: Difficulty/dual_variant_calc/settlement_pricing_market_index_vs_cost_plus
        """
        mi = _pricing_side(
            api,
            "MI Farm",
            {"pricing_model": "MARKET_INDEX", "spread_cents": 5, "margin_pct": 0},
            market_index_cents=140,
        )
        cp = _pricing_side(
            api,
            "CP Farm",
            {"pricing_model": "COST_PLUS", "spread_cents": 0, "margin_pct": 0.20},
            market_index_cents=None,
        )
        mi_final = validate_success(api.finalize_settlement(mi["id"], CONTRACT_MANAGER))
        cp_final = validate_success(api.finalize_settlement(cp["id"], CONTRACT_MANAGER))
        assert mi_final["total_cents"] == 2900
        assert cp_final["total_cents"] == 113954
        assert mi_final["total_cents"] != cp_final["total_cents"]


class TestPerLineRoundingOrder:
    def _setup_medium_line_settlement(self, api):
        """One MEDIUM grade-A 24-dozen lot shipped; MARKET_INDEX contract
        (index 140, spread 5) with a DRAFT settlement for 2026-07-20..26."""
        ctx = setup_shipped_lots(
            production_days=[
                {
                    "lay_date": "2026-07-20",
                    "eggs_collected": 288,
                    "rejected_eggs": 0,
                    "feed_issued_kg": 0,
                    "mortality_count": 0,
                }
            ],
            clock_iso="2026-07-24T00:00:00Z",
            eggs_to_grade=288,
            submit_counts=grading_submit_payload(medium_count=288),
        )
        ctx["settlement"] = create_draft_settlement(
            ctx["contract"]["id"], "2026-07-20", "2026-07-26", 140
        )
        return ctx

    def test_settlement_per_line_rounding_order(self, api):
        """PRD §3.6: "The line's `price_cents_per_dozen` is the base multiplied
        by this multiplier, rounded half-up to a whole number of cents — the
        rounding happens per line, before anything is summed."
        PRD §3.6: "Step three multiplies each line's `price_cents_per_dozen`
        by its `dozen_count` to get `line_amount_cents`, an exact integer."

        Design: Difficulty/combinatorial_formula/settlement_per_line_rounding_order
        """
        ctx = self._setup_medium_line_settlement(api)
        finalized = validate_success(
            api.finalize_settlement(ctx["settlement"]["id"], CONTRACT_MANAGER)
        )
        # exact price 145 x (1 - 0.05 + 0.0) = 137.75 -> per-line round -> 138
        assert finalized["lines"][0]["price_cents_per_dozen"] == 138, (
            f"round-half-up(137.75) = 138 per line first, got "
            f"{finalized['lines'][0]['price_cents_per_dozen']}"
        )
        assert finalized["lines"][0]["line_amount_cents"] == 3312  # 138 x 24

    def test_settlement_round_per_line_not_multiply_then_round(self, api):
        """PRD §3.6: "The line's `price_cents_per_dozen` is the base multiplied
        by this multiplier, rounded half-up to a whole number of cents — the
        rounding happens per line, before anything is summed."
        PRD §3.6: "Step four sums the line amounts into `subtotal_cents`."

        Design: Difficulty/combinatorial_formula/settlement_per_line_rounding_order
        """
        ctx = self._setup_medium_line_settlement(api)
        finalized = validate_success(
            api.finalize_settlement(ctx["settlement"]["id"], CONTRACT_MANAGER)
        )
        assert finalized["subtotal_cents"] == 3312
        assert finalized["total_cents"] == 3312, (
            "below both rebate tiers, total equals subtotal"
        )
        # multiply-then-round would give round(137.75 x 24) = 3306 — rejected.
        assert finalized["subtotal_cents"] != 3306


class TestRebateTier:
    def _setup_rebate_settlement(self, api):
        """JUMBO 80 dozen + LARGE 600 dozen (both grade A) shipped to one
        MARKET_INDEX contract; DRAFT settlement for 2026-07-20..26."""
        ctx = setup_shipped_lots(
            production_days=[
                {
                    "lay_date": "2026-07-20",
                    "eggs_collected": 8160,
                    "rejected_eggs": 0,
                    "feed_issued_kg": 0,
                    "mortality_count": 0,
                }
            ],
            clock_iso="2026-07-24T00:00:00Z",
            eggs_to_grade=8160,
            submit_counts=grading_submit_payload(large_count=7200, jumbo_count=960),
            contract_overrides={"max_open_dozen": 1000, "weekly_min_dozen": 100},
        )
        assert len(ctx["lots"]) == 2
        ctx["settlement"] = create_draft_settlement(
            ctx["contract"]["id"], "2026-07-20", "2026-07-26", 140
        )
        return ctx

    def test_settlement_rebate_tier_keyed_on_pre_rebate_subtotal(self, api):
        """PRD §3.6: "Step five selects the volume rebate tier from the
        pre-rebate subtotal — never from the final total: a `subtotal_cents`
        of at least 500000 earns a `rebate_pct` of 0.04; at least 100000 earns
        0.02; anything below earns 0."
        PRD §3.6: "Step six computes `rebate_cents` as the subtotal multiplied
        by `rebate_pct`, rounded half-up to a whole number of cents. Step
        seven sets `total_cents` to `subtotal_cents` minus `rebate_cents`."

        Design: Difficulty/combinatorial_formula/settlement_rebate_tier_keyed_on_pre_rebate_subtotal
        """
        ctx = self._setup_rebate_settlement(api)
        finalized = validate_success(
            api.finalize_settlement(ctx["settlement"]["id"], CONTRACT_MANAGER)
        )
        # JUMBO 145 x 1.20 = 174 x 80 = 13920; LARGE 145 x 600 = 87000.
        assert finalized["subtotal_cents"] == 100920
        assert finalized["rebate_pct"] == pytest.approx(0.02), (
            "tier selection must read the PRE-rebate subtotal 100920 >= 100000"
        )
        assert finalized["rebate_cents"] == 2018
        assert finalized["total_cents"] == 98902, (
            "the post-rebate total falls below the tier threshold; the tier "
            "must not flip"
        )

    def test_settlement_rebate_lines_and_covered_lots_closed(self, api):
        """PRD §3.6: "Step one selects the lines: every `SHIPPED` lot of the
        contract with `ship_date` inside the inclusive period, ordered by
        `pack_date` ascending with `created_at` ascending as the tie-break"
        PRD §3.6: "Every covered lot cascades from `SHIPPED` to `CLOSED`, each
        lot's `version` incrementing by 1, and the settlement's own `version`
        increments by 1."

        Design: Difficulty/combinatorial_formula/settlement_rebate_tier_keyed_on_pre_rebate_subtotal
        """
        ctx = self._setup_rebate_settlement(api)
        finalized = validate_success(
            api.finalize_settlement(ctx["settlement"]["id"], CONTRACT_MANAGER)
        )
        lines = finalized["lines"]
        assert len(lines) == 2
        # Both lots share pack_date 2026-07-24; creation order puts JUMBO first.
        assert lines[0]["size_class"] == "JUMBO"
        assert lines[0]["price_cents_per_dozen"] == 174
        assert lines[0]["line_amount_cents"] == 13920
        assert lines[1]["size_class"] == "LARGE"
        assert lines[1]["price_cents_per_dozen"] == 145
        assert lines[1]["line_amount_cents"] == 87000

        assert finalized["status"] == "FINALIZED"
        for lot in ctx["lots"]:
            refreshed = validate_success(api.get_lot(lot["id"], QA_MANAGER))
            assert refreshed["lifecycle_status"] == "CLOSED", (
                "finalize cascades every covered lot SHIPPED -> CLOSED"
            )


class TestSettlementGates:
    def test_finalize_empty_settlement_rejected(self, api):
        """PRD §3.6: "The contract must be `ACTIVE`, else
        `ERR_CONTRACT_INACTIVE` (HTTP 409), and there must be at least one
        `SHIPPED` lot of the contract whose `ship_date` falls within the
        inclusive period, else `ERR_SETTLEMENT_EMPTY` (HTTP 422)."

        Design: Corner/validations/finalize_empty_settlement_rejected
        """
        farm = setup_farm()
        contract = setup_active_contract(farm["id"], max_open_dozen=100)
        settlement = create_draft_settlement(
            contract["id"], "2026-07-27", "2026-08-02", market_index_cents=140
        )
        resp = api.finalize_settlement(settlement["id"], CONTRACT_MANAGER)
        validate_error(resp, ApiErrorId.ERR_SETTLEMENT_EMPTY)
        assert get_settlement(settlement["id"])["status"] == "DRAFT"

    def test_occ_stale_contract_version_on_settlement_create(self, api):
        """PRD §2.7: "The request must include `expected_contract_version`, a
        non-optional integer carrying the `version` of the target
        `RetailerContract` as last observed by the client."
        PRD §2.7: "If the contract's current `version` has advanced beyond
        that observation — for example because another writer created a
        settlement for an overlapping period (which legitimately supersedes
        the prior draft), or allocated or shipped lots against the contract —
        the create is rejected with `ERR_STALE_VERSION` (HTTP 412)"
        PRD §3.6: "Creating a settlement also increments the parent contract's
        `version` by 1, which is precisely what makes a stale
        `expected_contract_version` detectable."

        Design: Corner/complexity_layers/occ_stale_contract_version_on_settlement_create
        """
        farm = setup_farm()
        contract = setup_active_contract(farm["id"], max_open_dozen=100)
        observed_version = get_contract(contract["id"])["version"]
        s1 = validate_success(
            api.create_settlement(
                settlement_payload(
                    contract["id"],
                    observed_version,
                    period_start="2026-07-27",
                    period_end="2026-08-02",
                    market_index_cents=140,
                ),
                CONTRACT_MANAGER,
            ),
            201,
        )
        assert get_contract(contract["id"])["version"] > observed_version, (
            "creating the first settlement must bump the contract version"
        )

        resp = api.create_settlement(
            settlement_payload(
                contract["id"],
                observed_version,  # stale after S1's version bump
                period_start="2026-08-03",
                period_end="2026-08-09",
                market_index_cents=141,
            ),
            CONTRACT_MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
        assert get_settlement(s1["id"])["status"] == "DRAFT", (
            "a rejected create must not supersede the existing DRAFT"
        )
