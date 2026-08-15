"""Chamber slot ledger conservation, pinned burn-in duration rounding, dual-basis
utilization, and the OCC-guarded reschedule (PRD §2.6–§2.8, §3.3)."""
import pytest

from test_helpers import (
    assert_chamber_slot_invariant,
    reserve,
    setup_reservation_scenario,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import OPS


class TestSlotLedgerInvariant:
    def test_reserve_cancel_returns_ledger_to_prior_value(self, api):
        """PRD §2.8: "The committed load on a chamber is the sum of `slot_count`
        over that chamber's reservations whose status is `RESERVED` or
        `IN_PROGRESS`, and the chamber's `available_slots` is its total `slot_count`
        minus that committed load."
        PRD §2.8: "The ledger honors a compensating-pair invariant: creating a
        reservation and then cancelling that same reservation returns
        `available_slots` to exactly the value it held before the create."

        Design: Difficulty/compensating_invariant/chamber_slot_ledger_reserve_cancel_invariant
        """
        ctx = setup_reservation_scenario(
            part_number="PN-151", max_retests_per_unit=1, slot_count=8
        )
        r1 = reserve(ctx, start_at="2026-06-01T10:00:00Z",
                     end_at="2026-06-01T11:00:00Z", slot_count=3)
        chamber = validate_success(api.get_chamber(ctx["chamber"]["id"], OPS), 200)
        assert chamber["available_slots"] == 5, "3 reserved: 3 committed + 5 available == 8"

        reserve(ctx, start_at="2026-06-01T12:00:00Z",
                end_at="2026-06-01T13:00:00Z", slot_count=5)
        chamber = validate_success(api.get_chamber(ctx["chamber"]["id"], OPS), 200)
        assert chamber["available_slots"] == 0, (
            "3 + 5 committed: booking every remaining slot is permitted"
        )

        validate_success(api.cancel_reservation(r1["id"], OPS), 200)
        chamber = validate_success(api.get_chamber(ctx["chamber"]["id"], OPS), 200)
        # R1's cancel compensates its create exactly (+3): only R2's 5 slots stay
        # committed, so available_slots == 8 - 5 == 3 per the §2.8 definition.
        assert chamber["available_slots"] == 3, (
            "the compensating cancel freed exactly R1's 3 slots: 0 + 3, "
            "with R2's 5 still committed"
        )
        assert_chamber_slot_invariant(chamber)

    def test_reserve_cancel_pair_statuses(self, api):
        """PRD §3.3: "Cancelling moves a `RESERVED` reservation to `CANCELLED` and
        likewise frees its slots — cancellation is the exact compensating action of
        creation, restoring `available_slots` to its prior value."
        PRD §3.3: "A successfully created reservation lands in `RESERVED` status."

        Design: Difficulty/compensating_invariant/chamber_slot_ledger_reserve_cancel_invariant
        """
        ctx = setup_reservation_scenario(
            part_number="PN-151", max_retests_per_unit=1, slot_count=8
        )
        r1 = reserve(ctx, start_at="2026-06-01T10:00:00Z",
                     end_at="2026-06-01T11:00:00Z", slot_count=3)
        r2 = reserve(ctx, start_at="2026-06-01T12:00:00Z",
                     end_at="2026-06-01T13:00:00Z", slot_count=5)
        cancelled = validate_success(api.cancel_reservation(r1["id"], OPS), 200)
        assert cancelled["status"] == "CANCELLED"
        r2_after = validate_success(api.get_chamber_reservation(r2["id"], OPS), 200)
        assert r2_after["status"] == "RESERVED", (
            "cancelling R1 must not disturb the sibling reservation"
        )
        chamber = validate_success(api.get_chamber(ctx["chamber"]["id"], OPS), 200)
        # Conservation: 5 committed (R2) + 3 available == slot_count 8.
        assert chamber["available_slots"] == 3
        assert 5 + chamber["available_slots"] == chamber["slot_count"]


class TestBurnInDurationRounding:
    # Two-segment profile; per-segment round-half-up then sum:
    #   ramp1 = round_half_up((55-25)/7) = round_half_up(4.2857) = 4;  seg1 = 34
    #   ramp2 = round_half_up((95-55)/3) = round_half_up(13.3333) = 13; seg2 = 58
    #   planned total = 92 (the sum-then-round alternative, 93, is not compliant).
    TWO_SEG_PROFILE = [
        {"target_temp_c": 55, "ramp_rate_c_per_min": 7, "soak_minutes": 30},
        {"target_temp_c": 95, "ramp_rate_c_per_min": 3, "soak_minutes": 45},
    ]

    def test_planned_duration_per_segment_rounding(self, api):
        """PRD §3.3: "computation begins from an ambient baseline of 25 °C; for each
        profile segment in array order, the absolute temperature gap between the
        segment's target and the previous segment's target (the ambient baseline for
        the first segment) is divided by that segment's ramp rate, the quotient is
        rounded half-up to a whole number of ramp minutes, and the segment's soak
        minutes are added; the planned duration is the sum of these per-segment
        totals."

        Design: Difficulty/combinatorial_formula/burn_in_profile_duration_segment_rounding
        """
        ctx = setup_reservation_scenario(
            part_number="PN-400", max_retests_per_unit=1,
            bin_map={"1": "PASS", "9": "HARD_FAIL"},
            burn_profile=self.TWO_SEG_PROFILE,
        )
        reservation = reserve(
            ctx, start_at="2026-06-01T10:00:00Z", end_at="2026-06-01T12:00:00Z"
        )
        assert reservation["planned_duration_minutes"] == 92, (
            "per-segment round-half-up(4.2857)=4 + 30, round-half-up(13.3333)=13 + 45, "
            "then summed"
        )

    def test_planned_duration_is_not_sum_then_round(self, api):
        """PRD §3.3: "Rounding each segment's ramp before summing is part of the
        contract — summing raw ramp minutes and rounding once at the end produces a
        different integer and is not compliant."
        PRD §2.7: "Planned burn-in durations are whole minutes. Each profile
        segment's ramp time is rounded half-up to a whole number of minutes first,
        and the per-segment results are then summed; rounding only once at the end
        is not compliant."

        Design: Difficulty/combinatorial_formula/burn_in_profile_duration_segment_rounding
        """
        ctx = setup_reservation_scenario(
            part_number="PN-400", max_retests_per_unit=1,
            bin_map={"1": "PASS", "9": "HARD_FAIL"},
            burn_profile=self.TWO_SEG_PROFILE,
        )
        reservation = reserve(
            ctx, start_at="2026-06-01T10:00:00Z", end_at="2026-06-01T12:00:00Z"
        )
        # The sum-then-round alternative yields 93 (4.2857+30+13.3333+45 = 92.619).
        assert reservation["planned_duration_minutes"] != 93, (
            "sum-then-round is explicitly non-compliant"
        )
        assert reservation["planned_duration_minutes"] == 92
        assert isinstance(reservation["planned_duration_minutes"], int), (
            "planned durations are whole minutes"
        )


class TestChamberUtilizationDualBasis:
    def _build_utilization_scenario(self, api):
        """Chamber CH-U (4 slots, class A); R1 2 slots 01:00-03:00 driven to
        COMPLETED; R2 1 slot 04:00-06:00 left RESERVED; clock at 05:00."""
        ctx = setup_reservation_scenario(
            part_number="PN-200", max_retests_per_unit=2, slot_count=4,
            burn_profile=[{"target_temp_c": 55, "ramp_rate_c_per_min": 7,
                           "soak_minutes": 30}],
        )
        chamber = ctx["chamber"]
        r1 = reserve(ctx, start_at="2026-06-01T01:00:00Z",
                     end_at="2026-06-01T03:00:00Z", slot_count=2)
        validate_success(api.set_clock({"to_iso8601": "2026-06-01T01:00:00Z"}, OPS), 200)
        validate_success(api.start_reservation(r1["id"], OPS), 200)
        validate_success(api.set_clock({"to_iso8601": "2026-06-01T03:00:00Z"}, OPS), 200)
        validate_success(api.complete_reservation(r1["id"], OPS), 200)
        r2 = reserve(ctx, start_at="2026-06-01T04:00:00Z",
                     end_at="2026-06-01T06:00:00Z", slot_count=1)
        validate_success(api.set_clock({"to_iso8601": "2026-06-01T05:00:00Z"}, OPS), 200)
        return ctx, chamber, r1, r2

    def test_scheduled_basis_counts_reserved_and_completed_over_full_window(self, api):
        """PRD §3.3: "Under the `SCHEDULED` basis — the forward-looking measure —
        reservations in `RESERVED`, `IN_PROGRESS`, or `COMPLETED` status are
        counted, and `denominator_slot_minutes` is the chamber's total `slot_count`
        multiplied by the full window length in minutes."
        PRD §2.7: "Yield and utilization ratios are carried internally as exact
        fractions and serialized as numbers rounded to exactly 4 decimal places
        using the round-half-up method."

        Design: Difficulty/dual_variant_calc/chamber_utilization_scheduled_vs_actual_diverge
        """
        _ctx, chamber, _r1, _r2 = self._build_utilization_scenario(api)
        report = validate_success(
            api.get_chamber_utilization(
                chamber["id"],
                {"window_start": "2026-06-01T00:00:00Z",
                 "window_end": "2026-06-01T10:00:00Z", "basis": "SCHEDULED"},
                OPS,
            ),
            200,
        )
        assert report["basis"] == "SCHEDULED"
        # numerator = 2x120 (R1) + 1x120 (R2) = 360 slot-minutes
        assert report["numerator_slot_minutes"] == 360
        # denominator = 4 slots x 600 minutes
        assert report["denominator_slot_minutes"] == 2400
        assert report["utilization_ratio"] == pytest.approx(0.15, abs=1e-9)

    def test_actual_basis_counts_completed_over_elapsed_window_and_diverges(self, api):
        """PRD §3.3: "Under the `ACTUAL` basis — the chronological measure of
        completed work — only `COMPLETED` reservations are counted, and the
        denominator covers only the portion of the window that has already elapsed
        at the current logical clock, measured from the window start to the earlier
        of the window end and the clock."
        PRD §3.3: "`CANCELLED` reservations are never counted under either basis."

        Design: Difficulty/dual_variant_calc/chamber_utilization_scheduled_vs_actual_diverge
        """
        _ctx, chamber, _r1, _r2 = self._build_utilization_scenario(api)
        scheduled = validate_success(
            api.get_chamber_utilization(
                chamber["id"],
                {"window_start": "2026-06-01T00:00:00Z",
                 "window_end": "2026-06-01T10:00:00Z", "basis": "SCHEDULED"},
                OPS,
            ),
            200,
        )
        actual = validate_success(
            api.get_chamber_utilization(
                chamber["id"],
                {"window_start": "2026-06-01T00:00:00Z",
                 "window_end": "2026-06-01T10:00:00Z", "basis": "ACTUAL"},
                OPS,
            ),
            200,
        )
        assert actual["basis"] == "ACTUAL"
        # numerator = COMPLETED only: 2 x 120 = 240 slot-minutes
        assert actual["numerator_slot_minutes"] == 240
        # denominator = 4 slots x 300 elapsed minutes (00:00 -> clock 05:00)
        assert actual["denominator_slot_minutes"] == 1200
        assert actual["utilization_ratio"] == pytest.approx(0.2, abs=1e-9)
        assert scheduled["utilization_ratio"] != pytest.approx(
            actual["utilization_ratio"], abs=1e-9
        ), "the two bases must diverge over identical chamber state"


class TestRescheduleOcc:
    def test_first_reschedule_succeeds_and_bumps_version(self, api):
        """PRD §3.3: "A reservation still in `RESERVED` may be rescheduled: the
        window, the slot count, and the profile class may all change."
        PRD §2.6: "Rescheduling a chamber reservation requires the request to carry
        `expected_chamber_reservation_version`, a non-optional field holding the
        reservation's `version` as the client last observed it."
        PRD §2.9: "When a reservation is rescheduled, the reservation itself is
        excluded from its own overlap scan."

        Design: Corner/cross_cutting_layers/occ_reschedule_stale_version_returns_412
        """
        ctx = setup_reservation_scenario(part_number="PN-239", max_retests_per_unit=1)
        r1 = reserve(ctx, start_at="2026-06-01T10:00:00Z",
                     end_at="2026-06-01T11:00:00Z", slot_count=1)
        observed = r1["version"]
        rescheduled = validate_success(
            api.reschedule_reservation(
                r1["id"],
                {"expected_chamber_reservation_version": observed,
                 "start_at": "2026-06-01T12:00:00Z", "end_at": "2026-06-01T13:00:00Z"},
                OPS,
            ),
            200,
        )
        assert rescheduled["version"] == observed + 1, (
            "a successful reschedule increments the reservation's version"
        )
        assert rescheduled["start_at"] == "2026-06-01T12:00:00Z"
        assert rescheduled["end_at"] == "2026-06-01T13:00:00Z"

    def test_replayed_observed_version_rejected_stale(self, api):
        """PRD §2.6: "If the reservation's current `version` has advanced beyond
        that value, the reschedule is rejected with `ERR_STALE_VERSION` (HTTP 412),
        preventing the client from silently undoing a reschedule it never observed."

        Design: Corner/cross_cutting_layers/occ_reschedule_stale_version_returns_412
        """
        ctx = setup_reservation_scenario(part_number="PN-239", max_retests_per_unit=1)
        r1 = reserve(ctx, start_at="2026-06-01T10:00:00Z",
                     end_at="2026-06-01T11:00:00Z", slot_count=1)
        observed = r1["version"]
        first = validate_success(
            api.reschedule_reservation(
                r1["id"],
                {"expected_chamber_reservation_version": observed,
                 "start_at": "2026-06-01T12:00:00Z", "end_at": "2026-06-01T13:00:00Z"},
                OPS,
            ),
            200,
        )
        # Replaying the same observed version is deterministically stale.
        res = api.reschedule_reservation(
            r1["id"],
            {"expected_chamber_reservation_version": observed,
             "start_at": "2026-06-01T14:00:00Z", "end_at": "2026-06-01T15:00:00Z"},
            OPS,
        )
        validate_error(res, "ERR_STALE_VERSION", expected_status=412)
        after = validate_success(api.get_chamber_reservation(r1["id"], OPS), 200)
        assert after["start_at"] == first["start_at"]
        assert after["end_at"] == first["end_at"], "rejected reschedule changes nothing"
        assert after["version"] == first["version"]
