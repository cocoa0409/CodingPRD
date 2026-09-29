"""Role headers.

PRD section 2.1 splits the six roles in two. ``PropertyRoomManager`` and ``CourtClerk``
are opaque: their ``X-User-ID`` "is an opaque operator identifier that is not tied to
any persisted entity", so a fixed constant is enough. The other four are entity-backed:
``X-User-ID`` must be the ``id`` of the acting ``Custodian`` row whose ``role_type``
corresponds to the acting role, so those headers must be built per custodian.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# Opaque roles — a stable operator identifier is sufficient.
TEST_USERS: Dict[str, Dict[str, str]] = {
    "manager_headers": build_user_headers(
        "test-property-room-manager-1", "PropertyRoomManager"
    ),
    "manager_alt_headers": build_user_headers(
        "test-property-room-manager-2", "PropertyRoomManager"
    ),
    "court_clerk_headers": build_user_headers("test-court-clerk-1", "CourtClerk"),
}


# Entity-backed roles — the acting Custodian row's id must be threaded through.

def make_evidence_technician_headers(custodian_id: str) -> Dict[str, str]:
    """Headers for a Custodian whose ``role_type`` is ``EVIDENCE_TECH``."""
    return build_user_headers(custodian_id, "EvidenceTechnician")


def make_investigator_headers(custodian_id: str) -> Dict[str, str]:
    """Headers for a Custodian whose ``role_type`` is ``INVESTIGATOR``."""
    return build_user_headers(custodian_id, "Investigator")


def make_lab_analyst_headers(custodian_id: str) -> Dict[str, str]:
    """Headers for a Custodian whose ``role_type`` is ``LAB_ANALYST``."""
    return build_user_headers(custodian_id, "LabAnalyst")


def make_internal_auditor_headers(custodian_id: str) -> Dict[str, str]:
    """Headers for a Custodian whose ``role_type`` is ``AUDITOR``."""
    return build_user_headers(custodian_id, "InternalAuditor")


def make_headers(role: str, user_id: str) -> Dict[str, str]:
    """Arbitrary role/id pair, for role-authorization and header-validation tests."""
    return build_user_headers(user_id, role)


MANAGER = TEST_USERS["manager_headers"]
MANAGER_ALT = TEST_USERS["manager_alt_headers"]
COURT_CLERK = TEST_USERS["court_clerk_headers"]
