"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules: "All four roles carry opaque identities:
X-User-ID is an operator handle that is not foreign-keyed to any
persisted user entity." Shared constants are therefore canonical for
ALL four roles — the only ownership-style comparison the platform
performs is the segregation-of-duties check that compares a patrol's
verifier against its actor_id (two different X-User-ID values, not
X-User-ID vs an entity.id).

Per-instance builders (`make_*_headers`) are exposed so tests can mint
distinct actor identifiers when they need to:
  - drive the SoD check on patrol verify/reject (verifier must differ
    from the patrol record's actor_id), or
  - tell two operator actors apart for the alarm-already-acked race,
    audit-log distinguishability, etc.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Canonical opaque-actor identifiers (PRD §2.1)
# ---------------------------------------------------------------------------
PLATFORM_ADMIN_ID = "admin-001"
PLATFORM_ADMIN_ID_ALT = "admin-002"

OM_ENGINEER_ID = "om-eng-001"
OM_ENGINEER_ID_ALT = "om-eng-002"

FIELD_OPERATOR_ID = "field-op-001"
FIELD_OPERATOR_ID_ALT = "field-op-002"

FINANCE_OFFICER_ID = "finance-001"
FINANCE_OFFICER_ID_ALT = "finance-002"


TEST_USERS: Dict[str, Dict[str, str]] = {
    "platform_admin_headers": build_user_headers(
        PLATFORM_ADMIN_ID, "PlatformAdmin",
    ),
    "platform_admin_headers_alt": build_user_headers(
        PLATFORM_ADMIN_ID_ALT, "PlatformAdmin",
    ),
    "om_engineer_headers": build_user_headers(
        OM_ENGINEER_ID, "O&MEngineer",
    ),
    "om_engineer_headers_alt": build_user_headers(
        OM_ENGINEER_ID_ALT, "O&MEngineer",
    ),
    "field_operator_headers": build_user_headers(
        FIELD_OPERATOR_ID, "FieldOperator",
    ),
    "field_operator_headers_alt": build_user_headers(
        FIELD_OPERATOR_ID_ALT, "FieldOperator",
    ),
    "finance_officer_headers": build_user_headers(
        FINANCE_OFFICER_ID, "FinanceOfficer",
    ),
    "finance_officer_headers_alt": build_user_headers(
        FINANCE_OFFICER_ID_ALT, "FinanceOfficer",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — for tests that need distinct actor ids for
# the SoD check or actor-audit distinguishability.
# ---------------------------------------------------------------------------
def make_platform_admin_headers(actor_id: str) -> Dict[str, str]:
    return build_user_headers(actor_id, "PlatformAdmin")


def make_om_engineer_headers(actor_id: str) -> Dict[str, str]:
    return build_user_headers(actor_id, "O&MEngineer")


def make_field_operator_headers(actor_id: str) -> Dict[str, str]:
    """Mint a FieldOperator header with a specific actor_id.

    Required by tests that exercise the patrol SoD gate: verifier
    (O&MEngineer) must differ from the patrol's actor_id (which is the
    X-User-ID of the FieldOperator who started the patrol).
    """
    return build_user_headers(actor_id, "FieldOperator")


def make_finance_officer_headers(actor_id: str) -> Dict[str, str]:
    return build_user_headers(actor_id, "FinanceOfficer")


__all__ = [
    "PLATFORM_ADMIN_ID",
    "PLATFORM_ADMIN_ID_ALT",
    "OM_ENGINEER_ID",
    "OM_ENGINEER_ID_ALT",
    "FIELD_OPERATOR_ID",
    "FIELD_OPERATOR_ID_ALT",
    "FINANCE_OFFICER_ID",
    "FINANCE_OFFICER_ID_ALT",
    "TEST_USERS",
    "make_platform_admin_headers",
    "make_om_engineer_headers",
    "make_field_operator_headers",
    "make_finance_officer_headers",
]
