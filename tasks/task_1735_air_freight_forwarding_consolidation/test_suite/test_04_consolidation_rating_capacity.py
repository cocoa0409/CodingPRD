"""Consolidation gating, OCC, rating math, spot surcharge, capacity (PRD §2.5-§2.9, §3.4-§3.5)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_money_equal,
    assert_weight_equal,
    clear_hwb,
    consolidate_hwb,
    consolidate_payload,
    create_booking,
    create_hwb,
    create_known_shipper,
    create_mawb,
    create_shipper,
    drive_shipper_to_suspended,
    file_rate_agreement,
    get_booking,
    get_hwb,
    get_mawb,
    list_screening_records,
    open_mawb,
    resolve_screening,
    setup_cleared_hwb,
    setup_consolidated,
    setup_lane,
    set_clock,
    submit_hwb,
    validate_error,
    validate_paginated,
    validate_success,
)

# ---------------------------------------------------------------------------
# Cross-entity state dependency: consolidation requires an open master waybill
# ---------------------------------------------------------------------------


class TestConsolidationRequiresMawbOpen:
    def _setup_draft_mawb_scenario(self):
        shipper = create_known_shipper()
        file_rate_agreement(shipper["id"])
        booking = create_booking()
        mawb = create_mawb(booking["id"])  # deliberately left DRAFT
        hwb = create_hwb(shipper["id"], "HWB-A")
        clear_hwb(hwb["id"])
        return shipper, booking, mawb, hwb

    def test_consolidation_rejected_while_mawb_draft(self, api, forwarder_ops_headers):
        """PRD §3.4: "The target master waybill must be `OPEN_FOR_CONSOLIDATION`;
        otherwise `ERR_MAWB_NOT_OPEN_FOR_CONSOLIDATION`."

        Design: Difficulty/cross_entity_state_dependency/consolidation_requires_mawb_open
        """
        _shipper, _booking, mawb, hwb = self._setup_draft_mawb_scenario()
        version = get_mawb(mawb["id"])["version"]
        resp = api.consolidate_house_waybill(
            mawb["id"], consolidate_payload(hwb["id"], version), forwarder_ops_headers
        )
        validate_error(resp, ApiErrorId.ERR_MAWB_NOT_OPEN_FOR_CONSOLIDATION)
        after = get_hwb(hwb["id"])
        assert after["status"] == "CLEARED"
        assert after["mawb_id"] is None

    def test_consolidation_succeeds_after_open(self, api):
        """PRD §3.4: "A successful consolidation mutates three resources atomically.
        The waybill: `mawb_id` set to the target, `status` to `CONSOLIDATED`,
        `weight_basis` to `QUOTED`, `chargeable_weight_kg` computed from declared
        volume, the spot-surcharge flag decided from the pre-assignment utilization
        snapshot of §3.5 and then locked, all five charge lines computed via the
        selected rate agreement, and `rate_agreement_id` stamped with that agreement."

        Design: Difficulty/cross_entity_state_dependency/consolidation_requires_mawb_open
        """
        _shipper, _booking, mawb, hwb = self._setup_draft_mawb_scenario()
        open_mawb(mawb["id"])
        rated = consolidate_hwb(mawb["id"], hwb["id"])
        assert rated["mawb_id"] == mawb["id"]
        assert rated["status"] == "CONSOLIDATED"
        assert rated["weight_basis"] == "QUOTED"
        # 0.60 m3 / 0.006 = 100.0 kg dimensional beats 80.0 kg gross
        assert_weight_equal(rated["chargeable_weight_kg"], 100.0, "chargeable_weight_kg")
        # 100-kg break: 4.00 x 100.0 = 400.00; fuel 12.5% = 50.00; security 25.00
        assert_money_equal(rated["total_charge_amount"], 475.00, "total_charge_amount")


# ---------------------------------------------------------------------------
# Booking cutoff: system auto-transitions gating consolidation
# ---------------------------------------------------------------------------


class TestBookingCutoff:
    def test_cutoff_auto_close_blocks_consolidation(self, api, forwarder_ops_headers):
        """PRD §2.9: "Advancing the clock eagerly re-evaluates time-driven transitions:
        every booking still `OPEN` whose `cutoff_utc` is at or before the new time
        transitions to `CUTOFF_CLOSED` as part of the same call."
        PRD §2.9: "Once a booking is `CUTOFF_CLOSED`, consolidation into it is refused
        with `ERR_BOOKING_NOT_OPEN`"

        Design: Corner/state_machines/cutoff_auto_close_blocks_consolidation
        """
        ctx = setup_cleared_hwb()
        set_clock("2026-08-09T10:00:00Z")  # exactly the booking's cutoff_utc
        booking = get_booking(ctx["booking"]["id"])
        assert booking["status"] == "CUTOFF_CLOSED", (
            "clock == cutoff_utc is inclusive: the booking must leave OPEN"
        )
        version = get_mawb(ctx["mawb"]["id"])["version"]
        resp = api.consolidate_house_waybill(
            ctx["mawb"]["id"],
            consolidate_payload(ctx["hwb"]["id"], version),
            forwarder_ops_headers,
        )
        validate_error(resp, ApiErrorId.ERR_BOOKING_NOT_OPEN)
        after = get_hwb(ctx["hwb"]["id"])
        assert after["status"] == "CLEARED"
        assert after["mawb_id"] is None

    def test_default_clock_epoch_keeps_booking_open(self, api):
        """PRD §2.9: "Before any test-driving call, the logical clock reads exactly
        `2026-08-01T00:00:00Z` — a fixed startup default, never the wall clock."

        Design: Corner/state_machines/default_clock_epoch_keeps_booking_open
        """
        ctx = setup_cleared_hwb(
            booking_overrides={
                "cutoff_utc": "2026-08-10T10:00:00Z",
                "scheduled_departure_utc": "2026-08-11T10:00:00Z",
            }
        )
        rated = consolidate_hwb(ctx["mawb"]["id"], ctx["hwb"]["id"])
        assert rated["status"] == "CONSOLIDATED", (
            "no clock-set call: the fixed 2026-08-01 epoch precedes the cutoff"
        )
        assert get_booking(ctx["booking"]["id"])["status"] == "OPEN"


# ---------------------------------------------------------------------------
# Optimistic concurrency on the master waybill
# ---------------------------------------------------------------------------


class TestOptimisticConcurrency:
    def test_occ_stale_version_rejected_then_current_succeeds(
        self, api, forwarder_ops_headers
    ):
        """PRD §2.5: "If that value does not equal the master waybill's current
        `version` — because another consolidation or a deconsolidation has since
        advanced it, changing the totals and the attached set the caller based its
        decision on — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and
        nothing is mutated."
        PRD §3.4: "The master waybill: totals recomputed and `version` incremented by
        exactly one."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_version_rejected_then_current_succeeds
        """
        ctx = setup_lane()
        hwb_a = create_hwb(
            ctx["shipper"]["id"], "HWB-A", pieces=1, gross_weight_kg=10.0,
            declared_volume_m3=0.05,
        )
        clear_hwb(hwb_a["id"])
        hwb_b = create_hwb(
            ctx["shipper"]["id"], "HWB-B", pieces=1, gross_weight_kg=10.0,
            declared_volume_m3=0.05,
        )
        clear_hwb(hwb_b["id"])

        version_pre = get_mawb(ctx["mawb"]["id"])["version"]

        rated_a = consolidate_hwb(ctx["mawb"]["id"], hwb_a["id"])
        assert rated_a["status"] == "CONSOLIDATED"

        stale = api.consolidate_house_waybill(
            ctx["mawb"]["id"],
            consolidate_payload(hwb_b["id"], version_pre),
            forwarder_ops_headers,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        mawb_now = get_mawb(ctx["mawb"]["id"])
        assert mawb_now["version"] == version_pre + 1, (
            "one successful consolidation increments the version by exactly one"
        )
        assert_weight_equal(
            mawb_now["total_chargeable_weight_kg"], 10.0, "total_chargeable_weight_kg"
        )

        rated_b = consolidate_hwb(ctx["mawb"]["id"], hwb_b["id"])
        assert rated_b["status"] == "CONSOLIDATED"


# ---------------------------------------------------------------------------
# Immediate consistency of the consolidation side effects
# ---------------------------------------------------------------------------


class TestImmediateConsistency:
    def test_immediate_consistency_consolidate_visible_everywhere(
        self, api, forwarder_ops_headers
    ):
        """PRD §2.10: "Several operations deliberately mutate more than one resource,
        and every cascade is applied immediately and atomically — all side effects are
        visible in the triggering response and in any read issued afterwards."
        PRD §3.4: "The master waybill: totals recomputed and `version` incremented by
        exactly one. The booking: consumption and utilization recomputed per §2.7."

        Design: Corner/consistency_model/immediate_consistency_consolidate_visible_everywhere
        """
        ctx = setup_cleared_hwb()
        version_pre = get_mawb(ctx["mawb"]["id"])["version"]

        rated = consolidate_hwb(ctx["mawb"]["id"], ctx["hwb"]["id"])
        assert rated["status"] == "CONSOLIDATED"
        assert_weight_equal(rated["chargeable_weight_kg"], 100.0, "chargeable_weight_kg")
        assert_money_equal(rated["total_charge_amount"], 475.00, "total_charge_amount")

        mawb_after = get_mawb(ctx["mawb"]["id"])
        assert_weight_equal(
            mawb_after["total_chargeable_weight_kg"], 100.0, "mawb total_chargeable_weight_kg"
        )
        assert_money_equal(
            mawb_after["total_freight_amount"], 475.00, "mawb total_freight_amount"
        )
        assert mawb_after["version"] == version_pre + 1

        booking_after = get_booking(ctx["booking"]["id"])
        assert_weight_equal(
            booking_after["consumed_weight_kg"], 100.0, "consumed_weight_kg"
        )
        assert booking_after["utilization_pct"] == pytest.approx(20.0, abs=1e-6), (
            "100.0 kg of 500 kg booked is the governing ratio (volume 0.60 of 50)"
        )


# ---------------------------------------------------------------------------
# Chargeable weight and tariff selection math
# ---------------------------------------------------------------------------


class TestRatingMath:
    def test_dimensional_weight_half_kilo_ceiling(self, api):
        """PRD §3.5: "The dimensional weight is the volume divided by the IATA
        volumetric divisor of 0.006 cubic metres per kilogram — equivalently, one
        kilogram per 6000 cubic centimetres. The raw chargeable weight is the greater
        of the waybill's actual `gross_weight_kg` and that dimensional weight, and the
        final `chargeable_weight_kg` is the raw value rounded upward to the next half
        kilogram."

        Design: Corner/calculations/dimensional_weight_half_kilo_ceiling
        """
        ctx = setup_consolidated(
            hwb_number="HWB-DIM",
            hwb_overrides={"pieces": 2, "gross_weight_kg": 40.0, "declared_volume_m3": 0.25},
        )
        hwb = ctx["hwb"]
        # 0.25 / 0.006 = 41.6667 kg dimensional > 40.0 gross; ceils to 42.0
        assert_weight_equal(hwb["chargeable_weight_kg"], 42.0, "chargeable_weight_kg")
        # Only the 0-kg tier qualifies at 42.0: max(250.00, 5.00 x 42.0) = 250.00 floor
        assert_money_equal(hwb["freight_amount"], 250.00, "freight_amount")
        assert_money_equal(hwb["fuel_surcharge_amount"], 31.25, "fuel_surcharge_amount")
        assert_money_equal(hwb["security_fee_amount"], 25.00, "security_fee_amount")
        assert_money_equal(hwb["total_charge_amount"], 306.25, "total_charge_amount")

    def test_weight_break_tier_boundary_inclusive(self, api):
        """PRD §3.5: "Consider every tier whose `min_weight_kg` is at most the
        waybill's chargeable weight."

        Design: Corner/calculations/weight_break_tier_boundary_inclusive
        """
        ctx = setup_consolidated(
            hwb_number="HWB-EDGE",
            hwb_overrides={"pieces": 4, "gross_weight_kg": 100.0, "declared_volume_m3": 0.50},
        )
        hwb = ctx["hwb"]
        # Exactly 100.0 kg: the 100-kg tier's "at most" test is inclusive
        assert_weight_equal(hwb["chargeable_weight_kg"], 100.0, "chargeable_weight_kg")
        assert_money_equal(hwb["freight_amount"], 400.00, "freight_amount")
        assert_money_equal(hwb["total_charge_amount"], 475.00, "total_charge_amount")

    def test_min_charge_floor_below_all_tiers(self, api):
        """PRD §3.5: "If no tier qualifies, the freight line is the agreement's
        `min_charge_amount`."

        Design: Corner/calculations/min_charge_floor_below_all_tiers
        """
        ctx = setup_consolidated(
            shipper_name="Gama Logistics",
            account_code="GAMA",
            agreement_overrides={
                "origin_code": "SEA",
                "destination_code": "ORD",
                "weight_breaks": [
                    {"min_weight_kg": 45, "rate_per_kg": 4.50},
                    {"min_weight_kg": 100, "rate_per_kg": 4.00},
                ],
                "fuel_surcharge_pct": 0.10,
                "security_fee_amount": 20.00,
                "spot_surcharge_pct": 0,
            },
            booking_overrides={
                "airline_code": "AS",
                "flight_number": "AS200",
                "origin_code": "SEA",
                "destination_code": "ORD",
            },
            mawb_number="180-77777777",
            hwb_number="HWB-LOW",
            hwb_overrides={
                "origin_code": "SEA",
                "destination_code": "ORD",
                "pieces": 2,
                "gross_weight_kg": 40.0,
                "declared_volume_m3": 0.20,
            },
        )
        hwb = ctx["hwb"]
        assert_weight_equal(hwb["chargeable_weight_kg"], 40.0, "chargeable_weight_kg")
        assert_money_equal(hwb["freight_amount"], 250.00, "freight_amount")
        assert_money_equal(hwb["total_charge_amount"], 295.00, "total_charge_amount")

    def test_utilization_governed_by_volume_dimension(self, api):
        """PRD §2.7: "The booking's `utilization_pct` is the larger of the two
        consumption ratios — consumed weight divided by booked weight, consumed volume
        divided by booked volume — whichever is greater, expressed as a percentage and
        rounded half-up to two decimal places."
        PRD §3.5: "First, take a snapshot of the booking's consumption over house
        waybills already attached to the booking's non-`VOID` master waybills in
        `CONSOLIDATED` or `TENDERED` state, excluding the candidate."

        Design: Corner/calculations/utilization_governed_by_volume_dimension
        """
        ctx = setup_consolidated(
            booking_overrides={"booked_volume_m3": 2.0},
            hwb_number="HWB-VOL",
            hwb_overrides={"pieces": 9, "gross_weight_kg": 50.0, "declared_volume_m3": 1.80},
        )
        hwb = ctx["hwb"]
        # 1.80 / 0.006 = 300.0 kg dimensional beats 50.0 kg gross
        assert_weight_equal(hwb["chargeable_weight_kg"], 300.0, "chargeable_weight_kg")
        booking = get_booking(ctx["booking"]["id"])
        assert_weight_equal(booking["consumed_weight_kg"], 300.0, "consumed_weight_kg")
        assert booking["consumed_volume_m3"] == pytest.approx(1.8, abs=1e-6)
        # weight ratio 60% vs volume ratio 90%: the volume dimension governs
        assert booking["utilization_pct"] == pytest.approx(90.0, abs=1e-6)
        assert hwb["spot_surcharge_applied"] is False, (
            "the pre-assignment snapshot was 0%, so no spot despite the 90% outcome"
        )
        # freight: min(1500.00, 1350.00, 1200.00) = 1200.00; fuel 150.00; security 25.00
        assert_money_equal(hwb["total_charge_amount"], 1375.00, "total_charge_amount")


class TestTieredFreightSelection:
    def _setup_two_cleared(self):
        ctx = setup_lane()
        hwb_x = create_hwb(
            ctx["shipper"]["id"], "HWB-X", pieces=6, gross_weight_kg=120.0,
            declared_volume_m3=0.50,
        )
        clear_hwb(hwb_x["id"])
        hwb_y = create_hwb(
            ctx["shipper"]["id"], "HWB-Y", pieces=3, gross_weight_kg=60.0,
            declared_volume_m3=0.30,
        )
        clear_hwb(hwb_y["id"])
        return ctx, hwb_x, hwb_y

    def test_higher_break_wins_below_its_break_point(self, api):
        """PRD §3.5: "Otherwise, for each qualifying tier compute the tier's
        `rate_per_kg` multiplied by the chargeable weight, take the greater of that
        product and the `min_charge_amount`, and the freight line is the smallest of
        those per-tier candidates — a higher weight break with a lower per-kilogram
        rate therefore wins even when the waybill sits below that break."

        Design: Difficulty/combinatorial_formula/weight_break_tiered_freight_selection
        """
        ctx, hwb_x, _hwb_y = self._setup_two_cleared()
        rated_x = consolidate_hwb(ctx["mawb"]["id"], hwb_x["id"])
        # 120.0 kg: min(max(250, 600.00), max(250, 540.00), max(250, 480.00))
        assert_money_equal(rated_x["freight_amount"], 480.00, "freight_amount")
        # 480.00 + 60.00 fuel (12.5%) + 25.00 security, no spot (snapshot 0%)
        assert_money_equal(rated_x["total_charge_amount"], 565.00, "total_charge_amount")

    def test_min_charge_floor_interacts_with_tiers(self, api):
        """PRD §3.5: "Otherwise, for each qualifying tier compute the tier's
        `rate_per_kg` multiplied by the chargeable weight, take the greater of that
        product and the `min_charge_amount`, and the freight line is the smallest of
        those per-tier candidates"

        Design: Difficulty/combinatorial_formula/weight_break_tiered_freight_selection
        """
        ctx, hwb_x, hwb_y = self._setup_two_cleared()
        consolidate_hwb(ctx["mawb"]["id"], hwb_x["id"])
        rated_y = consolidate_hwb(ctx["mawb"]["id"], hwb_y["id"])
        # 60.0 kg: min(max(250, 300.00), max(250, 270.00)) = 270.00 via the 45-kg tier
        assert_money_equal(rated_y["freight_amount"], 270.00, "freight_amount")
        # 270.00 + 33.75 fuel + 25.00 security, no spot (snapshot 120/500 = 24%)
        assert_money_equal(rated_y["total_charge_amount"], 328.75, "total_charge_amount")


class TestPerLineRounding:
    def _consolidate_rounding_case(self):
        ctx = setup_consolidated(
            shipper_name="Beta Freight",
            account_code="BETA",
            agreement_overrides={
                "origin_code": "LAX",
                "destination_code": "JFK",
                "weight_breaks": [{"min_weight_kg": 0, "rate_per_kg": 3.33}],
                "min_charge_amount": 0.00,
                "fuel_surcharge_pct": 0.15,
                "security_fee_amount": 10.01,
                "spot_surcharge_pct": 0,
            },
            booking_overrides={
                "airline_code": "DL",
                "flight_number": "DL100",
                "origin_code": "LAX",
                "destination_code": "JFK",
            },
            mawb_number="180-99999999",
            hwb_number="HWB-R",
            hwb_overrides={
                "origin_code": "LAX",
                "destination_code": "JFK",
                "pieces": 2,
                "gross_weight_kg": 45.5,
                "declared_volume_m3": 0.20,
            },
        )
        return ctx["hwb"]

    def test_each_charge_line_rounded_half_up(self, api):
        """PRD §2.8: "Each charge line on a waybill — freight, fuel surcharge,
        security fee, spot surcharge — is individually rounded half-up to two decimal
        places first"
        PRD §2.8: "not from the raw rating result, so the percentage is applied to the
        value actually billed as freight."

        Design: Difficulty/combinatorial_formula/per_line_rounding_then_sum
        """
        hwb = self._consolidate_rounding_case()
        # 3.33 x 45.5 = 151.515 raw -> 151.52 rounded half-up
        assert_money_equal(hwb["freight_amount"], 151.52, "freight_amount")
        # fuel from the ROUNDED freight line: 151.52 x 0.15 = 22.728 -> 22.73
        assert_money_equal(hwb["fuel_surcharge_amount"], 22.73, "fuel_surcharge_amount")
        assert_money_equal(hwb["security_fee_amount"], 10.01, "security_fee_amount")

    def test_total_is_sum_of_rounded_lines_not_sum_then_round(self, api):
        """PRD §2.8: "the waybill's `total_charge_amount` is then the plain sum of
        those already-rounded lines. Summing raw components and rounding once at the
        end is a different, forbidden order: a freight line of 151.52 with a 15
        percent fuel surcharge of 22.73 and a flat 10.01 security fee totals 184.26
        under per-line rounding but 184.25 under sum-then-round."

        Design: Difficulty/combinatorial_formula/per_line_rounding_then_sum
        """
        hwb = self._consolidate_rounding_case()
        assert_money_equal(hwb["total_charge_amount"], 184.26, "total_charge_amount")


# ---------------------------------------------------------------------------
# Spot surcharge threshold semantics
# ---------------------------------------------------------------------------


class TestSpotSurcharge:
    def test_spot_snapshot_excludes_candidate(self, api):
        """PRD §3.5: "First, take a snapshot of the booking's consumption over house
        waybills already attached to the booking's non-`VOID` master waybills in
        `CONSOLIDATED` or `TENDERED` state, excluding the candidate. Second, compute
        the snapshot utilization exactly as §2.7 defines `utilization_pct`. Third, set
        `spot_surcharge_applied` to true exactly when the snapshot utilization is at
        least 85.00 percent"

        Design: Corner/calculations/spot_snapshot_excludes_candidate
        """
        ctx = setup_lane()
        hwb_f = create_hwb(
            ctx["shipper"]["id"], "HWB-F", pieces=21, gross_weight_kg=420.0,
            declared_volume_m3=2.10,
        )
        clear_hwb(hwb_f["id"])
        rated_f = consolidate_hwb(ctx["mawb"]["id"], hwb_f["id"])
        assert rated_f["spot_surcharge_applied"] is False, (
            "first consolidation snapshots an empty booking"
        )

        hwb_g = create_hwb(
            ctx["shipper"]["id"], "HWB-G", pieces=1, gross_weight_kg=10.0,
            declared_volume_m3=0.05,
        )
        clear_hwb(hwb_g["id"])
        rated_g = consolidate_hwb(ctx["mawb"]["id"], hwb_g["id"])
        # Snapshot EXCLUDING the candidate: 420.0/500.0 = 84.00% < 85.00
        assert rated_g["spot_surcharge_applied"] is False, (
            "candidate's own 10 kg (which would push utilization to 86%) is excluded"
        )
        assert_money_equal(rated_g["spot_surcharge_amount"], 0.00, "spot_surcharge_amount")
        # 10.0 kg: freight floor 250.00 + fuel 31.25 + security 25.00
        assert_money_equal(rated_g["total_charge_amount"], 306.25, "total_charge_amount")

    def test_spot_threshold_exactly_85_applies(self, api):
        """PRD §3.5: "Third, set `spot_surcharge_applied` to true exactly when the
        snapshot utilization is at least 85.00 percent — the threshold is inclusive."

        Design: Corner/calculations/spot_threshold_exactly_85_applies
        """
        ctx = setup_lane()
        hwb_d = create_hwb(
            ctx["shipper"]["id"], "HWB-D", pieces=17, gross_weight_kg=425.0,
            declared_volume_m3=2.0,
        )
        clear_hwb(hwb_d["id"])
        rated_d = consolidate_hwb(ctx["mawb"]["id"], hwb_d["id"])
        assert rated_d["spot_surcharge_applied"] is False
        # 425.0 kg: 100-kg break 4.00 x 425.0 = 1700.00; fuel 212.50; security 25.00
        assert_money_equal(rated_d["total_charge_amount"], 1937.50, "total_charge_amount")

        hwb_e = create_hwb(
            ctx["shipper"]["id"], "HWB-E", pieces=3, gross_weight_kg=50.0,
            declared_volume_m3=0.30,
        )
        clear_hwb(hwb_e["id"])
        rated_e = consolidate_hwb(ctx["mawb"]["id"], hwb_e["id"])
        # Snapshot: 425.0/500.0 = 85.00% — the inclusive threshold triggers
        assert rated_e["spot_surcharge_applied"] is True
        # spot line: round(250.00 x 0.075) = 18.75
        assert_money_equal(rated_e["spot_surcharge_amount"], 18.75, "spot_surcharge_amount")
        # 250.00 freight floor + 31.25 fuel + 25.00 security + 18.75 spot
        assert_money_equal(rated_e["total_charge_amount"], 325.00, "total_charge_amount")


# ---------------------------------------------------------------------------
# Capacity boundary precision
# ---------------------------------------------------------------------------


class TestCapacityBoundary:
    def _setup_three_cleared(self):
        ctx = setup_lane()
        hwb_a = create_hwb(ctx["shipper"]["id"], "HWB-A")  # 80.0 / 0.60 -> 100.0 kg
        clear_hwb(hwb_a["id"])
        hwb_b = create_hwb(
            ctx["shipper"]["id"], "HWB-B", pieces=20, gross_weight_kg=400.0,
            declared_volume_m3=1.0,
        )  # -> 400.0 kg
        clear_hwb(hwb_b["id"])
        hwb_c = create_hwb(
            ctx["shipper"]["id"], "HWB-C", pieces=1, gross_weight_kg=0.4,
            declared_volume_m3=0.003,
        )  # dim 0.5 -> 0.5 kg
        clear_hwb(hwb_c["id"])
        return ctx, hwb_a, hwb_b, hwb_c

    def test_capacity_exact_fill_allowed(self, api):
        """PRD §3.4: "Capacity: the booking's current `consumed_weight_kg` plus the
        candidate's chargeable weight must not exceed `booked_weight_kg`, and
        `consumed_volume_m3` plus the candidate's `effective_volume_m3` must not
        exceed `booked_volume_m3`; a breach on either dimension fails with
        `ERR_CAPACITY_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/capacity_exact_fill_allowed_overfill_rejected
        """
        ctx, hwb_a, hwb_b, _hwb_c = self._setup_three_cleared()
        rated_a = consolidate_hwb(ctx["mawb"]["id"], hwb_a["id"])
        assert rated_a["status"] == "CONSOLIDATED"
        rated_b = consolidate_hwb(ctx["mawb"]["id"], hwb_b["id"])
        assert rated_b["status"] == "CONSOLIDATED"
        booking = get_booking(ctx["booking"]["id"])
        # 100.0 + 400.0 == 500.0 == booked_weight_kg: "must not exceed" permits the fill
        assert_weight_equal(booking["consumed_weight_kg"], 500.0, "consumed_weight_kg")
        assert_weight_equal(booking["booked_weight_kg"], 500.0, "booked_weight_kg")

    def test_capacity_overfill_by_half_kilo_rejected(self, api, forwarder_ops_headers):
        """PRD §3.4: "Capacity: the booking's current `consumed_weight_kg` plus the
        candidate's chargeable weight must not exceed `booked_weight_kg`, and
        `consumed_volume_m3` plus the candidate's `effective_volume_m3` must not
        exceed `booked_volume_m3`; a breach on either dimension fails with
        `ERR_CAPACITY_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/capacity_exact_fill_allowed_overfill_rejected
        """
        ctx, hwb_a, hwb_b, hwb_c = self._setup_three_cleared()
        consolidate_hwb(ctx["mawb"]["id"], hwb_a["id"])
        consolidate_hwb(ctx["mawb"]["id"], hwb_b["id"])
        version = get_mawb(ctx["mawb"]["id"])["version"]
        resp = api.consolidate_house_waybill(
            ctx["mawb"]["id"], consolidate_payload(hwb_c["id"], version),
            forwarder_ops_headers,
        )
        # 500.0 + 0.5 > 500.0: one 0.5 kg chargeable step over the exact fill
        validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED)
        after = get_hwb(hwb_c["id"])
        assert after["status"] == "CLEARED"
        assert after["mawb_id"] is None


# ---------------------------------------------------------------------------
# Validation priority pairs (PRD §2.6 fixes the evaluation order)
# ---------------------------------------------------------------------------


class TestValidationPriorityPairs:
    def test_state_error_beats_safety_error(self, api, forwarder_ops_headers):
        """PRD §2.6: "A request failing several rules reports the earliest rule in
        this ordering that it violates." — with "5. State gates" preceding
        "6. Dangerous-goods compliance — known-shipper standing at submit and at
        consolidation (`ERR_SHIPPER_NOT_KNOWN`)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_consolidation
        """
        shipper = create_known_shipper()
        hwb_dgx = create_hwb(
            shipper["id"], "HWB-DGX", pieces=2, gross_weight_kg=80.0,
            declared_volume_m3=0.60, dg_flag=True,
        )
        submit_hwb(hwb_dgx["id"], user_id="ops-1")
        drive_shipper_to_suspended(shipper["id"])
        assert validate_success(api.get_shipper(shipper["id"], forwarder_ops_headers))[
            "known_shipper_status"
        ] == "SUSPENDED"

        booking = create_booking()
        mawb = create_mawb(booking["id"])
        open_mawb(mawb["id"])
        version = get_mawb(mawb["id"])["version"]
        resp = api.consolidate_house_waybill(
            mawb["id"], consolidate_payload(hwb_dgx["id"], version), forwarder_ops_headers
        )
        # HWB-DGX is in SCREENING (state gate) AND the shipper is SUSPENDED (dg
        # re-check): the earlier rule — state — must surface.
        validate_error(resp, ApiErrorId.ERR_HWB_NOT_CLEARED)

    def test_state_priority_pair_leaves_no_side_effects(self, api, forwarder_ops_headers):
        """PRD §2.6: "A request failing several rules reports the earliest rule in
        this ordering that it violates."
        PRD §3.4: "The candidate waybill must be `CLEARED`; anything else fails with
        `ERR_HWB_NOT_CLEARED`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_consolidation
        """
        shipper = create_known_shipper()
        hwb_dgx = create_hwb(
            shipper["id"], "HWB-DGX", pieces=2, gross_weight_kg=80.0,
            declared_volume_m3=0.60, dg_flag=True,
        )
        submit_hwb(hwb_dgx["id"], user_id="ops-1")
        drive_shipper_to_suspended(shipper["id"])
        booking = create_booking()
        mawb = create_mawb(booking["id"])
        open_mawb(mawb["id"])
        version_pre = get_mawb(mawb["id"])["version"]

        resp = api.consolidate_house_waybill(
            mawb["id"], consolidate_payload(hwb_dgx["id"], version_pre),
            forwarder_ops_headers,
        )
        validate_error(resp, ApiErrorId.ERR_HWB_NOT_CLEARED)
        assert get_hwb(hwb_dgx["id"])["status"] == "SCREENING"
        assert get_mawb(mawb["id"])["version"] == version_pre, (
            "a rejected consolidation must not touch the master waybill"
        )

    def test_safety_error_beats_fiscal_error(self, api, forwarder_ops_headers):
        """PRD §2.6: "A request failing several rules reports the earliest rule in
        this ordering that it violates." — with "6. Dangerous-goods compliance —
        known-shipper standing at submit and at consolidation (`ERR_SHIPPER_NOT_KNOWN`)"
        preceding "11. Capacity and money caps — booking capacity at consolidation and
        at tender, claim amounts against liability limits (`ERR_CAPACITY_EXCEEDED`,
        `ERR_AMOUNT_EXCEEDS_LIABILITY`)."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_on_consolidation
        """
        shipper = create_known_shipper()
        file_rate_agreement(
            shipper["id"],
            weight_breaks=[{"min_weight_kg": 0, "rate_per_kg": 5.00}],
            spot_surcharge_pct=0,
        )
        hwb_dgy = create_hwb(
            shipper["id"], "HWB-DGY", pieces=2, gross_weight_kg=80.0,
            declared_volume_m3=0.60, dg_flag=True,
        )
        clear_hwb(hwb_dgy["id"])  # clears SECURITY + DANGEROUS_GOODS while KNOWN
        drive_shipper_to_suspended(shipper["id"])

        booking = create_booking(flight_number="UA859", booked_weight_kg=50.0)
        mawb = create_mawb(booking["id"], "180-55555555")
        open_mawb(mawb["id"])
        version = get_mawb(mawb["id"])["version"]
        resp = api.consolidate_house_waybill(
            mawb["id"], consolidate_payload(hwb_dgy["id"], version), forwarder_ops_headers
        )
        # Shipper SUSPENDED (dg re-check) AND 100.0 kg candidate vs 50.0 kg booked
        # (capacity): the earlier rule — dg compliance — must surface.
        validate_error(resp, ApiErrorId.ERR_SHIPPER_NOT_KNOWN)

    def test_safety_priority_pair_leaves_no_side_effects(self, api, forwarder_ops_headers):
        """PRD §2.6: "A request failing several rules reports the earliest rule in
        this ordering that it violates."
        PRD §3.4: "Dangerous goods re-check: if the candidate's `dg_flag` is true, the
        shipper's `known_shipper_status` must still be `KNOWN` at this moment —
        standing is verified twice, at submit and again at consolidation — else
        `ERR_SHIPPER_NOT_KNOWN`."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_on_consolidation
        """
        shipper = create_known_shipper()
        file_rate_agreement(
            shipper["id"],
            weight_breaks=[{"min_weight_kg": 0, "rate_per_kg": 5.00}],
            spot_surcharge_pct=0,
        )
        hwb_dgy = create_hwb(
            shipper["id"], "HWB-DGY", pieces=2, gross_weight_kg=80.0,
            declared_volume_m3=0.60, dg_flag=True,
        )
        clear_hwb(hwb_dgy["id"])
        drive_shipper_to_suspended(shipper["id"])
        booking = create_booking(flight_number="UA859", booked_weight_kg=50.0)
        mawb = create_mawb(booking["id"], "180-55555555")
        open_mawb(mawb["id"])

        resp = api.consolidate_house_waybill(
            mawb["id"],
            consolidate_payload(hwb_dgy["id"], get_mawb(mawb["id"])["version"]),
            forwarder_ops_headers,
        )
        validate_error(resp, ApiErrorId.ERR_SHIPPER_NOT_KNOWN)
        assert get_hwb(hwb_dgy["id"])["status"] == "CLEARED"
        assert_weight_equal(
            get_booking(booking["id"])["consumed_weight_kg"], 0.0, "consumed_weight_kg"
        )


# ---------------------------------------------------------------------------
# Lane consistency and rate-agreement temporal rules
# ---------------------------------------------------------------------------


class TestLaneAndRateRules:
    def test_consolidation_lane_mismatch_rejected(self, api, forwarder_ops_headers):
        """PRD §3.4: "Lane consistency: the waybill's `origin_code` and
        `destination_code` must equal the booking's `origin_code` and
        `destination_code`, else `ERR_LANE_MISMATCH`."

        Design: Corner/validations/consolidation_lane_mismatch_rejected
        """
        ctx = setup_cleared_hwb(
            hwb_number="HWB-LANE",
            hwb_overrides={
                "origin_code": "LAX",
                "destination_code": "NRT",
                "pieces": 1,
                "gross_weight_kg": 10.0,
                "declared_volume_m3": 0.05,
            },
        )
        version = get_mawb(ctx["mawb"]["id"])["version"]
        resp = api.consolidate_house_waybill(
            ctx["mawb"]["id"], consolidate_payload(ctx["hwb"]["id"], version),
            forwarder_ops_headers,
        )
        validate_error(resp, ApiErrorId.ERR_LANE_MISMATCH)
        after = get_hwb(ctx["hwb"]["id"])
        assert after["status"] == "CLEARED"
        assert after["mawb_id"] is None
        assert_weight_equal(
            get_booking(ctx["booking"]["id"])["consumed_weight_kg"], 0.0,
            "consumed_weight_kg",
        )

    def test_expired_rate_agreement_blocks_consolidation(self, api, forwarder_ops_headers):
        """PRD §3.1: "An agreement is active for rating when the logical clock reads
        at or after its `valid_from_utc` and strictly before its `valid_to_utc`."
        PRD §3.4: "A rate agreement must be active for the waybill's shipper and lane
        at the logical clock, else `ERR_NO_ACTIVE_RATE_AGREEMENT`."

        Design: Corner/validations/expired_rate_agreement_blocks_consolidation
        """
        ctx = setup_cleared_hwb(
            agreement_overrides={"valid_to_utc": "2026-07-01T00:00:00Z"}
        )
        # No clock-set call: the logical clock reads the fixed 2026-08-01 default,
        # past the agreement's exclusive valid_to of 2026-07-01.
        version = get_mawb(ctx["mawb"]["id"])["version"]
        resp = api.consolidate_house_waybill(
            ctx["mawb"]["id"], consolidate_payload(ctx["hwb"]["id"], version),
            forwarder_ops_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_RATE_AGREEMENT)
        after = get_hwb(ctx["hwb"]["id"])
        assert after["status"] == "CLEARED"
        assert after["mawb_id"] is None


class TestRateAgreementWindows:
    def test_overlapping_window_rejected(self, api, pricing_manager_headers):
        """PRD §3.1: "Windows for the same shipper and lane must not overlap: a new
        agreement whose half-open window intersects an existing one is rejected with
        `ERR_RATE_AGREEMENT_OVERLAP`"

        Design: Difficulty/resource_temporal_overlap/rate_agreement_half_open_adjacency
        """
        shipper = create_shipper()
        file_rate_agreement(shipper["id"], valid_to_utc="2026-07-01T00:00:00Z")
        resp = api.create_rate_agreement(
            {
                "shipper_id": shipper["id"],
                "origin_code": "SFO",
                "destination_code": "NRT",
                "weight_breaks": [{"min_weight_kg": 0, "rate_per_kg": 4.80}],
                "min_charge_amount": 240.00,
                "fuel_surcharge_pct": 0.125,
                "security_fee_amount": 25.00,
                "spot_surcharge_pct": 0,
                "valid_from_utc": "2026-06-01T00:00:00Z",
                "valid_to_utc": "2026-12-01T00:00:00Z",
            },
            pricing_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_RATE_AGREEMENT_OVERLAP)

    def test_touching_window_allowed(self, api, forwarder_ops_headers, pricing_manager_headers):
        """PRD §3.1: "while touching windows — an existing agreement ending exactly
        when the new one begins — are allowed."

        Design: Difficulty/resource_temporal_overlap/rate_agreement_half_open_adjacency
        """
        shipper = create_shipper()
        file_rate_agreement(shipper["id"], valid_to_utc="2026-07-01T00:00:00Z")
        resp = api.create_rate_agreement(
            {
                "shipper_id": shipper["id"],
                "origin_code": "SFO",
                "destination_code": "NRT",
                "weight_breaks": [{"min_weight_kg": 0, "rate_per_kg": 4.80}],
                "min_charge_amount": 240.00,
                "fuel_surcharge_pct": 0.125,
                "security_fee_amount": 25.00,
                "spot_surcharge_pct": 0,
                "valid_from_utc": "2026-07-01T00:00:00Z",
                "valid_to_utc": "2027-01-01T00:00:00Z",
            },
            pricing_manager_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert data["id"], "touching window (valid_from == existing valid_to) is allowed"
        _rows, meta = validate_paginated(
            api.list_shipper_rate_agreements(shipper["id"], forwarder_ops_headers)
        )
        assert meta["total_count"] == 2
