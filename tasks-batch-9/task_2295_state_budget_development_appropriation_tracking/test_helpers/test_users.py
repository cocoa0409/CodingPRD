"""Pre-built role headers for every role in the PRD."""

from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
# `X-User-ID` is an opaque operator identifier for SystemAdmin, BudgetAnalyst,
# BudgetDirector, LegislativeFiscalOfficer and StateController, so these entries are
# canonical for those five roles. The AgencyBudgetOfficer entry is a fallback for calls
# that are not ownership-gated only; ownership-gated calls MUST use
# make_agency_officer_headers(agency["id"]).
TEST_USERS = {
    "system_admin_headers": build_user_headers("admin-1", "SystemAdmin"),
    "agency_officer_headers": build_user_headers("officer-1", "AgencyBudgetOfficer"),
    "budget_analyst_headers": build_user_headers("analyst-1", "BudgetAnalyst"),
    "budget_director_headers": build_user_headers("dir-1", "BudgetDirector"),
    "legislative_fiscal_officer_headers": build_user_headers(
        "legislative-1", "LegislativeFiscalOfficer"
    ),
    "state_controller_headers": build_user_headers("controller-1", "StateController"),
}

# A second BudgetDirector identity, for the approvals a preparer may not perform.
SECOND_DIRECTOR_HEADERS = build_user_headers("dir-2", "BudgetDirector")

# Headers carrying no X-User-Role at all.
ANONYMOUS_HEADERS = {"Content-Type": "application/json"}


def make_agency_officer_headers(agency_id: str) -> dict:
    """For AgencyBudgetOfficer, whose X-User-ID is the id of the acting Agency.

    Pass the real Agency id whenever the call is ownership-gated.
    """
    return build_user_headers(agency_id, "AgencyBudgetOfficer")


def make_system_admin_headers(user_id: str = "admin-1") -> dict:
    return build_user_headers(user_id, "SystemAdmin")


def make_analyst_headers(user_id: str = "analyst-1") -> dict:
    return build_user_headers(user_id, "BudgetAnalyst")


def make_director_headers(user_id: str = "dir-1") -> dict:
    return build_user_headers(user_id, "BudgetDirector")


def make_legislative_headers(user_id: str = "legislative-1") -> dict:
    return build_user_headers(user_id, "LegislativeFiscalOfficer")


def make_controller_headers(user_id: str = "controller-1") -> dict:
    return build_user_headers(user_id, "StateController")


ALL_ROLE_HEADERS = {
    "SystemAdmin": TEST_USERS["system_admin_headers"],
    "AgencyBudgetOfficer": TEST_USERS["agency_officer_headers"],
    "BudgetAnalyst": TEST_USERS["budget_analyst_headers"],
    "BudgetDirector": TEST_USERS["budget_director_headers"],
    "LegislativeFiscalOfficer": TEST_USERS["legislative_fiscal_officer_headers"],
    "StateController": TEST_USERS["state_controller_headers"],
}
