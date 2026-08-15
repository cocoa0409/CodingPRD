"""Entry-fee payments, treasury conservation, and ledger shape."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_participant_headers,
    create_open_event, create_registrant_with_vehicle, create_registration,
    create_paid_registration, get_summary, assert_payment,
)

ORG = TEST_USERS["organizer_headers"]
DESK = TEST_USERS["desk_headers"]


class TestPaymentLedgerShape:
    def test_payment_immutable_common_fields_absent(self, api):
        """PRD §2.5: "A `Payment` is an append-only ledger row, a `Waiver` is a
        signed legal certificate, and a `NoiseReading` is a sampled measurement;
        each carries only `id` and `created_at`, and both `updated_at` and
        `version` are absent from all three."

        Design: Corner/entities/payment_immutable_common_fields_absent
        """
        ev, cls, zone = create_open_event()
        reg, veh = create_registrant_with_vehicle()
        registration = create_registration(ev["id"], reg["id"], veh["id"], cls["id"])
        pay = validate_success(api.create_registration_payment(
            registration["id"], {"amount_cents": 3000, "method": "CASH"}, DESK),
            expected_status=201)
        assert_payment(pay)
        assert pay["kind"] == "ENTRY_FEE"
        assert pay["amount_cents"] == 3000


class TestPaymentAmount:
    def test_payment_amount_mismatch_rejected(self, api):
        """PRD §3.2: "the participant (for their own registration) or the desk
        records a payment whose `amount_cents` equals the frozen `fee_cents` —
        anything else is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH`".

        Design: Corner/validations/payment_amount_mismatch_rejected
        """
        ev, cls, zone = create_open_event()
        reg, veh = create_registrant_with_vehicle()
        registration = create_registration(ev["id"], reg["id"], veh["id"], cls["id"])
        resp = api.create_registration_payment(
            registration["id"], {"amount_cents": 2999, "method": "CASH"}, DESK)
        validate_error(resp, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH)
        # No payment row was written; the registration stays PENDING_PAYMENT.
        payments = validate_success(api.list_registration_payments(registration["id"], ORG))
        assert payments == []
        after = validate_success(api.get_registration(registration["id"], ORG))
        assert after["status"] == "PENDING_PAYMENT"
        # Exact amount then succeeds.
        pay = validate_success(api.create_registration_payment(
            registration["id"], {"amount_cents": 3000, "method": "CASH"}, DESK),
            expected_status=201)
        assert_payment(pay)
        confirmed = validate_success(api.get_registration(registration["id"], ORG))
        assert confirmed["status"] == "CONFIRMED"


class TestOwnershipOnPayments:
    def test_participant_pays_others_registration_returns_403(self, api):
        """PRD §2.1: "When `X-User-Role` is `Participant`, `X-User-ID` is the `id`
        of the acting registrant; ownership checks on registrations, vehicles,
        waivers, and ballots compare the resource's registrant reference — such as
        `registrant_id` or `voter_registrant_id` — to `X-User-ID`." and "An
        entity-backed actor touching a resource owned by someone else is rejected
        with `ERR_OWNERSHIP_VIOLATION` (HTTP 403)."

        Design: Corner/validations/participant_pays_others_registration_returns_403
        """
        ev, cls, zone = create_open_event()
        owner, veh = create_registrant_with_vehicle(name="O1", email="o1@example.com")
        registration = create_registration(ev["id"], owner["id"], veh["id"], cls["id"])
        other = get_success_data(api.create_registrant(
            {"full_name": "O2", "email": "o2@example.com"}, ORG))
        resp = api.create_registration_payment(
            registration["id"], {"amount_cents": 3000, "method": "CASH"},
            make_participant_headers(other["id"]))
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_VIOLATION)
        after = validate_success(api.get_registration(registration["id"], ORG))
        assert after["status"] == "PENDING_PAYMENT"
        assert after["paid_cents"] == 0


class TestImmediateConsistency:
    def test_immediate_read_after_write(self, api):
        """PRD §2.6: "The treasury is recomputed immediately on every payment
        mutation, and any payment that moves it also increments the event's
        `version`."

        Design: Corner/consistency_model/immediate_read_after_write
        """
        ev, cls, zone = create_open_event()
        reg, veh = create_registrant_with_vehicle()
        registration = create_registration(ev["id"], reg["id"], veh["id"], cls["id"])
        pay = validate_success(api.create_registration_payment(
            registration["id"], {"amount_cents": 3000, "method": "CASH"}, DESK),
            expected_status=201)
        assert pay["status"] == "SUCCEEDED"
        reg_read = validate_success(api.get_registration(registration["id"], ORG))
        assert reg_read["status"] == "CONFIRMED"
        assert reg_read["paid_cents"] == 3000
        summary = get_summary(ev["id"])
        assert summary["treasury_cents"] == 3000, "treasury must reflect the payment with no lag"


class TestTreasuryConservation:
    def _setup(self, api):
        ev, cls, zone = create_open_event()
        reg, v1 = create_registrant_with_vehicle(name="Led", email="led@example.com")
        v2 = get_success_data(api.create_vehicle(
            reg["id"], {"year": 1971, "make": "Chevrolet", "model": "Chevelle"}, ORG))
        return ev, cls, reg, v1, v2

    def test_treasury_conserved_payment_refund_pair(self, api):
        """PRD §2.6: "Every event owns a treasury, exposed as `treasury_cents`:
        the sum of `SUCCEEDED` payments whose `kind` is `ENTRY_FEE` or `BOOTH_FEE`
        for the event, minus the sum of its `SUCCEEDED` payments whose `kind` is
        `REFUND`." PRD §3.4: "at least 48 hours before gates open earns 50%".

        Design: Difficulty/compensating_invariant/treasury_conserved_payment_refund
        """
        ev, cls, reg, v1, v2 = self._setup(api)
        r1 = create_paid_registration(ev["id"], reg["id"], v1["id"], cls["id"])
        assert get_summary(ev["id"])["treasury_cents"] == 3000
        # 2026-08-10T09:00Z is exactly 120h before gates: the 50% tier.
        get_success_data(api.set_clock({"to_iso8601": "2026-08-10T09:00:00Z"}, ORG))
        get_success_data(api.withdraw_registration(r1["id"], {"reason": "sold the car"}, DESK))
        get_success_data(api.refund_decision(r1["id"], {"decision": "APPROVE"}, ORG))
        assert get_summary(ev["id"])["treasury_cents"] == 1500, "3000 - 1500 refund"
        r1_after = validate_success(api.get_registration(r1["id"], ORG))
        assert r1_after["refunded_cents"] == 1500
        assert r1_after["status"] == "REFUNDED"

    def test_treasury_conserved_across_second_payment(self, api):
        """PRD §2.6: "Registration money is tracked on a gross basis: a
        registration's `paid_cents` accumulates its `SUCCEEDED` `ENTRY_FEE`
        payments and never decreases, while its `refunded_cents` accumulates that
        registration's `SUCCEEDED` `REFUND` payments; the net position is the
        difference of the two."

        Design: Difficulty/compensating_invariant/treasury_conserved_payment_refund
        """
        ev, cls, reg, v1, v2 = self._setup(api)
        r1 = create_paid_registration(ev["id"], reg["id"], v1["id"], cls["id"])
        get_success_data(api.set_clock({"to_iso8601": "2026-08-10T09:00:00Z"}, ORG))
        get_success_data(api.withdraw_registration(r1["id"], {"reason": "sold the car"}, DESK))
        get_success_data(api.refund_decision(r1["id"], {"decision": "APPROVE"}, ORG))
        # R1 is REFUNDED (terminal), so it does not count toward the multi-vehicle
        # ordinal: the second registration prices at the full non-member fee.
        r2 = create_registration(ev["id"], reg["id"], v2["id"], cls["id"])
        assert r2["fee_cents"] == 3000
        get_success_data(api.create_registration_payment(
            r2["id"], {"amount_cents": 3000, "method": "CASH"}, DESK))
        assert get_summary(ev["id"])["treasury_cents"] == 4500, "(3000 + 3000) - 1500"
