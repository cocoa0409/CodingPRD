"""Pre-built role headers for every role in the PRD.

ProgramAdmin is an opaque identity: X-User-ID is not tied to any persisted
entity (distinct admin identifiers still matter for segregation-of-duties
checks on recycling batches). VolunteerLead and Volunteer are entity-backed by
Volunteer, Client by Client, and ReferralPartner by ReferralPartner: X-User-ID
is the acting entity's id, so ownership-gated calls MUST use the per-instance
builders with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque ProgramAdmin role, and as fallbacks
# for entity-backed roles in tests that do not exercise ownership.
TEST_USERS = {
    "program_admin_headers": build_user_headers("test-program-admin-1", "ProgramAdmin"),
    # entity_backed roles: shared constants are fallbacks for non-ownership tests only.
    "volunteer_lead_headers": build_user_headers("test-volunteer-lead-1", "VolunteerLead"),
    "volunteer_headers": build_user_headers("test-volunteer-1", "Volunteer"),
    "client_headers": build_user_headers("test-client-1", "Client"),
    "referral_partner_headers": build_user_headers("test-partner-1", "ReferralPartner"),
}


def make_program_admin_headers(user_id: str = "test-program-admin-1") -> dict:
    """ProgramAdmin is opaque; pass a distinct user_id when segregation-of-duties
    compares admin identifiers (recycling seal vs pickup)."""
    return build_user_headers(user_id, "ProgramAdmin")


def make_volunteer_lead_headers(volunteer_id: str) -> dict:
    """For VolunteerLead (entity_backed:Volunteer with is_lead=true). Pass the
    acting Volunteer's id whenever the call is ownership-gated."""
    return build_user_headers(volunteer_id, "VolunteerLead")


def make_volunteer_headers(volunteer_id: str) -> dict:
    """For Volunteer (entity_backed:Volunteer). Pass the acting Volunteer's id
    whenever the call is ownership-gated."""
    return build_user_headers(volunteer_id, "Volunteer")


def make_client_headers(client_id: str) -> dict:
    """For Client (entity_backed:Client). Pass the acting Client's id whenever
    the call is ownership-gated."""
    return build_user_headers(client_id, "Client")


def make_referral_partner_headers(partner_id: str) -> dict:
    """For ReferralPartner (entity_backed:ReferralPartner). Pass the acting
    ReferralPartner's id whenever the call is ownership-gated."""
    return build_user_headers(partner_id, "ReferralPartner")
