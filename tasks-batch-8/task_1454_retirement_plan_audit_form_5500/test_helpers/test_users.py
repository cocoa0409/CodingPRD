"""Pre-built role headers for every role in the PRD (§2.1).

All roles use the opaque identity model: ``X-User-ID`` is an opaque operator
identifier that the server never compares against any entity's ``id``; it is
recorded (``proposed_by_user_id``, ``approved_by_user_id``,
``created_by_user_id``) solely so segregation-of-duties checks can compare the
operator id captured at one step against the one presented at the paired step.
The constants below therefore use stable, distinct operator ids per duty lane.
"""
from prd_bench_local_runner.testing import build_user_headers

# Canonical operator ids per duty lane. The sponsor lane and the manager lane
# must stay distinct so propose/approve and create/mark_ready SoD pairs pass.
SPONSOR_USER_ID = "u-sponsor-1"
SPONSOR_2_USER_ID = "u-sponsor-2"
TPA_USER_ID = "u-tpa-1"
AUDITOR_USER_ID = "u-auditor-1"
MANAGER_USER_ID = "u-manager-1"
SYSTEM_USER_ID = "u-system-1"

SPONSOR = build_user_headers(SPONSOR_USER_ID, "SponsorAdmin")
SPONSOR_2 = build_user_headers(SPONSOR_2_USER_ID, "SponsorAdmin")
TPA = build_user_headers(TPA_USER_ID, "TPASpecialist")
AUDITOR = build_user_headers(AUDITOR_USER_ID, "PlanAuditor")
MANAGER = build_user_headers(MANAGER_USER_ID, "EngagementManager")
SYSTEM = build_user_headers(SYSTEM_USER_ID, "System")

TEST_USERS = {
    "sponsor_admin_headers": SPONSOR,
    "sponsor_admin_2_headers": SPONSOR_2,
    "tpa_specialist_headers": TPA,
    "plan_auditor_headers": AUDITOR,
    "engagement_manager_headers": MANAGER,
    "system_headers": SYSTEM,
}


def make_sponsor_headers(user_id: str) -> dict:
    """SponsorAdmin headers for a specific operator id (SoD scenarios)."""
    return build_user_headers(user_id, "SponsorAdmin")


def make_manager_headers(user_id: str) -> dict:
    """EngagementManager headers for a specific operator id (SoD scenarios)."""
    return build_user_headers(user_id, "EngagementManager")


def make_tpa_headers(user_id: str) -> dict:
    """TPASpecialist headers for a specific operator id (SoD scenarios)."""
    return build_user_headers(user_id, "TPASpecialist")
