"""Pre-built role headers for every role in the PRD (§2.1).

Four roles carry an OPAQUE identity — JointUseCoordinator, Engineer,
PermitOfficer, FieldAuditor — whose X-User-ID is recorded where a workflow
calls for it (e.g. surveyor_user_id) but never compared to an entity id. The
Attacher role is ENTITY-BACKED: X-User-ID must equal the acting Attacher
entity's id for ownership-gated calls, so callers MUST use
make_attacher_headers(attacher["id"]).
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles and for tests that don't exercise
# Attacher ownership. The Attacher entry is a fallback for non-ownership tests
# only (e.g. unauthenticated/authorization negatives).
TEST_USERS = {
    "coordinator_headers": build_user_headers("test-coordinator-1", "JointUseCoordinator"),
    "engineer_headers": build_user_headers("test-engineer-1", "Engineer"),
    "permit_officer_headers": build_user_headers("test-permit-officer-1", "PermitOfficer"),
    "field_auditor_headers": build_user_headers("test-field-auditor-1", "FieldAuditor"),
    "attacher_headers": build_user_headers("test-attacher-1", "Attacher"),
}


# Per-instance builders for opaque roles — pass a distinct user_id when a test
# needs to control the recorded operator identity (e.g. surveyor vs officer for
# the four-eyes segregation-of-duties rule).
def make_coordinator_headers(user_id: str = "test-coordinator-1") -> dict:
    return build_user_headers(user_id, "JointUseCoordinator")


def make_engineer_headers(user_id: str = "test-engineer-1") -> dict:
    return build_user_headers(user_id, "Engineer")


def make_permit_officer_headers(user_id: str = "test-permit-officer-1") -> dict:
    return build_user_headers(user_id, "PermitOfficer")


def make_field_auditor_headers(user_id: str = "test-field-auditor-1") -> dict:
    return build_user_headers(user_id, "FieldAuditor")


def make_attacher_headers(user_id: str) -> dict:
    """For the Attacher (entity_backed) role. Pass the actual Attacher.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Attacher")
