"""Subscription lifecycle: freeze/unfreeze cycle, cancel terminal state, and the
recurring-billing renewal and pack-expiry driver.
"""
from test_helpers import (
    validate_success, validate_error,
    make_member_headers,
    create_subscription_payload, create_freeze_payload,
    TEST_USERS,
)
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["admin_headers"]
MANAGER = TEST_USERS["manager_headers"]


# ─── Queue A: non_linear_state_machine (freeze/unfreeze cycle) ───────────────
def test_freeze_then_unfreeze_returns_to_active_with_grant(api):
    """PRD §3.4: "On freeze, the subscription moves to FROZEN, freeze_cycles_remaining is
    set to freeze_cycles, granted_credits_remaining is set to 0 because frozen cycles grant
    no credits, and the member's credit_balance is recomputed."
    PRD §3.4: "Either path moves the subscription from FROZEN to ACTIVE, sets
    freeze_cycles_remaining to 0, re-anchors cycle_anchor_at to the current clock and
    recomputes current_cycle_end_at, restores granted_credits_remaining to the plan's
    monthly_credit_grant, and recomputes the member's credit_balance."

    Design: Difficulty/non_linear_state_machine/subscription_freeze_unfreeze_cycle
    """
    plan = fx.create_plan(tier="PLUS", monthly_fee_cents=16900,
                          monthly_credit_grant=8, rollover_cap=4)
    location = fx.create_location()
    fx.set_clock("2026-06-01T00:00:00Z")
    member = fx.create_member(location["id"])
    sub = validate_success(api.create_subscription(
        member["id"], create_subscription_payload(plan["id"]),
        make_member_headers(member["id"])), 201)

    frozen = validate_success(api.freeze_subscription(
        sub["id"], create_freeze_payload(2), make_member_headers(member["id"])), 200)
    assert frozen["status"] == "FROZEN"
    assert frozen["granted_credits_remaining"] == 0, frozen

    back = validate_success(api.unfreeze_subscription(
        sub["id"], make_member_headers(member["id"])), 200)
    assert back["status"] == "ACTIVE"
    assert back["granted_credits_remaining"] == 8, back
    assert back["freeze_cycles_remaining"] == 0, back


def test_freeze_zeroes_member_credit_balance(api):
    """PRD §3.4: "On freeze, the subscription moves to FROZEN ... granted_credits_remaining
    is set to 0 because frozen cycles grant no credits, and the member's credit_balance is
    recomputed."
    PRD §3.6: "A member's credit_balance is reconciled as the subscription's
    granted_credits_remaining when the member has a subscription in ACTIVE or FROZEN status
    (and zero otherwise), plus the sum of remaining_credits across all of the member's credit
    packs whose status is ACTIVE."

    Design: Difficulty/non_linear_state_machine/subscription_freeze_unfreeze_cycle
    """
    plan = fx.create_plan(tier="PLUS", monthly_fee_cents=16900,
                          monthly_credit_grant=8, rollover_cap=4)
    location = fx.create_location()
    fx.set_clock("2026-06-01T00:00:00Z")
    member = fx.create_member(location["id"])
    sub = validate_success(api.create_subscription(
        member["id"], create_subscription_payload(plan["id"]),
        make_member_headers(member["id"])), 201)
    before = fx.get_member(member["id"])
    assert before["credit_balance"] == 8, before

    validate_success(api.freeze_subscription(
        sub["id"], create_freeze_payload(1), make_member_headers(member["id"])), 200)
    after = fx.get_member(member["id"])
    assert after["credit_balance"] == 0, after


# ─── Queue B: terminal state lockdown ───────────────────────────────────────
def test_cancelled_subscription_cannot_be_frozen(api):
    """PRD §3.4: "CANCELLED is terminal."
    PRD §3.4: "Freezing is permitted only while the subscription is ACTIVE".

    Design: Corner/state_machines/terminal_cancelled_subscription_cannot_freeze
    """
    plan = fx.create_plan(tier="PLUS", monthly_fee_cents=16900,
                          monthly_credit_grant=8, rollover_cap=4)
    location = fx.create_location()
    fx.set_clock("2026-06-01T00:00:00Z")
    member = fx.create_member(location["id"])
    sub = validate_success(api.create_subscription(
        member["id"], create_subscription_payload(plan["id"]),
        make_member_headers(member["id"])), 201)
    validate_success(api.cancel_subscription(sub["id"], make_member_headers(member["id"])), 200)

    res = api.freeze_subscription(
        sub["id"], create_freeze_payload(1), make_member_headers(member["id"]))
    validate_error(res, "ERR_INVALID_STATE")
    after = fx.get_subscription(sub["id"])
    assert after["status"] == "CANCELLED"


def test_duplicate_subscription_blocked(api):
    """PRD §3.4: "A member may hold only one live subscription at a time: starting a new
    subscription while a non-CANCELLED subscription already exists is rejected with
    ERR_DUPLICATE_SUBSCRIPTION (HTTP 409)."

    Design: Corner/validations/error_duplicate_subscription_blocked
    """
    plan = fx.create_plan(tier="PLUS", monthly_fee_cents=16900,
                          monthly_credit_grant=8, rollover_cap=4)
    location = fx.create_location()
    fx.set_clock("2026-06-01T00:00:00Z")
    member = fx.create_member(location["id"])
    validate_success(api.create_subscription(
        member["id"], create_subscription_payload(plan["id"]),
        make_member_headers(member["id"])), 201)

    res = api.create_subscription(
        member["id"], create_subscription_payload(plan["id"]),
        make_member_headers(member["id"]))
    validate_error(res, "ERR_DUPLICATE_SUBSCRIPTION")


def test_subscribe_with_missing_plan_reference(api):
    """PRD §2.7: "when a request body carries a foreign-key reference — such as plan_id,
    room_id, service_type_id, home_location_id, or location_id — and that reference does
    not resolve to an existing resource, the request is rejected with
    ERR_REFERENCE_NOT_FOUND (HTTP 404)."

    Design: Corner/validations/error_reference_not_found_bad_plan_on_subscribe
    """
    location = fx.create_location()
    member = fx.create_member(location["id"])
    res = api.create_subscription(
        member["id"],
        create_subscription_payload("00000000-0000-4000-8000-000000000000"),
        make_member_headers(member["id"]))
    validate_error(res, "ERR_REFERENCE_NOT_FOUND")


def test_upgrade_to_lower_fee_plan_rejected(api):
    """PRD §3.4: "The target plan's monthly_fee_cents must be strictly greater than the
    current plan's; an equal or lower fee is rejected with ERR_NOT_AN_UPGRADE (HTTP 409)."

    Design: Corner/validations/error_not_an_upgrade_to_lower_fee_plan
    """
    base = fx.create_plan(tier="BASE", monthly_fee_cents=9900,
                          monthly_credit_grant=4, rollover_cap=0)
    plus = fx.create_plan(tier="PLUS", monthly_fee_cents=16900,
                          monthly_credit_grant=8, rollover_cap=4)
    location = fx.create_location()
    fx.set_clock("2026-06-01T00:00:00Z")
    member = fx.create_member(location["id"])
    sub = validate_success(api.create_subscription(
        member["id"], create_subscription_payload(plus["id"]),
        make_member_headers(member["id"])), 201)

    from test_helpers import create_upgrade_payload
    res = api.upgrade_subscription(
        sub["id"], create_upgrade_payload(base["id"], sub["version"]),
        make_member_headers(member["id"]))
    validate_error(res, "ERR_NOT_AN_UPGRADE")
    after = fx.get_subscription(sub["id"])
    assert after["plan_id"] == plus["id"]


# ─── Queue B: scheduled / billing-driver actions ────────────────────────────
def test_billing_run_renews_active_subscription(api):
    """PRD §3.4: "For an ACTIVE subscription whose clock has reached or passed
    current_cycle_end_at, billing performs a renewal ... it appends a RENEWAL invoice for
    the plan's monthly_fee_cents in PAID status ... it replenishes granted_credits_remaining
    to the plan's monthly_credit_grant plus the carried-over credits".
    PRD §3.4: "it reports how many subscriptions were renewed, how many were unfrozen, and
    how many packs expired."

    Design: Corner/cross_cutting_complexity_layers/scheduled_billing_run_renews_active_subscription
    """
    plan = fx.create_plan(tier="BASE", monthly_fee_cents=9900,
                          monthly_credit_grant=4, rollover_cap=0)
    location = fx.create_location()
    fx.set_clock("2026-06-01T00:00:00Z")
    member = fx.create_member(location["id"])
    sub = validate_success(api.create_subscription(
        member["id"], create_subscription_payload(plan["id"]),
        make_member_headers(member["id"])), 201)
    fx.set_clock("2026-07-02T00:00:00Z")

    summary = fx.run_billing()
    assert summary["subscriptions_renewed"] == 1, summary

    invoices = fx.list_invoices(sub["id"])
    renewals = [i for i in invoices if i["kind"] == "RENEWAL"]
    assert len(renewals) == 1, invoices
    assert renewals[0]["amount_cents"] == 9900
    after = fx.get_subscription(sub["id"])
    assert after["granted_credits_remaining"] == 4, after


def test_billing_run_expires_old_pack(api):
    """PRD §3.6: "A pack moves from ACTIVE to EXPIRED when the billing driver runs and the
    clock has reached or passed the pack's expires_at: its remaining_credits is zeroed and
    the member's credit_balance is recomputed."
    PRD §3.6: "A credit pack is valid for 180 days from purchase, after which its remaining
    credits expire."

    Design: Corner/cross_cutting_complexity_layers/scheduled_billing_run_expires_old_pack
    """
    location = fx.create_location()
    fx.set_clock("2026-06-01T00:00:00Z")
    member = fx.create_member(location["id"])
    pack = fx.buy_pack(member["id"], 5, is_intro=False)
    fx.set_clock("2026-12-01T00:00:00Z")

    summary = fx.run_billing()
    assert summary["packs_expired"] == 1, summary
    after_pack = fx.get_credit_pack(pack["id"])
    assert after_pack["status"] == "EXPIRED"
    after_member = fx.get_member(member["id"])
    assert after_member["credit_balance"] == 0, after_member


def test_pack_refund_reconciles_member_balance(api):
    """PRD §3.6: "On refund the pack's remaining_credits is set to 0, its status moves from
    ACTIVE to REFUNDED, and the member's credit_balance is recomputed."
    PRD §3.6: "plus the sum of remaining_credits across all of the member's credit packs
    whose status is ACTIVE."

    Design: Corner/cross_cutting_complexity_layers/derived_balance_reconciles_after_pack_refund
    """
    location = fx.create_location()
    fx.set_clock("2026-06-01T00:00:00Z")
    member = fx.create_member(location["id"])
    pack = fx.buy_pack(member["id"], 5, is_intro=False)
    before = fx.get_member(member["id"])
    assert before["credit_balance"] == 5, before

    refunded = validate_success(api.refund_credit_pack(member["id"], pack["id"], MANAGER), 200)
    assert refunded["status"] == "REFUNDED"
    after = fx.get_member(member["id"])
    assert after["credit_balance"] == 0, after
