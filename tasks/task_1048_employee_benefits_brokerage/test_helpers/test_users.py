"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (BenefitsConsultant, CarrierRep,
# ComplianceOfficer, PlatformAdmin) whose X-User-ID is not compared to any
# entity id (PRD §2.1). For ClientContact the shared constant is a fallback for
# non-ownership tests only; ownership-gated calls MUST use make_client_contact_headers.
TEST_USERS = {
    "consultant_headers": build_user_headers("consultant-1", "BenefitsConsultant"),
    "carrier_headers": build_user_headers("carrier-1", "CarrierRep"),
    "compliance_headers": build_user_headers("officer-a", "ComplianceOfficer"),
    "compliance_b_headers": build_user_headers("officer-b", "ComplianceOfficer"),
    "client_contact_headers": build_user_headers("client-contact-1", "ClientContact"),
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
}


def make_consultant_headers(user_id: str = "consultant-1") -> dict:
    return build_user_headers(user_id, "BenefitsConsultant")


def make_carrier_headers(user_id: str = "carrier-1") -> dict:
    return build_user_headers(user_id, "CarrierRep")


def make_compliance_headers(user_id: str) -> dict:
    """ComplianceOfficer identity is opaque, but the acting X-User-ID is recorded
    on prepare/certify and compared for segregation of duties (PRD §3.7)."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_client_contact_headers(client_id: str) -> dict:
    """For ClientContact (identity entity_backed:Client). Pass the owning
    Client.id as X-User-ID whenever the election call is ownership-gated
    (PRD §2.1, §2.7 priority 3)."""
    return build_user_headers(client_id, "ClientContact")


def make_platform_admin_headers(user_id: str = "admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def unauthenticated_headers() -> dict:
    """Headers with NO X-User-Role, for the ERR_UNAUTHENTICATED path (PRD §2.1)."""
    return {"X-User-ID": "nobody", "Content-Type": "application/json"}
