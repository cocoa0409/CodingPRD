"""Pre-built role headers for every role in the PRD (§2.1).

The PRD requires two headers on every request other than the public verification
read: ``X-User-ID``, identifying the acting user, and ``X-User-Role``, declaring
the capacity in which that user is acting.

Eight of the ten roles are opaque operator identities — the shared constants
below are the canonical form for them, and the numbered variants exist because
segregation of duties compares recorded identities against the current
``X-User-ID`` (two distinct approvers, an auditor who is not a verifier, an
adopter who is not a panellist, a deciding officer who is not the opener).

Two roles are entity-backed. For those, ownership is decided by comparing an
entity field against ``X-User-ID``, so their headers MUST be built per instance
with :func:`make_candidate_headers` / :func:`make_certificant_headers`. Note the
PRD pins BOTH entity-backed roles to the acting ``Candidate``'s ``id``: a
``Certificant``-role caller's ``X-User-ID`` is compared against the addressed
certificant's ``candidate_id``, never against the certificant's own ``id``.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# --- Opaque operator identities (PRD §2.1) --------------------------------

PROGRAM_ADMIN_ID = "pa-1"

ITEM_AUTHOR_ID = "isp-author"
ITEM_REVIEWER_1_ID = "isp-rev-1"
ITEM_REVIEWER_2_ID = "isp-rev-2"
ITEM_REVIEWER_3_ID = "isp-rev-3"

PSYCHOMETRICIAN_ID = "psy-1"
PSYCHOMETRICIAN_2_ID = "psy-2"

PANELIST_IDS = ["pan-1", "pan-2", "pan-3", "pan-4", "pan-5"]
OUTSIDE_PANELIST_ID = "pan-9"

ELIGIBILITY_REVIEWER_1_ID = "elr-1"
ELIGIBILITY_REVIEWER_2_ID = "elr-2"
ELIGIBILITY_REVIEWER_3_ID = "elr-3"
ELIGIBILITY_REVIEWER_4_ID = "elr-4"

EXAM_OPERATIONS_ID = "ops-1"

ETHICS_OFFICER_1_ID = "eth-1"
ETHICS_OFFICER_2_ID = "eth-2"

IMPOSTOR_USER_ID = "impostor-user-1"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # ProgramAdmin — opaque
    "program_admin_headers": build_user_headers(PROGRAM_ADMIN_ID, "ProgramAdmin"),
    # ItemSpecialist — opaque; three distinct identities because two non-author
    # approvals are required and the author may be neither of them.
    "item_author_headers": build_user_headers(ITEM_AUTHOR_ID, "ItemSpecialist"),
    "item_reviewer_1_headers": build_user_headers(ITEM_REVIEWER_1_ID, "ItemSpecialist"),
    "item_reviewer_2_headers": build_user_headers(ITEM_REVIEWER_2_ID, "ItemSpecialist"),
    "item_reviewer_3_headers": build_user_headers(ITEM_REVIEWER_3_ID, "ItemSpecialist"),
    # Psychometrician — opaque; a second identity is needed because a panel
    # member may not adopt the cut score derived from their own panel.
    "psychometrician_headers": build_user_headers(PSYCHOMETRICIAN_ID, "Psychometrician"),
    "psychometrician_2_headers": build_user_headers(PSYCHOMETRICIAN_2_ID, "Psychometrician"),
    # Panelist — opaque
    "panelist_1_headers": build_user_headers(PANELIST_IDS[0], "Panelist"),
    "panelist_2_headers": build_user_headers(PANELIST_IDS[1], "Panelist"),
    "panelist_3_headers": build_user_headers(PANELIST_IDS[2], "Panelist"),
    "panelist_4_headers": build_user_headers(PANELIST_IDS[3], "Panelist"),
    "panelist_5_headers": build_user_headers(PANELIST_IDS[4], "Panelist"),
    # EligibilityReviewer — opaque; four identities because an auditor may not
    # be a verifier and a credit audit verifier may not be the reviewer.
    "eligibility_reviewer_1_headers": build_user_headers(
        ELIGIBILITY_REVIEWER_1_ID, "EligibilityReviewer"),
    "eligibility_reviewer_2_headers": build_user_headers(
        ELIGIBILITY_REVIEWER_2_ID, "EligibilityReviewer"),
    "eligibility_reviewer_3_headers": build_user_headers(
        ELIGIBILITY_REVIEWER_3_ID, "EligibilityReviewer"),
    "eligibility_reviewer_4_headers": build_user_headers(
        ELIGIBILITY_REVIEWER_4_ID, "EligibilityReviewer"),
    # ExamOperations — opaque
    "exam_operations_headers": build_user_headers(EXAM_OPERATIONS_ID, "ExamOperations"),
    # EthicsOfficer — opaque; two identities because the officer who opened a
    # case may never be the one who revokes on it.
    "ethics_officer_1_headers": build_user_headers(ETHICS_OFFICER_1_ID, "EthicsOfficer"),
    "ethics_officer_2_headers": build_user_headers(ETHICS_OFFICER_2_ID, "EthicsOfficer"),
    # Entity-backed roles: these shared constants are for non-ownership tests
    # only (role-gate refusals, malformed payloads). Ownership-gated calls MUST
    # use the per-instance builders below.
    "candidate_headers": build_user_headers(IMPOSTOR_USER_ID, "Candidate"),
    "certificant_headers": build_user_headers(IMPOSTOR_USER_ID, "Certificant"),
}


# --- Per-instance builders for the two entity-backed roles ----------------


def make_candidate_headers(candidate_id: str) -> Dict[str, str]:
    """Headers for the ``Candidate`` role.

    Pass the actual ``Candidate.id``: ownership checks on any resource that
    references a candidate compare the resource's ``candidate_id`` to
    ``X-User-ID``.
    """
    return build_user_headers(candidate_id, "Candidate")


def make_certificant_headers(candidate_id: str) -> Dict[str, str]:
    """Headers for the ``Certificant`` role.

    Pass the ``Candidate.id`` behind the credential — NOT the ``Certificant.id``.
    Ownership is established by comparing the addressed certificant's
    ``candidate_id`` to ``X-User-ID``.
    """
    return build_user_headers(candidate_id, "Certificant")


def make_item_specialist_headers(user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary ``ItemSpecialist`` identity."""
    return build_user_headers(user_id, "ItemSpecialist")


def make_panelist_headers(user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary ``Panelist`` identity."""
    return build_user_headers(user_id, "Panelist")


def make_psychometrician_headers(user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary ``Psychometrician`` identity."""
    return build_user_headers(user_id, "Psychometrician")


def make_eligibility_reviewer_headers(user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary ``EligibilityReviewer`` identity."""
    return build_user_headers(user_id, "EligibilityReviewer")


def make_ethics_officer_headers(user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary ``EthicsOfficer`` identity."""
    return build_user_headers(user_id, "EthicsOfficer")


NO_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}
"""Only the public registry verification read is reachable with no identity."""
