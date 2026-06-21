"""Difficulty Rule 2 — combinatorial_formula.

Formulas whose result depends on ≥3 interacting inputs branched non-linearly.
Case A: SPOT pricing combines (distance band) × (fuel constant) × (equipment
uplift with leaf-rounding). Case B: detention math whose ordering of
subtract→ceil→multiply is observably different from any other ordering.
"""
import pytest

from test_helpers import (
    create_shipper,
    deliver_load,
    set_clock,
    setup_awarded_load,
)


class TestQuoteTotalSpotCombinesTierFuelUpliftModeA:
    def test_spot_reefer_800_miles_combines_tier3_fuel_and_18pct_uplift(self, api):
        """PRD §3.3: "for `distance_miles` of 751 or more, the per-mile rate
        is 195 cents. The linehaul term is the chosen per-mile rate
        multiplied by `distance_miles`, and the fuel term is a flat 65 cents
        per mile multiplied by `distance_miles`. SPOT pricing further adds
        an equipment uplift expressed as a percentage of linehaul: `DRY_VAN`
        adds 0 percent, `REEFER` adds 18 percent, and `FLATBED` adds 10
        percent. The uplift is rounded to the nearest whole cent half-up
        before being summed into `quoted_total_cents`."

        Design: Difficulty/combinatorial_formula/quote_total_spot_combines_tier_fuel_uplift_mode_a
        """
        from test_helpers import create_quote
        set_clock("2026-06-01T00:00:00Z")
        shipper = create_shipper(credit_limit_cents=500_000_000)
        quote = create_quote(
            shipper["id"], lane_origin="94101", lane_destination="10001",
            distance_miles=800,
            pickup_window_start_utc="2026-06-15T08:00:00Z",
            pickup_window_end_utc="2026-06-15T18:00:00Z",
            requested_equipment="REEFER",
        )
        # tier3=195 c/mi × 800 = 156000; fuel=65 × 800 = 52000;
        # uplift=round(156000 × 0.18)=28080. Total=156000+52000+28080=236080.
        assert quote["rate_mode"] == "SPOT"
        assert quote["quoted_total_cents"] == 236080

    def test_spot_pricing_branches_on_equipment_within_same_distance_band(self, api):
        """PRD §3.3: "SPOT pricing further adds an equipment uplift expressed
        as a percentage of linehaul: `DRY_VAN` adds 0 percent, `REEFER` adds
        18 percent, and `FLATBED` adds 10 percent."

        Verifying the multi-input branch by holding distance constant and
        flipping equipment: the resulting quoted_total must include the
        per-equipment uplift component.

        Design: Difficulty/combinatorial_formula/quote_total_spot_combines_tier_fuel_uplift_mode_a
        """
        from test_helpers import create_quote
        set_clock("2026-06-01T00:00:00Z")
        shipper = create_shipper(credit_limit_cents=500_000_000)
        # Same distance band as tier 3 (800 mi), FLATBED uplift = 10%.
        # linehaul=195*800=156000; fuel=65*800=52000; uplift=round(156000*0.10)=15600
        # total = 156000 + 52000 + 15600 = 223600
        quote = create_quote(
            shipper["id"], lane_origin="94101", lane_destination="10001",
            distance_miles=800,
            pickup_window_start_utc="2026-06-15T08:00:00Z",
            pickup_window_end_utc="2026-06-15T18:00:00Z",
            requested_equipment="FLATBED",
        )
        assert quote["rate_mode"] == "SPOT"
        assert quote["quoted_total_cents"] == 223600


class TestDetentionSubtractThenCeilOrderMattersModeB:
    def test_detention_subtract_free_then_ceil_yields_15000_for_180min_free_110(self, api):
        """PRD §3.6: "From that raw minute count the platform subtracts a
        free-minute window: for `CONTRACT`-mode quotes, the window is the
        chosen `ContractRate.detention_free_minutes`; for `SPOT`-mode
        quotes, the window is 120 minutes. The result is clipped at zero,
        then converted to whole billable hours by **ceiling** the value
        divided by sixty up to the next whole hour."
        PRD §3.6: "The subtract-then-ceiling order matters: ceiling first
        would silently lose the boundary precision at the edge of the free
        window."

        Design: Difficulty/combinatorial_formula/detention_subtract_then_ceil_order_matters_mode_b
        """
        # CONTRACT mode with detention_free_minutes=110, rate=7500/hr.
        # actual_pickup at pickup_window_start + 3:00 → detention_minutes = 180.
        # Subtract-then-ceil: max(0, 180-110) = 70 → ceil(70/60) = 2 → 2 * 7500 = 15000.
        shipper, carrier, quote, load, contract = setup_awarded_load(
            pickup_window_start_utc="2026-06-10T08:00:00Z",
            pickup_window_end_utc="2026-06-10T18:00:00Z",
            distance_miles=400, requested_equipment="DRY_VAN",
            contract_overrides={
                "rate_per_mile_cents": 250,
                "fuel_surcharge_per_mile_cents": 60,
                "detention_free_minutes": 110,
                "detention_rate_per_hour_cents": 7500,
            },
        )
        delivered = deliver_load(
            load, carrier,
            actual_pickup_at_utc="2026-06-10T11:00:00Z",
            actual_delivery_at_utc="2026-06-11T11:00:00Z",
        )
        assert delivered["detention_charge_cents"] == 15000
        assert delivered["status"] == "DELIVERED"

    def test_detention_zero_when_billable_minutes_zero(self, api):
        """PRD §3.6: "The raw detention minutes at pickup are the wall-clock
        difference between `Load.actual_pickup_at_utc` and the originating
        `QuoteRequest.pickup_window_start_utc`, taken in seconds and divided
        by sixty with the floor — yielding whole minutes — and then clipped
        at zero so that early pickups produce zero detention rather than a
        negative figure."

        Design: Difficulty/combinatorial_formula/detention_subtract_then_ceil_order_matters_mode_b
        """
        # SPOT (free=120): pickup at exactly +30 min → raw minutes=30 → less than
        # the 120 free window → billable=0 → 0 hours × 7500 = 0 cents.
        shipper, carrier, quote, load, _contract = setup_awarded_load(
            pickup_window_start_utc="2026-06-10T08:00:00Z",
            pickup_window_end_utc="2026-06-10T18:00:00Z",
            distance_miles=400, requested_equipment="DRY_VAN",
            use_contract=False,
        )
        delivered = deliver_load(
            load, carrier,
            actual_pickup_at_utc="2026-06-10T08:30:00Z",
            actual_delivery_at_utc="2026-06-11T09:00:00Z",
        )
        assert delivered["detention_charge_cents"] == 0
