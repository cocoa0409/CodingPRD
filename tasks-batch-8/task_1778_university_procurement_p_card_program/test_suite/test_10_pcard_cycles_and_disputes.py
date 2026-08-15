"""P-card statement cycles, aging escalation, disputes, grant reconciliation."""
from test_helpers import (
    ApiErrorId,
    assert_card_credit_invariant,
    create_department,
    create_elevation_payload,
    create_grant,
    create_pcard,
    create_transaction_payload,
    get_success_data,
    make_cardholder_headers,
    post_debit,
    read_ledger,
    reconcile_txn,
    validate_error,
    validate_paginated,
)
from test_helpers.fixtures import ADMIN

ADMIN_H = ADMIN


class TestCycleCloseEscalation:
    def _setup(self, api):
        dept = create_department(name="Library")
        card = create_pcard(
            department_id=dept["id"], cardholder_name="Pat",
            single_txn_limit_cents=100000, monthly_limit_cents=500000,
        )
        cid = card["id"]
        post_debit(cid, 50000, merchant="Amazon")
        post_debit(cid, 40000, merchant="B&N")
        first_close = get_success_data(api.close_pcard_cycle(cid, ADMIN_H))
        assert first_close["consecutive_unreconciled_cycles"] == 1
        assert first_close["cycle_index"] == 1
        assert first_close["status"] == "ACTIVE"
        elev = get_success_data(
            api.create_elevation(
                cid,
                create_elevation_payload(
                    elevated_single_txn_limit_cents=200000,
                    window_start="2026-08-20T00:00:00Z",
                    window_end="2026-08-22T00:00:00Z",
                ),
                ADMIN_H,
            )
        )
        post_debit(cid, 30000, merchant="Amazon")  # cycle-1 debit
        return card, elev

    def test_second_dirty_close_suspends_card_and_cancels_elevation(self, api):
        """PRD §3.8: "When the counter reaches two — the threshold is inclusive —
        the card is automatically suspended and its scheduled elevations are
        cancelled in the same cascade as a manual suspension."

        Design: Difficulty/transitive_cascade/pcard_cycle_close_escalation_cascade
        """
        card, elev = self._setup(api)
        second_close = get_success_data(api.close_pcard_cycle(card["id"], ADMIN_H))
        assert second_close["consecutive_unreconciled_cycles"] == 2
        assert second_close["cycle_index"] == 2
        assert second_close["status"] == "SUSPENDED"

        elevations, _ = validate_paginated(
            api.list_pcard_elevations(card["id"], ADMIN_H)
        )
        by_id = {e["id"]: e["status"] for e in elevations}
        assert by_id[elev["id"]] == "CANCELLED", (
            "the suspension cascade cancels the SCHEDULED elevation"
        )

    def test_fresh_cycle_resets_utilization_and_posting_blocked(self, api):
        """PRD §3.8: "The checkpoint then increments `cycle_index`, opening a new
        cycle; transactions of the old cycle leave the utilization base from that
        moment."
        PRD §3.7: "Posting requires the card to be `ACTIVE`: a suspended card
        rejects with `ERR_CARD_NOT_ACTIVE`, and a closed one with
        `ERR_CARD_CLOSED`."

        Design: Difficulty/transitive_cascade/pcard_cycle_close_escalation_cascade
        """
        card, _ = self._setup(api)
        get_success_data(api.close_pcard_cycle(card["id"], ADMIN_H))
        live = get_success_data(api.get_pcard(card["id"], ADMIN_H))
        assert live["status"] == "SUSPENDED"
        # 120,000 of old-cycle debits remain POSTED but leave the fresh cycle's
        # utilization base.
        assert live["utilization_cents"] == 0
        assert live["available_credit_cents"] == 500000
        assert_card_credit_invariant(live)

        blocked = api.create_pcard_transaction(
            card["id"], create_transaction_payload(amount_cents=10000),
            make_cardholder_headers(card["id"]),
        )
        validate_error(blocked, ApiErrorId.ERR_CARD_NOT_ACTIVE, 409)


class TestCycleScopedUtilization:
    def test_utilization_scoped_to_current_cycle(self, api):
        """PRD §3.8: "transactions of the old cycle leave the utilization base
        from that moment".
        PRD §3.7: "The card's `utilization_cents` is the sum of `amount_cents`
        over its debits in the current cycle whose status is `POSTED`,
        `RECONCILED`, or `DISPUTED`, minus the corresponding sum over credits in
        the current cycle that have not been `REVERSED`".

        Design: Corner/calculations/utilization_cycle_scoping_filters_old_debits
        """
        dept = create_department(name="Grounds")
        card = create_pcard(department_id=dept["id"], cardholder_name="Gil")
        cid = card["id"]
        post_debit(cid, 30000, mcc_code="5200", merchant="HomeDepot")
        closed = get_success_data(api.close_pcard_cycle(cid, ADMIN_H))
        assert closed["consecutive_unreconciled_cycles"] == 1
        assert closed["cycle_index"] == 1

        post_debit(cid, 20000, mcc_code="5200", merchant="Lowes")
        live = get_success_data(api.get_pcard(cid, ADMIN_H))
        assert live["cycle_index"] == 1
        assert live["consecutive_unreconciled_cycles"] == 1
        assert live["utilization_cents"] == 20000, (
            "only the new-cycle debit counts; the 30,000 cycle-0 debit is out"
        )
        assert live["available_credit_cents"] == 480000


class TestCreditDecompositionInvariant:
    def _setup_two_debits(self, api):
        dept = create_department(name="Facilities")
        card = create_pcard(department_id=dept["id"], cardholder_name="Jo")
        t1 = post_debit(card["id"], 80000, mcc_code="5085", merchant="Grainger")
        t2 = post_debit(card["id"], 20000, mcc_code="5085", merchant="Grainger")
        return card, t1, t2

    def test_dispute_and_reversal_move_utilization_conservatively(self, api):
        """PRD §3.7: "Disputed debits deliberately remain inside utilization;
        reversed transactions leave it entirely".
        PRD §3.8: "`CARDHOLDER_FAVOR` reverses the transaction into the terminal
        `REVERSED` status: its amount leaves utilization".

        Design: Difficulty/compensating_invariant/pcard_credit_decomposition_invariant
        """
        card, t1, _ = self._setup_two_debits(api)
        cid = card["id"]
        get_success_data(
            api.dispute_transaction(
                t1["id"], {"reason": "unrecognized"}, make_cardholder_headers(cid)
            )
        )
        during = get_success_data(api.get_pcard(cid, ADMIN_H))
        assert during["utilization_cents"] == 100000, (
            "dispute alone moves nothing: DISPUTED stays in utilization"
        )
        assert during["available_credit_cents"] == 400000

        get_success_data(
            api.resolve_dispute(t1["id"], {"outcome": "MERCHANT_FAVOR"}, ADMIN_H)
        )
        get_success_data(
            api.dispute_transaction(
                t1["id"], {"reason": "still wrong"}, make_cardholder_headers(cid)
            )
        )
        reversed_txn = get_success_data(
            api.resolve_dispute(t1["id"], {"outcome": "CARDHOLDER_FAVOR"}, ADMIN_H)
        )
        assert reversed_txn["status"] == "REVERSED"
        after = get_success_data(api.get_pcard(cid, ADMIN_H))
        assert after["utilization_cents"] == 20000
        assert after["available_credit_cents"] == 480000
        assert_card_credit_invariant(after)

    def test_credit_refund_reduces_utilization_below_debits(self, api):
        """PRD §3.7: "refunds reduce it, so utilization may legitimately go
        negative" and "A posted debit starts in `POSTED`; a posted credit starts
        directly in `RECONCILED`."

        Design: Difficulty/compensating_invariant/pcard_credit_decomposition_invariant
        """
        card, t1, t2 = self._setup_two_debits(api)
        cid = card["id"]
        get_success_data(
            api.dispute_transaction(
                t1["id"], {"reason": "unrecognized"}, make_cardholder_headers(cid)
            )
        )
        get_success_data(
            api.resolve_dispute(t1["id"], {"outcome": "CARDHOLDER_FAVOR"}, ADMIN_H)
        )
        credit = get_success_data(
            api.create_pcard_transaction(
                cid,
                create_transaction_payload(
                    amount_cents=5000, entry_type="CREDIT",
                    merchant_name="Grainger", mcc_code="5085",
                ),
                make_cardholder_headers(cid),
            )
        )
        assert credit["status"] == "RECONCILED"
        mid = get_success_data(api.get_pcard(cid, ADMIN_H))
        assert mid["utilization_cents"] == 15000  # 20,000 debit - 5,000 refund
        assert mid["available_credit_cents"] == 485000

        reconcile_txn(t2["id"], cid, receipt_reference="rcpt-2")
        final = get_success_data(api.get_pcard(cid, ADMIN_H))
        assert final["utilization_cents"] == 15000, (
            "reconciling a debit does not change utilization"
        )
        assert_card_credit_invariant(final)


class TestGrantReconcileComposition:
    def test_pcard_grant_reconcile_allowability_and_compensation(self, api):
        """PRD §3.8: "A grant allocation re-runs the sponsor's allowability
        gauntlet: the grant must exist and be `ACTIVE` (otherwise
        `ERR_GRANT_NOT_ACTIVE`), the `cost_category` must appear in its
        `allowed_categories` (otherwise `ERR_GRANT_CATEGORY_NOT_ALLOWABLE`), the
        logical clock must lie inside the inclusive budget period (otherwise
        `ERR_GRANT_BUDGET_PERIOD_EXPIRED`), and the grant's
        `provisional_remaining_cents` must cover the transaction's `amount_cents`
        (otherwise `ERR_GRANT_BUDGET_EXCEEDED`, HTTP 402)."
        PRD §3.8: "Success records the receipt reference, allocation fields, and
        `reconciled_at`, moves the transaction to `RECONCILED`, and — for grant
        allocations — adds the amount to the grant's `spent_cents` immediately."
        PRD §3.8: "if the transaction had been reconciled to a grant before the
        dispute, the same amount is compensated out of that grant's
        `spent_cents`."

        Design: Corner/cross_cutting_layers/pcard_grant_reconcile_allowability_and_compensation
        """
        dept = create_department(name="Recon")
        grant = create_grant(
            grant_code="G-PC", sponsor="NSF", total_award_cents=50000,
            allowed_categories=["SUPPLIES"],
        )
        card = create_pcard(department_id=dept["id"], cardholder_name="Quinn")
        cid = card["id"]
        t1 = post_debit(cid, 40000, merchant="Lab")
        t2 = post_debit(cid, 60000, merchant="Lab")
        reconcile_txn(
            t1["id"], cid, receipt_reference="rcpt-g1", allocation_type="GRANT",
            grant_id=grant["id"], cost_category="SUPPLIES",
        )
        ledger1 = read_ledger(grant["id"])
        assert ledger1["spent_cents"] == 40000, (
            "P-card grant spend books directly to spent, no encumbrance phase"
        )
        assert ledger1["provisional_remaining_cents"] == 10000

        bad_category = api.reconcile_transaction(
            t2["id"],
            {
                "receipt_reference": "rcpt-g2", "allocation_type": "GRANT",
                "grant_id": grant["id"], "cost_category": "TRAVEL",
            },
            make_cardholder_headers(cid),
        )
        validate_error(bad_category, ApiErrorId.ERR_GRANT_CATEGORY_NOT_ALLOWABLE, 422)

        over_budget = api.reconcile_transaction(
            t2["id"],
            {
                "receipt_reference": "rcpt-g2", "allocation_type": "GRANT",
                "grant_id": grant["id"], "cost_category": "SUPPLIES",
            },
            make_cardholder_headers(cid),
        )
        # 60,000 > provisional remaining 10,000.
        validate_error(over_budget, ApiErrorId.ERR_GRANT_BUDGET_EXCEEDED, 402)

        get_success_data(
            api.dispute_transaction(
                t1["id"], {"reason": "double-billed"}, make_cardholder_headers(cid)
            )
        )
        reversed_txn = get_success_data(
            api.resolve_dispute(t1["id"], {"outcome": "CARDHOLDER_FAVOR"}, ADMIN_H)
        )
        assert reversed_txn["status"] == "REVERSED"
        ledger2 = read_ledger(grant["id"])
        assert ledger2["spent_cents"] == 0, "full compensation, no drift"
        assert ledger2["provisional_remaining_cents"] == 50000
