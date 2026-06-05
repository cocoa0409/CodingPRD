"""Pre-built role headers for every role in the PRD.

EligibilityClerk and CompetentProfessionalAuthority use opaque operator
identities (X-User-ID is not tied to any persisted entity), so their shared
constants are the canonical form. Participant is entity-backed: X-User-ID must
equal the acting Participant's id, so ownership-gated calls (notably
POST /redemptions and GET on own participant/EBT) MUST use
make_participant_headers(participant_id), never the shared constant.

Two distinct CPA identities are provided because approval enforces segregation
of duties against the user that ran income determination: an approval by the
same X-User-ID as determine-income is rejected.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — canonical for opaque roles; for entity-backed Participant
# the shared constant is a fallback usable only on non-ownership paths
# (e.g. a Participant attempting a forbidden write that fails at RBAC).
TEST_USERS = {
    "clerk_headers": build_user_headers("clerk-1", "EligibilityClerk"),
    "clerk2_headers": build_user_headers("clerk-2", "EligibilityClerk"),
    "cpa_headers": build_user_headers("cpa-1", "CompetentProfessionalAuthority"),
    "cpa2_headers": build_user_headers("cpa-2", "CompetentProfessionalAuthority"),
    # Opaque-identity fallback for a Participant whose request fails before any
    # ownership comparison (e.g. an RBAC-forbidden write).
    "participant_headers": build_user_headers(
        "00000000-0000-0000-0000-000000000001", "Participant"
    ),
}


def make_clerk_headers(user_id: str = "clerk-1") -> dict:
    """EligibilityClerk (opaque identity). user_id is an arbitrary operator id;
    it is recorded as determined_by_user_id at determine-income."""
    return build_user_headers(user_id, "EligibilityClerk")


def make_cpa_headers(user_id: str = "cpa-1") -> dict:
    """CompetentProfessionalAuthority (opaque identity). user_id is recorded as
    certified_by_user_id at approval; it must differ from the determine-income
    user_id for the segregation-of-duties check to pass."""
    return build_user_headers(user_id, "CompetentProfessionalAuthority")


def make_participant_headers(participant_id: str) -> dict:
    """Participant (entity_backed:Participant). Pass the actual Participant.id as
    participant_id whenever the call is ownership-gated (POST /redemptions on the
    own EBT account, GET on own participant / EBT / redemptions)."""
    return build_user_headers(participant_id, "Participant")
