"""Transitive cascades: borrower default, security halt, settlement unwind.

Covers difficulty instances borrower_default_four_link_cascade,
security_halt_three_link_cascade, plus corner instances
settlement_cascade_releases_everything and
no_indemnity_credit_when_owner_not_opted_in.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_borrow_request,
    create_loan_proposal,
    create_tranche,
    get_borrow_request,
    get_loan,
    get_margin_call,
    get_pledge,
    get_position,
    get_tranche,
    list_ledger_entries,
    make_borrower_rep_headers,
    post_cash_pledge,
    return_shares,
    run_mtm,
    set_clock,
    setup_booked_loan,
    setup_cash_loan_with_pledge,
    setup_desk,
    validate_error,
    validate_success,
)

TRADER = TEST_USERS["desk_trader_headers"]
RISK = TEST_USERS["risk_officer_headers"]
OPS = TEST_USERS["ops_settler_headers"]
ADMIN = TEST_USERS["desk_admin_headers"]


class TestBorrowerDefaultCascade:
    def _default_setup(self, api, indemnified):
        ctx = setup_cash_loan_with_pledge(
            pledge_amount_cents=1_020_000, security_symbol="DFT1",
            loan_quantity=1000, rate_bps=0, indemnification_opt_in=indemnified)
        tranche = create_tranche(ctx["loan"], principal_cents=600_000,
                                 stated_yield_bps=360)
        validate_success(api.mark_reinvestment(
            tranche["id"], {"current_nav_cents": 610000}, OPS))
        # Loan market value rises above posted collateral.
        validate_success(api.mark_security_price(
            ctx["security"]["id"], {"price_cents": 1100}, ADMIN))
        request = create_borrow_request(
            ctx["borrower"], ctx["security"], quantity=500, max_rate_bps=40)
        ctx["tranche"] = tranche
        ctx["request"] = request
        return ctx

    def test_borrower_default_four_link_cascade(self, api):
        """PRD §3.8: "Declaring default, from `ACTIVE` or `SUSPENDED`, moves
        the borrower to `DEFAULTED` and fires a four-link cascade. First,
        every loan of the borrower in `BOOKED` or `RECALLED` moves to
        `DEFAULTED`. Second, per defaulted loan, every `ACTIVE` collateral
        pledge moves to `SEIZED` and a `COLLATERAL_SEIZURE` ledger entry
        posts at the pledge's `marked_value_cents` as income on the owner
        side. Third, every `INVESTED` reinvestment tranche is unwound at its
        `current_nav_cents` with its `REINVEST_INCOME_FINAL` entry. Fourth,
        for each defaulted loan whose owner opted into indemnification, an
        `INDEMNITY_CREDIT` entry posts to that owner per the shortfall
        computation below."
        PRD §3.8: "In both paths the position's `quantity_on_loan` falls by
        the defaulted loan's outstanding quantity — the inventory returns to
        the owner's pool"
        PRD §3.8: "A borrower default also cancels the borrower's `SUBMITTED`
        and `MATCHED` borrow requests"
        PRD §3.8: "The shortfall is the difference, floored at zero"

        Design: Difficulty/transitive_cascade/borrower_default_four_link_cascade
        """
        ctx = self._default_setup(api, indemnified=True)
        loan_id = ctx["loan"]["id"]

        defaulted = validate_success(
            api.default_borrower(ctx["borrower"]["id"], RISK))
        assert defaulted["status"] == "DEFAULTED"           # link 1

        loan = get_loan(loan_id, RISK)
        assert loan["status"] == "DEFAULTED"                # link 2
        assert loan["market_value_cents"] == 1100000

        pledge = get_pledge(ctx["pledge"]["id"], RISK)      # link 3
        assert pledge["status"] == "SEIZED"
        seizures = list_ledger_entries(RISK, loan_id=loan_id,
                                       entry_type="COLLATERAL_SEIZURE")
        assert len(seizures) == 1
        assert seizures[0]["amount_cents"] == 1020000

        tranche = get_tranche(ctx["tranche"]["id"], RISK)   # link 3b
        assert tranche["status"] == "UNWOUND"
        assert tranche["realized_income_cents"] == 10000  # 610,000 - 600,000

        credits = list_ledger_entries(RISK, loan_id=loan_id,
                                      entry_type="INDEMNITY_CREDIT")
        # link 4: max(0, 1,100,000 owed - 1,020,000 seized) = 80,000
        assert len(credits) == 1
        assert credits[0]["amount_cents"] == 80000

        assert get_borrow_request(ctx["request"]["id"],
                                  RISK)["status"] == "CANCELLED"
        assert get_position(ctx["position"]["id"],
                            RISK)["quantity_on_loan"] == 0

    def test_no_indemnity_credit_when_owner_not_opted_in(self, api):
        """PRD §3.8: "When the owner's `indemnification_opt_in` is set, an
        `INDEMNITY_CREDIT` entry for the shortfall posts to the owner;
        otherwise no entry posts and the owner bears the shortfall
        themselves."

        Design: Corner/calculations/no_indemnity_credit_when_owner_not_opted_in
        """
        ctx = self._default_setup(api, indemnified=False)
        loan_id = ctx["loan"]["id"]
        validate_success(api.default_borrower(ctx["borrower"]["id"], RISK))
        credits = list_ledger_entries(RISK, loan_id=loan_id,
                                      entry_type="INDEMNITY_CREDIT")
        assert credits == []
        seizures = list_ledger_entries(RISK, loan_id=loan_id,
                                       entry_type="COLLATERAL_SEIZURE")
        assert len(seizures) == 1
        assert seizures[0]["amount_cents"] == 1020000

    def test_recall_open_on_defaulted_loan_is_cancelled(self, api):
        """PRD §3.8: "The same four links fire when a single loan defaults
        through a margin-call declaration rather than a borrower-wide event.
        In both paths the position's `quantity_on_loan` falls by the
        defaulted loan's outstanding quantity — the inventory returns to the
        owner's pool — and any recall still open on a defaulted loan
        (`ISSUED`, `EXTENDED`, or `FAILED`) is cancelled."

        Design: Difficulty/transitive_cascade/borrower_default_four_link_cascade
        """
        from test_helpers import issue_recall, get_recall
        ctx = setup_cash_loan_with_pledge(
            pledge_amount_cents=1_020_000, security_symbol="DFT2",
            loan_quantity=1000, rate_bps=0, indemnification_opt_in=True)
        recall = issue_recall(ctx["loan"], ctx["owner"], 1000,
                              deadline_date="2026-08-10")
        validate_success(api.default_borrower(ctx["borrower"]["id"], RISK))
        assert get_recall(recall["id"], RISK)["status"] == "CANCELLED"
        loan = get_loan(ctx["loan"]["id"], RISK)
        assert loan["status"] == "DEFAULTED"
        assert get_pledge(ctx["pledge"]["id"], RISK)["status"] == "SEIZED"
        assert get_position(ctx["position"]["id"],
                            RISK)["quantity_on_loan"] == 0


class TestSecurityHaltCascade:
    def _halt_setup(self, api):
        security, owner, borrower, position = setup_desk(
            security_symbol="HLT1", quantity_total=10000)
        r1 = create_borrow_request(borrower, security, quantity=3000)
        r2 = create_borrow_request(borrower, security, quantity=3000)
        lp2 = validate_success(api.match_borrow_request(
            r2["id"], {"position_id": position["id"]}, TRADER),
            expected_status=201)
        lp3 = create_loan_proposal(owner, borrower, security, position,
                                   quantity=2000, rate_bps=28)
        return security, owner, borrower, position, r1, r2, lp2, lp3

    def test_security_halt_three_link_cascade(self, api):
        """PRD §3.1: "When a `DeskAdmin` halts a security, its status moves
        from `LENDABLE` to `HALTED` and a three-link cascade fires at once:
        every `SUBMITTED` or `MATCHED` borrow request for that security is
        cancelled; every loan proposal in `PROPOSED` or `COUNTERED` for that
        security is cancelled — including desk-initiated proposals not tied
        to any borrow request; and each cancelled proposal releases its
        reservation, decrementing `quantity_reserved` on the source
        position."

        Design: Difficulty/transitive_cascade/security_halt_three_link_cascade
        """
        security, _, _, position, r1, r2, lp2, lp3 = self._halt_setup(api)
        mid = get_position(position["id"], ADMIN)
        assert mid["quantity_reserved"] == 5000

        halted = validate_success(api.halt_security(security["id"], ADMIN))
        assert halted["status"] == "HALTED"

        assert get_borrow_request(r1["id"], ADMIN)["status"] == "CANCELLED"
        assert get_borrow_request(r2["id"], ADMIN)["status"] == "CANCELLED"
        assert get_loan(lp2["id"], ADMIN)["status"] == "CANCELLED"
        assert get_loan(lp3["id"], ADMIN)["status"] == "CANCELLED"

        pos = get_position(position["id"], ADMIN)
        assert pos["quantity_reserved"] == 0
        assert pos["quantity_available"] == 10000

    def test_halt_leaves_booked_loans_untouched(self, api):
        """PRD §3.1: "halted securities are never purged, and their existing
        booked loans are unaffected by the halt itself."

        Design: Difficulty/transitive_cascade/security_halt_three_link_cascade
        """
        ctx = setup_booked_loan(security_symbol="HLT2", loan_quantity=1000)
        validate_success(api.halt_security(ctx["security"]["id"], ADMIN))
        loan = get_loan(ctx["loan"]["id"], ADMIN)
        assert loan["status"] == "BOOKED"
        pos = get_position(ctx["position"]["id"], ADMIN)
        assert pos["quantity_on_loan"] == 1000


class TestSettlementCascade:
    def test_full_return_releases_everything(self, api):
        """PRD §3.4: "A return that brings `outstanding_quantity` to zero
        settles the loan — `BOOKED` or `RECALLED` alike, the loan moves to
        `SETTLED` — and fires the settlement cascade: the position's
        `quantity_on_loan` is decremented; every `ACTIVE` collateral pledge
        moves to `RELEASED`, returning cash pledges and driving
        `cash_uninvested_cents` to zero; every `INVESTED` reinvestment
        tranche is unwound at its `current_nav_cents` with a final income
        entry per tranche; and any margin calls still `OPEN` or `ESCALATED`
        are cured by the system as part of settlement."

        Design: Corner/complexity_layers/settlement_cascade_releases_everything
        """
        ctx = setup_cash_loan_with_pledge(
            pledge_amount_cents=1_020_000, security_symbol="EP2",
            loan_quantity=1000, rate_bps=0)
        tranche = create_tranche(ctx["loan"], principal_cents=500_000,
                                 instrument_type="REPO", stated_yield_bps=360)
        validate_success(api.mark_reinvestment(
            tranche["id"], {"current_nav_cents": 505000}, OPS))
        validate_success(api.mark_security_price(
            ctx["security"]["id"], {"price_cents": 1100}, ADMIN))
        run_mtm()  # issues an OPEN margin call (deficit 102,000)
        call = validate_success(api.list_margin_calls(
            OPS, params={"loan_id": ctx["loan"]["id"]}))[0]
        assert get_loan(ctx["loan"]["id"], OPS)["margin_status"] == "CALL_OPEN"

        settled = return_shares(ctx["loan"], ctx["borrower"], 1000)
        assert settled["status"] == "SETTLED"
        assert settled["outstanding_quantity"] == 0
        assert get_margin_call(call["id"])["status"] == "CURED"
        assert get_pledge(ctx["pledge"]["id"], OPS)["status"] == "RELEASED"
        tr = get_tranche(tranche["id"], OPS)
        assert tr["status"] == "UNWOUND"
        assert tr["realized_income_cents"] == 5000
        loan = get_loan(ctx["loan"]["id"], OPS)
        assert loan["margin_status"] == "CURRENT"
        assert get_position(ctx["position"]["id"],
                            OPS)["quantity_on_loan"] == 0

    def test_return_response_reflects_final_state_immediately(self, api):
        """PRD §2.6: "All side effects of a mutation are applied atomically
        within the same request; any read afterwards observes the complete
        cascade."
        PRD §3.4: "Each return reduces `outstanding_quantity` and increments
        the loan's `version`"

        Design: Corner/consistency_model/return_response_reflects_final_state_immediately
        """
        ctx = setup_booked_loan(security_symbol="IC1", loan_quantity=500)
        settled = validate_success(api.return_loan(
            ctx["loan"]["id"], {"quantity": 500},
            make_borrower_rep_headers(ctx["borrower"]["id"])))
        assert settled["status"] == "SETTLED"
        assert settled["outstanding_quantity"] == 0
        # create v1, accept v2, return v3
        assert settled["version"] == 3
