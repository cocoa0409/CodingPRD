"""Calculation depth tests: sliding-scale pricing, outstanding-balance variants,
working-share daily-cap credit, and per-week hold-refund allocation.

Covers difficulty rules dual_variant_calc and combinatorial_formula.
"""
from test_helpers import (
    api_client, get_success_data, validate_success,
    setup_pending_subscription, setup_confirmed_subscription,
    setup_confirmed_working_share, add_add_on, register_member, set_clock,
    confirm_subscription, box_for_week, list_weekly_boxes, schedule_shift, complete_shift,
    make_member_headers,
    create_subscription_add_on_payload, create_vacation_hold_payload,
    create_subscription_payload, create_work_share_shift_payload,
    TEST_USERS,
)

FM = TEST_USERS["farm_manager_headers"]
DC = TEST_USERS["delivery_coordinator_headers"]


def _ledger(subscription_id, headers):
    res = api_client.list_ledger_entries(subscription_id, headers, params={"limit": 100})
    return get_success_data_list(res)


def get_success_data_list(res):
    body = res.json()
    return body.get("data", [])


# ─── Rule 1: dual_variant_calc ───────────────────────────────────────────────

def test_outstanding_balance_provisional_before_confirm(api):
    """PRD §3.4: "Before confirmation — while `billing_status` is `PENDING_PAYMENT`, before any `CHARGE_SEASON` has been posted — the gross charges exclude the season charge, so the balance reflects only any add-ons attached so far; this provisional balance is genuinely lower than the finalized one."
    PRD §3.5: "If no weekly boxes exist yet because the subscription is still `PENDING_PAYMENT` and has not been confirmed, the remaining weeks instead equal the season's `week_count`."

    Design: Difficulty/dual_variant_calc/outstanding_balance_provisional_vs_finalized
    """
    # OPEN season, MEDIUM share 50000, BASELINE member, 12 weeks; add-on 800/wk.
    base = setup_pending_subscription(tier="BASELINE", base_price_cents=50000, week_count=12)
    add_on = add_add_on(base["season"]["id"], kind="EGGS",
                        weekly_price_cents=800, weekly_supply_cap=50)
    sub_id = base["subscription"]["id"]
    mh = base["member_headers"]
    # Attach the add-on while still PENDING_PAYMENT (remaining_weeks = week_count 12).
    get_success_data(api_client.create_subscription_add_on(
        create_subscription_add_on_payload(sub_id, add_on["id"]), mh))

    sub = validate_success(api_client.get_subscription(sub_id, FM), 200)
    assert sub["billing_status"] == "PENDING_PAYMENT"
    # Provisional balance = add-on only = 800 × 12 = 9600 (no CHARGE_SEASON yet).
    assert sub["outstanding_balance_cents"] == 9600, (
        f"provisional balance expected 9600, got {sub['outstanding_balance_cents']}")


def test_outstanding_balance_finalized_after_confirm(api):
    """PRD §3.4: "Once `billing_status` is `CONFIRMED` or `ACTIVE`, the gross charges include `CHARGE_SEASON`, producing the higher, finalized balance for the same add-on state."
    PRD §3.3: "A `CHARGE_SEASON` ledger entry is posted for that amount."

    Design: Difficulty/dual_variant_calc/outstanding_balance_provisional_vs_finalized
    """
    base = setup_pending_subscription(tier="BASELINE", base_price_cents=50000, week_count=12)
    add_on = add_add_on(base["season"]["id"], kind="EGGS",
                        weekly_price_cents=800, weekly_supply_cap=50)
    sub_id = base["subscription"]["id"]
    mh = base["member_headers"]
    get_success_data(api_client.create_subscription_add_on(
        create_subscription_add_on_payload(sub_id, add_on["id"]), mh))

    confirmed = confirm_subscription(base["season"]["id"], sub_id)
    # Finalized balance = season 50000 + add-on 9600 = 59600.
    assert confirmed["outstanding_balance_cents"] == 59600, (
        f"finalized balance expected 59600, got {confirmed['outstanding_balance_cents']}")


def test_hold_refund_early_week_carries_extra_cent(api):
    """PRD §3.7: "a held box whose `week_index` is less than or equal to the remainder is refunded the base amount plus one cent, while a held box whose `week_index` is greater than the remainder is refunded exactly the base amount."
    PRD §3.7: "In `REFUND` mode the system posts a `CREDIT_HOLD_REFUND` ledger entry for one week's pro-rata share value and then recomputes the subscription's `outstanding_balance_cents`."

    Design: Difficulty/dual_variant_calc/hold_refund_value_early_vs_late_week
    """
    # season_price 50000 over 12 weeks: base = 4166, remainder = 8. Week 1 ≤ 8 → 4167.
    ctx = setup_confirmed_subscription(tier="BASELINE", base_price_cents=50000,
                                       week_count=12, clock="2026-06-15T00:00:00Z")
    sub_id = ctx["subscription"]["id"]
    mh = ctx["member_headers"]
    box_w1 = box_for_week(sub_id, mh, 1)
    get_success_data(api_client.create_vacation_hold(
        create_vacation_hold_payload(sub_id, box_w1["id"]), mh))

    entries = _ledger(sub_id, mh)
    refunds = [e for e in entries if e["entry_type"] == "CREDIT_HOLD_REFUND"]
    assert len(refunds) == 1, f"expected one CREDIT_HOLD_REFUND, got {len(refunds)}"
    assert refunds[0]["amount_cents"] == -4167, (
        f"week-1 refund expected -4167, got {refunds[0]['amount_cents']}")


def test_hold_refund_late_week_is_floor(api):
    """PRD §3.7: "a held box whose `week_index` is greater than the remainder is refunded exactly the base amount."
    PRD §3.7: "Divide `season_price_cents` by the season's `week_count` using integer division (discarding any fractional part) to get a base per-week amount, and let the remainder be `season_price_cents` minus that base amount times `week_count`."

    Design: Difficulty/dual_variant_calc/hold_refund_value_early_vs_late_week
    """
    # Week 12 > remainder 8 → floor 4166.
    ctx = setup_confirmed_subscription(tier="BASELINE", base_price_cents=50000,
                                       week_count=12, clock="2026-06-15T00:00:00Z")
    sub_id = ctx["subscription"]["id"]
    mh = ctx["member_headers"]
    box_w12 = box_for_week(sub_id, mh, 12)
    get_success_data(api_client.create_vacation_hold(
        create_vacation_hold_payload(sub_id, box_w12["id"]), mh))

    entries = _ledger(sub_id, mh)
    refunds = [e for e in entries if e["entry_type"] == "CREDIT_HOLD_REFUND"]
    assert len(refunds) == 1, f"expected one CREDIT_HOLD_REFUND, got {len(refunds)}"
    assert refunds[0]["amount_cents"] == -4166, (
        f"week-12 refund expected -4166, got {refunds[0]['amount_cents']}")


# ─── Rule 2: combinatorial_formula ───────────────────────────────────────────

def test_workshare_credit_straddles_daily_cap(api):
    """PRD §3.9: "The creditable hours are this shift's `hours`, but no more than the daily cap of 6 hours minus those prior same-date hours, and never less than zero. The earned credit is the creditable hours multiplied by 1500 cents per hour, rounded half-up to a whole number of cents, and stored as `credit_earned_cents`."
    PRD §3.9: "On completion, the cascade runs in order: the `credit_earned_cents` is computed, a `CREDIT_WORKSHARE` ledger entry is posted on the subscription, the member's `wallet_credit_cents` is incremented by the earned credit, and the subscription's `outstanding_balance_cents` is recomputed with the now-available wallet credit applied."

    Design: Difficulty/combinatorial_formula/workshare_credit_straddles_daily_cap_mode_a
    """
    ctx = setup_confirmed_working_share(tier="BASELINE", base_price_cents=30000,
                                        share_size="SMALL", items_per_box=5)
    sub_id = ctx["subscription"]["id"]
    mh = ctx["member_headers"]
    # Same date 2026-08-01: a 4h shift (earlier created_at) then a 3h shift.
    shift_a = schedule_shift(sub_id, mh, "2026-08-01T09:00:00Z", 4)
    shift_b = schedule_shift(sub_id, mh, "2026-08-01T13:00:00Z", 3)

    done_a = complete_shift(shift_a["id"])
    done_b = complete_shift(shift_b["id"])

    # 4h fully under cap → 6000; 3h with 4 prior → min(3, 6-4)=2h → 3000.
    assert done_a["credit_earned_cents"] == 6000, (
        f"shift A credit expected 6000, got {done_a['credit_earned_cents']}")
    assert done_b["credit_earned_cents"] == 3000, (
        f"shift B credit expected 3000, got {done_b['credit_earned_cents']}")
    member = validate_success(api_client.get_member(ctx["member"]["id"], FM), 200)
    assert member["wallet_credit_cents"] == 9000, (
        f"wallet expected 9000, got {member['wallet_credit_cents']}")


def test_outstanding_balance_pinned_eval_order(api):
    """PRD §3.4: "determine the wallet credit to apply: take the smaller of the member's available `wallet_credit_cents` and the net-after-refunds amount floored at zero (so wallet credit is never applied against a negative net)."
    PRD §3.4: "The outstanding balance is then the net-after-refunds amount, minus the wallet credit applied, minus the total payments, with the final result floored at zero so the balance never goes negative."

    Design: Difficulty/combinatorial_formula/outstanding_balance_pinned_eval_order_mode_c
    """
    # CONFIRMED BASELINE working-share sub, season_price 50000; 4h shift → wallet 6000;
    # REFUND hold on week 2 (refund 4167). net = 50000-4167 = 45833;
    # wallet_applied = min(6000, 45833) = 6000; outstanding = 45833-6000 = 39833.
    ctx = setup_confirmed_working_share(tier="BASELINE", base_price_cents=50000,
                                        week_count=12, clock="2026-06-15T00:00:00Z")
    sub_id = ctx["subscription"]["id"]
    mh = ctx["member_headers"]
    shift = schedule_shift(sub_id, mh, "2026-08-05T09:00:00Z", 4)
    complete_shift(shift["id"])

    box_w2 = box_for_week(sub_id, mh, 2)
    get_success_data(api_client.create_vacation_hold(
        create_vacation_hold_payload(sub_id, box_w2["id"]), mh))

    sub = validate_success(api_client.get_subscription(sub_id, FM), 200)
    assert sub["outstanding_balance_cents"] == 39833, (
        f"outstanding expected 39833 (net 45833 − wallet 6000), "
        f"got {sub['outstanding_balance_cents']}")


# ─── Second-instance coverage (distinct facets) ──────────────────────────────

def test_workshare_credit_separate_dates_not_capped_together(api):
    """PRD §3.9: "The credit is computed against a fixed hourly rate of 1500 cents
    per hour, subject to a daily cap of 6 creditable hours per calendar date."

    Design: Difficulty/combinatorial_formula/workshare_credit_straddles_daily_cap_mode_a
    """
    # Two 4h shifts on DIFFERENT UTC dates: each fits under its own date's 6h cap,
    # so both earn full credit (6000 each) — proving the cap is per-calendar-date.
    ctx = setup_confirmed_working_share(tier="BASELINE", base_price_cents=30000,
                                        share_size="SMALL", items_per_box=5)
    sub_id = ctx["subscription"]["id"]
    mh = ctx["member_headers"]
    shift_a = schedule_shift(sub_id, mh, "2026-08-01T09:00:00Z", 4)
    shift_b = schedule_shift(sub_id, mh, "2026-08-02T09:00:00Z", 4)
    done_a = complete_shift(shift_a["id"])
    done_b = complete_shift(shift_b["id"])
    assert done_a["credit_earned_cents"] == 6000, (
        f"date-1 shift expected 6000, got {done_a['credit_earned_cents']}")
    assert done_b["credit_earned_cents"] == 6000, (
        f"date-2 shift expected 6000, got {done_b['credit_earned_cents']}")
    member = validate_success(api_client.get_member(ctx["member"]["id"], FM), 200)
    assert member["wallet_credit_cents"] == 12000


def test_outstanding_balance_pinned_order_underlying_ledger(api):
    """PRD §3.4: "First, sum the `amount_cents` of all charge entries — those of
    type `CHARGE_SEASON`, `CHARGE_ADDON`, and `CHARGE_SURCHARGE` — to obtain the
    gross charges."
    PRD §3.4: "Second, sum the magnitudes of the hold-refund credits (the
    `CREDIT_HOLD_REFUND` entries, stored negative) and subtract that total from the
    gross charges to obtain the net amount after refunds."

    Design: Difficulty/combinatorial_formula/outstanding_balance_pinned_eval_order_mode_c
    """
    # Same scenario as the primary test; here assert the underlying ledger lines
    # (CHARGE_SEASON 50000 and CREDIT_HOLD_REFUND -4167) that the pinned order sums.
    ctx = setup_confirmed_working_share(tier="BASELINE", base_price_cents=50000,
                                        week_count=12, clock="2026-06-15T00:00:00Z")
    sub_id = ctx["subscription"]["id"]
    mh = ctx["member_headers"]
    shift = schedule_shift(sub_id, mh, "2026-08-05T09:00:00Z", 4)
    complete_shift(shift["id"])
    box_w2 = box_for_week(sub_id, mh, 2)
    get_success_data(api_client.create_vacation_hold(
        create_vacation_hold_payload(sub_id, box_w2["id"]), mh))

    entries = _ledger(sub_id, mh)
    season = [e for e in entries if e["entry_type"] == "CHARGE_SEASON"]
    refund = [e for e in entries if e["entry_type"] == "CREDIT_HOLD_REFUND"]
    assert season and season[0]["amount_cents"] == 50000, "CHARGE_SEASON of 50000 expected"
    assert refund and refund[0]["amount_cents"] == -4167, (
        f"week-2 CREDIT_HOLD_REFUND expected -4167, got "
        f"{refund[0]['amount_cents'] if refund else None}")
