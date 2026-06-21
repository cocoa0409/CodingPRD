"""Boundary-precision checks: auto-reload threshold and HOV occupancy minimum."""
import pytest
from test_helpers import (
    validate_success,
    setup_account_near_threshold, setup_bound_account, create_plaza,
    create_account, create_vehicle, create_transponder, bind_transponder,
    record_transponder_read, price, create_hov_window_payload,
    api_client, TEST_USERS, make_account_holder_headers,
)

OP = TEST_USERS["toll_operator_headers"]


class TestAutoReloadThresholdBoundary:
    def test_reload_fires_when_balance_lands_exactly_at_threshold(self, api):
        """PRD §3.1: "If `auto_reload_enabled` is true and the resulting `balance_cents`
        is at or below `low_balance_threshold_cents` (the boundary is inclusive — equal
        counts), a reload fires. Under `FIXED`, the credited amount is exactly
        `reload_amount_cents`."

        Design: Difficulty/boundary_precision_check/auto_reload_fires_at_threshold_inclusive
        """
        account, txn = setup_account_near_threshold(
            seed_balance=1400, threshold=1000, reload_amount=4000, reload_policy="FIXED",
            base_rate_cents=400, serial="TP-BND")
        price(txn["id"])
        acct = validate_success(api.get_account(account["id"], OP), 200)
        # 1400 - 400 = 1000 (== threshold) -> reload +4000 = 5000
        assert acct["balance_cents"] == 5000, f"expected 5000, got {acct['balance_cents']}"

    def test_reload_appends_reload_credit_ledger_entry(self, api):
        """PRD §3.1: "Auto-reload is evaluated immediately after any ledger entry that
        decreases the balance ... a reload fires. Under `FIXED`, the credited amount is
        exactly `reload_amount_cents`. ... Each reload appends a `LedgerEntry` of type
        `RELOAD_CREDIT`."

        Design: Difficulty/boundary_precision_check/auto_reload_fires_at_threshold_inclusive
        """
        account, txn = setup_account_near_threshold(
            seed_balance=1400, threshold=1000, reload_amount=4000, reload_policy="FIXED",
            base_rate_cents=400, serial="TP-BND2")
        price(txn["id"])
        entries = validate_success(api.list_account_ledger_entries(account["id"], OP), 200)
        reloads = [e for e in entries if e["entry_type"] == "RELOAD_CREDIT"
                   and e["amount_cents"] == 4000]
        assert len(reloads) >= 1, "expected a RELOAD_CREDIT of +4000 at the inclusive boundary"

    def test_no_reload_when_balance_one_above_threshold(self, api):
        """PRD §3.1: "If `auto_reload_enabled` is true and the resulting `balance_cents`
        is at or below `low_balance_threshold_cents` (the boundary is inclusive — equal
        counts), a reload fires."

        Design: Corner/cross_cutting_complexity_layers/rate_threshold_no_reload_above_threshold
        """
        account, txn = setup_account_near_threshold(
            seed_balance=1401, threshold=1000, reload_amount=4000, reload_policy="FIXED",
            base_rate_cents=400, serial="TP-NR")
        price(txn["id"])
        acct = validate_success(api.get_account(account["id"], OP), 200)
        # 1401 - 400 = 1001 (> threshold) -> NO reload
        assert acct["balance_cents"] == 1001, f"expected 1001, got {acct['balance_cents']}"


class TestHovOccupancyBoundary:
    def test_exemption_granted_at_min_occupants_inclusive(self, api):
        """PRD §3.6: "If a `DECLARED` `HovWindow` on the resolved vehicle covers
        `read_at` and its `declared_occupants` is greater than or equal to the plaza's
        `hov_min_occupants`, the transaction goes to `EXEMPT`: `hov_exempt` is set to
        true, `gross_toll_cents` is still computed, `toll_cents` is set to 0, no account
        debit occurs, and the settlement dimension moves from `UNSETTLED` to `SETTLED`".

        Design: Difficulty/boundary_precision_check/hov_exemption_at_min_occupants_inclusive
        """
        account = create_account()
        vehicle = create_vehicle(account["id"], plate_number="HOV1", hov_capable=True)
        transponder = create_transponder(account["id"], "TP-HOV")
        bind_transponder(account["id"], transponder["id"], vehicle["id"], vehicle["version"])
        holder = make_account_holder_headers(account["id"])
        api.create_hov_window(create_hov_window_payload(
            vehicle["id"], "2026-02-09T07:00:00Z", "2026-02-09T10:00:00Z", 3), holder)
        plaza = create_plaza(base_rate_cents=400, hov_min_occupants=3)
        txn = record_transponder_read(plaza["id"], transponder["id"], "2026-02-09T08:00:00Z",
                                      is_peak=False, declared_axles=2)
        priced = price(txn["id"])
        assert priced["pricing_status"] == "EXEMPT"
        assert priced["hov_exempt"] is True
        assert priced["toll_cents"] == 0

    def test_exempt_read_settles_with_zero_toll(self, api):
        """PRD §3.6: "the transaction goes to `EXEMPT`: `hov_exempt` is set to true,
        `gross_toll_cents` is still computed, `toll_cents` is set to 0, no account debit
        occurs, and the settlement dimension moves from `UNSETTLED` to `SETTLED` because
        nothing is owed."

        Design: Difficulty/boundary_precision_check/hov_exemption_at_min_occupants_inclusive
        """
        account = create_account()
        vehicle = create_vehicle(account["id"], plate_number="HOV2", hov_capable=True)
        transponder = create_transponder(account["id"], "TP-HOV2")
        bind_transponder(account["id"], transponder["id"], vehicle["id"], vehicle["version"])
        holder = make_account_holder_headers(account["id"])
        api.create_hov_window(create_hov_window_payload(
            vehicle["id"], "2026-02-09T07:00:00Z", "2026-02-09T10:00:00Z", 3), holder)
        plaza = create_plaza(base_rate_cents=400, hov_min_occupants=3)
        txn = record_transponder_read(plaza["id"], transponder["id"], "2026-02-09T08:00:00Z",
                                      is_peak=False, declared_axles=2)
        priced = price(txn["id"])
        assert priced["settlement_status"] == "SETTLED"
        acct = validate_success(api.get_account(account["id"], OP), 200)
        assert acct["balance_cents"] == 0, "no debit occurs on an exempt read"
