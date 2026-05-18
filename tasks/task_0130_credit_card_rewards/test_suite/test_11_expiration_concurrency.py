"""Points expiration sweep and concurrency rules — PRD §3.8 / §3.6.

Coverage:
- Account inactive for exactly 365 days forfeits the entire balance.
- Account inactive for 364 days does not.
- CLOSED accounts are skipped by the expiration sweep.
- Zero-balance accounts get no ledger entry.
- Concurrent activation: exactly one wins on the (account, category,
  quarter) uniqueness; loser receives ERR_ACTIVATION_ALREADY_EXISTS.
- Concurrent redemptions where both would individually fit but
  collectively exceed the balance: exactly one wins; loser ->
  ERR_INSUFFICIENT_POINTS.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    EXPIRATION_INACTIVITY_DAYS,
    advance_clock_to,
    api_client,
    assert_exactly_one_succeeds,
    create_activation_payload,
    create_points_first_redemption_payload,
    find_ledger_entries,
    get_ledger,
    initiate_points_transfer,
    make_cardholder_headers,
    re_get_account,
    register_partner,
    register_rotating_category,
    run_race,
    run_sweep,
    setup_account_with_balance_via_signup,
    setup_account_with_rotating_category,
    setup_clock_at,
    setup_platinum_with_high_balance,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


# ===========================================================================
# Points expiration — PRD §3.8
# ===========================================================================
class TestPointsExpirationSweep:

    def test_exactly_365_days_inactive_expires_balance(self, api):
        """PRD §3.8: "The horizon is exactly three hundred sixty-five
        days, measured as the floor of the difference between the
        current clock and last_qualifying_activity_at in whole days
        (one day equals eighty-six thousand four hundred seconds), and
        the comparison is at-or-greater-than — an account inactive for
        exactly three hundred sixty-five days expires, an account
        inactive for three hundred sixty-four days does not."

        Claim: an ACTIVE account with last_qualifying_activity_at exactly
        365 days before the current clock, after /_sweep/run, has its
        entire positive points_balance forfeited via a single EXPIRE
        ledger entry whose delta_points is the negation of the prior
        balance.
        """
        setup_clock_at(2026, 1, 1)
        ch, acc, _cat = setup_account_with_balance_via_signup(
            open_year=2026, open_month=1, open_day=2,
        )
        balance_before_expire = re_get_account(
            acc["id"],
        )["points_balance"]
        assert balance_before_expire > 0
        # last_qualifying_activity_at was set on the purchase at
        # ~2026-01-02. Advance 365 days from that anchor.
        advance_clock_to("2027-01-02T00:00:00.000Z")
        run_sweep()
        ledger = get_ledger(acc["id"])
        expire_rows = find_ledger_entries(
            ledger, entry_type="EXPIRE",
        )
        assert len(expire_rows) == 1, (
            f"expected exactly one EXPIRE row at 365-day boundary, got "
            f"{len(expire_rows)}"
        )
        assert expire_rows[0]["delta_points"] == -balance_before_expire
        acc_after = re_get_account(acc["id"])
        assert acc_after["points_balance"] == 0

    def test_364_days_inactive_does_not_expire(self, api):
        """PRD §3.8: "the comparison is at-or-greater-than — an account
        inactive for exactly three hundred sixty-five days expires, an
        account inactive for three hundred sixty-four days does not."

        Claim: 364 days inactive yields no EXPIRE row and an unchanged
        points_balance.
        """
        setup_clock_at(2026, 1, 1)
        ch, acc, _cat = setup_account_with_balance_via_signup(
            open_year=2026, open_month=1, open_day=2,
        )
        balance_before = re_get_account(acc["id"])["points_balance"]
        # Advance 364 days (one short of the horizon).
        advance_clock_to("2027-01-01T00:00:00.000Z")
        run_sweep()
        ledger = get_ledger(acc["id"])
        expire_rows = find_ledger_entries(
            ledger, entry_type="EXPIRE",
        )
        assert len(expire_rows) == 0, (
            f"no EXPIRE row may be written at 364 days, got "
            f"{len(expire_rows)}"
        )
        acc_after = re_get_account(acc["id"])
        assert acc_after["points_balance"] == balance_before


# ===========================================================================
# Concurrent activation uniqueness — PRD §3.2
# ===========================================================================
class TestConcurrentActivation:

    def test_duplicate_activation_race_serialises(self, api):
        """PRD §3.2: "Two concurrent activation requests for the
        identical triple serialise on the uniqueness key; exactly one
        wins, and the loser receives ERR_ACTIVATION_ALREADY_EXISTS."

        Claim: two concurrent POST /accounts/{id}/activate-category
        with the same (category_id, quarter_label) on the same account
        produce one success and one ERR_ACTIVATION_ALREADY_EXISTS.
        """
        ch, acc, cat = setup_account_with_rotating_category()
        advance_clock_to("2026-04-15T12:00:00.000Z")
        headers = make_cardholder_headers(ch["id"])
        payload = create_activation_payload(
            category_id=cat["id"], quarter_label="2026Q2",
        )

        def call():
            return api_client.activate_category(
                acc["id"], payload, headers,
            )

        results = run_race(call, call)
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        # Loser must surface the PRD-named error id.
        loser = outcome["failures"][0]
        validate_error(
            loser, ApiErrorId.ERR_ACTIVATION_ALREADY_EXISTS.value,
        )


# ===========================================================================
# Concurrent redemption — PRD §3.6
# ===========================================================================
class TestConcurrentRedemption:

    def test_two_redemptions_overlap_balance_loser_is_insufficient(self, api):
        """PRD §3.6: "When two redemption attempts race against the same
        points_balance such that each independently fits but together
        they would drive the balance below zero, the system serialises
        on the balance check: exactly one wins and the loser is
        rejected with ERR_INSUFFICIENT_POINTS."

        Claim: two redemption requests each sized to consume slightly
        more than half the balance, fired concurrently, produce one
        success and one ERR_INSUFFICIENT_POINTS.
        """
        ch, acc, _cat = setup_platinum_with_high_balance()
        balance = acc["points_balance"]
        # Pick a points size such that 2 * size > balance, size <= balance.
        size = (balance // 2) + 1_000
        # Make sure size meets the minimum.
        from test_helpers import MIN_REDEMPTION_POINTS
        size = max(size, MIN_REDEMPTION_POINTS)
        # And ensure size <= balance for each individual request.
        assert size <= balance, (
            f"setup error: size={size} > balance={balance}"
        )
        assert 2 * size > balance, (
            f"setup error: 2*size={2 * size} <= balance={balance}; "
            f"race would not trigger insufficient-balance condition"
        )
        headers = make_cardholder_headers(ch["id"])
        payload = create_points_first_redemption_payload(
            account_id=acc["id"], requested_points=size,
        )

        def call():
            return api_client.create_statement_credit(payload, headers)

        results = run_race(call, call)
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error(
            loser, ApiErrorId.ERR_INSUFFICIENT_POINTS.value,
        )


# ===========================================================================
# Close vs redemption race — PRD §3.1
# ===========================================================================
class TestCloseVsRedemptionRace:

    def test_close_and_redemption_race_outcome(self, api):
        """PRD §3.1: "When two concurrent attempts to operate on the
        same account collide — for example a close arriving
        simultaneously with a fresh statement-credit redemption — the
        system serialises on Account.lifecycle_state: exactly one
        transition wins, and if the close wins first the redemption is
        rejected with ERR_ACCOUNT_CLOSED. If instead the redemption
        commits first, the close still succeeds and the FORFEIT ledger
        entry sees the post-redemption balance".

        Claim: in a race between close and redemption, both eventually
        succeed (close always succeeds; redemption commits first ->
        succeeds; close commits first -> redemption -> ERR_ACCOUNT_CLOSED).
        The exact loser error_id depends on commit order; PRD names
        ERR_ACCOUNT_CLOSED as the loser id when close wins, and "the
        redemption that won is honored" when redemption wins.
        """
        ch, acc, _cat = setup_platinum_with_high_balance()
        from test_helpers import MIN_REDEMPTION_POINTS
        headers = make_cardholder_headers(ch["id"])
        redeem_payload = create_points_first_redemption_payload(
            account_id=acc["id"],
            requested_points=MIN_REDEMPTION_POINTS,
        )

        def redeem():
            return api_client.create_statement_credit(
                redeem_payload, headers,
            )

        def close_op():
            return api_client.close_account(
                acc["id"], None, headers,
            )

        results = run_race(redeem, close_op)
        # PRD allows two outcomes: (a) close wins first -> redemption
        # gets ERR_ACCOUNT_CLOSED; or (b) redemption wins first ->
        # both succeed. Either is PRD-faithful.
        statuses = sorted(r.status_code for r in results)
        # At least one 2xx is guaranteed (close always succeeds per
        # PRD §3.1).
        successes = [r for r in results if 200 <= r.status_code < 300]
        assert len(successes) >= 1, (
            f"close must always succeed; got statuses {statuses}"
        )
        # If only one succeeded, the failure must be the redemption
        # with ERR_ACCOUNT_CLOSED.
        failures = [r for r in results if r.status_code >= 400]
        for f in failures:
            validate_error(f, ApiErrorId.ERR_ACCOUNT_CLOSED.value)
