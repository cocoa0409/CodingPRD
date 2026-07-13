"""Pre-built role headers for every role in the PRD (§2.1).

``Specialist`` and ``Toxicologist`` are entity-backed: their ``X-User-ID`` must be
the ``id`` of a real ``Specialist`` record so that ownership/attribution checks
resolve. Use ``make_specialist_headers(id)`` / ``make_toxicologist_headers(id)``
with the actual entity id whenever a call attributes to or is gated on that user.

``SurveillanceOfficer`` and ``SystemAdmin`` are opaque operator identities.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that never exercise
# specialist ownership/attribution.
TEST_USERS = {
    # entity_backed: shared constant is a fallback for non-ownership tests only.
    "specialist_headers": build_user_headers("test-specialist-1", "Specialist"),
    "toxicologist_headers": build_user_headers("test-toxicologist-1", "Toxicologist"),
    # opaque: shared constant is the canonical form.
    "surveillance_officer_headers": build_user_headers("test-surveillance-1", "SurveillanceOfficer"),
    "system_admin_headers": build_user_headers("test-admin-1", "SystemAdmin"),
}


def make_specialist_headers(user_id: str) -> dict:
    """Headers for a Specialist (entity_backed:Specialist). Pass the actual
    Specialist.id so intake_specialist_id / ownership checks resolve."""
    return build_user_headers(user_id, "Specialist")


def make_toxicologist_headers(user_id: str) -> dict:
    """Headers for a Toxicologist (entity_backed:Specialist with TOXICOLOGIST
    credential). Pass the actual Specialist.id so requesting_specialist_id /
    ownership checks resolve."""
    return build_user_headers(user_id, "Toxicologist")


def make_surveillance_headers(user_id: str = "test-surveillance-1") -> dict:
    return build_user_headers(user_id, "SurveillanceOfficer")


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "SystemAdmin")
