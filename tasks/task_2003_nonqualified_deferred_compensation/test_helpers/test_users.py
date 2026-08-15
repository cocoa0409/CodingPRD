"""Pre-built role headers for every role in the PRD (§2.1).

The Participant role is entity-backed: X-User-ID must equal the acting
Participant record's id. Use make_participant_headers(participant["id"]) for
any ownership-gated call; the shared "participant_headers" constant is a
fallback for non-ownership tests only.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: shared constants are the canonical form (PRD §2.1).
    "plan_sponsor_headers": build_user_headers("ps-1", "PlanSponsor"),
    "benefits_admin_headers": build_user_headers("ba-1", "BenefitsAdministrator"),
    "benefits_admin_2_headers": build_user_headers("ba-2", "BenefitsAdministrator"),
    "compliance_officer_headers": build_user_headers("co-1", "ComplianceOfficer"),
    "compliance_officer_2_headers": build_user_headers("co-2", "ComplianceOfficer"),
    "trust_officer_headers": build_user_headers("to-1", "TrustOfficer"),
    "platform_admin_headers": build_user_headers("pa-1", "PlatformAdmin"),
    # entity_backed:Participant — fallback for non-ownership tests only.
    "participant_headers": build_user_headers("test-participant-fallback", "Participant"),
}


def make_participant_headers(user_id: str) -> dict:
    """For Participant (entity_backed:Participant). Pass the actual
    Participant.id as user_id whenever the call is ownership-gated
    (election create/submit/void, distribution create)."""
    return build_user_headers(user_id, "Participant")


def make_compliance_officer_headers(user_id: str) -> dict:
    """ComplianceOfficer with a caller-chosen opaque user id (used by
    segregation-of-duties probes that deliberately reuse another actor's id)."""
    return build_user_headers(user_id, "ComplianceOfficer")
