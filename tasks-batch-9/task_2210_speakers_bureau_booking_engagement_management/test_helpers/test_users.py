"""Caller identities and header builders (PRD §2.1, §2.4).

Two of the four roles are backed by a stored row: a ``Speaker`` caller sends
the id of the speaker row it represents and a ``Client`` caller sends the id of
the client row it represents.  Tests that exercise ownership must therefore
build those headers from the id returned when the row was created, using
``make_speaker_headers`` / ``make_client_headers``, rather than reusing a fixed
placeholder identity.

The remaining two roles (``BureauAdmin`` and ``BookingAgent``) are opaque staff
identities and may be reused freely.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# Opaque staff identities: any stable string is a valid user id for these
# roles because the PRD does not tie them to a stored row.
ADMIN_USER_ID = "admin-01"
AGENT_USER_ID = "agent-01"
OTHER_AGENT_USER_ID = "agent-02"

# Placeholder entity-backed identities. These are only useful for calls where
# the PRD gates on the role alone; ownership-gated calls must use the builders
# below with a real row id.
PLACEHOLDER_SPEAKER_USER_ID = "00000000-0000-4000-8000-0000000000aa"
PLACEHOLDER_CLIENT_USER_ID = "00000000-0000-4000-8000-0000000000bb"


TEST_USERS = {
    "admin": {
        "user_id": ADMIN_USER_ID,
        "role": UserRole.BUREAU_ADMIN.value,
    },
    "agent": {
        "user_id": AGENT_USER_ID,
        "role": UserRole.BOOKING_AGENT.value,
    },
    "other_agent": {
        "user_id": OTHER_AGENT_USER_ID,
        "role": UserRole.BOOKING_AGENT.value,
    },
    "speaker": {
        "user_id": PLACEHOLDER_SPEAKER_USER_ID,
        "role": UserRole.SPEAKER.value,
    },
    "client": {
        "user_id": PLACEHOLDER_CLIENT_USER_ID,
        "role": UserRole.CLIENT.value,
    },
}


def make_admin_headers(user_id: str = ADMIN_USER_ID) -> dict:
    """Headers for a BureauAdmin caller."""
    return build_user_headers(user_id, UserRole.BUREAU_ADMIN.value)


def make_agent_headers(user_id: str = AGENT_USER_ID) -> dict:
    """Headers for a BookingAgent caller."""
    return build_user_headers(user_id, UserRole.BOOKING_AGENT.value)


def make_speaker_headers(user_id: str) -> dict:
    """Headers for a Speaker caller; user_id must be the speaker row's id."""
    return build_user_headers(user_id, UserRole.SPEAKER.value)


def make_client_headers(user_id: str) -> dict:
    """Headers for a Client caller; user_id must be the client row's id."""
    return build_user_headers(user_id, UserRole.CLIENT.value)


def make_headers_without_user_id(role: str) -> dict:
    """Headers that carry a role but no X-User-ID, to probe the header check."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def make_headers_without_role(user_id: str) -> dict:
    """Headers that carry an X-User-ID but no role."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


ADMIN_HEADERS = make_admin_headers()
AGENT_HEADERS = make_agent_headers()
OTHER_AGENT_HEADERS = make_agent_headers(OTHER_AGENT_USER_ID)
