"""The points-earning calculation: category/quarterly/tier blend, the per-quarter
bonus cap, round-once precision, the provisional-vs-posted variant, tier
promotion, and quarterly activation gating (PRD §3.3, §3.5, §3.6)."""
from test_helpers import (
    validate_success,
    TEST_USERS,
    make_cardholder_headers,
    set_clock,
    create_product,
    create_cashback_category,
    create_quarterly_category,
    create_account,
    create_active_account,
    setup_active_account,
    setup_account_with_activated_quarterly,
    create_pending_transaction,
    post_transaction,
    create_and_post_transaction,
    get_account,
)

_ADMIN = TEST_USERS["program_admin_headers"]


def test_three_input_blend_category_quarterly_cap_tier(api):
    """PRD §3.5: "The base part is the amount of cents that did not receive the
    quarterly bonus (the `amount_cents` minus the bonus cents) multiplied by the
    stage-one per-cent multiplier in basis points. The quarterly part is the bonus
    cents multiplied by the quarterly category's `earn_multiplier_bps` ... The
    system adds the base part and the quarterly part, multiplies that sum by the
    tier multiplier in basis points, and then divides by 1,000,000 ... taking the
    floor of that single division to yield `earned_points`."
    PRD §3.5: "The cents of this transaction that earn the quarterly multiplier —
    recorded as the transaction's `quarterly_bonus_applied_cents` — is the smaller
    of the transaction's `amount_cents` and that remaining cap."

    Design: Difficulty/combinatorial_formula/three_input_blend_category_quarterly_cap_tier_mode_a
    """
    set_clock("2026-07-01T00:00:00Z")
    prod = create_product(
        name="Tier Visa",
        base_earn_rate_bps=100,
        signup_bonus_spend_threshold_cents=100000,
        signup_bonus_window_days=365,
        tier_thresholds=[{"min_annual_spend_cents": 100000, "tier_multiplier_bps": 150}],
    )
    qcat = create_quarterly_category(
        prod["id"], code="GROCERY", quarter_label="2026-Q3",
        window_start="2026-07-01T00:00:00Z", window_end="2026-10-01T00:00:00Z",
        earn_multiplier_bps=500, bonus_cap_cents=50000,
    )
    acct = create_active_account(card_product_id=prod["id"])
    validate_success(
        api.create_category_activation(
            {"card_account_id": acct["id"], "quarterly_category_id": qcat["id"]},
            make_cardholder_headers(acct["id"]),
        ),
        expected_status=201,
    )
    # Warm up to tier 1 (>=100000 annual spend) with an OTHER posting.
    create_and_post_transaction(acct["id"], 100000, category_code="OTHER", transacted_at="2026-07-05T00:00:00Z")
    assert get_account(acct["id"])["current_tier_index"] == 1, "warmup must promote to tier 1"

    set_clock("2026-08-01T00:00:00Z")
    gtxn = create_and_post_transaction(acct["id"], 60000, category_code="GROCERY", transacted_at="2026-08-01T00:00:00Z")
    assert gtxn["quarterly_bonus_applied_cents"] == 50000, (
        f"quarterly_bonus_applied_cents must cap at 50000, got {gtxn['quarterly_bonus_applied_cents']}"
    )
    assert gtxn["earned_points"] == 3900, f"blended earned_points must be 3900, got {gtxn['earned_points']}"


def test_rounding_order_floor_once_not_per_step(api):
    """PRD §2.9: "The points-earning computation multiplies all of its
    basis-point factors together first and divides only once, applying a single
    floor (round-down to a whole number of points) at the very end. Per-step
    rounding is forbidden".
    PRD §3.5: "No intermediate result is rounded; the floor is applied only at
    this final step."

    Design: Difficulty/combinatorial_formula/rounding_order_floor_once_not_per_step_mode_b
    """
    set_clock("2026-07-01T00:00:00Z")
    prod = create_product(name="Dine Visa", base_earn_rate_bps=100, signup_bonus_spend_threshold_cents=100000)
    create_cashback_category(prod["id"], "DINING", 300)
    acct = create_active_account(card_product_id=prod["id"])
    d1 = create_pending_transaction(acct["id"], 333, category_code="DINING", transacted_at="2026-07-02T00:00:00Z")
    d2 = create_pending_transaction(acct["id"], 333, category_code="DINING", transacted_at="2026-07-02T01:00:00Z")
    d1 = post_transaction(d1["id"])
    d2 = post_transaction(d2["id"])
    assert d1["earned_points"] == 9, f"each 333c DINING txn floors to 9 points, got {d1['earned_points']}"
    assert d2["earned_points"] == 9, f"each 333c DINING txn floors to 9 points, got {d2['earned_points']}"
    acct = get_account(acct["id"])
    assert acct["points_balance"] == 18, (
        f"two independent floor-once postings sum to 18 (NOT 19 from sum-then-floor), got {acct['points_balance']}"
    )


def test_provisional_pending_then_posted_balance(api):
    """PRD §3.3: "At creation the system computes the **provisional** points
    figure for the transaction using the same earning formula ... the provisional
    figure is added to the account's `pending_points` ... The transaction's
    `earned_points` field remains 0 ... while the transaction is still `PENDING`".
    PRD §3.5: "The **posted** variant runs at posting: the result is written to
    `earned_points`, a PointsLot is minted, and the points move from
    `pending_points` into `points_balance`."

    Design: Difficulty/dual_variant_calc/provisional_pending_vs_posted_balance_on_transaction
    """
    set_clock("2026-07-01T00:00:00Z")
    prod = create_product(
        name="Cash Visa", base_earn_rate_bps=100, signup_bonus_points=10000,
        signup_bonus_spend_threshold_cents=100000, signup_bonus_window_days=90,
        tier_thresholds=[{"min_annual_spend_cents": 100000, "tier_multiplier_bps": 150}],
    )
    acct = create_active_account(card_product_id=prod["id"])
    txn = create_pending_transaction(acct["id"], 50000, category_code="OTHER", transacted_at="2026-07-02T00:00:00Z")
    after_create = get_account(acct["id"])
    assert after_create["pending_points"] == 500, (
        f"provisional 500 must land in pending_points, got {after_create['pending_points']}"
    )
    assert after_create["points_balance"] == 0, (
        f"points_balance must stay 0 while PENDING, got {after_create['points_balance']}"
    )

    posted = post_transaction(txn["id"])
    assert posted["earned_points"] == 500, f"posted txn earned_points must be 500, got {posted['earned_points']}"
    after_post = get_account(acct["id"])
    assert after_post["pending_points"] == 0, f"pending_points must clear on post, got {after_post['pending_points']}"
    assert after_post["points_balance"] == 500, (
        f"points_balance must hold 500 after post, got {after_post['points_balance']}"
    )


def test_provisional_earned_points_zero_on_pending_row(api):
    """PRD §3.3: "The transaction's `earned_points` field remains 0 and its
    `quarterly_bonus_applied_cents` field remains 0 while the transaction is still
    `PENDING`; these settle only at posting."

    Design: Difficulty/dual_variant_calc/provisional_pending_vs_posted_balance_on_transaction
    """
    set_clock("2026-07-01T00:00:00Z")
    prod = create_product(name="Cash Visa", base_earn_rate_bps=100, signup_bonus_spend_threshold_cents=999999)
    acct = create_active_account(card_product_id=prod["id"])
    txn = create_pending_transaction(acct["id"], 50000, category_code="OTHER", transacted_at="2026-07-02T00:00:00Z")
    assert txn["earned_points"] == 0, f"PENDING txn earned_points must be 0, got {txn['earned_points']}"
    assert txn["quarterly_bonus_applied_cents"] == 0, (
        f"PENDING txn quarterly_bonus_applied_cents must be 0, got {txn['quarterly_bonus_applied_cents']}"
    )
    acct = get_account(acct["id"])
    assert acct["pending_points"] == 500, f"pending_points must hold the provisional 500, got {acct['pending_points']}"


def test_quarterly_cap_straddle_across_two_transactions(api):
    """PRD §3.5: "it sums the `quarterly_bonus_applied_cents` of the account's
    already-`POSTED` transactions in that same quarterly category that received a
    positive quarterly bonus ... and subtracts that used amount from the
    category's `bonus_cap_cents`, flooring the remaining cap at 0. The cents of
    this transaction that earn the quarterly multiplier ... is the smaller of the
    transaction's `amount_cents` and that remaining cap."

    Design: Corner/calculations/quarterly_cap_straddle_across_two_transactions
    """
    set_clock("2026-07-01T00:00:00Z")
    prod, acct, qcat = setup_account_with_activated_quarterly(
        product_overrides={"name": "Q Visa", "base_earn_rate_bps": 100,
                           "signup_bonus_spend_threshold_cents": 999999, "signup_bonus_window_days": 365},
        quarterly_overrides={"code": "GROCERY", "quarter_label": "2026-Q3",
                             "window_start": "2026-07-01T00:00:00Z", "window_end": "2026-10-01T00:00:00Z",
                             "earn_multiplier_bps": 500, "bonus_cap_cents": 50000},
    )
    g1 = create_and_post_transaction(acct["id"], 40000, category_code="GROCERY", transacted_at="2026-07-05T00:00:00Z")
    assert g1["quarterly_bonus_applied_cents"] == 40000, (
        f"first 40000 fully bonused, got {g1['quarterly_bonus_applied_cents']}"
    )
    assert g1["earned_points"] == 2000, f"40000c @500bps -> 2000 points, got {g1['earned_points']}"
    g2 = create_and_post_transaction(acct["id"], 30000, category_code="GROCERY", transacted_at="2026-07-06T00:00:00Z")
    assert g2["quarterly_bonus_applied_cents"] == 10000, (
        f"second txn gets only 10000 cap-remaining, got {g2['quarterly_bonus_applied_cents']}"
    )
    assert g2["earned_points"] == 700, (
        f"10000c @500bps + 20000c @100bps -> 700 points, got {g2['earned_points']}"
    )


def test_unactivated_quarterly_category_earns_base_only(api):
    """PRD §3.5: "The quarterly bonus applies only if such a category exists
    **and** the account has an `ACTIVE` `CategoryActivation` for it whose
    `activated_at` is at or before `transacted_at`. ... When no quarterly category
    applies or the account has not activated it, `quarterly_bonus_applied_cents`
    is 0."

    Design: Corner/calculations/unactivated_quarterly_category_earns_base_only
    """
    set_clock("2026-07-05T00:00:00Z")
    prod = create_product(name="Q Visa", base_earn_rate_bps=100, signup_bonus_spend_threshold_cents=999999,
                          signup_bonus_window_days=365)
    create_quarterly_category(
        prod["id"], code="GROCERY", quarter_label="2026-Q3",
        window_start="2026-07-01T00:00:00Z", window_end="2026-10-01T00:00:00Z",
        earn_multiplier_bps=500, bonus_cap_cents=50000,
    )
    acct = create_active_account(card_product_id=prod["id"])  # NOT activated for the quarterly category
    g = create_and_post_transaction(acct["id"], 20000, category_code="GROCERY", transacted_at="2026-07-06T00:00:00Z")
    assert g["quarterly_bonus_applied_cents"] == 0, (
        f"unactivated quarterly spend earns no bonus, got {g['quarterly_bonus_applied_cents']}"
    )
    assert g["earned_points"] == 200, f"20000c @ base 100bps -> 200 points, got {g['earned_points']}"


def test_post_promotes_tier_then_next_txn_earns_at_new_tier(api):
    """PRD §3.6: "The index is re-derived on every posting (which adds spend) ...
    Because the earning formula reads `current_tier_index` as it stands before the
    current transaction's own spend is added, the spend from a single posting
    raises the tier for subsequent transactions, not for itself."

    Design: Corner/state_machines/post_transaction_promotes_tier_then_subsequent_earns_at_new_tier
    """
    set_clock("2026-07-01T00:00:00Z")
    prod = create_product(
        name="Tier Visa", base_earn_rate_bps=100, signup_bonus_spend_threshold_cents=999999,
        signup_bonus_window_days=365, tier_thresholds=[{"min_annual_spend_cents": 100000, "tier_multiplier_bps": 150}],
    )
    acct = create_active_account(card_product_id=prod["id"])
    t1 = create_and_post_transaction(acct["id"], 100000, category_code="OTHER", transacted_at="2026-07-02T00:00:00Z")
    assert t1["earned_points"] == 1000, f"t1 posts at tier 0 -> 1000 points, got {t1['earned_points']}"
    assert get_account(acct["id"])["current_tier_index"] == 1, "t1 must promote account to tier 1"
    t2 = create_and_post_transaction(acct["id"], 50000, category_code="OTHER", transacted_at="2026-07-03T00:00:00Z")
    assert t2["earned_points"] == 750, f"t2 posts at tier 1 (50000*150bps) -> 750 points, got {t2['earned_points']}"
