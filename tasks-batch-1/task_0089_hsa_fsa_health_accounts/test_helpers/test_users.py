"""Pre-built role headers for every role in the PRD.

PlanAdmin, Adjudicator, and FundDisburser carry opaque operator ids not tied to any
persisted entity, so the shared constants below are the canonical form for them.
A Participant's X-User-ID must equal the acting Participant entity's id (ownership
checks compare the resource's owning participant_id to X-User-ID), so the shared
constant is only valid for non-ownership tests; ownership-gated calls must use
make_participant_headers(participant_id) with the real id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Distinct opaque operator ids: the segregation-of-duties rule compares the
# adjudicator's recorded id against the disburser's, so these must differ.
ADJUDICATOR_USER_ID = "adj-1"
DISBURSER_USER_ID = "disb-1"

TEST_USERS = {
    "plan_admin_headers": build_user_headers("admin-1", "PlanAdmin"),
    "adjudicator_headers": build_user_headers(ADJUDICATOR_USER_ID, "Adjudicator"),
    "fund_disburser_headers": build_user_headers(DISBURSER_USER_ID, "FundDisburser"),
    # Fallback Participant constant: valid ONLY for tests that do not exercise ownership.
    "participant_headers": build_user_headers("participant-fallback", "Participant"),
}


def make_participant_headers(participant_id: str) -> dict:
    """For the Participant role (entity_backed:Participant). Pass the actual
    Participant.id as the user id whenever the call is ownership-gated."""
    return build_user_headers(participant_id, "Participant")


def make_adjudicator_headers(user_id: str = ADJUDICATOR_USER_ID) -> dict:
    """Opaque Adjudicator headers; override user_id to model a specific operator
    (e.g. to make the disburser equal the adjudicator for a segregation test)."""
    return build_user_headers(user_id, "Adjudicator")


def make_disburser_headers(user_id: str = DISBURSER_USER_ID) -> dict:
    """Opaque FundDisburser headers; override user_id to model a specific operator."""
    return build_user_headers(user_id, "FundDisburser")
