"""Difficulty Rule 7 — cross_entity_state_dependency.

State transitions whose preconditions reference the state of a different
entity entirely: awarding a QuoteRequest requires the Carrier to be
QUALIFIED, and approving a FactoringRequest requires the parent Invoice to
be in {ISSUED, PARTIALLY_PAID} AND not already factored.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    create_carrier,
    create_quote,
    create_shipper,
    get_success_data,
    open_dispute,
    open_factoring_request,
    set_clock,
    setup_invoiced_load,
    validate_error,
)
from test_helpers.api_client import api_client
from test_helpers.factories import award_quote_payload


class TestAwardRequiresCarrierQualifiedState:
    def test_award_with_pending_carrier_returns_invalid_state(self, api):
        """PRD §3.4: "The award runs five preconditions in addition to the
        standard pipeline: the quote's `status` must be `OPEN`; the current
        server time must be strictly earlier than the quote's
        `expires_at_utc`; the chosen carrier's `qualification_status` must
        be `QUALIFIED`; if the quote has `requires_smartway` set to true,
        the carrier's `smartway_tier` must be one of `BRONZE`, `SILVER`,
        or `GOLD`; and if `rate_mode` is `CONTRACT`, the referenced
        `ContractRate` must still be `ACTIVE` and its current `version`
        must match the quote's pinned `contract_rate_version`."
        PRD §2.7: "state-machine admissibility of the requested transition
        (`ERR_INVALID_STATE`)"

        Design: Difficulty/cross_entity_state_dependency/award_requires_carrier_qualified_state
        """
        set_clock("2026-06-01T00:00:00Z")
        shipper = create_shipper(credit_limit_cents=100_000_000)
        # Carrier created but NOT qualified.
        carrier = create_carrier(
            smartway_tier="NONE",
            insurance_expiry_utc="2027-01-01T00:00:00Z",
            safety_score=30.0,
        )
        assert carrier["qualification_status"] == "PENDING"
        quote = create_quote(
            shipper["id"], lane_origin="10001", lane_destination="30303",
            distance_miles=400,
            pickup_window_start_utc="2026-06-15T08:00:00Z",
            pickup_window_end_utc="2026-06-15T18:00:00Z",
            requested_equipment="DRY_VAN",
        )
        res = api.award_quote(
            quote["id"],
            award_quote_payload(carrier["id"], quote["version"]),
            TEST_USERS["broker_ops_headers"],
        )
        validate_error(res, "ERR_INVALID_STATE")

        quote_after = get_success_data(
            api_client.get_quote_request(quote["id"], TEST_USERS["broker_ops_headers"])
        )
        # The transition did not happen — the quote is still OPEN.
        assert quote_after["status"] == "OPEN"

    def test_award_against_rejected_carrier_also_returns_invalid_state(self, api):
        """PRD §3.4: "The award runs five preconditions in addition to the
        standard pipeline: the quote's `status` must be `OPEN`; the
        current server time must be strictly earlier than the quote's
        `expires_at_utc`; the chosen carrier's `qualification_status`
        must be `QUALIFIED`; if the quote has `requires_smartway` set to
        true, the carrier's `smartway_tier` must be one of `BRONZE`,
        `SILVER`, or `GOLD`; and if `rate_mode` is `CONTRACT`, the
        referenced `ContractRate` must still be `ACTIVE` and its current
        `version` must match the quote's pinned `contract_rate_version`."
        PRD §3.1: "A rejected carrier is terminal — there is no path out of
        `REJECTED`."

        With a REJECTED carrier the cross-entity precondition fails the same
        way as PENDING — the carrier is not in QUALIFIED, so the requested
        award transition is inadmissible.

        Design: Difficulty/cross_entity_state_dependency/award_requires_carrier_qualified_state
        """
        set_clock("2026-06-01T00:00:00Z")
        shipper = create_shipper(credit_limit_cents=100_000_000)
        carrier = create_carrier(
            smartway_tier="NONE",
            insurance_expiry_utc="2027-01-01T00:00:00Z",
            safety_score=30.0,
        )
        # Move PENDING → REJECTED so the carrier is decisively not QUALIFIED.
        get_success_data(
            api_client.reject_carrier(carrier["id"], {"reason_code": "BAD_MC"},
                                       TEST_USERS["broker_ops_headers"])
        )
        quote = create_quote(
            shipper["id"], lane_origin="10001", lane_destination="30303",
            distance_miles=400,
            pickup_window_start_utc="2026-06-15T08:00:00Z",
            pickup_window_end_utc="2026-06-15T18:00:00Z",
            requested_equipment="DRY_VAN",
        )
        res = api.award_quote(
            quote["id"],
            award_quote_payload(carrier["id"], quote["version"]),
            TEST_USERS["broker_ops_headers"],
        )
        validate_error(res, "ERR_INVALID_STATE")


class TestFactoringApproveRequiresInvoiceOpenAndNotFactored:
    def test_approve_when_invoice_is_disputed_returns_invalid_state(self, api):
        """PRD §3.8: "The invoice must be in `ISSUED` or `PARTIALLY_PAID`
        status and not already factored."
        PRD §2.7: "state-machine admissibility of the requested transition
        (`ERR_INVALID_STATE`)"

        Design: Difficulty/cross_entity_state_dependency/factoring_approve_requires_invoice_open_and_not_factored
        """
        # safety_score=20 puts the carrier in PRD §3.8's <25 band → fee floor 2.0%,
        # so factoring_fee_pct=2.0 satisfies ERR_FACTORING_FEE_BELOW_MIN.
        shipper, carrier, _quote, _load, invoice, _contract = setup_invoiced_load(
            contract_overrides={
                "rate_per_mile_cents": 200,
                "fuel_surcharge_per_mile_cents": 50,
            },
            safety_score=20.0,
        )
        # Open a FactoringRequest in REQUESTED.
        fr = open_factoring_request(invoice["id"], carrier["id"],
                                    factoring_fee_pct=2.0)
        # Now dispute the invoice → invoice transitions to DISPUTED.
        open_dispute(invoice["id"], shipper["id"],
                     claim_type="OVERCHARGE",
                     claimed_amount_cents=5000)

        # Approving the factoring on a DISPUTED invoice is inadmissible.
        res = api.approve_factoring(fr["id"], TEST_USERS["broker_ops_headers"])
        validate_error(res, "ERR_INVALID_STATE")

        fr_after = get_success_data(
            api_client.get_factoring_request(fr["id"], TEST_USERS["broker_ops_headers"])
        )
        invoice_after = get_success_data(
            api_client.get_invoice(invoice["id"], TEST_USERS["broker_ops_headers"])
        )
        assert fr_after["status"] == "REQUESTED"
        assert invoice_after["status"] == "DISPUTED"

    def test_approve_succeeds_when_invoice_is_issued_and_not_factored(self, api):
        """PRD §3.8: "A `BrokerOps` operator approves the request, moving it
        `REQUESTED → APPROVED` and flipping `Invoice.factored` to true in
        the same transaction (`Invoice.version` advances)."

        The positive control for the precondition above — when the cross-
        entity precondition holds, approve succeeds and the cascade flips
        Invoice.factored to true.

        Design: Difficulty/cross_entity_state_dependency/factoring_approve_requires_invoice_open_and_not_factored
        """
        # safety_score=20 puts the carrier in PRD §3.8's <25 band → fee floor 2.0%,
        # so factoring_fee_pct=2.0 satisfies ERR_FACTORING_FEE_BELOW_MIN.
        shipper, carrier, _quote, _load, invoice, _contract = setup_invoiced_load(
            contract_overrides={
                "rate_per_mile_cents": 200,
                "fuel_surcharge_per_mile_cents": 50,
            },
            safety_score=20.0,
        )
        assert invoice["status"] == "ISSUED"
        assert invoice["factored"] is False
        fr = open_factoring_request(invoice["id"], carrier["id"],
                                    factoring_fee_pct=2.0)
        approved = get_success_data(
            api_client.approve_factoring(fr["id"], TEST_USERS["broker_ops_headers"])
        )
        assert approved["status"] == "APPROVED"

        invoice_after = get_success_data(
            api_client.get_invoice(invoice["id"], TEST_USERS["broker_ops_headers"])
        )
        assert invoice_after["factored"] is True
