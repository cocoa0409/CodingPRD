"""Pre-built role headers for every role the PRD declares (PRD §2.1).

Two roles bind ``X-User-ID`` to a stored row: ``Operator`` (the acting
company's ``Operator.id``) and ``Inspector`` (the acting
``InspectorProfile.id``). Ownership-gated calls for those roles MUST use the
per-instance builders below with the real entity id.

``BondSpecialist`` is an opaque identifier that is nonetheless recorded into
``accepted_by_user_id`` and ``decided_by_user_id``, and the segregation-of-duties
rule compares those two values. Two distinct specialist identities are therefore
pre-declared: ``bs-001`` posts financial security, ``bs-002`` decides releases.
"""
from prd_bench_local_runner.testing import build_user_headers

BOND_SPECIALIST_ACCEPTER_ID = "bs-001"
BOND_SPECIALIST_DECIDER_ID = "bs-002"

TEST_USERS = {
    # Operator is entity_backed: this shared constant is only safe for tests
    # that never reach an ownership check (schema errors, 404s, role denials).
    "operator_headers": build_user_headers("test-operator-1", "Operator"),
    # Inspector is entity_backed: same caveat as Operator.
    "inspector_headers": build_user_headers("test-inspector-1", "Inspector"),
    # Opaque roles: the shared constant is the canonical form.
    "permit_reviewer_headers": build_user_headers("test-reviewer-1", "PermitReviewer"),
    "program_director_headers": build_user_headers("test-director-1", "ProgramDirector"),
    "public_participant_headers": build_user_headers("test-public-1", "PublicParticipant"),
    # Opaque but recorded: keep the two identities distinct.
    "bond_specialist_headers": build_user_headers(BOND_SPECIALIST_ACCEPTER_ID, "BondSpecialist"),
    "bond_specialist_decider_headers": build_user_headers(
        BOND_SPECIALIST_DECIDER_ID, "BondSpecialist"
    ),
}


def make_operator_headers(user_id: str) -> dict:
    """For the Operator role. Pass the acting company's Operator.id."""
    return build_user_headers(user_id, "Operator")


def make_inspector_headers(user_id: str) -> dict:
    """For the Inspector role. Pass the acting InspectorProfile.id."""
    return build_user_headers(user_id, "Inspector")


def make_bond_specialist_headers(user_id: str) -> dict:
    """For the BondSpecialist role. The id is opaque but is recorded."""
    return build_user_headers(user_id, "BondSpecialist")


def make_permit_reviewer_headers(user_id: str = "test-reviewer-1") -> dict:
    return build_user_headers(user_id, "PermitReviewer")


def make_program_director_headers(user_id: str = "test-director-1") -> dict:
    return build_user_headers(user_id, "ProgramDirector")


def make_public_participant_headers(user_id: str = "test-public-1") -> dict:
    return build_user_headers(user_id, "PublicParticipant")


# Convenience aliases used throughout the fixtures.
PROGRAM_DIRECTOR = TEST_USERS["program_director_headers"]
PERMIT_REVIEWER = TEST_USERS["permit_reviewer_headers"]
BOND_SPECIALIST_ACCEPTER = TEST_USERS["bond_specialist_headers"]
BOND_SPECIALIST_DECIDER = TEST_USERS["bond_specialist_decider_headers"]
PUBLIC_PARTICIPANT = TEST_USERS["public_participant_headers"]
