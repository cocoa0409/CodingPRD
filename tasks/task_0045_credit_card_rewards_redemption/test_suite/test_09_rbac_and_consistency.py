"""Role-based access control, ownership enforcement, immediate consistency, and
derived-field reconciliation (PRD §2.1, §2.10, §3.4, §3.6)."""
from test_helpers import (
    validate_success,
    validate_error,
    TEST_USERS,
    make_cardholder_headers,
    make_headers,
    set_clock,
    create_product,
    create_active_account,
    setup_account_with_balance,
    create_pending_transaction,
    create_and_post_transaction,
    get_account,
    account_version,
    ApiErrorId,
)

_ADMIN = TEST_USERS["program_admin_headers"]
_OPS = TEST_USERS["rewards_ops_headers"]


def test_cardholder_cannot_post_transaction(api):
    """PRD §2.1: "When an authenticated caller invokes an operation that their
    role is not allowed to perform, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403). A `ProgramAdmin` ... records, posts,
    declines, and refunds transactions."

    Design: Corner/rbac/cardholder_cannot_post_transaction
    """
    set_clock("2026-07-01T00:00:00Z")
    prod = create_product(signup_bonus_spend_threshold_cents=999999)
    acct = create_active_account(card_product_id=prod["id"])
    txn = create_pending_transaction(acct["id"], 50000, category_code="OTHER", transacted_at="2026-07-02T00:00:00Z")
    res = api.post_transaction(txn["id"], make_cardholder_headers(acct["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_rewardsops_cannot_post_transaction(api):
    """PRD §2.1: "When an authenticated caller invokes an operation that their
    role is not allowed to perform, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403). A `ProgramAdmin` ... records, posts,
    declines, and refunds transactions."

    Design: Corner/rbac/rewardsops_cannot_post_transaction
    """
    set_clock("2026-07-01T00:00:00Z")
    prod = create_product(signup_bonus_spend_threshold_cents=999999)
    acct = create_active_account(card_product_id=prod["id"])
    txn = create_pending_transaction(acct["id"], 50000, category_code="OTHER", transacted_at="2026-07-02T00:00:00Z")
    res = api.post_transaction(txn["id"], _OPS)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_cardholder_cannot_redeem_other_account(api):
    """PRD §2.1: "when a `Cardholder` requests a redemption ... the
    `card_account_id` involved must equal `X-User-ID`; otherwise the request is
    rejected with `ERR_NOT_ACCOUNT_OWNER` (HTTP 403)."

    Design: Corner/rbac/cardholder_cannot_redeem_other_account
    """
    set_clock("2026-07-01T00:00:00Z")
    prod = create_product(signup_bonus_spend_threshold_cents=999999)
    acctA = create_active_account(card_product_id=prod["id"])
    acctB = create_active_account(card_product_id=prod["id"])
    create_and_post_transaction(acctA["id"], 100000, category_code="OTHER", transacted_at="2026-07-02T00:00:00Z")
    # Cardholder authenticated as account B tries to redeem against account A.
    res = api.create_redemption(
        {"card_account_id": acctA["id"], "redemption_type": "STATEMENT_CREDIT",
         "points_requested": 100, "expected_card_account_version": account_version(acctA["id"])},
        make_cardholder_headers(acctB["id"]),
    )
    validate_error(res, ApiErrorId.ERR_NOT_ACCOUNT_OWNER.value)


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one of
    the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    set_clock("2026-07-01T00:00:00Z")
    prod = create_product()
    res = api.get_product(prod["id"], make_headers("some-user", "Stranger"))
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_computed_read_account_summary_balance(api):
    """PRD §2.6: "`points_balance` is always the sum of `remaining_points` over
    the account's PointsLot rows that are still in `ACTIVE` status".
    PRD §2.1: "A `Cardholder` is the account owner: it ... reads its own
    resources."

    Design: Corner/endpoints/computed_read_account_summary_balance
    """
    set_clock("2026-07-01T00:00:00Z")
    prod = create_product(signup_bonus_spend_threshold_cents=999999)
    acct = create_active_account(card_product_id=prod["id"])
    create_and_post_transaction(acct["id"], 100000, category_code="OTHER", transacted_at="2026-07-02T00:00:00Z")
    # The owning Cardholder reads its own account and sees the computed balance.
    res = api.get_account(acct["id"], make_cardholder_headers(acct["id"]))
    data = validate_success(res)
    assert data["points_balance"] == 1000, (
        f"GET /accounts/{{id}} must report points_balance 1000, got {data['points_balance']}"
    )


def test_post_balance_visible_in_same_response(api):
    """PRD §3.4: "the lot's points are added into the account's `points_balance`."
    PRD §2.6: "`points_balance` is always the sum of `remaining_points` over the
    account's PointsLot rows that are still in `ACTIVE` status, and it is
    recomputed on every mint, consumption, clawback, and expiry."

    Design: Corner/consistency_model/post_balance_visible_in_same_response
    """
    set_clock("2026-07-01T00:00:00Z")
    prod = create_product(signup_bonus_spend_threshold_cents=999999)
    acct = create_active_account(card_product_id=prod["id"])
    txn = create_pending_transaction(acct["id"], 100000, category_code="OTHER", transacted_at="2026-07-02T00:00:00Z")
    posted = validate_success(api.post_transaction(txn["id"], _ADMIN))
    assert posted["earned_points"] == 1000, f"posted txn earns 1000, got {posted['earned_points']}"
    # An immediate read reflects the new balance with no lag.
    acct = get_account(acct["id"])
    assert acct["points_balance"] == 1000, (
        f"GET right after post must show balance 1000, got {acct['points_balance']}"
    )


def test_derived_balance_reconciliation_after_refund(api):
    """PRD §3.4: "The refund then subtracts the `amount_cents` from the account's
    `annual_spend_cents` (floored at 0) and re-derives `current_tier_index`, which
    may demote the tier".
    PRD §3.6: "The index is re-derived on every posting (which adds spend) and
    every refund (which subtracts spend and may therefore demote the tier)."

    Design: Corner/cross_cutting_complexity_layers/derived_balance_reconciliation_after_refund
    """
    set_clock("2026-07-01T00:00:00Z")
    prod = create_product(
        name="Tier Visa", base_earn_rate_bps=100, signup_bonus_spend_threshold_cents=999999,
        signup_bonus_window_days=365, tier_thresholds=[{"min_annual_spend_cents": 100000, "tier_multiplier_bps": 150}],
    )
    acct = create_active_account(card_product_id=prod["id"])
    txn = create_and_post_transaction(acct["id"], 100000, category_code="OTHER", transacted_at="2026-07-02T00:00:00Z")
    before = get_account(acct["id"])
    assert before["current_tier_index"] == 1, f"single 100000 posting must promote to tier 1, got {before['current_tier_index']}"
    assert before["annual_spend_cents"] == 100000, f"annual_spend must be 100000, got {before['annual_spend_cents']}"
    validate_success(api.refund_transaction(txn["id"], _ADMIN))
    after = get_account(acct["id"])
    assert after["annual_spend_cents"] == 0, f"refund must decrement annual_spend to 0, got {after['annual_spend_cents']}"
    assert after["current_tier_index"] == 0, f"refund must demote tier to 0, got {after['current_tier_index']}"
