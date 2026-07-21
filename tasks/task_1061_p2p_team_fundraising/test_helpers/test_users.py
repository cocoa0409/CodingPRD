"""Pre-built role headers for every role in the PRD.

Identity binding differs by role (PRD §2.1):
  - CampaignManager: X-User-ID is the acting Organization's id  -> per-instance builder
  - Participant:     X-User-ID is the acting Participant's id   -> per-instance builder
  - Donor:           X-User-ID is the acting Donor's id         -> per-instance builder
  - PlatformAdmin / FinanceReviewer / Anonymous: opaque operator identifiers
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import PLATFORM_ADMIN_ID, REVIEWER_ONE_ID, REVIEWER_TWO_ID

# Shared constants — safe for the opaque roles, and for identity-bound roles only
# in tests that never exercise ownership (e.g. 401/403/404 paths).
TEST_USERS = {
    "platform_admin_headers": build_user_headers(PLATFORM_ADMIN_ID, "PlatformAdmin"),
    "finance_reviewer_headers": build_user_headers(REVIEWER_ONE_ID, "FinanceReviewer"),
    "finance_reviewer_two_headers": build_user_headers(
        REVIEWER_TWO_ID, "FinanceReviewer"
    ),
    "anonymous_headers": build_user_headers("anon-visitor-1", "Anonymous"),
    # Fallbacks for entity-backed roles; never use these on ownership-gated calls.
    "campaign_manager_headers": build_user_headers("test-org-1", "CampaignManager"),
    "participant_headers": build_user_headers("test-participant-1", "Participant"),
    "donor_headers": build_user_headers("test-donor-1", "Donor"),
}


def make_campaign_manager_headers(organization_id: str) -> dict:
    """For CampaignManager. Pass the acting Organization's id (PRD §2.1)."""
    return build_user_headers(organization_id, "CampaignManager")


def make_participant_headers(participant_id: str) -> dict:
    """For Participant. Pass the acting Participant's id (PRD §2.1)."""
    return build_user_headers(participant_id, "Participant")


def make_donor_headers(donor_id: str) -> dict:
    """For Donor. Pass the acting Donor's id (PRD §2.1)."""
    return build_user_headers(donor_id, "Donor")


def make_finance_reviewer_headers(user_id: str) -> dict:
    """For FinanceReviewer. The id is opaque but is recorded on the payout."""
    return build_user_headers(user_id, "FinanceReviewer")


def make_platform_admin_headers(user_id: str = PLATFORM_ADMIN_ID) -> dict:
    """For PlatformAdmin. The id is opaque and never compared to an entity id."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_anonymous_headers(user_id: str = "anon-visitor-1") -> dict:
    """For Anonymous. The public surface must state itself explicitly."""
    return build_user_headers(user_id, "Anonymous")
