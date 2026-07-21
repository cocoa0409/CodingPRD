"""Pre-built role headers for every role in the PRD.

Three roles are entity-backed (``Attendee`` -> Registration.id,
``SpeakerUser`` -> Speaker.id, ``SponsorUser`` -> Sponsor.id); calls made in
those capacities must use the per-instance builders below with the real row's
``id``. The shared ``TEST_USERS`` constants are safe only for the three opaque
roles, and for tests that never exercise an ownership comparison.
"""
from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ORGANIZER_USER_ID,
    OTHER_ORGANIZER_USER_ID,
    PLATFORM_ADMIN_USER_ID,
    FINANCE_ADMIN_USER_ID,
    SECOND_FINANCE_ADMIN_USER_ID,
)

TEST_USERS = {
    # Opaque roles - the shared constant is the canonical form.
    "organizer_headers": build_user_headers(ORGANIZER_USER_ID, "Organizer"),
    "other_organizer_headers": build_user_headers(OTHER_ORGANIZER_USER_ID, "Organizer"),
    "platform_admin_headers": build_user_headers(PLATFORM_ADMIN_USER_ID, "PlatformAdmin"),
    "finance_admin_headers": build_user_headers(FINANCE_ADMIN_USER_ID, "FinanceAdmin"),
    "second_finance_admin_headers": build_user_headers(
        SECOND_FINANCE_ADMIN_USER_ID, "FinanceAdmin"
    ),
    # Entity-backed roles - fallbacks for non-ownership tests only.
    "attendee_headers": build_user_headers("test-attendee-1", "Attendee"),
    "speaker_headers": build_user_headers("test-speaker-1", "SpeakerUser"),
    "sponsor_headers": build_user_headers("test-sponsor-1", "SponsorUser"),
}


def make_organizer_headers(user_id: str = ORGANIZER_USER_ID) -> dict:
    """Organizer identity. Must match the target event's organizer_user_id."""
    return build_user_headers(user_id, "Organizer")


def make_platform_admin_headers(user_id: str = PLATFORM_ADMIN_USER_ID) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_finance_admin_headers(user_id: str = FINANCE_ADMIN_USER_ID) -> dict:
    return build_user_headers(user_id, "FinanceAdmin")


def make_attendee_headers(registration_id: str) -> dict:
    """For Attendee actions. Pass the acting Registration's id."""
    return build_user_headers(registration_id, "Attendee")


def make_speaker_headers(speaker_id: str) -> dict:
    """For SpeakerUser actions. Pass the acting Speaker's id."""
    return build_user_headers(speaker_id, "SpeakerUser")


def make_sponsor_headers(sponsor_id: str) -> dict:
    """For SponsorUser actions. Pass the acting Sponsor's id."""
    return build_user_headers(sponsor_id, "SponsorUser")


def make_unknown_role_headers(user_id: str = "ghost-1", role: str = "Ghost") -> dict:
    """Headers naming a role outside the six declared names."""
    return build_user_headers(user_id, role)
