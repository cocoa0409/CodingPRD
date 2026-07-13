"""Subscription lifecycle: win-back cycle, activation gating, renewal/win-back
timing, and change-tier optimistic concurrency.

Difficulty (queue A): win-back cycle CANCELED->ACTIVE; activation blocked by a
suspended publication. Corner (queue B): renew-before-period; reactivate after
win-back window; stale subscription version.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    make_member_headers,
    new_publication, new_tier, new_paid_subscriber, new_trialing_paid_subscriber,
    setup_publication_with_pro_balance, setup_canceled_pro_subscription,
    set_clock, reset_clock, sub_version,
)

ADMIN = TEST_USERS["admin_headers"]


# ---------------------------------------------------------------------------
# Difficulty A5 — win-back cycle: ACTIVE -> CANCELED -> ACTIVE
# ---------------------------------------------------------------------------

def test_winback_reactivation_returns_to_active(api):
    """PRD §3.5: "A successful reactivation moves the subscription from
    `CANCELED` back to `ACTIVE`, increments `reactivation_count` by one, sets
    `is_win_back` to true, clears `canceled_at` ..."

    Design: Difficulty/non_linear_state_machine/subscription_winback_cycle_canceled_back_to_active
    """
    bundle = setup_canceled_pro_subscription(api)
    member, sub = bundle["member"], bundle["subscription"]
    resp = api.reactivate_subscription(sub["id"], make_member_headers(member["id"]))
    updated = validate_success(resp, expected_status=200)
    assert updated["status"] == "ACTIVE"
    assert updated["reactivation_count"] == 1


def test_winback_reactivation_sets_win_back_flag(api):
    """PRD §3.5: "A successful reactivation moves the subscription from
    `CANCELED` back to `ACTIVE`, increments `reactivation_count` by one, sets
    `is_win_back` to true, clears `canceled_at` ..."

    Design: Difficulty/non_linear_state_machine/subscription_winback_cycle_canceled_back_to_active
    """
    bundle = setup_canceled_pro_subscription(api)
    member, sub = bundle["member"], bundle["subscription"]
    resp = api.reactivate_subscription(sub["id"], make_member_headers(member["id"]))
    updated = validate_success(resp, expected_status=200)
    assert updated["is_win_back"] is True


# ---------------------------------------------------------------------------
# Difficulty A13 — activation blocked by a suspended publication
# ---------------------------------------------------------------------------

def _trialing_sub_on_suspended_pub(api):
    pub = new_publication(api)
    pro = new_tier(api, pub["id"], tier_rank=2, monthly_price_cents=2500, name="Pro")
    t = new_trialing_paid_subscriber(api, pub["id"], pro["id"])
    api.suspend_publication(pub["id"], ADMIN)
    return pub, t


def test_activation_blocked_by_suspended_publication_error(api):
    """PRD §3.3: "A `SUCCEEDED` outcome on the `INITIAL` invoice — permitted only
    while the publication is `ACTIVE` — advances the subscription from
    `TRIALING` to `ACTIVE` ..."
    PRD §3.1: "while suspended, the publication blocks new payout requests and
    blocks subscriptions from transitioning into an active spell, surfacing
    `ERR_PUBLICATION_SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/subscription_activation_blocked_by_suspended_publication
    """
    _, t = _trialing_sub_on_suspended_pub(api)
    resp = api.simulate_payment(
        {"invoice_id": t["initial_invoice_id"], "outcome": "SUCCEEDED"}, ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_PUBLICATION_SUSPENDED.value)


def test_activation_blocked_leaves_subscription_trialing(api):
    """PRD §3.1: "while suspended, the publication blocks new payout requests and
    blocks subscriptions from transitioning into an active spell, surfacing
    `ERR_PUBLICATION_SUSPENDED`."
    PRD §3.3: "and stays `TRIALING` until that `INITIAL` invoice is paid."

    Design: Difficulty/cross_entity_state_dependency/subscription_activation_blocked_by_suspended_publication
    """
    _, t = _trialing_sub_on_suspended_pub(api)
    api.simulate_payment(
        {"invoice_id": t["initial_invoice_id"], "outcome": "SUCCEEDED"}, ADMIN
    )
    member = t["member"]
    sub = validate_success(
        api.get_subscription(t["subscription"]["id"], make_member_headers(member["id"])),
        expected_status=200,
    )
    assert sub["status"] == "TRIALING"


# ---------------------------------------------------------------------------
# Corner — renew before period end
# ---------------------------------------------------------------------------

def test_renew_before_period_end_rejected(api):
    """PRD §3.3: "An active subscription is **renewed** by a platform
    administrator or the creator, but only once the clock has reached or passed
    `current_period_end`; a premature attempt is rejected with
    `ERR_PERIOD_NOT_ENDED`."

    Design: Corner/state_machines/renew_before_period_end_returns_409
    """
    reset_clock(api)
    bundle = setup_publication_with_pro_balance(api)
    resp = api.renew_subscription(bundle["subscription"]["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_PERIOD_NOT_ENDED.value)


# ---------------------------------------------------------------------------
# Corner — reactivate after the win-back window has closed
# ---------------------------------------------------------------------------

def test_reactivate_after_winback_window_rejected(api):
    """PRD §3.5: "**Reactivation** is performed by the member or creator only
    while the subscription is `CANCELED`, only when the publication is `ACTIVE`,
    and only within the win-back window — that is, when the clock is at or before
    thirty days after `canceled_at`. A reactivation attempt after that window has
    closed is rejected with `ERR_WINBACK_WINDOW_EXPIRED`."

    Design: Corner/state_machines/reactivate_after_winback_window_returns_409
    """
    bundle = setup_canceled_pro_subscription(api)  # canceled at clock 2026-03-01
    member, sub = bundle["member"], bundle["subscription"]
    set_clock(api, "2026-05-01T00:00:00Z")  # > 30 days after cancel
    resp = api.reactivate_subscription(sub["id"], make_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_WINBACK_WINDOW_EXPIRED.value)


# ---------------------------------------------------------------------------
# Corner — stale subscription version on change-tier (OCC)
# ---------------------------------------------------------------------------

def test_change_tier_stale_subscription_version_rejected(api):
    """PRD §2.8: "If this value does not match the subscription's current
    `version` — because a prior change-tier has already superseded that base tier
    since the client last read the subscription — the request is rejected with
    `ERR_STALE_SUBSCRIPTION_VERSION` (HTTP 412). A successful change-tier
    increments the subscription's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/change_tier_stale_subscription_version_rejected
    """
    reset_clock(api)
    pub = new_publication(api, platform_fee_bps=1000)
    plus = new_tier(api, pub["id"], tier_rank=1, monthly_price_cents=1000, name="Plus")
    pro = new_tier(api, pub["id"], tier_rank=2, monthly_price_cents=2500, name="Pro")
    mx = new_tier(api, pub["id"], tier_rank=3, monthly_price_cents=4000, name="Max")
    bundle = new_paid_subscriber(api, pub["id"], plus["id"])
    member, sub = bundle["member"], bundle["subscription"]
    stale_v = sub_version(api, sub["id"], member["id"])
    # First change-tier applies and advances the version.
    validate_success(
        api.change_tier(
            sub["id"],
            {"new_tier_id": pro["id"], "expected_subscription_version": stale_v},
            make_member_headers(member["id"]),
        ),
        expected_status=200,
    )
    # Second change-tier reuses the now-stale version.
    resp = api.change_tier(
        sub["id"],
        {"new_tier_id": mx["id"], "expected_subscription_version": stale_v},
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_SUBSCRIPTION_VERSION.value)
