"""Draws against an active HELOC.

Covers PRD §3.3 (draw rules, available-credit deduction, ledger entry
shape) and the state-based rejection codes for non-DRAW HELOCs.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    assert_credit_conservation,
    assert_draw,
    assert_version_incremented_by_one,
    create_draw_payload,
    make_borrower_headers,
    setup_active_heloc,
    setup_active_heloc_with_balance,
    setup_heloc_default_via_bankruptcy,
    setup_heloc_in_repay,
    setup_pending_heloc,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.3 Successful draws
# ===========================================================================
class TestDrawSuccess:

    def test_first_draw_increments_principal_and_decrements_credit(
        self, api,
    ):
        """PRD §3.3: "A successfully recorded draw is an immutable
        ledger entry containing the originating heloc_id, the
        amount_cents, and a server-clock drawn_at timestamp; it adds
        amount_cents to the HELOC's principal_balance_cents and
        subtracts amount_cents from its available_credit_cents".
        """
        borrower, _, _, heloc = setup_active_heloc(
            credit_limit_cents=2_000_000,
        )
        before_version = heloc["version"]
        before_avail = heloc["available_credit_cents"]
        assert before_avail == 2_000_000
        assert heloc["principal_balance_cents"] == 0

        resp = api.create_draw(
            heloc["id"],
            create_draw_payload(amount_cents=500_000),
            make_borrower_headers(borrower["id"]),
        )
        draw = validate_success(resp, 201)
        assert_draw(draw)
        assert draw["heloc_id"] == heloc["id"]
        assert draw["amount_cents"] == 500_000

        # Read back updated HELOC.
        h2 = validate_success(
            api.get_heloc(
                heloc["id"], make_borrower_headers(borrower["id"]),
            ), 200,
        )
        assert h2["principal_balance_cents"] == 500_000
        assert h2["available_credit_cents"] == 1_500_000
        # PRD §3.3: "bumping the HELOC's version and refreshing
        # updated_at".
        assert_version_incremented_by_one(h2, heloc)
        assert_credit_conservation(h2)

    def test_below_minimum_draw_rejected(
        self, api,
    ):
        """PRD §3.3: "the Borrower (or a PlatformAdmin acting on their
        behalf) may take a draw by supplying an amount_cents of at
        least 10000 (one hundred dollars)".

        9999 must fail. PRD §2.12 says generic body-shape failures
        return ERR_VALIDATION_FAILED; the minimum is a domain-level
        amount constraint stated alongside the field. Either
        ERR_VALIDATION_FAILED (400) or ERR_INSUFFICIENT_AVAILABLE_CREDIT
        could be argued, but PRD §2.12 explicitly says "a cents-valued
        amount is supplied as a negative number" is the §2.12 path;
        a positive-but-too-small amount is a domain-business-amount
        check, which PRD does not name a specific error_id for.
        We assert a 4xx rejection but accept either error_id.
        """
        borrower, _, _, heloc = setup_active_heloc()
        resp = api.create_draw(
            heloc["id"],
            {"amount_cents": 9_999},
            make_borrower_headers(borrower["id"]),
        )
        assert resp.status_code in (400, 422), (
            f"below-minimum draw must be rejected with 4xx, got "
            f"{resp.status_code}"
        )

    def test_draw_amount_equals_available_credit_succeeds(self, api):
        """PRD §3.3: "The requested amount_cents must additionally be
        no greater than the HELOC's current available_credit_cents at
        request time, or the request is rejected with
        ERR_INSUFFICIENT_AVAILABLE_CREDIT."

        amount == available is "no greater than" → allowed.
        """
        borrower, _, _, heloc = setup_active_heloc(
            credit_limit_cents=1_000_000,
        )
        resp = api.create_draw(
            heloc["id"],
            create_draw_payload(amount_cents=1_000_000),
            make_borrower_headers(borrower["id"]),
        )
        validate_success(resp, 201)
        h2 = validate_success(
            api.get_heloc(
                heloc["id"], make_borrower_headers(borrower["id"]),
            ), 200,
        )
        assert h2["available_credit_cents"] == 0
        assert h2["principal_balance_cents"] == 1_000_000
        assert_credit_conservation(h2)


# ===========================================================================
# §3.3 Insufficient credit
# ===========================================================================
class TestInsufficientCredit:

    def test_amount_exceeds_available_credit_rejected(self, api):
        """PRD §3.3: "The requested amount_cents must additionally be
        no greater than the HELOC's current available_credit_cents at
        request time, or the request is rejected with
        ERR_INSUFFICIENT_AVAILABLE_CREDIT."
        """
        borrower, _, _, heloc = setup_active_heloc(
            credit_limit_cents=1_000_000,
        )
        resp = api.create_draw(
            heloc["id"],
            create_draw_payload(amount_cents=1_000_001),
            make_borrower_headers(borrower["id"]),
        )
        validate_error(
            resp, ApiErrorId.ERR_INSUFFICIENT_AVAILABLE_CREDIT.value,
        )

    def test_after_partial_draw_remaining_credit_enforced(self, api):
        """PRD §3.3: "The requested amount_cents must additionally be
        no greater than the HELOC's current available_credit_cents at
        request time".
        """
        borrower, _, _, heloc, _ = setup_active_heloc_with_balance(
            credit_limit_cents=1_000_000,
            draw_amount_cents=600_000,
        )
        # Now only 400_000 available.
        resp = api.create_draw(
            heloc["id"],
            create_draw_payload(amount_cents=400_001),
            make_borrower_headers(borrower["id"]),
        )
        validate_error(
            resp, ApiErrorId.ERR_INSUFFICIENT_AVAILABLE_CREDIT.value,
        )


# ===========================================================================
# §3.3 State-based rejections
# ===========================================================================
class TestDrawStateGates:

    def test_draw_on_default_heloc_returns_heloc_defaulted(self, api):
        """PRD §3.3: "an attempt against a DEFAULT HELOC is rejected
        with the specific ERR_HELOC_DEFAULTED".
        PRD §3.6: "Once a HELOC is in DEFAULT, no further Draw may be
        created against it — attempts return ERR_HELOC_DEFAULTED."
        """
        borrower, _, _, heloc, _ = setup_heloc_default_via_bankruptcy()
        assert heloc["status"] == "DEFAULT"
        resp = api.create_draw(
            heloc["id"],
            create_draw_payload(amount_cents=10_000),
            make_borrower_headers(borrower["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_HELOC_DEFAULTED.value)

    def test_draw_on_repay_heloc_returns_draw_period_ended(self, api):
        """PRD §3.3: "an attempt against a HELOC already rolled into
        REPAY is rejected with ERR_DRAW_PERIOD_ENDED".
        """
        borrower, _, _, heloc = setup_heloc_in_repay()
        assert heloc["status"] == "REPAY"
        resp = api.create_draw(
            heloc["id"],
            create_draw_payload(amount_cents=10_000),
            make_borrower_headers(borrower["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DRAW_PERIOD_ENDED.value)

    def test_draw_on_pending_heloc_returns_invalid_state(self, api):
        """PRD §3.3: "While the HELOC is in `DRAW`, the `Borrower` (or
        a `PlatformAdmin` acting on their behalf) may take a draw".
        PRD §2.10: "Only after existence is established does the
        server evaluate state preconditions".

        PRD names ERR_HELOC_DEFAULTED for DEFAULT, ERR_DRAW_PERIOD_ENDED
        for REPAY, and ERR_HELOC_CLOSED for CLOSED but does not pin an
        error_id for PENDING; the test therefore asserts only a 409
        state-class rejection.
        """
        borrower, _, _, heloc = setup_pending_heloc()
        resp = api.create_draw(
            heloc["id"],
            create_draw_payload(amount_cents=10_000),
            make_borrower_headers(borrower["id"]),
        )
        assert resp.status_code == 409, (
            f"draw on PENDING must be a 409 state error, got "
            f"{resp.status_code}"
        )


# ===========================================================================
# §3.3 Draws list endpoint — PRD §2.3 pagination + §3.3 ledger shape
# ===========================================================================
class TestDrawsList:

    def test_list_draws_returns_created_draws_with_pagination(self, api):
        """PRD §2.3: "Paginated responses include the fields `limit`,
        `offset`, `total_count`, and `has_more` inside the `meta`
        object of the envelope."
        PRD §3.3: "A successfully recorded draw is an immutable
        ledger entry containing the originating `heloc_id`, the
        `amount_cents`, and a server-clock `drawn_at` timestamp".

        Two created draws must appear in the listing, each carrying
        the PRD-required fields.
        """
        borrower, _, _, heloc, _draw1 = (
            setup_active_heloc_with_balance(draw_amount_cents=50_000)
        )
        # Add a second draw.
        api.create_draw(
            heloc["id"], create_draw_payload(amount_cents=70_000),
            make_borrower_headers(borrower["id"]),
        )
        resp = api.list_draws(
            heloc["id"], make_borrower_headers(borrower["id"]),
        )
        from test_helpers import validate_paginated
        data, meta = validate_paginated(resp)
        assert meta["total_count"] >= 2
        for draw in data:
            assert draw["heloc_id"] == heloc["id"]
            assert "amount_cents" in draw
            assert "drawn_at" in draw
