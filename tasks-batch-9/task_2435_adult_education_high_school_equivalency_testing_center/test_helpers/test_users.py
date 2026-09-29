"""Caller identities and header builders for the seven declared roles.

Four roles are opaque: any non-empty ``X-User-ID`` string identifies the caller
and the service never resolves it to a record. Three roles are entity-backed —
``CenterAdministrator`` carries a ``TestingCenter`` id, ``Proctor`` carries a
``Proctor`` id and ``Student`` carries a ``Student`` id — so their headers must
always be built from the real record id created during setup.
"""

from __future__ import annotations

from typing import Dict

from .types import Role

#: Stable opaque identities. Entity-backed roles have no default identity because
#: their ``X-User-ID`` must be the id of the record they act for.
TEST_USERS: Dict[str, str] = {
    Role.STATE_AUTHORITY: "state-1",
    Role.PROGRAM_COORDINATOR: "coord-1",
    Role.REGISTRAR: "reg-1",
    Role.INSTRUCTOR: "instructor-1",
}

#: A second distinct identity per opaque role, for separation-of-duties checks.
ALTERNATE_TEST_USERS: Dict[str, str] = {
    Role.STATE_AUTHORITY: "state-2",
    Role.PROGRAM_COORDINATOR: "coord-2",
    Role.REGISTRAR: "reg-2",
    Role.INSTRUCTOR: "instructor-2",
}

#: A role string the PRD does not declare, used to exercise the auth band.
UNDECLARED_ROLE = "AuditorGeneral"


def make_headers(role: str, user_id: str) -> Dict[str, str]:
    """Build the two headers every endpoint requires."""
    return {"X-User-Role": role, "X-User-ID": user_id}


def make_state_authority_headers(user_id: str | None = None) -> Dict[str, str]:
    return make_headers(Role.STATE_AUTHORITY, user_id or TEST_USERS[Role.STATE_AUTHORITY])


def make_program_coordinator_headers(user_id: str | None = None) -> Dict[str, str]:
    return make_headers(
        Role.PROGRAM_COORDINATOR, user_id or TEST_USERS[Role.PROGRAM_COORDINATOR]
    )


def make_registrar_headers(user_id: str | None = None) -> Dict[str, str]:
    return make_headers(Role.REGISTRAR, user_id or TEST_USERS[Role.REGISTRAR])


def make_instructor_headers(user_id: str | None = None) -> Dict[str, str]:
    return make_headers(Role.INSTRUCTOR, user_id or TEST_USERS[Role.INSTRUCTOR])


def make_center_administrator_headers(testing_center_id: str) -> Dict[str, str]:
    """Headers for the administrator of one centre; the id IS the centre id."""
    return make_headers(Role.CENTER_ADMINISTRATOR, testing_center_id)


def make_proctor_headers(proctor_id: str) -> Dict[str, str]:
    """Headers for one proctor; the id IS the proctor record id."""
    return make_headers(Role.PROCTOR, proctor_id)


def make_student_headers(student_id: str) -> Dict[str, str]:
    """Headers for one learner; the id IS the student record id."""
    return make_headers(Role.STUDENT, student_id)


def make_undeclared_role_headers(user_id: str = "outsider-1") -> Dict[str, str]:
    """Headers naming a role the PRD does not declare."""
    return make_headers(UNDECLARED_ROLE, user_id)


#: No authentication headers at all.
NO_AUTH_HEADERS: Dict[str, str] = {}

#: A role header with no accompanying user id.
MISSING_USER_ID_HEADERS: Dict[str, str] = {"X-User-Role": Role.STATE_AUTHORITY}

#: A user id with no accompanying role header.
MISSING_ROLE_HEADERS: Dict[str, str] = {"X-User-ID": TEST_USERS[Role.STATE_AUTHORITY]}
