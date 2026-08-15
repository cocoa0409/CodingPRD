"""Renter-ledger conservation: FINAL issuance accrues, FEE_PAYMENT cancels the
accrual exactly, and a damage claim above the held deposit splits into
DEPOSIT_FORFEIT plus a DAMAGE invoice with no cents lost (PRD §3.5, §3.6, §3.8)."""
import pytest

from test_helpers import (
    validate_success,
    sum_txns, txns_of_kind, invoice_of_kind,
    make_renter_headers,
    setup_completed_permit, make_damage_assessment, pay_fee,
    api_client,
    TEST_USERS,
)

DIRECTOR = TEST_USERS["director_headers"]


def _completed_with_final_invoice(api):
    """NP-STD permit completed with verified 6.5 actual hours; the FINAL invoice
    (62225) is ISSUED. Returns (env, permit, final_invoice)."""
    env, req, permit, work_order = setup_completed_permit(
        deposit_cents=10000, clock_after_end="2026-09-13T12:00:00Z",
        actual_hours=6.5, idempotency_key="dep-k-1",
        event_title="Auction Night", headcount_estimate=200,
        starts_at="2026-09-13T00:00:00Z", ends_at="2026-09-13T04:00:00Z")
    invoices = validate_success(api.list_permit_invoices(permit["id"], DIRECTOR))
    return env, permit, invoice_of_kind(invoices, "FINAL")


class TestInvoiceAccrualPayAndDamageShortfallConservation:
    def test_final_invoice_issuance_and_payment_cancel_exactly(self, api):
        """PRD §3.6: "Issuance of a `FINAL` or `DAMAGE` invoice accrues
        `total_cents` onto the renter's `outstanding_balance_cents`."
        PRD §3.5: "Settling the `FINAL` invoice — while that invoice is `ISSUED`
        — moves the permit's financial dimension `INVOICED` → `SETTLED`, reduces
        the renter's `outstanding_balance_cents` by the payment, and releases the
        deposit: a `DEPOSIT_REFUND` transaction posts for the full
        `deposit_held_cents`, unless a damage assessment in `OPEN`,
        `ADJUDICATED`, or `APPEALED` exists for the permit, in which case the
        deposit stays held and the financial dimension moves to `FORFEIT_PENDING`
        instead (§3.8)."

        Design: Difficulty/compensating_invariant/invoice_accrual_pay_and_damage_shortfall_conservation
        """
        env, permit, final = _completed_with_final_invoice(api)
        assert final["total_cents"] == 62225
        org = validate_success(api.get_renter(env["org"]["id"], DIRECTOR))
        assert org["outstanding_balance_cents"] == 62225, "FINAL issuance accrues"

        pay_fee(env, permit["id"], final["id"], 62225, "fee-k-1")

        paid = validate_success(api.get_invoice(final["id"], DIRECTOR))
        assert paid["invoice_status"] == "PAID"
        assert paid["amount_paid_cents"] == 62225
        org = validate_success(api.get_renter(env["org"]["id"], DIRECTOR))
        assert org["outstanding_balance_cents"] == 0, "issue/pay pair cancels exactly"
        settled = validate_success(api.get_permit(permit["id"], DIRECTOR))
        assert settled["financial_status"] == "SETTLED"
        payments = validate_success(api.list_permit_payments(permit["id"], DIRECTOR))
        # No open damage assessment existed at settlement: deposit released.
        assert sum_txns(payments, "DEPOSIT_REFUND") == 10000

    def test_damage_shortfall_splits_and_conserves(self, api):
        """PRD §3.8: "The amount applied to damage is the smaller of the held
        deposit and the adjudicated amount; the rest of the held deposit comes
        back to the renter as a `DEPOSIT_REFUND`; and any adjudicated shortfall
        beyond the deposit becomes a `DAMAGE` invoice — a `DAMAGE_CHARGE` — added
        to the renter's `outstanding_balance_cents`. The allocation conserves on
        both sides: applied-to-damage plus deposit-refunded equals the held
        deposit, and applied-to-damage plus shortfall equals the adjudicated
        amount."
        PRD §3.8: "Intake belongs to the `SiteCoordinator`: on a `COMPLETED`
        permit, they record a **DamageAssessment** whose `line_items` form a
        non-empty array, each entry carrying a `description` and a
        `repair_cost_cents` strictly greater than zero — an empty array or any
        non-positive cost is rejected with `ERR_EMPTY_DAMAGE_CLAIM`."

        Design: Difficulty/compensating_invariant/invoice_accrual_pay_and_damage_shortfall_conservation
        """
        env, permit, final = _completed_with_final_invoice(api)
        # Intake freezes the deposit BEFORE the FINAL invoice is settled, so the
        # forfeiture allocation still has the held deposit to draw on.
        assessment = make_damage_assessment(permit["id"], [
            {"description": "Stage damage", "repair_cost_cents": 15000}])
        frozen = validate_success(api.get_permit(permit["id"], DIRECTOR))
        assert frozen["financial_status"] == "FORFEIT_PENDING"

        # The issue/pay pair still cancels exactly; the deposit stays held.
        pay_fee(env, permit["id"], final["id"], 62225, "fee-k-2")
        org = validate_success(api.get_renter(env["org"]["id"], DIRECTOR))
        assert org["outstanding_balance_cents"] == 0
        held = validate_success(api.get_permit(permit["id"], DIRECTOR))
        assert held["financial_status"] == "FORFEIT_PENDING"
        assert held["deposit_held_cents"] == 10000

        validate_success(api.adjudicate_damage_assessment(
            assessment["id"], {"adjudicated_amount_cents": 15000}, DIRECTOR))
        validate_success(api.accept_damage_assessment(
            assessment["id"], make_renter_headers(env["org"]["id"])))

        payments = validate_success(api.list_permit_payments(permit["id"], DIRECTOR))
        assert sum_txns(payments, "DEPOSIT_FORFEIT") == 10000
        assert txns_of_kind(payments, "DEPOSIT_REFUND") == [], (
            "held deposit fully applied: nothing left to refund")
        invoices = validate_success(api.list_permit_invoices(permit["id"], DIRECTOR))
        damage = invoice_of_kind(invoices, "DAMAGE")
        assert damage["total_cents"] == 5000
        assert damage["invoice_status"] == "ISSUED"

        # Conservation: applied_to_damage + damage_shortfall == adjudicated.
        assert 10000 + 5000 == 15000
        # and applied_to_damage + deposit_refunded == held deposit.
        assert 10000 + 0 == 10000

        org = validate_success(api.get_renter(env["org"]["id"], DIRECTOR))
        assert org["outstanding_balance_cents"] == 5000, "DAMAGE accrual"
        assert org["forfeiture_count"] == 1
        forfeited = validate_success(api.get_permit(permit["id"], DIRECTOR))
        assert forfeited["financial_status"] == "FORFEITED"

        # The DAMAGE accrual is itself settled by payment, returning to zero.
        pay_fee(env, permit["id"], damage["id"], 5000, "fee-k-3")
        org = validate_success(api.get_renter(env["org"]["id"], DIRECTOR))
        assert org["outstanding_balance_cents"] == 0
        damage_paid = validate_success(api.get_invoice(damage["id"], DIRECTOR))
        assert damage_paid["invoice_status"] == "PAID"
