"""Pre-built role headers for every role in the PRD.

CenterDirector and BillingAdmin are opaque operator identities (X-User-ID is not
compared to any entity id), so shared constants are the canonical form for them.
Parent (entity_backed:Family) and Teacher (entity_backed:Classroom) need
per-instance builders so ownership checks resolve against the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator roles — shared constant is the canonical form.
    "director_headers": build_user_headers("test-director-1", "CenterDirector"),
    "billing_headers": build_user_headers("test-billing-1", "BillingAdmin"),
    # Entity-backed roles — shared constants for non-ownership tests only
    # (e.g. 401/403/404 paths). Ownership-gated calls MUST use the builders below.
    "parent_headers": build_user_headers("test-parent-1", "Parent"),
    "teacher_headers": build_user_headers("test-teacher-1", "Teacher"),
}


def make_director_headers(user_id: str = "test-director-1") -> dict:
    """CenterDirector is opaque; user_id is not entity-checked."""
    return build_user_headers(user_id, "CenterDirector")


def make_billing_headers(user_id: str = "test-billing-1") -> dict:
    """BillingAdmin is opaque; user_id is not entity-checked."""
    return build_user_headers(user_id, "BillingAdmin")


def make_parent_headers(user_id: str) -> dict:
    """For Parent (entity_backed:Family). Pass the acting Family.id as user_id
    whenever the call is ownership-gated (child/waitlist/enrollment-accept)."""
    return build_user_headers(user_id, "Parent")


def make_teacher_headers(user_id: str) -> dict:
    """For Teacher (entity_backed:Classroom). Pass the acting Classroom.id as
    user_id whenever the call is ownership-gated (attendance create/check-out)."""
    return build_user_headers(user_id, "Teacher")
