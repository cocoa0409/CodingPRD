"""Pre-built role headers for every role in the PRD.

ClinicalDirector, Biller, and FrontDesk are opaque identities — X-User-ID is
not compared against any persisted entity, so a shared constant is correct.

Therapist is entity_backed:Therapist — ownership checks compare X-User-ID to the
rendering clinician's id. Use make_therapist_headers(therapist_id) whenever a call
is ownership-gated (render/complete/sign/cosign). The shared constant is a fallback
only for non-ownership tests (e.g., 403-on-wrong-role, 422-on-bad-payload).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "clinical_director_headers": build_user_headers("test-director-1", "ClinicalDirector"),
    "therapist_headers": build_user_headers("test-therapist-1", "Therapist"),
    "biller_headers": build_user_headers("test-biller-1", "Biller"),
    "front_desk_headers": build_user_headers("test-frontdesk-1", "FrontDesk"),
}


def make_therapist_headers(user_id: str) -> dict:
    """For Therapist (entity_backed:Therapist). Pass the actual Therapist.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Therapist")
