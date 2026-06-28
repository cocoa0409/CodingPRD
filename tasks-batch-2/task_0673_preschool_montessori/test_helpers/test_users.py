"""Pre-built role headers for every role in the PRD.

All four roles carry an *opaque* identity (PRD §2.1): the server never compares
X-User-ID to an entity id. Two roles, however, carry operator-id semantics that
fixtures must thread explicitly:

  * Parent — ownership of a Parent-actionable resource is determined by comparing
    the acting parent's X-User-ID to the owning Student.parent_user_id. A Student
    is registered with parent_user_id set to the acting parent. So whenever a test
    registers a student as "parent-1" and later acts (resubmit / accept-offer /
    decline-offer / book) on that student, the acting Parent headers MUST carry the
    same X-User-ID "parent-1" — use make_parent_headers("parent-1").

  * Guide — completing / no-show / cancel on a ConferenceSlot requires the acting
    guide's X-User-ID to equal the slot's stored guide_user_id. Use
    make_guide_headers("guide-1") to match the guide_user_id given at slot open.

The shared TEST_USERS constants are safe for opaque-only tests (403-on-bad-role,
404-on-missing-resource, reads, ComplianceOfficer/Registrar operator actions).
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "registrar_headers": build_user_headers("test-registrar-1", "Registrar"),
    "guide_headers": build_user_headers("test-guide-1", "Guide"),
    "compliance_officer_headers": build_user_headers("test-compliance-1", "ComplianceOfficer"),
    "parent_headers": build_user_headers("test-parent-1", "Parent"),
}


def make_registrar_headers(user_id: str = "test-registrar-1") -> dict:
    """Registrar (opaque). The operator id is never matched against an entity id."""
    return build_user_headers(user_id, "Registrar")


def make_compliance_officer_headers(user_id: str = "test-compliance-1") -> dict:
    """ComplianceOfficer (opaque). The operator id is never matched against an entity id."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_parent_headers(parent_user_id: str) -> dict:
    """Parent (opaque, ownership semantics). Pass the same parent_user_id that was
    stored on the Student so ownership-gated calls (resubmit, accept-offer,
    decline-offer, book) pass the X-User-ID == Student.parent_user_id check."""
    return build_user_headers(parent_user_id, "Parent")


def make_guide_headers(guide_user_id: str) -> dict:
    """Guide (opaque, slot-control semantics). Pass the same guide_user_id stored on
    the ConferenceSlot so complete / no-show / cancel pass the
    X-User-ID == slot.guide_user_id check."""
    return build_user_headers(guide_user_id, "Guide")
