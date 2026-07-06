"""Pre-built role headers for every role in the PRD.

Three agency-staff roles (CaseManager, Screener, FinanceOfficer) are opaque:
X-User-ID is an operator identifier not tied to any persisted entity. The two
party roles (IntendedParentActor, CarrierActor) are entity_backed: X-User-ID
must be the acting IntendedParent.id / GestationalCarrier.id whenever an
ownership-gated call is made.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for non-ownership tests.
TEST_USERS = {
    "case_manager_headers": build_user_headers("cm-shared-1", "CaseManager"),
    "screener_headers": build_user_headers("screener-shared-1", "Screener"),
    "finance_officer_headers": build_user_headers("fo-shared-1", "FinanceOfficer"),
    # entity_backed fallbacks — only for tests that do NOT exercise ownership.
    "intended_parent_actor_headers": build_user_headers("ip-shared-1", "IntendedParentActor"),
    "carrier_actor_headers": build_user_headers("carrier-shared-1", "CarrierActor"),
}


# Opaque-role builders — let tests control the operator identifier
# (needed for segregation-of-duties: approver vs releaser).
def make_case_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CaseManager")


def make_screener_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Screener")


def make_finance_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FinanceOfficer")


# Per-instance builders — MANDATORY for entity_backed roles on ownership-gated
# calls. Pass the actual IntendedParent.id / GestationalCarrier.id.
def make_intended_parent_actor_headers(user_id: str) -> dict:
    """For IntendedParentActor (entity_backed:IntendedParent). Pass the acting
    IntendedParent.id as user_id for ip-sign and escrow deposit."""
    return build_user_headers(user_id, "IntendedParentActor")


def make_carrier_actor_headers(user_id: str) -> dict:
    """For CarrierActor (entity_backed:GestationalCarrier). Pass the acting
    GestationalCarrier.id as user_id for carrier-sign."""
    return build_user_headers(user_id, "CarrierActor")
