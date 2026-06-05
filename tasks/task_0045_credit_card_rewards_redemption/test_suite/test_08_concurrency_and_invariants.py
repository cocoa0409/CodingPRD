"""Optimistic-concurrency control on redemption creation and the
compensating-action conservation invariants (PRD §2.6, §2.7, §2.8, §3.4, §3.8)."""
from test_helpers import (
    validate_success,
    validate_error,
    TEST_USERS,
    make_cardholder_headers,
    set_clock,
    create_product,
    create_active_account,
    setup_account_with_balance,
    create_and_post_transaction,
    create_redemption,
    confirm_redemption,
    get_account,
    account_version,
    ApiErrorId,
)

_ADMIN = TEST_USERS["program_admin_headers"]
_OPS = TEST_USERS["rewards_ops_headers"]


def test_stale_account_version_on_redemption_create(api):
    """PRD §2.7: "If `expected_card_account_version` does not equal the account's
    current `version` at the moment the redemption is created — because some other
    writer (another redemption that drew down the balance, or a refund that clawed
    points back) has advanced the account's `version` since the client last read
    it — the request is rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412)."

    Design: Corner/errors/stale_account_version_on_redemption_create
    """
    set_clock("2026-07-01T00:00:00Z")
    acct, _ = setup_account_with_balance(
        amount_cents=200000, product_overrides={"signup_bonus_spend_threshold_cents": 999999}
    )  # balance 2000
    v_obs = account_version(acct["id"])
    chh = make_cardholder_headers(acct["id"])
    # First redemption create succeeds and advances the account version.
    validate_success(
        api.create_redemption(
            {"card_account_id": acct["id"], "redemption_type": "STATEMENT_CREDIT",
             "points_requested": 100, "expected_card_account_version": v_obs}, chh,
        ),
        expected_status=201,
    )
    # Second create reuses the now-stale version.
    res = api.create_redemption(
        {"card_account_id": acct["id"], "redemption_type": "STATEMENT_CREDIT",
         "points_requested": 100, "expected_card_account_version": v_obs}, chh,
    )
    validate_error(res, ApiErrorId.ERR_STALE_ACCOUNT_VERSION.value)


def test_correct_version_redemption_succeeds_and_bumps_version(api):
    """PRD §2.7: "A request to create a redemption must include
    `expected_card_account_version`, carrying the `version` of the target
    `CardAccount` that the client last observed."
    PRD §2.8: "creating a redemption ... each bump the affected
    `CardAccount.version` by exactly one."

    Design: Corner/errors/correct_version_redemption_succeeds
    """
    set_clock("2026-07-01T00:00:00Z")
    acct, _ = setup_account_with_balance(
        amount_cents=200000, product_overrides={"signup_bonus_spend_threshold_cents": 999999}
    )  # balance 2000
    v_obs = account_version(acct["id"])
    res = api.create_redemption(
        {"card_account_id": acct["id"], "redemption_type": "STATEMENT_CREDIT",
         "points_requested": 100, "expected_card_account_version": v_obs},
        make_cardholder_headers(acct["id"]),
    )
    red = validate_success(res, expected_status=201)
    assert red["status"] == "PENDING", f"created redemption must be PENDING, got {red['status']!r}"
    assert get_account(acct["id"])["version"] == v_obs + 1, (
        f"redemption create must bump account version to {v_obs + 1}, got {get_account(acct['id'])['version']}"
    )


def test_post_then_refund_conserves_points_balance(api):
    """PRD §3.4: "The refund claws back the `EARN` PointsLot minted by that
    transaction: the lot's `status` becomes `CLAWED_BACK`."
    PRD §2.6: "the result must equal the account's `points_balance`. ...
    `points_balance` is always the sum of `remaining_points` over the account's
    PointsLot rows that are still in `ACTIVE` status".

    Design: Difficulty/compensating_invariant/post_then_refund_conserves_account_points_balance
    """
    set_clock("2026-07-01T00:00:00Z")
    prod = create_product(signup_bonus_spend_threshold_cents=999999)
    acct = create_active_account(card_product_id=prod["id"])
    txn = create_and_post_transaction(acct["id"], 100000, category_code="OTHER", transacted_at="2026-07-02T00:00:00Z")
    after_post = get_account(acct["id"])
    assert after_post["points_balance"] == 1000, (
        f"POST must mint 1000 points, got {after_post['points_balance']}"
    )
    validate_success(api.refund_transaction(txn["id"], _ADMIN))
    after_refund = get_account(acct["id"])
    assert after_refund["points_balance"] == 0, (
        f"REFUND must claw back exactly 1000 -> balance 0 (pre-POST value), got {after_refund['points_balance']}"
    )


def test_confirm_then_reverse_conserves_consumed_lot_points(api):
    """PRD §3.8: "The reversal restores points to the exact lots recorded in
    `lots_consumed`: each such lot's `remaining_points` is increased by the
    `points_taken` originally recorded for it. ... The account's `points_balance`
    is recomputed, with a net change of exactly plus the `points_requested` — the
    reversal identity of §2.6."

    Design: Difficulty/compensating_invariant/confirm_then_reverse_conserves_consumed_lot_points
    """
    set_clock("2026-07-01T00:00:00Z")
    prod = create_product(signup_bonus_spend_threshold_cents=999999)
    acct = create_active_account(card_product_id=prod["id"])
    create_and_post_transaction(acct["id"], 100000, category_code="OTHER", transacted_at="2026-07-02T00:00:00Z")  # 1000
    create_and_post_transaction(acct["id"], 75000, category_code="OTHER", transacted_at="2026-07-03T00:00:00Z")   # 750
    acct = get_account(acct["id"])
    assert acct["points_balance"] == 1750, f"precondition balance 1750, got {acct['points_balance']}"

    red = create_redemption(acct["id"], "STATEMENT_CREDIT", 1200, account_version(acct["id"]))
    confirm_redemption(red["id"])
    after_confirm = get_account(acct["id"])
    assert after_confirm["points_balance"] == 550, (
        f"confirm consumes 1200 -> balance 550, got {after_confirm['points_balance']}"
    )
    rev = validate_success(api.reverse_redemption(red["id"], _OPS))
    assert rev["status"] == "REVERSED", f"redemption must be REVERSED, got {rev['status']!r}"
    after_reverse = get_account(acct["id"])
    assert after_reverse["points_balance"] == 1750, (
        f"reverse restores exactly +1200 -> balance 1750, got {after_reverse['points_balance']}"
    )
