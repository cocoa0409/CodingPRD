"""Redemption workflows: the PENDING -> {CONFIRMED, REJECTED} fork, the
CONFIRMED -> REVERSED revert, redemption-value variants, FIFO lot consumption,
the partner-active gate, the minimum-transfer floor, partner-field shape, and
balance sufficiency (PRD §3.8)."""
from test_helpers import (
    validate_success,
    validate_error,
    TEST_USERS,
    make_cardholder_headers,
    set_clock,
    create_product,
    create_transfer_partner,
    suspend_transfer_partner,
    create_active_account,
    setup_account_with_balance,
    create_and_post_transaction,
    create_redemption,
    confirm_redemption,
    get_account,
    account_version,
    list_lots_by_source_txn,
    ApiErrorId,
)

_ADMIN = TEST_USERS["program_admin_headers"]
_OPS = TEST_USERS["rewards_ops_headers"]


def _balance_account(amount_cents, **prod_overrides):
    """Helper: ACTIVE account with one POSTED OTHER txn (base 100bps)."""
    prod = create_product(signup_bonus_spend_threshold_cents=999999, **prod_overrides)
    acct = create_active_account(card_product_id=prod["id"])
    create_and_post_transaction(acct["id"], amount_cents, category_code="OTHER", transacted_at="2026-07-02T00:00:00Z")
    return get_account(acct["id"])


def test_redemption_value_statement_vs_transfer(api):
    """PRD §3.8: "For a `STATEMENT_CREDIT`, the value in cents is the
    `points_requested` valued at a flat one cent per point — that is,
    `points_requested` times 1, exactly". "For a `POINTS_TRANSFER`, the value in
    partner units is `points_requested` multiplied by the partner's
    `transfer_ratio_num`, divided by its `transfer_ratio_den`, with the fractional
    remainder floored away (round-down)".

    Design: Difficulty/dual_variant_calc/statement_credit_cents_vs_points_transfer_units_on_redemption
    """
    set_clock("2026-07-01T00:00:00Z")
    prod = create_product(signup_bonus_spend_threshold_cents=100000)
    partner = create_transfer_partner(name="SkyMiles", partner_type="AIRLINE",
                                       transfer_ratio_num=5, transfer_ratio_den=4, min_transfer_points=1000)
    acct = create_active_account(card_product_id=prod["id"])
    create_and_post_transaction(acct["id"], 250000, category_code="OTHER", transacted_at="2026-07-02T00:00:00Z")
    create_and_post_transaction(acct["id"], 250000, category_code="OTHER", transacted_at="2026-07-03T00:00:00Z")

    red_sc = create_redemption(acct["id"], "STATEMENT_CREDIT", 2500, account_version(acct["id"]))
    red_sc = confirm_redemption(red_sc["id"])
    assert red_sc["redeemed_value"] == 2500, (
        f"STATEMENT_CREDIT 2500 pts -> 2500 cents, got {red_sc['redeemed_value']}"
    )
    red_pt = create_redemption(acct["id"], "POINTS_TRANSFER", 2500, account_version(acct["id"]),
                               transfer_partner_id=partner["id"])
    red_pt = confirm_redemption(red_pt["id"])
    assert red_pt["redeemed_value"] == 3125, (
        f"POINTS_TRANSFER 2500 @5:4 -> floor(3125)=3125 units, got {red_pt['redeemed_value']}"
    )
    assert red_sc["redeemed_value"] != red_pt["redeemed_value"], (
        "same 2500 points must yield different redeemed_value across the two types"
    )


def test_redemption_branch_reject_vs_confirm_reverse(api):
    """PRD §3.8: "Rejecting instead advances the redemption from `PENDING` to the
    terminal `REJECTED` state, consuming no lots and changing no balance."
    PRD §3.8: "The account's `points_balance` is recomputed, with a net change of
    exactly plus the `points_requested` — the reversal identity of §2.6."

    Design: Difficulty/non_linear_state_machine/redemption_branch_confirmed_vs_rejected_plus_reverse_revert
    """
    set_clock("2026-07-01T00:00:00Z")
    acct = _balance_account(100000)  # balance 1000
    rej = create_redemption(acct["id"], "STATEMENT_CREDIT", 200, account_version(acct["id"]))
    rej = validate_success(api.reject_redemption(rej["id"], _OPS))
    assert rej["status"] == "REJECTED", f"rejected redemption must be REJECTED, got {rej['status']!r}"

    conf = create_redemption(acct["id"], "STATEMENT_CREDIT", 300, account_version(acct["id"]))
    confirm_redemption(conf["id"])
    rev = validate_success(api.reverse_redemption(conf["id"], _OPS))
    assert rev["status"] == "REVERSED", f"reversed redemption must be REVERSED, got {rev['status']!r}"

    acct = get_account(acct["id"])
    assert acct["points_balance"] == 1000, (
        f"reject consumes nothing and confirm+reverse nets zero -> balance 1000, got {acct['points_balance']}"
    )


def test_points_transfer_floors_fractional_units(api):
    """PRD §3.8: "the value in partner units is `points_requested` multiplied by
    the partner's `transfer_ratio_num`, divided by its `transfer_ratio_den`, with
    the fractional remainder floored away (round-down)".

    Design: Corner/calculations/points_transfer_floors_fractional_units
    """
    set_clock("2026-07-01T00:00:00Z")
    prod = create_product(signup_bonus_spend_threshold_cents=999999)
    partner = create_transfer_partner(name="SkyMiles", partner_type="AIRLINE",
                                       transfer_ratio_num=5, transfer_ratio_den=4, min_transfer_points=1000)
    acct = create_active_account(card_product_id=prod["id"])
    create_and_post_transaction(acct["id"], 300000, category_code="OTHER", transacted_at="2026-07-02T00:00:00Z")
    red = create_redemption(acct["id"], "POINTS_TRANSFER", 2503, account_version(acct["id"]),
                            transfer_partner_id=partner["id"])
    red = confirm_redemption(red["id"])
    assert red["redeemed_value"] == 3128, (
        f"2503 @5:4 = 3128.75 -> floor 3128, got {red['redeemed_value']}"
    )


def test_fifo_lot_consumption_order_by_expiry(api):
    """PRD §3.8: "Confirmation consumes `points_requested` from the account's
    `ACTIVE` PointsLot rows in FIFO order — ordered by ascending `expires_at`,
    breaking ties by ascending `created_at` — decrementing each touched lot's
    `remaining_points` ... Any lot whose `remaining_points` reaches 0 transitions
    to `CONSUMED`."

    Design: Corner/calculations/fifo_lot_consumption_order_by_expiry
    """
    set_clock("2026-07-01T00:00:00Z")
    prod = create_product(signup_bonus_spend_threshold_cents=999999)
    acct = create_active_account(card_product_id=prod["id"])
    txnA = create_and_post_transaction(acct["id"], 100000, category_code="OTHER", transacted_at="2026-07-02T00:00:00Z")
    set_clock("2026-07-10T00:00:00Z")
    txnB = create_and_post_transaction(acct["id"], 75000, category_code="OTHER", transacted_at="2026-07-10T00:00:00Z")

    red = create_redemption(acct["id"], "STATEMENT_CREDIT", 1200, account_version(acct["id"]))
    confirm_redemption(red["id"])

    lotsA = list_lots_by_source_txn(txnA["id"])
    lotsB = list_lots_by_source_txn(txnB["id"])
    assert lotsA and lotsA[0]["remaining_points"] == 0, (
        f"earlier-expiring lot A must be drained to 0, got {lotsA[0]['remaining_points'] if lotsA else 'none'}"
    )
    assert lotsA[0]["status"] == "CONSUMED", f"emptied lot A must be CONSUMED, got {lotsA[0]['status']}"
    assert lotsB and lotsB[0]["remaining_points"] == 550, (
        f"later lot B must retain 550, got {lotsB[0]['remaining_points'] if lotsB else 'none'}"
    )
    assert lotsB[0]["status"] == "ACTIVE", f"partially-consumed lot B must stay ACTIVE, got {lotsB[0]['status']}"


def test_points_transfer_requires_partner_active(api):
    """PRD §3.8: "For a points transfer, the referenced `TransferPartner` must be
    `ACTIVE`; a transfer to a `SUSPENDED` partner is rejected with
    `ERR_CROSS_PRODUCT_MISMATCH` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/points_transfer_requires_partner_active
    """
    set_clock("2026-07-01T00:00:00Z")
    prod = create_product(signup_bonus_spend_threshold_cents=999999)
    partner = create_transfer_partner(name="SkyMiles", partner_type="AIRLINE",
                                       transfer_ratio_num=1, transfer_ratio_den=1, min_transfer_points=100)
    suspend_transfer_partner(partner["id"])
    acct = create_active_account(card_product_id=prod["id"])
    create_and_post_transaction(acct["id"], 200000, category_code="OTHER", transacted_at="2026-07-02T00:00:00Z")
    res = api.create_redemption(
        {
            "card_account_id": acct["id"], "redemption_type": "POINTS_TRANSFER",
            "points_requested": 1000, "transfer_partner_id": partner["id"],
            "expected_card_account_version": account_version(acct["id"]),
        },
        make_cardholder_headers(acct["id"]),
    )
    validate_error(res, ApiErrorId.ERR_CROSS_PRODUCT_MISMATCH.value)


def test_min_transfer_points_boundary(api):
    """PRD §3.8: "For a points transfer, `points_requested` must be at least the
    partner's `min_transfer_points`; falling below that floor is rejected with
    `ERR_BELOW_MIN_TRANSFER` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/min_transfer_points_boundary_on_redemption_create
    """
    set_clock("2026-07-01T00:00:00Z")
    prod = create_product(signup_bonus_spend_threshold_cents=999999)
    partner = create_transfer_partner(name="SkyMiles", partner_type="AIRLINE",
                                       transfer_ratio_num=1, transfer_ratio_den=1, min_transfer_points=1000)
    acct = create_active_account(card_product_id=prod["id"])
    create_and_post_transaction(acct["id"], 200000, category_code="OTHER", transacted_at="2026-07-02T00:00:00Z")
    v = account_version(acct["id"])
    chh = make_cardholder_headers(acct["id"])
    # 999 (floor - 1) is rejected; the rejected create does not advance version.
    below = api.create_redemption(
        {"card_account_id": acct["id"], "redemption_type": "POINTS_TRANSFER", "points_requested": 999,
         "transfer_partner_id": partner["id"], "expected_card_account_version": v},
        chh,
    )
    validate_error(below, ApiErrorId.ERR_BELOW_MIN_TRANSFER.value)
    # 1000 (exact floor, >=) succeeds at the same unchanged version.
    ok = api.create_redemption(
        {"card_account_id": acct["id"], "redemption_type": "POINTS_TRANSFER", "points_requested": 1000,
         "transfer_partner_id": partner["id"], "expected_card_account_version": v},
        chh,
    )
    created = validate_success(ok, expected_status=201)
    assert created["status"] == "PENDING", f"exact-floor transfer must succeed PENDING, got {created['status']!r}"


def test_partner_field_mismatch_on_statement_credit(api):
    """PRD §3.8: "The `transfer_partner_id` must be present exactly when
    `redemption_type` is `POINTS_TRANSFER` and must be absent when it is
    `STATEMENT_CREDIT`; supplying it for a statement credit, or omitting it for a
    points transfer, is rejected with `ERR_PARTNER_FIELD_MISMATCH` (HTTP 422)."

    Design: Corner/validations/partner_field_mismatch_on_statement_credit
    """
    set_clock("2026-07-01T00:00:00Z")
    prod = create_product(signup_bonus_spend_threshold_cents=999999)
    partner = create_transfer_partner(name="SkyMiles", partner_type="AIRLINE",
                                       transfer_ratio_num=1, transfer_ratio_den=1, min_transfer_points=100)
    acct = create_active_account(card_product_id=prod["id"])
    create_and_post_transaction(acct["id"], 100000, category_code="OTHER", transacted_at="2026-07-02T00:00:00Z")
    res = api.create_redemption(
        {"card_account_id": acct["id"], "redemption_type": "STATEMENT_CREDIT", "points_requested": 200,
         "transfer_partner_id": partner["id"], "expected_card_account_version": account_version(acct["id"])},
        make_cardholder_headers(acct["id"]),
    )
    validate_error(res, ApiErrorId.ERR_PARTNER_FIELD_MISMATCH.value)


def test_insufficient_points_on_create_rejected(api):
    """PRD §3.8: "At create time, and again when the redemption is confirmed,
    `points_requested` must not exceed the account's `points_balance`; an
    insufficient balance is rejected with `ERR_INSUFFICIENT_POINTS` (HTTP 422)."

    Design: Corner/validations/insufficient_points_on_create_rejected
    """
    set_clock("2026-07-01T00:00:00Z")
    acct = _balance_account(100000)  # balance 1000
    res = api.create_redemption(
        {"card_account_id": acct["id"], "redemption_type": "STATEMENT_CREDIT", "points_requested": 5000,
         "expected_card_account_version": account_version(acct["id"])},
        make_cardholder_headers(acct["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_POINTS.value)


def test_confirm_redemption_twice_idempotency_rejected(api):
    """PRD §3.8: "Confirming advances the redemption from `PENDING` to
    `CONFIRMED`; it is permitted only when the redemption is `PENDING`".

    Design: Corner/state_machines/confirm_redemption_twice_idempotency_rejected
    """
    set_clock("2026-07-01T00:00:00Z")
    acct = _balance_account(100000)  # balance 1000
    red = create_redemption(acct["id"], "STATEMENT_CREDIT", 200, account_version(acct["id"]))
    confirm_redemption(red["id"])
    res = api.confirm_redemption(red["id"], _OPS)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
    acct = get_account(acct["id"])
    assert acct["points_balance"] == 800, (
        f"points consumed exactly once -> balance 800, got {acct['points_balance']}"
    )


def test_reverse_non_confirmed_redemption_rejected(api):
    """PRD §3.8: "A `RewardsOps` operator may reverse a redemption only while it
    is `CONFIRMED`, moving it to the terminal `REVERSED` state."

    Design: Corner/state_machines/reverse_non_confirmed_redemption_rejected
    """
    set_clock("2026-07-01T00:00:00Z")
    acct = _balance_account(100000)
    red = create_redemption(acct["id"], "STATEMENT_CREDIT", 200, account_version(acct["id"]))
    res = api.reverse_redemption(red["id"], _OPS)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
