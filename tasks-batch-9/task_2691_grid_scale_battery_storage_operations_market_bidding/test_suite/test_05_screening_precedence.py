"""Which refusal wins when a single request breaks two rules at once.

The screening order is banded, and these pairs sit either side of a band edge:
a state guard outranks the safety gate, and the market-availability gate
outranks the energy-headroom budget.
"""
import pytest
from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers.api_client import api_client
from test_helpers.factories import (
    create_capacity_test_payload,
    create_soc_reservation_payload,
)
from test_helpers.fixtures import (
    ASSET_MANAGER,
    make_site_controller_headers,
    TRADER,
    commission_asset,
    lockout_asset,
    refresh_asset,
    refresh_test,
    reference_plant,
    register_asset,
    schedule_test,
    set_clock,
    start_test,
)


class TestStateGuardOutranksSafetyGate:
    """A running capacity test on a plant that has since locked itself out."""

    def _running_test_on_a_locked_out_plant(self):
        set_clock("2026-08-01T00:00:00Z")
        asset = reference_plant()
        test = schedule_test(asset["id"], scheduled_date="2026-08-05T00:00:00Z")
        start_test(test["id"], asset["id"])
        lockout_asset(asset["id"])
        return asset, test

    def test_starting_a_running_test_again_reports_the_state_error(self):
        """The test is already discharging, and that refusal comes before the safety gate.

        PRD: "The order is deliberately banded: authentication and shape, then existence, then identity and state, then safety and regulatory compliance, then referential and temporal constraints, and finally capacity, cycle and fiscal budgets."

        Design: Difficulty/priority_pair_validation_conflict/state_error_outranks_safety_lockout_on_capacity_test_start
        """
        asset, test = self._running_test_on_a_locked_out_plant()

        response = api_client.start_capacity_test(
            test["id"], make_site_controller_headers(asset["id"])
        )

        validate_error(response, "ERR_TEST_NOT_SCHEDULED")
        assert refresh_asset(asset["id"])["safety_state"] == "LOCKOUT"
        assert refresh_test(test["id"])["status"] == "IN_PROGRESS"

    def test_scheduling_a_fresh_test_reports_the_safety_lockout(self):
        """With no state guard in the way, the lockout is the refusal the caller sees.

        PRD: "While the asset's `safety_state` is `LOCKOUT`, every write outside the safety-event surface is refused with `ERR_ASSET_SAFETY_LOCKOUT` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/state_error_outranks_safety_lockout_on_capacity_test_start
        """
        asset, test = self._running_test_on_a_locked_out_plant()

        response = api_client.create_capacity_test(
            create_capacity_test_payload(
                asset["id"], scheduled_date="2026-08-20T00:00:00Z"
            ),
            ASSET_MANAGER,
        )

        validate_error(response, "ERR_ASSET_SAFETY_LOCKOUT")

    def test_neither_refusal_created_or_advanced_a_capacity_test(self):
        """A refused request leaves no partial write behind.

        PRD: "Checks run in a fixed order, and the first failing check decides the response; no later check runs, and no partial write survives a rejection."

        Design: Difficulty/priority_pair_validation_conflict/state_error_outranks_safety_lockout_on_capacity_test_start
        """
        asset, test = self._running_test_on_a_locked_out_plant()

        api_client.start_capacity_test(test["id"], make_site_controller_headers(asset["id"]))
        api_client.create_capacity_test(
            create_capacity_test_payload(
                asset["id"], scheduled_date="2026-08-20T00:00:00Z"
            ),
            ASSET_MANAGER,
        )

        listing, meta = validate_paginated(
            api_client.list_capacity_tests(ASSET_MANAGER, {"asset_id": asset["id"]})
        )
        assert meta["total_count"] == 1
        assert listing[0]["id"] == test["id"]


class TestMarketGateOutranksEnergyBudget:
    """A 90 MWh reservation request against a 70 MWh envelope on an offline plant."""

    def _oversized_request(self, asset):
        return create_soc_reservation_payload(
            asset["id"],
            refresh_asset(asset["id"])["version"],
            purpose="ENERGY_ARBITRAGE",
            reserved_mwh=90.0,
            window_start="2026-08-10T12:00:00Z",
            window_end="2026-08-10T20:00:00Z",
        )

    def test_an_offline_plant_reports_market_availability_first(self):
        """A plant that was never commissioned is refused before its headroom is measured.

        PRD: "The market-availability gate — `ERR_ASSET_NOT_MARKET_AVAILABLE` (HTTP 409) — guards reservation creation, offer drafting, offer submission, offer revision, clearing-result posting, dispatch-instruction creation and dispatch acceptance."

        Design: Difficulty/priority_pair_validation_conflict/market_availability_outranks_soc_insufficiency_on_reservation_create
        """
        set_clock("2026-08-01T00:00:00Z")
        asset = register_asset()

        response = api_client.create_soc_reservation(
            self._oversized_request(asset), TRADER
        )

        validate_error(response, "ERR_ASSET_NOT_MARKET_AVAILABLE")
        assert asset["market_state"] == "OFFLINE"
        assert asset["safety_state"] == "NORMAL"

    def test_the_same_request_then_reports_insufficient_headroom(self):
        """Once the plant is market-available the energy budget is what refuses the request.

        PRD: "A reservation request fits the asset's remaining state-of-charge headroom."

        Design: Difficulty/priority_pair_validation_conflict/market_availability_outranks_soc_insufficiency_on_reservation_create
        """
        set_clock("2026-08-01T00:00:00Z")
        asset = register_asset()
        commissioned = commission_asset(asset["id"])

        response = api_client.create_soc_reservation(
            self._oversized_request(asset), TRADER
        )

        assert commissioned["market_state"] == "AVAILABLE"
        validate_error(response, "ERR_SOC_INSUFFICIENT")

    def test_neither_refusal_withheld_any_energy(self):
        """Two refused reservation requests leave the plant's reservation ledger at zero.

        PRD: "Checks run in a fixed order, and the first failing check decides the response; no later check runs, and no partial write survives a rejection."

        Design: Difficulty/priority_pair_validation_conflict/market_availability_outranks_soc_insufficiency_on_reservation_create
        """
        set_clock("2026-08-01T00:00:00Z")
        asset = register_asset()

        api_client.create_soc_reservation(self._oversized_request(asset), TRADER)
        commission_asset(asset["id"])
        api_client.create_soc_reservation(self._oversized_request(asset), TRADER)

        after = refresh_asset(asset["id"])
        assert after["reserved_mwh_total"] == pytest.approx(0.0, abs=0.01)
        listing, meta = validate_paginated(
            api_client.list_soc_reservations(TRADER, {"asset_id": asset["id"]})
        )
        assert meta["total_count"] == 0
        assert listing == []
