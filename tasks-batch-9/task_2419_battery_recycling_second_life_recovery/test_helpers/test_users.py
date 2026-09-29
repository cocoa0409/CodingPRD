"""Pre-built role headers for the ten operating roles (PRD §2.1).

Nine roles carry an opaque identity: their X-User-ID is an operator identifier
never compared against any entity id, so a shared constant is the canonical
form.  Where the PRD compares two actors' X-User-ID values against each other
(manifest submit versus manifest close), use the per-role builders below with
two distinct identifiers.

SupplierRep is entity-backed: its X-User-ID must be the acting Supplier's id.
Ownership-gated calls MUST use make_supplier_rep_headers(supplier["id"]).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for SupplierRep only in tests
# that do not exercise ownership.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "market_analyst_headers": build_user_headers("test-market-analyst-1", "MarketAnalyst"),
    "intake_clerk_headers": build_user_headers("test-intake-clerk-1", "IntakeClerk"),
    "plant_operator_headers": build_user_headers("test-plant-operator-1", "PlantOperator"),
    "compliance_officer_headers": build_user_headers(
        "test-compliance-officer-1", "ComplianceOfficer"
    ),
    "triage_engineer_headers": build_user_headers("test-triage-engineer-1", "TriageEngineer"),
    "assay_technician_headers": build_user_headers(
        "test-assay-technician-1", "AssayTechnician"
    ),
    "settlement_accountant_headers": build_user_headers(
        "test-settlement-accountant-1", "SettlementAccountant"
    ),
    "certification_officer_headers": build_user_headers(
        "test-certification-officer-1", "CertificationOfficer"
    ),
    # Fallback only — never use for a settlement dispute.
    "supplier_rep_headers": build_user_headers("test-supplier-rep-1", "SupplierRep"),
}


# --------------------------------------------------------------------------
# Per-instance builders
# --------------------------------------------------------------------------

def make_supplier_rep_headers(supplier_id: str) -> dict:
    """For SupplierRep, whose X-User-ID is the id of the acting Supplier.

    Pass the real Supplier id whenever the call is ownership-gated.
    """
    return build_user_headers(supplier_id, "SupplierRep")


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_market_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "MarketAnalyst")


def make_intake_clerk_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "IntakeClerk")


def make_plant_operator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlantOperator")


def make_compliance_officer_headers(user_id: str) -> dict:
    """Manifest close compares X-User-ID against submitted_by_user_id, so the
    submitter and the counter-signer must be built with distinct ids."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_triage_engineer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "TriageEngineer")


def make_assay_technician_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AssayTechnician")


def make_settlement_accountant_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SettlementAccountant")


def make_certification_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CertificationOfficer")


def make_headers(user_id: str, role: str) -> dict:
    """Escape hatch for role names the API is expected to reject."""
    return build_user_headers(user_id, role)


ROLE_HEADER_KEYS = {
    "PlatformAdmin": "platform_admin_headers",
    "MarketAnalyst": "market_analyst_headers",
    "IntakeClerk": "intake_clerk_headers",
    "PlantOperator": "plant_operator_headers",
    "ComplianceOfficer": "compliance_officer_headers",
    "TriageEngineer": "triage_engineer_headers",
    "AssayTechnician": "assay_technician_headers",
    "SettlementAccountant": "settlement_accountant_headers",
    "CertificationOfficer": "certification_officer_headers",
    "SupplierRep": "supplier_rep_headers",
}
