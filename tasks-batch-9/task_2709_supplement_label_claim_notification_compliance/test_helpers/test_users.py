"""Test principals and their request headers.

PRD §2.1: for the five non-supplier roles ``X-User-ID`` is an opaque operator
identifier never compared to any entity id, so fixed literals are used. For a
``SupplierRepresentative``, ``X-User-ID`` **is** the ``id`` of the acting
``Supplier``, so its headers must be built per-supplier at call time.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_CLAIM_APPROVAL_OFFICER,
    ROLE_COMPLIANCE_AUDITOR,
    ROLE_QUALITY_ASSURANCE_MANAGER,
    ROLE_REGULATORY_AFFAIRS_SPECIALIST,
    ROLE_SUBSTANTIATION_REVIEWER,
    ROLE_SUPPLIER_REPRESENTATIVE,
)

# Opaque operator identifiers. Distinct values per principal so that the
# segregation-of-duties comparisons of PRD §2.10 can be exercised both ways.
USER_RAS_01 = "u_ras_01"
USER_RAS_02 = "u_ras_02"
USER_SR_01 = "u_sr_01"
USER_SR_02 = "u_sr_02"
USER_CAO_01 = "u_cao_01"
USER_CAO_02 = "u_cao_02"
USER_QAM_01 = "u_qam_01"
USER_QAM_02 = "u_qam_02"
USER_AUD_01 = "u_aud_01"

TEST_USERS: Dict[str, Dict[str, str]] = {
    "regulatory_affairs_specialist": {
        "user_id": USER_RAS_01,
        "role": ROLE_REGULATORY_AFFAIRS_SPECIALIST,
    },
    "regulatory_affairs_specialist_alt": {
        "user_id": USER_RAS_02,
        "role": ROLE_REGULATORY_AFFAIRS_SPECIALIST,
    },
    "substantiation_reviewer": {
        "user_id": USER_SR_01,
        "role": ROLE_SUBSTANTIATION_REVIEWER,
    },
    "substantiation_reviewer_alt": {
        "user_id": USER_SR_02,
        "role": ROLE_SUBSTANTIATION_REVIEWER,
    },
    "claim_approval_officer": {
        "user_id": USER_CAO_01,
        "role": ROLE_CLAIM_APPROVAL_OFFICER,
    },
    "claim_approval_officer_alt": {
        "user_id": USER_CAO_02,
        "role": ROLE_CLAIM_APPROVAL_OFFICER,
    },
    "quality_assurance_manager": {
        "user_id": USER_QAM_01,
        "role": ROLE_QUALITY_ASSURANCE_MANAGER,
    },
    "quality_assurance_manager_alt": {
        "user_id": USER_QAM_02,
        "role": ROLE_QUALITY_ASSURANCE_MANAGER,
    },
    "compliance_auditor": {
        "user_id": USER_AUD_01,
        "role": ROLE_COMPLIANCE_AUDITOR,
    },
}


def _headers(key: str) -> Dict[str, str]:
    entry = TEST_USERS[key]
    return build_user_headers(entry["user_id"], entry["role"])


RAS_HEADERS = _headers("regulatory_affairs_specialist")
RAS_ALT_HEADERS = _headers("regulatory_affairs_specialist_alt")
REVIEWER_HEADERS = _headers("substantiation_reviewer")
REVIEWER_ALT_HEADERS = _headers("substantiation_reviewer_alt")
CAO_HEADERS = _headers("claim_approval_officer")
CAO_ALT_HEADERS = _headers("claim_approval_officer_alt")
QAM_HEADERS = _headers("quality_assurance_manager")
QAM_ALT_HEADERS = _headers("quality_assurance_manager_alt")
AUDITOR_HEADERS = _headers("compliance_auditor")


def make_supplier_representative_headers(user_id: str) -> Dict[str, str]:
    """Headers for a ``SupplierRepresentative`` acting as the supplier ``user_id``.

    PRD §2.1: ``X-User-ID`` is the ``id`` of the acting ``Supplier``, so callers
    must thread the real supplier id through here.
    """
    return build_user_headers(user_id, ROLE_SUPPLIER_REPRESENTATIVE)


def headers_for_role(role: str, user_id: str) -> Dict[str, str]:
    """Arbitrary role/identity pairing, for authorization probes."""
    return build_user_headers(user_id, role)
