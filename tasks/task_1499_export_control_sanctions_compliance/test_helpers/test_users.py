"""Pre-built role headers for every role in the PRD (§2.1).

All four roles use opaque X-User-ID identifiers (not tied to any persisted
entity), so shared constants are the canonical form. The make_* builders
exist for segregation-of-duties scenarios that need a specific X-User-ID
shared across two different roles.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "analyst_headers": build_user_headers("analyst-1", "ComplianceAnalyst"),
    "analyst2_headers": build_user_headers("analyst-2", "ComplianceAnalyst"),
    "manager_headers": build_user_headers("manager-1", "ComplianceManager"),
    "manager2_headers": build_user_headers("manager-2", "ComplianceManager"),
    "ops_headers": build_user_headers("ops-1", "TradeOpsSpecialist"),
    "director_headers": build_user_headers("director-1", "ComplianceDirector"),
}


def make_analyst_headers(user_id: str) -> dict:
    """ComplianceAnalyst headers with a specific X-User-ID (SoD scenarios)."""
    return build_user_headers(user_id, "ComplianceAnalyst")


def make_manager_headers(user_id: str) -> dict:
    """ComplianceManager headers with a specific X-User-ID (SoD scenarios)."""
    return build_user_headers(user_id, "ComplianceManager")


def make_ops_headers(user_id: str) -> dict:
    """TradeOpsSpecialist headers with a specific X-User-ID."""
    return build_user_headers(user_id, "TradeOpsSpecialist")


def make_director_headers(user_id: str) -> dict:
    """ComplianceDirector headers with a specific X-User-ID."""
    return build_user_headers(user_id, "ComplianceDirector")
