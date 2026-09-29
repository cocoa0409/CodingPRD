"""
Operator identities and request headers.

PRD §2.1 states that no role in this system is backed by a persisted entity:
`X-User-ID` is an opaque operator string everywhere. Two rules nevertheless
compare one recorded operator string against another — the reporting
segregation of duties and the presenter's uncounted ballot — so the suite keeps
a small stable roster of distinguishable operator ids per role and a helper for
minting extra ones on demand.
"""

from typing import Dict, Optional

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_EPILEPTOLOGIST,
    ROLE_NURSE,
    ROLE_PAYER_REVIEWER,
    ROLE_TECHNOLOGIST,
    ROLE_UNIT_COORDINATOR,
)

# Default operator id per role.
COORDINATOR_ID = "coord-1"
TECHNOLOGIST_ID = "tech-1"
TECHNOLOGIST_ID_2 = "tech-2"
NURSE_ID = "nurse-1"
NURSE_ID_2 = "nurse-2"
EPILEPTOLOGIST_ID = "epi-1"
EPILEPTOLOGIST_ID_2 = "epi-2"
EPILEPTOLOGIST_ID_3 = "epi-3"
EPILEPTOLOGIST_ID_4 = "epi-4"
PAYER_ID = "payer-1"

COORDINATOR = build_user_headers(COORDINATOR_ID, ROLE_UNIT_COORDINATOR)
TECHNOLOGIST = build_user_headers(TECHNOLOGIST_ID, ROLE_TECHNOLOGIST)
NURSE = build_user_headers(NURSE_ID, ROLE_NURSE)
EPILEPTOLOGIST = build_user_headers(EPILEPTOLOGIST_ID, ROLE_EPILEPTOLOGIST)
PAYER_REVIEWER = build_user_headers(PAYER_ID, ROLE_PAYER_REVIEWER)

ROLE_HEADERS: Dict[str, Dict[str, str]] = {
    ROLE_UNIT_COORDINATOR: COORDINATOR,
    ROLE_TECHNOLOGIST: TECHNOLOGIST,
    ROLE_NURSE: NURSE,
    ROLE_EPILEPTOLOGIST: EPILEPTOLOGIST,
    ROLE_PAYER_REVIEWER: PAYER_REVIEWER,
}


def as_coordinator(user_id: str = COORDINATOR_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_UNIT_COORDINATOR)


def as_technologist(user_id: str = TECHNOLOGIST_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_TECHNOLOGIST)


def as_nurse(user_id: str = NURSE_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_NURSE)


def as_epileptologist(user_id: str = EPILEPTOLOGIST_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_EPILEPTOLOGIST)


def as_payer_reviewer(user_id: str = PAYER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_PAYER_REVIEWER)


def headers_for(role: str, user_id: Optional[str] = None) -> Dict[str, str]:
    """Headers for an arbitrary role, optionally overriding the operator id."""
    if user_id is None:
        return ROLE_HEADERS[role]
    return build_user_headers(user_id, role)


# Headers that deliberately fail authentication (PRD §2.1).
NO_AUTH_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}
MISSING_ROLE_HEADERS: Dict[str, str] = {
    "X-User-ID": COORDINATOR_ID,
    "Content-Type": "application/json",
}
MISSING_USER_HEADERS: Dict[str, str] = {
    "X-User-Role": ROLE_UNIT_COORDINATOR,
    "Content-Type": "application/json",
}
UNDECLARED_ROLE_HEADERS: Dict[str, str] = build_user_headers(
    COORDINATOR_ID, "Neurosurgeon"
)
