"""Difficulty-queue tests for compensating-reversal invariants on settlement void:
account-cash conservation and debt-principal conservation."""
import pytest
from test_helpers import (
    TEST_USERS, make_client_headers, get_success_data,
    create_settlement_payload,
    set_clock, create_client, create_program, create_debt,
    create_offer, accept_offer, fund_settlement, complete_settlement,
    get_account_for_program,
)

ADMIN = TEST_USERS["program_admin_headers"]
AGENT = TEST_USERS["negotiation_agent_headers"]


def _fund6(api, program_id, client_id):
    for m in range(1, 7):
        api.create_deposit(
            {"program_id": program_id, "scheduled_for": f"2026-{m:02d}-10T00:00:00Z",
             "amount": 600}, make_client_headers(client_id))


class TestVoidCashConservation:

    def test_account_balance_conserved_after_void(self, api):
        """PRD §2.8: "every compensating reversal must leave it conserved: voiding a settlement returns the account to its exact pre-funding balance."
        PRD §3.8: "The `funded_amount` is credited back to the dedicated account, and the linked `SettlementFee` — still `OUTSTANDING` — moves to `WAIVED` so that no fee is ever debited for this aborted settlement."

        Design: Difficulty/compensating_invariant/account_cash_conserved_on_settlement_void
        """
        set_clock("2026-06-01T00:00:00Z")
        client = create_client(full_name="Vo Id", email="void@x.com", state_code="CA")
        program = create_program(client["id"], monthly_deposit_amount=600, reserve_floor=0)
        debt = create_debt(program["id"], creditor_name="Cred", account_number="VD-1",
                          original_balance=5000)
        activated = get_success_data(api.activate_program(program["id"], ADMIN))
        v1 = activated["version"]
        _fund6(api, program["id"], client["id"])
        offer = create_offer(program["id"], debt["id"], offer_pct=0.40,
                            due_date="2026-12-01T00:00:00Z")
        accept_offer(offer["id"], v1)
        settle = fund_settlement(program["id"], offer["id"])

        bal_before = get_account_for_program(program["id"])["balance"]
        # 3600 - 2000 funded; fee not yet paid
        assert bal_before == pytest.approx(1600.00, abs=0.01)
        get_success_data(api.void_settlement(settle["id"], ADMIN))
        acct_after = get_account_for_program(program["id"])
        # funded 2000 credited back, fee 500 WAIVED -> back to 3600
        assert acct_after["balance"] == pytest.approx(3600.00, abs=0.01)
        assert acct_after["balance"] == pytest.approx(acct_after["lifetime_deposited"], abs=0.01)

    def test_void_waives_fee_no_debit(self, api):
        """PRD §2.8: "voiding a settlement returns the account to its exact pre-funding balance."
        PRD §3.8: "the linked `SettlementFee` — still `OUTSTANDING` — moves to `WAIVED` so that no fee is ever debited for this aborted settlement."

        Design: Difficulty/compensating_invariant/account_cash_conserved_on_settlement_void
        """
        set_clock("2026-06-01T00:00:00Z")
        client = create_client(full_name="Void2", email="void2@x.com", state_code="CA")
        program = create_program(client["id"], monthly_deposit_amount=600, reserve_floor=0)
        debt = create_debt(program["id"], creditor_name="Cred", account_number="VD-2",
                          original_balance=5000)
        activated = get_success_data(api.activate_program(program["id"], ADMIN))
        v1 = activated["version"]
        _fund6(api, program["id"], client["id"])
        offer = create_offer(program["id"], debt["id"], offer_pct=0.40,
                            due_date="2026-12-01T00:00:00Z")
        accept_offer(offer["id"], v1)
        settle = fund_settlement(program["id"], offer["id"])
        get_success_data(api.void_settlement(settle["id"], ADMIN))
        acct_after = get_account_for_program(program["id"])
        # no fee debit ever applied; balance equals lifetime deposited (3600)
        assert acct_after["balance"] == pytest.approx(3600.00, abs=0.01)

    def test_debt_principal_conserved_after_void(self, api):
        """PRD §3.8: "The parent debt reverts to `IN_NEGOTIATION`, with its `current_balance` restored to `original_balance` and its `settled_amount`, `forgiven_amount`, and `settled_offer_id` reset to their pre-settlement defaults."

        Design: Difficulty/compensating_invariant/debt_principal_conserved_on_settlement_void
        """
        set_clock("2026-06-01T00:00:00Z")
        client = create_client(full_name="Pri Ncipal", email="prin@x.com", state_code="CA")
        program = create_program(client["id"], monthly_deposit_amount=600, reserve_floor=0)
        debt = create_debt(program["id"], creditor_name="Cred", account_number="PR-1",
                          original_balance=5000)
        activated = get_success_data(api.activate_program(program["id"], ADMIN))
        v1 = activated["version"]
        _fund6(api, program["id"], client["id"])
        offer = create_offer(program["id"], debt["id"], offer_pct=0.40,
                            due_date="2026-12-01T00:00:00Z")
        accept_offer(offer["id"], v1)
        settle = fund_settlement(program["id"], offer["id"])
        # PRD §3.8: a settlement may only be voided while it is FUNDED. Funding alone
        # does not settle the debt (settlement of principal happens at completion,
        # §3.7), so the debt is still IN_NEGOTIATION here with its full principal intact.

        get_success_data(api.void_settlement(settle["id"], ADMIN))
        reverted = get_success_data(api.get_debt(debt["id"], ADMIN))
        assert reverted["current_balance"] == pytest.approx(5000.00, abs=0.01)
        assert reverted["settled_amount"] == pytest.approx(0.00, abs=0.01)
        assert reverted["forgiven_amount"] == pytest.approx(0.00, abs=0.01)
        assert reverted["status"] == "IN_NEGOTIATION"

    def test_completed_debt_principal_decomposition_before_void(self, api):
        """PRD §3.7: "The parent debt becomes `SETTLED`: its `settled_amount` is set to the settlement's `funded_amount`, its `forgiven_amount` becomes `original_balance` minus `funded_amount`, its `current_balance` falls to zero, and its `settled_offer_id` is set to the originating offer."

        Design: Difficulty/compensating_invariant/debt_principal_conserved_on_settlement_void
        """
        set_clock("2026-06-01T00:00:00Z")
        client = create_client(full_name="Prin2", email="prin2@x.com", state_code="CA")
        program = create_program(client["id"], monthly_deposit_amount=600, reserve_floor=0)
        debt = create_debt(program["id"], creditor_name="Cred", account_number="PR-2",
                          original_balance=5000)
        activated = get_success_data(api.activate_program(program["id"], ADMIN))
        v1 = activated["version"]
        _fund6(api, program["id"], client["id"])
        offer = create_offer(program["id"], debt["id"], offer_pct=0.40,
                            due_date="2026-12-01T00:00:00Z")
        accept_offer(offer["id"], v1)
        settle = fund_settlement(program["id"], offer["id"])
        complete_settlement(settle["id"])
        settled = get_success_data(api.get_debt(debt["id"], ADMIN))
        # 0 + 2000 + 3000 == 5000 original
        assert (settled["current_balance"] + settled["settled_amount"]
                + settled["forgiven_amount"]) == pytest.approx(5000.00, abs=0.01)
