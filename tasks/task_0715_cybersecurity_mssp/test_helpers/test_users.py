"""Pre-built role headers for every role in the PRD.

Per PRD §2.1, all five roles carry an OPAQUE identity: the X-User-ID is an
operator identifier never compared against any persisted entity's id. The
shared-constant form below is therefore the canonical form for every role.
Segregation-of-duties checks compare one recorded X-User-ID against another
recorded X-User-ID, so several tests need DISTINCT user-ids for the same role;
the per-role builders make that explicit.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "engagement_lead_headers": build_user_headers("test-lead-1", "EngagementLead"),
    "soc_analyst_headers": build_user_headers("test-soc-1", "SocAnalyst"),
    "auditor_headers": build_user_headers("test-auditor-1", "Auditor"),
    "client_contact_headers": build_user_headers("test-contact-1", "ClientContact"),
}


# Per-role builders — pass a distinct user_id to drive segregation-of-duties.
def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_engagement_lead_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "EngagementLead")


def make_soc_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SocAnalyst")


def make_auditor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Auditor")


def make_client_contact_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ClientContact")
