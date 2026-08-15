"""Tests for compensating invariants: fluid volume and invoice balance."""
import pytest

from test_helpers import (

    TEST_USERS,
    setup_invoice_for_cleared_operation,
    setup_operation_cleared,
    validate_success,
)


class TestFluidVolumeInvariant:
    def test_fluid_volume_complete_then_void(self, api):
        """PRD §3.6: "Voiding moves the operation to `VOIDED` and applies exact
        compensation: the operation's `actual_liters` are added back to the
        tank's `on_hand_liters`, restoring the pre-completion volume precisely,
        and its `collected_liters` are withdrawn from the station's
        `collected_pool_liters`."

        Design: Difficulty/compensating_invariant/fluid_volume_complete_then_void
        """
        station, permit, tank, pad, airline, request, operation = (
            setup_operation_cleared(actual_liters=600, collected_liters=400)
        )

        # Mid-chain state after completion and clearing.
        resp = api.get_fluid_tank(
            tank["id"], TEST_USERS["pad_operator_headers"]
        )
        tank_mid = validate_success(resp)
        assert tank_mid["on_hand_liters"] == 19400

        resp = api.get_station(
            station["id"], TEST_USERS["station_admin_headers"]
        )
        station_mid = validate_success(resp)
        assert station_mid["collected_pool_liters"] == 400

        # Void the operation.
        resp = api.void_deice_operation(
            operation["id"], TEST_USERS["pad_operator_headers"]
        )
        assert validate_success(resp)["status"] == "VOIDED"

        # Invariants restored exactly.
        resp = api.get_fluid_tank(
            tank["id"], TEST_USERS["pad_operator_headers"]
        )
        tank_end = validate_success(resp)
        assert tank_end["on_hand_liters"] == 20000

        resp = api.get_station(
            station["id"], TEST_USERS["station_admin_headers"]
        )
        station_end = validate_success(resp)
        assert station_end["collected_pool_liters"] == 0

    def test_fluid_volume_invariant_is_exact_not_approximate(self, api):
        """PRD §3.6: "Voiding moves the operation to `VOIDED` and applies exact
        compensation: the operation's `actual_liters` are added back to the
        tank's `on_hand_liters`, restoring the pre-completion volume precisely,
        and its `collected_liters` are withdrawn from the station's
        `collected_pool_liters`. Tank status and station posture and alert are
        recomputed, the operation's `version` increments, and the pad —
        already `AVAILABLE` since clearing — is unaffected. Voiding is a data
        correction, not an operational undo: the originating request remains
        `COMPLETED`."

        Design: Difficulty/compensating_invariant/fluid_volume_complete_then_void
        """
        station, permit, tank, pad, airline, request, operation = (
            setup_operation_cleared(actual_liters=600, collected_liters=400)
        )

        # Capture pre-void versions.
        resp = api.get_deice_operation(
            operation["id"], TEST_USERS["pad_operator_headers"]
        )
        op_before = validate_success(resp)
        assert op_before["status"] == "CLEARED"

        # Void.
        resp = api.void_deice_operation(
            operation["id"], TEST_USERS["pad_operator_headers"]
        )
        op_after = validate_success(resp)
        assert op_after["status"] == "VOIDED"
        assert op_after["version"] == op_before["version"] + 1

        # Request remains COMPLETED.
        resp = api.get_deice_request(
            request["id"], TEST_USERS["pad_operator_headers"]
        )
        assert validate_success(resp)["status"] == "COMPLETED"

        # Pad remains AVAILABLE.
        resp = api.get_pad(pad["id"], TEST_USERS["pad_operator_headers"])
        assert validate_success(resp)["status"] == "AVAILABLE"
