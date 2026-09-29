"""Canonical acting identities and the header builders that carry them.

Every request carries ``X-User-ID`` naming the acting party and ``X-User-Role``
naming the capacity it acts in.  Four of the five roles use a free-form
identifier.  ``CustomerCommitteeRep`` is the exception: for that role
``X-User-ID`` is the id of the apparatus program whose committee the
representative speaks for, so its headers can only be built once the program
exists.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# ─── Stable identifiers for the four free-form roles ──────────────────────

PROGRAM_ADMIN_ID = "admin-1"
PURCHASING_OFFICER_ID = "po-1"
BODY_ENGINEER_ID = "eng-1"
THIRD_PARTY_TESTER_ID = "tester-1"

# A specification must be released by someone other than its author, and a
# certification result must be signed by someone other than the unit's weight
# calculation engineer, so a second identity is needed for each of those roles.
SPEC_AUTHOR_ID = "po-author"
SPEC_RELEASER_ID = "po-releaser"
SECOND_BODY_ENGINEER_ID = "eng-2"
SECOND_THIRD_PARTY_TESTER_ID = "tester-2"


# ─── Header builders ──────────────────────────────────────────────────────

def make_program_admin_headers(user_id=PROGRAM_ADMIN_ID):
    return build_user_headers(user_id, UserRole.PROGRAM_ADMIN.value)


def make_purchasing_officer_headers(user_id=PURCHASING_OFFICER_ID):
    return build_user_headers(user_id, UserRole.PURCHASING_OFFICER.value)


def make_body_engineer_headers(user_id=BODY_ENGINEER_ID):
    return build_user_headers(user_id, UserRole.BODY_ENGINEER.value)


def make_third_party_tester_headers(user_id=THIRD_PARTY_TESTER_ID):
    return build_user_headers(user_id, UserRole.THIRD_PARTY_TESTER.value)


def make_customer_committee_rep_headers(program_id):
    """Headers for the committee of one specific apparatus program.

    ``X-User-ID`` must be the program's own id: ownership checks compare the
    program of the addressed resource against this header, and a mismatch is a
    committee-scope violation.
    """
    return build_user_headers(program_id, UserRole.CUSTOMER_COMMITTEE_REP.value)


# ─── Malformed-authentication headers ─────────────────────────────────────

def make_headers_missing_user_id(role=UserRole.PROGRAM_ADMIN.value):
    return {"X-User-Role": role}


def make_headers_missing_role(user_id=PROGRAM_ADMIN_ID):
    return {"X-User-ID": user_id}


def make_headers_with_unknown_role(user_id=PROGRAM_ADMIN_ID, role="PlantForeman"):
    return build_user_headers(user_id, role)


ALL_ROLE_HEADER_BUILDERS = {
    UserRole.PROGRAM_ADMIN.value: make_program_admin_headers,
    UserRole.PURCHASING_OFFICER.value: make_purchasing_officer_headers,
    UserRole.BODY_ENGINEER.value: make_body_engineer_headers,
    UserRole.THIRD_PARTY_TESTER.value: make_third_party_tester_headers,
}
