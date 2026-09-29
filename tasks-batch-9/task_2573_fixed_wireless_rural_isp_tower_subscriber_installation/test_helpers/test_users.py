"""Pre-built request headers for every role named in PRD 2.1.

The six operator roles carry an opaque `X-User-ID` that the server never resolves
to a row, so the shared constants below are the canonical form for them. Two
controls compare one operator identifier against another (PRD 2.11), so distinct
per-person builders are provided for those workflows.

The `Subscriber` role is different: its `X-User-ID` is the account's own `id`, so
any subscriber-scoped call MUST use `make_subscriber_headers(subscriber["id"])`.
"""

from prd_bench_local_runner.testing import build_user_headers

# Shared operator identities. Safe for every operator call: an operator
# identifier is never compared to a record's id.
TEST_USERS = {
    "network_engineer_headers": build_user_headers("op-neteng-1", "NetworkEngineer"),
    "capacity_planner_headers": build_user_headers("op-capplan-1", "CapacityPlanner"),
    "sales_agent_headers": build_user_headers("op-sales-1", "SalesAgent"),
    "field_tech_headers": build_user_headers("op-fieldtech-1", "FieldTech"),
    "billing_admin_headers": build_user_headers("op-billing-1", "BillingAdmin"),
    "finance_approver_headers": build_user_headers("op-finance-1", "FinanceApprover"),
    # Fallback subscriber identity: only for calls that are refused before the
    # ownership rung (unknown-account 404s, role checks).
    "subscriber_headers": build_user_headers("00000000-0000-4000-8000-000000000abc", "Subscriber"),
}

# Convenience aliases used throughout the fixtures.
NETWORK_ENGINEER = TEST_USERS["network_engineer_headers"]
CAPACITY_PLANNER = TEST_USERS["capacity_planner_headers"]
SALES_AGENT = TEST_USERS["sales_agent_headers"]
FIELD_TECH = TEST_USERS["field_tech_headers"]
BILLING_ADMIN = TEST_USERS["billing_admin_headers"]
FINANCE_APPROVER = TEST_USERS["finance_approver_headers"]


def make_network_engineer_headers(user_id: str) -> dict:
    """A named NetworkEngineer. Use two distinct ids across a survey and its
    mounting-exception decision (PRD 2.11)."""
    return build_user_headers(user_id, "NetworkEngineer")


def make_capacity_planner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CapacityPlanner")


def make_sales_agent_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SalesAgent")


def make_field_tech_headers(user_id: str) -> dict:
    """A named FieldTech. The id supplied here is recorded as the work order's
    `surveyed_by_user_id` (PRD 2.1)."""
    return build_user_headers(user_id, "FieldTech")


def make_billing_admin_headers(user_id: str) -> dict:
    """A named BillingAdmin. The id supplied here is recorded as a credit's
    `prepared_by_user_id` (PRD 2.1)."""
    return build_user_headers(user_id, "BillingAdmin")


def make_finance_approver_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FinanceApprover")


def make_subscriber_headers(subscriber_id: str) -> dict:
    """For the `Subscriber` role, whose `X-User-ID` is the acting account's `id`
    (PRD 2.1). Always pass the real account id for ownership-gated reads."""
    return build_user_headers(subscriber_id, "Subscriber")


# Headers for every role, keyed by the role name, for parametrized role sweeps.
HEADERS_BY_ROLE = {
    "NetworkEngineer": NETWORK_ENGINEER,
    "CapacityPlanner": CAPACITY_PLANNER,
    "SalesAgent": SALES_AGENT,
    "FieldTech": FIELD_TECH,
    "BillingAdmin": BILLING_ADMIN,
    "FinanceApprover": FINANCE_APPROVER,
    "Subscriber": TEST_USERS["subscriber_headers"],
}
