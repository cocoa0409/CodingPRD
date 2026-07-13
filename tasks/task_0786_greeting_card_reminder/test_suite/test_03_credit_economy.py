"""The card-credit economy: subscription grants (full vs prorated), credit
conservation across submit/cancel, insufficient-credit and stale-version guards
on submit, and immediate balance visibility.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    build_pipeline, set_clock, new_account, new_subscription, grant_credits,
    new_contact, new_card, new_order, account_version, account_balance, holder,
)


def test_mid_cycle_upgrade_grants_prorated_credits(api):
    """PRD §3.1: "The prorated grant is then the new tier's monthly credit count
    multiplied by that days-remaining figure, divided by the thirty-day period
    length, with the result rounded *up* to a whole number of credits."

    Design: Difficulty/dual_variant_calc/renewal_full_grant_vs_prorated_upgrade_diverges
    """
    set_clock("2026-03-01T00:00:00Z")
    account = new_account()
    sub = new_subscription(account["id"], "FREE")  # 0 credits, period ends 2026-03-31
    set_clock("2026-03-21T00:00:00Z")  # 10 days remain
    validate_success(api.change_tier(sub["id"], {"tier": "PRO"}, holder(account["id"])), 200)
    # ceil(12 * 10 / 30) = 4; FREE granted 0, so balance is exactly the prorated 4.
    assert account_balance(account["id"]) == 4


def test_new_subscription_grants_full_credits(api):
    """PRD §3.1: "Creating the subscription grants the tier's full monthly
    credits immediately: a `CreditTransaction` with reason `SUBSCRIPTION_GRANT`
    and a positive `delta` equal to the tier's monthly credits is written".

    Design: Difficulty/dual_variant_calc/renewal_full_grant_vs_prorated_upgrade_diverges
    """
    account = new_account()
    new_subscription(account["id"], "PRO")
    # The full new_or_renew grant is 12 — strictly more than the prorated upgrade (4).
    assert account_balance(account["id"]) == 12


def test_credit_conserved_across_submit_then_cancel(api):
    """PRD §2.6: "Credits are a conserved quantity: an `ORDER_HOLD` of minus one
    paired with a later `ORDER_REFUND` of plus one leaves the account's balance
    exactly where it started."

    Design: Difficulty/compensating_invariant/credit_conserved_across_submit_then_cancel
    """
    ctx = build_pipeline("submitted", tier="PRO")  # holds one credit: 12 -> 11
    assert account_balance(ctx["account_id"]) == 11
    validate_success(api.cancel_order(ctx["order_id"], holder(ctx["account_id"])), 200)
    assert account_balance(ctx["account_id"]) == 12, "refund restores the pre-submit balance"


def test_credit_refunded_on_cancel_from_proof_approved(api):
    """PRD §3.8: "Cancelling from `PENDING_PROOF`, `PROOF_APPROVED`, or
    `SCHEDULED` — states in which `credit_status` is `HELD` — refunds the held
    credit by moving `credit_status` from `HELD` to `REFUNDED`, writing a
    `CreditTransaction` with reason `ORDER_REFUND` and a `delta` of plus one".

    Design: Difficulty/compensating_invariant/credit_conserved_across_submit_then_cancel
    """
    ctx = build_pipeline("approved", tier="PRO")  # credit still HELD, balance 11
    validate_success(api.cancel_order(ctx["order_id"], holder(ctx["account_id"])), 200)
    assert account_balance(ctx["account_id"]) == 12
    order = validate_success(api.get_order(ctx["order_id"], holder(ctx["account_id"])), 200)
    assert order["credit_status"] == "REFUNDED"


def test_submit_with_zero_credits_rejected(api):
    """PRD §3.4: "the account must hold at least one credit, or it fails with
    `ERR_INSUFFICIENT_CREDITS`".

    Design: Corner/validations/submit_zero_credits_returns_insufficient_credits
    """
    account = new_account()  # no subscription -> zero credits
    contact = new_contact(account["id"], verified=True)
    card = new_card()
    order = new_order(account["id"], contact["id"], card["id"])
    version = account_version(account["id"])
    validate_error(
        api.submit_order(order["id"], {"expected_account_version": version}, holder(account["id"])),
        ApiErrorId.ERR_INSUFFICIENT_CREDITS.value,
    )


def test_submit_with_stale_account_version_rejected(api):
    """PRD §2.8: "If the account's current `version` has advanced since then —
    because another submit already held a credit, or because a credit adjustment
    or a subscription grant posted to the ledger — the caller's view is stale and
    the submit is rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/submit_stale_account_version_returns_412
    """
    account = new_account()
    grant_credits(account["id"], 2)
    contact = new_contact(account["id"], verified=True)
    card = new_card()
    order_a = new_order(account["id"], contact["id"], card["id"], message_text="a")
    order_b = new_order(account["id"], contact["id"], card["id"], message_text="b")
    ah = holder(account["id"])
    observed = account_version(account["id"])
    # First submit advances Account.version.
    validate_success(api.submit_order(order_a["id"], {"expected_account_version": observed}, ah), 200)
    # Second submit still presents the now-stale version.
    validate_error(
        api.submit_order(order_b["id"], {"expected_account_version": observed}, ah),
        ApiErrorId.ERR_STALE_ACCOUNT_VERSION.value,
    )


def test_balance_decrement_visible_immediately_after_submit(api):
    """PRD §3.4: "the system holds a credit by writing a `CreditTransaction` with
    reason `ORDER_HOLD` and a `delta` of minus one, recomputes the account's
    balance, increments the account's `version` by one".
    PRD §2.6: "it is recomputed on every ledger insert and is never negative."

    Design: Corner/consistency_model/credit_balance_visible_immediately_after_submit
    """
    ctx = build_pipeline("submitted", tier="PRO")  # PRO 12, then hold one
    assert account_balance(ctx["account_id"]) == 11, \
        "the held credit is visible immediately on the next read"
