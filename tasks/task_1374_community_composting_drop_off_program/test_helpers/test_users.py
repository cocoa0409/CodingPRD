"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not
# exercise ownership. entity_backed roles also get per-instance builders below.
TEST_USERS = {
    "anonymous_headers": build_user_headers("anon-1", "Anonymous"),
    "program_admin_headers": build_user_headers("test-admin-1", "ProgramAdmin"),
    "site_host_headers": build_user_headers("test-host-1", "SiteHost"),
    "participant_headers": build_user_headers("test-participant-1", "Participant"),
    "route_operator_headers": build_user_headers("test-operator-1", "RouteOperator"),
    "processing_partner_headers": build_user_headers("test-partner-1", "ProcessingPartner"),
    "municipal_auditor_headers": build_user_headers("aud-1", "MunicipalAuditor"),
}


def make_participant_headers(user_id: str) -> dict:
    """For Participant (entity_backed). Pass the actual Participant.id as
    user_id whenever the call is ownership-gated (drops, allocations)."""
    return build_user_headers(user_id, "Participant")


def make_processing_partner_headers(user_id: str) -> dict:
    """For ProcessingPartner (entity_backed). Pass the actual
    ProcessingPartner.id as user_id for the batch-close call."""
    return build_user_headers(user_id, "ProcessingPartner")


def make_municipal_auditor_headers(user_id: str) -> dict:
    """For MunicipalAuditor (opaque). Distinct ids are used to exercise
    segregation-of-duties (certifier must differ from creator)."""
    return build_user_headers(user_id, "MunicipalAuditor")
