"""Pre-built role headers for every role in the PRD (§2.1).

All three roles use opaque operator identifiers: the server never compares
`X-User-ID` against a resource's `id`. The identifier resurfaces only in the
invoice segregation-of-duties check (approver vs. recorded submitter), so the
two analyst constants use distinct user IDs to keep approval chains clean.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Manager — taxonomy, fiscal calendar, budgets, firm lifecycle, pay, publish
    "manager_headers": build_user_headers("manager-1", "LegalOpsManager"),
    # Primary analyst — matters, assignments, accruals, invoices (creator side)
    "analyst_headers": build_user_headers("analyst-1", "LegalOpsAnalyst"),
    # Second analyst — used as the default approver so invoices at or above
    # the 100000-cent SOD threshold are never self-approved by accident
    "analyst_2_headers": build_user_headers("analyst-2", "LegalOpsAnalyst"),
    # Executive — read-only consumer
    "executive_headers": build_user_headers("executive-1", "LegalOpsExecutive"),
}


def make_manager_headers(user_id: str) -> dict:
    """Manager headers with an explicit operator id (all roles are opaque)."""
    return build_user_headers(user_id, "LegalOpsManager")


def make_analyst_headers(user_id: str) -> dict:
    """Analyst headers with an explicit operator id.

    Use a distinct user id whenever the segregation-of-duties rule (PRD §3.5)
    is under test: the approver's id is compared against the id recorded when
    the invoice was submitted.
    """
    return build_user_headers(user_id, "LegalOpsAnalyst")


def make_executive_headers(user_id: str) -> dict:
    """Executive headers with an explicit operator id."""
    return build_user_headers(user_id, "LegalOpsExecutive")
