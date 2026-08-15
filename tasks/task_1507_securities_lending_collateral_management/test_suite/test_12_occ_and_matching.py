"""Optimistic concurrency on the loan version and the match selector.

Covers corner instances occ_amendment_stale_version_rejected,
occ_substitute_stale_version_rejected,
match_selector_ranks_by_min_fee_then_created,
match_with_empty_eligible_pool_returns_no_inventory,
return_exceeding_outstanding_rejected, offboard_blocked_while_loans_open.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_borrow_request,
    create_position,
    get_loan,
    get_pledge,
    get_position,
    make_borrower_rep_headers,
    make_owner_rep_headers,
    post_cash_pledge,
    return_shares,
    setup_booked_loan,
    setup_cash_loan_with_pledge,
    setup_desk,
    validate_error,
    validate_success,
)

TRADER = TEST_USERS["desk_trader_headers"]
RISK = TEST_USERS["risk_officer_headers"]


class TestOCCAmendments:
    def test_amendment_stale_version_rejected(self, api):
        """PRD §2.6: "Amending a `BOOKED` loan's terms and substituting one
        of its collateral pledges each require the request to carry
        `expected_loan_version`, a non-optional field holding the loan
        `version` the client last observed. If the loan's current `version`
        has advanced beyond that value — because a counter, a return, a
        recall, a prior amendment, or any other mutation landed in between —
        the request is rejected with `ERR_STALE_VERSION` (HTTP 412)"
        PRD §3.4: "A successful amendment increments the loan's `version` by
        one."

        Design: Corner/complexity_layers/occ_amendment_stale_version_rejected
        """
        ctx = setup_booked_loan(security_symbol="OC1", loan_quantity=1000)
        loan = ctx["loan"]
        current = get_loan(loan["id"], make_borrower_rep_headers(
            ctx["borrower"]["id"]))
        assert current["version"] == 2  # create 1, accept 2

        amended = validate_success(api.amend_loan(
            loan["id"], {"expected_loan_version": 2, "rate_bps": 30}, TRADER))
        assert amended["rate_bps"] == 30
        assert amended["version"] == 3

        resp = api.amend_loan(
            loan["id"], {"expected_loan_version": 2, "rate_bps": 32}, TRADER)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert get_loan(loan["id"])["rate_bps"] == 30

    def test_amendment_with_current_version_succeeds(self, api):
        """PRD §3.4: "A `DeskTrader` may amend a `BOOKED` loan's `rate_bps`,
        its `term_days`, or both, in a request that must carry
        `expected_loan_version`; a value that no longer matches the loan's
        current `version` is rejected with `ERR_STALE_VERSION`"

        Design: Corner/complexity_layers/occ_amendment_stale_version_rejected
        """
        ctx = setup_booked_loan(security_symbol="OC1B", loan_quantity=1000)
        loan = ctx["loan"]
        amended = validate_success(api.amend_loan(
            loan["id"], {"expected_loan_version": 2, "rate_bps": 30,
                         "term_days": 14}, TRADER))
        assert amended["rate_bps"] == 30
        assert amended["term_days"] == 14
        assert amended["version"] == 3
        # The new version is the basis for the next amendment.
        amended2 = validate_success(api.amend_loan(
            loan["id"], {"expected_loan_version": 3, "rate_bps": 28}, TRADER))
        assert amended2["rate_bps"] == 28
        assert amended2["version"] == 4


class TestOCCSubstitution:
    def test_substitute_stale_version_rejected(self, api):
        """PRD §3.5: "A `BorrowerRep` substitutes an `ACTIVE` pledge on a
        `BOOKED` or `RECALLED` loan with a payload carrying
        `expected_loan_version` — rejected with `ERR_STALE_VERSION` when the
        loan's `version` has advanced past it"
        PRD §3.5: "A successful substitution moves the old pledge to
        `SUBSTITUTED`, creates the new pledge `ACTIVE`, increments the loan's
        `version` by one"

        Design: Corner/complexity_layers/occ_substitute_stale_version_rejected
        """
        ctx = setup_cash_loan_with_pledge(
            pledge_amount_cents=1_020_000, security_symbol="OC2",
            loan_quantity=1000, rate_bps=0)
        loan, borrower, p1 = ctx["loan"], ctx["borrower"], ctx["pledge"]
        headers = make_borrower_rep_headers(borrower["id"])
        v = get_loan(loan["id"], headers)["version"]

        p2 = validate_success(api.substitute_pledge(
            loan["id"], p1["id"],
            {"expected_loan_version": v, "pledge_type": "CASH",
             "amount_cents": 1020000}, headers))
        assert p2["status"] == "ACTIVE"
        assert get_pledge(p1["id"])["status"] == "SUBSTITUTED"

        resp = api.substitute_pledge(
            loan["id"], p2["id"],
            {"expected_loan_version": v, "pledge_type": "CASH",
             "amount_cents": 1020000}, headers)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_substitute_with_fresh_version_after_mutation(self, api):
        """PRD §2.6: "If the loan's current `version` has advanced beyond
        that value — because a counter, a return, a recall, a prior
        amendment, or any other mutation landed in between — the request is
        rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client
        from overwriting a loan state it has not observed."

        A client that re-reads the loan after the first substitution and
        carries the fresh version substitutes successfully.

        Design: Corner/complexity_layers/occ_substitute_stale_version_rejected
        """
        ctx = setup_cash_loan_with_pledge(
            pledge_amount_cents=1_020_000, security_symbol="OC2B",
            loan_quantity=1000, rate_bps=0)
        loan, borrower, p1 = ctx["loan"], ctx["borrower"], ctx["pledge"]
        headers = make_borrower_rep_headers(borrower["id"])
        v1 = get_loan(loan["id"], headers)["version"]
        p2 = validate_success(api.substitute_pledge(
            loan["id"], p1["id"],
            {"expected_loan_version": v1, "pledge_type": "CASH",
             "amount_cents": 1020000}, headers))
        v2 = get_loan(loan["id"], headers)["version"]
        p3 = validate_success(api.substitute_pledge(
            loan["id"], p2["id"],
            {"expected_loan_version": v2, "pledge_type": "CASH",
             "amount_cents": 1020000}, headers))
        assert p3["status"] == "ACTIVE"
        assert get_pledge(p2["id"])["status"] == "SUBSTITUTED"
        assert get_loan(loan["id"])["posted_collateral_cents"] == 1020000


class TestMatchSelector:
    def test_selector_ranks_by_min_fee_then_created(self, api):
        """PRD §3.3: "The selector considers only eligible positions — `OPEN`
        positions in the requested security whose owner is `ACTIVE`, whose
        `min_fee_bps` does not exceed the request's `max_rate_bps`, and whose
        forward capacity covers the requested quantity across the window from
        the current date through the current date plus the request's
        `term_days` — and ranks them by `min_fee_bps` ascending, then by
        `created_at` ascending, then by `quantity_total` descending."
        PRD §3.3: "A successful match creates a `Loan` in `PROPOSED` status —
        `rate_bps` set to the position's `min_fee_bps`, terms copied from the
        request, `borrow_request_id` pointing back at it — moves the request
        from `SUBMITTED` to `MATCHED`"

        Design: Corner/endpoints/match_selector_ranks_by_min_fee_then_created
        """
        # Use a setup_desk position whose min_fee_bps (50) is above the
        # request's max_rate_bps (40) so it is ineligible and the only
        # eligible candidates are the two positions created below.
        security, owner, borrower, _ = setup_desk(security_symbol="SEL1",
                                                  quantity_total=10000,
                                                  min_fee_bps=50)
        p1 = create_position(owner, security, quantity_total=10000,
                             min_fee_bps=30)
        p2 = create_position(owner, security, quantity_total=10000,
                             min_fee_bps=25)
        request = create_borrow_request(borrower, security, quantity=1000,
                                        max_rate_bps=40)
        loan = validate_success(api.match_borrow_request(
            request["id"], {}, TRADER), expected_status=201)
        assert loan["position_id"] == p2["id"]
        assert loan["rate_bps"] == 25
        assert loan["status"] == "PROPOSED"
        from test_helpers import get_borrow_request
        assert get_borrow_request(request["id"])["status"] == "MATCHED"

    def test_match_with_empty_eligible_pool_returns_no_inventory(self, api):
        """PRD §3.3: "If no eligible position exists the match is rejected
        with `ERR_NO_INVENTORY`"

        Design: Corner/endpoints/match_with_empty_eligible_pool_returns_no_inventory
        """
        security, owner, borrower, _ = setup_desk(security_symbol="SEL2",
                                                  quantity_total=500)
        request = create_borrow_request(borrower, security, quantity=1000,
                                        max_rate_bps=40)
        resp = api.match_borrow_request(request["id"], {}, TRADER)
        validate_error(resp, ApiErrorId.ERR_NO_INVENTORY)
        from test_helpers import get_borrow_request
        assert get_borrow_request(request["id"])["status"] == "SUBMITTED"


class TestReturnGuards:
    def test_return_exceeding_outstanding_rejected(self, api):
        """PRD §3.4: "a `BorrowerRep` posts a return `quantity` against a
        `BOOKED` or `RECALLED` loan, which may not exceed the loan's
        `outstanding_quantity` (`ERR_RETURN_EXCEEDS_LOAN`)."

        Design: Corner/errors/return_exceeding_outstanding_rejected
        """
        ctx = setup_booked_loan(security_symbol="RET1", loan_quantity=1000)
        return_shares(ctx["loan"], ctx["borrower"], 400)
        resp = api.return_loan(
            ctx["loan"]["id"], {"quantity": 601},
            make_borrower_rep_headers(ctx["borrower"]["id"]))
        validate_error(resp, ApiErrorId.ERR_RETURN_EXCEEDS_LOAN)
        assert get_loan(ctx["loan"]["id"])["outstanding_quantity"] == 600

    def test_return_exactly_outstanding_boundary(self, api):
        """PRD §3.4: "a `BorrowerRep` posts a return `quantity` against a
        `BOOKED` or `RECALLED` loan, which may not exceed the loan's
        `outstanding_quantity` (`ERR_RETURN_EXCEEDS_LOAN`). Each return
        reduces `outstanding_quantity` and increments the loan's `version`"
        PRD §3.4: "A return that brings `outstanding_quantity` to zero
        settles the loan"

        Boundary: returning exactly the outstanding quantity is allowed and
        settles the loan.

        Design: Corner/errors/return_exceeding_outstanding_rejected
        """
        ctx = setup_booked_loan(security_symbol="RET2", loan_quantity=1000)
        return_shares(ctx["loan"], ctx["borrower"], 400)
        settled = return_shares(ctx["loan"], ctx["borrower"], 600)
        assert settled["status"] == "SETTLED"
        assert settled["outstanding_quantity"] == 0


class TestOffboard:
    def test_offboard_blocked_while_loans_open(self, api):
        """PRD §3.2: "Offboarding — from either `ACTIVE` or `SUSPENDED` to
        `OFFBOARDED` — is guarded: the owner must have no loans in `BOOKED`
        or `RECALLED`, and every position must show zero `quantity_on_loan`
        and zero `quantity_reserved`; otherwise the request is rejected with
        `ERR_OWNER_HAS_OPEN_LOANS`. A successful offboarding moves all of the
        owner's `OPEN` positions to `SUSPENDED`."

        Design: Corner/errors/offboard_blocked_while_loans_open
        """
        ctx = setup_booked_loan(security_symbol="OFF1", quantity_total=10000,
                                loan_quantity=500)
        resp = api.offboard_beneficial_owner(ctx["owner"]["id"], RISK)
        validate_error(resp, ApiErrorId.ERR_OWNER_HAS_OPEN_LOANS)

        return_shares(ctx["loan"], ctx["borrower"], 500)
        offboarded = validate_success(
            api.offboard_beneficial_owner(ctx["owner"]["id"], RISK))
        assert offboarded["status"] == "OFFBOARDED"
        assert get_position(ctx["position"]["id"], RISK)["status"] == \
            "SUSPENDED"
