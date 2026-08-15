"""Pre-built role headers for every role in the PRD (§2.1).

PracticeAdmin is an opaque role: its X-User-ID is never compared to an entity id,
so a shared constant is canonical. Coach, FamilyMember, and ExternalContact are
entity-backed roles — ownership-gated calls MUST be made with headers built from
the real entity id via the per-instance builders below.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque role: shared constant is the canonical form.
    "admin_headers": build_user_headers("test-admin-1", "PracticeAdmin"),
    # Entity-backed roles: fallback constants for tests that do NOT exercise
    # ownership (e.g. role-denial probes). Never use these for ownership-gated
    # calls — use the builders below with the real entity id.
    "coach_headers": build_user_headers("test-coach-fallback", "Coach"),
    "family_headers": build_user_headers("test-family-fallback", "FamilyMember"),
    "contact_headers": build_user_headers("test-contact-fallback", "ExternalContact"),
}


def make_coach_headers(coach_id: str) -> dict:
    """Coach is entity-backed by Coach.id; pass the real coach id for any call
    whose ownership check compares against coach foreign keys."""
    return build_user_headers(coach_id, "Coach")


def make_family_headers(family_id: str) -> dict:
    """FamilyMember is entity-backed by Family.id; pass the real family id for
    any ownership-gated call."""
    return build_user_headers(family_id, "FamilyMember")


def make_contact_headers(contact_id: str) -> dict:
    """ExternalContact is entity-backed by CoordinationContact.id; pass the real
    contact id for the shared-notes view."""
    return build_user_headers(contact_id, "ExternalContact")
