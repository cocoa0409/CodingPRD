"""Ledgers that must come back to exactly where they started.

Two compensating pairs: a reservation release returns precisely the energy the
hold withheld, and compensating a completed delivery unwinds every ledger
movement the completion applied.
"""
import pytest
from prd_bench_local_runner.testing import validate_paginated

from test_helpers.api_client import api_client
from test_helpers.fixtures import (
    DISPATCH_DAY_CLOCK,
    TRADER,
    delivered_position,
    fail_dispatch,
    hold_reservation,
    refresh_asset,
    refresh_dispatch,
    refresh_reservation,
    reference_plant,
    release_reservation,
    set_clock,
)


class TestReservationPoolConservation:
    """Forty and thirty megawatt-hours held, then handed back one at a time."""

    WINDOW = ("2026-08-10T12:00:00Z", "2026-08-10T20:00:00Z")

    def _fully_booked_plant(self):
        set_clock("2026-08-01T00:00:00Z")
        asset = reference_plant()
        first = hold_reservation(
            asset["id"],
            purpose="ENERGY_ARBITRAGE",
            reserved_mwh=40.0,
            window_start=self.WINDOW[0],
            window_end=self.WINDOW[1],
        )
        second = hold_reservation(
            asset["id"],
            purpose="ANCILLARY",
            reserved_mwh=30.0,
            window_start=self.WINDOW[0],
            window_end=self.WINDOW[1],
        )
        return asset, first, second

    def test_two_holds_take_the_whole_pool(self):
        """Seventy megawatt-hours of headroom become seventy megawatt-hours withheld.

        PRD: "The same discipline governs reserved energy: `reserved_mwh_total` is recomputed from the reservations that are actually held whenever any reservation changes status and whenever the asset's stored or available energy changes, so a release always returns exactly what a hold withheld."

        Design: Difficulty/compensating_invariant/reservation_pool_conservation_across_release
        """
        asset, first, second = self._fully_booked_plant()

        assert asset["reserved_mwh_total"] == pytest.approx(0.0, abs=0.01)
        assert asset["free_dispatchable_mwh"] == pytest.approx(70.0, abs=0.01)
        booked = refresh_asset(asset["id"])
        assert booked["reserved_mwh_total"] == pytest.approx(70.0, abs=0.01)
        assert booked["free_dispatchable_mwh"] == pytest.approx(0.0, abs=0.01)

    def test_releasing_one_hold_returns_exactly_what_it_withheld(self):
        """Handing back forty megawatt-hours leaves thirty held and forty free.

        PRD: "A `MarketTrader` or `AssetManager` may release it explicitly, giving `status` `RELEASED` and `released_reason` `OPERATOR_RELEASE`; the release is refused with `ERR_RESERVATION_NOT_HELD` when the reservation is not `HELD`, and also when any offer with `status` `SUBMITTED` or `CLEARED` still references it, since live market exposure cannot be un-backed by an operator's choice."

        Design: Difficulty/compensating_invariant/reservation_pool_conservation_across_release
        """
        asset, first, second = self._fully_booked_plant()

        released = release_reservation(first["id"])

        assert released["status"] == "RELEASED"
        assert released["released_reason"] == "OPERATOR_RELEASE"
        after = refresh_asset(asset["id"])
        assert after["reserved_mwh_total"] == pytest.approx(30.0, abs=0.01)
        assert after["free_dispatchable_mwh"] == pytest.approx(40.0, abs=0.01)

    def test_releasing_both_holds_restores_the_opening_pool(self):
        """The pool returns to zero held and seventy free, exactly as it began.

        PRD: "`free_dispatchable_mwh` becomes the usable ceiling minus the floor minus `reserved_mwh_total`, rounded half up to 3 decimal places and floored at 0."

        Design: Difficulty/compensating_invariant/reservation_pool_conservation_across_release
        """
        asset, first, second = self._fully_booked_plant()

        release_reservation(first["id"])
        release_reservation(second["id"])

        after = refresh_asset(asset["id"])
        assert after["reserved_mwh_total"] == pytest.approx(0.0, abs=0.01)
        assert after["free_dispatchable_mwh"] == pytest.approx(70.0, abs=0.01)

    def test_the_released_rows_survive_as_history(self):
        """Nothing is deleted: both holds are still listed, neither is still HELD.

        PRD: "Reservations in `CONSUMED`, `RELEASED` or `EXPIRED` occupy nothing."

        Design: Difficulty/compensating_invariant/reservation_pool_conservation_across_release
        """
        asset, first, second = self._fully_booked_plant()
        release_reservation(first["id"])
        release_reservation(second["id"])

        _, held_meta = validate_paginated(
            api_client.list_soc_reservations(
                TRADER, {"asset_id": asset["id"], "status": "HELD"}
            )
        )
        rows, all_meta = validate_paginated(
            api_client.list_soc_reservations(TRADER, {"asset_id": asset["id"]})
        )
        assert held_meta["total_count"] == 0
        assert all_meta["total_count"] == 2
        assert {row["status"] for row in rows} == {"RELEASED"}


class TestDeliveryLedgerCompensation:
    """A 19.8 MWh delivery credited, then voided.

    The compensation must land the plant back on 80.0 MWh stored, zero
    throughput and zero cycles.
    """

    def _completed_delivery(self):
        set_clock(DISPATCH_DAY_CLOCK)
        return delivered_position()

    def test_completion_credits_the_ledgers_from_the_delivery(self):
        """Nineteen point eight megawatt-hours leave the pack and enter the throughput ledger.

        PRD: "The ledgers then move, in this order. The asset's `soc_mwh` becomes its previous value plus `soc_delta_mwh`, rounded half up to 3 decimal places. The asset's `cumulative_throughput_mwh` becomes its previous value plus `delivered_mwh`, rounded half up to 3 decimal places."

        Design: Difficulty/compensating_invariant/throughput_and_soc_conservation_across_dispatch_compensation
        """
        position = self._completed_delivery()
        dispatch = position["dispatch"]

        assert dispatch["delivered_mwh"] == pytest.approx(19.8, abs=0.01)
        assert dispatch["soc_delta_mwh"] == pytest.approx(-19.8, abs=0.01)
        assert dispatch["scoring_status"] == "PROVISIONAL"
        assert dispatch["composite_score"] == pytest.approx(91.10, abs=0.01)
        mid = refresh_asset(position["asset"]["id"])
        assert mid["soc_mwh"] == pytest.approx(60.2, abs=0.01)
        assert mid["cumulative_throughput_mwh"] == pytest.approx(19.8, abs=0.01)
        assert mid["equivalent_full_cycles_ytd"] == pytest.approx(0.099, abs=0.01)

    def test_completion_consumes_the_backing_reservation(self):
        """The hold becomes a consumption recording exactly the delivered energy.

        PRD: "The backing reservation moves `HELD → CONSUMED` with `consumed_mwh` set to `delivered_mwh`, and the asset's `reserved_mwh_total` and `free_dispatchable_mwh` are recomputed."

        Design: Difficulty/compensating_invariant/throughput_and_soc_conservation_across_dispatch_compensation
        """
        position = self._completed_delivery()

        consumed = refresh_reservation(position["reservation"]["id"])
        assert consumed["status"] == "CONSUMED"
        assert consumed["consumed_mwh"] == pytest.approx(19.8, abs=0.01)

    def test_compensation_voids_the_instruction_s_own_figures(self):
        """Failing a completed delivery blanks its energy, its deltas and its score.

        PRD: "The instruction's own `delivered_mwh` and `soc_delta_mwh` are reset to 0.0, its `failure_reason` becomes `DELIVERY_VOIDED`, its scoring axis moves `PROVISIONAL → NOT_SCORED`, its `accuracy_score`, `deadband_pct` and `composite_score` are set to null, and its `non_performance_charge_usd` returns to 0.0."

        Design: Difficulty/compensating_invariant/throughput_and_soc_conservation_across_dispatch_compensation
        """
        position = self._completed_delivery()

        fail_dispatch(position["dispatch"]["id"], failure_reason="DELIVERY_VOIDED")

        voided = refresh_dispatch(position["dispatch"]["id"])
        assert voided["execution_status"] == "FAILED"
        assert voided["failure_reason"] == "DELIVERY_VOIDED"
        assert voided["delivered_mwh"] == pytest.approx(0.0, abs=0.01)
        assert voided["soc_delta_mwh"] == pytest.approx(0.0, abs=0.01)
        assert voided["accuracy_score"] is None
        assert voided["deadband_pct"] is None
        assert voided["composite_score"] is None
        assert voided["non_performance_charge_usd"] == pytest.approx(0.0, abs=0.01)
        assert voided["scoring_status"] == "NOT_SCORED"

    def test_compensation_restores_the_asset_ledgers_exactly(self):
        """Stored energy, throughput and cycles all return to their opening values.

        PRD: "Failed instructions contribute zero to both sums because their `delivered_mwh` and `soc_delta_mwh` are reset to 0.0 when they fail."

        Design: Difficulty/compensating_invariant/throughput_and_soc_conservation_across_dispatch_compensation
        """
        position = self._completed_delivery()

        fail_dispatch(position["dispatch"]["id"], failure_reason="DELIVERY_VOIDED")

        after = refresh_asset(position["asset"]["id"])
        assert after["soc_mwh"] == pytest.approx(80.0, abs=0.01)
        assert after["cumulative_throughput_mwh"] == pytest.approx(0.0, abs=0.01)
        assert after["equivalent_full_cycles_ytd"] == pytest.approx(0.0, abs=0.01)
        assert after["reserved_mwh_total"] == pytest.approx(0.0, abs=0.01)
        assert after["free_dispatchable_mwh"] == pytest.approx(70.0, abs=0.01)

    def test_compensation_hands_the_consumed_reservation_back(self):
        """The consumption is unwound into a release naming the compensation.

        PRD: "The backing reservation moves `CONSUMED → RELEASED` with `consumed_mwh` reset to 0.0 and `released_reason` of `DISPATCH_COMPENSATION`."

        Design: Difficulty/compensating_invariant/throughput_and_soc_conservation_across_dispatch_compensation
        """
        position = self._completed_delivery()

        fail_dispatch(position["dispatch"]["id"], failure_reason="DELIVERY_VOIDED")

        released = refresh_reservation(position["reservation"]["id"])
        assert released["status"] == "RELEASED"
        assert released["consumed_mwh"] == pytest.approx(0.0, abs=0.01)
        assert released["released_reason"] == "DISPATCH_COMPENSATION"
