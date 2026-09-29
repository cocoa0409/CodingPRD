"""Pre-built role headers for the six roles of PRD §2.1.

PRD §2.1 makes two of the six roles entity-backed: for ``Customer`` the
``X-User-ID`` header must carry the acting ``Customer.id``, and for
``RetailPartner`` it must carry the acting ``RetailPartner.id``. Every
ownership-gated call therefore has to use ``make_customer_headers(customer_id)``
or ``make_retail_partner_headers(partner_id)`` with a real persisted id — the
shared ``TEST_USERS`` constants for those two roles are only safe in tests that
never reach an ownership comparison.

The remaining four roles carry opaque operator identifiers that the API records
verbatim into ``approved_by_user_id``, ``settled_by_user_id``,
``authorized_by_user_id`` and ``released_by_user_id``. Segregation of duties
(PRD §2.11) needs two *distinct* operator ids for the same role, which is what
the ``make_<role>_headers`` builders are for.
"""

from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers reused across fixtures.
TRIAL_SUPPORT_AGENT_USER_ID = "agent-1"
LOGISTICS_COORDINATOR_USER_ID = "logistics-1"
FINANCE_CONTROLLER_USER_ID = "finance-1"
PLATFORM_ADMIN_USER_ID = "admin-1"

# Second operators, for the two segregation-of-duties rules of PRD §2.11.
SECOND_TRIAL_SUPPORT_AGENT_USER_ID = "agent-2"
SECOND_FINANCE_CONTROLLER_USER_ID = "finance-2"

TEST_USERS = {
    # entity_backed roles — fallbacks for tests that never reach an ownership check.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "retail_partner_headers": build_user_headers("test-partner-1", "RetailPartner"),
    # opaque operator roles — canonical form.
    "trial_support_agent_headers": build_user_headers(
        TRIAL_SUPPORT_AGENT_USER_ID, "TrialSupportAgent"
    ),
    "logistics_coordinator_headers": build_user_headers(
        LOGISTICS_COORDINATOR_USER_ID, "LogisticsCoordinator"
    ),
    "finance_controller_headers": build_user_headers(
        FINANCE_CONTROLLER_USER_ID, "FinanceController"
    ),
    "platform_admin_headers": build_user_headers(PLATFORM_ADMIN_USER_ID, "PlatformAdmin"),
}


def make_customer_headers(user_id: str) -> dict:
    """For the ``Customer`` role: pass the acting ``Customer.id`` (PRD §2.1)."""
    return build_user_headers(user_id, "Customer")


def make_retail_partner_headers(user_id: str) -> dict:
    """For the ``RetailPartner`` role: pass the acting ``RetailPartner.id`` (PRD §2.1)."""
    return build_user_headers(user_id, "RetailPartner")


def make_trial_support_agent_headers(user_id: str = TRIAL_SUPPORT_AGENT_USER_ID) -> dict:
    return build_user_headers(user_id, "TrialSupportAgent")


def make_logistics_coordinator_headers(
    user_id: str = LOGISTICS_COORDINATOR_USER_ID,
) -> dict:
    return build_user_headers(user_id, "LogisticsCoordinator")


def make_finance_controller_headers(user_id: str = FINANCE_CONTROLLER_USER_ID) -> dict:
    return build_user_headers(user_id, "FinanceController")


def make_platform_admin_headers(user_id: str = PLATFORM_ADMIN_USER_ID) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_unknown_role_headers(user_id: str = "ghost-1") -> dict:
    """A syntactically present but unrecognised role (PRD §2.1)."""
    return build_user_headers(user_id, "WarehouseIntern")
