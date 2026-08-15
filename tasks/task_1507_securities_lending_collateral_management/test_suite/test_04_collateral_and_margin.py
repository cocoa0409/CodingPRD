"""Collateral valuation, margin calls, release/substitution guards.

Covers difficulty instances posted_collateral_per_pledge_round_then_sum,
required_margin_collateral_type_branch,
margin_deficit_zero_no_call_one_cent_call, and corner instances on release,
substitution, pledge-type mismatch, price-update recompute, and the margin
call lifecycle.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_and_book_loan,
    create_security,
    get_loan,
    get_margin_call,
    get_pledge,
    make_borrower_rep_headers,
    post_cash_pledge,
    post_security_pledge,
    run_mtm,
    set_clock,
    setup_booked_loan,
    setup_cash_loan_with_pledge,
    setup_desk,
    validate_error,
    validate_success,
    create_tranche,
)

TRADER = TEST_USERS["desk_trader_headers"]
OPS = TEST_USERS["ops_settler_headers"]
ADMIN = TEST_USERS["desk_admin_headers"]


class TestRequiredMarginBranch:
    def test_cash_vs_securities_margin_branch_spread(self, api):
        """PRD §2.11: "A loan collateralized by **cash** must hold posted
        collateral of at least 102 percent of market value — a margin of
        10200 basis points; a loan collateralized by **securities** must hold
        at least 105 percent — 10500 basis points. Formally,
        `required_collateral_cents` is the loan's `outstanding_quantity`
        multiplied by the security's current `price_cents`, multiplied by
        the applicable margin in basis points and divided by 10000, rounded
        half-up to whole cents at that final multiplication only."

        Design: Difficulty/combinatorial_formula/required_margin_collateral_type_branch
        """
        security, owner, borrower, position = setup_desk(
            security_symbol="MRG1", quantity_total=100000)
        loan_cash = create_and_book_loan(
            owner, borrower, security, position, quantity=1000,
            collateral_type="CASH", rate_bps=100)
        loan_sec = create_and_book_loan(
            owner, borrower, security, position, quantity=1000,
            collateral_type="SECURITIES", rate_bps=25)
        cash = get_loan(loan_cash["id"])
        sec = get_loan(loan_sec["id"])
        # 1000 x 1000 x 10200/10000 = 1,020,000 ; x 10500/10000 = 1,050,000
        assert cash["required_collateral_cents"] == 1020000
        assert sec["required_collateral_cents"] == 1050000
        assert (sec["required_collateral_cents"]
                - cash["required_collateral_cents"]) == 30000

    def test_required_collateral_uses_current_mark(self, api):
        """PRD §2.11: "`required_collateral_cents` is the loan's
        `outstanding_quantity` multiplied by the security's current
        `price_cents`, multiplied by the applicable margin in basis points
        and divided by 10000"

        Design: Difficulty/combinatorial_formula/required_margin_collateral_type_branch
        """
        ctx = setup_booked_loan(security_symbol="MRG2", loan_quantity=1000,
                                collateral_type="CASH", rate_bps=0)
        before = get_loan(ctx["loan"]["id"])
        assert before["required_collateral_cents"] == 1020000
        validate_success(api.mark_security_price(
            ctx["security"]["id"], {"price_cents": 1500}, ADMIN))
        after = get_loan(ctx["loan"]["id"])
        # 1000 x 1500 x 10200/10000 = 1,530,000
        assert after["required_collateral_cents"] == 1530000


class TestPerPledgeRounding:
    def test_posted_collateral_rounds_per_pledge_then_sums(self, api):
        """PRD §2.11: "Posted collateral is valued pledge by pledge and then
        summed, and the rounding order is pinned: each pledge is rounded to
        whole cents first, and only then are the pledge values added."
        PRD §2.11: "A securities pledge is worth its `quantity` multiplied by
        the pledged security's current `price_cents`, multiplied by 10000
        minus the pledged security's `haircut_bps` and divided by 10000,
        rounded half-up to whole cents per pledge."

        Two 1-share pledges of an EQUITY @ 22225c (haircut 1000):
        round_half_up(1 x 22225 x 9000/10000) = round_half_up(20002.5) =
        20003 each; posted = 40006. Sum-then-round would give 40005.

        Design: Difficulty/combinatorial_formula/posted_collateral_per_pledge_round_then_sum
        """
        security, owner, borrower, position = setup_desk(
            security_symbol="RND1", quantity_total=100000)
        csec = create_security(symbol="RND2", asset_class="EQUITY",
                               price_cents=22225)
        loan = create_and_book_loan(owner, borrower, security, position,
                                    quantity=1000,
                                    collateral_type="SECURITIES", rate_bps=25)
        p1 = post_security_pledge(loan, borrower, csec["id"], 1)
        p2 = post_security_pledge(loan, borrower, csec["id"], 1)
        assert p1["marked_value_cents"] == 20003
        assert p2["marked_value_cents"] == 20003
        assert get_loan(loan["id"])["posted_collateral_cents"] == 40006

    def test_posted_collateral_excludes_released_pledges(self, api):
        """PRD §2.11: "Only pledges in `ACTIVE` status count toward
        `posted_collateral_cents`; `RELEASED`, `SUBSTITUTED`, and `SEIZED`
        pledges are excluded."

        Design: Difficulty/combinatorial_formula/posted_collateral_per_pledge_round_then_sum
        """
        ctx = setup_cash_loan_with_pledge(pledge_amount_cents=1_020_000,
                                          security_symbol="RND3")
        loan, borrower = ctx["loan"], ctx["borrower"]
        extra = post_cash_pledge(loan, borrower, 50_000)
        assert get_loan(loan["id"])["posted_collateral_cents"] == 1070000
        validate_success(api.release_pledge(extra["id"], TRADER))
        after = get_loan(loan["id"])
        assert after["posted_collateral_cents"] == 1020000


class TestMarginDeficitBoundary:
    def _two_loans(self, api):
        security, owner, borrower, position = setup_desk(
            security_symbol="MGN1", quantity_total=100000)
        l1 = create_and_book_loan(owner, borrower, security, position,
                                  quantity=1000, collateral_type="CASH",
                                  rate_bps=0)
        post_cash_pledge(l1, borrower, 1_020_000)  # exactly required
        l2 = create_and_book_loan(owner, borrower, security, position,
                                  quantity=1000, collateral_type="CASH",
                                  rate_bps=0)
        post_cash_pledge(l2, borrower, 1_019_999)  # one cent short
        return l1, l2

    def test_zero_deficit_no_call_one_cent_deficit_issues_call(self, api):
        """PRD §2.11: "A loan's margin deficit is its
        `required_collateral_cents` minus its `posted_collateral_cents`. A
        strictly positive deficit is margin-call territory; a deficit of
        exactly zero is not — exact equality between posted and required is
        fully collateralized."
        PRD §3.5: "When the daily run finds a strictly positive deficit on a
        `BOOKED` or `RECALLED` loan, it issues a `MarginCall` in `OPEN`
        status whose `amount_due_cents` equals that day's deficit"

        Design: Difficulty/boundary_precision_check/margin_deficit_zero_no_call_one_cent_call
        """
        l1, l2 = self._two_loans(api)
        summary = run_mtm()
        assert summary["margin_calls_issued"] == 1

        calls_l1 = validate_success(api.list_margin_calls(
            OPS, params={"loan_id": l1["id"]}))
        assert calls_l1 == []

        calls_l2 = validate_success(api.list_margin_calls(
            OPS, params={"loan_id": l2["id"]}))
        assert len(calls_l2) == 1
        assert calls_l2[0]["amount_due_cents"] == 1
        assert calls_l2[0]["status"] == "OPEN"

        assert get_loan(l1["id"], OPS)["margin_status"] == "CURRENT"
        assert get_loan(l2["id"], OPS)["margin_status"] == "CALL_OPEN"

    def test_call_due_date_is_next_calendar_day(self, api):
        """PRD §3.5: "it issues a `MarginCall` in `OPEN` status whose
        `amount_due_cents` equals that day's deficit and whose `issued_date`
        is the current clock date, with `due_date` one calendar day later."

        Design: Difficulty/boundary_precision_check/margin_deficit_zero_no_call_one_cent_call
        """
        _, l2 = self._two_loans(api)
        run_mtm()  # clock is 2026-08-01
        call = validate_success(api.list_margin_calls(
            OPS, params={"loan_id": l2["id"]}))[0]
        assert call["issued_date"] == "2026-08-01"
        assert call["due_date"] == "2026-08-02"


class TestMarginCallLifecycle:
    def _deficit_setup(self, api):
        """CASH loan pledged exactly at 102%, then price moved to 1100c."""
        ctx = setup_cash_loan_with_pledge(
            pledge_amount_cents=1_020_000, security_symbol="SM4",
            loan_quantity=1000, rate_bps=0)
        validate_success(api.mark_security_price(
            ctx["security"]["id"], {"price_cents": 1100}, ADMIN))
        return ctx

    def test_open_escalate_cure_lifecycle_with_amendment_gate(self, api):
        """PRD §3.5: "If an `OPEN` call already exists, the run refreshes its
        `amount_due_cents` to the current deficit instead of issuing another;
        an `ESCALATED` call keeps its original amount. A call still open past
        its `due_date` with the deficit persisting is escalated by the run
        from `OPEN` to `ESCALATED`. Whenever posted collateral again reaches
        or exceeds required collateral — after a pledge, a substitution, a
        release, a price mark, or a run — calls in `OPEN` or `ESCALATED` are
        cured to `CURED`"
        PRD §3.4: "any amendment is refused outright while the loan's
        `margin_status` is `CALL_OPEN` — an open or escalated margin call
        blocks renegotiation with `ERR_MARGIN_CALL_OUTSTANDING`."

        Design: Corner/state_machines/margin_call_open_escalated_cured_lifecycle
        """
        ctx = self._deficit_setup(api)
        loan, borrower = ctx["loan"], ctx["borrower"]
        summary = run_mtm()
        assert summary["margin_calls_issued"] == 1
        call = validate_success(api.list_margin_calls(
            OPS, params={"loan_id": loan["id"]}))[0]
        # required now 1000 x 1100 x 1.02 = 1,122,000; deficit 102,000
        assert call["amount_due_cents"] == 102000
        assert call["due_date"] == "2026-08-02"
        assert get_loan(loan["id"], OPS)["margin_status"] == "CALL_OPEN"

        current_version = get_loan(loan["id"], OPS)["version"]
        resp = api.amend_loan(
            loan["id"], {"expected_loan_version": current_version,
                         "rate_bps": 5}, TRADER)
        validate_error(resp, ApiErrorId.ERR_MARGIN_CALL_OUTSTANDING)

        set_clock("2026-08-03T00:00:00Z")
        summary2 = run_mtm()
        assert summary2["margin_calls_escalated"] == 1
        assert get_margin_call(call["id"])["status"] == "ESCALATED"

        # Top-up restores coverage: posted 1,122,000 >= required 1,122,000.
        post_cash_pledge(loan, borrower, 102_000)
        assert get_margin_call(call["id"])["status"] == "CURED"
        assert get_loan(loan["id"], OPS)["margin_status"] == "CURRENT"

    def test_declare_default_rejected_on_open_margin_call(self, api):
        """PRD §3.5: "declaring default on an `ESCALATED` call — only an
        escalated call, and only while its loan is `BOOKED` or `RECALLED`, or
        the request is rejected with `ERR_INVALID_STATE`"

        Design: Corner/state_machines/declare_default_rejected_on_open_margin_call
        """
        ctx = self._deficit_setup(api)
        run_mtm()  # issues an OPEN call; clock still 2026-08-01
        call = validate_success(api.list_margin_calls(
            OPS, params={"loan_id": ctx["loan"]["id"]}))[0]
        resp = api.declare_margin_call_default(
            call["id"], TEST_USERS["risk_officer_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestPriceUpdateRecompute:
    def test_price_update_recomputes_market_value_immediately(self, api):
        """PRD §3.1: "when a `DeskAdmin` marks a new `price_cents`, the
        system immediately recomputes the `marked_value_cents` of every
        `ACTIVE` collateral pledge referencing that security and the
        `market_value_cents` of every open loan in it"
        PRD §2.12: "Price marking between runs is immediate — marking a new
        price recomputes pledge and loan market values at once — but
        margin-call *issuance* remains batched at the daily run."

        Design: Corner/endpoints/price_update_recomputes_market_value_immediately
        """
        ctx = setup_booked_loan(security_symbol="DRV1", loan_quantity=1000,
                                collateral_type="CASH", rate_bps=0)
        validate_success(api.mark_security_price(
            ctx["security"]["id"], {"price_cents": 1200}, ADMIN))
        loan = get_loan(ctx["loan"]["id"])
        assert loan["market_value_cents"] == 1200000
        # 1000 x 1200 x 10200/10000 = 1,224,000
        assert loan["required_collateral_cents"] == 1224000
        calls = validate_success(api.list_margin_calls(
            OPS, params={"loan_id": ctx["loan"]["id"]}))
        assert calls == []


class TestPledgeReleaseGuards:
    def test_release_of_deficit_creating_pledge_rejected(self, api):
        """PRD §3.5: "First, the post-release `posted_collateral_cents` must
        still be at least the loan's `required_collateral_cents` — a release
        that would open a deficit is rejected with `ERR_MARGIN_DEFICIT`."

        Design: Corner/endpoints/release_of_deficit_creating_pledge_rejected
        """
        ctx = setup_cash_loan_with_pledge(
            pledge_amount_cents=1_020_000, security_symbol="REL1",
            loan_quantity=1000, rate_bps=0)
        loan, borrower = ctx["loan"], ctx["borrower"]
        big = ctx["pledge"]
        small = post_cash_pledge(loan, borrower, 50_000)

        resp = api.release_pledge(big["id"], TRADER)
        validate_error(resp, ApiErrorId.ERR_MARGIN_DEFICIT)
        # Releasing the 50,000 excess leaves exactly required: equality passes.
        released = validate_success(api.release_pledge(small["id"], TRADER))
        assert released["status"] == "RELEASED"

    def test_release_exact_equality_boundary(self, api):
        """PRD §3.5: "the post-release `posted_collateral_cents` must still
        be at least the loan's `required_collateral_cents`"
        PRD §2.11: "a deficit of exactly zero is not — exact equality
        between posted and required is fully collateralized."

        Boundary: releasing down to exactly the required amount succeeds.

        Design: Corner/endpoints/release_of_deficit_creating_pledge_rejected
        """
        ctx = setup_cash_loan_with_pledge(
            pledge_amount_cents=1_020_000, security_symbol="REL2",
            loan_quantity=1000, rate_bps=0)
        loan, borrower = ctx["loan"], ctx["borrower"]
        extra = post_cash_pledge(loan, borrower, 1)
        released = validate_success(api.release_pledge(extra["id"], TRADER))
        assert released["status"] == "RELEASED"
        assert get_loan(loan["id"])["posted_collateral_cents"] == 1020000


class TestCashRailsGuards:
    def test_reinvestment_over_uninvested_cash_rejected(self, api):
        """PRD §3.6: "the principal may not exceed the loan's
        `cash_uninvested_cents` (`ERR_REINVEST_EXCEEDS_CASH`)"
        PRD §3.5: "Second, and only after the margin check passes, releasing
        a `CASH` pledge requires the loan's `cash_uninvested_cents` to cover
        the released amount — cash that has been reinvested is not
        releasable, and the attempt is rejected with
        `ERR_INSUFFICIENT_UNINVESTED_CASH`."
        PRD §3.6: "Reinvestment is defined only for loans whose
        `collateral_type` is `CASH` — an attempt against a
        securities-collateral loan is rejected with
        `ERR_LOAN_NOT_CASH_COLLATERAL`"

        Design: Corner/errors/reinvestment_over_uninvested_cash_rejected
        """
        security, owner, borrower, position = setup_desk(
            security_symbol="CSH1", quantity_total=100000)
        l1 = create_and_book_loan(owner, borrower, security, position,
                                  quantity=1000, collateral_type="CASH",
                                  rate_bps=0)
        post_cash_pledge(l1, borrower, 1_020_000)
        plg = post_cash_pledge(l1, borrower, 200_000)
        create_tranche(l1, principal_cents=1_100_000)
        # cash_uninvested = 1,220,000 - 1,100,000 = 120,000
        l2 = create_and_book_loan(owner, borrower, security, position,
                                  quantity=1000, collateral_type="SECURITIES",
                                  rate_bps=25)

        resp1 = api.create_reinvestment(
            l1["id"], {"instrument_type": "MMF", "principal_cents": 120001,
                       "stated_yield_bps": 360}, TRADER)
        validate_error(resp1, ApiErrorId.ERR_REINVEST_EXCEEDS_CASH)

        # Releasing the 200,000c pledge leaves posted 1,020,000 >= required,
        # so the margin check passes — but only 120,000c is uninvested.
        resp2 = api.release_pledge(plg["id"], TRADER)
        validate_error(resp2, ApiErrorId.ERR_INSUFFICIENT_UNINVESTED_CASH)

        resp3 = api.create_reinvestment(
            l2["id"], {"instrument_type": "MMF", "principal_cents": 1000,
                       "stated_yield_bps": 360}, TRADER)
        validate_error(resp3, ApiErrorId.ERR_LOAN_NOT_CASH_COLLATERAL)

    def test_cash_pledge_field_mismatch_rejected(self, api):
        """PRD §3.5: "The two types carry mutually exclusive payloads: a
        `CASH` pledge requires `amount_cents` and forbids
        `pledge_security_id` and `quantity`, while a `SECURITY` pledge
        requires `pledge_security_id` and `quantity` and forbids
        `amount_cents`; mixing them is rejected with
        `ERR_PLEDGE_TYPE_MISMATCH`."

        Design: Corner/errors/cash_pledge_field_mismatch_rejected
        """
        ctx = setup_booked_loan(security_symbol="PTY1", loan_quantity=1000,
                                collateral_type="CASH", rate_bps=0)
        resp = api.create_pledge(
            ctx["loan"]["id"],
            {"pledge_type": "CASH", "amount_cents": 1020000, "quantity": 5},
            make_borrower_rep_headers(ctx["borrower"]["id"]))
        validate_error(resp, ApiErrorId.ERR_PLEDGE_TYPE_MISMATCH)

    def test_security_pledge_with_amount_rejected(self, api):
        """PRD §3.5: "a `SECURITY` pledge requires `pledge_security_id` and
        `quantity` and forbids `amount_cents`; mixing them is rejected with
        `ERR_PLEDGE_TYPE_MISMATCH`."

        Design: Corner/errors/cash_pledge_field_mismatch_rejected
        """
        ctx = setup_booked_loan(security_symbol="PTY2", loan_quantity=1000,
                                collateral_type="SECURITIES", rate_bps=25)
        resp = api.create_pledge(
            ctx["loan"]["id"],
            {"pledge_type": "SECURITY",
             "pledge_security_id": ctx["security"]["id"], "quantity": 100,
             "amount_cents": 5000},
            make_borrower_rep_headers(ctx["borrower"]["id"]))
        validate_error(resp, ApiErrorId.ERR_PLEDGE_TYPE_MISMATCH)


class TestSubstitution:
    def test_substitute_with_lower_value_rejected(self, api):
        """PRD §3.5: "The replacement's `marked_value_cents` must be at least
        the substituted pledge's `marked_value_cents`, or the substitution is
        rejected with `ERR_COLLATERAL_SHORTFALL`."

        Design: Corner/errors/substitute_with_lower_value_rejected
        """
        ctx = setup_cash_loan_with_pledge(
            pledge_amount_cents=1_020_000, security_symbol="SUB1",
            loan_quantity=1000, rate_bps=0)
        loan, borrower, pledge = ctx["loan"], ctx["borrower"], ctx["pledge"]
        current = get_loan(loan["id"], make_borrower_rep_headers(borrower["id"]))
        resp = api.substitute_pledge(
            loan["id"], pledge["id"],
            {"expected_loan_version": current["version"],
             "pledge_type": "CASH", "amount_cents": 1019999},
            make_borrower_rep_headers(borrower["id"]))
        validate_error(resp, ApiErrorId.ERR_COLLATERAL_SHORTFALL)
        assert get_pledge(pledge["id"])["status"] == "ACTIVE"

    def test_substitute_with_equal_value_succeeds(self, api):
        """PRD §3.5: "The replacement's `marked_value_cents` must be at least
        the substituted pledge's `marked_value_cents`, or the substitution is
        rejected with `ERR_COLLATERAL_SHORTFALL`. A successful substitution
        moves the old pledge to `SUBSTITUTED`, creates the new pledge
        `ACTIVE`, increments the loan's `version` by one, and recomputes
        posted collateral."

        Boundary: an equal-value replacement is accepted (>=, not >).

        Design: Corner/errors/substitute_with_lower_value_rejected
        """
        ctx = setup_cash_loan_with_pledge(
            pledge_amount_cents=1_020_000, security_symbol="SUB2",
            loan_quantity=1000, rate_bps=0)
        loan, borrower, pledge = ctx["loan"], ctx["borrower"], ctx["pledge"]
        before = get_loan(loan["id"], make_borrower_rep_headers(borrower["id"]))
        new_pledge = validate_success(api.substitute_pledge(
            loan["id"], pledge["id"],
            {"expected_loan_version": before["version"],
             "pledge_type": "CASH", "amount_cents": 1020000},
            make_borrower_rep_headers(borrower["id"])))
        assert new_pledge["status"] == "ACTIVE"
        assert get_pledge(pledge["id"])["status"] == "SUBSTITUTED"
        after = get_loan(loan["id"])
        assert after["version"] == before["version"] + 1
        assert after["posted_collateral_cents"] == 1020000
