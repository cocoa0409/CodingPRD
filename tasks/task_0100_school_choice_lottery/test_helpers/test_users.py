"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

OPAQUE roles — X-User-ID is an opaque operator identifier that is not
tied to any persisted entity row. Shared constants are canonical:
  - SystemOperator

ENTITY-BACKED roles — PRD §2.1:
  - DistrictAdmin: X-User-ID is the id of the acting District;
    ownership checks compare the resource's district FK to X-User-ID.
  - FamilyUser: X-User-ID is the id of the acting Family; ownership
    checks compare the resource's family FK to X-User-ID.

Every DistrictAdmin call whose success depends on the resource
belonging to the right district MUST mint headers via
make_district_admin_headers(district_id) — never the shared fallback
constant. Likewise every FamilyUser ownership-gated call MUST mint
headers via make_family_user_headers(family_id) using the actual
Family.id of the resource owner.

The shared *_FALLBACK_ID constants below are reserved for tests that do
NOT exercise ownership (missing-headers / role-mismatch / NotFound
paths, or calls where the role is provably non-permitted regardless of
identity).
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Opaque-role canonical ids — shared constants are PRD-correct because
# the server records but does not match these against any entity id
# (PRD §2.1: "the server does not compare it to any entity's id").
# ---------------------------------------------------------------------------
SYSTEM_OPERATOR_ID = "system-operator-1"
SYSTEM_OPERATOR_ID_ALT = "system-operator-2"


# ---------------------------------------------------------------------------
# Entity-backed-role fallback ids — DO NOT USE for ownership-gated
# calls. Use the make_*_headers builders with the entity's actual id.
# ---------------------------------------------------------------------------
DISTRICT_ADMIN_FALLBACK_ID = "district-admin-fallback"
FAMILY_USER_FALLBACK_ID = "family-user-fallback"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque role — shared constant canonical (PRD §2.1).
    "system_operator_headers": build_user_headers(
        SYSTEM_OPERATOR_ID, "SystemOperator",
    ),
    "system_operator_headers_alt": build_user_headers(
        SYSTEM_OPERATOR_ID_ALT, "SystemOperator",
    ),

    # Entity-backed fallbacks — only safe for non-ownership tests.
    "district_admin_headers": build_user_headers(
        DISTRICT_ADMIN_FALLBACK_ID, "DistrictAdmin",
    ),
    "family_user_headers": build_user_headers(
        FAMILY_USER_FALLBACK_ID, "FamilyUser",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — REQUIRED for entity-backed roles whenever the
# call is ownership-gated. Pass the District.id or Family.id of the
# resource owner so PRD §2.1 ownership checks pass.
# ---------------------------------------------------------------------------
def make_district_admin_headers(district_id: str) -> Dict[str, str]:
    """For DistrictAdmin (entity_backed:District). Pass the District.id
    of the district that owns / targets the resource being operated on.
    PRD §2.1: "ownership checks on any resource that references a
    District ... compare the resource's district foreign-key to
    X-User-ID."
    """
    return build_user_headers(district_id, "DistrictAdmin")


def make_family_user_headers(family_id: str) -> Dict[str, str]:
    """For FamilyUser (entity_backed:Family). Pass the Family.id of the
    student's / application's owning family. PRD §2.1: "ownership
    checks on any resource that references a Family ... compare the
    resource's family foreign-key to X-User-ID."
    """
    return build_user_headers(family_id, "FamilyUser")


def make_system_operator_headers(operator_id: str) -> Dict[str, str]:
    """For SystemOperator (opaque). The id is recorded but not compared
    to any entity (PRD §2.1)."""
    return build_user_headers(operator_id, "SystemOperator")


__all__ = [
    "SYSTEM_OPERATOR_ID",
    "SYSTEM_OPERATOR_ID_ALT",
    "DISTRICT_ADMIN_FALLBACK_ID",
    "FAMILY_USER_FALLBACK_ID",
    "TEST_USERS",
    "make_district_admin_headers",
    "make_family_user_headers",
    "make_system_operator_headers",
]
