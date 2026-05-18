"""Optimistic concurrency control and concurrency races whose outcomes
the PRD explicitly defines.

Covers PRD §2.5 (OCC version check) and the explicit concurrency
guarantees stated in §3.2, §3.3, §3.5, and §3.9. Concurrent operations
whose outcome PRD leaves underdetermined are NOT tested here — see the
Silence patterns in the test-generator skill.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    activate_heloc_payload,
    api_client,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    create_draw_payload,
    create_payment_payload,
    create_rate_reset_payload,
    get_heloc,
    make_borrower_headers,
    post_draw,
    post_payment,
    post_rate_reset,
    run_race,
    setup_active_heloc,
    setup_active_heloc_with_balance,
    setup_pending_heloc,
    TEST_USERS,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


# ===========================================================================
# §2.5 Optimistic concurrency control: stale version → ERR_VERSION_CONFLICT
# ===========================================================================
class TestOptimisticConcurrencyControl:

    def test_payment_with_stale_version_rejected(self, api):
        """PRD §2.5: "When version is supplied, the server compares it
        to the HELOC's persisted version; if the two are not equal
        the request is rejected with ERR_VERSION_CONFLICT."
        """
        borrower, _, _, heloc, _ = setup_active_heloc_with_balance(
            draw_amount_cents=200_000,
        )
        # heloc was returned from setup_active_heloc; the draw bumped
        # version. Re-fetch to know the current version.
        h_now = get_heloc(
            heloc["id"], make_borrower_headers(borrower["id"]),
        )
        stale = h_now["version"] - 1  # known-stale
        resp = api.create_payment(
            heloc["id"],
            create_payment_payload(amount_cents=10_000, version=stale),
            make_borrower_headers(borrower["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_VERSION_CONFLICT.value)

    def test_payment_with_matching_version_succeeds(self, api):
        """PRD §2.5: "When version is supplied, the server compares it
        to the HELOC's persisted version; if the two are not equal
        the request is rejected with ERR_VERSION_CONFLICT."

        Equal version → no rejection, request proceeds.
        """
        borrower, _, _, heloc, _ = setup_active_heloc_with_balance(
            draw_amount_cents=200_000,
        )
        # accrue interest so payment-minimum is non-trivially > 0 in
        # DRAW (accrued = 0 means minimum=0, so amount=1 satisfies
        # floor).
        from test_helpers import advance_clock_days, run_billing_cycle_sweep
        advance_clock_days(days=30)
        run_billing_cycle_sweep()
        h_now = get_heloc(
            heloc["id"], make_borrower_headers(borrower["id"]),
        )
        resp = api.create_payment(
            heloc["id"],
            create_payment_payload(
                amount_cents=h_now["accrued_interest_cents"],
                version=h_now["version"],
            ),
            make_borrower_headers(borrower["id"]),
        )
        validate_success(resp, 201)

    def test_draw_with_stale_version_rejected(self, api):
        """PRD §2.5: "This optional field is accepted on activation,
        draws, payments, rate resets, and close."
        """
        borrower, _, _, heloc = setup_active_heloc(
            credit_limit_cents=1_000_000,
        )
        resp = api.create_draw(
            heloc["id"],
            create_draw_payload(
                amount_cents=10_000,
                version=heloc["version"] + 99,
            ),
            make_borrower_headers(borrower["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_VERSION_CONFLICT.value)

    def test_close_with_stale_version_rejected(self, api):
        """PRD §2.5: "This optional field is accepted on activation,
        draws, payments, rate resets, and close."
        """
        borrower, _, _, heloc = setup_active_heloc()
        resp = api.close_heloc(
            heloc["id"], make_borrower_headers(borrower["id"]),
            {"version": heloc["version"] + 99},
        )
        validate_error(resp, ApiErrorId.ERR_VERSION_CONFLICT.value)

    def test_omitting_version_skips_check(self, api):
        """PRD §2.5: "When version is omitted from the request body,
        no concurrency check is performed and the mutation proceeds
        against whatever the current state happens to be."
        """
        borrower, _, _, heloc = setup_active_heloc()
        # No version field at all.
        resp = api.create_draw(
            heloc["id"], {"amount_cents": 50_000},
            make_borrower_headers(borrower["id"]),
        )
        validate_success(resp, 201)


# ===========================================================================
# §3.2 Two concurrent activations of same PENDING — exactly one wins
# ===========================================================================
class TestActivationRace:

    def test_two_simultaneous_activations_exactly_one_succeeds(
        self, api, originator_headers,
    ):
        """PRD §3.2: "If two activations of the same PENDING HELOC are
        submitted simultaneously, the first to commit wins; the loser
        observes that the HELOC is no longer in PENDING and is
        rejected with ERR_INVALID_STATE."
        """
        _, _, _, heloc = setup_pending_heloc()
        results = run_race(
            lambda: api.activate_heloc(
                heloc["id"],
                activate_heloc_payload(prime_rate_bps=500),
                originator_headers,
            ),
            lambda: api.activate_heloc(
                heloc["id"],
                activate_heloc_payload(prime_rate_bps=500),
                originator_headers,
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        # PRD pins the loser's error.
        body = loser.json()
        assert body["data"]["error_id"] == "ERR_INVALID_STATE", (
            f"PRD §3.2 pins the loser of concurrent activations to "
            f"ERR_INVALID_STATE; got {body['data']['error_id']!r}"
        )


# ===========================================================================
# §3.3 Two concurrent draws exceeding available credit together
# ===========================================================================
class TestDrawRace:

    def test_two_simultaneous_draws_exceeding_together_one_rejected(
        self, api,
    ):
        """PRD §3.3: "When two draws on the same DRAW HELOC arrive
        simultaneously, where each draw alone would fit within
        available_credit_cents but together they would exceed it,
        exactly one draw succeeds; the second is rejected with
        ERR_INSUFFICIENT_AVAILABLE_CREDIT."
        """
        borrower, _, _, heloc = setup_active_heloc(
            credit_limit_cents=1_000_000,
        )
        # Each draw is 700k; together 1.4M > 1M.
        hdrs = make_borrower_headers(borrower["id"])
        results = run_race(
            lambda: api.create_draw(
                heloc["id"],
                create_draw_payload(amount_cents=700_000), hdrs,
            ),
            lambda: api.create_draw(
                heloc["id"],
                create_draw_payload(amount_cents=700_000), hdrs,
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        body = loser.json()
        assert (
            body["data"]["error_id"]
            == "ERR_INSUFFICIENT_AVAILABLE_CREDIT"
        ), (
            f"PRD §3.3 pins the loser to ERR_INSUFFICIENT_AVAILABLE_"
            f"CREDIT; got {body['data']['error_id']!r}"
        )


# ===========================================================================
# §3.9 close vs payment race
# ===========================================================================
class TestCloseVsPaymentRace:

    def test_close_vs_payment_exactly_one_succeeds_with_pinned_errors(
        self, api,
    ):
        """PRD §3.9: "When a close commits simultaneously with a
        payment that would push the balance back above zero, exactly
        one operation succeeds: if the close commits first, the
        payment is rejected with ERR_HELOC_CLOSED; if the payment
        commits first, the close is rejected with ERR_BALANCE_NOT_ZERO."

        Setup: HELOC with zero balance (so close-precheck would see
        zero). Concurrent payment of >0 vs concurrent close → exactly
        one succeeds, and the loser's error is one of the two PRD-
        pinned codes.
        """
        borrower, _, _, heloc = setup_active_heloc()
        bh = make_borrower_headers(borrower["id"])
        results = run_race(
            lambda: api.close_heloc(heloc["id"], bh, {}),
            # Payment 10_000 with no accrued interest will be a
            # principal-component payment that drives the balance
            # back above zero from zero — exactly the race PRD §3.9
            # describes. minimum_payment_due in DRAW is
            # accrued_interest_cents == 0 so amount=10_000 satisfies
            # the floor.
            lambda: api.create_payment(
                heloc["id"],
                create_payment_payload(amount_cents=10_000), bh,
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        body = loser.json()
        # PRD pins both pairwise outcomes — accept either.
        assert body["data"]["error_id"] in {
            "ERR_HELOC_CLOSED", "ERR_BALANCE_NOT_ZERO",
        }, (
            f"PRD §3.9 pins loser to ERR_HELOC_CLOSED or "
            f"ERR_BALANCE_NOT_ZERO; got {body['data']['error_id']!r}"
        )
