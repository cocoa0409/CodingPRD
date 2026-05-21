"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

    "ElectionBoard, RegistrarClerk, ReviewerClerk, PrecinctOfficer, and
    TestDriver are all operator roles whose X-User-ID is an opaque
    operator identifier not tied to any persisted entity."

    "When X-User-Role is Voter, X-User-ID is the id of the acting Voter;
    ownership checks on any resource that references a Voter compare
    that resource's voter_id foreign key to X-User-ID, and a Voter can
    only act on their own row."

Operator roles (ElectionBoard, RegistrarClerk, ReviewerClerk,
PrecinctOfficer, TestDriver) are `opaque` — a shared constant suffices
for tests that do not depend on the opaque-id matching any persisted
field. The one exception is the SOD check on CuringCase mutations:
PRD §2.1 says "the ReviewerClerk who acts on a CuringCase ... must
present an X-User-ID different from the Voter.registered_by_user_id
snapshot captured when that voter transitioned from PENDING to ACTIVE."
For that path, fixtures use distinct registrar-clerk and reviewer-clerk
ids so the SOD check passes by construction.

Voter is `entity_backed:Voter` — fixtures that exercise ownership
(submit cure, change own party, request own absentee ballot, PATCH own
row) MUST mint headers via make_voter_headers(voter_id) with the real
Voter.id.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Stable opaque ids for operator roles. The REGISTRAR_CLERK id is the one
# fixtures use when activating voters, and the REVIEWER_CLERK id is the
# one used for curing-case adjudication; they are distinct so the SOD
# check on POST /curing-cases/{caseId}/* passes by default.
# ---------------------------------------------------------------------------
ELECTION_BOARD_ID: str = "election-board-op-0001"
REGISTRAR_CLERK_ID: str = "registrar-clerk-op-0001"
REGISTRAR_CLERK_ALT_ID: str = "registrar-clerk-op-0002"
REVIEWER_CLERK_ID: str = "reviewer-clerk-op-0001"
REVIEWER_CLERK_ALT_ID: str = "reviewer-clerk-op-0002"
PRECINCT_OFFICER_ID: str = "precinct-officer-op-0001"
TEST_DRIVER_ID: str = "test-driver-op-0001"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque operator roles. Safe as shared constants for any test whose
    # success does not depend on the opaque id matching a stored field.
    "election_board_headers": build_user_headers(
        ELECTION_BOARD_ID, "ElectionBoard",
    ),
    "registrar_clerk_headers": build_user_headers(
        REGISTRAR_CLERK_ID, "RegistrarClerk",
    ),
    "registrar_clerk_alt_headers": build_user_headers(
        REGISTRAR_CLERK_ALT_ID, "RegistrarClerk",
    ),
    "reviewer_clerk_headers": build_user_headers(
        REVIEWER_CLERK_ID, "ReviewerClerk",
    ),
    "reviewer_clerk_alt_headers": build_user_headers(
        REVIEWER_CLERK_ALT_ID, "ReviewerClerk",
    ),
    "precinct_officer_headers": build_user_headers(
        PRECINCT_OFFICER_ID, "PrecinctOfficer",
    ),
    "test_driver_headers": build_user_headers(
        TEST_DRIVER_ID, "TestDriver",
    ),
    # entity_backed:Voter — shared constant only valid for tests that
    # don't fire an ownership check (e.g., 404 probes, role-forbidden
    # probes on Voter-exclusive endpoints).
    "voter_headers": build_user_headers("voter-shared-0001", "Voter"),
}


# ---------------------------------------------------------------------------
# Per-instance builders for entity_backed:Voter — MANDATORY whenever a
# call goes through a Voter ownership check (PATCH /voters/{voterId} by
# the voter themselves, POST /voters/{voterId}/party-registration as
# VoterSelf, POST /voters/{voterId}/absentee-ballots as Voter, POST
# /curing-cases/{caseId}/submit).
#
# PRD §2.1: "X-User-ID is the id of the acting Voter; ownership checks
# on any resource that references a Voter compare that resource's
# voter_id foreign key to X-User-ID."
# ---------------------------------------------------------------------------
def make_voter_headers(voter_id: str) -> Dict[str, str]:
    """Headers for a Voter acting on their own row. Pass the real
    Voter.id so ownership checks comparing X-User-ID to voter_id
    succeed.
    """
    return build_user_headers(voter_id, "Voter")


def make_registrar_clerk_headers(opaque_id: str) -> Dict[str, str]:
    """Headers for a RegistrarClerk under a chosen opaque id. Use when
    a test needs to control which opaque-id snapshot lands in
    Voter.registered_by_user_id (PRD §2.1 SOD precondition).
    """
    return build_user_headers(opaque_id, "RegistrarClerk")


def make_reviewer_clerk_headers(opaque_id: str) -> Dict[str, str]:
    """Headers for a ReviewerClerk under a chosen opaque id. Use when a
    test needs to control whether the reviewer id collides with the
    Voter.registered_by_user_id snapshot (PRD §2.1 SOD check).
    """
    return build_user_headers(opaque_id, "ReviewerClerk")


def make_precinct_officer_headers(opaque_id: str) -> Dict[str, str]:
    """Headers for a PrecinctOfficer under a chosen opaque id."""
    return build_user_headers(opaque_id, "PrecinctOfficer")


def make_election_board_headers(opaque_id: str) -> Dict[str, str]:
    """Headers for an ElectionBoard under a chosen opaque id."""
    return build_user_headers(opaque_id, "ElectionBoard")


__all__ = [
    "ELECTION_BOARD_ID",
    "REGISTRAR_CLERK_ID",
    "REGISTRAR_CLERK_ALT_ID",
    "REVIEWER_CLERK_ID",
    "REVIEWER_CLERK_ALT_ID",
    "PRECINCT_OFFICER_ID",
    "TEST_DRIVER_ID",
    "TEST_USERS",
    "make_voter_headers",
    "make_registrar_clerk_headers",
    "make_reviewer_clerk_headers",
    "make_precinct_officer_headers",
    "make_election_board_headers",
]
