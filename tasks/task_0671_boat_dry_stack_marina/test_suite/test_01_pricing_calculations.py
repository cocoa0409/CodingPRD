"""Pricing & fee calculations: dual-variant storage invoices, launch fee
composition, service totals, seasonal proration, and oversize boundary.

Difficulty queue: dual_variant_calc, combinatorial_formula, boundary_precision_check.
Corner queue: calculations.* instances.
"""
import pytest

from test_helpers import (
    api_client, validate_success, get_success_data,
    setup_active_agreement, setup_racked_vessel_with_forklift,
    setup_owner_and_vessel, create_launch, issue_invoice, create_service_order,
    TEST_USERS,
)

BC = TEST_USERS["billing_clerk_headers"]
DM = TEST_USERS["dock_master_headers"]


class TestDualVariantStorageInvoice:
    """A PROVISIONAL invoice bills the full seasonal monthly; a FINAL invoice for
    the same agreement prorates by occupancy days. Same agreement, two algorithms."""

    def _active_large_oversize(self):
        # LARGE rack max_loa 40.00, vessel loa 39.60 (gap 0.40 <= 0.5 -> oversize):
        # monthly_base_cents = round_half_up(52500 * 1.15) = 60375.
        ctx = setup_active_agreement(
            rack_overrides={"bay_label": "L-1", "size_class": "LARGE",
                            "max_loa_ft": 40.00, "max_beam_ft": 14.00,
                            "max_weight_lbs": 12000},
            vessel_overrides={"name": "BigBoat", "loa_ft": 39.60,
                              "beam_ft": 13.00, "dry_weight_lbs": 6000})
        # Move to July so the seasonal peak multiplier (1.20) applies.
        get_success_data(api_client.set_clock("2026-07-10T00:00:00Z", BC))
        return ctx

    def test_provisional_storage_invoice_bills_full_seasonal_monthly(self, api):
        """PRD §3.7: "The provisional variant (variant PROVISIONAL), issued at the
        start of a period, is forward-looking: it assumes the vessel stays the whole
        month and bills the full seasonal monthly amount, ignoring period_end."
        PRD §3.7: "months May through September inclusive (month 5 through month 9)
        are peak and carry a multiplier of 1.20"

        Design: Difficulty/dual_variant_calc/provisional_vs_final_storage_invoice
        """
        ctx = self._active_large_oversize()
        inv = issue_invoice(ctx["owner"]["id"], "STORAGE_AGREEMENT",
                            ctx["agreement"]["id"], variant="PROVISIONAL",
                            period_start="2026-07-01T00:00:00Z",
                            period_end="2026-08-01T00:00:00Z")
        assert inv["amount_cents"] == 72450, \
            f"PROVISIONAL July (60375 * 1.20) should be 72450, got {inv['amount_cents']}"

    def test_final_storage_invoice_prorates_by_occupancy_days(self, api):
        """PRD §3.7: "The final variant (variant FINAL), issued at period close, is
        chronological and prorated: it multiplies the seasonal monthly amount by the
        billable days divided by the number of days in the month of period_start,
        rounded half up to whole cents."
        PRD §3.7: "The billable-days count is the inclusive day span across the
        half-open period from period_start up to but not including period_end."

        Design: Difficulty/dual_variant_calc/provisional_vs_final_storage_invoice
        """
        ctx = self._active_large_oversize()
        inv = issue_invoice(ctx["owner"]["id"], "STORAGE_AGREEMENT",
                            ctx["agreement"]["id"], variant="FINAL",
                            period_start="2026-07-10T00:00:00Z",
                            period_end="2026-07-25T00:00:00Z")
        # round_half_up(72450 * 15 / 31) = round_half_up(35056.45) = 35056.
        assert inv["amount_cents"] == 35056, \
            f"FINAL 15/31 July should be 35056, got {inv['amount_cents']}"

    def test_provisional_minus_final_is_proration_delta(self, api):
        """PRD §3.7: "The difference between the provisional amount and the final
        amount is the proration credit delta."

        Design: Difficulty/dual_variant_calc/provisional_vs_final_storage_invoice
        """
        ctx = self._active_large_oversize()
        prov = issue_invoice(ctx["owner"]["id"], "STORAGE_AGREEMENT",
                             ctx["agreement"]["id"], variant="PROVISIONAL",
                             period_start="2026-07-01T00:00:00Z",
                             period_end="2026-08-01T00:00:00Z")
        final = issue_invoice(ctx["owner"]["id"], "STORAGE_AGREEMENT",
                              ctx["agreement"]["id"], variant="FINAL",
                              period_start="2026-07-10T00:00:00Z",
                              period_end="2026-07-25T00:00:00Z")
        assert prov["amount_cents"] - final["amount_cents"] == 37394, \
            "proration delta 72450 - 35056 should be 37394"


class TestWaitlistPriorityReadBasis:
    """priority_score is recomputed against the logical clock AT READ TIME, so a
    later read of the same entry yields a higher days-waiting score."""

    def _entry_joined_at_april_1(self):
        from test_helpers import join_waitlist
        marina, owner, vessel = setup_owner_and_vessel(
            clock="2026-04-01T00:00:00Z",
            vessel_overrides={"loa_ft": 20.00, "beam_ft": 8.00, "dry_weight_lbs": 3000})
        entry = join_waitlist(vessel["id"], owner["id"],
                              requested_size_class="SMALL", deposit_paid=False)
        return owner, entry

    def test_priority_score_three_at_three_days(self, api):
        """PRD §3.4: "The entry's days-waiting is the whole number of days between
        its joined_at and the logical clock - computed as the elapsed seconds
        divided by 86400 and then floored to a whole number of days."
        PRD §3.4: "Reading a single waitlist entry or listing the waitlist
        recomputes priority_score against the logical clock at read time, so a later
        read of the same entry yields a higher score as more whole days accrue."

        Design: Difficulty/dual_variant_calc/waitlist_priority_read_vs_promotion_basis
        """
        owner, entry = self._entry_joined_at_april_1()
        get_success_data(api_client.set_clock("2026-04-04T00:00:00Z", DM))
        from test_helpers import make_boat_owner_headers
        read = validate_success(
            api.get_waitlist_entry(entry["id"], make_boat_owner_headers(owner["id"])), 200)
        assert read["priority_score"] == 3, \
            f"3 whole days waited (deposit false) -> 3, got {read['priority_score']}"

    def test_priority_score_seven_at_seven_days(self, api):
        """PRD §3.4: "The priority_score is that days-waiting count plus a deposit
        bonus of 100000 when deposit_paid is true (and zero when it is false)."
        PRD §3.4: "a later read of the same entry yields a higher score as more
        whole days accrue."

        Design: Difficulty/dual_variant_calc/waitlist_priority_read_vs_promotion_basis
        """
        owner, entry = self._entry_joined_at_april_1()
        get_success_data(api_client.set_clock("2026-04-08T00:00:00Z", DM))
        from test_helpers import make_boat_owner_headers
        read = validate_success(
            api.get_waitlist_entry(entry["id"], make_boat_owner_headers(owner["id"])), 200)
        assert read["priority_score"] == 7, \
            f"7 whole days waited (deposit false) -> 7, got {read['priority_score']}"


class TestLaunchFeeComposition:
    """launch_fee = base + per-foot(ceil loa) + heavy surcharge + splash."""

    def test_launch_fee_heavy_and_splash_combined(self, api):
        """PRD §3.5: "The base is 4500 cents. The per-foot component is 250 cents
        multiplied by the vessel's loa_ft rounded up to the next whole foot. A heavy
        surcharge of 3000 cents applies when the vessel's dry_weight_lbs is strictly
        greater than 8000 pounds, and is zero otherwise. A splash fee of 6000 cents
        applies when with_valet_splash is true, and is zero otherwise."

        Design: Difficulty/combinatorial_formula/launch_fee_nonlinear_heavy_and_splash
        """
        ctx = setup_racked_vessel_with_forklift(
            vessel_overrides={"name": "Heavy", "loa_ft": 28.20,
                              "beam_ft": 10.00, "dry_weight_lbs": 9000},
            rack_overrides={"bay_label": "M-1", "size_class": "MEDIUM",
                            "max_loa_ft": 30.00, "max_beam_ft": 11.00,
                            "max_weight_lbs": 10000})
        launch = create_launch(ctx["vessel"]["id"], ctx["owner"]["id"],
                               with_valet_splash=True)
        scheduled = validate_success(api.schedule_launch(launch["id"], DM), 200)
        # 4500 + 250*ceil(28.20)=250*29=7250 + 3000 (9000>8000) + 6000 = 20750.
        assert scheduled["launch_fee_cents"] == 20750, \
            f"expected 20750, got {scheduled['launch_fee_cents']}"
        assert scheduled["status"] == "SCHEDULED"

    def test_launch_fee_heavy_only_no_splash(self, api):
        """PRD §3.5: "A heavy surcharge of 3000 cents applies when the vessel's
        dry_weight_lbs is strictly greater than 8000 pounds, and is zero otherwise. A
        splash fee of 6000 cents applies when with_valet_splash is true, and is zero
        otherwise. The launch_fee_cents is the sum of those four parts"

        Design: Difficulty/combinatorial_formula/launch_fee_nonlinear_heavy_and_splash
        """
        # Heavy branch ON (9000 > 8000), splash branch OFF: isolates the two branches.
        ctx = setup_racked_vessel_with_forklift(
            vessel_overrides={"name": "HeavyDry", "loa_ft": 28.20,
                              "beam_ft": 10.00, "dry_weight_lbs": 9000})
        launch = create_launch(ctx["vessel"]["id"], ctx["owner"]["id"],
                               with_valet_splash=False)
        scheduled = validate_success(api.schedule_launch(launch["id"], DM), 200)
        # 4500 + 250*ceil(28.20)=7250 + 3000 (heavy) + 0 (no splash) = 14750.
        assert scheduled["launch_fee_cents"] == 14750, \
            f"expected 14750, got {scheduled['launch_fee_cents']}"

    def test_launch_fee_heavy_surcharge_excluded_at_exactly_8000(self, api):
        """PRD §3.5: "A heavy surcharge of 3000 cents applies when the vessel's
        dry_weight_lbs is strictly greater than 8000 pounds, and is zero otherwise."

        Design: Corner/calculations/launch_fee_heavy_boundary_at_8000_lbs
        """
        ctx = setup_racked_vessel_with_forklift(
            vessel_overrides={"name": "Edge8000", "loa_ft": 28.00,
                              "beam_ft": 9.00, "dry_weight_lbs": 8000})
        launch = create_launch(ctx["vessel"]["id"], ctx["owner"]["id"])
        scheduled = validate_success(api.schedule_launch(launch["id"], DM), 200)
        # 4500 + 250*28 = 11500, no heavy surcharge at exactly 8000 (strict >).
        assert scheduled["launch_fee_cents"] == 11500, \
            f"expected 11500 (no surcharge at 8000), got {scheduled['launch_fee_cents']}"


class TestServiceTotal:
    """ServiceOrder.total_cents per service kind; FUEL is round-per-line."""

    def test_fuel_total_round_per_line(self, api):
        """PRD §3.6: "For a FUEL order it is the single fuel line - fuel_gallons
        multiplied by fuel_price_cents_per_gal - rounded half up to whole cents (the
        per-line round); because there is exactly one line, the total equals that
        rounded line."

        Design: Difficulty/combinatorial_formula/service_total_fuel_round_per_line_then_sum
        """
        marina, owner, vessel = setup_owner_and_vessel(
            vessel_overrides={"name": "Fueler", "loa_ft": 22.00,
                              "beam_ft": 8.50, "dry_weight_lbs": 4000})
        so = create_service_order(vessel["id"], owner["id"], "FUEL",
                                  fuel_gallons=15.250, fuel_price_cents_per_gal=712)
        # round_half_up(15.250 * 712) = round_half_up(10858.0) = 10858.
        assert so["total_cents"] == 10858, \
            f"expected 10858, got {so['total_cents']}"

    def test_winterization_flat_total(self, api):
        """PRD §3.6: "For WINTERIZATION the total is 25000 cents."

        Design: Difficulty/combinatorial_formula/service_total_fuel_round_per_line_then_sum
        """
        marina, owner, vessel = setup_owner_and_vessel()
        so = create_service_order(vessel["id"], owner["id"], "WINTERIZATION")
        assert so["total_cents"] == 25000, \
            f"WINTERIZATION total should be 25000, got {so['total_cents']}"


class TestOversizeBandBoundary:
    """Oversize surcharge at exactly the 0.5 ft band boundary."""

    def test_oversize_surcharge_applied_at_exactly_half_foot_gap(self, api):
        """PRD §3.3: "An oversize surcharge applies when the vessel is nearly as
        long as the rack permits: specifically, when the rack's max_loa_ft minus the
        vessel's loa_ft is at most half a foot (0.5 ft), the vessel is within the
        oversize band."
        PRD §3.3: "When within the band, monthly_base_cents is the base multiplied
        by 1.15 (a fifteen-percent surcharge), rounded half up to whole cents, and
        oversize_surcharge_applied is set true"

        Design: Difficulty/boundary_precision_check/oversize_band_exactly_half_foot
        """
        ctx = setup_active_agreement(
            rack_overrides={"bay_label": "L-1", "size_class": "LARGE",
                            "max_loa_ft": 40.00, "max_beam_ft": 14.00,
                            "max_weight_lbs": 12000},
            vessel_overrides={"name": "EdgeBoat", "loa_ft": 39.50,
                              "beam_ft": 13.00, "dry_weight_lbs": 6000})
        agr = ctx["agreement"]
        # gap 40.00 - 39.50 = 0.50 exactly -> within band; 52500*1.15 = 60375.
        assert agr["oversize_surcharge_applied"] is True, \
            "0.50 ft gap is within the band (<= 0.5)"
        assert agr["monthly_base_cents"] == 60375, \
            f"expected 60375, got {agr['monthly_base_cents']}"

    def test_no_oversize_surcharge_when_gap_exceeds_band(self, api):
        """PRD §3.3: "otherwise monthly_base_cents is exactly the base and
        oversize_surcharge_applied is false."

        Design: Difficulty/boundary_precision_check/oversize_band_exactly_half_foot
        """
        # MEDIUM base 35000, gap 30.00 - 25.00 = 5.0 > 0.5 -> no surcharge.
        ctx = setup_active_agreement(
            rack_overrides={"bay_label": "M-1", "size_class": "MEDIUM",
                            "max_loa_ft": 30.00, "max_beam_ft": 11.00,
                            "max_weight_lbs": 10000},
            vessel_overrides={"loa_ft": 25.00, "beam_ft": 9.00, "dry_weight_lbs": 5000})
        agr = ctx["agreement"]
        assert agr["oversize_surcharge_applied"] is False
        assert agr["monthly_base_cents"] == 35000, \
            f"MEDIUM base should be exactly 35000, got {agr['monthly_base_cents']}"


class TestSeasonalOffPeakProration:
    """OFF-season FINAL invoice (multiplier 1.00) prorated by occupancy days."""

    def test_off_season_final_proration_february(self, api):
        """PRD §3.7: "all other months are off-season and carry a multiplier of
        1.00. The seasonal monthly amount is monthly_base_cents multiplied by that
        factor, rounded half up to whole cents."
        PRD §3.7: "it multiplies the seasonal monthly amount by the billable days
        divided by the number of days in the month of period_start, rounded half up
        to whole cents."

        Design: Corner/calculations/seasonal_off_peak_final_proration_february
        """
        # MEDIUM base 35000, no oversize. Feb is off-season (x1.00).
        ctx = setup_active_agreement(
            clock="2026-02-01T00:00:00Z",
            rack_overrides={"bay_label": "M-1", "size_class": "MEDIUM",
                            "max_loa_ft": 30.00, "max_beam_ft": 11.00,
                            "max_weight_lbs": 10000},
            vessel_overrides={"loa_ft": 25.00, "beam_ft": 9.00, "dry_weight_lbs": 5000})
        inv = issue_invoice(ctx["owner"]["id"], "STORAGE_AGREEMENT",
                            ctx["agreement"]["id"], variant="FINAL",
                            period_start="2026-02-15T00:00:00Z",
                            period_end="2026-03-01T00:00:00Z")
        # round_half_up(35000 * 14 / 28) = 17500.
        assert inv["amount_cents"] == 17500, \
            f"expected 17500, got {inv['amount_cents']}"
