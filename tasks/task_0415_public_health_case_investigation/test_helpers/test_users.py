"""Pre-built role headers for every role in the PRD.

Two program-wide roles (JurisdictionAdmin, EpiAnalyst) carry opaque X-User-ID
identifiers not tied to any persisted entity — their shared constants are the
canonical form. The three operational roles (IntakeProcessor, CaseInvestigator,
ContactTracer) are jurisdiction-scoped: their X-User-ID is the id of the acting
Jurisdiction. For any ownership-gated call, the per-instance builder MUST be used
with the real Jurisdiction.id; the shared constant is a fallback for tests that do
not exercise the jurisdiction-scope overlay (e.g. 400/403/404 before the scope check).
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque, program-wide roles — shared constant is canonical.
    "admin_headers": build_user_headers("test-admin-1", "JurisdictionAdmin"),
    "epi_headers": build_user_headers("test-epi-1", "EpiAnalyst"),
    # Scoped roles — shared fallback for non-ownership tests only.
    "intake_headers": build_user_headers("test-intake-1", "IntakeProcessor"),
    "investigator_headers": build_user_headers("test-investigator-1", "CaseInvestigator"),
    "tracer_headers": build_user_headers("test-tracer-1", "ContactTracer"),
}


# ── Per-instance builders (mandatory for entity_backed:Jurisdiction roles) ──
def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    """JurisdictionAdmin (opaque). X-User-ID is not compared to any entity."""
    return build_user_headers(user_id, "JurisdictionAdmin")


def make_epi_headers(user_id: str = "test-epi-1") -> dict:
    """EpiAnalyst (opaque, program-wide). X-User-ID is not compared to any entity."""
    return build_user_headers(user_id, "EpiAnalyst")


def make_intake_headers(jurisdiction_id: str) -> dict:
    """IntakeProcessor (entity_backed:Jurisdiction). Pass the acting Jurisdiction.id."""
    return build_user_headers(jurisdiction_id, "IntakeProcessor")


def make_investigator_headers(jurisdiction_id: str) -> dict:
    """CaseInvestigator (entity_backed:Jurisdiction). Pass the case's Jurisdiction.id
    for ownership-gated case operations."""
    return build_user_headers(jurisdiction_id, "CaseInvestigator")


def make_tracer_headers(jurisdiction_id: str) -> dict:
    """ContactTracer (entity_backed:Jurisdiction). Pass the contact's monitoring
    Jurisdiction.id for ownership-gated contact operations."""
    return build_user_headers(jurisdiction_id, "ContactTracer")


def make_unknown_role_headers(user_id: str = "test-bogus-1") -> dict:
    """A header set whose X-User-Role is not one of the five recognized roles.
    Used for the unknown-role rejection test (ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)."""
    return build_user_headers(user_id, "SUPERHERO")
