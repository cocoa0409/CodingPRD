"""Difficulty Rule 4 — transitive_cascade.

Cascades whose secondary mutations are themselves causally triggered by the
primary mutation's state change (each subsequent hop is a consequence of the
prior hop, not directly of the API call). Instance A: dispute UPHELD writes
off an invoice (hop 1), which closes the load (hop 2), which recalls the
related factoring advance (hop 3). Instance B: cancelling an AWARDED load
flips the load to CANCELLED (hop 1), which forces the originating quote
back to WITHDRAWN (hop 2).
"""
import pytest

from test_helpers import (
    TEST_USERS,
    get_success_data,
    open_dispute,
    resolve_dispute,
    setup_advanced_factoring,
    setup_awarded_load,
)
from test_helpers.api_client import api_client


class TestDisputeUpheldCascadeToFactoringRecourseDepth3:
    def test_upheld_resolution_writes_off_invoice_closes_load_and_recourses_factoring(self, api):
        """PRD §3.7: "An `UPHELD` resolution writes the invoice off:
        `Invoice.status` moves to `WRITTEN_OFF` and `Shipper.open_ar_cents`
        is recomputed (because written-off invoices no longer contribute to
        the open-AR sum), and the cascade then continues — the parent `Load`
        moves to `CLOSED`, and if `Invoice.factored` is true the related
        `FactoringRequest` moves to `RECOURSE` so the broker can recall the
        advance from the factor."

        Design: Difficulty/transitive_cascade/dispute_upheld_cascade_to_factoring_recourse_depth3
        """
        # Invoice total = 200 c/mi linehaul + 50 c/mi fuel × 400 mi = 100000.
        shipper, carrier, _quote, load, invoice, factoring, _contract = setup_advanced_factoring(
            contract_overrides={
                "rate_per_mile_cents": 200,
                "fuel_surcharge_per_mile_cents": 50,
            },
        )
        assert invoice["total_cents"] == 100000
        # Open a full-balance dispute and uphold it.
        dispute = open_dispute(invoice["id"], shipper["id"],
                               claim_type="DAMAGED_GOODS",
                               claimed_amount_cents=100000)
        resolve_dispute(dispute["id"], resolution_kind="UPHELD",
                        resolution_amount_cents=100000)

        invoice_after = get_success_data(
            api_client.get_invoice(invoice["id"], TEST_USERS["broker_ops_headers"])
        )
        load_after = get_success_data(
            api_client.get_load(load["id"], TEST_USERS["broker_ops_headers"])
        )
        factoring_after = get_success_data(
            api_client.get_factoring_request(factoring["id"],
                                              TEST_USERS["broker_ops_headers"])
        )
        assert invoice_after["status"] == "WRITTEN_OFF"
        assert load_after["status"] == "CLOSED"
        assert factoring_after["status"] == "RECOURSE"

    def test_upheld_non_factored_invoice_closes_load_without_recourse(self, api):
        """PRD §3.7: "An `UPHELD` resolution writes the invoice off:
        `Invoice.status` moves to `WRITTEN_OFF` and `Shipper.open_ar_cents`
        is recomputed (because written-off invoices no longer contribute
        to the open-AR sum), and the cascade then continues — the parent
        `Load` moves to `CLOSED`, and if `Invoice.factored` is true the
        related `FactoringRequest` moves to `RECOURSE` so the broker can
        recall the advance from the factor."

        The "if Invoice.factored is true" guard makes the FactoringRequest
        hop conditional; on a non-factored invoice, the cascade stops at
        Load.CLOSED (no FactoringRequest is created in this scenario).

        Design: Difficulty/transitive_cascade/dispute_upheld_cascade_to_factoring_recourse_depth3
        """
        # No factoring path: just shipper → carrier → load → invoice; UPHELD it.
        from test_helpers import setup_invoiced_load
        shipper, _carrier, _quote, load, invoice, _contract = setup_invoiced_load(
            contract_overrides={
                "rate_per_mile_cents": 200,
                "fuel_surcharge_per_mile_cents": 50,
            },
        )
        assert invoice["total_cents"] == 100000
        assert invoice["factored"] is False
        dispute = open_dispute(invoice["id"], shipper["id"],
                               claim_type="DAMAGED_GOODS",
                               claimed_amount_cents=100000)
        resolve_dispute(dispute["id"], resolution_kind="UPHELD",
                        resolution_amount_cents=100000)
        invoice_after = get_success_data(
            api_client.get_invoice(invoice["id"], TEST_USERS["broker_ops_headers"])
        )
        load_after = get_success_data(
            api_client.get_load(load["id"], TEST_USERS["broker_ops_headers"])
        )
        assert invoice_after["status"] == "WRITTEN_OFF"
        assert load_after["status"] == "CLOSED"


class TestLoadCancelCascadeToQuoteWithdrawnDepth2:
    def test_cancel_awarded_load_flips_load_to_cancelled_and_quote_to_withdrawn(self, api):
        """PRD §3.5: "A `BrokerOps` operator may cancel an `AWARDED` load
        before pickup. Cancellation transitions the load `AWARDED →
        CANCELLED` and cascades the parent quote back to `WITHDRAWN`,
        advancing both `Load.version` and `QuoteRequest.version` by one."

        Design: Difficulty/transitive_cascade/load_cancel_cascade_to_quote_withdrawn_depth2
        """
        shipper, carrier, quote, load, _contract = setup_awarded_load(use_contract=False)
        assert load["status"] == "AWARDED"

        cancelled = get_success_data(
            api_client.cancel_load(load["id"], TEST_USERS["broker_ops_headers"])
        )
        assert cancelled["status"] == "CANCELLED"

        quote_after = get_success_data(
            api_client.get_quote_request(quote["id"], TEST_USERS["broker_ops_headers"])
        )
        assert quote_after["status"] == "WITHDRAWN"

    def test_cancel_advances_both_load_and_quote_versions_by_one(self, api):
        """PRD §3.5: "advancing both `Load.version` and
        `QuoteRequest.version` by one."

        Design: Difficulty/transitive_cascade/load_cancel_cascade_to_quote_withdrawn_depth2
        """
        shipper, carrier, quote, load, _contract = setup_awarded_load(use_contract=False)
        # Capture the post-award versions.
        load_v_before = load["version"]
        quote_after_award = get_success_data(
            api_client.get_quote_request(quote["id"], TEST_USERS["broker_ops_headers"])
        )
        quote_v_before = quote_after_award["version"]

        cancelled = get_success_data(
            api_client.cancel_load(load["id"], TEST_USERS["broker_ops_headers"])
        )
        quote_after_cancel = get_success_data(
            api_client.get_quote_request(quote["id"], TEST_USERS["broker_ops_headers"])
        )
        assert cancelled["version"] == load_v_before + 1
        assert quote_after_cancel["version"] == quote_v_before + 1
