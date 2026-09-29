"""Writes settle inside their own request: nothing is deferred to a later pass."""

from __future__ import annotations

import pytest
from prd_bench_local_runner.testing import get_success_data

from test_helpers import AUDIT_INSPECTOR, LOAD_CONTROLLER, api_client
from test_helpers import assertions as A
from test_helpers import fixtures as fx

_BALANCE_CHAIN = (
    "status",
    "base_payload_kg",
    "planned_payload_kg",
    "zero_fuel_weight_kg",
    "index_zfw",
    "mac_zfw_pct",
    "takeoff_weight_kg",
    "index_tow",
    "mac_tow_pct",
    "taxi_weight_kg",
    "landing_weight_kg",
    "underload_kg",
    "frozen_underload_kg",
    "restriction_status",
    "envelope_ok",
)


class TestComputeSettlesWithinItsOwnResponse:
    def test_the_compute_answer_and_the_reads_that_follow_agree_field_for_field(self):
        """One call publishes the whole chain; the immediate reads add nothing.

        PRD: "Unless otherwise noted, operations that create or modify a resource will
        return the created or updated resource object in the data field."

        Design: Corner/consistency_model/compute_response_already_carries_the_recomputed_figures
        """
        world = fx.fx_a(flight_overrides={"flight_number": "LX1602"})

        response = api_client.compute_load_plan(world.plan_id, LOAD_CONTROLLER)

        computed = get_success_data(response, 200)
        A.assert_plan_figures(
            computed,
            status="COMPUTED",
            base_payload_kg=6100.00,
            planned_payload_kg=6100.00,
            zero_fuel_weight_kg=48650.00,
            index_zfw=78.66,
            mac_zfw_pct=14.03,
            takeoff_weight_kg=58200.00,
            index_tow=87.26,
            mac_tow_pct=15.24,
            taxi_weight_kg=58450.00,
            landing_weight_kg=51300.00,
            underload_kg=14080.00,
            frozen_underload_kg=14080.00,
            restriction_status="UNRESTRICTED",
            envelope_ok=True,
        )

        read_back = get_success_data(
            api_client.get_load_plan(world.plan_id, AUDIT_INSPECTOR), 200
        )
        flight = get_success_data(
            api_client.get_flight(world.flight_id, AUDIT_INSPECTOR), 200
        )

        for field in _BALANCE_CHAIN:
            assert read_back.get(field) == computed.get(field), (
                f"the plan read should return {field} as {computed.get(field)!r} "
                f"but returned {read_back.get(field)!r}"
            )
        A.assert_flight_state(flight, status="LOAD_CONTROLLED")
        A.assert_flight_capacity(flight, allowed_payload_kg=20180.00)
