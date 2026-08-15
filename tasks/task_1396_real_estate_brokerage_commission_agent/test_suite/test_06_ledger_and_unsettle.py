"""Debit ledger, unsettle compensation, manual adjustments (PRD §3.8, §2.11)."""
import pytest
from test_helpers import (
    api_client, TEST_USERS, validate_success, validate_error, get_success_data,
    ApiErrorId, create_agent_payload, create_debit_adjustment_payload,
    setup_active_agent, setup_agent_on_plan, setup_agent_with_debit,
    setup_closed_deal, setup_settled_deal,
    get_settlement_legs, get_window_for_agent,
)


class TestSettleUnsettleCompensation:
    def test_unsettle_restores_debit_balance_and_accumulators_exactly(self, api):
        """PRD §3.8: "the debit ledger is compensated — when the settlement had a
        positive debit_recovery_cents, a DEBIT_RECOVERY_REVERSAL entry adds that
        amount back to debit_balance_cents, and when it had a positive
        fee_shortfall_cents, a FEE_SHORTFALL_REVERSAL entry subtracts that
        amount from debit_balance_cents"; "the anniversary window's accumulators
        are restored exactly".

        Design: Difficulty/compensating_invariant/settle_unsettle_leaves_debit_balance_and_accumulators_exact
        """
        agent, plan, _e = setup_agent_on_plan(agent_name="Drift Dan")
        deal = setup_closed_deal(agent["id"], address="7 Drift Ave",
                                 gross_commission_cents=5000, closing_date="2026-01-15")
        api.settle_deal(deal["id"], TEST_USERS["transaction_coordinator_headers"])
        get_success_data(api.unsettle_deal(deal["id"], TEST_USERS["transaction_coordinator_headers"]))
        after = get_success_data(api.get_agent(agent["id"], TEST_USERS["broker_admin_headers"]))
        assert after["debit_balance_cents"] == 0
        assert after["settled_deal_count"] == 0
        w0 = get_window_for_agent(agent["id"], 0)
        assert w0["company_dollar_accrued_cents"] == 0
        assert w0["royalty_accrued_cents"] == 0

    def test_unsettle_writes_compensating_ledger_entries_in_order(self, api):
        """PRD §3.8: "when it had a positive `fee_shortfall_cents`, a
        `FEE_SHORTFALL_REVERSAL` entry subtracts that amount from
        `debit_balance_cents`" — the ledger shows accrual then reversal with the
        running balance returning to zero. PRD §2.11: "Each entry records
        `resulting_balance_cents`, the agent's balance immediately after that
        entry".

        Design: Difficulty/compensating_invariant/settle_unsettle_leaves_debit_balance_and_accumulators_exact
        """
        agent, plan, _e = setup_agent_on_plan(agent_name="Drift Dan")
        deal = setup_closed_deal(agent["id"], gross_commission_cents=5000, closing_date="2026-01-15")
        api.settle_deal(deal["id"], TEST_USERS["transaction_coordinator_headers"])
        api.unsettle_deal(deal["id"], TEST_USERS["transaction_coordinator_headers"])
        entries = get_success_data(api.list_ledger_entries(
            TEST_USERS["broker_admin_headers"], params={"agent_id": agent["id"]}))
        types = [e["entry_type"] for e in entries]
        assert types == ["FEE_SHORTFALL_ACCRUAL", "FEE_SHORTFALL_REVERSAL"]
        assert entries[0]["amount_cents"] == 27710
        assert entries[0]["resulting_balance_cents"] == 27710
        assert entries[1]["amount_cents"] == -27710
        assert entries[1]["resulting_balance_cents"] == 0


class TestLedgerEntryShape:
    def test_ledger_entry_is_append_only_without_version(self, api):
        """PRD §2.5: "a debit ledger entry and a trust transaction each carry
        only id and created_at — both updated_at and version are absent from
        them, because they are never modified after creation."

        Design: Corner/entities/ledger_entry_immutability_shape
        """
        agent = setup_active_agent(name="Ledger Lou")
        entry = get_success_data(api.create_debit_adjustment(
            agent["id"], create_debit_adjustment_payload(50000, "advance desk fee"),
            TEST_USERS["broker_admin_headers"]))
        fetched = get_success_data(api.get_ledger_entry(entry["id"], TEST_USERS["broker_admin_headers"]))
        assert "id" in fetched and "created_at" in fetched
        assert "version" not in fetched
        assert "updated_at" not in fetched

    def test_manual_debit_entry_fields(self, api):
        """PRD §3.8: "a positive amount books a `MANUAL_DEBIT`"; "Each
        adjustment moves `debit_balance_cents` by the signed amount"; entries
        carry "`resulting_balance_cents`, the running balance immediately after
        the entry".

        Design: Corner/entities/ledger_entry_immutability_shape
        """
        agent = setup_active_agent(name="Ledger Lou")
        entry = get_success_data(api.create_debit_adjustment(
            agent["id"], create_debit_adjustment_payload(50000, "advance desk fee"),
            TEST_USERS["broker_admin_headers"]))
        assert entry["entry_type"] == "MANUAL_DEBIT"
        assert entry["amount_cents"] == 50000
        assert entry["resulting_balance_cents"] == 50000


class TestDebitWriteOffFloor:
    def test_write_off_may_not_exceed_balance(self, api):
        """PRD §3.8: "a negative amount books a DEBIT_WRITE_OFF whose magnitude
        may not exceed the agent's current debit balance, else
        ERR_WRITE_OFF_EXCEEDS_DEBIT (HTTP 422)."

        Design: Corner/endpoints/debit_write_off_floor_and_audit_trail
        """
        agent = setup_active_agent(name="Debt Doug")
        get_success_data(api.create_debit_adjustment(
            agent["id"], create_debit_adjustment_payload(50000, "advance E&O"),
            TEST_USERS["broker_admin_headers"]))
        get_success_data(api.create_debit_adjustment(
            agent["id"], create_debit_adjustment_payload(-20000, "goodwill write-off"),
            TEST_USERS["broker_admin_headers"]))
        resp = api.create_debit_adjustment(
            agent["id"], create_debit_adjustment_payload(-30001, "too much"),
            TEST_USERS["broker_admin_headers"])
        validate_error(resp, ApiErrorId.ERR_WRITE_OFF_EXCEEDS_DEBIT, expected_status=422)

    def test_zero_amount_adjustment_rejected_and_audit_trail_exact(self, api):
        """PRD §3.8: "A zero `amount_cents` or a missing `reason` is rejected
        with `ERR_DEBIT_ADJUSTMENT_INVALID` (HTTP 422)." PRD §2.11: "Each entry
        records `resulting_balance_cents`, the agent's balance immediately after
        that entry".

        Design: Corner/endpoints/debit_write_off_floor_and_audit_trail
        """
        agent = setup_active_agent(name="Debt Doug")
        e1 = get_success_data(api.create_debit_adjustment(
            agent["id"], create_debit_adjustment_payload(50000, "advance E&O"),
            TEST_USERS["broker_admin_headers"]))
        assert e1["resulting_balance_cents"] == 50000
        e2 = get_success_data(api.create_debit_adjustment(
            agent["id"], create_debit_adjustment_payload(-20000, "goodwill write-off"),
            TEST_USERS["broker_admin_headers"]))
        assert e2["resulting_balance_cents"] == 30000
        resp = api.create_debit_adjustment(
            agent["id"], create_debit_adjustment_payload(0, "no-op"),
            TEST_USERS["broker_admin_headers"])
        validate_error(resp, ApiErrorId.ERR_DEBIT_ADJUSTMENT_INVALID, expected_status=422)
        entries = get_success_data(api.list_ledger_entries(
            TEST_USERS["auditor_headers"], params={"agent_id": agent["id"]}))
        assert entries[0]["entry_type"] == "MANUAL_DEBIT"
        assert entries[0]["resulting_balance_cents"] == 50000
        assert entries[1]["entry_type"] == "DEBIT_WRITE_OFF"
        assert entries[1]["resulting_balance_cents"] == 30000
        final = get_success_data(api.get_agent(agent["id"], TEST_USERS["auditor_headers"]))
        assert final["debit_balance_cents"] == 30000


class TestDealVoidReversesTrustReceipt:
    def test_void_posts_receipt_reversal_and_zeroes_received(self, api):
        """PRD §3.5: "Voiding is the corrector for a closing recorded in error:
        it moves a deal from CLOSED to VOIDED ... writing a trust
        RECEIPT_REVERSAL for the negated trust_received_cents and zeroing
        trust_received_cents."

        Design: Corner/endpoints/deal_void_reverses_trust_receipt
        """
        agent = setup_active_agent(name="Void Vera")
        deal = setup_closed_deal(agent["id"], address="99 Voidable Rd",
                                 gross_commission_cents=1000000, closing_date="2026-01-15")
        pre = get_success_data(api.get_trust_ledger(TEST_USERS["auditor_headers"]))
        assert pre["held_cents"] == 1000000
        voided = get_success_data(api.void_deal(deal["id"], TEST_USERS["transaction_coordinator_headers"]))
        assert voided["status"] == "VOIDED"
        assert voided["trust_received_cents"] == 0
        post = get_success_data(api.get_trust_ledger(TEST_USERS["auditor_headers"]))
        assert post["held_cents"] == 0
        assert post["released_cents"] == 0

    def test_trust_journal_shows_receipt_then_reversal(self, api):
        """PRD §3.8: trust transactions record "a `kind` of `RECEIPT` (written
        at closing for the full gross), `RECEIPT_REVERSAL` (written at void for
        the negated gross)".

        Design: Corner/endpoints/deal_void_reverses_trust_receipt
        """
        agent = setup_active_agent(name="Void Vera")
        deal = setup_closed_deal(agent["id"], gross_commission_cents=1000000, closing_date="2026-01-15")
        api.void_deal(deal["id"], TEST_USERS["transaction_coordinator_headers"])
        txns = get_success_data(api.list_trust_transactions(
            TEST_USERS["auditor_headers"], params={"deal_id": deal["id"]}))
        assert txns[0]["kind"] == "RECEIPT" and txns[0]["amount_cents"] == 1000000
        assert txns[1]["kind"] == "RECEIPT_REVERSAL" and txns[1]["amount_cents"] == -1000000


class TestSettleResponseImmediateConsistency:
    def test_settle_response_and_reads_agree_immediately(self, api):
        """PRD §3.6: settle "answers `201 Created` with the posted settlement"
        and "Settling then cascades, atomically: the window's
        `company_dollar_accrued_cents` rises by `company_dollar_cents` and its
        `royalty_accrued_cents` by `royalty_cents`".

        Design: Corner/consistency_model/settle_response_immediately_reflects_all_mutations
        """
        agent, plan, _e = setup_agent_with_debit(150000, agent_name="Consist Cora")
        deal = setup_closed_deal(agent["id"], address="110 Consistency Ct",
                                 gross_commission_cents=1000000, closing_date="2026-01-15")
        resp = api.settle_deal(deal["id"], TEST_USERS["transaction_coordinator_headers"])
        s = validate_success(resp, expected_status=201)
        assert s["agent_net_cents"] == 477000
        assert s["debit_recovery_cents"] == 150000
        after = get_success_data(api.get_agent(agent["id"], TEST_USERS["broker_admin_headers"]))
        assert after["debit_balance_cents"] == 0
        assert after["settled_deal_count"] == 1
        w0 = get_window_for_agent(agent["id"], 0)
        assert w0["company_dollar_accrued_cents"] == 282000
        assert w0["royalty_accrued_cents"] == 60000

    def test_settle_creates_legs_and_ledger_atomically(self, api):
        """PRD §3.6: "The same request also creates the settlement's disbursement
        legs" and "when debit_recovery_cents is positive, a DEBIT_RECOVERY entry
        posts after it" — all visible immediately after the 201.

        Design: Corner/consistency_model/settle_response_immediately_reflects_all_mutations
        """
        agent, plan, _e = setup_agent_with_debit(150000, agent_name="Consist Cora")
        deal = setup_closed_deal(agent["id"], gross_commission_cents=1000000, closing_date="2026-01-15")
        s = get_success_data(api.settle_deal(deal["id"], TEST_USERS["transaction_coordinator_headers"]))
        legs = get_settlement_legs(s["id"])
        assert len(legs) == 3
        by_type = {leg["payee_type"]: leg for leg in legs}
        assert by_type["ROYALTY"]["amount_cents"] == 60000
        assert by_type["COMPANY"]["amount_cents"] == 463000
        assert by_type["AGENT"]["amount_cents"] == 477000
        entries = get_success_data(api.list_ledger_entries(
            TEST_USERS["broker_admin_headers"],
            params={"agent_id": agent["id"], "entry_type": "DEBIT_RECOVERY"}))
        assert entries[0]["amount_cents"] == -150000
        assert entries[0]["resulting_balance_cents"] == 0
