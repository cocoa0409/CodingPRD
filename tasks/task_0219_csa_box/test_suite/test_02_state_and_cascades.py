"""State-machine depth and transitive-cascade tests: cyclic box hold/release,
parallel subscription axes, the depth-3 cancel cascade, and the depth-2
work-share-credit cascade.

Covers difficulty rules non_linear_state_machine and transitive_cascade.
"""
from test_helpers import (
    api_client, get_success_data, validate_success,
    setup_confirmed_subscription, setup_confirmed_with_refund_hold,
    setup_confirmed_with_addon, setup_confirmed_working_share,
    setup_first_box_delivered,
    confirm_subscription, box_for_week, schedule_shift, complete_shift,
    create_vacation_hold_payload,
    TEST_USERS,
)

FM = TEST_USERS["farm_manager_headers"]


# ─── Rule 3: non_linear_state_machine ────────────────────────────────────────

def test_box_returns_to_scheduled_after_release(api):
    """PRD §3.7: "A `Member` may release an active hold, which returns the held box from `HELD` to `SCHEDULED` and moves the hold from `ACTIVE` to `RELEASED`; release is permitted only while the hold is `ACTIVE` and the current clock is still strictly before the held box's delivery date."

    Design: Difficulty/non_linear_state_machine/weekly_box_held_release_cycle
    """
    ctx = setup_confirmed_with_refund_hold(week_index=3, clock="2026-06-15T00:00:00Z")
    sub_id = ctx["subscription"]["id"]
    mh = ctx["member_headers"]
    box_id = ctx["box"]["id"]
    hold_id = ctx["hold"]["id"]

    # Box went SCHEDULED→HELD on placing; now release it back.
    released_hold = validate_success(api_client.release_vacation_hold(hold_id, mh), 200)
    assert released_hold["status"] == "RELEASED"

    box = validate_success(api_client.get_weekly_box(box_id, mh), 200)
    assert box["status"] == "SCHEDULED", (
        f"box expected SCHEDULED after release, got {box['status']}")


def test_held_box_is_held_before_release(api):
    """PRD §3.7: "Placing a hold advances the held box from `SCHEDULED` to `HELD`, and is permitted only when the box is currently `SCHEDULED` and the current clock is strictly before that box's delivery date".

    Design: Difficulty/non_linear_state_machine/weekly_box_held_release_cycle
    """
    ctx = setup_confirmed_with_refund_hold(week_index=3, clock="2026-06-15T00:00:00Z")
    mh = ctx["member_headers"]
    box = validate_success(api_client.get_weekly_box(ctx["box"]["id"], mh), 200)
    assert box["status"] == "HELD", f"box expected HELD after place, got {box['status']}"
    hold = validate_success(api_client.get_vacation_hold(ctx["hold"]["id"], mh), 200)
    assert hold["status"] == "ACTIVE"


def test_first_delivery_flips_both_axes(api):
    """PRD §3.6: "When the box being delivered is the *first* box of its subscription to reach `DELIVERED`, the subscription's billing axis flips from `CONFIRMED` to `ACTIVE` and, in the same step, its fulfillment axis flips from `NOT_STARTED` to `IN_SEASON`."

    Design: Difficulty/non_linear_state_machine/subscription_parallel_billing_and_fulfillment_axes
    """
    ctx = setup_first_box_delivered(clock_confirm="2026-06-15T00:00:00Z",
                                    clock_deliver="2026-07-01T08:00:00Z")
    sub = validate_success(api_client.get_subscription(ctx["subscription"]["id"], FM), 200)
    assert sub["billing_status"] == "ACTIVE", (
        f"billing expected ACTIVE after first delivery, got {sub['billing_status']}")
    assert sub["fulfillment_status"] == "IN_SEASON", (
        f"fulfillment expected IN_SEASON after first delivery, got {sub['fulfillment_status']}")


def test_axes_independent_before_first_delivery(api):
    """PRD §3.3: "A new subscription begins with its billing axis in `PENDING_PAYMENT` and its fulfillment axis in `NOT_STARTED`; its `season_price_cents` and `outstanding_balance_cents` both start at 0."
    PRD §3.6: "Delivery is where the two subscription axes wake up."

    Design: Difficulty/non_linear_state_machine/subscription_parallel_billing_and_fulfillment_axes
    """
    # After confirm but before any delivery: billing CONFIRMED, fulfillment NOT_STARTED.
    ctx = setup_confirmed_subscription(tier="BASELINE", base_price_cents=50000,
                                       week_count=12, clock="2026-06-15T00:00:00Z")
    sub = validate_success(api_client.get_subscription(ctx["subscription"]["id"], FM), 200)
    assert sub["billing_status"] == "CONFIRMED", (
        f"billing expected CONFIRMED post-confirm, got {sub['billing_status']}")
    assert sub["fulfillment_status"] == "NOT_STARTED", (
        f"fulfillment expected NOT_STARTED pre-delivery, got {sub['fulfillment_status']}")


# ─── Rule 4: transitive_cascade ──────────────────────────────────────────────

def test_cancel_depth3_cascade_box_hold_addon(api):
    """PRD §3.10: "First, every non-terminal weekly box (those in `SCHEDULED` or `HELD`) is moved to `SKIPPED`. Second, for each such box that was `HELD`, its covering vacation hold is released, moving that hold from `ACTIVE` to `RELEASED`. Third, every `ATTACHED` add-on attachment is detached, moving it to `DETACHED` and decrementing each affected add-on's `committed_count`."

    Design: Difficulty/transitive_cascade/cancel_cascades_boxes_holds_addons_depth3
    """
    # CONFIRMED sub with one ATTACHED add-on and a REFUND hold on box week 4.
    ctx = setup_confirmed_with_addon(kind="FLOWERS", weekly_price_cents=1000,
                                     weekly_supply_cap=20, clock="2026-06-15T00:00:00Z",
                                     base_price_cents=50000, week_count=12)
    sub_id = ctx["subscription"]["id"]
    mh = ctx["member_headers"]
    add_on_id = ctx["add_on"]["id"]
    sao_id = ctx["subscription_add_on"]["id"]

    box_w4 = box_for_week(sub_id, mh, 4)
    hold = get_success_data(api_client.create_vacation_hold(
        create_vacation_hold_payload(sub_id, box_w4["id"]), mh))

    # Trigger: cancel.
    validate_success(api_client.cancel_subscription(sub_id, mh), 200)

    # Hop 1: held box → SKIPPED.
    box = validate_success(api_client.get_weekly_box(box_w4["id"], mh), 200)
    assert box["status"] == "SKIPPED", f"hop1: box expected SKIPPED, got {box['status']}"
    # Hop 2: the box's hold released (caused by the box becoming SKIPPED on cancel).
    hold_after = validate_success(api_client.get_vacation_hold(hold["id"], mh), 200)
    assert hold_after["status"] == "RELEASED", (
        f"hop2: hold expected RELEASED, got {hold_after['status']}")
    # Hop 3: add-on detached and committed_count decremented to 0.
    sao = validate_success(api_client.get_subscription_add_on(sao_id, mh), 200)
    assert sao["status"] == "DETACHED", f"hop3: SAO expected DETACHED, got {sao['status']}"
    add_on = validate_success(api_client.get_add_on(add_on_id, FM), 200)
    assert add_on["committed_count"] == 0, (
        f"hop3: committed_count expected 0, got {add_on['committed_count']}")


def test_workshare_complete_depth2_credit_then_balance(api):
    """PRD §3.9: "the member's `wallet_credit_cents` is incremented by the earned credit, and the subscription's `outstanding_balance_cents` is recomputed with the now-available wallet credit applied."
    PRD §3.4: "determine the wallet credit to apply: take the smaller of the member's available `wallet_credit_cents` and the net-after-refunds amount floored at zero (so wallet credit is never applied against a negative net)."

    Design: Difficulty/transitive_cascade/workshare_complete_credit_balance_depth2
    """
    # SUSTAINER → season_price 50000 × 1.25 = 62500; 4h shift → 6000 credit.
    ctx = setup_confirmed_working_share(tier="SUSTAINER", base_price_cents=50000,
                                        share_size="LARGE", items_per_box=12,
                                        week_count=12)
    sub_id = ctx["subscription"]["id"]
    mh = ctx["member_headers"]
    shift = schedule_shift(sub_id, mh, "2026-08-02T09:00:00Z", 4)
    complete_shift(shift["id"])

    # Hop 1: wallet credited.
    member = validate_success(api_client.get_member(ctx["member"]["id"], FM), 200)
    assert member["wallet_credit_cents"] == 6000, (
        f"hop1: wallet expected 6000, got {member['wallet_credit_cents']}")
    # Hop 2: balance recomputed with wallet applied = 62500 − 6000 = 56500.
    sub = validate_success(api_client.get_subscription(sub_id, FM), 200)
    assert sub["outstanding_balance_cents"] == 56500, (
        f"hop2: outstanding expected 56500, got {sub['outstanding_balance_cents']}")


# ─── Second-instance coverage (distinct facets) ──────────────────────────────

def _ledger(subscription_id, headers):
    res = api_client.list_ledger_entries(subscription_id, headers, params={"limit": 100})
    return res.json().get("data", [])


def test_cancel_also_reconciles_season_and_site_counters(api):
    """PRD §3.10: "recomputes `outstanding_balance_cents`, decrements the season's
    `confirmed_share_count` by one and the site's `active_subscription_count` by
    one, and increments the subscription's `version`."

    Design: Difficulty/transitive_cascade/cancel_cascades_boxes_holds_addons_depth3
    """
    # A distinct facet of the same cancel cascade: the season/site denormalized
    # counters reconcile downward alongside the box/hold/add-on teardown.
    ctx = setup_confirmed_with_addon(kind="FLOWERS", weekly_price_cents=1000,
                                     weekly_supply_cap=20, clock="2026-06-15T00:00:00Z",
                                     base_price_cents=50000, week_count=12)
    sub_id = ctx["subscription"]["id"]
    mh = ctx["member_headers"]
    season_id = ctx["season"]["id"]
    site_id = ctx["site"]["id"]
    # Confirm side effects set the counters to 1.
    season_before = validate_success(api_client.get_season(season_id, FM), 200)
    assert season_before["confirmed_share_count"] == 1

    validate_success(api_client.cancel_subscription(sub_id, mh), 200)

    season_after = validate_success(api_client.get_season(season_id, FM), 200)
    site_after = validate_success(api_client.get_pickup_site(site_id, FM), 200)
    assert season_after["confirmed_share_count"] == 0, (
        f"season confirmed_share_count expected 0, got {season_after['confirmed_share_count']}")
    assert site_after["active_subscription_count"] == 0, (
        f"site active_subscription_count expected 0, got {site_after['active_subscription_count']}")


def test_workshare_complete_posts_credit_workshare_ledger(api):
    """PRD §3.9: "On completion, the cascade runs in order: the `credit_earned_cents`
    is computed, a `CREDIT_WORKSHARE` ledger entry is posted on the subscription,
    the member's `wallet_credit_cents` is incremented by the earned credit, and the
    subscription's `outstanding_balance_cents` is recomputed with the now-available
    wallet credit applied."

    Design: Difficulty/transitive_cascade/workshare_complete_credit_balance_depth2
    """
    # Distinct facet: the CREDIT_WORKSHARE ledger entry that mediates the cascade.
    ctx = setup_confirmed_working_share(tier="SUSTAINER", base_price_cents=50000,
                                        share_size="LARGE", items_per_box=12,
                                        week_count=12)
    sub_id = ctx["subscription"]["id"]
    mh = ctx["member_headers"]
    shift = schedule_shift(sub_id, mh, "2026-08-02T09:00:00Z", 4)
    complete_shift(shift["id"])

    entries = _ledger(sub_id, mh)
    ws = [e for e in entries if e["entry_type"] == "CREDIT_WORKSHARE"]
    assert ws, "expected a CREDIT_WORKSHARE ledger entry after shift completion"
    assert ws[0]["amount_cents"] == -6000, (
        f"CREDIT_WORKSHARE amount expected -6000 (credit stored negative), "
        f"got {ws[0]['amount_cents']}")
