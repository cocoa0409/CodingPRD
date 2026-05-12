"""Session lifecycle: entry, exit, pay, waive — and parallel state
dimensions occupancy_status × payment_status (PRD §3.5, §2.8)."""
from __future__ import annotations

import pytest

from test_helpers import (
    add_hours,
    advance_clock,
    bind_vehicle_to_card,
    create_card,
    create_session_payload,
    create_vehicle,
    exit_session,
    get_card,
    get_session,
    get_space,
    list_audit_logs,
    make_driver_headers,
    open_session,
    pay_session,
    pay_session_payload,
    recharge_card,
    setup_basic_session_scenario,
    setup_lot_zone_spaces,
    setup_paid_session_for_refund,
    setup_session_with_storedvalue_card,
    unique_external_ref,
    validate_error,
    validate_success,
    waive_session_payload,
)


# ===========================================================================
# §3.5 / §2.8 — Entry side effects
# ===========================================================================
class TestSessionEntry:
    def test_entry_flips_space_to_occupied(self, api):
        """PRD §2.8: 'A successful gate-in atomically transitions
        Space.occupancy_status from FREE to OCCUPIED, sets
        Space.current_session_id to the new session.'"""
        scen = setup_basic_session_scenario(
            base_iso="2026-09-01T10:00:00.000Z"
        )
        sp = get_space(
            scen["lot"]["id"], scen["zone"]["id"], scen["space"]["id"]
        )
        assert sp["occupancy_status"] == "OCCUPIED"
        assert sp["current_session_id"] == scen["session"]["id"]

    def test_entry_into_occupied_space_rejected(self, api):
        """PRD §3.5: 'Entry is admitted only when the chosen space's
        occupancy_status equals FREE ... otherwise the request is rejected
        with ERR_SPACE_OCCUPIED (the space is currently occupied by a
        different session).'"""
        scen = setup_basic_session_scenario(
            base_iso="2026-09-02T10:00:00.000Z"
        )
        v2 = create_vehicle()
        # Try to open second session on same space.
        from test_helpers import TEST_USERS
        res = api.create_session(
            scen["lot"]["id"],
            create_session_payload(
                vehicle_id=v2["id"], space_id=scen["space"]["id"]
            ),
            TEST_USERS["gate_headers"],
        )
        validate_error(res, "ERR_SPACE_OCCUPIED")


# ===========================================================================
# §3.5 / §2.8 — Exit side effects
# ===========================================================================
class TestSessionExit:
    def test_exit_pins_exit_at_and_final_fee(self, api):
        """PRD §3.5: 'Exiting the session pins exit_at to the current
        instant, runs the final-settlement variant of session billing to
        pin final_fee_cents and billing_kind, transitions occupancy_status
        from ACTIVE to EXITED.'"""
        scen = setup_basic_session_scenario(
            base_iso="2026-09-03T10:00:00.000Z",
            free_minutes=0, hourly_rate_cents=400, daily_cap_cents=2000,
        )
        advance_clock("2026-09-03T11:00:00.000Z")
        exit_session(scen["session"]["id"])
        sess = get_session(scen["session"]["id"])
        assert sess["occupancy_status"] == "EXITED"
        assert sess["payment_status"] == "UNPAID"
        assert sess["exit_at"] == "2026-09-03T11:00:00.000Z"
        assert sess["final_fee_cents"] == 400
        assert sess["billing_kind"] == "HOURLY"

    def test_exit_frees_space_and_sets_last_exited_at(self, api):
        """PRD §3.5: 'transitions the holding space's occupancy_status from
        OCCUPIED to FREE, sets Space.last_exited_at equal to exit_at, clears
        Space.current_session_id.'"""
        scen = setup_basic_session_scenario(
            base_iso="2026-09-04T10:00:00.000Z",
            free_minutes=0, hourly_rate_cents=400,
        )
        advance_clock("2026-09-04T11:00:00.000Z")
        exit_session(scen["session"]["id"])
        sp = get_space(
            scen["lot"]["id"], scen["zone"]["id"], scen["space"]["id"]
        )
        assert sp["occupancy_status"] == "FREE"
        assert sp["last_exited_at"] == "2026-09-04T11:00:00.000Z"
        assert sp.get("current_session_id") is None


# ===========================================================================
# §3.5 — Pay session
# ===========================================================================
class TestSessionPay:
    def test_pay_active_session_rejected_invalid_state(self, api):
        """PRD §3.5: 'Payment is admitted only on a session whose
        occupancy_status is EXITED and whose final_fee_cents is pinned.'
        PRD §2.7: state-machine eligibility yields ERR_INVALID_STATE."""
        scen = setup_basic_session_scenario(
            base_iso="2026-09-05T10:00:00.000Z"
        )
        # session is ACTIVE
        headers = make_driver_headers(scen["vehicle"]["id"])
        res = api.pay_session(
            scen["session"]["id"], pay_session_payload(), headers
        )
        validate_error(res, "ERR_INVALID_STATE")

    def test_pay_exempt_vehicle_session_rejected(self, api):
        """PRD §3.5: 'When the session's vehicle is EMERGENCY or DISABLED,
        the request is rejected with ERR_EXEMPT_VEHICLE.'"""
        scen = setup_basic_session_scenario(
            base_iso="2026-09-06T10:00:00.000Z",
            vehicle_kind="EMERGENCY",
            free_minutes=0,
            hourly_rate_cents=400,
        )
        advance_clock("2026-09-06T11:00:00.000Z")
        exit_session(scen["session"]["id"])
        headers = make_driver_headers(scen["vehicle"]["id"])
        res = api.pay_session(
            scen["session"]["id"], pay_session_payload(), headers
        )
        validate_error(res, "ERR_EXEMPT_VEHICLE")

    def test_pay_with_insufficient_balance_rejected(self, api):
        """PRD §3.5: 'When a STORED_VALUE card is used, the card's
        balance_cents must be at least final_fee_cents; otherwise
        ERR_INSUFFICIENT_BALANCE.'"""
        # set up a session pinned to a card with 0 balance
        scen = setup_session_with_storedvalue_card(
            base_iso="2026-09-07T10:00:00.000Z",
            free_minutes=0, hourly_rate_cents=400,
            initial_balance_cents=0,
            auto_pay_enabled=False,
        )
        advance_clock("2026-09-07T11:00:00.000Z")
        exit_session(scen["session"]["id"])
        headers = make_driver_headers(scen["vehicle"]["id"])
        res = api.pay_session(
            scen["session"]["id"],
            pay_session_payload(card_id=scen["card"]["id"]),
            headers,
        )
        validate_error(res, "ERR_INSUFFICIENT_BALANCE")

    def test_pay_debits_storedvalue_balance(self, api):
        """PRD §3.5: 'On success, a SESSION_FEE Payment is created,
        payment_status transitions from UNPAID to PAID, the stored-value
        card's balance_cents is debited by final_fee_cents.'"""
        scen = setup_paid_session_for_refund(
            base_iso="2026-09-08T09:00:00.000Z",
            final_fee_cents=400,
            initial_balance_cents=5000,
        )
        # session was paid in fixture; final balance = 5000 - 400 = 4600
        card = get_card(scen["card"]["id"])
        assert card["balance_cents"] == 4600
        sess = get_session(scen["session"]["id"])
        assert sess["payment_status"] == "PAID"


# ===========================================================================
# §3.5 — Waive session
# ===========================================================================
class TestSessionWaive:
    def test_waive_unpaid_exited_session(self, api, operator_headers):
        """PRD §3.5: 'An Operator may waive an unpaid session by supplying
        a non-empty reason. Waivers are admitted only on EXITED sessions;
        they transition payment_status from UNPAID to WAIVED.'"""
        scen = setup_basic_session_scenario(
            base_iso="2026-09-09T10:00:00.000Z",
            free_minutes=0, hourly_rate_cents=400,
        )
        advance_clock("2026-09-09T11:00:00.000Z")
        exit_session(scen["session"]["id"])
        res = api.waive_session(
            scen["session"]["id"],
            waive_session_payload(reason="goodwill"),
            operator_headers,
        )
        validate_success(res, expected_status=200)
        sess = get_session(scen["session"]["id"])
        assert sess["payment_status"] == "WAIVED"

    def test_waive_active_session_rejected_invalid_state(self, api, operator_headers):
        """PRD §3.5: 'Waivers are admitted only on EXITED sessions.'
        PRD §2.7: state-machine eligibility yields ERR_INVALID_STATE."""
        scen = setup_basic_session_scenario(
            base_iso="2026-09-10T10:00:00.000Z"
        )
        res = api.waive_session(
            scen["session"]["id"],
            waive_session_payload(reason="goodwill"),
            operator_headers,
        )
        validate_error(res, "ERR_INVALID_STATE")

    def test_waive_without_reason_rejected(self, api, operator_headers):
        """PRD §2.11: 'A missing or empty reason on any such action is
        rejected with ERR_REASON_REQUIRED.'"""
        scen = setup_basic_session_scenario(
            base_iso="2026-09-11T10:00:00.000Z",
            free_minutes=0, hourly_rate_cents=400,
        )
        advance_clock("2026-09-11T11:00:00.000Z")
        exit_session(scen["session"]["id"])
        res = api.waive_session(
            scen["session"]["id"], {"reason": ""}, operator_headers
        )
        validate_error(res, "ERR_REASON_REQUIRED")

    def test_waive_writes_audit_log(self, api, auditor_headers, operator_headers):
        """PRD §2.11: 'When the action proceeds, the server appends an
        AuditLog row whose action is one of BILLING_ADJUSTMENT,
        RESERVATION_CHANGE, FINE_WAIVE, or CARD_TRANSFER.'"""
        scen = setup_basic_session_scenario(
            base_iso="2026-09-12T10:00:00.000Z",
            free_minutes=0, hourly_rate_cents=400,
        )
        advance_clock("2026-09-12T11:00:00.000Z")
        exit_session(scen["session"]["id"])
        api.waive_session(
            scen["session"]["id"], waive_session_payload(reason="custom"),
            operator_headers,
        )
        logs = list_audit_logs(
            params={"subject_id": scen["session"]["id"], "limit": 20}
        )
        kinds = {l.get("action") for l in logs}
        assert "BILLING_ADJUSTMENT" in kinds
