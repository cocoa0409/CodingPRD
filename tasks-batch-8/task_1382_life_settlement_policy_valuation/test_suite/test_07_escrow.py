"""Escrow funding guards, release window, waterfall, rescission (PRD §3.5)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, make_broker_headers, make_finance_headers,
    make_compliance_headers,
    setup_case_in_closing, setup_package_approved, setup_ownership_confirmed,
    set_clock, create_portfolio_payload,
    assert_escrow_cash_invariant,
)

ADMIN = TEST_USERS["admin_headers"]
CM = TEST_USERS["case_manager_headers"]
PM = TEST_USERS["portfolio_manager_headers"]
CO_1 = make_compliance_headers("co_1")
FO_1 = make_finance_headers("fo_1")


class TestFundingGuards:
    def test_fund_amount_mismatch_rejected(self, api):
        """PRD §3.5: "the deposited `amount_cents` must equal
        `expected_funding_cents` exactly (`ERR_ESCROW_FUNDS_MISMATCH`, HTTP 422)."

        Design: Corner/validations/fund_amount_mismatch_rejected
        """
        ctx = setup_package_approved()
        escrow = ctx["escrow"]
        assert escrow["expected_funding_cents"] == 6090000
        resp = api.fund_escrow(escrow["id"], {"amount_cents": 6090001}, FO_1)
        validate_error(resp, ApiErrorId.ERR_ESCROW_FUNDS_MISMATCH)
        after = validate_success(api.get_escrow_account(escrow["id"], CM))
        assert after["status"] == "OPEN"

    def test_fund_without_portfolio_assignment_rejected(self, api):
        """PRD §3.5: "the case must already carry a `portfolio_id`
        (`ERR_PORTFOLIO_NOT_ASSIGNED`, HTTP 422)"

        Design: Corner/validations/fund_without_portfolio_assignment_rejected
        """
        ctx = setup_package_approved(portfolio=False)
        escrow = ctx["escrow"]
        resp = api.fund_escrow(escrow["id"], {"amount_cents": 6090000}, FO_1)
        validate_error(resp, ApiErrorId.ERR_PORTFOLIO_NOT_ASSIGNED)

        pf = validate_success(api.create_portfolio(create_portfolio_payload(), PM),
                              expected_status=201)
        validate_success(api.assign_portfolio(ctx["case"]["id"], {"portfolio_id": pf["id"]}, PM))
        funded = validate_success(api.fund_escrow(escrow["id"], {"amount_cents": 6090000}, FO_1))
        assert funded["status"] == "FUNDED"

    def test_escrow_fund_rejected_before_package_approval(self, api):
        """PRD §3.5: "The closing package must be `APPROVED` (otherwise
        `ERR_INVALID_STATE_TRANSITION`)"
        PRD §3.5: "A valid funding stamps `funded_at` with the clock, sets
        `releasable_at` to `funded_at` plus 15 days — the seller's statutory
        rescission window"

        Design: Difficulty/cross_entity_state_dependency/escrow_fund_rejected_before_package_approval
        """
        # Package signed but still OUT_FOR_SIGNATURE (submit-review NOT yet called)
        # is not APPROVED; fund must be rejected.
        from test_helpers import setup_case_in_closing, sign_documents
        ctx = setup_case_in_closing()
        validate_success(api.send_for_signature(ctx["package"]["id"], CM))
        sign_documents(ctx["package"]["id"])
        escrow = ctx["escrow"]

        resp = api.fund_escrow(escrow["id"], {"amount_cents": 6090000}, FO_1)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

        # Same rejection from COMPLIANCE_REVIEW: funding requires APPROVED.
        validate_success(api.submit_review(ctx["package"]["id"], CM))
        resp_mid = api.fund_escrow(escrow["id"], {"amount_cents": 6090000}, FO_1)
        validate_error(resp_mid, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        validate_success(api.approve_package(ctx["package"]["id"], CO_1))
        funded = validate_success(api.fund_escrow(escrow["id"], {"amount_cents": 6090000}, FO_1))
        assert funded["status"] == "FUNDED"
        assert funded["releasable_at"] == "2026-08-16T00:00:00Z", (
            "funded at the default clock 2026-08-01, plus 15 days"
        )

    def test_escrow_fund_succeeds_immediately_after_approval(self, api):
        """PRD §3.5: "The closing package must be `APPROVED` (otherwise
        `ERR_INVALID_STATE_TRANSITION`)"
        PRD §3.5: "A valid funding stamps `funded_at` with the clock, sets
        `releasable_at` to `funded_at` plus 15 days — the seller's statutory
        rescission window — records `funded_amount_cents`, sets `balance_cents` to
        the funded amount, and moves the account from `OPEN` to `FUNDED` with a
        version increment."

        Design: Difficulty/cross_entity_state_dependency/escrow_fund_rejected_before_package_approval
        """
        ctx = setup_package_approved()
        escrow = ctx["escrow"]
        funded = validate_success(api.fund_escrow(
            escrow["id"], {"amount_cents": escrow["expected_funding_cents"]}, FO_1))
        assert funded["status"] == "FUNDED"
        assert funded["funded_amount_cents"] == 6090000
        assert funded["funded_at"] == "2026-08-01T00:00:00Z"
        assert funded["releasable_at"] == "2026-08-16T00:00:00Z"
        assert funded["balance_cents"] == 6090000

    def test_broker_cannot_fund_escrow(self, api):
        """PRD §2.1: "If the role is recognized but does not appear in the
        endpoint's authorized role list, the request is rejected with
        `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §4: "POST | /api/escrow-accounts/{id}/fund | Fund escrow at the exact
        expected amount | FinanceOfficer"

        Design: Corner/rbac/broker_cannot_fund_escrow
        """
        ctx = setup_case_in_closing(portfolio=False)
        resp = api.fund_escrow(ctx["escrow"]["id"], {"amount_cents": 6090000},
                               make_broker_headers(ctx["broker"]["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)


class TestReleaseWindowAndWaterfall:
    def test_rescission_window_second_precision(self, api):
        """PRD §3.5: "the clock must have reached `releasable_at` — an earlier
        attempt is rejected with `ERR_RESCISSION_WINDOW_ACTIVE` (HTTP 409)"
        PRD §3.5: "A valid funding stamps `funded_at` with the clock, sets
        `releasable_at` to `funded_at` plus 15 days — the seller's statutory
        rescission window"

        Design: Difficulty/boundary_precision_check/rescission_window_second_precision
        """
        ctx = setup_ownership_confirmed()  # funded at default clock 2026-08-01
        escrow = ctx["escrow"]
        assert escrow["releasable_at"] == "2026-08-16T00:00:00Z"

        set_clock("2026-08-15T23:59:59Z")
        resp = api.release_escrow(escrow["id"], FO_1)
        validate_error(resp, ApiErrorId.ERR_RESCISSION_WINDOW_ACTIVE)

        set_clock("2026-08-16T00:00:00Z")
        released = validate_success(api.release_escrow(escrow["id"], FO_1))
        assert released["status"] == "RELEASED", "release at exactly releasable_at succeeds (>= inclusive)"
        case_after = validate_success(api.get_case(ctx["case"]["id"], CM))
        assert case_after["status"] == "ACQUIRED"

    def test_release_one_second_before_window_rejected(self, api):
        """PRD §3.5: "the clock must have reached `releasable_at` — an earlier
        attempt is rejected with `ERR_RESCISSION_WINDOW_ACTIVE` (HTTP 409)"
        PRD §2.4: "The clock's startup default, before any call to set it, is
        exactly 2026-08-01T00:00:00Z."

        Design: Difficulty/boundary_precision_check/rescission_window_second_precision
        """
        ctx = setup_ownership_confirmed()  # funded at the default clock 2026-08-01
        escrow = ctx["escrow"]
        assert escrow["funded_at"] == "2026-08-01T00:00:00Z"
        assert escrow["releasable_at"] == "2026-08-16T00:00:00Z"

        set_clock("2026-08-15T23:59:59Z")
        resp = api.release_escrow(escrow["id"], FO_1)
        validate_error(resp, ApiErrorId.ERR_RESCISSION_WINDOW_ACTIVE)
        after = validate_success(api.get_escrow_account(escrow["id"], CM))
        assert after["status"] == "FUNDED", "rejected release leaves the escrow FUNDED"

    def test_waterfall_per_bucket_rounding_beats_sum_rounding(self, api):
        """PRD §3.5: "The waterfall itself allocates the funds into exactly four
        `Disbursement` rows, each stamped with the account's `escrow_id` and a
        `bucket` value of ESCROW_FEE, SERVICING_FEE, BROKER_COMMISSION, or
        SELLER_NET, created `PENDING` in that fixed bucket order, and each bucket's
        `amount_cents` is rounded half-up to cents immediately, before the next
        bucket is computed — the rounding is per-bucket, never a single rounding of
        the total. The ESCROW_FEE row is the flat 75000 cents. The SERVICING_FEE
        row is the price times 25 basis points, rounded half-up. The
        BROKER_COMMISSION row is the smaller of the price times the case's stored
        `broker_commission_bps` (rounded half-up) and the policy's face amount
        times 600 basis points (rounded half-up); when a commission is payable, the
        row's `payee_broker_id` names the case's broker, and otherwise that field
        stays unset. The SELLER_NET row receives the price minus the commission —
        the seller's proceeds net of broker compensation — while the two fees are
        funded by the provider on top of price, so the four disbursements sum
        exactly to the funded amount and `balance_cents` lands at 0."

        Design: Difficulty/combinatorial_formula/waterfall_per_bucket_rounding_beats_sum_rounding
        """
        # P = 6789110: per-bucket commission+servicing (325878) differs from
        # sum-then-round of the combined 480 bps (325877) by exactly one cent.
        ctx = setup_ownership_confirmed(offer_amount=6789110)
        escrow = ctx["escrow"]
        assert escrow["expected_funding_cents"] == 6881083, (
            "6789110 + 75000 + round_half_up(6789110*25/10000) = 6789110 + 75000 + 16973"
        )
        # Fixture funded at the default clock; releasable 2026-08-16.
        set_clock("2026-08-16T00:00:00Z")
        released = validate_success(api.release_escrow(escrow["id"], FO_1))
        assert released["status"] == "RELEASED"

        rows, _m = validate_paginated(api.list_escrow_disbursements(escrow["id"], CM))
        assert len(rows) == 4
        assert [r["bucket"] for r in rows] == ["ESCROW_FEE", "SERVICING_FEE",
                                               "BROKER_COMMISSION", "SELLER_NET"]
        assert rows[0]["amount_cents"] == 75000
        assert rows[1]["amount_cents"] == 16973, "round_half_up(6789110 * 25/10000)"
        assert rows[2]["amount_cents"] == 308905, (
            "round_half_up(6789110 * 455/10000), under the face cap 600000"
        )
        assert rows[2]["payee_broker_id"] == ctx["broker"]["id"]
        assert rows[3]["amount_cents"] == 6480205, "6789110 - 308905"
        assert rows[1]["amount_cents"] + rows[2]["amount_cents"] == 325878
        assert 325878 != 325877, "per-bucket rounding beats round_half_up(6789110*480/10000)"
        assert sum(r["amount_cents"] for r in rows) == 6881083
        after = validate_success(api.get_escrow_account(escrow["id"], CM))
        assert after["balance_cents"] == 0
        assert after["funded_amount_cents"] == 6881083

    def test_waterfall_bucket_amounts_and_commission_cap_face(self, api):
        """PRD §3.5: "The waterfall itself allocates the funds into exactly four
        `Disbursement` rows, each stamped with the account's `escrow_id` and a
        `bucket` value of ESCROW_FEE, SERVICING_FEE, BROKER_COMMISSION, or
        SELLER_NET, created `PENDING` in that fixed bucket order, and each bucket's
        `amount_cents` is rounded half-up to cents immediately, before the next
        bucket is computed — the rounding is per-bucket, never a single rounding of
        the total. The ESCROW_FEE row is the flat 75000 cents. The SERVICING_FEE
        row is the price times 25 basis points, rounded half-up. The
        BROKER_COMMISSION row is the smaller of the price times the case's stored
        `broker_commission_bps` (rounded half-up) and the policy's face amount
        times 600 basis points (rounded half-up); when a commission is payable, the
        row's `payee_broker_id` names the case's broker, and otherwise that field
        stays unset. The SELLER_NET row receives the price minus the commission —
        the seller's proceeds net of broker compensation — while the two fees are
        funded by the provider on top of price, so the four disbursements sum
        exactly to the funded amount and `balance_cents` lands at 0."

        Design: Difficulty/combinatorial_formula/waterfall_per_bucket_rounding_beats_sum_rounding
        """
        # P = 6000000, commission 455 bps: round_half_up(6000000*455/10000) = 273000,
        # face cap round_half_up(10000000*600/10000) = 600000 (not binding).
        ctx = setup_ownership_confirmed(offer_amount=6000000)
        escrow = ctx["escrow"]
        assert escrow["expected_funding_cents"] == 6090000
        set_clock("2026-08-16T00:00:00Z")
        validate_success(api.release_escrow(escrow["id"], FO_1))

        rows, _m = validate_paginated(api.list_escrow_disbursements(escrow["id"], CM))
        assert [r["bucket"] for r in rows] == ["ESCROW_FEE", "SERVICING_FEE",
                                               "BROKER_COMMISSION", "SELLER_NET"]
        assert all(r["status"] == "PENDING" for r in rows)
        assert rows[0]["amount_cents"] == 75000
        assert rows[1]["amount_cents"] == 15000, "round_half_up(6000000 * 25/10000)"
        assert rows[2]["amount_cents"] == 273000, "min(273000, face cap 600000)"
        assert rows[2]["payee_broker_id"] == ctx["broker"]["id"]
        assert rows[3]["amount_cents"] == 5727000, "6000000 - 273000"
        assert sum(r["amount_cents"] for r in rows) == 6090000
        after = validate_success(api.get_escrow_account(escrow["id"], CM))
        assert after["balance_cents"] == 0

    def test_escrow_closes_when_last_disbursement_settles(self, api):
        """PRD §3.5: "When the last `PENDING` row settles, the escrow account closes
        automatically (`RELEASED` → `CLOSED`)."

        Design: Corner/state_machines/escrow_closes_when_last_disbursement_settles
        """
        ctx = setup_ownership_confirmed()
        set_clock("2026-08-16T00:00:00Z")
        validate_success(api.release_escrow(ctx["escrow"]["id"], FO_1))
        rows, _m = validate_paginated(api.list_escrow_disbursements(ctx["escrow"]["id"], CM))
        assert len(rows) == 4
        for row in rows[:3]:
            validate_success(api.mark_disbursement_paid(row["id"], FO_1))
        mid = validate_success(api.get_escrow_account(ctx["escrow"]["id"], CM))
        assert mid["status"] == "RELEASED", "3 of 4 settled: escrow stays RELEASED"
        validate_success(api.mark_disbursement_paid(rows[3]["id"], FO_1))
        end = validate_success(api.get_escrow_account(ctx["escrow"]["id"], CM))
        assert end["status"] == "CLOSED"


class TestRescission:
    def test_rescind_after_window_rejected(self, api):
        """PRD §3.5: "while the clock is still earlier than `releasable_at`, a
        compliance officer may rescind the funded escrow — at or after
        `releasable_at` the window has closed and the attempt is rejected with
        `ERR_RESCISSION_WINDOW_EXPIRED` (HTTP 409)."

        Design: Corner/validations/rescind_after_window_rejected
        """
        ctx = setup_package_approved()
        funded = validate_success(api.fund_escrow(
            ctx["escrow"]["id"], {"amount_cents": 6090000}, FO_1))
        assert funded["releasable_at"] == "2026-08-16T00:00:00Z"

        set_clock("2026-08-16T00:00:00Z")
        resp = api.rescind_escrow(ctx["escrow"]["id"], CO_1)
        validate_error(resp, ApiErrorId.ERR_RESCISSION_WINDOW_EXPIRED)
        after = validate_success(api.get_escrow_account(ctx["escrow"]["id"], CM))
        assert after["status"] == "FUNDED"

    def test_escrow_fund_rescind_conserves_cash(self, api):
        """PRD §3.5: "A valid funding stamps `funded_at` with the clock, sets
        `releasable_at` to `funded_at` plus 15 days — the seller's statutory
        rescission window — records `funded_amount_cents`, sets `balance_cents` to
        the funded amount, and moves the account from `OPEN` to `FUNDED` with a
        version increment."
        PRD §3.5: "Rescission refunds the provider's funding source in full:
        `refund_cents` equals `funded_amount_cents` with no fee retained,
        `balance_cents` returns to 0, and the account moves from `FUNDED` to
        `REVERSED`. The cascade closes the loop: the closing package moves to
        `CANCELLED` (from whichever of its post-approval states it occupies), the
        case moves from `IN_CLOSING` to `RESCINDED` with `purchase_price_cents`
        cleared while `accepted_offer_id` is kept for audit"

        Design: Difficulty/compensating_invariant/escrow_fund_rescind_conserves_cash
        """
        ctx = setup_package_approved()
        funded = validate_success(api.fund_escrow(
            ctx["escrow"]["id"], {"amount_cents": 6090000}, FO_1))
        assert funded["balance_cents"] == 6090000
        assert_escrow_cash_invariant(6090000, 0, funded["balance_cents"], 0)

        reversed_ = validate_success(api.rescind_escrow(ctx["escrow"]["id"], CO_1))
        assert reversed_["status"] == "REVERSED"
        assert reversed_["refund_cents"] == 6090000
        assert reversed_["balance_cents"] == 0
        assert_escrow_cash_invariant(6090000, 0, reversed_["balance_cents"],
                                     reversed_["refund_cents"])

        case_after = validate_success(api.get_case(ctx["case"]["id"], CM))
        assert case_after["status"] == "RESCINDED"
        pkg_after = validate_success(api.get_closing_package(ctx["package"]["id"], CM))
        assert pkg_after["status"] == "CANCELLED"

    def test_rescind_clears_purchase_price_but_keeps_offer_audit(self, api):
        """PRD §3.5: "Rescission refunds the provider's funding source in full:
        `refund_cents` equals `funded_amount_cents` with no fee retained,
        `balance_cents` returns to 0, and the account moves from `FUNDED` to
        `REVERSED`. The cascade closes the loop: the closing package moves to
        `CANCELLED` (from whichever of its post-approval states it occupies), the
        case moves from `IN_CLOSING` to `RESCINDED` with `purchase_price_cents`
        cleared while `accepted_offer_id` is kept for audit"

        Design: Difficulty/compensating_invariant/escrow_fund_rescind_conserves_cash
        """
        ctx = setup_package_approved()
        accepted_offer_id = ctx["offer"]["id"]
        funded = validate_success(api.fund_escrow(
            ctx["escrow"]["id"], {"amount_cents": 6090000}, FO_1))
        assert funded["funded_amount_cents"] == 6090000

        # Inside the window (clock still the startup default 2026-08-01).
        reversed_ = validate_success(api.rescind_escrow(ctx["escrow"]["id"], CO_1))
        assert reversed_["refund_cents"] == 6090000
        assert reversed_["status"] == "REVERSED"

        case_after = validate_success(api.get_case(ctx["case"]["id"], CM))
        assert case_after["status"] == "RESCINDED"
        assert case_after["purchase_price_cents"] is None
        assert case_after["accepted_offer_id"] == accepted_offer_id

    def test_portfolio_capital_acquire_rescind_invariant(self, api):
        """PRD §3.5: "Funding also dirties the destination portfolio in one cascade:
        the portfolio's `invested_capital_cents` grows by the case's
        `purchase_price_cents`, its `holding_count` grows by 1, `nav_stale` becomes
        true, and the portfolio's `version` increments."
        PRD §3.5: "the portfolio reverses its funding-time entries —
        `invested_capital_cents` loses the purchase price that was added at
        funding, `holding_count` decrements, `nav_stale` becomes true, and the
        portfolio's `version` increments."

        Design: Difficulty/compensating_invariant/portfolio_capital_acquire_rescind_invariant
        """
        ctx = setup_package_approved()
        pf = ctx["portfolio"]
        at_zero = validate_success(api.get_portfolio(pf["id"], PM))
        assert at_zero["invested_capital_cents"] == 0
        assert at_zero["holding_count"] == 0

        validate_success(api.fund_escrow(ctx["escrow"]["id"], {"amount_cents": 6090000}, FO_1))
        mid = validate_success(api.get_portfolio(pf["id"], PM))
        assert mid["invested_capital_cents"] == 6000000, (
            "exactly purchase_price_cents, not the fee-loaded 6090000"
        )
        assert mid["holding_count"] == 1
        assert mid["nav_stale"] is True

        validate_success(api.rescind_escrow(ctx["escrow"]["id"], CO_1))
        end = validate_success(api.get_portfolio(pf["id"], PM))
        assert end["invested_capital_cents"] == 0
        assert end["holding_count"] == 0
        case_after = validate_success(api.get_case(ctx["case"]["id"], CM))
        assert case_after["status"] == "RESCINDED"

    def test_portfolio_capital_fund_adds_exactly_purchase_price(self, api):
        """PRD §3.5: "Funding also dirties the destination portfolio in one
        cascade: the portfolio's `invested_capital_cents` grows by the case's
        `purchase_price_cents`, its `holding_count` grows by 1, `nav_stale` becomes
        true, and the portfolio's `version` increments."
        PRD §3.6: "A portfolio's `holding_count` counts its cases that are either
        `IN_CLOSING` with a funded escrow or `ACQUIRED`. Its
        `invested_capital_cents` sums the `purchase_price_cents` of its
        funded-and-not-rescinded cases plus every `PAID` premium on those cases'
        schedules."

        Design: Difficulty/compensating_invariant/portfolio_capital_acquire_rescind_invariant
        """
        ctx = setup_package_approved()
        pf = ctx["portfolio"]
        before = validate_success(api.get_portfolio(pf["id"], PM))
        assert before["invested_capital_cents"] == 0
        assert before["holding_count"] == 0
        assert before["nav_stale"] is False

        validate_success(api.fund_escrow(ctx["escrow"]["id"], {"amount_cents": 6090000}, FO_1))
        after = validate_success(api.get_portfolio(pf["id"], PM))
        assert after["invested_capital_cents"] == 6000000, (
            "funding adds purchase_price_cents only; the 90000 of fees are not portfolio capital"
        )
        assert after["holding_count"] == 1
        assert after["nav_stale"] is True
        assert after["version"] == before["version"] + 1
