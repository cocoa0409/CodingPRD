"""Cancellation semantics: parallel booking/billing dimensions, entitlement invariant,
terminal lockdown."""
import pytest

from test_helpers import (
    ApiErrorId,
    assign_booking_ok,
    cancel_booking_ok,
    confirm_booking_ok,
    create_aircraft,
    create_booking_ok,
    create_confirmed_booking,
    get_booking,
    get_share,
    make_owner_headers,
    setup_program_with_share,
    validate_error_is_one_of,
    validate_success,
)
from test_helpers import TEST_USERS

FLEET = TEST_USERS["fleet_ops_headers"]


class TestParallelDimensions:
    def test_confirm_moves_scheduling_and_billing_together(self, api):
        """PRD §3.3: "Upon confirmation the estimated hours are debited provisionally
        from the share, the share's `version` advances, `billing_status` becomes
        `PROVISIONALLY_BILLED`"

        Design: Difficulty/non_linear_state_machine/booking_parallel_dims_scheduling_x_billing
        """
        sc = setup_program_with_share(program_code="FJX-NL2", class_code="MID")
        booking = create_booking_ok(
            sc["share"]["id"], sc["owner"]["id"], sc["cls"]["id"],
            "2026-09-10T15:00:00Z", 2.00,
            expected_share_version=sc["share"]["version"],
        )
        assert booking["booking_status"] == "REQUESTED"
        assert booking["billing_status"] == "UNBILLED"
        confirmed = confirm_booking_ok(booking["id"], sc["owner"]["id"])
        assert confirmed["booking_status"] == "CONFIRMED"
        assert confirmed["billing_status"] == "PROVISIONALLY_BILLED", (
            "confirmation moves the billing dimension to PROVISIONALLY_BILLED"
        )
        assert get_share(sc["share"]["id"])["hours_remaining_cy"] == pytest.approx(98.00, abs=0.005)

    def test_cancel_reverts_billing_while_scheduling_goes_terminal(self, api):
        """PRD §3.3: "Cancelling a confirmed booking restores the provisionally debited
        `estimated_block_hours` to the share's remaining balance — a compensating
        re-credit that preserves the entitlement invariant — returns `billing_status` to
        `UNBILLED`, voids any provisional lines for the booking at the next aggregation,
        and advances the share's `version`."

        Design: Difficulty/non_linear_state_machine/booking_parallel_dims_scheduling_x_billing
        """
        sc = setup_program_with_share(program_code="FJX-NL2B", class_code="MID")
        booking = create_confirmed_booking(
            sc["share"]["id"], sc["owner"]["id"], sc["cls"]["id"],
            "2026-09-10T15:00:00Z", 2.00,
        )
        cancelled = cancel_booking_ok(booking["id"], sc["owner"]["id"])
        assert cancelled["booking_status"] == "CANCELLED", "scheduling dimension goes terminal"
        assert cancelled["billing_status"] == "UNBILLED", (
            "billing dimension reverts to UNBILLED — independent of the terminal booking status"
        )
        assert get_share(sc["share"]["id"])["hours_remaining_cy"] == pytest.approx(100.00, abs=0.005)


class TestConfirmCancelInvariant:
    def test_confirm_debits_estimated_hours(self, api):
        """PRD §3.3: "Upon confirmation the estimated hours are debited provisionally
        from the share"

        Design: Difficulty/compensating_invariant/entitlement_hours_confirm_cancel_invariant
        """
        sc = setup_program_with_share(program_code="FJX-CI1", class_code="MID")
        booking = create_confirmed_booking(
            sc["share"]["id"], sc["owner"]["id"], sc["cls"]["id"],
            "2026-09-10T15:00:00Z", 3.50,
        )
        assert booking["booking_status"] == "CONFIRMED"
        assert get_share(sc["share"]["id"])["hours_remaining_cy"] == pytest.approx(96.50, abs=0.005), (
            "100.00 - 3.50 provisional debit"
        )

    def test_cancel_restores_full_balance_exactly(self, api):
        """PRD §3.3: "Cancelling a confirmed booking restores the provisionally debited
        `estimated_block_hours` to the share's remaining balance — a compensating
        re-credit that preserves the entitlement invariant"

        Design: Difficulty/compensating_invariant/entitlement_hours_confirm_cancel_invariant
        """
        sc = setup_program_with_share(program_code="FJX-CI1B", class_code="MID")
        booking = create_confirmed_booking(
            sc["share"]["id"], sc["owner"]["id"], sc["cls"]["id"],
            "2026-09-10T15:00:00Z", 3.50,
        )
        assert get_share(sc["share"]["id"])["hours_remaining_cy"] == pytest.approx(96.50, abs=0.005)
        cancel_booking_ok(booking["id"], sc["owner"]["id"])
        restored = get_share(sc["share"]["id"])["hours_remaining_cy"]
        assert restored == pytest.approx(100.00, abs=0.005), (
            f"confirm(x) then cancel(x) must leave the balance unchanged; got {restored}"
        )


class TestTerminalLockdown:
    def test_cancelled_booking_rejects_further_actions(self, api):
        """PRD §2.8: "The target entity is in a state that permits the requested
        transition — otherwise `ERR_INVALID_STATE` (HTTP 409); attempts to move an entity
        that has already reached a terminal state are rejected with
        `ERR_ALREADY_TERMINAL` (HTTP 409)."

        Design: Corner/state_machines/booking_terminal_cancelled_lockdown
        """
        sc = setup_program_with_share(program_code="FJX-SM1", class_code="MID")
        tail = create_aircraft(sc["program"]["id"], sc["cls"]["id"], tail_number="N900SM")
        booking = create_booking_ok(
            sc["share"]["id"], sc["owner"]["id"], sc["cls"]["id"],
            "2026-09-10T15:00:00Z", 1.00,
            expected_share_version=sc["share"]["version"],
        )
        cancel_booking_ok(booking["id"], sc["owner"]["id"])
        resp = api.assign_booking(booking["id"], {"aircraft_id": tail["id"]}, FLEET)
        validate_error_is_one_of(
            resp, [ApiErrorId.ERR_ALREADY_TERMINAL, ApiErrorId.ERR_INVALID_STATE]
        )
        assert resp.status_code == 409
        after = get_booking(booking["id"])
        assert after["booking_status"] == "CANCELLED"
        assert after["assigned_aircraft_id"] is None
