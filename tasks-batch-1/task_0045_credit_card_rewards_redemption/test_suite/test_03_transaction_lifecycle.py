"""Transaction lifecycle: the PENDING -> {POSTED, DECLINED} fork, the
POSTED -> REFUNDED revert, invalid transitions, terminal lockdown, and the
account-state gate on posting (PRD §3.3, §3.4)."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    set_clock,
    create_product,
    create_account,
    create_active_account,
    create_pending_transaction,
    post_transaction,
    create_and_post_transaction,
    get_account,
)

_ADMIN = TEST_USERS["program_admin_headers"]


def test_transaction_decline_then_post_refund_branches(api):
    """PRD §3.3: "Declining advances it from `PENDING` to `DECLINED`: the
    transaction's provisional contribution is removed from the account's
    `pending_points`, no lot is minted, and no spend counter is touched."
    PRD §3.4: "A `ProgramAdmin` may refund a transaction only while it is
    `POSTED`, moving it to the terminal `REFUNDED` state. The refund claws back
    the `EARN` PointsLot minted by that transaction".

    Design: Difficulty/non_linear_state_machine/transaction_branch_posted_vs_declined_plus_refund_revert
    """
    set_clock("2026-07-01T00:00:00Z")
    prod = create_product(signup_bonus_spend_threshold_cents=999999)
    acct = create_active_account(card_product_id=prod["id"])
    decl = create_pending_transaction(acct["id"], 50000, category_code="OTHER", transacted_at="2026-07-02T00:00:00Z")
    ref = create_pending_transaction(acct["id"], 30000, category_code="OTHER", transacted_at="2026-07-03T00:00:00Z")

    decl = validate_success(api.decline_transaction(decl["id"], _ADMIN))
    assert decl["status"] == "DECLINED", f"declined txn must be DECLINED, got {decl['status']!r}"
    post_transaction(ref["id"])
    ref = validate_success(api.refund_transaction(ref["id"], _ADMIN))
    assert ref["status"] == "REFUNDED", f"refunded txn must be REFUNDED, got {ref['status']!r}"

    acct = get_account(acct["id"])
    assert acct["pending_points"] == 0, f"pending_points must be 0 after decline+refund, got {acct['pending_points']}"
    assert acct["points_balance"] == 0, f"points_balance must be 0 (refund clawed back), got {acct['points_balance']}"


def test_transaction_branch_divergent_side_effects(api):
    """PRD §3.4: "when the computed `earned_points` is greater than 0, the system
    mints a new **PointsLot** of `lot_type` `EARN` ... the lot's points are added
    into the account's `points_balance`."
    PRD §3.3: "Declining advances it from `PENDING` to `DECLINED`: the
    transaction's provisional contribution is removed from the account's
    `pending_points`, no lot is minted, and no spend counter is touched."

    Design: Difficulty/non_linear_state_machine/transaction_branch_posted_vs_declined_plus_refund_revert
    """
    set_clock("2026-07-01T00:00:00Z")
    prod = create_product(signup_bonus_spend_threshold_cents=999999)
    acct = create_active_account(card_product_id=prod["id"])
    # POSTED branch mints a lot and credits points_balance.
    posted = create_and_post_transaction(acct["id"], 100000, category_code="OTHER", transacted_at="2026-07-02T00:00:00Z")
    assert posted["earned_points"] == 1000, f"posted txn earns 1000, got {posted['earned_points']}"
    acct1 = get_account(acct["id"])
    assert acct1["points_balance"] == 1000, f"balance must be 1000 after post, got {acct1['points_balance']}"
    # DECLINED branch credits nothing.
    decl = create_pending_transaction(acct["id"], 50000, category_code="OTHER", transacted_at="2026-07-03T00:00:00Z")
    validate_success(api.decline_transaction(decl["id"], _ADMIN))
    acct2 = get_account(acct["id"])
    assert acct2["points_balance"] == 1000, f"decline must not change points_balance, got {acct2['points_balance']}"
    assert acct2["pending_points"] == 0, f"decline must release pending_points, got {acct2['pending_points']}"


def test_decline_already_posted_transaction_rejected(api):
    """PRD §3.3: "Both posting and declining require the transaction to currently
    be `PENDING`."

    Design: Corner/state_machines/decline_already_posted_transaction_rejected
    """
    set_clock("2026-07-01T00:00:00Z")
    prod = create_product(signup_bonus_spend_threshold_cents=999999)
    acct = create_active_account(card_product_id=prod["id"])
    txn = create_and_post_transaction(acct["id"], 50000, category_code="OTHER", transacted_at="2026-07-02T00:00:00Z")
    res = api.decline_transaction(txn["id"], _ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
    after = validate_success(api.get_transaction(txn["id"], _ADMIN))
    assert after["status"] == "POSTED", f"transaction must remain POSTED after rejected decline, got {after['status']!r}"


def test_refunded_transaction_is_terminal(api):
    """PRD §3.4: "A `ProgramAdmin` may refund a transaction only while it is
    `POSTED`, moving it to the terminal `REFUNDED` state."

    Design: Corner/state_machines/refunded_transaction_is_terminal
    """
    set_clock("2026-07-01T00:00:00Z")
    prod = create_product(signup_bonus_spend_threshold_cents=999999)
    acct = create_active_account(card_product_id=prod["id"])
    txn = create_and_post_transaction(acct["id"], 50000, category_code="OTHER", transacted_at="2026-07-02T00:00:00Z")
    validate_success(api.refund_transaction(txn["id"], _ADMIN))
    res = api.refund_transaction(txn["id"], _ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_transaction_post_requires_account_active(api):
    """PRD §3.4: "Posting a `PENDING` transaction is the central earning event,
    and it is permitted only when the transaction is `PENDING` and its owning
    account is `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/transaction_post_requires_account_active
    """
    set_clock("2026-07-01T00:00:00Z")
    prod = create_product(signup_bonus_spend_threshold_cents=999999)
    acct = create_active_account(card_product_id=prod["id"])
    txn = create_pending_transaction(acct["id"], 50000, category_code="OTHER", transacted_at="2026-07-02T00:00:00Z")
    validate_success(api.close_account(acct["id"], _ADMIN))  # account now CLOSED
    res = api.post_transaction(txn["id"], _ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
    after = validate_success(api.get_transaction(txn["id"], _ADMIN))
    assert after["status"] == "PENDING", f"transaction must remain PENDING after rejected post, got {after['status']!r}"


def test_post_requires_account_active_alt_closed_path(api):
    """PRD §3.2: "An account may only transact, redeem, or activate categories
    while `ACTIVE`; attempting any of these against an account in the wrong state
    is rejected with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/transaction_post_requires_account_active
    """
    set_clock("2026-07-01T00:00:00Z")
    prod = create_product(signup_bonus_spend_threshold_cents=999999)
    acct = create_active_account(card_product_id=prod["id"])
    txn = create_pending_transaction(acct["id"], 80000, category_code="OTHER", transacted_at="2026-07-04T00:00:00Z")
    validate_success(api.close_account(acct["id"], _ADMIN))
    res = api.post_transaction(txn["id"], _ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_filtered_transaction_list_by_account(api):
    """PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."
    PRD §2.5: "relationships are expressed through foreign-key fields in request
    bodies rather than through nested URL segments."

    Design: Corner/endpoints/filtered_transaction_list_by_account
    """
    set_clock("2026-07-01T00:00:00Z")
    prod = create_product(signup_bonus_spend_threshold_cents=999999)
    acct = create_active_account(card_product_id=prod["id"])
    create_pending_transaction(acct["id"], 5000, category_code="OTHER", transacted_at="2026-07-02T00:00:00Z")
    create_pending_transaction(acct["id"], 6000, category_code="DINING", transacted_at="2026-07-03T00:00:00Z")
    res = api.list_transactions(_ADMIN, params={"card_account_id": acct["id"]})
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 2, f"total_count must be 2, got {meta['total_count']}"
    assert all(t["card_account_id"] == acct["id"] for t in data), "all items must belong to the filtered account"
