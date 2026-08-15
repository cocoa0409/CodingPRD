"""Pre-built role headers for every role in the PRD.

Organizer and RegistrationDesk are opaque identities: their X-User-ID is
recorded for audit but never compared to an entity id, so shared constants
are canonical. Participant, Judge, and Vendor are entity-backed: ownership
checks compare X-User-ID to a persisted entity id, so per-instance builders
are mandatory for any ownership-gated call.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: shared constants are the canonical form.
    "organizer_headers": build_user_headers("test-organizer-1", "Organizer"),
    "desk_headers": build_user_headers("test-desk-1", "RegistrationDesk"),
    # Entity-backed roles: shared constants are a fallback only for tests
    # whose outcome does not depend on owning the subject resource.
    "participant_headers": build_user_headers("test-participant-1", "Participant"),
    "judge_headers": build_user_headers("test-judge-1", "Judge"),
    "vendor_headers": build_user_headers("test-vendor-1", "Vendor"),
}


def make_organizer_headers(user_id: str) -> dict:
    """Organizer is opaque; distinct ids matter only for segregation-of-duties
    (the finalizer may not override)."""
    return build_user_headers(user_id, "Organizer")


def make_desk_headers(user_id: str) -> dict:
    """RegistrationDesk is opaque."""
    return build_user_headers(user_id, "RegistrationDesk")


def make_participant_headers(user_id: str) -> dict:
    """Participant is entity-backed: pass the acting Registrant.id."""
    return build_user_headers(user_id, "Participant")


def make_judge_headers(user_id: str) -> dict:
    """Judge is entity-backed: pass the acting Judge.id."""
    return build_user_headers(user_id, "Judge")


def make_vendor_headers(user_id: str) -> dict:
    """Vendor is entity-backed: pass the vendor's own BoothApplication.id."""
    return build_user_headers(user_id, "Vendor")
