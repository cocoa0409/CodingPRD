"""Transaction state machine: ingest PENDING, post, recategorize cycle, removal terminal.

Translates Difficulty queue (A) non_linear_state_machine (transaction) and Corner queue
(B) state_machines transaction claims.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, admin_headers,
    ApiErrorId,
    create_household, create_account, ingest_transaction, post_transaction,
    setup_household_period_category,
)


def test_new_transaction_starts_pending(api):
    """PRD §3.3: "The new Transaction is created on its account_id with a status of
    PENDING."

    Design: Corner/state_machines/new_transaction_starts_pending
    """
    hh, owner_headers = create_household()
    acc = create_account(hh["id"], owner_headers, opening_balance_cents=10000)
    resp = api.create_transaction(
        acc["id"], {"amount_cents": -1000, "merchant_name": "Store"}, admin_headers())
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "PENDING", f"expected PENDING, got {data['status']}"


def test_post_already_posted_returns_invalid_state(api):
    """PRD §2.7: "for transition endpoints, the target must currently be in a state from
    which the requested transition is defined, otherwise ERR_INVALID_STATE."
    PRD §3.3: "Posting clears a pending transaction, advancing its status from PENDING to
    POSTED."

    Design: Corner/state_machines/post_already_posted_returns_invalid_state
    """
    hh, owner_headers = create_household()
    acc = create_account(hh["id"], owner_headers, opening_balance_cents=10000)
    txn = ingest_transaction(acc["id"], amount_cents=-1000, merchant_name="Store")
    post_transaction(acc["id"], txn["id"])
    resp = api.post_transaction(acc["id"], txn["id"], admin_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_recategorize_removed_txn_returns_invalid_state(api):
    """PRD §3.3: "a transaction may be removed from either PENDING or POSTED, landing in
    the terminal REMOVED state."
    PRD §3.3: "Recategorizing requires the transaction to currently be in a state from
    which the transition is defined; otherwise ERR_INVALID_STATE."

    Design: Corner/state_machines/recategorize_removed_txn_returns_invalid_state
    """
    hh, owner_headers, period, cat = setup_household_period_category(
        income_expected_cents=5000, cat_name="Food", allocated_cents=5000)
    acc = create_account(hh["id"], owner_headers, opening_balance_cents=10000)
    txn = ingest_transaction(acc["id"], amount_cents=-1000, merchant_name="Store")
    validate_success(api.remove_transaction(acc["id"], txn["id"], admin_headers()))
    resp = api.recategorize_transaction(
        acc["id"], txn["id"], {"budget_category_id": cat["id"]}, owner_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_recategorize_cycle_returns_to_posted_in_original_category(api):
    """PRD §3.3: "Modeled as a state machine, a POSTED transaction enters RECATEGORIZED
    and then returns to POSTED, so the loop POSTED → RECATEGORIZED → POSTED is cyclic and a
    transaction can be recategorized repeatedly."
    PRD §3.3: "from the old category (if any) this transaction's outflow is subtracted and
    that envelope's spent_cents, available_cents, and envelope_state are recomputed; then
    the transaction's budget_category_id is set to the target ... and the new category's
    spent_cents, available_cents, and envelope_state are recomputed."

    Design: Difficulty/non_linear_state_machine/transaction_recategorize_cycle
    """
    hh, owner_headers, period, food = setup_household_period_category(
        income_expected_cents=20000, cat_name="Food", allocated_cents=10000)
    fun = get_success_data(api.create_category(
        hh["id"], period["id"], {"name": "Fun", "allocated_cents": 10000}, owner_headers))
    acc = create_account(hh["id"], owner_headers, opening_balance_cents=50000)
    txn = ingest_transaction(acc["id"], amount_cents=-2000, merchant_name="Cafe",
                             budget_category_id=food["id"])
    post_transaction(acc["id"], txn["id"])

    # Recategorize to Fun, then back to Food.
    validate_success(api.recategorize_transaction(
        acc["id"], txn["id"], {"budget_category_id": fun["id"]}, owner_headers))
    final = validate_success(api.recategorize_transaction(
        acc["id"], txn["id"], {"budget_category_id": food["id"]}, owner_headers))

    assert final["status"] == "POSTED", \
        f"cycle returns to POSTED, got {final['status']}"
    assert final["budget_category_id"] == food["id"], \
        f"final category is Food, got {final['budget_category_id']}"
    fun_data = validate_success(api.get_category(fun["id"], owner_headers))
    assert fun_data["spent_cents"] == 0, \
        f"Fun unwound -> spent 0, got {fun_data['spent_cents']}"
    food_data = validate_success(api.get_category(food["id"], owner_headers))
    assert food_data["spent_cents"] == 2000, \
        f"Food re-applied -> spent 2000, got {food_data['spent_cents']}"


def test_recategorize_repeats_keeps_posted(api):
    """PRD §3.3: "a transaction can be recategorized repeatedly."
    PRD §3.3: "the loop POSTED → RECATEGORIZED → POSTED is cyclic".

    Design: Difficulty/non_linear_state_machine/transaction_recategorize_cycle
    """
    hh, owner_headers, period, food = setup_household_period_category(
        income_expected_cents=30000, cat_name="Food", allocated_cents=10000)
    fun = get_success_data(api.create_category(
        hh["id"], period["id"], {"name": "Fun", "allocated_cents": 10000}, owner_headers))
    other = get_success_data(api.create_category(
        hh["id"], period["id"], {"name": "Other", "allocated_cents": 10000}, owner_headers))
    acc = create_account(hh["id"], owner_headers, opening_balance_cents=50000)
    txn = ingest_transaction(acc["id"], amount_cents=-1000, merchant_name="Cafe",
                             budget_category_id=food["id"])
    post_transaction(acc["id"], txn["id"])

    for target in (fun["id"], other["id"], food["id"]):
        result = validate_success(api.recategorize_transaction(
            acc["id"], txn["id"], {"budget_category_id": target}, owner_headers))
        assert result["status"] == "POSTED", \
            f"each recategorize lands back in POSTED, got {result['status']}"
    assert result["budget_category_id"] == food["id"]
