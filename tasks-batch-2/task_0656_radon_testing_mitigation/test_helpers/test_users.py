"""Pre-built role headers for every role in the PRD.

Per PRD §2.1 the six roles relate to persisted entities three ways:
  - Inspector       → X-User-ID is the acting Inspector.id (entity-backed)
  - CrewLead        → X-User-ID is the acting MitigationCrew.id (entity-backed)
  - ClientContact   → X-User-ID is the acting Property.id (entity-backed)
  - PlatformAdmin / MitigationDesigner / ComplianceOfficer → opaque operator ids

Entity-backed roles get a per-instance builder make_<role>_headers(entity_id)
that MUST be used with the real entity id whenever a call is ownership-gated.
The shared TEST_USERS constants are safe only for opaque roles and for tests
that do not exercise ownership (bad-payload, missing-resource, RBAC-forbidden).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — the shared constant is the canonical form.
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "mitigation_designer_headers": build_user_headers("test-designer-1", "MitigationDesigner"),
    "compliance_officer_headers": build_user_headers("test-compliance-1", "ComplianceOfficer"),

    # Entity-backed roles — shared constant is a fallback for non-ownership tests only.
    "inspector_headers": build_user_headers("test-inspector-1", "Inspector"),
    "crew_lead_headers": build_user_headers("test-crew-1", "CrewLead"),
    "client_contact_headers": build_user_headers("test-client-1", "ClientContact"),
}


# ── Per-instance builders for entity-backed roles ──────────────────────────

def make_inspector_headers(inspector_id: str) -> dict:
    """For Inspector (X-User-ID = Inspector.id). Pass the real inspector id."""
    return build_user_headers(inspector_id, "Inspector")


def make_crew_lead_headers(crew_id: str) -> dict:
    """For CrewLead (X-User-ID = MitigationCrew.id). Pass the real crew id."""
    return build_user_headers(crew_id, "CrewLead")


def make_client_contact_headers(property_id: str) -> dict:
    """For ClientContact (X-User-ID = Property.id). Pass the real property id."""
    return build_user_headers(property_id, "ClientContact")


# ── Opaque-role builders (id is recorded but never compared) ───────────────

def make_platform_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_mitigation_designer_headers(user_id: str = "test-designer-1") -> dict:
    return build_user_headers(user_id, "MitigationDesigner")


def make_compliance_officer_headers(user_id: str = "test-compliance-1") -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")
