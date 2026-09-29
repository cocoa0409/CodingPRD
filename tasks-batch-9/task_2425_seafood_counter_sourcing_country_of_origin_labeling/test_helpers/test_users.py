"""Pre-built role headers for every role in the PRD.

Per PRD §2.1 two roles are entity-backed: a `SeafoodManager`'s `X-User-ID` is the
`id` of the acting `Counter`, and a `SupplierRep`'s `X-User-ID` is the `id` of the
acting `Supplier`. Ownership-gated calls MUST therefore use
make_seafood_manager_headers(counter_id) / make_supplier_rep_headers(supplier_id).
The shared TEST_USERS entries for those two roles are only safe where the outcome
does not depend on ownership. The other three roles are opaque operator ids.
"""
from prd_bench_local_runner.testing import build_user_headers


# Opaque operator identifiers used across the suite.
CHAIN_ADMIN_USER_ID = "chain-admin-1"
OFFICER_SAMPLING_USER_ID = "officer-sampling-1"
OFFICER_COOL_USER_ID = "officer-cool-1"
OFFICER_CLAIM_USER_ID = "officer-claim-2"
OFFICER_SIMP_USER_ID = "officer-simp-3"
OFFICER_LEDGER_USER_ID = "officer-ledger-4"
OFFICER_COLD_USER_ID = "officer-cold-5"
OFFICER_READ_USER_ID = "officer-read-9"
MERCH_LEAD_USER_ID = "merch-lead-1"
ASSOCIATE_USER_ID = "assoc-7"


TEST_USERS = {
    "chain_admin_headers": build_user_headers(CHAIN_ADMIN_USER_ID, "ChainAdmin"),
    "compliance_officer_headers": build_user_headers(OFFICER_SAMPLING_USER_ID, "ComplianceOfficer"),
    "cool_reviewer_headers": build_user_headers(OFFICER_COOL_USER_ID, "ComplianceOfficer"),
    "claim_reviewer_headers": build_user_headers(OFFICER_CLAIM_USER_ID, "ComplianceOfficer"),
    "simp_reviewer_headers": build_user_headers(OFFICER_SIMP_USER_ID, "ComplianceOfficer"),
    "ledger_officer_headers": build_user_headers(OFFICER_LEDGER_USER_ID, "ComplianceOfficer"),
    "cold_chain_officer_headers": build_user_headers(OFFICER_COLD_USER_ID, "ComplianceOfficer"),
    "merchandising_lead_headers": build_user_headers(MERCH_LEAD_USER_ID, "MerchandisingLead"),
    # Entity-backed roles: fallback constants for non-ownership tests only.
    "seafood_manager_headers": build_user_headers("test-counter-1", "SeafoodManager"),
    "supplier_rep_headers": build_user_headers("test-supplier-1", "SupplierRep"),
}


def make_chain_admin_headers(user_id: str = CHAIN_ADMIN_USER_ID) -> dict:
    """ChainAdmin is opaque: the id is never compared to any entity."""
    return build_user_headers(user_id, "ChainAdmin")


def make_compliance_officer_headers(user_id: str = OFFICER_SAMPLING_USER_ID) -> dict:
    """ComplianceOfficer is opaque, but the acting id is recorded on advertisement reviews."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_merchandising_lead_headers(user_id: str = MERCH_LEAD_USER_ID) -> dict:
    """MerchandisingLead is opaque and never persisted."""
    return build_user_headers(user_id, "MerchandisingLead")


def make_seafood_manager_headers(counter_id: str) -> dict:
    """For SeafoodManager: X-User-ID must be the acting Counter's id."""
    return build_user_headers(counter_id, "SeafoodManager")


def make_supplier_rep_headers(supplier_id: str) -> dict:
    """For SupplierRep: X-User-ID must be the acting Supplier's id."""
    return build_user_headers(supplier_id, "SupplierRep")


def headers_without_user_id(role: str) -> dict:
    """Headers carrying only X-User-Role — the absent-header case of PRD §2.1."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str) -> dict:
    """Headers carrying only X-User-ID — the absent-header case of PRD §2.1."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}
