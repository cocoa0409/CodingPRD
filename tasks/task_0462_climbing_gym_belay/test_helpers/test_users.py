"""Pre-built role headers for every role in the PRD.

The Member role is entity-backed: its X-User-ID must equal the acting Member's
id for ownership checks to pass. Use make_member_headers(member_id) whenever a
call is ownership-gated. The other four roles (FrontDesk, Examiner, RouteSetter,
GymAdmin) are opaque operator identifiers; their shared constants are canonical.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for Member tests that do NOT
# exercise ownership (e.g. 400/403/404 paths). For ownership-gated Member calls,
# use make_member_headers(member_id) with the real Member id instead.
TEST_USERS = {
    # opaque roles — shared constant is the canonical form.
    "frontdesk_headers": build_user_headers("frontdesk-1", "FrontDesk"),
    "examiner_headers": build_user_headers("examiner-1", "Examiner"),
    "setter_headers": build_user_headers("setter-1", "RouteSetter"),
    "admin_headers": build_user_headers("admin-1", "GymAdmin"),
    # entity_backed Member — shared constant is a fallback for non-ownership tests only.
    "member_headers": build_user_headers("member-placeholder", "Member"),
}


# ─── Per-instance builders ────────────────────────────────────────────────
def make_member_headers(member_id: str) -> dict:
    """For the Member role (entity_backed:Member). Pass the actual Member.id as
    user_id whenever the call is ownership-gated (freeze/resume/cancel/withdraw/
    enroll-own)."""
    return build_user_headers(member_id, "Member")


def make_setter_headers(setter_user_id: str) -> dict:
    """For RouteSetter (opaque). The id is recorded as setter_user_id on routes;
    pass an explicit value when a test needs a specific setter identity."""
    return build_user_headers(setter_user_id, "RouteSetter")


def make_examiner_headers(examiner_user_id: str) -> dict:
    """For Examiner (opaque). The id is recorded as examiner_user_id on graded
    certifications; pass an explicit value when needed."""
    return build_user_headers(examiner_user_id, "Examiner")
