"""Caller identities and header builders.

Five roles are opaque operator identities, so a shared constant identifier is
enough. Two roles are entity-backed: a `Volunteer` caller's ``X-User-ID`` is a
Volunteer row's id and a `CouncilRepresentative` caller's ``X-User-ID`` is a
Resident row's id, so those headers can only be built once the row exists.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import (
    ROLE_ACTIVITY_AIDE,
    ROLE_ACTIVITY_DIRECTOR,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_COUNCIL_REPRESENTATIVE,
    ROLE_RECREATION_THERAPIST,
    ROLE_VOLUNTEER,
    ROLE_VOLUNTEER_COORDINATOR,
)

# Opaque operator identifiers.
DIRECTOR_USER_ID = "director-01"
THERAPIST_USER_ID = "therapist-A"
THERAPIST_B_USER_ID = "therapist-B"
AIDE_USER_ID = "aide-01"
COORDINATOR_USER_ID = "coordinator-01"
COMPLIANCE_USER_ID = "compliance-A"
COMPLIANCE_B_USER_ID = "compliance-B"

TEST_USERS = {
    "director": {"user_id": DIRECTOR_USER_ID, "role": ROLE_ACTIVITY_DIRECTOR},
    "therapist": {"user_id": THERAPIST_USER_ID, "role": ROLE_RECREATION_THERAPIST},
    "therapist_b": {"user_id": THERAPIST_B_USER_ID, "role": ROLE_RECREATION_THERAPIST},
    "aide": {"user_id": AIDE_USER_ID, "role": ROLE_ACTIVITY_AIDE},
    "coordinator": {"user_id": COORDINATOR_USER_ID, "role": ROLE_VOLUNTEER_COORDINATOR},
    "compliance": {"user_id": COMPLIANCE_USER_ID, "role": ROLE_COMPLIANCE_OFFICER},
    "compliance_b": {"user_id": COMPLIANCE_B_USER_ID, "role": ROLE_COMPLIANCE_OFFICER},
}

DIRECTOR_HEADERS = build_user_headers(DIRECTOR_USER_ID, ROLE_ACTIVITY_DIRECTOR)
THERAPIST_HEADERS = build_user_headers(THERAPIST_USER_ID, ROLE_RECREATION_THERAPIST)
THERAPIST_B_HEADERS = build_user_headers(THERAPIST_B_USER_ID, ROLE_RECREATION_THERAPIST)
AIDE_HEADERS = build_user_headers(AIDE_USER_ID, ROLE_ACTIVITY_AIDE)
COORDINATOR_HEADERS = build_user_headers(COORDINATOR_USER_ID, ROLE_VOLUNTEER_COORDINATOR)
COMPLIANCE_HEADERS = build_user_headers(COMPLIANCE_USER_ID, ROLE_COMPLIANCE_OFFICER)
COMPLIANCE_B_HEADERS = build_user_headers(COMPLIANCE_B_USER_ID, ROLE_COMPLIANCE_OFFICER)


def make_volunteer_headers(volunteer_id):
    """Headers for a volunteer acting for themselves."""
    return build_user_headers(volunteer_id, ROLE_VOLUNTEER)


def make_council_rep_headers(resident_id):
    """Headers for a council representative backed by a Resident row."""
    return build_user_headers(resident_id, ROLE_COUNCIL_REPRESENTATIVE)


def make_therapist_headers(user_id):
    """Headers for a specific therapist identity, for segregation-of-duties tests."""
    return build_user_headers(user_id, ROLE_RECREATION_THERAPIST)


def make_compliance_headers(user_id):
    """Headers for a specific compliance officer identity."""
    return build_user_headers(user_id, ROLE_COMPLIANCE_OFFICER)


def make_headers(user_id, role):
    """Headers for an arbitrary identifier / role string pair."""
    return build_user_headers(user_id, role)


def headers_without_role(user_id):
    """Headers carrying an identifier but no role at all."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role):
    """Headers carrying a role but no identifier at all."""
    return {"X-User-Role": role, "Content-Type": "application/json"}
