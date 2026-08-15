"""Invoice settlement, refund-policy variants, funds conservation, and entrant
standing (PRD §3.3).
"""
from test_helpers import (
    ApiErrorId,
    assert_invoice,
    assert_refund_invariant,
    make_entrant_headers,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["program_admin_headers"]


class TestWithdrawalRefundPolicyDivergence:
    def test_flat_fee_withdrawal_refund_split(self, api):
        """PRD §3.3: "Under `FLAT_FEE`, the program retains a flat 2,500-cent
        withdrawal fee and refunds the remainder of `amount_cents`, clamped at
        zero."
        PRD §3.3: "Withdrawing an entry whose invoice is `PAID` instead runs the
        refund calculation: the invoice becomes `REFUNDED` with `refund_cents`
        and `retained_cents` written, and `payment_status` becomes `REFUNDED`."

        Design: Difficulty/dual_variant_calc/withdrawal_refund_policy_divergence
        """
        bundle = fx.setup_under_review_entry("GALA-FLAT")  # early tier, 10000 paid
        entry, entrant, invoice = (
            bundle["entry"],
            bundle["entrant"],
            bundle["invoice"],
        )
        assert invoice["amount_cents"] == 10000
        withdrawn = validate_success(
            api.withdraw_entry(entry["id"], make_entrant_headers(entrant["id"]))
        )
        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["payment_status"] == "REFUNDED"
        refunded = fx.get_invoice(invoice["id"])
        assert refunded["status"] == "REFUNDED"
        assert refunded["refund_cents"] == 7500
        assert refunded["retained_cents"] == 2500
        assert_refund_invariant(refunded)

    def test_early_bird_free_withdrawal_full_refund(self, api):
        """PRD §3.3: "Under `EARLY_BIRD_FREE`, an invoice whose `paid_at`
        precedes `early_fee_ends_at` is refunded in full with nothing retained"

        Design: Difficulty/dual_variant_calc/withdrawal_refund_policy_divergence
        """
        bundle = fx.setup_under_review_entry(
            "GALA-EBF", season_overrides={"refund_policy": "EARLY_BIRD_FREE"}
        )
        entry, entrant, invoice = (
            bundle["entry"],
            bundle["entrant"],
            bundle["invoice"],
        )
        # paid at 2026-08-10, before early_fee_ends_at 2026-08-20
        withdrawn = validate_success(
            api.withdraw_entry(entry["id"], make_entrant_headers(entrant["id"]))
        )
        assert withdrawn["payment_status"] == "REFUNDED"
        refunded = fx.get_invoice(invoice["id"])
        assert refunded["status"] == "REFUNDED"
        assert refunded["refund_cents"] == 10000
        assert refunded["retained_cents"] == 0
        assert_refund_invariant(refunded)


class TestWithdrawalFundsConservation:
    def test_paid_withdrawal_conserves_invoice_funds(self, api):
        """PRD §3.3: "The invariant that `refund_cents` plus `retained_cents`
        equals `amount_cents` always holds"

        Design: Difficulty/compensating_invariant/withdrawal_refund_funds_conservation
        """
        bundle = fx.setup_under_review_entry("GALA-INV2")
        entry, entrant, invoice = (
            bundle["entry"],
            bundle["entrant"],
            bundle["invoice"],
        )
        validate_success(
            api.withdraw_entry(entry["id"], make_entrant_headers(entrant["id"]))
        )
        refunded = fx.get_invoice(invoice["id"])
        assert refunded["status"] == "REFUNDED"
        assert refunded["refund_cents"] == 7500
        assert refunded["retained_cents"] == 2500
        assert_refund_invariant(refunded)

    def test_refund_clamped_at_zero_retains_full_amount(self, api):
        """PRD §3.3: "when the clamped refund is zero, the retained amount
        equals the full invoice amount."
        PRD §3.3: "Under `FLAT_FEE`, the program retains a flat 2,500-cent
        withdrawal fee and refunds the remainder of `amount_cents`, clamped at
        zero."

        Design: Difficulty/compensating_invariant/withdrawal_refund_funds_conservation
        """
        bundle = fx.setup_under_review_entry(
            "GALA-INV2C", category_overrides={"early_fee_cents": 2000}
        )
        entry, entrant, invoice = (
            bundle["entry"],
            bundle["entrant"],
            bundle["invoice"],
        )
        assert invoice["amount_cents"] == 2000
        validate_success(
            api.withdraw_entry(entry["id"], make_entrant_headers(entrant["id"]))
        )
        refunded = fx.get_invoice(invoice["id"])
        assert refunded["status"] == "REFUNDED"
        assert refunded["refund_cents"] == 0
        assert refunded["retained_cents"] == 2000
        assert_refund_invariant(refunded)


class TestInvoiceSettlement:
    def test_invoice_pay_cascades_entry_to_under_review(self, api):
        """PRD §3.3: "Payment stamps `paid_at`, moves the invoice to `PAID`,
        sets the entry's `payment_status` to `PAID`, and cascades a `SUBMITTED`
        entry into `UNDER_REVIEW`"

        Design: Corner/state_machines/side_effect_execution_invoice_cascade_on_pay
        """
        bundle = fx.setup_submitted_entry("GALA-SE")
        entry, entrant, invoice = (
            bundle["entry"],
            bundle["entrant"],
            bundle["invoice"],
        )
        assert entry["status"] == "SUBMITTED"
        paid = validate_success(
            api.pay_invoice(invoice["id"], make_entrant_headers(entrant["id"]))
        )
        assert_invoice(paid)
        assert paid["status"] == "PAID"
        assert _same_instant(paid["paid_at"], "2026-08-10T00:00:00Z")
        fetched = fx.get_entry(entry["id"])
        assert fetched["status"] == "UNDER_REVIEW"
        assert fetched["payment_status"] == "PAID"

    def test_non_owner_cannot_pay_invoice(self, api):
        """PRD §3.3: "Only the entrant that owns the invoice's entry may pay it,
        and an invoice no longer in `ISSUED` is not payable; both failures are
        `ERR_FISCAL_BLOCK`."

        Design: Corner/validations/fiscal_block_non_owner_payment
        """
        bundle = fx.setup_submitted_entry("GALA-FIS")
        entrant2 = fx.register_entrant("e2@x.com", "Entrant 2")
        invoice = bundle["invoice"]
        resp = api.pay_invoice(invoice["id"], make_entrant_headers(entrant2["id"]))
        validate_error(resp, ApiErrorId.ERR_FISCAL_BLOCK)
        fetched = fx.get_invoice(invoice["id"])
        assert fetched["status"] == "ISSUED"


class TestEntrantStanding:
    def test_overdue_invoice_marks_delinquent_and_payment_repairs(self, api):
        """PRD §3.3: "Whenever the clock sweep finds an entrant with an `ISSUED`
        invoice whose `due_at` has passed, a `GOOD` entrant becomes `DELINQUENT`
        with `delinquent_since` set to that instant; when no overdue invoice
        remains, a `DELINQUENT` entrant returns to `GOOD` and `delinquent_since`
        is cleared."
        PRD §3.3: "If the payment lands after `due_at` while the entrant is
        `DELINQUENT`, settlement also repairs their standing to `GOOD` and clears
        `delinquent_since`."

        Design: Corner/calculations/entrant_standing_delinquent_flip_and_repair
        """
        bundle = fx.setup_submitted_entry("GALA-DLN")  # due_at = 2026-08-13T00:00Z
        entrant, invoice = bundle["entrant"], bundle["invoice"]
        fx.set_clock("2026-09-01T00:00:00Z")  # well past due_at
        overdue = validate_success(api.get_entrant(entrant["id"], ADMIN))
        assert overdue["standing"] == "DELINQUENT"
        assert _same_instant(overdue["delinquent_since"], "2026-09-01T00:00:00Z")
        validate_success(
            api.pay_invoice(invoice["id"], make_entrant_headers(entrant["id"]))
        )
        repaired = validate_success(api.get_entrant(entrant["id"], ADMIN))
        assert repaired["standing"] == "GOOD"
        assert repaired.get("delinquent_since") is None


def _same_instant(actual: str, expected: str) -> bool:
    from datetime import datetime

    return datetime.fromisoformat(actual.replace("Z", "+00:00")) == datetime.fromisoformat(
        expected.replace("Z", "+00:00")
    )
