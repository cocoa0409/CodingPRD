"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

    "When X-User-Role is Claimant, the X-User-ID is the id of the acting
    Claimant; ownership checks on any resource that references a Claimant
    compare the resource's claimant_id to X-User-ID, and a mismatched
    claimant in the URL path also yields ERR_FORBIDDEN. When X-User-Role
    is any of DDS_Examiner, ALJ, AppealsCouncil, CDR_Reviewer, or
    PlatformAdmin, the X-User-ID is an opaque operator identifier not
    tied to any persisted entity."

The shared *_headers constants below are appropriate ONLY for:

    * Claimant-role tests whose success does NOT depend on the caller
      owning the subject resource (auth probes, 404-on-missing-claimant
      probes, RBAC probes).
    * The five opaque roles (DDS_Examiner, ALJ, AppealsCouncil,
      CDR_Reviewer, PlatformAdmin), where X-User-ID is never compared
      against any entity id.

For any Claimant-scoped operation whose acceptance depends on the caller
being the resource owner (every submit/appeal/medical-evidence/quarter-
credit/application call), tests and fixtures MUST mint headers via
make_claimant_headers(claimant_id) with the real Claimant.id returned
by POST /claimants.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Shared constants — safe for opaque roles and non-ownership Claimant tests.
# ---------------------------------------------------------------------------
TEST_USERS: Dict[str, Dict[str, str]] = {
    # entity_backed:Claimant — shared constant is reserved for non-ownership
    # tests (auth probes, 404 probes, RBAC probes that do not require the
    # caller's id to match a resource's claimant_id).
    "claimant_headers": build_user_headers("claimant-shared-0001", "Claimant"),
    # Opaque operator roles — X-User-ID is not compared to any entity.
    "dds_examiner_headers": build_user_headers(
        "dds-examiner-0001", "DDS_Examiner",
    ),
    "dds_examiner_2_headers": build_user_headers(
        "dds-examiner-0002", "DDS_Examiner",
    ),
    "alj_headers": build_user_headers("alj-0001", "ALJ"),
    "alj_2_headers": build_user_headers("alj-0002", "ALJ"),
    "appeals_council_headers": build_user_headers(
        "appeals-council-0001", "AppealsCouncil",
    ),
    "cdr_reviewer_headers": build_user_headers(
        "cdr-reviewer-0001", "CDR_Reviewer",
    ),
    "cdr_reviewer_2_headers": build_user_headers(
        "cdr-reviewer-0002", "CDR_Reviewer",
    ),
    "platform_admin_headers": build_user_headers(
        "platform-admin-0001", "PlatformAdmin",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — MANDATORY for the entity_backed Claimant role
# whenever the downstream call is ownership-gated.
#
# PRD §2.1: "When X-User-Role is Claimant, the X-User-ID is the id of the
# acting Claimant; ownership checks on any resource that references a
# Claimant compare the resource's claimant_id to X-User-ID".
# ---------------------------------------------------------------------------
def make_claimant_headers(claimant_id: str) -> Dict[str, str]:
    """Headers for a specific Claimant. Use this whenever the call is
    ownership-gated — i.e. any /claimants/{claimantId}/** call where the
    server must verify the caller is the owner.
    """
    return build_user_headers(claimant_id, "Claimant")


def make_dds_examiner_headers(
    operator_id: str = "dds-examiner-0001",
) -> Dict[str, str]:
    """Headers for a DDS_Examiner operator. PRD §2.1 declares this role
    opaque, so the operator_id is recorded for audit (and bound onto
    Application.last_initial_examiner_id for SoD) but not compared to any
    entity's id.
    """
    return build_user_headers(operator_id, "DDS_Examiner")


def make_alj_headers(operator_id: str = "alj-0001") -> Dict[str, str]:
    """Headers for an ALJ operator. Opaque role per PRD §2.1. The
    operator_id supplied here is also the value to pass as alj_id in
    POST /hearing-slots since both reference the same logical user.
    """
    return build_user_headers(operator_id, "ALJ")


def make_appeals_council_headers(
    operator_id: str = "appeals-council-0001",
) -> Dict[str, str]:
    """Headers for an AppealsCouncil operator. Opaque role per PRD §2.1."""
    return build_user_headers(operator_id, "AppealsCouncil")


def make_cdr_reviewer_headers(
    operator_id: str = "cdr-reviewer-0001",
) -> Dict[str, str]:
    """Headers for a CDR_Reviewer operator. Opaque role per PRD §2.1."""
    return build_user_headers(operator_id, "CDR_Reviewer")


def make_platform_admin_headers(
    operator_id: str = "platform-admin-0001",
) -> Dict[str, str]:
    """Headers for a PlatformAdmin. Opaque role per PRD §2.1; holds the
    test-driving clock-advance capability."""
    return build_user_headers(operator_id, "PlatformAdmin")


__all__ = [
    "TEST_USERS",
    "make_claimant_headers",
    "make_dds_examiner_headers",
    "make_alj_headers",
    "make_appeals_council_headers",
    "make_cdr_reviewer_headers",
    "make_platform_admin_headers",
]
