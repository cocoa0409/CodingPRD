"""Delinquency escalation, disconnect gates, reconnection, and member suspension."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    bill_cycle_with_readings,
    close_cycle,
    get_cycle_invoice,
    get_success_data,
    issue_boil_order,
    open_cycle,
    pay_invoice,
    set_clock,
    setup_billed_invoice,
    setup_disconnect_eligible_scenario,
    setup_disconnected_tap_scenario,
    setup_member_with_installed_tap,
    validate_error,
)
from test_helpers.constants import (
    CLOCK_DUE_PLUS_10D,
    CLOCK_DUE_PLUS_45D,
    CYCLE_2,
    CYCLE_3,
    CYCLE_4,
)
from test_helpers.fixtures import CLERK, FIELD, TREASURER

EARLY_DUE = "2026-08-10T00:00:00Z"


class TestDisconnectGates:
    def test_disconnect_during_boil_order_surfaces_moratorium(self, api):
        """PRD section 2.7: "a mid-flight boil order surfaces as
        `ERR_BOIL_ORDER_MORATORIUM` rather than being masked by a later fiscal
        check". PRD section 3.6: "if any boil order is `IN_EFFECT` for the
        district, no disconnect proceeds, rejected with
        `ERR_BOIL_ORDER_MORATORIUM` (HTTP 409)." Here the invoice is also not yet
        disconnect-eligible, and the moratorium still wins.

        Design: Difficulty/priority_pair_validation_conflict/disconnect_boil_moratorium_vs_not_eligible_priority
        """
        ctx = setup_billed_invoice(usage_gallons=3000)  # invoice CURRENT, due 2026-09-10
        district = ctx["district"]
        issue_boil_order(district["id"], at_iso="2026-08-05T12:00:00Z", reason="Turbidity exceedance")
        resp = api.disconnect_tap(district["id"], ctx["tap"]["id"], FIELD)
        validate_error(resp, ApiErrorId.ERR_BOIL_ORDER_MORATORIUM, expected_status=409)
        after = get_success_data(api.get_tap(district["id"], ctx["tap"]["id"], FIELD))
        assert after["status"] == "INSTALLED"

    def test_disconnect_with_current_invoice_surfaces_not_eligible(self, api):
        """PRD section 3.6: "every unpaid invoice on the tap must be in
        `DISCONNECT_ELIGIBLE` status, else `ERR_NOT_DISCONNECT_ELIGIBLE`
        (HTTP 409)." With no boil order in effect, a tap whose only invoice is
        still CURRENT is rejected on the fiscal gate.

        Design: Difficulty/priority_pair_validation_conflict/disconnect_boil_moratorium_vs_not_eligible_priority
        """
        ctx = setup_billed_invoice(usage_gallons=3000)
        district = ctx["district"]
        resp = api.disconnect_tap(district["id"], ctx["tap"]["id"], FIELD)
        validate_error(resp, ApiErrorId.ERR_NOT_DISCONNECT_ELIGIBLE, expected_status=409)
        after = get_success_data(api.get_tap(district["id"], ctx["tap"]["id"], FIELD))
        assert after["status"] == "INSTALLED"


class TestCrossEntityDisconnectGate:
    def test_disconnect_rejected_before_eligibility(self, api):
        """PRD section 3.6: "every unpaid invoice on the tap must be in
        `DISCONNECT_ELIGIBLE` status, else `ERR_NOT_DISCONNECT_ELIGIBLE`
        (HTTP 409)." A NOTICED invoice (10 days past due) is not yet eligible.

        Design: Difficulty/cross_entity_state_dependency/tap_disconnect_gated_by_invoice_collection_state
        """
        ctx = setup_billed_invoice(usage_gallons=2001, due_date_utc=EARLY_DUE)  # total 3950
        district = ctx["district"]
        set_clock(CLOCK_DUE_PLUS_10D)
        noticed = get_success_data(api.issue_notice(district["id"], ctx["invoice"]["id"], CLERK))
        assert noticed["collection_status"] == "NOTICED"
        resp = api.disconnect_tap(district["id"], ctx["tap"]["id"], FIELD)
        validate_error(resp, ApiErrorId.ERR_NOT_DISCONNECT_ELIGIBLE, expected_status=409)
        after = get_success_data(api.get_tap(district["id"], ctx["tap"]["id"], FIELD))
        assert after["status"] == "INSTALLED"

    def test_disconnect_cascades_once_invoices_eligible(self, api):
        """PRD section 3.6: "A `NOTICED` invoice at least 45 days past due becomes
        `DISCONNECT_ELIGIBLE` — a 45-day-old invoice is eligible, the comparison
        is inclusive." and "Disconnecting moves the tap `INSTALLED → DISCONNECTED`
        (or `RECONNECTED → DISCONNECTED`), cascades each unpaid invoice on the tap
        to collection status `DISCONNECTED` with its `days_past_due` frozen, and —
        when that was the member's last active tap and any invoice remains unpaid —
        moves the member `ACTIVE → SUSPENDED`."

        Design: Difficulty/cross_entity_state_dependency/tap_disconnect_gated_by_invoice_collection_state
        """
        ctx = setup_disconnect_eligible_scenario(first_usage=2001, second_usage_register=2001)
        district = ctx["district"]
        invoice1 = ctx["invoice1"]
        assert invoice1["collection_status"] == "DISCONNECT_ELIGIBLE", (
            "45 days past due at the second bill cascade must advance NOTICED to "
            f"DISCONNECT_ELIGIBLE, got {invoice1['collection_status']}"
        )
        days_at_disconnect = invoice1["days_past_due"]
        assert days_at_disconnect == 45

        tap = get_success_data(api.disconnect_tap(district["id"], ctx["tap"]["id"], FIELD))
        assert tap["status"] == "DISCONNECTED"
        invoice1_after = get_success_data(api.get_invoice(district["id"], invoice1["id"], CLERK))
        assert invoice1_after["collection_status"] == "DISCONNECTED"
        member_after = get_success_data(api.get_member(district["id"], ctx["member"]["id"], CLERK))
        assert member_after["membership_status"] == "SUSPENDED"

        # days_past_due is frozen at disconnect: further clock movement must not move it.
        set_clock("2026-10-09T00:00:00Z")
        frozen = get_success_data(api.get_invoice(district["id"], invoice1["id"], CLERK))
        assert frozen["days_past_due"] == days_at_disconnect


class TestPaymentCascadeToReconnect:
    def test_reconnect_rejected_while_balance_outstanding(self, api):
        """PRD section 3.6: "Reconnection of a `DISCONNECTED` tap by a
        `FieldOperator` requires every invoice on the tap to be `PAID` — any
        balance outstanding yields `ERR_OUTSTANDING_BALANCE` (HTTP 402)."

        Design: Difficulty/transitive_cascade/payment_in_full_cascade_depth2
        """
        ctx = setup_disconnected_tap_scenario(first_usage=4300, second_usage_register=4300)
        district = ctx["district"]
        assert ctx["tap"]["status"] == "DISCONNECTED"
        assert ctx["member"]["membership_status"] == "SUSPENDED"
        resp = api.reconnect_tap(district["id"], ctx["tap"]["id"], FIELD)
        validate_error(resp, ApiErrorId.ERR_OUTSTANDING_BALANCE, expected_status=402)
        after = get_success_data(api.get_tap(district["id"], ctx["tap"]["id"], FIELD))
        assert after["status"] == "DISCONNECTED"

    def test_full_payment_cures_and_reconnect_restores_member(self, api):
        """PRD section 3.6: "Paying an invoice in full always returns its
        collection status to `CURRENT` from `DELINQUENT`, `NOTICED`,
        `DISCONNECT_ELIGIBLE`, or `DISCONNECTED`." and "Reconnection arms a
        `pending_reconnect_fee` flag on the tap so that the next issued invoice
        carries `reconnect_fee_cents` from that cycle's pinned schedule (the flag
        clears once billed), moves the tap to `RECONNECTED`, and restores a
        `SUSPENDED` member to `ACTIVE`."

        Design: Difficulty/transitive_cascade/payment_in_full_cascade_depth2
        """
        ctx = setup_disconnected_tap_scenario(first_usage=4300, second_usage_register=4300)
        district = ctx["district"]
        member = ctx["member"]
        invoice1 = ctx["invoice1"]
        assert invoice1["total_cents"] == 4850

        pay_invoice(district["id"], member["id"], invoice1["id"], 4850)
        paid = get_success_data(api.get_invoice(district["id"], invoice1["id"], TREASURER))
        assert paid["billing_status"] == "PAID"
        assert paid["collection_status"] == "CURRENT", "Payment in full cures even from DISCONNECTED"

        tap = get_success_data(api.reconnect_tap(district["id"], ctx["tap"]["id"], FIELD))
        assert tap["status"] == "RECONNECTED"
        member_after = get_success_data(api.get_member(district["id"], member["id"], CLERK))
        assert member_after["membership_status"] == "ACTIVE"


class TestDelinquentCycleCounter:
    def test_consecutive_delinquent_cycles_increment_and_reset(self, api):
        """PRD section 3.3: closing "walks every member to update
        `consecutive_delinquent_cycles` — reset to 0 if this cycle's invoice was
        fully paid by its due date, incremented otherwise".

        Design: Corner/calculations/consecutive_delinquent_cycles_counter_reset
        """
        ctx = setup_billed_invoice(usage_gallons=100)  # C1 invoice 3500
        district = ctx["district"]
        member = ctx["member"]
        # Close C1 unpaid (clock past due 2026-09-10) -> counter 1
        set_clock("2026-09-15T00:00:00Z")
        close_cycle(district["id"], ctx["cycle"]["id"], master_gallons=100)
        mid = get_success_data(api.get_member(district["id"], member["id"], TREASURER))
        assert mid["consecutive_delinquent_cycles"] == 1

        # C2 billed and paid before its due date -> close resets the counter to 0
        cycle2 = open_cycle(district["id"], **CYCLE_2)
        bill_cycle_with_readings(district["id"], cycle2["id"], [(ctx["tap"]["id"], 200)])
        invoice2 = get_cycle_invoice(district["id"], cycle2["id"])
        pay_invoice(district["id"], member["id"], invoice2["id"], invoice2["total_cents"])
        close_cycle(district["id"], cycle2["id"], master_gallons=100)
        end = get_success_data(api.get_member(district["id"], member["id"], TREASURER))
        assert end["consecutive_delinquent_cycles"] == 0


class TestReconnectFeeBilling:
    def test_reconnect_fee_carried_onto_next_invoice_then_cleared(self, api):
        """PRD section 3.4: "Finally `total_cents` is that base plus
        `reconnect_fee_cents`, which is non-zero only when the tap carried a
        pending reconnect fee at billing time (armed at reconnection, §3.6) and is
        cleared once billed." The next cycle's invoice therefore carries
        the 5000-cent fee on top of the 3500 minimum (total 8500), and the cycle
        after that bills the bare minimum again.

        Design: Corner/cross_cutting_layers/reconnect_fee_carried_onto_next_invoice
        """
        ctx = setup_disconnected_tap_scenario(first_usage=100, second_usage_register=100)
        district = ctx["district"]
        member = ctx["member"]
        pay_invoice(district["id"], member["id"], ctx["invoice1"]["id"], 3500)
        tap = get_success_data(api.reconnect_tap(district["id"], ctx["tap"]["id"], FIELD))
        assert tap["status"] == "RECONNECTED"
        close_cycle(district["id"], ctx["cycle2"]["id"], master_gallons=100)

        cycle3 = open_cycle(district["id"], **CYCLE_3)
        bill_cycle_with_readings(district["id"], cycle3["id"], [(ctx["tap"]["id"], 100)])
        invoice3 = get_cycle_invoice(district["id"], cycle3["id"])
        assert invoice3["reconnect_fee_cents"] == 5000
        assert invoice3["total_cents"] == 8500

        close_cycle(district["id"], cycle3["id"], master_gallons=100)
        cycle4 = open_cycle(district["id"], **CYCLE_4)
        bill_cycle_with_readings(district["id"], cycle4["id"], [(ctx["tap"]["id"], 100)])
        invoice4 = get_cycle_invoice(district["id"], cycle4["id"])
        assert invoice4["reconnect_fee_cents"] == 0, "The fee flag clears once billed"
        assert invoice4["total_cents"] == 3500
