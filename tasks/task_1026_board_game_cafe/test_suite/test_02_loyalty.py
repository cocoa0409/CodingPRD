"""Loyalty: per-line point flooring, the close->accrual->tier-upgrade cascade,
the redeem/reverse conservation invariant, tier thresholds, and redemption errors."""
from test_helpers import (
    validate_success, validate_error, get_success_data, TEST_USERS,
    create_table, create_membership, grant_loyalty,
    create_seated_reservation, add_fnb, set_clock, make_member_headers,
)

MGR = TEST_USERS["manager_headers"]
STAFF = TEST_USERS["staff_headers"]


# ─── Difficulty/combinatorial_formula/loyalty_points_floor_per_line_then_sum_mode_b ─
def test_points_floored_per_line_before_summation(api):
    """PRD §3.3: "`points_earned` is computed by taking each non-`VOID` food-and-beverage
    order, converting its `total_cents` to whole points at one point per 100 cents and
    discarding any remainder on that line, and then summing those per-line whole-point
    amounts. The per-line flooring is pinned to happen before summation, so multiple
    small lines do not pool their remainders."

    Design: Difficulty/combinatorial_formula/loyalty_points_floor_per_line_then_sum_mode_b
    """
    table = create_table(api, seats=4, half_hour_rate_cents=0, day_pass_cents=0,
                         cover_fee_cents=0, min_spend_cents=0, zone="QUIET")
    member = create_membership(api, email="floor@x.com", full_name="M Three")
    resv = create_seated_reservation(
        api, table_id=table["id"], membership_id=member["id"], party_size=2,
        start_at="2026-07-04T18:00:00Z", end_at="2026-07-04T19:00:00Z",
        seated_at="2026-07-04T18:00:00Z", booking_clock="2026-07-04T18:00:00Z",
    )
    add_fnb(api, resv["id"], 250, "Coffee")
    add_fnb(api, resv["id"], 250, "Tea")
    set_clock(api, "2026-07-04T19:00:00Z")

    closed = validate_success(api.close_reservation(resv["id"], STAFF))
    # floor(250/100)+floor(250/100)=2+2=4, NOT floor(500/100)=5
    assert closed["points_earned"] == 4, f"expected 4 points, got {closed['points_earned']}"


def test_per_line_points_credited_to_membership(api):
    """PRD §3.3: "`points_earned` is added to both `lifetime_points` and `points_balance`,
    and then the membership's `tier` is recomputed from the new `lifetime_points` (§3.1)."

    Design: Difficulty/combinatorial_formula/loyalty_points_floor_per_line_then_sum_mode_b
    """
    table = create_table(api, seats=4, half_hour_rate_cents=0, day_pass_cents=0,
                         cover_fee_cents=0, min_spend_cents=0, zone="QUIET")
    member = create_membership(api, email="floor2@x.com", full_name="M Three B")
    resv = create_seated_reservation(
        api, table_id=table["id"], membership_id=member["id"], party_size=2,
        start_at="2026-07-04T18:00:00Z", end_at="2026-07-04T19:00:00Z",
        seated_at="2026-07-04T18:00:00Z", booking_clock="2026-07-04T18:00:00Z",
    )
    add_fnb(api, resv["id"], 250, "Coffee")
    add_fnb(api, resv["id"], 250, "Tea")
    set_clock(api, "2026-07-04T19:00:00Z")
    validate_success(api.close_reservation(resv["id"], STAFF))

    m = validate_success(api.get_membership(member["id"], STAFF))
    assert m["lifetime_points"] == 4 and m["points_balance"] == 4, \
        f"expected lifetime/balance 4, got {m['lifetime_points']}/{m['points_balance']}"


# ─── Difficulty/transitive_cascade/close_session_accrual_then_tier_upgrade_cascade ─
def test_close_accrues_points_and_upgrades_tier(api):
    """PRD §3.3: "`points_earned` is added to both `lifetime_points` and `points_balance`,
    and then the membership's `tier` is recomputed from the new `lifetime_points` (§3.1)."
    PRD §3.1: "The lower bound is inclusive — a member whose `lifetime_points` is exactly
    500 is `SILVER`, and exactly 2000 is `GOLD`."

    Design: Difficulty/transitive_cascade/close_session_accrual_then_tier_upgrade_cascade
    """
    table = create_table(api, seats=4, half_hour_rate_cents=0, day_pass_cents=0,
                         cover_fee_cents=0, min_spend_cents=0, zone="MAIN")
    member = create_membership(api, email="cascade@x.com", full_name="M Four")
    grant_loyalty(api, member["id"], 480, "carryover")  # BRONZE at 480
    resv = create_seated_reservation(
        api, table_id=table["id"], membership_id=member["id"], party_size=2,
        start_at="2026-07-06T18:00:00Z", end_at="2026-07-06T19:00:00Z",
        seated_at="2026-07-06T18:00:00Z", booking_clock="2026-07-06T18:00:00Z",
    )
    add_fnb(api, resv["id"], 3000, "Big platter")
    set_clock(api, "2026-07-06T19:00:00Z")

    closed = validate_success(api.close_reservation(resv["id"], STAFF))
    assert closed["points_earned"] == 30, "floor(3000/100)"

    m = validate_success(api.get_membership(member["id"], STAFF))
    assert m["lifetime_points"] == 510, "480 + 30"
    assert m["tier"] == "SILVER", "510 >= 500 threshold"


def test_close_cascade_credits_points_balance(api):
    """PRD §3.3: "`points_earned` is added to both `lifetime_points` and `points_balance`,
    and then the membership's `tier` is recomputed from the new `lifetime_points` (§3.1)."

    Design: Difficulty/transitive_cascade/close_session_accrual_then_tier_upgrade_cascade
    """
    table = create_table(api, seats=4, half_hour_rate_cents=0, day_pass_cents=0,
                         cover_fee_cents=0, min_spend_cents=0, zone="MAIN")
    member = create_membership(api, email="cascade2@x.com", full_name="M Four B")
    grant_loyalty(api, member["id"], 480, "carryover")
    resv = create_seated_reservation(
        api, table_id=table["id"], membership_id=member["id"], party_size=2,
        start_at="2026-07-06T18:00:00Z", end_at="2026-07-06T19:00:00Z",
        seated_at="2026-07-06T18:00:00Z", booking_clock="2026-07-06T18:00:00Z",
    )
    add_fnb(api, resv["id"], 3000, "Big platter")
    set_clock(api, "2026-07-06T19:00:00Z")
    validate_success(api.close_reservation(resv["id"], STAFF))

    m = validate_success(api.get_membership(member["id"], STAFF))
    assert m["points_balance"] == 510, "480 + 30"


# ─── Difficulty/compensating_invariant/loyalty_redeem_reverse_conserves_points_balance ─
def test_redeem_then_reverse_conserves_points_balance(api):
    """PRD §3.1: "On success the `points_cost` is subtracted from `points_balance`
    (lifetime points are unaffected), a new redemption identifier is recorded as
    `last_redemption_id`, `last_redemption_points` is set to the `points_cost`, and
    `last_redemption_status` becomes `APPLIED`."
    PRD §3.1: "On success, `last_redemption_points` is added back to `points_balance`
    and `last_redemption_status` becomes `REVERSED`."

    Design: Difficulty/compensating_invariant/loyalty_redeem_reverse_conserves_points_balance
    """
    member = create_membership(api, email="conserve@x.com", full_name="M Seven")
    grant_loyalty(api, member["id"], 300, "grant")  # balance 300

    redeemed = validate_success(
        api.redeem(member["id"], {"points_cost": 100, "reward_description": "Poster"},
                   make_member_headers(member["id"]))
    )
    assert redeemed["points_balance"] == 200, "300 - 100"
    rid = redeemed["last_redemption_id"]

    reversed_m = validate_success(api.reverse_redemption(member["id"], rid, STAFF))
    assert reversed_m["points_balance"] == 300, "restored to pre-redemption balance"
    assert reversed_m["last_redemption_status"] == "REVERSED"


def test_reverse_sets_last_redemption_status_reversed(api):
    """PRD §3.1: "On success, `last_redemption_points` is added back to `points_balance`
    and `last_redemption_status` becomes `REVERSED`."

    Design: Difficulty/compensating_invariant/loyalty_redeem_reverse_conserves_points_balance
    """
    member = create_membership(api, email="conserve2@x.com", full_name="M Seven B")
    grant_loyalty(api, member["id"], 300, "grant")
    redeemed = validate_success(
        api.redeem(member["id"], {"points_cost": 100, "reward_description": "Mug"},
                   make_member_headers(member["id"]))
    )
    rid = redeemed["last_redemption_id"]
    validate_success(api.reverse_redemption(member["id"], rid, STAFF))

    m = validate_success(api.get_membership(member["id"], STAFF))
    assert m["last_redemption_status"] == "REVERSED"


# ─── Corner/calculations/membership_tier_gold_at_threshold ─────────────────
def test_grant_to_exactly_gold_threshold_sets_gold(api):
    """PRD §3.1: "a member is `GOLD` once lifetime points reach at least 2000, `SILVER`
    once they reach at least 500 (but below the gold threshold), and `BRONZE` otherwise."
    PRD §3.1: "The lower bound is inclusive — a member whose `lifetime_points` is exactly
    500 is `SILVER`, and exactly 2000 is `GOLD`."

    Design: Corner/calculations/membership_tier_gold_at_threshold
    """
    member = create_membership(api, email="gold@x.com", full_name="Goldie")
    m = validate_success(
        api.loyalty_adjustment(member["id"], {"points_delta": 2000, "reason": "big grant"}, MGR)
    )
    assert m["lifetime_points"] == 2000 and m["tier"] == "GOLD"


# ─── Corner/state_machines/reinstate_suspended_member_resets_strikes ───────
def test_reinstate_suspended_member_resets_strikes(api):
    """PRD §3.1: "Reinstating moves a `SUSPENDED` membership back to `ACTIVE` and resets
    `no_show_strikes` to zero."

    Design: Corner/state_machines/reinstate_suspended_member_resets_strikes
    """
    member = create_membership(api, email="susp@x.com", full_name="Susp")
    validate_success(api.update_membership(member["id"], {"status": "SUSPENDED"}, MGR))
    m = validate_success(api.update_membership(member["id"], {"status": "ACTIVE"}, MGR))
    assert m["status"] == "ACTIVE" and m["no_show_strikes"] == 0


# ─── Corner/validations/redeem_more_than_balance_returns_insufficient ──────
def test_redeem_over_balance_returns_insufficient_points(api):
    """PRD §3.1: "The `points_cost` may not exceed the current `points_balance`; an
    over-redemption is rejected with `ERR_INSUFFICIENT_POINTS`."

    Design: Corner/validations/redeem_more_than_balance_returns_insufficient
    """
    member = create_membership(api, email="poor@x.com", full_name="Poor")
    grant_loyalty(api, member["id"], 50, "small grant")
    res = api.redeem(member["id"], {"points_cost": 100, "reward_description": "Big reward"},
                     make_member_headers(member["id"]))
    validate_error(res, "ERR_INSUFFICIENT_POINTS")


# ─── Corner/validations/reverse_already_reversed_redemption_returns_error ──
def test_reverse_already_reversed_redemption_returns_error(api):
    """PRD §3.1: "If the named redemption is not the most recent applied one — for
    instance because it has already been reversed — the request is rejected with
    `ERR_REDEMPTION_ALREADY_REVERSED`."

    Design: Corner/validations/reverse_already_reversed_redemption_returns_error
    """
    member = create_membership(api, email="rev@x.com", full_name="Rev")
    grant_loyalty(api, member["id"], 300, "grant")
    redeemed = validate_success(
        api.redeem(member["id"], {"points_cost": 100, "reward_description": "Poster"},
                   make_member_headers(member["id"]))
    )
    rid = redeemed["last_redemption_id"]
    validate_success(api.reverse_redemption(member["id"], rid, STAFF))

    res = api.reverse_redemption(member["id"], rid, STAFF)
    validate_error(res, "ERR_REDEMPTION_ALREADY_REVERSED")
