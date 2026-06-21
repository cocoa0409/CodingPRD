"""Pre-built role headers for every role in the PRD.

MemberOperator is the only entity-backed role: its X-User-ID must equal the
acting Member's id. Use make_member_operator_headers(member_id) for any
ownership-gated call. Anonymous, FacilityManager, and ComplianceOfficer are
opaque operator identifiers not tied to any persisted entity, so their shared
constants are the canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque roles — shared constant is canonical.
    "anonymous_headers": build_user_headers("anon-1", "Anonymous"),
    "facility_manager_headers": build_user_headers("facility-mgr-1", "FacilityManager"),
    "compliance_officer_headers": build_user_headers("compliance-1", "ComplianceOfficer"),
    # entity_backed MemberOperator — shared constant is a fallback for
    # non-ownership tests only (e.g. 403/401 without a real member). Ownership
    # tests MUST use make_member_operator_headers(member["id"]).
    "member_operator_headers": build_user_headers("member-op-unknown", "MemberOperator"),
}


def make_member_operator_headers(member_id: str) -> dict:
    """For MemberOperator (entity_backed:Member). Pass the actual Member.id as
    user_id whenever the call is ownership-gated (every member-scoped write)."""
    return build_user_headers(member_id, "MemberOperator")


def make_anonymous_headers() -> dict:
    return build_user_headers("anon-1", "Anonymous")
