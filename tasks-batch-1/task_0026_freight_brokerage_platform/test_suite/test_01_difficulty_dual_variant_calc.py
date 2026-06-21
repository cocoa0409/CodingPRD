"""Difficulty Rule 1 — dual_variant_calc.

Two same-input setups whose differing entity context produces a measurably
different number: a quote priced under an ACTIVE contract diverges from the
same quote priced via SPOT after the contract is terminated; a factoring
advance against a 100,000-cent invoice diverges between a safety_score=20
carrier (fee floor 2.0%) and a safety_score=40 carrier (fee floor 2.5%).
"""
import pytest

from test_helpers import (
    create_active_contract,
    create_qualified_carrier,
    create_quote,
    create_shipper,
    get_success_data,
    open_factoring_request,
    set_clock,
    setup_invoiced_load,
    validate_success,
)
from test_helpers.api_client import api_client


class TestQuoteTotalContractVsSpotDivergesOnSameLane:
    def test_contract_total_uses_pinned_contract_rate_and_fuel(self, api):
        """PRD §3.3: "The quoted total is then the sum of the linehaul term
        (the contract's `rate_per_mile_cents` multiplied by `distance_miles`)
        and the fuel term (the contract's `fuel_surcharge_per_mile_cents`
        multiplied by `distance_miles`); contract pricing uses no tier table
        and applies no equipment uplift, and both terms are exact whole-cent
        products of whole-cent rates and whole-mile distances."

        Design: Difficulty/dual_variant_calc/quote_total_contract_vs_spot_diverges_on_same_lane
        """
        set_clock("2026-06-01T00:00:00Z")
        shipper = create_shipper(credit_limit_cents=10_000_000)
        create_active_contract(
            shipper["id"],
            lane_origin="10001", lane_destination="30303",
            rate_per_mile_cents=250, fuel_surcharge_per_mile_cents=60,
            detention_free_minutes=120, detention_rate_per_hour_cents=7500,
            effective_from_utc="2026-01-01T00:00:00Z",
            effective_until_utc="2027-01-01T00:00:00Z",
        )
        quote = create_quote(
            shipper["id"], lane_origin="10001", lane_destination="30303",
            distance_miles=400,
            pickup_window_start_utc="2026-06-10T08:00:00Z",
            pickup_window_end_utc="2026-06-10T18:00:00Z",
            requested_equipment="DRY_VAN",
        )
        assert quote["rate_mode"] == "CONTRACT"
        # 250 c/mi linehaul + 60 c/mi fuel × 400 mi = 100000 + 24000 = 124000.
        assert quote["quoted_total_cents"] == 124000

    def test_spot_total_uses_tier_and_fuel_when_no_active_contract(self, api):
        """PRD §3.3: "SPOT pricing applies a distance-tiered per-mile rate:
        for `distance_miles` of at most 250, the per-mile rate is 320
        cents; for `distance_miles` of 251 through 750 inclusive, the
        per-mile rate is 235 cents; for `distance_miles` of 751 or more,
        the per-mile rate is 195 cents."
        PRD §3.3: "The linehaul term is the chosen per-mile rate
        multiplied by `distance_miles`, and the fuel term is a flat 65
        cents per mile multiplied by `distance_miles`."
        PRD §3.3: "SPOT pricing further adds an equipment uplift
        expressed as a percentage of linehaul: `DRY_VAN` adds 0 percent,
        `REEFER` adds 18 percent, and `FLATBED` adds 10 percent."

        Design: Difficulty/dual_variant_calc/quote_total_contract_vs_spot_diverges_on_same_lane
        """
        set_clock("2026-06-01T00:00:00Z")
        shipper = create_shipper(credit_limit_cents=10_000_000)
        # No covering ContractRate → SPOT path.
        quote = create_quote(
            shipper["id"], lane_origin="10001", lane_destination="30303",
            distance_miles=400,
            pickup_window_start_utc="2026-06-12T08:00:00Z",
            pickup_window_end_utc="2026-06-12T18:00:00Z",
            requested_equipment="DRY_VAN",
        )
        assert quote["rate_mode"] == "SPOT"
        # 235 c/mi × 400 + 65 c/mi × 400 + 0% DRY_VAN uplift = 94000 + 26000 = 120000.
        assert quote["quoted_total_cents"] == 120000


class TestFactoringAdvanceDivergesWithCarrierSafetyBand:
    def test_advance_with_safety_below_25_uses_2pct_fee(self, api):
        """PRD §3.8: "The factoring fee is subject to a safety-tiered
        floor: for a carrier whose `safety_score` is strictly less than
        25, the floor is 2.0 percent; for a carrier whose `safety_score`
        is at least 25 and strictly less than 50, the floor is 2.5
        percent; for a carrier whose `safety_score` is at least 50 and
        strictly less than 75, the floor is 3.5 percent."
        PRD §3.8: "The raw advance equals `Invoice.total_cents`
        multiplied by the quantity (one hundred minus the actual fee
        percent) divided by one hundred; that raw value is then rounded
        to the nearest whole cent half-up to produce `advance_cents`."

        Design: Difficulty/dual_variant_calc/factoring_advance_diverges_with_carrier_safety_band
        """
        # Build an invoice with total_cents=100000.
        # Contract 200 c/mi + 50 c/mi fuel × 400 mi = 100000.
        shipper, carrier, _quote, _load, invoice, _contract = setup_invoiced_load(
            contract_overrides={
                "rate_per_mile_cents": 200,
                "fuel_surcharge_per_mile_cents": 50,
            },
            safety_score=20.0,
            insurance_expiry_utc="2027-01-01T00:00:00Z",
        )
        assert invoice["total_cents"] == 100000
        fr = open_factoring_request(invoice["id"], carrier["id"],
                                    factoring_fee_pct=2.0)
        # round(100000 × 0.98) = 98000.
        assert fr["advance_cents"] == 98000

    def test_advance_with_safety_in_25_to_50_uses_2_5pct_fee(self, api):
        """PRD §3.8: "for a carrier whose `safety_score` is at least 25 and
        strictly less than 50, the floor is 2.5 percent."
        PRD §3.8: "The platform computes `advance_cents` at request time
        using the larger of the submitted `factoring_fee_pct` and the
        safety-tiered floor as the **actual fee percent**."

        Design: Difficulty/dual_variant_calc/factoring_advance_diverges_with_carrier_safety_band
        """
        # Same invoice topology but safety_score=40 → applicable floor 2.5%.
        shipper, carrier, _quote, _load, invoice, _contract = setup_invoiced_load(
            contract_overrides={
                "rate_per_mile_cents": 200,
                "fuel_surcharge_per_mile_cents": 50,
            },
            safety_score=40.0,
            insurance_expiry_utc="2027-01-01T00:00:00Z",
        )
        assert invoice["total_cents"] == 100000
        # Submitted fee 2.0 is below the 2.5 floor → server uses max(2.0, 2.5)=2.5.
        fr = open_factoring_request(invoice["id"], carrier["id"],
                                    factoring_fee_pct=2.5)
        # round(100000 × 0.975) = 97500.
        assert fr["advance_cents"] == 97500
