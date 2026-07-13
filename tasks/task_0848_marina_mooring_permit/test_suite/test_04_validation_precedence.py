"""Validation precedence: the fixed order of §2.9 means a state check pre-empts a
fiscal check, and a referential check pre-empts a constraint check."""
from test_helpers import (
    validate_error,
    ApiErrorId,
    TEST_USERS,
    set_clock,
    create_marina,
    create_berth,
    create_boater,
    create_vessel,
    setup_active_permit,
    setup_offered_permit,
    create_permit_payload,
    get_invoice,
)

HARBOR = TEST_USERS["harbormaster_headers"]


class TestInvoiceStateBeatsAmountMismatch:
    def _paid_invoice(self, api):
        b = setup_active_permit(api, clock="2026-05-15T00:00:00Z", vessel_overrides={"length_ft": 30})
        return b["invoice"]["id"]

    def test_repay_paid_invoice_wrong_amount_returns_not_payable(self, api):
        """PRD §2.9: "Fifth, the target resource's state is checked against the
        state machine for the requested transition, yielding `ERR_INVALID_STATE`
        (HTTP 409) when the resource is not in a legal from-state. Only after these
        five gates do the domain-specific business rules run — registration
        currency, berth-type and size matching, season overlap, ramp-pass overlap,
        vessel length, the liveaboard cap, payment amount, lottery timing, and the
        reassignment stale-version check — each described alongside the workflow it
        guards."
        PRD §3.4: "an invoice that is not `UNPAID` cannot be paid and is rejected
        with `ERR_INVOICE_NOT_PAYABLE` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/invoice_not_payable_state_beats_amount_mismatch_fiscal
        """
        invoice_id = self._paid_invoice(api)
        validate_error(
            api.pay_invoice(invoice_id, {"amount_cents": 999}, HARBOR),
            ApiErrorId.ERR_INVOICE_NOT_PAYABLE,
        )

    def test_repay_paid_invoice_correct_amount_also_not_payable(self, api):
        """PRD §3.4: "an invoice that is not `UNPAID` cannot be paid and is
        rejected with `ERR_INVOICE_NOT_PAYABLE` (HTTP 409)."
        PRD §2.9: "Fifth, the target resource's state is checked against the state
        machine for the requested transition, yielding `ERR_INVALID_STATE` (HTTP
        409) when the resource is not in a legal from-state. Only after these five
        gates do the domain-specific business rules run — registration currency,
        berth-type and size matching, season overlap, ramp-pass overlap, vessel
        length, the liveaboard cap, payment amount, lottery timing, and the
        reassignment stale-version check — each described alongside the workflow it
        guards."

        Design: Difficulty/priority_pair_validation_conflict/invoice_not_payable_state_beats_amount_mismatch_fiscal
        """
        invoice_id = self._paid_invoice(api)
        # Even a well-formed amount cannot resurrect a PAID invoice: the state
        # gate fires before the payment-amount business rule is ever consulted.
        validate_error(
            api.pay_invoice(invoice_id, {"amount_cents": 120000}, HARBOR),
            ApiErrorId.ERR_INVOICE_NOT_PAYABLE,
        )


class TestRegistrationBeatsTooLong:
    def test_expired_and_too_long_vessel_returns_registration_error(self, api):
        """PRD §2.9: "Only after these five gates do the domain-specific business
        rules run — registration currency, berth-type and size matching, season
        overlap, ramp-pass overlap, vessel length, the liveaboard cap, payment
        amount, lottery timing, and the reassignment stale-version check — each
        described alongside the workflow it guards."
        PRD §3.3: "an application on an `EXPIRED` or `REVOKED` vessel is rejected
        with `ERR_VESSEL_REGISTRATION_EXPIRED` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/registration_expired_referential_beats_too_long_constraint
        """
        set_clock(api, "2026-04-01T00:00:00Z")
        marina = create_marina(api)
        create_berth(api, marina["id"], max_length_ft=40)
        boater = create_boater(api)
        vessel = create_vessel(
            api, boater["id"], length_ft=50, registration_expiry_date="2026-04-30"
        )
        set_clock(api, "2026-05-15T00:00:00Z")  # vessel EXPIRED and too long (50 > 40)
        validate_error(
            api.create_permit(
                create_permit_payload(marina["id"], boater["id"], vessel["id"]), HARBOR
            ),
            ApiErrorId.ERR_VESSEL_REGISTRATION_EXPIRED,
        )

    def test_registered_but_too_long_vessel_returns_too_long(self, api):
        """PRD §3.3: "On the immediate-offer path the vessel must fit the berth: a
        `length_ft` greater than the berth's `max_length_ft` is rejected with
        `ERR_VESSEL_TOO_LONG` (HTTP 422), and a requested berth type or size class
        that cannot be matched, or a `resident_only` berth requested by a
        non-resident, is rejected with `ERR_BERTH_TYPE_MISMATCH` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/registration_expired_referential_beats_too_long_constraint
        """
        set_clock(api, "2026-05-01T00:00:00Z")
        marina = create_marina(api)
        create_berth(api, marina["id"], max_length_ft=40)
        boater = create_boater(api)
        # REGISTERED (expiry 2026-12-31) but 50ft > 40ft berth: only the length
        # rule can fail, so ERR_VESSEL_TOO_LONG is returned in isolation.
        vessel = create_vessel(api, boater["id"], length_ft=50)
        validate_error(
            api.create_permit(
                create_permit_payload(marina["id"], boater["id"], vessel["id"]), HARBOR
            ),
            ApiErrorId.ERR_VESSEL_TOO_LONG,
        )


class TestPartialPayment:
    def test_partial_payment_rejected_with_amount_mismatch(self, api):
        """PRD §3.4: "Paying an invoice supplies an `amount_cents` that must
        exactly equal the invoice's `amount_due_cents`; a mismatched amount is
        rejected with `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 422), and an invoice that
        is not `UNPAID` cannot be paid and is rejected with `ERR_INVOICE_NOT_PAYABLE`
        (HTTP 409)."

        Design: Corner/validations/pay_partial_amount_returns_amount_mismatch
        """
        b = setup_offered_permit(api, clock="2026-05-01T00:00:00Z")
        validate_error(
            api.pay_invoice(b["invoice_id"], {"amount_cents": 60000}, HARBOR),
            ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH,
        )
        assert get_invoice(api, b["invoice_id"])["status"] == "UNPAID"
