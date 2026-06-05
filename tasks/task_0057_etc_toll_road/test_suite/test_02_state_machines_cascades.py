"""Parallel/cyclic state machines and transitive cascades."""
import pytest
from test_helpers import (
    validate_success, get_success_data,
    setup_plate_violation, setup_priced_unsettled_plate_read, setup_bound_account,
    setup_delinquent_account_contested, setup_account_near_threshold,
    create_plaza, record_transponder_read, price, create_account, create_vehicle,
    api_client, TEST_USERS, make_account_holder_headers,
)

OP = TEST_USERS["toll_operator_headers"]


class TestParallelDimensions:
    def test_plate_read_priced_then_in_violation(self, api):
        """PRD §3.6: "A toll transaction carries two independent status dimensions that
        evolve separately on the same row."
        PRD §3.8: "It creates a `Violation` in `ASSESSED` status ... moves the linked
        transaction's settlement dimension from `UNSETTLED` to `IN_VIOLATION`".

        Design: Difficulty/non_linear_state_machine/toll_transaction_parallel_pricing_and_settlement
        """
        account, vehicle, plaza, txn = setup_priced_unsettled_plate_read(plate_number="PAR1")
        assert txn["pricing_status"] == "PRICED"
        assert txn["settlement_status"] == "UNSETTLED"
        viol = validate_success(api.create_violation({"toll_transaction_id": txn["id"]}, OP), 201)
        after = validate_success(api.get_toll_transaction(txn["id"], OP), 200)
        assert after["pricing_status"] == "PRICED"
        assert after["settlement_status"] == "IN_VIOLATION"

    def test_pricing_dimension_unchanged_by_settlement_move(self, api):
        """PRD §3.6: "two independent status dimensions that evolve separately on the
        same row. The pricing dimension, `pricing_status`, is one of `PENDING`, `PRICED`,
        `EXEMPT`, or `REPRICED`. The settlement dimension, `settlement_status`, is one of
        `UNSETTLED`, `SETTLED`, `IN_VIOLATION`, or `WRITTEN_OFF`."

        Design: Difficulty/non_linear_state_machine/toll_transaction_parallel_pricing_and_settlement
        """
        account, vehicle, plaza, txn, viol = setup_plate_violation(plate_number="PAR2")
        after = validate_success(api.get_toll_transaction(txn["id"], OP), 200)
        # settlement moved to IN_VIOLATION but pricing stays PRICED
        assert after["settlement_status"] == "IN_VIOLATION"
        assert after["pricing_status"] == "PRICED"


class TestViolationCycle:
    def test_reject_dispute_returns_to_assessed_and_increments_tier(self, api):
        """PRD §3.8: "Rejecting the dispute moves it from `CONTESTED` back to `ASSESSED`,
        increments `escalation_tier` by 1, recomputes `penalty_cents` and
        `fine_total_cents` at the new tier, and recomputes the account's
        `outstanding_fines_cents`."

        Design: Difficulty/non_linear_state_machine/violation_cyclic_contest_reject_reissue
        """
        account, vehicle, plaza, txn, viol = setup_plate_violation(plate_number="CYC1")
        api.contest_violation(viol["id"], {"dispute_reason": "not me"},
                              make_account_holder_headers(account["id"]))
        rejected = validate_success(api.reject_dispute(viol["id"], OP), 200)
        assert rejected["settlement_status"] == "ASSESSED"
        assert rejected["escalation_tier"] == 2

    def test_reject_dispute_recomputes_fine_at_tier_two(self, api):
        """PRD §3.8: "The penalty is a flat base administrative penalty of 2500 cents
        plus 1500 cents for each re-issue cycle beyond the first — that is, 2500 plus
        1500 multiplied by the quantity (`escalation_tier` minus 1). The
        `fine_total_cents` is `toll_due_cents` plus `penalty_cents`."

        Design: Difficulty/non_linear_state_machine/violation_cyclic_contest_reject_reissue
        """
        account, vehicle, plaza, txn, viol = setup_plate_violation(plate_number="CYC2")
        # toll_due = 750 (plate peak). tier 2 penalty = 2500 + 1500 = 4000. fine = 4750.
        api.contest_violation(viol["id"], {"dispute_reason": "not me"},
                              make_account_holder_headers(account["id"]))
        rejected = validate_success(api.reject_dispute(viol["id"], OP), 200)
        assert rejected["fine_total_cents"] == 4750, \
            f"expected 4750, got {rejected['fine_total_cents']}"


class TestTransitiveCascades:
    def test_price_debit_triggers_autoreload_depth3(self, api):
        """PRD §3.6: "the account's `balance_cents` is debited by `toll_cents`, a
        `TOLL_DEBIT` ledger entry for the negative `toll_cents` is appended, and the
        settlement dimension moves from `UNSETTLED` to `SETTLED`."
        PRD §3.1: "Auto-reload is evaluated immediately after any ledger entry that
        decreases the balance ... If `auto_reload_enabled` is true and the resulting
        `balance_cents` is at or below `low_balance_threshold_cents` (the boundary is
        inclusive — equal counts), a reload fires."

        Design: Difficulty/transitive_cascade/price_debit_lowbalance_autoreload_depth3
        """
        account, txn = setup_account_near_threshold(
            seed_balance=900, threshold=1000, reload_amount=4000, reload_policy="FIXED",
            base_rate_cents=400, serial="TP-CSC")
        priced = price(txn["id"])
        assert priced["settlement_status"] == "SETTLED"
        acct = validate_success(api.get_account(account["id"], OP), 200)
        # 900 - 400 = 500 (<= 1000) -> +4000 = 4500
        assert acct["balance_cents"] == 4500, f"expected 4500, got {acct['balance_cents']}"

    def test_price_debit_autoreload_writes_both_ledger_entries(self, api):
        """PRD §3.6: "a `TOLL_DEBIT` ledger entry for the negative `toll_cents` is
        appended". PRD §3.1: "Each reload appends a `LedgerEntry` of type
        `RELOAD_CREDIT`."

        Design: Difficulty/transitive_cascade/price_debit_lowbalance_autoreload_depth3
        """
        account, txn = setup_account_near_threshold(
            seed_balance=900, threshold=1000, reload_amount=4000, reload_policy="FIXED",
            base_rate_cents=400, serial="TP-CSC2")
        price(txn["id"])
        entries = validate_success(
            api.list_account_ledger_entries(account["id"], OP), 200)
        by_type = {}
        for e in entries:
            by_type.setdefault(e["entry_type"], []).append(e)
        assert any(e["amount_cents"] == -400 for e in by_type.get("TOLL_DEBIT", [])), \
            "expected a TOLL_DEBIT of -400"
        assert any(e["amount_cents"] == 4000 for e in by_type.get("RELOAD_CREDIT", [])), \
            "expected a RELOAD_CREDIT of +4000"

    def test_accept_dispute_writeoff_clears_delinquent_depth3(self, api):
        """PRD §3.8: "Accepting the dispute moves it from `CONTESTED` to the terminal
        `DISMISSED`; as cascades, the linked transaction moves from `IN_VIOLATION` to
        `WRITTEN_OFF`, the account's `outstanding_fines_cents` is recomputed, and if that
        total is now 0 and the account is `DELINQUENT`, the account returns to `ACTIVE`."

        Design: Difficulty/transitive_cascade/accept_dispute_writeoff_delinquent_clears_depth3
        """
        account, vehicle, plaza, txn, viol = setup_delinquent_account_contested()
        dismissed = validate_success(api.accept_dispute(viol["id"], OP), 200)
        assert dismissed["settlement_status"] == "DISMISSED"
        after_txn = validate_success(api.get_toll_transaction(txn["id"], OP), 200)
        assert after_txn["settlement_status"] == "WRITTEN_OFF"
        acct = validate_success(api.get_account(account["id"], OP), 200)
        assert acct["status"] == "ACTIVE"
        assert acct["outstanding_fines_cents"] == 0

    def test_accept_dispute_recomputes_outstanding_to_zero(self, api):
        """PRD §3.8: "the account's `outstanding_fines_cents` is recomputed, and if that
        total is now 0 and the account is `DELINQUENT`, the account returns to `ACTIVE`."
        PRD §3.1: "A read-only `outstanding_fines_cents` on the account is the sum of
        `fine_total_cents` over every `Violation` of that account whose settlement status
        is `ASSESSED` or `CONTESTED`; violations that are `SETTLED` or `DISMISSED` are
        excluded."

        Design: Difficulty/transitive_cascade/accept_dispute_writeoff_delinquent_clears_depth3
        """
        account, vehicle, plaza, txn, viol = setup_delinquent_account_contested()
        api.accept_dispute(viol["id"], OP)
        acct = validate_success(api.get_account(account["id"], OP), 200)
        assert acct["outstanding_fines_cents"] == 0
