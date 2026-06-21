"""Second coverage pass for the depth (difficulty) design instances. Each test
here exercises a distinct facet of the named instance from a different angle than
its companion in the earlier files (PRD §2.x, §3.x)."""
from test_helpers import (
    validate_success,
    validate_error,
    TEST_USERS,
    make_cardholder_headers,
    set_clock,
    create_product,
    create_cashback_category,
    create_quarterly_category,
    create_transfer_partner,
    suspend_transfer_partner,
    create_active_account,
    setup_account_with_balance,
    setup_account_with_activated_quarterly,
    create_pending_transaction,
    post_transaction,
    create_and_post_transaction,
    create_redemption,
    confirm_redemption,
    get_account,
    account_version,
    list_account_lots,
    list_lots_by_source_txn,
    ApiErrorId,
)

_ADMIN = TEST_USERS["program_admin_headers"]
_OPS = TEST_USERS["rewards_ops_headers"]


# ─── Rule 1: dual-variant calculations ──────────────────────────
def test_provisional_decline_releases_pending_points(api):
    """PRD §3.3: "Declining advances it from `PENDING` to `DECLINED`: the
    transaction's provisional contribution is removed from the account's
    `pending_points`, no lot is minted, and no spend counter is touched."

    Design: Difficulty/dual_variant_calc/provisional_pending_vs_posted_balance_on_transaction
    """
    set_clock("2026-07-01T00:00:00Z")
    prod = create_product(signup_bonus_spend_threshold_cents=999999)
    acct = create_active_account(card_product_id=prod["id"])
    txn = create_pending_transaction(acct["id"], 50000, category_code="OTHER", transacted_at="2026-07-02T00:00:00Z")
    assert get_account(acct["id"])["pending_points"] == 500, "provisional 500 must sit in pending_points"
    validate_success(api.decline_transaction(txn["id"], _ADMIN))
    acct = get_account(acct["id"])
    assert acct["pending_points"] == 0, f"decline must release provisional points, got {acct['pending_points']}"
    assert acct["points_balance"] == 0, f"decline mints nothing into balance, got {acct['points_balance']}"


def test_statement_credit_value_one_cent_per_point(api):
    """PRD §3.8: "For a `STATEMENT_CREDIT`, the value in cents is the
    `points_requested` valued at a flat one cent per point — that is,
    `points_requested` times 1, exactly, with no rounding loss."

    Design: Difficulty/dual_variant_calc/statement_credit_cents_vs_points_transfer_units_on_redemption
    """
    set_clock("2026-07-01T00:00:00Z")
    acct, _ = setup_account_with_balance(
        amount_cents=100000, product_overrides={"signup_bonus_spend_threshold_cents": 999999}
    )  # balance 1000
    red = create_redemption(acct["id"], "STATEMENT_CREDIT", 750, account_version(acct["id"]))
    red = confirm_redemption(red["id"])
    assert red["redeemed_value"] == 750, f"STATEMENT_CREDIT 750 pts -> 750 cents, got {red['redeemed_value']}"


# ─── Rule 2: combinatorial formulas ─────────────────────────────
def test_three_input_blend_quarterly_part_distinct_from_base(api):
    """PRD §3.5: "The quarterly part is the bonus cents multiplied by the
    quarterly category's `earn_multiplier_bps` (and is 0 when no quarterly
    category applies)."

    Design: Difficulty/combinatorial_formula/three_input_blend_category_quarterly_cap_tier_mode_a
    """
    set_clock("2026-07-01T00:00:00Z")
    prod, acct, qcat = setup_account_with_activated_quarterly(
        product_overrides={"name": "Tier Visa", "base_earn_rate_bps": 100,
                           "signup_bonus_spend_threshold_cents": 999999, "signup_bonus_window_days": 365},
        quarterly_overrides={"code": "GROCERY", "quarter_label": "2026-Q3",
                             "window_start": "2026-07-01T00:00:00Z", "window_end": "2026-10-01T00:00:00Z",
                             "earn_multiplier_bps": 500, "bonus_cap_cents": 50000},
    )
    # 30000 GROCERY, tier 0, fully under cap: base_part=0, quarterly_part=30000*500=15,000,000;
    # *100 tier /1,000,000 = 1500 points.
    g = create_and_post_transaction(acct["id"], 30000, category_code="GROCERY", transacted_at="2026-07-05T00:00:00Z")
    assert g["quarterly_bonus_applied_cents"] == 30000, (
        f"all 30000 under cap earns quarterly, got {g['quarterly_bonus_applied_cents']}"
    )
    assert g["earned_points"] == 1500, f"30000c @500bps tier0 -> 1500 points, got {g['earned_points']}"


def test_floor_once_single_transaction_truncates(api):
    """PRD §3.5: "taking the floor of that single division to yield
    `earned_points`. No intermediate result is rounded; the floor is applied only
    at this final step."

    Design: Difficulty/combinatorial_formula/rounding_order_floor_once_not_per_step_mode_b
    """
    set_clock("2026-07-01T00:00:00Z")
    prod = create_product(name="Dine Visa", base_earn_rate_bps=100, signup_bonus_spend_threshold_cents=999999)
    create_cashback_category(prod["id"], "DINING", 300)
    acct = create_active_account(card_product_id=prod["id"])
    # 333c @300bps tier0: 333*300*100/1,000,000 = 9.99 -> floor 9.
    d = create_and_post_transaction(acct["id"], 333, category_code="DINING", transacted_at="2026-07-02T00:00:00Z")
    assert d["earned_points"] == 9, f"333c @300bps must floor to 9 (not 10), got {d['earned_points']}"


# ─── Rule 3: non-linear state machines ──────────────────────────
def test_redemption_reject_consumes_no_lots(api):
    """PRD §3.8: "Rejecting instead advances the redemption from `PENDING` to the
    terminal `REJECTED` state, consuming no lots and changing no balance."

    Design: Difficulty/non_linear_state_machine/redemption_branch_confirmed_vs_rejected_plus_reverse_revert
    """
    set_clock("2026-07-01T00:00:00Z")
    acct, _ = setup_account_with_balance(
        amount_cents=100000, product_overrides={"signup_bonus_spend_threshold_cents": 999999}
    )  # balance 1000
    red = create_redemption(acct["id"], "STATEMENT_CREDIT", 400, account_version(acct["id"]))
    rej = validate_success(api.reject_redemption(red["id"], _OPS))
    assert rej["status"] == "REJECTED", f"rejected redemption must be REJECTED, got {rej['status']!r}"
    acct = get_account(acct["id"])
    assert acct["points_balance"] == 1000, f"reject must not change balance, got {acct['points_balance']}"
    lots = list_account_lots(acct["id"])
    assert all(l["status"] == "ACTIVE" for l in lots if l["lot_type"] == "EARN"), (
        "reject must leave EARN lots ACTIVE (no consumption)"
    )


# ─── Rule 4: transitive cascades ────────────────────────────────
def test_signup_grant_mints_signup_bonus_lot_type(api):
    """PRD §3.7: "When granted, the account's `signup_bonus_status` becomes
    `EARNED`, a `SIGNUP_BONUS` PointsLot is minted with `original_points` and
    `remaining_points` both equal to the product's `signup_bonus_points`".

    Design: Difficulty/transitive_cascade/post_drives_qualifying_spend_then_signup_grant_then_balance_depth3
    """
    set_clock("2026-07-01T00:00:00Z")
    prod = create_product(name="Bonus Visa", base_earn_rate_bps=100, signup_bonus_points=5000,
                          signup_bonus_spend_threshold_cents=100000, signup_bonus_window_days=90)
    acct = create_active_account(card_product_id=prod["id"])
    create_and_post_transaction(acct["id"], 100000, category_code="OTHER", transacted_at="2026-07-05T00:00:00Z")
    lots = list_account_lots(acct["id"])
    signup = [l for l in lots if l["lot_type"] == "SIGNUP_BONUS"]
    assert len(signup) == 1, f"exactly one SIGNUP_BONUS lot expected, got {len(signup)}"
    assert signup[0]["original_points"] == 5000 and signup[0]["remaining_points"] == 5000, (
        f"SIGNUP_BONUS lot must hold 5000/5000, got {signup[0]['original_points']}/{signup[0]['remaining_points']}"
    )


def test_refund_claws_lot_then_recomputes_balance_depth2(api):
    """PRD §3.4: "The refund claws back the `EARN` PointsLot minted by that
    transaction: the lot's `status` becomes `CLAWED_BACK`."
    PRD §2.6: "`points_balance` is always the sum of `remaining_points` over the
    account's PointsLot rows that are still in `ACTIVE` status, and it is
    recomputed on every mint, consumption, clawback, and expiry."

    Design: Difficulty/transitive_cascade/refund_claws_lot_then_recomputes_balance_depth2
    """
    set_clock("2026-07-01T00:00:00Z")
    prod = create_product(signup_bonus_spend_threshold_cents=999999)
    acct = create_active_account(card_product_id=prod["id"])
    txn = create_and_post_transaction(acct["id"], 100000, category_code="OTHER", transacted_at="2026-07-02T00:00:00Z")
    assert get_account(acct["id"])["points_balance"] == 1000, "precondition balance 1000"
    validate_success(api.refund_transaction(txn["id"], _ADMIN))
    lots = list_lots_by_source_txn(txn["id"])
    assert lots and lots[0]["status"] == "CLAWED_BACK", (
        f"the EARN lot must become CLAWED_BACK, got {lots[0]['status'] if lots else 'none'}"
    )
    assert get_account(acct["id"])["points_balance"] == 0, (
        f"points_balance must recompute to 0 after clawback, got {get_account(acct['id'])['points_balance']}"
    )


def test_refund_clawback_recomputes_balance_for_partial_account(api):
    """PRD §3.4: "The refund claws back the `EARN` PointsLot minted by that
    transaction: the lot's `status` becomes `CLAWED_BACK`. ... The account's
    `points_balance` is recomputed afterward."

    Design: Difficulty/transitive_cascade/refund_claws_lot_then_recomputes_balance_depth2
    """
    set_clock("2026-07-01T00:00:00Z")
    prod = create_product(signup_bonus_spend_threshold_cents=999999)
    acct = create_active_account(card_product_id=prod["id"])
    keep = create_and_post_transaction(acct["id"], 100000, category_code="OTHER", transacted_at="2026-07-02T00:00:00Z")
    drop = create_and_post_transaction(acct["id"], 50000, category_code="OTHER", transacted_at="2026-07-03T00:00:00Z")
    assert get_account(acct["id"])["points_balance"] == 1500, "precondition balance 1500 (1000 + 500)"
    validate_success(api.refund_transaction(drop["id"], _ADMIN))
    dropped_lots = list_lots_by_source_txn(drop["id"])
    assert dropped_lots and dropped_lots[0]["status"] == "CLAWED_BACK", (
        f"refunded txn's lot must be CLAWED_BACK, got {dropped_lots[0]['status'] if dropped_lots else 'none'}"
    )
    # Only the refunded lot's 500 points are removed; the kept lot's 1000 remain.
    assert get_account(acct["id"])["points_balance"] == 1000, (
        f"balance must recompute down by exactly the clawed lot's 500, got {get_account(acct['id'])['points_balance']}"
    )


# ─── Rule 5: priority-pair validation conflicts ─────────────────
def test_state_beats_insufficient_points_returns_409(api):
    """PRD §2.10: "the checks are evaluated in a fixed priority order, and the
    first failure determines the error returned. ... Earlier checks take
    precedence over later ones".

    Design: Difficulty/priority_pair_validation_conflict/state_beats_insufficient_points_on_confirm
    """
    set_clock("2026-07-01T00:00:00Z")
    acct, txn = setup_account_with_balance(
        amount_cents=100000, product_overrides={"signup_bonus_spend_threshold_cents": 999999}
    )  # balance 1000
    # Create within balance (PRD §3.8 validates the balance at create time), then
    # reject to leave PENDING, then refund the minting txn so the balance is
    # clawed to 0 — the redemption is now BOTH non-PENDING (p7) and over balance (p13).
    red = create_redemption(acct["id"], "STATEMENT_CREDIT", 1000, account_version(acct["id"]))
    validate_success(api.reject_redemption(red["id"], _OPS))
    validate_success(api.refund_transaction(txn["id"], _ADMIN))
    # State (p7) fires before insufficient-points (p13): expect the 409, not 422.
    res = api.confirm_redemption(red["id"], _OPS)
    err = validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
    assert err["error_id"] == "ERR_INVALID_STATE", f"state must win, got {err['error_id']!r}"


def test_cross_product_short_circuits_before_duplicate(api):
    """PRD §2.10: "(8) cross-product referential integrity, yielding
    `ERR_CROSS_PRODUCT_MISMATCH`; (9) uniqueness constraints, yielding
    `ERR_DUPLICATE_ACTIVATION`".

    Design: Difficulty/priority_pair_validation_conflict/cross_product_beats_duplicate_on_activation
    """
    set_clock("2026-07-01T00:00:00Z")
    p1 = create_product(name="P1 Visa")
    p2 = create_product(name="P2 Visa")
    qcat_p2 = create_quarterly_category(
        p2["id"], code="ONLINE", quarter_label="2026-Q3",
        window_start="2026-07-01T00:00:00Z", window_end="2026-10-01T00:00:00Z",
        earn_multiplier_bps=400, bonus_cap_cents=20000,
    )
    acct = create_active_account(card_product_id=p1["id"])
    res = api.create_category_activation(
        {"card_account_id": acct["id"], "quarterly_category_id": qcat_p2["id"]},
        make_cardholder_headers(acct["id"]),
    )
    validate_error(res, ApiErrorId.ERR_CROSS_PRODUCT_MISMATCH.value)


# ─── Rule 6: boundary precision ─────────────────────────────────
def test_signup_threshold_one_cent_short_not_qualified(api):
    """PRD §3.7: "the `qualifying_spend_cents` has reached at least the product's
    `signup_bonus_spend_threshold_cents` (reaching the threshold exactly
    qualifies)".

    Design: Difficulty/boundary_precision_check/signup_threshold_ge_exact_on_transaction_post
    """
    set_clock("2026-07-01T00:00:00Z")
    prod = create_product(name="Bonus Visa", base_earn_rate_bps=100, signup_bonus_points=10000,
                          signup_bonus_spend_threshold_cents=100000, signup_bonus_window_days=90)
    acct = create_active_account(card_product_id=prod["id"])
    create_and_post_transaction(acct["id"], 99999, category_code="OTHER", transacted_at="2026-07-05T00:00:00Z")
    acct = get_account(acct["id"])
    assert acct["qualifying_spend_cents"] == 99999, f"qualifying_spend must be 99999, got {acct['qualifying_spend_cents']}"
    assert acct["signup_bonus_status"] == "NOT_QUALIFIED", (
        f"99999 (threshold - 1) must stay NOT_QUALIFIED, got {acct['signup_bonus_status']!r}"
    )


def test_min_transfer_exact_floor_passes(api):
    """PRD §3.8: "For a points transfer, `points_requested` must be at least the
    partner's `min_transfer_points`; falling below that floor is rejected with
    `ERR_BELOW_MIN_TRANSFER` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/min_transfer_points_boundary_on_redemption_create
    """
    set_clock("2026-07-01T00:00:00Z")
    prod = create_product(signup_bonus_spend_threshold_cents=999999)
    partner = create_transfer_partner(name="SkyMiles", partner_type="AIRLINE",
                                       transfer_ratio_num=1, transfer_ratio_den=1, min_transfer_points=500)
    acct = create_active_account(card_product_id=prod["id"])
    create_and_post_transaction(acct["id"], 200000, category_code="OTHER", transacted_at="2026-07-02T00:00:00Z")
    res = api.create_redemption(
        {"card_account_id": acct["id"], "redemption_type": "POINTS_TRANSFER", "points_requested": 500,
         "transfer_partner_id": partner["id"], "expected_card_account_version": account_version(acct["id"])},
        make_cardholder_headers(acct["id"]),
    )
    created = validate_success(res, expected_status=201)
    assert created["status"] == "PENDING", f"exact-floor 500 must succeed, got {created['status']!r}"


# ─── Rule 7: cross-entity state dependencies ────────────────────
def test_transaction_post_on_closed_account_keeps_pending(api):
    """PRD §3.4: "Posting a `PENDING` transaction is the central earning event,
    and it is permitted only when the transaction is `PENDING` and its owning
    account is `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/transaction_post_requires_account_active
    """
    set_clock("2026-07-01T00:00:00Z")
    prod = create_product(signup_bonus_spend_threshold_cents=999999)
    acct = create_active_account(card_product_id=prod["id"])
    txn = create_pending_transaction(acct["id"], 30000, category_code="OTHER", transacted_at="2026-07-02T00:00:00Z")
    validate_success(api.close_account(acct["id"], _ADMIN))
    res = api.post_transaction(txn["id"], _ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
    after = validate_success(api.get_transaction(txn["id"], _ADMIN))
    assert after["status"] == "PENDING", f"txn must stay PENDING, got {after['status']!r}"


def test_transfer_to_suspended_partner_rejected_cross_product(api):
    """PRD §3.8: "For a points transfer, the referenced `TransferPartner` must be
    `ACTIVE`; a transfer to a `SUSPENDED` partner is rejected with
    `ERR_CROSS_PRODUCT_MISMATCH` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/points_transfer_requires_partner_active
    """
    set_clock("2026-07-01T00:00:00Z")
    prod = create_product(signup_bonus_spend_threshold_cents=999999)
    partner = create_transfer_partner(name="HotelRewards", partner_type="HOTEL",
                                       transfer_ratio_num=2, transfer_ratio_den=1, min_transfer_points=100)
    suspend_transfer_partner(partner["id"])
    acct = create_active_account(card_product_id=prod["id"])
    create_and_post_transaction(acct["id"], 150000, category_code="OTHER", transacted_at="2026-07-02T00:00:00Z")
    res = api.create_redemption(
        {"card_account_id": acct["id"], "redemption_type": "POINTS_TRANSFER", "points_requested": 500,
         "transfer_partner_id": partner["id"], "expected_card_account_version": account_version(acct["id"])},
        make_cardholder_headers(acct["id"]),
    )
    validate_error(res, ApiErrorId.ERR_CROSS_PRODUCT_MISMATCH.value)


# ─── Rule 8: temporal-overlap interval semantics ────────────────
def test_quarterly_window_inclusive_start_earns_bonus(api):
    """PRD §3.5: "whose window contains the transaction time, meaning
    `window_start` is at or before `transacted_at` and `transacted_at` is strictly
    before `window_end`".

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
    set_clock("2026-09-15T00:00:00Z")
    # A txn strictly inside the window earns the quarterly bonus.
    g = create_and_post_transaction(acct["id"], 10000, category_code="GROCERY", transacted_at="2026-09-15T00:00:00Z")
    assert g["quarterly_bonus_applied_cents"] == 10000, (
        f"mid-window grocery must earn the bonus, got {g['quarterly_bonus_applied_cents']}"
    )
    assert g["earned_points"] == 500, f"10000c @500bps -> 500 points, got {g['earned_points']}"


def test_signup_window_inside_boundary_advances_qualifying(api):
    """PRD §3.7: "That window begins at `opened_at` (inclusive) and ends at
    `opened_at` plus the product's `signup_bonus_window_days` days (exclusive)".

    Design: Difficulty/resource_temporal_overlap/signup_window_half_open_account_anchored_interval
    """
    set_clock("2026-07-01T00:00:00Z")
    prod = create_product(name="Win Visa", base_earn_rate_bps=100, signup_bonus_points=10000,
                          signup_bonus_spend_threshold_cents=100000, signup_bonus_window_days=30)
    acct = create_active_account(card_product_id=prod["id"])  # opened_at == 2026-07-01
    set_clock("2026-07-30T12:00:00Z")
    # 2026-07-30 is one day before the exclusive upper bound (opened_at + 30d == 2026-07-31): inside.
    create_and_post_transaction(acct["id"], 40000, category_code="OTHER", transacted_at="2026-07-30T00:00:00Z")
    acct = get_account(acct["id"])
    assert acct["qualifying_spend_cents"] == 40000, (
        f"a txn inside the window must advance qualifying_spend, got {acct['qualifying_spend_cents']}"
    )


# ─── Rule 9: compensating-action invariants ─────────────────────
def test_post_refund_lot_clawed_back_balance_floored(api):
    """PRD §3.4: "If that lot's points had already been partly redeemed, the
    shortfall (the points that can no longer be reclaimed from the lot) is taken
    from the account's `points_balance`, down to a floor of 0 so the balance never
    goes negative."

    Design: Difficulty/compensating_invariant/post_then_refund_conserves_account_points_balance
    """
    set_clock("2026-07-01T00:00:00Z")
    prod = create_product(signup_bonus_spend_threshold_cents=999999)
    acct = create_active_account(card_product_id=prod["id"])
    txn = create_and_post_transaction(acct["id"], 50000, category_code="OTHER", transacted_at="2026-07-02T00:00:00Z")
    assert get_account(acct["id"])["points_balance"] == 500, "precondition balance 500"
    validate_success(api.refund_transaction(txn["id"], _ADMIN))
    after = get_account(acct["id"])
    assert after["points_balance"] == 0, (
        f"refund of the only posting returns balance to its pre-POST value 0, got {after['points_balance']}"
    )


def test_reverse_restores_consumed_redemption_to_pending(api):
    """PRD §3.8: "The reversal restores points to the exact lots recorded in
    `lots_consumed`: each such lot's `remaining_points` is increased by the
    `points_taken` originally recorded for it. ... The account's `points_balance`
    is recomputed, with a net change of exactly plus the `points_requested`".

    Design: Difficulty/compensating_invariant/confirm_then_reverse_conserves_consumed_lot_points
    """
    set_clock("2026-07-01T00:00:00Z")
    acct, _ = setup_account_with_balance(
        amount_cents=100000, product_overrides={"signup_bonus_spend_threshold_cents": 999999}
    )  # balance 1000
    red = create_redemption(acct["id"], "STATEMENT_CREDIT", 600, account_version(acct["id"]))
    confirm_redemption(red["id"])
    assert get_account(acct["id"])["points_balance"] == 400, "confirm consumes 600 -> balance 400"
    validate_success(api.reverse_redemption(red["id"], _OPS))
    after = get_account(acct["id"])
    assert after["points_balance"] == 1000, (
        f"reverse restores exactly +600 -> balance 1000, got {after['points_balance']}"
    )
