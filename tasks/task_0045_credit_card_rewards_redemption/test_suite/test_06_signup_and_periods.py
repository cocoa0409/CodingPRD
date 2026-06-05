"""Signup-bonus qualification, the half-open temporal windows (quarterly and
signup), the signup-grant cascade, and the period-close sweeps
(PRD §3.5, §3.7, §3.10)."""
from test_helpers import (
    validate_success,
    validate_error,
    TEST_USERS,
    make_cardholder_headers,
    set_clock,
    create_product,
    create_quarterly_category,
    create_active_account,
    setup_account_with_activated_quarterly,
    create_and_post_transaction,
    create_pending_transaction,
    post_transaction,
    get_account,
    list_account_lots,
    close_period,
    ApiErrorId,
)

_ADMIN = TEST_USERS["program_admin_headers"]
_OPS = TEST_USERS["rewards_ops_headers"]


def test_post_drives_qualifying_spend_signup_grant_balance_depth3(api):
    """PRD §3.7: "On each posting that updates `qualifying_spend_cents`, the
    system grants the signup bonus when all of the following hold: the account's
    `signup_bonus_status` is still `NOT_QUALIFIED`; the `qualifying_spend_cents`
    has reached at least the product's `signup_bonus_spend_threshold_cents`
    (reaching the threshold exactly qualifies) ... When granted, the account's
    `signup_bonus_status` becomes `EARNED`, a `SIGNUP_BONUS` PointsLot is minted
    with `original_points` and `remaining_points` both equal to the product's
    `signup_bonus_points` ... and that many points are added to the account's
    `points_balance`."

    Design: Difficulty/transitive_cascade/post_drives_qualifying_spend_then_signup_grant_then_balance_depth3
    """
    set_clock("2026-07-01T00:00:00Z")
    prod = create_product(name="Bonus Visa", base_earn_rate_bps=100, signup_bonus_points=10000,
                          signup_bonus_spend_threshold_cents=100000, signup_bonus_window_days=90)
    acct = create_active_account(card_product_id=prod["id"])
    create_and_post_transaction(acct["id"], 50000, category_code="OTHER", transacted_at="2026-07-05T00:00:00Z")
    set_clock("2026-07-10T00:00:00Z")
    t2 = create_pending_transaction(acct["id"], 50000, category_code="OTHER", transacted_at="2026-07-10T00:00:00Z")
    post_transaction(t2["id"])

    acct = get_account(acct["id"])
    assert acct["qualifying_spend_cents"] == 100000, (
        f"qualifying_spend must reach 100000, got {acct['qualifying_spend_cents']}"
    )
    assert acct["signup_bonus_status"] == "EARNED", (
        f"signup_bonus_status must flip to EARNED, got {acct['signup_bonus_status']!r}"
    )
    lots = list_account_lots(acct["id"])
    signup = [l for l in lots if l["lot_type"] == "SIGNUP_BONUS"]
    assert len(signup) == 1, f"exactly one SIGNUP_BONUS lot expected, got {len(signup)}"
    assert signup[0]["original_points"] == 10000, (
        f"SIGNUP_BONUS lot must hold 10000 points, got {signup[0]['original_points']}"
    )
    assert acct["points_balance"] == 11000, (
        f"balance must be 500+500+10000=11000, got {acct['points_balance']}"
    )


def test_signup_threshold_ge_exact_boundary(api):
    """PRD §3.7: "the `qualifying_spend_cents` has reached at least the product's
    `signup_bonus_spend_threshold_cents` (reaching the threshold exactly
    qualifies)".

    Design: Difficulty/boundary_precision_check/signup_threshold_ge_exact_on_transaction_post
    """
    set_clock("2026-07-01T00:00:00Z")
    prod = create_product(name="Bonus Visa", base_earn_rate_bps=100, signup_bonus_points=10000,
                          signup_bonus_spend_threshold_cents=100000, signup_bonus_window_days=90)
    acct = create_active_account(card_product_id=prod["id"])
    t1 = create_and_post_transaction(acct["id"], 99999, category_code="OTHER", transacted_at="2026-07-05T00:00:00Z")
    acct99999 = get_account(acct["id"])
    assert acct99999["signup_bonus_status"] == "NOT_QUALIFIED", (
        f"one cent short of threshold must stay NOT_QUALIFIED, got {acct99999['signup_bonus_status']!r}"
    )
    create_and_post_transaction(acct["id"], 1, category_code="OTHER", transacted_at="2026-07-06T00:00:00Z")
    acct100000 = get_account(acct["id"])
    assert acct100000["qualifying_spend_cents"] == 100000, "qualifying_spend must reach exactly 100000"
    assert acct100000["signup_bonus_status"] == "EARNED", (
        f"reaching threshold exactly must flip to EARNED, got {acct100000['signup_bonus_status']!r}"
    )


def test_signup_window_half_open_account_anchored(api):
    """PRD §3.7: "That window begins at `opened_at` (inclusive) and ends at
    `opened_at` plus the product's `signup_bonus_window_days` days (exclusive); a
    transaction whose time is exactly at that upper boundary, to the millisecond,
    is outside the window."

    Design: Difficulty/resource_temporal_overlap/signup_window_half_open_account_anchored_interval
    """
    set_clock("2026-07-01T00:00:00Z")
    prod = create_product(name="Win Visa", base_earn_rate_bps=100, signup_bonus_points=10000,
                          signup_bonus_spend_threshold_cents=100000, signup_bonus_window_days=30)
    acct = create_active_account(card_product_id=prod["id"])  # opened_at == 2026-07-01
    set_clock("2026-07-31T12:00:00Z")
    # opened_at + 30 days == 2026-07-31T00:00:00Z is the exclusive upper bound.
    edge = create_and_post_transaction(acct["id"], 100000, category_code="OTHER",
                                       transacted_at="2026-07-31T00:00:00Z")
    acct = get_account(acct["id"])
    assert acct["qualifying_spend_cents"] == 0, (
        f"txn at exclusive upper boundary must not advance qualifying_spend, got {acct['qualifying_spend_cents']}"
    )
    assert acct["signup_bonus_status"] == "NOT_QUALIFIED", (
        f"boundary-excluded spend must leave NOT_QUALIFIED, got {acct['signup_bonus_status']!r}"
    )


def test_quarterly_window_half_open_calendar_interval(api):
    """PRD §3.1: "The window boundary is inclusive at the start and exclusive at
    the end: spend whose transaction time is at or after `window_end` does not
    earn the quarterly bonus."
    PRD §3.5: "whose window contains the transaction time, meaning `window_start`
    is at or before `transacted_at` and `transacted_at` is strictly before
    `window_end`".

    Design: Difficulty/resource_temporal_overlap/quarterly_window_half_open_calendar_interval
    """
    set_clock("2026-06-30T00:00:00Z")
    prod, acct, qcat = setup_account_with_activated_quarterly(
        product_overrides={"name": "Q Visa", "base_earn_rate_bps": 100,
                           "signup_bonus_spend_threshold_cents": 999999, "signup_bonus_window_days": 365},
        quarterly_overrides={"code": "GROCERY", "quarter_label": "2026-Q3",
                             "window_start": "2026-07-01T00:00:00Z", "window_end": "2026-10-01T00:00:00Z",
                             "earn_multiplier_bps": 500, "bonus_cap_cents": 100000},
    )
    set_clock("2026-10-02T00:00:00Z")
    in_txn = create_and_post_transaction(acct["id"], 10000, category_code="GROCERY",
                                         transacted_at="2026-07-01T00:00:00Z")
    out_txn = create_and_post_transaction(acct["id"], 10000, category_code="GROCERY",
                                          transacted_at="2026-10-01T00:00:00Z")
    assert in_txn["quarterly_bonus_applied_cents"] == 10000, (
        f"txn at inclusive window_start must earn the bonus, got {in_txn['quarterly_bonus_applied_cents']}"
    )
    assert in_txn["earned_points"] == 500, f"10000c @500bps -> 500 points, got {in_txn['earned_points']}"
    assert out_txn["quarterly_bonus_applied_cents"] == 0, (
        f"txn at exclusive window_end must earn no bonus, got {out_txn['quarterly_bonus_applied_cents']}"
    )
    assert out_txn["earned_points"] == 100, f"10000c @ base 100bps -> 100 points, got {out_txn['earned_points']}"


def test_signup_window_expiry_sweep_marks_unqualified(api):
    """PRD §3.7: "If the window passes without the threshold ever being met ... the
    period-close epoch (§3.10) marks the account's `signup_bonus_status` as
    `EXPIRED_UNQUALIFIED`."
    PRD §3.10: "every account whose signup-bonus window has passed without the
    threshold being met has its `signup_bonus_status` set to
    `EXPIRED_UNQUALIFIED`."

    Design: Corner/state_machines/signup_window_expiry_sweep_marks_unqualified
    """
    set_clock("2026-07-01T00:00:00Z")
    prod = create_product(name="Win Visa", base_earn_rate_bps=100, signup_bonus_points=10000,
                          signup_bonus_spend_threshold_cents=100000, signup_bonus_window_days=30)
    acct = create_active_account(card_product_id=prod["id"])
    set_clock("2026-08-15T00:00:00Z")
    summary = close_period()
    assert summary["signup_windows_expired"] >= 1, (
        f"sweep must report at least one expired signup window, got {summary['signup_windows_expired']}"
    )
    acct = get_account(acct["id"])
    assert acct["signup_bonus_status"] == "EXPIRED_UNQUALIFIED", (
        f"unmet window must become EXPIRED_UNQUALIFIED, got {acct['signup_bonus_status']!r}"
    )


def test_expired_lot_sweep_forfeits_points(api):
    """PRD §3.10: "every `ACTIVE` PointsLot whose `expires_at` is at or before the
    current clock transitions to `EXPIRED`, forfeiting its `remaining_points` ...
    The operation reports a summary giving the `expired_lot_count` ... the
    `expired_points` (the total points forfeited)".

    Design: Corner/state_machines/expired_lot_sweep_forfeits_points
    """
    set_clock("2026-07-01T00:00:00Z")
    prod = create_product(name="Exp Visa", base_earn_rate_bps=100, signup_bonus_spend_threshold_cents=999999,
                          signup_bonus_window_days=365, points_expiry_months=1)
    acct = create_active_account(card_product_id=prod["id"])
    create_and_post_transaction(acct["id"], 100000, category_code="OTHER", transacted_at="2026-07-02T00:00:00Z")
    set_clock("2026-09-01T00:00:00Z")
    summary = close_period()
    assert summary["expired_points"] == 1000, (
        f"sweep must forfeit the lot's 1000 points, got {summary['expired_points']}"
    )
    acct = get_account(acct["id"])
    assert acct["points_balance"] == 0, f"points_balance must drop to 0 after expiry, got {acct['points_balance']}"
    lots = list_account_lots(acct["id"])
    earn = [l for l in lots if l["lot_type"] == "EARN"]
    assert earn and earn[0]["status"] == "EXPIRED", (
        f"the EARN lot must be EXPIRED, got {earn[0]['status'] if earn else 'none'}"
    )


def test_transaction_in_future_rejected_temporal(api):
    """PRD §3.3: "The `transacted_at` must be no earlier than the account's
    `opened_at` and no later than the current server clock; a value before opening
    or in the future is rejected with `ERR_TEMPORAL_OUT_OF_RANGE` (HTTP 422)."

    Design: Corner/validations/transaction_in_future_rejected_temporal
    """
    set_clock("2026-07-05T00:00:00Z")
    prod = create_product(signup_bonus_spend_threshold_cents=999999)
    acct = create_active_account(card_product_id=prod["id"])
    res = api.create_transaction(
        {"card_account_id": acct["id"], "amount_cents": 5000, "category_code": "OTHER",
         "transacted_at": "2026-08-01T00:00:00Z"},
        _ADMIN,
    )
    validate_error(res, ApiErrorId.ERR_TEMPORAL_OUT_OF_RANGE.value)
