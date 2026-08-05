"""Dynamic pricing: estimate vs settled, combinatorial factor interaction, surge boundary.

Covers difficulty queue A: dual_variant_calc (reservation), combinatorial_formula
(pricing mode a), boundary_precision_check (surge ratio >= 0.80).
"""
from test_helpers import (
    validate_success,
    make_permittee_headers,
    setup_active_permit,
    make_confirmed_reservation,
    make_reservation,
    confirm_reservation,
    record_occupancy,
    fetch_ledger_entries,
    ledger_entries_for_reservation,
    ledger_entries_of_type,
)


class TestEstimateVsSettled:
    """A reservation's ESTIMATE at confirm diverges from its SETTLED price at fulfill."""

    def test_settled_recomputes_from_observed_minutes(self, api):
        """PRD §3.4: "At confirmation the estimate variant uses the booked duration
        — the minutes between start_utc and end_utc — and stamps estimated_price_cents
        and surge_ratio_bps. At fulfillment the settled variant recomputes the price
        from the actually observed minutes (see 3.5) while reusing the very same
        surge_ratio_bps that was stamped at confirmation, and stamps settled_price_cents."

        Design: Difficulty/dual_variant_calc/reservation_estimate_vs_settled
        """
        ctx = setup_active_permit(api)
        res = make_confirmed_reservation(
            api, ctx["permit_id"], ctx["permittee_id"], ctx["zone_id"],
            "2026-06-01T08:00:00Z", "2026-06-01T08:45:00Z")
        assert res["estimated_price_cents"] == 900, "45 booked min -> 3 slots @1.5x peak @200 = 900"

        # Observed 62 minutes: entered 08:00, exited 09:02.
        sess = record_occupancy(
            api, ctx["zone_id"], res["id"], "2026-06-01T08:00:00Z", "2026-06-01T09:02:00Z")
        assert sess["actual_minutes"] == 62

        fulfilled = validate_success(
            api.fulfill_reservation(res["id"], make_permittee_headers(ctx["permittee_id"])))
        assert fulfilled["booking_status"] == "FULFILLED"
        assert fulfilled["settled_price_cents"] == 1500, "62 observed min -> 5 slots @1.5x @200 = 1500"

    def test_settlement_delta_booked_as_adjustment_ledger_entry(self, api):
        """PRD §3.5: "If the settled price differs from the previously stamped
        estimated_price_cents, a ledger ADJUSTMENT entry is appended whose amount_cents
        is the settled price minus the estimated price (positive when the settlement is
        higher, negative when lower); if the two are equal, no adjustment entry is written."

        Design: Difficulty/dual_variant_calc/reservation_estimate_vs_settled
        """
        ctx = setup_active_permit(api)
        res = make_confirmed_reservation(
            api, ctx["permit_id"], ctx["permittee_id"], ctx["zone_id"],
            "2026-06-01T08:00:00Z", "2026-06-01T08:45:00Z")
        record_occupancy(
            api, ctx["zone_id"], res["id"], "2026-06-01T08:00:00Z", "2026-06-01T09:02:00Z")
        validate_success(
            api.fulfill_reservation(res["id"], make_permittee_headers(ctx["permittee_id"])))

        entries = fetch_ledger_entries(api, params={"reservation_id": res["id"]})
        adjustments = ledger_entries_of_type(entries, "ADJUSTMENT")
        assert len(adjustments) == 1, "exactly one ADJUSTMENT expected (settled 1500 != estimate 900)"
        assert adjustments[0]["amount_cents"] == 600, "settled 1500 - estimate 900 = 600"


class TestCombinatorialPricing:
    """The estimate combines slots x time-of-use x tiered surge non-linearly."""

    def _setup_five_on_peak_window(self, api):
        ctx = setup_active_permit(api)
        ids = []
        # Confirm four reservations sharing the peak window [08:00,08:45) on a cap-5 zone.
        for _ in range(4):
            r = make_confirmed_reservation(
                api, ctx["permit_id"], ctx["permittee_id"], ctx["zone_id"],
                "2026-06-01T08:00:00Z", "2026-06-01T08:45:00Z")
            ids.append(r)
        # Fifth reservation stays PENDING until the trigger.
        r5 = make_reservation(
            api, ctx["permit_id"], ctx["permittee_id"], ctx["zone_id"],
            "2026-06-01T08:00:00Z", "2026-06-01T08:45:00Z")
        return ctx, ids, r5

    def test_fifth_confirm_stacks_peak_and_tier2_surge(self, api):
        """PRD §3.4: "The price in cents is the base multiplied by the slot count,
        multiplied by the time-of-use factor, multiplied by the surge factor, divided
        by 10000 twice (once for each basis-point factor), and rounded half-up to a
        whole number of cents."

        Design: Difficulty/combinatorial_formula/reservation_price_tiered_tou_surge_mode_a
        """
        ctx, _confirmed, r5 = self._setup_five_on_peak_window(api)
        confirmed5 = confirm_reservation(api, r5["id"], ctx["permittee_id"])
        assert confirmed5["surge_ratio_bps"] == 8000, "overlap 4 / cap 5 = 0.80 -> 8000 bps"
        # base 200 * 3 slots * 1.5 peak * 1.5 tier2 = 1350
        assert confirmed5["estimated_price_cents"] == 1350

    def test_changing_the_surge_factor_changes_the_price(self, api):
        """PRD §3.4: "If that ratio is at or above surge_tier2_ratio_bps the surge factor
        is surge_tier2_mult_bps; otherwise if it is at or above surge_tier1_ratio_bps the
        surge factor is surge_tier1_mult_bps; otherwise the surge factor is 10000 basis points."

        Design: Difficulty/combinatorial_formula/reservation_price_tiered_tou_surge_mode_a
        """
        ctx, confirmed, _r5 = self._setup_five_on_peak_window(api)
        # The 4th confirmed reservation saw overlap 3 -> ratio 0.60 -> tier1 (1.25x).
        r4 = confirmed[3]
        # base 200 * 3 slots * 1.5 peak * 1.25 tier1 = 1125 (differs from tier2's 1350)
        assert r4["estimated_price_cents"] == 1125
        assert r4["surge_ratio_bps"] == 6000


class TestSurgeRatioBoundary:
    """Occupancy ratio exactly 0.80 uses >= and selects tier2."""

    def _setup_offpeak_four_confirmed(self, api):
        ctx = setup_active_permit(api)
        confirmed = []
        for _ in range(4):
            r = make_confirmed_reservation(
                api, ctx["permit_id"], ctx["permittee_id"], ctx["zone_id"],
                "2026-06-01T12:00:00Z", "2026-06-01T12:15:00Z")
            confirmed.append(r)
        r5 = make_reservation(
            api, ctx["permit_id"], ctx["permittee_id"], ctx["zone_id"],
            "2026-06-01T12:00:00Z", "2026-06-01T12:15:00Z")
        return ctx, confirmed, r5

    def test_ratio_at_080_selects_tier2(self, api):
        """PRD §3.4: "If that ratio is at or above surge_tier2_ratio_bps the surge
        factor is surge_tier2_mult_bps; otherwise if it is at or above
        surge_tier1_ratio_bps the surge factor is surge_tier1_mult_bps; otherwise the
        surge factor is 10000 basis points."

        Design: Difficulty/boundary_precision_check/surge_ratio_ge_080_triggers_tier2
        """
        ctx, _confirmed, r5 = self._setup_offpeak_four_confirmed(api)
        confirmed5 = confirm_reservation(api, r5["id"], ctx["permittee_id"])
        assert confirmed5["surge_ratio_bps"] == 8000, "overlap 4 / cap 5 = 0.80"
        # offpeak: base 200 * 1 slot * 1.0 tou * 1.5 tier2 = 300
        assert confirmed5["estimated_price_cents"] == 300

    def test_ratio_at_060_selects_tier1_below_boundary(self, api):
        """PRD §3.4: "the system counts the other CONFIRMED reservations on the zone
        whose windows overlap this one (excluding the reservation being priced),
        multiplies that count by 10000, divides by the zone's capacity_slots, and rounds
        down to a whole number of basis points to obtain the occupancy ratio."

        Design: Difficulty/boundary_precision_check/surge_ratio_ge_080_triggers_tier2
        """
        ctx, confirmed, _r5 = self._setup_offpeak_four_confirmed(api)
        # 4th confirmed saw overlap 3 -> 0.60 -> tier1 (1.25x); below the 0.80 boundary.
        r4 = confirmed[3]
        assert r4["surge_ratio_bps"] == 6000
        # offpeak: base 200 * 1 slot * 1.0 tou * 1.25 tier1 = 250
        assert r4["estimated_price_cents"] == 250
