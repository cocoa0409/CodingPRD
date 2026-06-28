"""Auto-categorization at post time: priority/created_at ranking and no-match handling.

Translates Corner queue (B) section calculations (auto_categorize).
"""
from test_helpers import (
    validate_success, get_success_data, admin_headers,
    create_household, create_account, ingest_transaction, post_transaction,
    setup_household_period_category,
)


def test_auto_categorize_priority_then_created_at(api):
    """PRD §3.4: "Among candidates the winner is the one with the lowest priority (a lower
    number wins); ties on priority are broken by earliest created_at (ascending), never by
    id."
    PRD §3.4: "The winning rule's budget_category_id is assigned — but only if that
    category belongs to the household's current period".

    Design: Corner/calculations/auto_categorize_priority_then_created_at
    """
    hh, owner_headers, period, misc = setup_household_period_category(
        income_expected_cents=20000, cat_name="Misc", allocated_cents=10000)
    groc = get_success_data(api.create_category(
        hh["id"], period["id"], {"name": "Groceries", "allocated_cents": 10000},
        owner_headers))
    # priority 2 -> Misc created first; priority 1 -> Groceries created second.
    get_success_data(api.create_category_rule(
        hh["id"], {"match_substring": "foods", "budget_category_id": misc["id"],
                   "priority": 2}, owner_headers))
    get_success_data(api.create_category_rule(
        hh["id"], {"match_substring": "foods", "budget_category_id": groc["id"],
                   "priority": 1}, owner_headers))
    acc = create_account(hh["id"], owner_headers, opening_balance_cents=50000)
    txn = ingest_transaction(acc["id"], amount_cents=-3000, merchant_name="WHOLE FOODS")
    posted = post_transaction(acc["id"], txn["id"])

    assert posted["budget_category_id"] == groc["id"], \
        f"priority-1 rule wins -> Groceries, got {posted['budget_category_id']}"
    groc_data = validate_success(api.get_category(groc["id"], owner_headers))
    assert groc_data["spent_cents"] == 3000, \
        f"3000 charged to Groceries, got {groc_data['spent_cents']}"
    misc_data = validate_success(api.get_category(misc["id"], owner_headers))
    assert misc_data["spent_cents"] == 0, \
        f"Misc untouched, got {misc_data['spent_cents']}"


def test_auto_categorize_no_match_leaves_uncategorized(api):
    """PRD §3.4: "If no rule matches at all, the transaction posts uncategorized, leaving
    its budget_category_id null and producing no envelope impact."

    Design: Corner/calculations/auto_categorize_no_match_leaves_uncategorized
    """
    hh, owner_headers, period, cat = setup_household_period_category(
        income_expected_cents=10000, cat_name="Online", allocated_cents=10000)
    get_success_data(api.create_category_rule(
        hh["id"], {"match_substring": "amazon", "budget_category_id": cat["id"],
                   "priority": 1}, owner_headers))
    acc = create_account(hh["id"], owner_headers, opening_balance_cents=50000)
    txn = ingest_transaction(acc["id"], amount_cents=-3000, merchant_name="GROCER")
    posted = post_transaction(acc["id"], txn["id"])

    assert posted["budget_category_id"] is None, \
        f"no match -> uncategorized, got {posted['budget_category_id']}"
    cat_data = validate_success(api.get_category(cat["id"], owner_headers))
    assert cat_data["spent_cents"] == 0, \
        f"no envelope impact, got {cat_data['spent_cents']}"
