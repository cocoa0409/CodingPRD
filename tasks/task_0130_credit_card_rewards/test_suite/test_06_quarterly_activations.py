"""Quarterly activation lifecycle and rotating-category earn —
PRD §3.2 / §3.4.

Coverage:
- Successful activation creates a QuarterlyActivation in ACTIVATED with
  derived window endpoints.
- Activating a non-ROTATING category -> ERR_CATEGORY_NOT_ACTIVATABLE.
- Activating outside the 14-day pre-window or after the window ->
  ERR_ACTIVATION_WINDOW_CLOSED.
- Duplicate triple (account, category, quarter_label) ->
  ERR_ACTIVATION_ALREADY_EXISTS.
- ROTATING_QUARTERLY purchase without activation falls back to BASE_BPS
  (1%).
- ROTATING_QUARTERLY purchase with active activation uses base_rate_bps.
- Sweep transitions ACTIVATED -> EXPIRED past activation_window_end.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    BASE_BPS,
    activate_category,
    advance_clock_to,
    assert_quarterly_activation,
    create_activation_payload,
    get_account_activations,
    make_cardholder_headers,
    post_purchase,
    re_get_transaction,
    register_fixed_bonus_category,
    register_rotating_category,
    run_sweep,
    setup_account_with_fixed_bonus_category,
    setup_account_with_rotating_category,
    setup_clock_at,
    validate_error,
    validate_success,
)


# ===========================================================================
# Activation creation — PRD §3.2
# ===========================================================================
class TestActivationCreation:

    def test_activation_creates_activated_row_with_derived_window(self, api):
        """PRD §3.2: "On success, the server creates the activation in
        ACTIVATED status, derives activation_window_start as UTC
        midnight of the first day of the named quarter, derives
        activation_window_end as UTC midnight of the first day of the
        following quarter, and records activated_at as the current
        clock instant."

        Claim: a Cardholder activation for 2026Q2 returns ACTIVATED
        with window_start=2026-04-01T00:00:00Z, window_end=
        2026-07-01T00:00:00Z, and a populated activated_at.
        """
        ch, acc, cat = setup_account_with_rotating_category()
        # Clock at 2026-04-15 is well inside Q2.
        advance_clock_to("2026-04-15T12:00:00.000Z")
        act = activate_category(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"], quarter_label="2026Q2",
        )
        assert_quarterly_activation(act)
        assert act["status"] == "ACTIVATED"
        assert act["quarter_label"] == "2026Q2"
        assert act["activation_window_start"].startswith(
            "2026-04-01T00:00:00",
        )
        assert act["activation_window_end"].startswith(
            "2026-07-01T00:00:00",
        )

    def test_activate_non_rotating_returns_not_activatable(self, api):
        """PRD §3.2: "the referenced category has category_type equal
        to ROTATING_QUARTERLY (otherwise ERR_CATEGORY_NOT_ACTIVATABLE)".

        Claim: activating a FIXED_BONUS category ->
        ERR_CATEGORY_NOT_ACTIVATABLE.
        """
        ch, acc, cat = setup_account_with_fixed_bonus_category()
        advance_clock_to("2026-04-15T12:00:00.000Z")
        resp = api.activate_category(
            acc["id"],
            create_activation_payload(
                category_id=cat["id"], quarter_label="2026Q2",
            ),
            make_cardholder_headers(ch["id"]),
        )
        validate_error(
            resp, ApiErrorId.ERR_CATEGORY_NOT_ACTIVATABLE.value,
        )

    def test_activate_more_than_fourteen_days_early_rejected(self, api):
        """PRD §3.2: "the current logical clock is strictly before that
        quarter's activation_window_end and at-or-after a point fourteen
        days before activation_window_start (otherwise
        ERR_ACTIVATION_WINDOW_CLOSED, covering both an already-ended
        quarter and an activation attempt more than fourteen days in
        advance of the quarter's start)".

        Claim: trying to activate Q2 (start 2026-04-01) more than 14
        days early (i.e., on 2026-03-17 — 15 days before) is rejected
        with ERR_ACTIVATION_WINDOW_CLOSED.
        """
        ch, acc, cat = setup_account_with_rotating_category()
        advance_clock_to("2026-03-17T00:00:00.000Z")
        resp = api.activate_category(
            acc["id"],
            create_activation_payload(
                category_id=cat["id"], quarter_label="2026Q2",
            ),
            make_cardholder_headers(ch["id"]),
        )
        validate_error(
            resp, ApiErrorId.ERR_ACTIVATION_WINDOW_CLOSED.value,
        )

    def test_activate_after_window_end_rejected(self, api):
        """PRD §3.2: "covering both an already-ended quarter and an
        activation attempt more than fourteen days in advance of the
        quarter's start".

        Claim: trying to activate Q2 once the clock has moved into Q3
        (i.e., on 2026-07-01 — Q2 end) is rejected with
        ERR_ACTIVATION_WINDOW_CLOSED.
        """
        ch, acc, cat = setup_account_with_rotating_category()
        # Q2 ends at exactly 2026-07-01T00:00:00Z; the comparison is
        # strict so anywhere at-or-after is rejected.
        advance_clock_to("2026-07-01T00:00:00.000Z")
        resp = api.activate_category(
            acc["id"],
            create_activation_payload(
                category_id=cat["id"], quarter_label="2026Q2",
            ),
            make_cardholder_headers(ch["id"]),
        )
        validate_error(
            resp, ApiErrorId.ERR_ACTIVATION_WINDOW_CLOSED.value,
        )

    def test_duplicate_activation_rejected(self, api):
        """PRD §3.2: "no QuarterlyActivation already exists with the
        same account_id, category_id, and quarter_label (otherwise
        ERR_ACTIVATION_ALREADY_EXISTS)".

        Claim: a second activation for the identical triple returns
        ERR_ACTIVATION_ALREADY_EXISTS.
        """
        ch, acc, cat = setup_account_with_rotating_category()
        advance_clock_to("2026-04-15T12:00:00.000Z")
        # First activation succeeds.
        activate_category(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"], quarter_label="2026Q2",
        )
        # Second activation for the same (account, category, quarter)
        # triple is rejected.
        resp = api.activate_category(
            acc["id"],
            create_activation_payload(
                category_id=cat["id"], quarter_label="2026Q2",
            ),
            make_cardholder_headers(ch["id"]),
        )
        validate_error(
            resp, ApiErrorId.ERR_ACTIVATION_ALREADY_EXISTS.value,
        )


# ===========================================================================
# Rotating-category earn semantics — PRD §3.2 / §3.4
# ===========================================================================
class TestRotatingCategoryEarn:

    def test_rotating_without_activation_falls_back_to_one_percent(self, api):
        """PRD §3.2: "Categories of type ROTATING_QUARTERLY earn at
        base_rate_bps only inside a quarter for which the account has
        an active QuarterlyActivation; outside that window, they earn
        at the platform fallback rate of one hundred basis points,
        equivalent to one percent."
        PRD §3.4 step one: "otherwise the category rate falls back to
        the platform fallback of one hundred basis points (one percent)".

        Claim: 20,000-cent PURCHASE on a ROTATING category without
        activation, on STANDARD tier, yields floor(20000 *
        floor(100*10000/10000) / 10000) = 200 points (1%).
        """
        ch, acc, cat = setup_account_with_rotating_category(
            base_rate_bps=500,
        )
        advance_clock_to("2026-04-15T12:00:00.000Z")
        txn = post_purchase(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"], amount_cents=20_000,
        )
        # floor(20000 * 100 / 10000) = 200 points at fallback.
        assert txn["points_provisional"] == 200, (
            f"unactivated rotating must fall back to 1% (200 points), "
            f"got {txn['points_provisional']}"
        )

    def test_rotating_with_activation_uses_declared_rate(self, api):
        """PRD §3.2: "Categories of type ROTATING_QUARTERLY earn at
        base_rate_bps only inside a quarter for which the account has
        an active QuarterlyActivation".

        Claim: 20,000-cent PURCHASE on a ROTATING category whose
        activation is live yields 5% (1000 points) for category 500
        bps on STANDARD.
        """
        ch, acc, cat = setup_account_with_rotating_category(
            base_rate_bps=500,
        )
        advance_clock_to("2026-04-15T12:00:00.000Z")
        activate_category(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"], quarter_label="2026Q2",
        )
        txn = post_purchase(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"], amount_cents=20_000,
        )
        # floor(20000 * 500 / 10000) = 1000 points at declared rate.
        assert txn["points_provisional"] == 1000


# ===========================================================================
# Sweep transitions ACTIVATED -> EXPIRED — PRD §3.2 / §3.8
# ===========================================================================
class TestActivationExpiry:

    def test_sweep_after_window_end_expires_activation(self, api):
        """PRD §3.2: "An activation persists in ACTIVATED until the
        sweep transition fires: when the logical clock advances past
        activation_window_end and a PlatformAdmin runs the periodic
        sweep, every QuarterlyActivation whose activation_window_end is
        at-or-before the current clock advances to EXPIRED."

        Claim: after advancing past 2026-07-01T00:00:00Z and running
        sweep, a Q2 activation moves to EXPIRED.
        """
        ch, acc, cat = setup_account_with_rotating_category()
        advance_clock_to("2026-04-15T12:00:00.000Z")
        activate_category(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"], quarter_label="2026Q2",
        )
        # Advance past Q2 end and run sweep.
        advance_clock_to("2026-07-02T00:00:00.000Z")
        run_sweep()
        acts = get_account_activations(
            acc["id"], quarter_label="2026Q2",
        )
        assert len(acts) == 1
        assert acts[0]["status"] == "EXPIRED"

    def test_after_expiry_subsequent_posts_fall_back(self, api):
        """PRD §3.2: "Expiration is forward-only: it does not
        retroactively re-rate transactions that posted while the
        activation was live; it simply means that any further purchases
        against the same (account, category) revert to the fallback
        one-percent rate exactly as if no activation had ever existed
        for that quarter."

        Claim: after sweep expires the activation, a NEW purchase
        against the same (account, category) — albeit posted in a new
        quarter where no activation exists — earns at 1% fallback.
        """
        ch, acc, cat = setup_account_with_rotating_category(
            base_rate_bps=500,
        )
        advance_clock_to("2026-04-15T12:00:00.000Z")
        activate_category(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"], quarter_label="2026Q2",
        )
        # Move into Q3 and sweep so the Q2 activation expires.
        advance_clock_to("2026-07-02T00:00:00.000Z")
        run_sweep()
        # New purchase in Q3 against the same rotating category —
        # falls back to 1%.
        txn = post_purchase(
            cardholder_id=ch["id"], account_id=acc["id"],
            category_id=cat["id"], amount_cents=10_000,
        )
        # 10000 * 100 / 10000 = 100 points at the 1% fallback.
        assert txn["points_provisional"] == 100
