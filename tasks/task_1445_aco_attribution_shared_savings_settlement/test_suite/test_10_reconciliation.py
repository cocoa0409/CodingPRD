"""Reconciliation adjustments: ledger balance conservation and reversal gate."""
import pytest

from test_helpers import (
    ApiErrorId,
    make_actuary_headers,
    post_adjustment,
    reverse_adjustment,
    setup_lite_final_settlement,
    validate_error,
    validate_success,
)

ACTUARY = make_actuary_headers()


class TestReconciliationBalanceConservation:
    def test_adjustments_move_reconciliation_balance(self, api, actuary_headers):
        """PRD §3.8: "the settlement's `reconciliation_balance_cents` is
        maintained as the sum of `POSTED` credit amounts minus the sum of
        `POSTED` debit amounts."

        Design: Difficulty/compensating_invariant/post_then_reverse_conserves_reconciliation_balance
        """
        ctx = setup_lite_final_settlement(tax_id="ACO-RA")
        settlement = ctx["settlement"]
        assert settlement["reconciliation_balance_cents"] == 0
        post_adjustment(settlement["id"], "CREDIT", 5000, "APPEAL_AWARD")
        post_adjustment(settlement["id"], "DEBIT", 2000, "CLAWBACK")
        after = validate_success(api.get_settlement(settlement["id"], actuary_headers), 200)
        assert after["reconciliation_balance_cents"] == 3000

    def test_reversals_restore_zero_balance(self, api, actuary_headers):
        """PRD §3.8: "Reversal moves a `POSTED` adjustment to `REVERSED` —
        attempting it in any other status draws `ERR_ADJUSTMENT_NOT_POSTED` —
        and the balance is recomputed over `POSTED` adjustments only, so a
        reversed entry simply drops out of the ledger."

        Design: Difficulty/compensating_invariant/post_then_reverse_conserves_reconciliation_balance
        """
        ctx = setup_lite_final_settlement(tax_id="ACO-RA2")
        settlement = ctx["settlement"]
        adj1 = post_adjustment(settlement["id"], "CREDIT", 5000, "APPEAL_AWARD")
        adj2 = post_adjustment(settlement["id"], "DEBIT", 2000, "CLAWBACK")
        reverse_adjustment(adj1["id"])
        reverse_adjustment(adj2["id"])
        after = validate_success(api.get_settlement(settlement["id"], actuary_headers), 200)
        assert after["reconciliation_balance_cents"] == 0

    def test_reverse_already_reversed_adjustment_rejected(self, api, actuary_headers):
        """PRD §3.8: "Reversal moves a `POSTED` adjustment to `REVERSED` —
        attempting it in any other status draws `ERR_ADJUSTMENT_NOT_POSTED`".

        Design: Corner/validations/reverse_already_reversed_adjustment_rejected
        """
        ctx = setup_lite_final_settlement(tax_id="ACO-V15")
        adj = post_adjustment(ctx["settlement"]["id"], "CREDIT", 1000, "X")
        reverse_adjustment(adj["id"])
        res = api.reverse_reconciliation_adjustment(adj["id"], actuary_headers)
        validate_error(res, ApiErrorId.ERR_ADJUSTMENT_NOT_POSTED, expected_status=409)
