"""Composite setup helpers.

Each fixture builds preconditions from scratch using only PRD-declared endpoints,
then returns the entities the tests assert against. Fixtures use get_success_data()
(lenient validator) so setup failures surface as clear "Setup failed" errors.

Identity threading: HouseholdOwner / HouseholdMember are entity_backed:Member. After
creating a household, ownership-gated calls use make_owner_headers(owner_member_id) /
make_member_headers(member_id) — never the shared placeholder constants.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import admin_headers, make_owner_headers, make_member_headers


# --------------------------------------------------------------------------- #
# Clock                                                                        #
# --------------------------------------------------------------------------- #
def set_clock(to_iso8601: str):
    """Set the logical clock (PlatformAdmin)."""
    return get_success_data(api_client.set_clock(to_iso8601, admin_headers()))


# --------------------------------------------------------------------------- #
# Households / members                                                         #
# --------------------------------------------------------------------------- #
def create_household(name="Test Household", owner_email="owner@example.com",
                     owner_display_name="Owner", base_currency=None):
    """Create a household + founding OWNER. Returns (household, owner_headers).

    household["owner_member_id"] is the OWNER Member.id; owner_headers are bound
    to it so subsequent ownership-gated calls pass the own-household check.
    """
    payload = {
        "name": name,
        "owner_email": owner_email,
        "owner_display_name": owner_display_name,
    }
    if base_currency is not None:
        payload["base_currency"] = base_currency
    hh = get_success_data(api_client.create_household(payload, admin_headers()))
    owner_headers = make_owner_headers(hh["owner_member_id"])
    return hh, owner_headers


def invite_member(household_id, owner_headers, email="member@example.com",
                  display_name="Member"):
    """Owner invites a MEMBER. Returns (member, member_headers)."""
    mem = get_success_data(api_client.create_member(
        household_id, {"email": email, "display_name": display_name}, owner_headers))
    return mem, make_member_headers(mem["id"])


# --------------------------------------------------------------------------- #
# Accounts                                                                     #
# --------------------------------------------------------------------------- #
def create_account(household_id, owner_headers, account_type="DEPOSITORY",
                   opening_balance_cents=0, institution_name="Bank"):
    """Link an account. Returns the account."""
    return get_success_data(api_client.create_account(
        household_id,
        {"institution_name": institution_name, "account_type": account_type,
         "opening_balance_cents": opening_balance_cents},
        owner_headers,
    ))


# --------------------------------------------------------------------------- #
# Periods / categories                                                         #
# --------------------------------------------------------------------------- #
def open_period(household_id, owner_headers, month="2026-01", income_expected_cents=0):
    """Open a budget period. Returns the period."""
    return get_success_data(api_client.create_budget_period(
        household_id, {"month": month, "income_expected_cents": income_expected_cents},
        owner_headers,
    ))


def create_category(household_id, period_id, owner_headers, name="Groceries",
                    allocated_cents=0, rollover_enabled=None):
    """Create an envelope. Returns the category."""
    payload = {"name": name, "allocated_cents": allocated_cents}
    if rollover_enabled is not None:
        payload["rollover_enabled"] = rollover_enabled
    return get_success_data(api_client.create_category(
        household_id, period_id, payload, owner_headers))


def setup_household_with_period(month="2026-01", income_expected_cents=0):
    """Household + one OPEN period. Returns (household, owner_headers, period)."""
    hh, owner_headers = create_household()
    period = open_period(hh["id"], owner_headers, month, income_expected_cents)
    return hh, owner_headers, period


def setup_household_period_category(month="2026-01", income_expected_cents=0,
                                    cat_name="Groceries", allocated_cents=0,
                                    rollover_enabled=None):
    """Household + OPEN period + one category.
    Returns (household, owner_headers, period, category)."""
    hh, owner_headers, period = setup_household_with_period(month, income_expected_cents)
    cat = create_category(hh["id"], period["id"], owner_headers, cat_name,
                          allocated_cents, rollover_enabled)
    return hh, owner_headers, period, cat


# --------------------------------------------------------------------------- #
# Transactions (state progression)                                            #
# --------------------------------------------------------------------------- #
def ingest_transaction(account_id, amount_cents=-1000, merchant_name="Store",
                       budget_category_id=None):
    """Ingest a PENDING transaction (PlatformAdmin). Returns the transaction."""
    payload = {"amount_cents": amount_cents, "merchant_name": merchant_name}
    if budget_category_id is not None:
        payload["budget_category_id"] = budget_category_id
    return get_success_data(api_client.create_transaction(account_id, payload, admin_headers()))


def post_transaction(account_id, transaction_id):
    """Post a transaction (PlatformAdmin). Returns the transaction."""
    return get_success_data(api_client.post_transaction(
        account_id, transaction_id, admin_headers()))


def ingest_and_post(account_id, amount_cents=-1000, merchant_name="Store",
                    budget_category_id=None):
    """Ingest then post a transaction. Returns the posted transaction."""
    txn = ingest_transaction(account_id, amount_cents, merchant_name, budget_category_id)
    return post_transaction(account_id, txn["id"])


def setup_posted_categorized_txn(allocated_cents=10000, amount_cents=-3000,
                                 income_expected_cents=None, opening_balance_cents=50000):
    """Household + period + category + DEPOSITORY account + one POSTED categorized outflow.

    Returns dict with household, owner_headers, period, category, account, transaction.
    income_expected_cents defaults to allocated_cents for an easily-closable period.
    """
    if income_expected_cents is None:
        income_expected_cents = allocated_cents
    hh, owner_headers, period, cat = setup_household_period_category(
        income_expected_cents=income_expected_cents,
        cat_name="Groceries", allocated_cents=allocated_cents)
    acc = create_account(hh["id"], owner_headers,
                         opening_balance_cents=opening_balance_cents)
    txn = ingest_transaction(acc["id"], amount_cents=amount_cents,
                             merchant_name="Mart", budget_category_id=cat["id"])
    posted = post_transaction(acc["id"], txn["id"])
    return {
        "household": hh, "owner_headers": owner_headers, "period": period,
        "category": cat, "account": acc, "transaction": posted,
    }


# --------------------------------------------------------------------------- #
# Goals / contributions                                                       #
# --------------------------------------------------------------------------- #
def create_goal(household_id, owner_headers, funding_category_id, name="Goal",
                target_cents=10000):
    """Create a goal. Returns the goal."""
    return get_success_data(api_client.create_goal(
        household_id,
        {"name": name, "target_cents": target_cents,
         "funding_category_id": funding_category_id},
        owner_headers,
    ))


def contribute(household_id, goal_id, owner_headers, amount_cents):
    """Contribute to a goal. Returns the contribution."""
    return get_success_data(api_client.contribute_goal(
        household_id, goal_id, {"amount_cents": amount_cents}, owner_headers))


def setup_goal_with_funding(allocated_cents=10000, target_cents=10000,
                            contribution_cents=None):
    """Household + period + funding category + ACTIVE goal, optionally pre-funded.

    Returns dict with household, owner_headers, period, category, goal.
    If contribution_cents is set, a contribution is applied (goal may become FUNDED).
    """
    hh, owner_headers, period, cat = setup_household_period_category(
        income_expected_cents=allocated_cents, cat_name="Save",
        allocated_cents=allocated_cents)
    goal = create_goal(hh["id"], owner_headers, cat["id"], name="Trip",
                       target_cents=target_cents)
    if contribution_cents is not None:
        contribute(hh["id"], goal["id"], owner_headers, contribution_cents)
        goal = get_success_data(api_client.get_goal(goal["id"], owner_headers))
    return {
        "household": hh, "owner_headers": owner_headers, "period": period,
        "category": cat, "goal": goal,
    }


# --------------------------------------------------------------------------- #
# Recurring bills                                                             #
# --------------------------------------------------------------------------- #
def create_bill(household_id, owner_headers, funding_category_id, payee="Rent",
                amount_cents=1000, day_of_month=1):
    """Create a SCHEDULED recurring bill. Returns the bill."""
    return get_success_data(api_client.create_recurring_bill(
        household_id,
        {"payee": payee, "amount_cents": amount_cents, "day_of_month": day_of_month,
         "funding_category_id": funding_category_id},
        owner_headers,
    ))


def setup_forecast_scenario(clock_iso="2026-02-01T00:00:00Z", month="2026-02",
                            opening_balance_cents=10000, bills=None):
    """Set clock + household + period + 'Bills' category + DEPOSITORY account + bills.

    bills: list of dicts {payee, amount_cents, day_of_month} created in order.
    Returns dict with household, owner_headers, period, category, account, bills.
    """
    set_clock(clock_iso)
    hh, owner_headers, period, cat = setup_household_period_category(
        month=month, income_expected_cents=0, cat_name="Bills", allocated_cents=0)
    acc = create_account(hh["id"], owner_headers,
                         opening_balance_cents=opening_balance_cents)
    created_bills = []
    for b in (bills or []):
        created_bills.append(create_bill(
            hh["id"], owner_headers, cat["id"],
            payee=b["payee"], amount_cents=b["amount_cents"],
            day_of_month=b["day_of_month"]))
    return {
        "household": hh, "owner_headers": owner_headers, "period": period,
        "category": cat, "account": acc, "bills": created_bills,
    }


# --------------------------------------------------------------------------- #
# Period close / OCC                                                          #
# --------------------------------------------------------------------------- #
def observe_household_version(household_id, owner_headers):
    """Read the household and return its current version."""
    hh = get_success_data(api_client.get_household(household_id, owner_headers))
    return hh["version"]


def close_period(household_id, period_id, owner_headers, expected_household_version):
    """Close a period with explicit expected_household_version (raw response)."""
    return api_client.close_budget_period(
        household_id, period_id,
        {"expected_household_version": expected_household_version}, owner_headers)


def find_open_period(household_id, owner_headers):
    """Return the household's current OPEN period (first match)."""
    resp = api_client.list_budget_periods(
        owner_headers, params={"household_id": household_id, "status": "OPEN"})
    items = get_success_data(resp)
    return items[0]


def find_category_by_name(household_id, period_id, owner_headers, name):
    """Return the first category named `name` in the given period."""
    resp = api_client.list_categories(
        owner_headers, params={"household_id": household_id, "budget_period_id": period_id})
    items = get_success_data(resp)
    for c in items:
        if c["name"] == name:
            return c
    return None
