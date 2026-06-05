"""Difficulty Rule 3 — non_linear_state_machine.

State machines whose graph has a cycle (an entity returns to a previously
visited state via a transition that mutates auxiliary fields). The Invoice
machine cycles ISSUED → DISPUTED → ISSUED on PARTIAL resolution with a
strictly-smaller `total_cents`. The Carrier machine cycles QUALIFIED →
SUSPENDED → QUALIFIED with a monotonically-advancing `version`.
"""
import pytest

from test_helpers import (
    create_carrier,
    open_dispute,
    resolve_dispute,
    set_clock,
    setup_invoiced_load,
)
from test_helpers.api_client import api_client
from test_helpers import TEST_USERS, get_success_data, validate_success


class TestInvoiceDisputePartialRevertCycle:
    def test_partial_resolution_returns_invoice_to_issued_with_reduced_total(self, api):
        """PRD §3.7: "A `PARTIAL` resolution also rewinds the invoice's
        status under the same `ISSUED`-or-`PARTIALLY_PAID` rule, but
        additionally re-runs the invoice-total calculation with the new
        partial-credit term — the net effect being that `Invoice.total_cents`
        is reduced by exactly `resolution_amount_cents`, and
        `Shipper.open_ar_cents` is recomputed to reflect both the status
        change and the total reduction."

        Design: Difficulty/non_linear_state_machine/invoice_dispute_partial_revert_cycle
        """
        shipper, carrier, _quote, _load, invoice, _contract = setup_invoiced_load(
            contract_overrides={
                "rate_per_mile_cents": 250,
                "fuel_surcharge_per_mile_cents": 60,
                "detention_free_minutes": 120,
            },
        )
        # 250+60 c/mi × 400 mi = 124000.
        assert invoice["total_cents"] == 124000

        dispute = open_dispute(invoice["id"], shipper["id"],
                               claim_type="OVERCHARGE",
                               claimed_amount_cents=10000)

        resolve_dispute(dispute["id"], resolution_kind="PARTIAL",
                        resolution_amount_cents=4000)

        # Re-fetch invoice and dispute to observe the cycle exit.
        invoice_after = get_success_data(
            api_client.get_invoice(invoice["id"], TEST_USERS["broker_ops_headers"])
        )
        dispute_after = get_success_data(
            api_client.get_dispute_claim(dispute["id"],
                                         TEST_USERS["broker_ops_headers"])
        )
        # No payments yet, so revert target is ISSUED.
        assert invoice_after["status"] == "ISSUED"
        assert invoice_after["total_cents"] == 120000
        assert dispute_after["status"] == "RESOLVED"
        assert dispute_after["resolution_kind"] == "PARTIAL"

    def test_dispute_opening_flips_invoice_to_disputed_in_same_transaction(self, api):
        """PRD §3.7: "When the claim is created, the new `DisputeClaim` row
        enters `OPEN`, and in the same transaction the parent invoice
        transitions to `DISPUTED`, advancing `Invoice.version` by one."

        Design: Difficulty/non_linear_state_machine/invoice_dispute_partial_revert_cycle
        """
        shipper, _carrier, _quote, _load, invoice, _contract = setup_invoiced_load()
        # Capture the original version before opening the dispute.
        version_before = invoice["version"]

        dispute = open_dispute(invoice["id"], shipper["id"],
                               claim_type="OVERCHARGE",
                               claimed_amount_cents=5000)
        assert dispute["status"] == "OPEN"

        invoice_after = get_success_data(
            api_client.get_invoice(invoice["id"], TEST_USERS["broker_ops_headers"])
        )
        assert invoice_after["status"] == "DISPUTED"
        assert invoice_after["version"] == version_before + 1


class TestCarrierQualifiedSuspendReinstateCycle:
    def test_reinstate_returns_carrier_to_qualified_with_advanced_version(self, api):
        """PRD §3.1: "Once `QUALIFIED`, a carrier may be moved to `SUSPENDED`
        by a `BrokerOps` operator at any time without supplying a reason. A
        suspended carrier may be brought back to `QUALIFIED` by reinstatement,
        which re-verifies `insurance_expiry_utc` against the current server
        time and rejects with `ERR_INSURANCE_EXPIRED` if the insurance has
        since lapsed."
        PRD §2.4: "a non-negative integer that starts at 1 (or any value
        the implementation chooses) on creation and increments by exactly
        one on every mutation, including state transitions and
        computed-field refreshes."

        Design: Difficulty/non_linear_state_machine/carrier_qualified_suspend_reinstate_cycle
        """
        set_clock("2026-06-01T00:00:00Z")
        carrier = create_carrier(
            smartway_tier="BRONZE",
            insurance_expiry_utc="2027-01-01T00:00:00Z",
            safety_score=30.0,
        )
        v0 = carrier["version"]

        qualified = get_success_data(
            api_client.qualify_carrier(carrier["id"], TEST_USERS["broker_ops_headers"])
        )
        assert qualified["qualification_status"] == "QUALIFIED"
        assert qualified["version"] == v0 + 1

        suspended = get_success_data(
            api_client.suspend_carrier(carrier["id"], TEST_USERS["broker_ops_headers"])
        )
        assert suspended["qualification_status"] == "SUSPENDED"
        assert suspended["version"] == v0 + 2

        reinstated = get_success_data(
            api_client.reinstate_carrier(carrier["id"], TEST_USERS["broker_ops_headers"])
        )
        assert reinstated["qualification_status"] == "QUALIFIED"
        assert reinstated["version"] > v0 + 2

    def test_each_state_change_increments_version_monotonically(self, api):
        """PRD §2.4: "a non-negative integer that starts at 1 (or any value
        the implementation chooses) on creation and increments by exactly one
        on every mutation, including state transitions and computed-field
        refreshes."

        Design: Difficulty/non_linear_state_machine/carrier_qualified_suspend_reinstate_cycle
        """
        set_clock("2026-06-01T00:00:00Z")
        carrier = create_carrier(
            smartway_tier="BRONZE",
            insurance_expiry_utc="2027-01-01T00:00:00Z",
            safety_score=30.0,
        )
        versions = [carrier["version"]]

        for action in (
            api_client.qualify_carrier,
            api_client.suspend_carrier,
            api_client.reinstate_carrier,
        ):
            updated = get_success_data(
                action(carrier["id"], TEST_USERS["broker_ops_headers"])
            )
            versions.append(updated["version"])

        # Each transition must advance the version by exactly 1.
        diffs = [b - a for a, b in zip(versions, versions[1:])]
        assert diffs == [1, 1, 1], (
            f"Carrier.version did not advance by exactly 1 per transition: {versions}"
        )
