"""Hired-judge contracts: tiered quote/final fees, auto-release, dispute cycle."""
from test_helpers import (
    TEST_USERS,
    accept_contract,
    assert_contract_invariants,
    create_contract_for_school,
    dispute_contract,
    fill_contract,
    get_contract,
    get_judge,
    get_school,
    make_coach_headers,
    pay_contract,
    resolve_dispute,
    setup_fee_divergence_scenario,
    setup_school_with_shortfall,
    validate_error,
    withdraw_entry,
)

DIRECTOR = TEST_USERS["director_headers"]


class TestHiredJudgeFeeVariants:
    def test_quote_counts_requested_contracts_final_excludes_them(self, api):
        """PRD §3.3: "At creation, `fee_quote_cents` is computed under the
        provisional-quote variant: consider every contract of the tournament in
        `REQUESTED`, `FILLED`, `CONFIRMED`, `DISPUTED`, or `PAID`, ordered by
        `created_at` ascending with ties broken by `rounds_requested` ascending,
        never by `id`."
        PRD §3.3: "The final fee is computed under the final-invoice variant —
        same tiered formula, but the candidate set excludes `REQUESTED`
        contracts."

        Design: Difficulty/dual_variant_calc/hired_judge_fee_quote_final_divergence
        """
        ws = setup_fee_divergence_scenario()
        c_a, c_b = ws["c_a"], ws["c_b"]
        school_b = ws["schools"]["b"]["id"]

        # Alpha's 4-round request stays REQUESTED; Beta fills and accepts.
        fill_contract(c_b["id"], "Hired Beta")
        accept_contract(c_b["id"], school_b)

        alpha_contract = get_contract(c_a["id"])
        assert alpha_contract["status"] == "REQUESTED"
        assert alpha_contract["fee_quote_cents"] == 20000, (
            "4 rounds x 5000 with zero preceding load")

        beta_contract = get_contract(c_b["id"])
        # Quote: preceding load 4 (Alpha's still-REQUESTED contract) -> 4 base +
        # 2 premium = 35000. Final: REQUESTED excluded -> 6 x 5000 = 30000.
        assert beta_contract["fee_quote_cents"] == 35000
        assert beta_contract["final_fee_cents"] == 30000
        assert beta_contract["fee_quote_cents"] != beta_contract["final_fee_cents"], (
            "the two variants diverge on identical tournament data")

    def test_fill_creates_hired_judge_with_contract_rounds(self, api):
        """PRD §3.3: "Filling creates a `HIRED` judge directly in `COMMITTED`
        status, with `commitment_rounds` equal to the contract's
        `rounds_requested` (which may exceed `prelim_round_count`; the commitment
        ceiling applies only to school-provided commits), with no school
        affiliation (`school_id` is null), and records it as the contract's
        `hired_judge_id`."

        Design: Difficulty/dual_variant_calc/hired_judge_fee_quote_final_divergence
        """
        ws = setup_fee_divergence_scenario()
        c_b = ws["c_b"]
        assert c_b["hired_judge_id"] is None, "unset until the contract is filled"

        filled = fill_contract(c_b["id"], "Hired Beta")
        assert filled["hired_judge_id"] is not None

        judge = get_judge(filled["hired_judge_id"])
        assert judge["judge_type"] == "HIRED"
        assert judge["status"] == "COMMITTED"
        assert judge["commitment_rounds"] == 6, (
            "hired judges receive rounds_requested even above prelim_round_count 4")
        assert judge["school_id"] is None


class TestEntryWithdrawAutoRelease:
    def _scenario(self, api):
        """Alpha with 4 confirmed entries (obligation 8), one committed 4-round
        judge (shortfall 4), and a REQUESTED 4-round contract (quote 20000)."""
        ws = setup_school_with_shortfall(
            name="Districts AR", entries=4, prelim_round_count=4,
            entry_fee_cents=2500, judge_rounds=[4])
        ws["c_a"] = create_contract_for_school(ws["schools"]["a"]["id"], 4)
        return ws

    def test_withdrawal_recomputes_obligation_and_invoice(self, api):
        """PRD §3.2: "First, the entry leaves the invoice status set, so the
        school's `confirmed_entry_count` and `judge_obligation_rounds` are
        recomputed and the school's `version` increments."
        PRD §3.2: "Third, the contract fee changes feed a fresh recomputation of
        the school's `invoice_balance_cents`, with another `version` increment."

        Design: Difficulty/transitive_cascade/entry_withdraw_triggers_hired_round_auto_release
        """
        ws = self._scenario(api)
        school_id = ws["schools"]["a"]["id"]
        for entry in ws["entries"]["a"][2:]:  # withdraw E-Three, E-Four
            withdraw_entry(entry["id"], school_id)

        school = get_school(school_id)
        assert school["confirmed_entry_count"] == 2
        assert school["judge_obligation_rounds"] == 4, "ceil(2/2) * 4"
        assert school["covered_judge_rounds"] == 4
        assert school["shortfall_rounds"] == 0
        assert school["obligation_status"] == "SATISFIED"
        assert school["invoice_balance_cents"] == 5000, (
            "2 remaining entries x 2500; the cancelled contract never invoiced")

    def test_surplus_requested_contract_drained_and_cancelled(self, api):
        """PRD §3.2: "the surplus is drained from the school's contracts in
        `REQUESTED` or `CONFIRMED` status, most recently created first, increasing
        each affected contract's `rounds_released` (never beyond its
        `rounds_requested`, so active rounds never fall below zero) and
        recomputing its fees; a `REQUESTED` contract drained to zero active rounds
        is automatically `CANCELLED`."

        Design: Difficulty/transitive_cascade/entry_withdraw_triggers_hired_round_auto_release
        """
        ws = self._scenario(api)
        school_id = ws["schools"]["a"]["id"]
        for entry in ws["entries"]["a"][2:]:
            withdraw_entry(entry["id"], school_id)

        contract = get_contract(ws["c_a"]["id"])
        assert contract["rounds_released"] == 4, "all 4 surplus rounds released"
        assert_contract_invariants(contract)
        assert contract["rounds_active"] == 0
        assert contract["status"] == "CANCELLED", (
            "a REQUESTED contract drained to zero active rounds is auto-cancelled")


class TestContractDisputeCycle:
    def _accepted_contract(self, api):
        """Alpha: 2 confirmed entries (2500 each) + a 4-round contract filled and
        accepted (final fee 20000). Invoice is 25000 throughout the cycle."""
        ws = setup_school_with_shortfall(
            name="DC", entries=2, prelim_round_count=4, entry_fee_cents=2500)
        school_id = ws["schools"]["a"]["id"]
        contract = create_contract_for_school(school_id, 4)
        fill_contract(contract["id"], "Hired Alpha")
        accept_contract(contract["id"], school_id)
        return ws, contract["id"], school_id

    def test_dispute_resolve_cycle_keeps_invoice(self, api):
        """PRD §3.3: "From `CONFIRMED` the coach may dispute the contract
        (`CONFIRMED` → `DISPUTED`), and the director may resolve the dispute
        (`DISPUTED` → `CONFIRMED`, a cycle); both actions increment the school's
        `version` and change no fees, and a `DISPUTED` contract continues to count
        toward both coverage and the invoice."

        Design: Corner/state_machines/contract_dispute_resolve_cycle
        """
        ws, contract_id, school_id = self._accepted_contract(api)
        assert get_school(school_id)["invoice_balance_cents"] == 25000

        disputed = dispute_contract(contract_id, school_id)
        assert disputed["status"] == "DISPUTED"
        assert get_school(school_id)["invoice_balance_cents"] == 25000, (
            "a DISPUTED contract continues to count toward the invoice")

        resolved = resolve_dispute(contract_id)
        assert resolved["status"] == "CONFIRMED"
        assert get_school(school_id)["invoice_balance_cents"] == 25000

    def test_paid_contract_cannot_be_disputed(self, api):
        """PRD §3.3: "Paying a `CONFIRMED` contract moves it to `PAID` and
        subtracts its `final_fee_cents` from the school's `invoice_balance_cents`".
        PRD §3.3: "From `CONFIRMED` the coach may dispute the contract (`CONFIRMED`
        → `DISPUTED`)" — no path out of `PAID` exists, so a dispute attempt hits
        the contract state error.
        PRD §2.7: "the per-entity state errors `ERR_SCHOOL_INVALID_STATE`,
        `ERR_ENTRY_INVALID_STATE`, `ERR_JUDGE_INVALID_STATE`,
        `ERR_ROUND_INVALID_STATE`, `ERR_PAIRING_INVALID_STATE`,
        `ERR_BALLOT_INVALID_STATE`, `ERR_CONTRACT_INVALID_STATE`, and
        `ERR_ORDER_INVALID_STATE`".

        Design: Corner/state_machines/paid_contract_dispute_rejected
        """
        ws, contract_id, school_id = self._accepted_contract(api)
        pay_contract(contract_id, school_id)
        assert get_school(school_id)["invoice_balance_cents"] == 5000, (
            "25000 pre-discount minus the 20000 payment; entry fees remain")

        resp = api.dispute_contract(contract_id, make_coach_headers(school_id))
        validate_error(resp, "ERR_CONTRACT_INVALID_STATE")

        contract = get_contract(contract_id)
        assert contract["status"] == "PAID", "PAID is terminal"
        assert get_school(school_id)["invoice_balance_cents"] == 5000
