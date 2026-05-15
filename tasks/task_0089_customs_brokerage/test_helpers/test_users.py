"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- BrokerOps, DeclarationOfficer, DocReviewer, FilingOfficer,
  InspectionOfficer, SettlementOfficer, SystemAdmin are OPAQUE — the
  server records the X-User-ID as an audit-log actor_id but does NOT
  resolve it against any entity table. Shared constants are canonical.

- ClientUser is ENTITY-BACKED: X-User-ID equals the acting
  ClientCompany.id. Any ownership-gated call by a ClientUser MUST use
  make_client_user_headers(client_company["id"]) so the server-side
  ownership check (compare X-User-ID to the resolved ClientCompany.id)
  succeeds.

- Segregation-of-duties (PRD §2.9) pair-checks compare two opaque ids
  as plain strings. The "_alt" variants exist so that a test or fixture
  needing two distinct actors of the same role can grab a second id
  without collisions.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Canonical opaque actor identifiers (PRD §2.1).
# Distinct ids are necessary for PRD §2.9 segregation-of-duties tests.
# ---------------------------------------------------------------------------
BROKER_OPS_ID = "broker-ops-001"
BROKER_OPS_ID_ALT = "broker-ops-002"

DECLARATION_OFFICER_ID = "dec-officer-001"
DECLARATION_OFFICER_ID_ALT = "dec-officer-002"

DOC_REVIEWER_ID = "doc-reviewer-001"
DOC_REVIEWER_ID_ALT = "doc-reviewer-002"

FILING_OFFICER_ID = "filing-officer-001"
FILING_OFFICER_ID_ALT = "filing-officer-002"

INSPECTION_OFFICER_ID = "insp-officer-001"
INSPECTION_OFFICER_ID_ALT = "insp-officer-002"

SETTLEMENT_OFFICER_ID = "settle-officer-001"
SETTLEMENT_OFFICER_ID_ALT = "settle-officer-002"

SYSTEM_ADMIN_ID = "sysadmin-001"

# ClientUser fallback — for tests that do NOT exercise ClientCompany
# ownership (e.g., missing-auth or wrong-role tests). Any ownership-gated
# ClientUser call MUST use make_client_user_headers(<real client.id>).
CLIENT_USER_FALLBACK_ID = "client-user-fallback-000"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # BrokerOps (opaque) — PRD §2.1.
    "broker_ops_headers":      build_user_headers(BROKER_OPS_ID, "BrokerOps"),
    "broker_ops_headers_alt":  build_user_headers(BROKER_OPS_ID_ALT, "BrokerOps"),

    # DeclarationOfficer (opaque) — PRD §2.1.
    "declaration_officer_headers":      build_user_headers(DECLARATION_OFFICER_ID, "DeclarationOfficer"),
    "declaration_officer_headers_alt":  build_user_headers(DECLARATION_OFFICER_ID_ALT, "DeclarationOfficer"),

    # DocReviewer (opaque) — PRD §2.1, §2.9.
    "doc_reviewer_headers":      build_user_headers(DOC_REVIEWER_ID, "DocReviewer"),
    "doc_reviewer_headers_alt":  build_user_headers(DOC_REVIEWER_ID_ALT, "DocReviewer"),

    # FilingOfficer (opaque) — PRD §2.1, §2.9.
    "filing_officer_headers":      build_user_headers(FILING_OFFICER_ID, "FilingOfficer"),
    "filing_officer_headers_alt":  build_user_headers(FILING_OFFICER_ID_ALT, "FilingOfficer"),

    # InspectionOfficer (opaque) — PRD §2.1.
    "inspection_officer_headers":      build_user_headers(INSPECTION_OFFICER_ID, "InspectionOfficer"),
    "inspection_officer_headers_alt":  build_user_headers(INSPECTION_OFFICER_ID_ALT, "InspectionOfficer"),

    # SettlementOfficer (opaque) — PRD §2.1, §2.9.
    "settlement_officer_headers":      build_user_headers(SETTLEMENT_OFFICER_ID, "SettlementOfficer"),
    "settlement_officer_headers_alt":  build_user_headers(SETTLEMENT_OFFICER_ID_ALT, "SettlementOfficer"),

    # SystemAdmin (opaque) — PRD §2.1; drives _clock/advance and _events/emit.
    "system_admin_headers":  build_user_headers(SYSTEM_ADMIN_ID, "SystemAdmin"),

    # ClientUser fallback — DO NOT use for ownership-gated calls.
    # See make_client_user_headers() for the canonical builder.
    "client_user_headers":  build_user_headers(CLIENT_USER_FALLBACK_ID, "ClientUser"),
}


# ---------------------------------------------------------------------------
# Per-instance builders.
# ---------------------------------------------------------------------------
def make_broker_ops_headers(user_id: str) -> Dict[str, str]:
    """BrokerOps X-User-ID is opaque (PRD §2.1). Use a distinct id when a
    test needs two BrokerOps actors that must differ as opaque strings."""
    return build_user_headers(user_id, "BrokerOps")


def make_declaration_officer_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "DeclarationOfficer")


def make_doc_reviewer_headers(user_id: str) -> Dict[str, str]:
    """PRD §2.9: "a DocReviewer who advances a declaration to PRE_VALIDATED
    cannot then act as the FilingOfficer on the same declaration's file
    transition." Tests that exercise this pair must pass distinct ids to
    make_doc_reviewer_headers and make_filing_officer_headers."""
    return build_user_headers(user_id, "DocReviewer")


def make_filing_officer_headers(user_id: str) -> Dict[str, str]:
    """PRD §2.9: "the FilingOfficer who files a declaration cannot then
    act as the SettlementOfficer who advances the resulting settlement."
    Pass distinct ids when exercising this pair."""
    return build_user_headers(user_id, "FilingOfficer")


def make_inspection_officer_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "InspectionOfficer")


def make_settlement_officer_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, "SettlementOfficer")


def make_client_user_headers(client_company_id: str) -> Dict[str, str]:
    """PRD §2.1: "ClientUser is entity-backed: when X-User-Role is ClientUser,
    X-User-ID is the id of the acting ClientCompany, and any ownership
    check on a resource that ultimately resolves to a ClientCompany
    compares that ClientCompany.id to X-User-ID."

    Pass the ClientCompany.id the caller is acting as. Falling back to
    the shared constant for an ownership-gated ClientUser call would
    make every ownership check reject the request regardless of how the
    implementation models tenancy."""
    return build_user_headers(client_company_id, "ClientUser")


def make_system_admin_headers(user_id: str = SYSTEM_ADMIN_ID) -> Dict[str, str]:
    return build_user_headers(user_id, "SystemAdmin")


__all__ = [
    # ids
    "BROKER_OPS_ID",
    "BROKER_OPS_ID_ALT",
    "DECLARATION_OFFICER_ID",
    "DECLARATION_OFFICER_ID_ALT",
    "DOC_REVIEWER_ID",
    "DOC_REVIEWER_ID_ALT",
    "FILING_OFFICER_ID",
    "FILING_OFFICER_ID_ALT",
    "INSPECTION_OFFICER_ID",
    "INSPECTION_OFFICER_ID_ALT",
    "SETTLEMENT_OFFICER_ID",
    "SETTLEMENT_OFFICER_ID_ALT",
    "SYSTEM_ADMIN_ID",
    "CLIENT_USER_FALLBACK_ID",
    # registries
    "TEST_USERS",
    # builders
    "make_broker_ops_headers",
    "make_declaration_officer_headers",
    "make_doc_reviewer_headers",
    "make_filing_officer_headers",
    "make_inspection_officer_headers",
    "make_settlement_officer_headers",
    "make_client_user_headers",
    "make_system_admin_headers",
]
