"""Pre-built role headers for every role in the PRD (§2.1).

Seven roles are opaque identities; PartnerRepresentative is entity-backed:
its X-User-ID must equal the acting PartnerCompany's id (PRD §2.1).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not
# exercise entity-backed ownership.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "production_manager_headers": build_user_headers("pm-1", "ProductionManager"),
    "casting_director_headers": build_user_headers("cd-1", "CastingDirector"),
    "contracts_officer_headers": build_user_headers("co-1", "ContractsOfficer"),
    "technical_director_headers": build_user_headers("td-1", "TechnicalDirector"),
    "box_office_manager_headers": build_user_headers("bom-1", "BoxOfficeManager"),
    "any_headers": build_user_headers("reader-1", "Any"),
    # Fallback for non-ownership tests only; ownership-gated calls must use
    # make_partner_representative_headers(<PartnerCompany.id>).
    "partner_representative_headers": build_user_headers(
        "partner-rep-unbound", "PartnerRepresentative"
    ),
}


def make_partner_representative_headers(company_id: str) -> dict:
    """PartnerRepresentative is entity-backed (PRD §2.1): X-User-ID must equal
    the acting PartnerCompany's id for ownership-gated rental-offer calls."""
    return build_user_headers(company_id, "PartnerRepresentative")


def make_production_manager_headers(user_id: str) -> dict:
    """ProductionManager is opaque; distinct ids matter for the settle
    segregation-of-duties check (PRD §2.10)."""
    return build_user_headers(user_id, "ProductionManager")


def make_contracts_officer_headers(user_id: str) -> dict:
    """ContractsOfficer is opaque; distinct ids matter for the waiver
    segregation-of-duties check (PRD §2.10)."""
    return build_user_headers(user_id, "ContractsOfficer")
