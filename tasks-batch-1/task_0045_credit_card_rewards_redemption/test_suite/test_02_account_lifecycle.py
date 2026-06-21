"""CardAccount lifecycle: initial state, activation, close, and the
close-forfeiture cascade (PRD §3.2)."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_cardholder_headers,
    set_clock,
    create_product,
    create_account,
    create_active_account,
    setup_account_with_balance,
    create_and_post_transaction,
    get_account,
    account_version,
    create_redemption,
    list_account_lots,
)

_ADMIN = TEST_USERS["program_admin_headers"]


def test_account_initial_state_is_pending(api):
    """PRD §3.2: "A new account starts in `status` `PENDING`; the account
    `status` enumerates `PENDING`, `ACTIVE`, and `CLOSED`."

    Design: Corner/state_machines/account_initial_state_is_pending
    """
    set_clock("2026-07-01T00:00:00Z")
    prod = create_product()
    res = api.create_account({"card_product_id": prod["id"], "cardholder_name": "Ada"}, _ADMIN)
    acct = validate_success(res, expected_status=201)
    assert acct["status"] == "PENDING", f"new account must be PENDING, got {acct['status']!r}"


def test_transaction_on_pending_account_rejected(api):
    """PRD §3.2: "An account may only transact, redeem, or activate categories
    while `ACTIVE`; attempting any of these against an account in the wrong state
    is rejected with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/transaction_on_pending_account_rejected
    """
    set_clock("2026-07-01T00:00:00Z")
    prod = create_product()
    acct = create_account(prod["id"])  # PENDING, never activated
    res = api.create_transaction(
        {
            "card_account_id": acct["id"],
            "amount_cents": 5000,
            "category_code": "OTHER",
            "transacted_at": "2026-07-02T00:00:00Z",
        },
        _ADMIN,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_activate_account_transitions_pending_to_active(api):
    """PRD §3.2: "Activation moves an account from `PENDING` to `ACTIVE`."
    PRD §2.8: "activating an account ... each bump the affected
    `CardAccount.version` by exactly one."

    Design: Corner/endpoints/activate_account_transitions_pending_to_active
    """
    set_clock("2026-07-01T00:00:00Z")
    prod = create_product()
    acct = create_account(prod["id"])
    assert acct["version"] == 1, f"PENDING account must be version 1, got {acct['version']}"
    res = api.activate_account(acct["id"], _ADMIN)
    data = validate_success(res)
    assert data["status"] == "ACTIVE", f"account must be ACTIVE after activate, got {data['status']!r}"
    assert data["version"] == 2, f"activate must bump version to 2, got {data['version']}"


def test_close_account_cascades_lot_forfeiture(api):
    """PRD §3.2: "Closing forfeits all unredeemed points: every `ACTIVE`
    PointsLot of the account transitions to `EXPIRED` with its `remaining_points`
    zeroed, and the account's `points_balance` is recomputed to 0."

    Design: Corner/state_machines/close_account_cascades_lot_forfeiture
    """
    set_clock("2026-07-01T00:00:00Z")
    acct, _ = setup_account_with_balance(
        amount_cents=100000, product_overrides={"signup_bonus_spend_threshold_cents": 999999}
    )
    assert acct["points_balance"] == 1000, f"precondition balance 1000, got {acct['points_balance']}"
    res = api.close_account(acct["id"], _ADMIN)
    closed = validate_success(res)
    assert closed["status"] == "CLOSED", f"account must be CLOSED, got {closed['status']!r}"
    assert closed["points_balance"] == 0, f"points_balance must forfeit to 0, got {closed['points_balance']}"
    lots = list_account_lots(acct["id"])
    earn = [l for l in lots if l["lot_type"] == "EARN"]
    assert earn and earn[0]["status"] == "EXPIRED", (
        f"EARN lot must be EXPIRED after close, got {earn[0]['status'] if earn else 'none'}"
    )


def test_close_account_with_pending_redemption_rejected(api):
    """PRD §3.2: "Closing is permitted only when the account is `ACTIVE` and
    there is **no** redemption for the account currently in `PENDING` status; a
    close attempted with a pending redemption outstanding is rejected with
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/close_account_with_pending_redemption_rejected
    """
    set_clock("2026-07-01T00:00:00Z")
    acct, _ = setup_account_with_balance(
        amount_cents=100000, product_overrides={"signup_bonus_spend_threshold_cents": 999999}
    )
    create_redemption(acct["id"], "STATEMENT_CREDIT", 200, account_version(acct["id"]))
    res = api.close_account(acct["id"], _ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
    assert get_account(acct["id"])["status"] == "ACTIVE", "account must remain ACTIVE after rejected close"
