"""Exact-boundary probes: one hundredth either side of a threshold.

Both pairs turn on an inclusive comparison. A reservation for exactly the
remaining headroom is accepted while one hundredth more is refused, and a
composite score sitting exactly on the performance floor is charged nothing
while one hundredth of a point below it is charged.
"""
import pytest
from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers.api_client import api_client
from test_helpers.factories import create_soc_reservation_payload
from test_helpers.fixtures import (
    TRADER,
    append_samples,
    cleared_bid,
    complete_dispatch,
    executing_dispatch,
    hold_reservation,
    provision_asset,
    refresh_asset,
    reference_plant,
    set_clock,
    settle_score,
)


class TestReservationHeadroomBoundary:
    """A 70 MWh envelope met by 40.0, then exactly 30.0, then 0.01 too much."""

    WINDOW = ("2026-08-10T12:00:00Z", "2026-08-10T20:00:00Z")

    def _plant_with_forty_held(self):
        set_clock("2026-08-01T00:00:00Z")
        asset = reference_plant()
        first = hold_reservation(
            asset["id"],
            reserved_mwh=40.0,
            window_start=self.WINDOW[0],
            window_end=self.WINDOW[1],
        )
        return asset, first

    def test_the_first_hold_leaves_exactly_thirty_of_headroom(self):
        """Forty megawatt-hours off a seventy megawatt-hour envelope leaves thirty.

        PRD: "`free_dispatchable_mwh` becomes the usable ceiling minus the floor minus `reserved_mwh_total`, rounded half up to 3 decimal places and floored at 0."

        Design: Difficulty/boundary_precision_check/soc_headroom_exact_equality_accepted_and_one_hundredth_over_rejected
        """
        asset, first = self._plant_with_forty_held()

        assert asset["free_dispatchable_mwh"] == pytest.approx(70.0, abs=0.01)
        after = refresh_asset(asset["id"])
        assert after["free_dispatchable_mwh"] == pytest.approx(30.0, abs=0.01)
        assert first["status"] == "HELD"

    def test_a_request_for_exactly_the_remaining_headroom_is_held(self):
        """Equality is inside the budget, so the boundary request succeeds.

        PRD: "The fourth step is the acceptance test, and it is inclusive: the request is accepted when `reserved_mwh` is less than or equal to the available headroom."

        Design: Difficulty/boundary_precision_check/soc_headroom_exact_equality_accepted_and_one_hundredth_over_rejected
        """
        asset, first = self._plant_with_forty_held()

        second = hold_reservation(
            asset["id"],
            purpose="ANCILLARY",
            reserved_mwh=30.0,
            window_start=self.WINDOW[0],
            window_end=self.WINDOW[1],
        )

        assert second["status"] == "HELD"
        after = refresh_asset(asset["id"])
        assert after["reserved_mwh_total"] == pytest.approx(70.0, abs=0.01)
        assert after["free_dispatchable_mwh"] == pytest.approx(0.0, abs=0.01)

    def test_one_hundredth_beyond_an_exhausted_envelope_is_refused(self):
        """With zero headroom left, 0.01 MWh exceeds it and is rejected.

        PRD: "A request for exactly the remaining headroom succeeds; a request for one hundredth of a megawatt-hour more does not."

        Design: Difficulty/boundary_precision_check/soc_headroom_exact_equality_accepted_and_one_hundredth_over_rejected
        """
        asset, first = self._plant_with_forty_held()
        hold_reservation(
            asset["id"],
            purpose="ANCILLARY",
            reserved_mwh=30.0,
            window_start=self.WINDOW[0],
            window_end=self.WINDOW[1],
        )

        response = api_client.create_soc_reservation(
            create_soc_reservation_payload(
                asset["id"],
                refresh_asset(asset["id"])["version"],
                purpose="ANCILLARY",
                reserved_mwh=0.01,
                window_start=self.WINDOW[0],
                window_end=self.WINDOW[1],
            ),
            TRADER,
        )

        validate_error(response, "ERR_SOC_INSUFFICIENT")

    def test_the_refused_sliver_created_no_reservation(self):
        """Only the two accepted holds exist afterwards.

        PRD: "Checks run in a fixed order, and the first failing check decides the response; no later check runs, and no partial write survives a rejection."

        Design: Difficulty/boundary_precision_check/soc_headroom_exact_equality_accepted_and_one_hundredth_over_rejected
        """
        asset, first = self._plant_with_forty_held()
        second = hold_reservation(
            asset["id"],
            purpose="ANCILLARY",
            reserved_mwh=30.0,
            window_start=self.WINDOW[0],
            window_end=self.WINDOW[1],
        )
        api_client.create_soc_reservation(
            create_soc_reservation_payload(
                asset["id"],
                refresh_asset(asset["id"])["version"],
                purpose="ANCILLARY",
                reserved_mwh=0.01,
                window_start=self.WINDOW[0],
                window_end=self.WINDOW[1],
            ),
            TRADER,
        )

        rows, meta = validate_paginated(
            api_client.list_soc_reservations(
                TRADER, {"asset_id": asset["id"], "status": "HELD"}
            )
        )
        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {first["id"], second["id"]}


# The two boundary deliveries differ only in their fifth reading: 18.0 MW puts
# the composite exactly on the floor, 17.99 MW puts it one hundredth below.
_ON_FLOOR_RUN = [
    ("2026-08-10T14:10:00Z", 20.0, 78.0),
    ("2026-08-10T14:20:00Z", 20.0, 73.0),
    ("2026-08-10T14:30:00Z", 16.0, 69.0),
    ("2026-08-10T14:40:00Z", 16.0, 65.0),
    ("2026-08-10T14:50:00Z", 18.0, 60.5),
]
_BELOW_FLOOR_RUN = _ON_FLOOR_RUN[:4] + [("2026-08-10T14:50:00Z", 17.99, 60.5)]


def _scored_delivery(name, samples):
    """Run one 20 MW hour of delivery to completion and return the instruction."""
    asset = provision_asset(name=name)
    reservation = hold_reservation(
        asset["id"],
        reserved_mwh=40.0,
        window_start="2026-08-10T12:00:00Z",
        window_end="2026-08-10T20:00:00Z",
    )
    bid = cleared_bid(
        asset["id"],
        reservation["id"],
        cleared_price_usd_per_mwh=45.00,
        cleared_mw=20.0,
        delivery_start="2026-08-10T12:00:00Z",
        delivery_end="2026-08-10T16:00:00Z",
        offer_mw=20.0,
    )
    dispatch = executing_dispatch(
        bid["id"],
        asset["id"],
        instructed_mw=20.0,
        setpoint_start="2026-08-10T14:00:00Z",
        setpoint_end="2026-08-10T15:00:00Z",
    )
    append_samples(dispatch["id"], asset["id"], samples)
    return asset, complete_dispatch(dispatch["id"], asset["id"])


class TestPerformanceFloorBoundary:
    """One composite score exactly on 75.00 and one at 74.99."""

    def test_a_score_exactly_on_the_floor_is_charged_nothing(self):
        """Seventy-five is at the floor, so the settled charge term is zero.

        PRD: "A composite score at or above the performance floor of 75.00 therefore costs nothing, and every point below it costs four dollars per instructed megawatt."

        Design: Difficulty/boundary_precision_check/composite_score_exactly_at_performance_floor_charges_nothing
        """
        set_clock("2026-08-10T00:00:00Z")
        asset, completed = _scored_delivery("Boundary BESS A", _ON_FLOOR_RUN)

        settled = settle_score(completed["id"])

        assert settled["accuracy_score"] == pytest.approx(90.00, abs=0.01)
        assert settled["deadband_pct"] == pytest.approx(40.00, abs=0.01)
        assert settled["composite_score"] == pytest.approx(75.00, abs=0.01)
        assert settled["non_performance_charge_usd"] == pytest.approx(0.00, abs=0.01)
        assert settled["scoring_status"] == "SETTLED"

    def test_one_hundredth_of_a_point_below_the_floor_is_charged(self):
        """A 17.99 MW fifth reading drops the composite to 74.99 and costs 0.80 dollars.

        PRD: "`non_performance_charge_usd` is the greater of 0 and 75.00 minus `composite_score`, multiplied by `instructed_mw`, multiplied by 4.00 dollars, rounded half up to 2 decimal places."

        Design: Difficulty/boundary_precision_check/composite_score_exactly_at_performance_floor_charges_nothing
        """
        set_clock("2026-08-10T00:00:00Z")
        asset, completed = _scored_delivery("Boundary BESS B", _BELOW_FLOOR_RUN)

        settled = settle_score(completed["id"])

        assert settled["accuracy_score"] == pytest.approx(89.99, abs=0.01)
        assert settled["deadband_pct"] == pytest.approx(40.00, abs=0.01)
        assert settled["composite_score"] == pytest.approx(74.99, abs=0.01)
        assert settled["non_performance_charge_usd"] == pytest.approx(0.80, abs=0.01)
        assert settled["scoring_status"] == "SETTLED"

    def test_the_provisional_pass_scores_the_same_and_charges_nothing(self):
        """With every sample on time the two passes agree on the score, not on the charge.

        PRD: "Its `non_performance_charge_usd` is forced to 0.0 regardless of how poor the composite score is — the provisional pass never charges."

        Design: Difficulty/boundary_precision_check/composite_score_exactly_at_performance_floor_charges_nothing
        """
        set_clock("2026-08-10T00:00:00Z")
        asset_a, on_floor = _scored_delivery("Boundary BESS A", _ON_FLOOR_RUN)
        asset_b, below_floor = _scored_delivery("Boundary BESS B", _BELOW_FLOOR_RUN)

        assert on_floor["scoring_status"] == "PROVISIONAL"
        assert on_floor["composite_score"] == pytest.approx(75.00, abs=0.01)
        assert on_floor["non_performance_charge_usd"] == pytest.approx(0.00, abs=0.01)
        assert below_floor["scoring_status"] == "PROVISIONAL"
        assert below_floor["composite_score"] == pytest.approx(74.99, abs=0.01)
        assert below_floor["non_performance_charge_usd"] == pytest.approx(0.00, abs=0.01)

    def test_the_two_deliveries_differ_only_in_delivered_energy(self):
        """Quarter-hour aggregation gives 22.5 MWh against 22.498 MWh.

        PRD: "Delivered energy is aggregated from on-time telemetry only: taking the samples of this instruction whose `sampled_at` is at or before `setpoint_end`, `delivered_mwh` is the sum of each sample's `measured_mw` multiplied by a fixed sample width of one quarter of an hour, rounded half up to 3 decimal places."

        Design: Difficulty/boundary_precision_check/composite_score_exactly_at_performance_floor_charges_nothing
        """
        set_clock("2026-08-10T00:00:00Z")
        asset_a, on_floor = _scored_delivery("Boundary BESS A", _ON_FLOOR_RUN)
        asset_b, below_floor = _scored_delivery("Boundary BESS B", _BELOW_FLOOR_RUN)

        assert on_floor["delivered_mwh"] == pytest.approx(22.5, abs=0.01)
        assert below_floor["delivered_mwh"] == pytest.approx(22.498, abs=0.01)
        assert on_floor["telemetry_sample_count"] == 5
        assert below_floor["telemetry_sample_count"] == 5
