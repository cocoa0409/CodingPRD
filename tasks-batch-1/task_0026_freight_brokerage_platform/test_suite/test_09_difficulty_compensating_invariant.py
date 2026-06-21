"""Difficulty Rule 9 — compensating_invariant.

Two conserved-quantity invariants the PRD pins by name: Shipper.open_ar_cents
is unchanged across a dispute open + withdraw round-trip, and
Load.accessorial_total_cents is unchanged across a forward
add-accessorial / compensating PARTIAL-resolution pair.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    attach_accessorial,
    get_success_data,
    open_dispute,
    resolve_dispute,
    setup_delivered_load,
    setup_invoiced_load,
    withdraw_dispute,
)
from test_helpers.api_client import api_client


class TestShipperOpenArConservedAcrossDisputeWithdrawRoundtrip:
    def test_shipper_open_ar_unchanged_after_dispute_open_then_withdraw(self, api):
        """PRD §2.9: "The forward action is recording a payment: `POST
        /freight/invoices/{id}/payments` adds `amount_cents` to
        `Invoice.amount_paid_cents`, which mechanically reduces the open-AR
        sum. The compensating action is `POST
        /freight/dispute-claims/{id}/withdraw`: a dispute withdraw restores
        the invoice's `status` to its pre-`DISPUTED` value without changing
        `total_cents` or `amount_paid_cents`, so the invoice's contribution
        to open AR returns to the same number it held before the dispute
        was opened. Forward action paired with compensating action must
        leave `Shipper.open_ar_cents` exactly unchanged — there is no drift
        tolerance."

        Design: Difficulty/compensating_invariant/shipper_open_ar_conserved_across_dispute_withdraw_roundtrip
        """
        # 250 c/mi total × 400 mi = 100000.
        shipper, _carrier, _quote, _load, invoice, _contract = setup_invoiced_load(
            contract_overrides={
                "rate_per_mile_cents": 200,
                "fuel_surcharge_per_mile_cents": 50,
            },
        )
        # Invoice issued, no payments yet → open_ar contribution = total_cents.
        assert invoice["total_cents"] == 100000

        shipper_after_invoice = get_success_data(
            api_client.get_shipper(shipper["id"], TEST_USERS["broker_ops_headers"])
        )
        ar_before = shipper_after_invoice["open_ar_cents"]
        assert ar_before == 100000

        dispute = open_dispute(invoice["id"], shipper["id"],
                               claim_type="OVERCHARGE",
                               claimed_amount_cents=5000)
        withdraw_dispute(dispute["id"], shipper["id"])

        shipper_after = get_success_data(
            api_client.get_shipper(shipper["id"], TEST_USERS["broker_ops_headers"])
        )
        assert shipper_after["open_ar_cents"] == ar_before

        # Invoice itself is back at its pre-DISPUTED status (ISSUED, given no
        # payments) and total_cents/amount_paid_cents are untouched.
        invoice_after = get_success_data(
            api_client.get_invoice(invoice["id"], TEST_USERS["broker_ops_headers"])
        )
        assert invoice_after["status"] == "ISSUED"
        assert invoice_after["total_cents"] == 100000
        assert invoice_after["amount_paid_cents"] == 0

    def test_dispute_withdraw_does_not_change_invoice_total_or_amount_paid(self, api):
        """PRD §2.9: "The compensating action is `POST
        /freight/dispute-claims/{id}/withdraw`: a dispute withdraw
        restores the invoice's `status` to its pre-`DISPUTED` value
        without changing `total_cents` or `amount_paid_cents`, so the
        invoice's contribution to open AR returns to the same number it
        held before the dispute was opened."

        Design: Difficulty/compensating_invariant/shipper_open_ar_conserved_across_dispute_withdraw_roundtrip
        """
        shipper, _carrier, _quote, _load, invoice, _contract = setup_invoiced_load(
            contract_overrides={
                "rate_per_mile_cents": 200,
                "fuel_surcharge_per_mile_cents": 50,
            },
        )
        total_before = invoice["total_cents"]
        paid_before = invoice["amount_paid_cents"]

        dispute = open_dispute(invoice["id"], shipper["id"],
                               claim_type="OVERCHARGE",
                               claimed_amount_cents=5000)
        withdraw_dispute(dispute["id"], shipper["id"])

        invoice_after = get_success_data(
            api_client.get_invoice(invoice["id"], TEST_USERS["broker_ops_headers"])
        )
        assert invoice_after["total_cents"] == total_before
        assert invoice_after["amount_paid_cents"] == paid_before


class TestLoadAccessorialTotalConservedAcrossPartialDisputeResolution:
    def test_partial_resolution_reduces_invoice_total_but_not_load_accessorial_total(self, api):
        """PRD §2.9: "The compensating action is an `OVERCHARGE` dispute
        claim resolved as `PARTIAL` with `resolution_amount_cents` equal
        to the disputed accessorial's `amount_cents`: that resolution
        reduces `Invoice.total_cents` by exactly the same amount but does
        not mutate `Load.accessorial_total_cents`, preserving the broader
        invariant that the invoice's total equals the load's agreed rate
        plus its detention charge plus its accessorial total minus the
        cumulative partial-resolution credits."

        Design: Difficulty/compensating_invariant/load_accessorial_total_conserved_across_partial_dispute_resolution
        """
        # Delivered load with no detention; attach LUMPER 5000 BEFORE invoicing.
        shipper, carrier, _quote, load, _contract = setup_delivered_load(
            contract_overrides={
                "rate_per_mile_cents": 200,
                "fuel_surcharge_per_mile_cents": 50,
            },
        )
        attach_accessorial(load["id"], code="LUMPER", amount_cents=5000,
                           note="Lumper at destination")
        load_after_acc = get_success_data(
            api_client.get_load(load["id"], TEST_USERS["broker_ops_headers"])
        )
        # Load.accessorial_total_cents = 5000.
        assert load_after_acc["accessorial_total_cents"] == 5000

        # Now invoice and dispute.
        invoice = get_success_data(
            api_client.invoice_load(load["id"], TEST_USERS["broker_ops_headers"])
        )
        # Invoice.total_cents = agreed (100000) + 0 detention + 5000 accessorial = 105000.
        assert invoice["total_cents"] == 105000

        dispute = open_dispute(invoice["id"], shipper["id"],
                               claim_type="OVERCHARGE",
                               claimed_amount_cents=5000)
        resolve_dispute(dispute["id"], resolution_kind="PARTIAL",
                        resolution_amount_cents=5000)

        invoice_after = get_success_data(
            api_client.get_invoice(invoice["id"], TEST_USERS["broker_ops_headers"])
        )
        load_after = get_success_data(
            api_client.get_load(load["id"], TEST_USERS["broker_ops_headers"])
        )
        # Invoice.total_cents reduced by exactly 5000 → 100000.
        assert invoice_after["total_cents"] == 100000
        # Load.accessorial_total_cents untouched → 5000.
        assert load_after["accessorial_total_cents"] == 5000

    def test_partial_resolution_dispute_record_persists_with_amount(self, api):
        """PRD §3.7: "In every case the resolved claim moves to `RESOLVED`
        and `DisputeClaim.version` advances by one."
        PRD §2.9: "The compensating action is an `OVERCHARGE` dispute
        claim resolved as `PARTIAL` with `resolution_amount_cents` equal
        to the disputed accessorial's `amount_cents`: that resolution
        reduces `Invoice.total_cents` by exactly the same amount but
        does not mutate `Load.accessorial_total_cents`, preserving the
        broader invariant that the invoice's total equals the load's
        agreed rate plus its detention charge plus its accessorial total
        minus the cumulative partial-resolution credits."

        Design: Difficulty/compensating_invariant/load_accessorial_total_conserved_across_partial_dispute_resolution
        """
        shipper, carrier, _quote, load, _contract = setup_delivered_load(
            contract_overrides={
                "rate_per_mile_cents": 200,
                "fuel_surcharge_per_mile_cents": 50,
            },
        )
        attach_accessorial(load["id"], code="LUMPER", amount_cents=5000)
        invoice = get_success_data(
            api_client.invoice_load(load["id"], TEST_USERS["broker_ops_headers"])
        )
        dispute = open_dispute(invoice["id"], shipper["id"],
                               claim_type="OVERCHARGE",
                               claimed_amount_cents=5000)
        resolve_dispute(dispute["id"], resolution_kind="PARTIAL",
                        resolution_amount_cents=5000)

        dispute_after = get_success_data(
            api_client.get_dispute_claim(dispute["id"],
                                          TEST_USERS["broker_ops_headers"])
        )
        assert dispute_after["status"] == "RESOLVED"
        assert dispute_after["resolution_kind"] == "PARTIAL"
        assert dispute_after["resolution_amount_cents"] == 5000
