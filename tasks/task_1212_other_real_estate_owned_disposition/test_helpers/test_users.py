"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that don't exercise ownership.
# For entity-backed roles (Appraiser, Broker) the shared constant is a fallback
# ONLY for tests that do not require identity match against a persisted entity.
TEST_USERS = {
    "oreo_admin_headers": build_user_headers("test-admin-1", "OREOAdmin"),
    "property_manager_headers": build_user_headers("test-pm-1", "PropertyManager"),
    "oreo_specialist_headers": build_user_headers("test-spec-1", "OREOSpecialist"),
    "appraiser_headers": build_user_headers("test-appraiser-1", "Appraiser"),
    "chief_appraiser_headers": build_user_headers("chief-appraiser-1", "ChiefAppraiser"),
    "credit_officer_headers": build_user_headers("co-1", "CreditOfficer"),
    "oreo_committee_headers": build_user_headers("committee-1", "OREOCommittee"),
    "compliance_officer_headers": build_user_headers("comp-1", "ComplianceOfficer"),
    "broker_headers": build_user_headers("test-broker-1", "Broker"),
}


def make_appraiser_headers(user_id: str) -> dict:
    """Appraiser is entity-backed:Appraiser. Pass the actual Appraiser.id as
    user_id whenever the call is ownership-gated (create appraisal, submit)."""
    return build_user_headers(user_id, "Appraiser")


def make_broker_headers(user_id: str) -> dict:
    """Broker is entity-backed:Broker. Pass the actual Broker.id as user_id
    whenever the call is ownership-gated (self-scoped reads)."""
    return build_user_headers(user_id, "Broker")


def make_chief_appraiser_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ChiefAppraiser")


def make_oreo_committee_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "OREOCommittee")


def make_credit_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CreditOfficer")


def make_oreo_specialist_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "OREOSpecialist")


def make_property_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PropertyManager")


def make_oreo_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "OREOAdmin")


def make_compliance_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")
