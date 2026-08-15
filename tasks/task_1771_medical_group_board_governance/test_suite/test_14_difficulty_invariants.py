"""Difficulty queue: compensating invariants — share conservation and capital ledger."""
from test_helpers import (
    adopt_buyout_approval,
    adopted_and_billed_call,
    adopted_distribution,
    allocation_for,
    appraise_valuation,
    assert_share_conservation,
    create_buy_in_offer,
    create_physician,
    create_policy,
    create_shareholder,
    finalize_exit,
    get_physician,
    get_policy,
    initiate_exit,
    list_physicians,
    list_physician_assessments,
    pay_allocation,
    pay_assessment,
    pay_installment,
    respond_offer,
    void_distribution,
    get_distribution,
)


def _treasury():
    return get_policy()["treasury_shares"]


class TestSharesConservedAcrossExitAndBuyin:
    def test_exit_finalize_returns_shares_to_treasury(self, api):
        """PRD §3.1: "Treasury shares follow the companion rule:
        `total_shares_authorized` minus the sum of `shares_held` over all physicians
        (an `EXITED` physician holds zero, so the two sums coincide in practice)."
        PRD §3.6: "First, the physician moves from `EXITING` to `EXITED`,
        `shares_held` goes to 0, and the returned shares flow back to
        `treasury_shares`."
        X 1000 + Y 8000 outstanding -> treasury 991000; exit returns 1000 -> 992000.

        Design: Difficulty/compensating_invariant/shares_conserved_across_exit_and_buyin
        """
        create_policy(total_shares_authorized=1000000, board_quorum_count=1)
        x = create_shareholder("Dr X", 1000, "2011-01-01T00:00:00Z")
        y = create_shareholder("Dr Y", 8000, "2012-01-01T00:00:00Z")
        assert _treasury() == 991000

        valuation = initiate_exit(x["id"], "VOLUNTARY")
        appraised = appraise_valuation(valuation, 90000000)
        motion = adopt_buyout_approval(y, appraised["id"])
        finalize_exit(appraised["id"], motion["id"])

        assert _treasury() == 992000, (
            f"991000 + 1000 returned shares, got {_treasury()}"
        )
        assert get_physician(x["id"])["shares_held"] == 0
        physicians, _ = list_physicians()
        assert_share_conservation(get_policy(), physicians)

    def test_buyin_completion_reissues_shares_from_treasury(self, api):
        """PRD §3.2: "When the final installment lands — `paid_installment_count`
        reaching `installment_count` — the offer completes, and the physician's tier
        advances: to `PARTNER_TRACK` with no shares issued for a partner-track offer,
        or to `SHAREHOLDER` for a shareholder offer, in which case the treasury must
        hold at least `share_grant` shares (`ERR_INSUFFICIENT_TREASURY_SHARES`
        otherwise), the physician's `shares_held` increases by `share_grant`, and
        `treasury_shares` decreases by the same amount."
        PRD §3.1: "`tenure_years` is the number of full 365.25-day years elapsed
        between `hire_date` and the logical clock."
        Z hired 2024-08-01, offered at the 2026-08-01 default clock: 730 days contain
        one full 365.25-day year (two would need 730.5), so tenure 1 -> discount 0.02
        -> round(25000000 * 0.98 * 11/12) = 22458333; completion returns treasury from
        992000 back to 991000.

        Design: Difficulty/compensating_invariant/shares_conserved_across_exit_and_buyin
        """
        create_policy(total_shares_authorized=1000000, board_quorum_count=1)
        x = create_shareholder("Dr X", 1000, "2011-01-01T00:00:00Z")
        y = create_shareholder("Dr Y", 8000, "2012-01-01T00:00:00Z")
        z = create_physician(full_name="Dr Z", hire_date="2024-08-01T00:00:00Z")
        valuation = initiate_exit(x["id"], "VOLUNTARY")
        appraised = appraise_valuation(valuation, 90000000)
        motion = adopt_buyout_approval(y, appraised["id"])
        finalize_exit(appraised["id"], motion["id"])
        assert _treasury() == 992000

        offer = create_buy_in_offer(
            z["id"], target_tier="SHAREHOLDER", share_grant=1000, installment_count=1
        )
        assert offer["final_amount_cents"] == 22458333, (
            f"tenure 1 (730 days < 2 full 365.25-day years) -> "
            f"round(25000000*0.98*11/12) = 22458333, got {offer['final_amount_cents']}"
        )
        respond_offer(offer["id"], z, "ACCEPT")
        completed = pay_installment(offer["id"], offer["final_amount_cents"])
        assert completed["status"] == "COMPLETED"

        z_after = get_physician(z["id"])
        assert z_after["partnership_status"] == "SHAREHOLDER"
        assert z_after["shares_held"] == 1000
        assert _treasury() == 991000, "compensating leg: 992000 - 1000 = 991000"
        physicians, _ = list_physicians()
        assert_share_conservation(get_policy(), physicians)


class TestCapitalLedgerConservedAcrossPayAndClawback:
    def _setup_ledger(self):
        """A/B/C 1000/1000/500 shares; call 5000000 paid in full by all; PRO_RATA
        distribution 10000001 adopted; only A's allocation disbursed."""
        create_policy(total_shares_authorized=1000000, board_quorum_count=1)
        a = create_shareholder("Dr A", 1000, "2015-01-01T00:00:00Z")
        b = create_shareholder("Dr B", 1000, "2016-01-01T00:00:00Z")
        c = create_shareholder("Dr C", 500, "2025-01-01T00:00:00Z")
        _m1, _call, _assessments = adopted_and_billed_call(
            a, 5000000, purpose="Equipment"
        )
        for physician in (a, b, c):
            asmts, _ = list_physician_assessments(physician["id"])
            pay_assessment(asmts[0]["id"], asmts[0]["total_due_cents"])
        _m2, distribution = adopted_distribution(a, 10000001, method="PRO_RATA", voters=[b])
        return a, b, c, distribution

    def test_allocation_pay_drives_capital_account_negative(self, api):
        """PRD §3.1: "`capital_account_balance_cents` is a ledger that increases with
        assessment payments, decreases with paid distribution allocations, increases
        with clawback compensation, and is permitted to go negative."
        A: 2000000 assessment paid, then 4000001 allocation disbursed -> -2000001.
        Ledger identity: -2000001 + 2000000 + 1000000 = 999999 == 5000000 - 4000001.

        Design: Difficulty/compensating_invariant/capital_ledger_conserved_across_pay_and_clawback
        """
        a, b, c, distribution = self._setup_ledger()
        pay_allocation(distribution["id"], a["id"])

        assert get_physician(a["id"])["capital_account_balance_cents"] == -2000001
        assert get_physician(b["id"])["capital_account_balance_cents"] == 2000000
        assert get_physician(c["id"])["capital_account_balance_cents"] == 1000000
        total = sum(
            get_physician(p["id"])["capital_account_balance_cents"] for p in (a, b, c)
        )
        assert total == 999999, (
            f"ledger identity: 5000000 assessed - 4000001 paid out = 999999, got {total}"
        )
        refreshed = get_distribution(distribution["id"])
        assert allocation_for(refreshed, a["id"])["status"] == "PAID"

    def test_void_restores_every_account_exactly(self, api):
        """PRD §3.5: "Voiding works from either `APPROVED` or `PAID`: every `PENDING`
        allocation becomes `CANCELLED`, every `PAID` allocation becomes `CLAWED_BACK`
        with the `allocated_cents` added back to the physician's capital account as
        compensation, and the distribution becomes `VOIDED`."
        After the void every account returns to its post-call balance exactly and the
        ledger identity holds: 5000000 == 5000000 - 0.

        Design: Difficulty/compensating_invariant/capital_ledger_conserved_across_pay_and_clawback
        """
        a, b, c, distribution = self._setup_ledger()
        pay_allocation(distribution["id"], a["id"])
        assert get_physician(a["id"])["capital_account_balance_cents"] == -2000001

        voided = void_distribution(distribution["id"])
        assert voided["status"] == "VOIDED"
        assert allocation_for(voided, a["id"])["status"] == "CLAWED_BACK"
        assert allocation_for(voided, b["id"])["status"] == "CANCELLED"
        assert allocation_for(voided, c["id"])["status"] == "CANCELLED"

        assert get_physician(a["id"])["capital_account_balance_cents"] == 2000000
        assert get_physician(b["id"])["capital_account_balance_cents"] == 2000000
        assert get_physician(c["id"])["capital_account_balance_cents"] == 1000000
        total = sum(
            get_physician(p["id"])["capital_account_balance_cents"] for p in (a, b, c)
        )
        assert total == 5000000, (
            f"post-void identity: assessments 5000000 - PAID allocations 0, got {total}"
        )
