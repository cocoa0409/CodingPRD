"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

    "Five of the six roles are entity-backed. When X-User-Role is
    Applicant, X-User-ID is the id of the acting Applicant; ownership
    checks compare resource foreign-key fields ... to X-User-ID. When
    X-User-Role is Landlord, X-User-ID is the id of the acting Landlord
    ... When X-User-Role is Inspector, X-User-ID is the id of the acting
    Inspector and is used to scope inspection-completion authority to
    the inspector's own PHA. When X-User-Role is CaseWorker, X-User-ID
    is the id of the acting CaseWorker. When X-User-Role is
    PortabilityCoordinator, X-User-ID is the id of the acting
    PortabilityCoordinator."

    "When X-User-Role is PHAAdmin, X-User-ID is an opaque operator
    identifier not tied to any persisted entity."

The shared *_headers constants below are appropriate ONLY for tests
whose success does not depend on the caller owning the subject
resource — for example, ERR_AUTH_REQUIRED probes that send empty
values, ERR_FORBIDDEN_ROLE probes that simply test "role X cannot call
endpoint Y", or any call made by PHAAdmin (which is opaque per PRD).

The mandatory builders are `make_<role>_headers(user_id)`. Fixtures
that create an entity (Applicant, Landlord, Inspector, CaseWorker,
PortabilityCoordinator) and then act as that entity MUST mint headers
with that entity's id — otherwise the server's ownership check would
reject the call.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Bootstrap identifiers — used by PHAAdmin (opaque) and for tests that
# don't exercise ownership at all.
# ---------------------------------------------------------------------------
PHA_ADMIN_BOOTSTRAP_ID: str = "pha-admin-bootstrap-0001"
CASE_WORKER_BOOTSTRAP_ID: str = "caseworker-bootstrap-0001"
LANDLORD_BOOTSTRAP_ID: str = "landlord-bootstrap-0001"
INSPECTOR_BOOTSTRAP_ID: str = "inspector-bootstrap-0001"
APPLICANT_BOOTSTRAP_ID: str = "applicant-bootstrap-0001"
PORTABILITY_COORDINATOR_BOOTSTRAP_ID: str = "portcoord-bootstrap-0001"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # PHAAdmin is opaque per PRD §2.1 — shared constant is canonical.
    "pha_admin_headers": build_user_headers(
        PHA_ADMIN_BOOTSTRAP_ID, "PHAAdmin",
    ),
    # The five entity-backed roles: shared constants are fallbacks for
    # non-ownership tests only (auth probes, 404 probes, role-forbidden
    # probes). Ownership-gated calls MUST use the make_*_headers()
    # builders with the actual entity id.
    "applicant_headers": build_user_headers(
        APPLICANT_BOOTSTRAP_ID, "Applicant",
    ),
    "landlord_headers": build_user_headers(
        LANDLORD_BOOTSTRAP_ID, "Landlord",
    ),
    "inspector_headers": build_user_headers(
        INSPECTOR_BOOTSTRAP_ID, "Inspector",
    ),
    "case_worker_headers": build_user_headers(
        CASE_WORKER_BOOTSTRAP_ID, "CaseWorker",
    ),
    "portability_coordinator_headers": build_user_headers(
        PORTABILITY_COORDINATOR_BOOTSTRAP_ID, "PortabilityCoordinator",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — MANDATORY for entity_backed roles whenever the
# downstream call is ownership-gated.
# ---------------------------------------------------------------------------
def make_applicant_headers(applicant_id: str) -> Dict[str, str]:
    """Headers for an Applicant identified by a real Applicant.id.

    PRD §2.1: "When X-User-Role is Applicant, X-User-ID is the id of the
    acting Applicant; ownership checks compare resource foreign-key
    fields (the applicant_id on a Voucher, or the Voucher.applicant_id
    reached transitively from a Tenancy.voucher_id) to X-User-ID."
    """
    return build_user_headers(applicant_id, "Applicant")


def make_landlord_headers(landlord_id: str) -> Dict[str, str]:
    """Headers for a Landlord identified by a real Landlord.id.

    PRD §2.1: "the Unit.landlord_id field on each unit is compared to
    X-User-ID for ownership."
    """
    return build_user_headers(landlord_id, "Landlord")


def make_inspector_headers(inspector_id: str) -> Dict[str, str]:
    """Headers for an Inspector identified by a real Inspector.id.

    PRD §2.1: "X-User-ID is the id of the acting Inspector and is used
    to scope inspection-completion authority to the inspector's own PHA."
    """
    return build_user_headers(inspector_id, "Inspector")


def make_case_worker_headers(case_worker_id: str) -> Dict[str, str]:
    """Headers for a CaseWorker identified by a real CaseWorker.id.

    PRD §2.1: "When X-User-Role is CaseWorker, X-User-ID is the id of
    the acting CaseWorker."
    """
    return build_user_headers(case_worker_id, "CaseWorker")


def make_portability_coordinator_headers(
    pc_id: str,
) -> Dict[str, str]:
    """Headers for a PortabilityCoordinator identified by a real id.

    PRD §2.1: "X-User-ID is the id of the acting PortabilityCoordinator."
    """
    return build_user_headers(pc_id, "PortabilityCoordinator")


def make_pha_admin_headers(operator_id: str = PHA_ADMIN_BOOTSTRAP_ID) -> Dict[str, str]:
    """Headers for PHAAdmin. The id is opaque per PRD §2.1."""
    return build_user_headers(operator_id, "PHAAdmin")


__all__ = [
    "PHA_ADMIN_BOOTSTRAP_ID",
    "CASE_WORKER_BOOTSTRAP_ID",
    "LANDLORD_BOOTSTRAP_ID",
    "INSPECTOR_BOOTSTRAP_ID",
    "APPLICANT_BOOTSTRAP_ID",
    "PORTABILITY_COORDINATOR_BOOTSTRAP_ID",
    "TEST_USERS",
    "make_applicant_headers",
    "make_landlord_headers",
    "make_inspector_headers",
    "make_case_worker_headers",
    "make_portability_coordinator_headers",
    "make_pha_admin_headers",
]
