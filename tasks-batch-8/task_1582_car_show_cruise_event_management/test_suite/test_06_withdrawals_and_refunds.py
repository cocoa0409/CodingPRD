"""Withdrawal refund tiers, the deny/approve cycle, and refund-decision caps."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_open_event, create_registrant_with_vehicle, create_registration,
    create_paid_registration, get_summary,
)

ORG = TEST_USERS["organizer_headers"]
DESK = TEST_USERS["desk_headers"]


def _paid_registration(api, club_member=False):
    ev, cls, zone = create_open_event()
    reg, veh = create_registrant_with_vehicle(club_member=club_member)
    registration = create_paid_registration(ev["id"], reg["id"], veh["id"], cls["id"])
    return ev, cls, registration


class TestWithdrawalRefundBoundary:
    def _setup_two_paid(self, api):
        ev, cls, zone = create_open_event()
        regs = []
        for i, (yr, make, model) in enumerate([(1970, "Ford", "Mustang"),
                                               (1971, "Chevrolet", "Chevelle")]):
            reg, veh = create_registrant_with_vehicle(
                name=f"T{i}", email=f"t{i}@example.com",
                vehicle_overrides={"year": yr, "make": make, "model": model})
            regs.append(create_paid_registration(ev["id"], reg["id"], veh["id"], cls["id"]))
        return ev, regs

    def test_exactly_168h_earns_full_refund(self, api):
        """PRD §3.4: "The boundaries are inclusive: exactly 168.0 hours out is a
        full refund, and exactly 48.0 hours out is a half refund."

        Design: Difficulty/boundary_precision_check/withdrawal_refund_168h_boundary
        """
        ev, regs = self._setup_two_paid(api)
        # Gates open 2026-08-15T09:00:00Z; exactly 168.0h before is 2026-08-08T09:00:00Z.
        get_success_data(api.set_clock({"to_iso8601": "2026-08-08T09:00:00Z"}, ORG))
        get_success_data(api.withdraw_registration(regs[0]["id"], {"reason": "exactly 168h"}, DESK))
        decided = validate_success(api.refund_decision(regs[0]["id"], {"decision": "APPROVE"}, ORG))
        assert decided["status"] == "REFUNDED"
        payments = validate_success(api.list_registration_payments(regs[0]["id"], ORG))
        refunds = [p for p in payments if p["kind"] == "REFUND"]
        assert len(refunds) == 1
        assert refunds[0]["amount_cents"] == 3000, "168.0h exactly => 100% tier"

    def test_one_second_past_168h_earns_half_refund(self, api):
        """PRD §3.4: "Withdrawing at least 168 hours before gates open, a full
        week out, earns a 100% refund tier; at least 48 hours before gates open
        earns 50%; anything closer earns nothing."

        Design: Difficulty/boundary_precision_check/withdrawal_refund_168h_boundary
        """
        ev, regs = self._setup_two_paid(api)
        get_success_data(api.set_clock({"to_iso8601": "2026-08-08T09:00:01Z"}, ORG))
        get_success_data(api.withdraw_registration(regs[1]["id"], {"reason": "one second late"}, DESK))
        decided = validate_success(api.refund_decision(regs[1]["id"], {"decision": "APPROVE"}, ORG))
        assert decided["status"] == "REFUNDED"
        payments = validate_success(api.list_registration_payments(regs[1]["id"], ORG))
        refunds = [p for p in payments if p["kind"] == "REFUND"]
        assert len(refunds) == 1
        assert refunds[0]["amount_cents"] == 1500, "just under 168h => 50% tier"


class TestRefundDeniedCycle:
    def _setup(self, api):
        ev, cls, registration = _paid_registration(api)
        # 2026-08-05T00:00:00Z is 249h before gates: 100% tier.
        get_success_data(api.set_clock({"to_iso8601": "2026-08-05T00:00:00Z"}, ORG))
        return ev, registration

    def test_deny_returns_to_confirmed_and_clears_withdrawn_at(self, api):
        """PRD §3.4: "On `DENY`, the registration returns to `CONFIRMED` and
        `withdrawn_at` is cleared back to null."

        Design: Difficulty/non_linear_state_machine/registration_refund_denied_cycle
        """
        ev, registration = self._setup(api)
        req = validate_success(api.withdraw_registration(
            registration["id"], {"reason": "first attempt"}, DESK))
        assert req["status"] == "REFUND_REQUESTED"
        denied = validate_success(api.refund_decision(registration["id"], {"decision": "DENY"}, ORG))
        assert denied["status"] == "CONFIRMED"
        assert denied["withdrawn_at"] is None
        payments = validate_success(api.list_registration_payments(registration["id"], ORG))
        assert all(p["kind"] != "REFUND" for p in payments), "no REFUND payment on deny"

    def test_cycle_completes_with_approve_and_full_refund(self, api):
        """PRD §3.4: "A positive tier parks the registration in
        `REFUND_REQUESTED` with `withdrawn_at` stamped, awaiting an organizer's
        decision." and "Approval writes a `REFUND` payment, grows
        `refunded_cents`, debits the event treasury (incrementing the event's
        `version`), voids the entry's ballots, decrements the class's
        `confirmed_count`, and lands the registration in `REFUNDED`."

        Design: Difficulty/non_linear_state_machine/registration_refund_denied_cycle
        """
        ev, registration = self._setup(api)
        validate_success(api.withdraw_registration(registration["id"], {"reason": "first attempt"}, DESK))
        validate_success(api.refund_decision(registration["id"], {"decision": "DENY"}, ORG))
        req2 = validate_success(api.withdraw_registration(registration["id"], {"reason": "second attempt"}, DESK))
        assert req2["status"] == "REFUND_REQUESTED"
        approved = validate_success(api.refund_decision(registration["id"], {"decision": "APPROVE"}, ORG))
        assert approved["status"] == "REFUNDED"
        assert approved["refunded_cents"] == 3000
        payments = validate_success(api.list_registration_payments(registration["id"], ORG))
        refunds = [p for p in payments if p["kind"] == "REFUND"]
        assert len(refunds) == 1
        assert refunds[0]["amount_cents"] == 3000, "100% of gross at 249h"


class TestZeroPercentTier:
    def test_withdrawal_zero_percent_tier(self, api):
        """PRD §3.4: "A zero tier — withdrawal inside 48 hours of gates open —
        terminates immediately in `WITHDRAWN`: `withdrawn_at` is stamped, every
        ballot cast for the entry flips `VALID` → `VOID`, and the class's
        `confirmed_count` is decremented."

        Design: Corner/calculations/withdrawal_zero_percent_tier
        """
        ev, cls, registration = _paid_registration(api)
        # Exactly 24h before gates: inside 48h => 0% tier.
        get_success_data(api.set_clock({"to_iso8601": "2026-08-14T09:00:00Z"}, ORG))
        withdrawn = validate_success(api.withdraw_registration(
            registration["id"], {"reason": "too late to refund"}, DESK))
        assert withdrawn["status"] == "WITHDRAWN", "no REFUND_REQUESTED hop at 0%"
        payments = validate_success(api.list_registration_payments(registration["id"], ORG))
        assert len(payments) == 1
        assert payments[0]["kind"] == "ENTRY_FEE"
        assert get_summary(ev["id"])["treasury_cents"] == 3000, "treasury untouched"


class TestRefundCap:
    def test_refund_decision_over_net_paid_rejected(self, api):
        """PRD §3.4: "Either way the amount must not exceed the net paid, else
        `ERR_REFUND_EXCEEDS_PAID`." and "otherwise the policy amount: the
        registration's net paid, meaning `paid_cents` minus `refunded_cents`
        measured at decision time, multiplied by the tier percentage that was
        frozen at `withdrawn_at`".

        Design: Corner/errors/refund_decision_over_net_paid_rejected
        """
        ev, cls, registration = _paid_registration(api)
        # 2026-08-10T09:00:00Z is 120h before gates: 50% tier => policy 1500.
        get_success_data(api.set_clock({"to_iso8601": "2026-08-10T09:00:00Z"}, ORG))
        get_success_data(api.withdraw_registration(registration["id"], {"reason": "wants out"}, DESK))
        resp = api.refund_decision(registration["id"], {"decision": "APPROVE", "amount_cents": 4000}, ORG)
        validate_error(resp, ApiErrorId.ERR_REFUND_EXCEEDS_PAID)
        still = validate_success(api.get_registration(registration["id"], ORG))
        assert still["status"] == "REFUND_REQUESTED"
        approved = validate_success(api.refund_decision(registration["id"], {"decision": "APPROVE"}, ORG))
        assert approved["status"] == "REFUNDED"
        assert approved["refunded_cents"] == 1500, "default policy amount at the 50% tier"
