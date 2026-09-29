"""Pre-built role headers for every role in the PRD (§2.1).

Six roles carry an opaque `X-User-ID`; only `UnitManager` carries the `id` of
the acting `HospitalUnit`, so ownership-gated ticket transitions MUST use
`make_unit_manager_headers(unit["id"])`.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# Canonical opaque principal identifiers reused across fixtures.
DIRECTOR_USER_ID = "dir-1"
OWNER_USER_ID = "owner-1"
SECOND_OWNER_USER_ID = "owner-2"
VALIDATOR_USER_ID = "val-1"
SURVEYOR_USER_ID = "surv-1"
SAFETY_USER_ID = "safety-1"
EXTERNAL_SURVEYOR_USER_ID = "ext-1"

TEST_USERS: Dict[str, Dict[str, str]] = {
    "director_headers": build_user_headers(DIRECTOR_USER_ID, "AccreditationDirector"),
    "standard_owner_headers": build_user_headers(OWNER_USER_ID, "StandardOwner"),
    "second_standard_owner_headers": build_user_headers(SECOND_OWNER_USER_ID, "StandardOwner"),
    "evidence_validator_headers": build_user_headers(VALIDATOR_USER_ID, "EvidenceValidator"),
    "tracer_surveyor_headers": build_user_headers(SURVEYOR_USER_ID, "TracerSurveyor"),
    "safety_officer_headers": build_user_headers(SAFETY_USER_ID, "SafetyOfficer"),
    "external_surveyor_headers": build_user_headers(EXTERNAL_SURVEYOR_USER_ID, "ExternalSurveyor"),
    # UnitManager identity is a HospitalUnit id, so the shared constant is only
    # usable by tests that do not exercise unit scoping.
    "unit_manager_headers": build_user_headers("unit-manager-placeholder", "UnitManager"),
}


def make_director_headers(user_id: str = DIRECTOR_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, "AccreditationDirector")


def make_standard_owner_headers(user_id: str = OWNER_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, "StandardOwner")


def make_evidence_validator_headers(user_id: str = VALIDATOR_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, "EvidenceValidator")


def make_tracer_surveyor_headers(user_id: str = SURVEYOR_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, "TracerSurveyor")


def make_safety_officer_headers(user_id: str = SAFETY_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, "SafetyOfficer")


def make_external_surveyor_headers(user_id: str = EXTERNAL_SURVEYOR_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, "ExternalSurveyor")


def make_unit_manager_headers(unit_id: str) -> Dict[str, str]:
    """For UnitManager, whose `X-User-ID` is the id of the acting HospitalUnit.
    Pass the real unit id whenever the call is scope-gated."""
    return build_user_headers(unit_id, "UnitManager")


def make_role_headers(user_id: str, role: str) -> Dict[str, str]:
    """Arbitrary role/principal pair — used for authorization probes."""
    return build_user_headers(user_id, role)


def headers_without_user_id(role: str) -> Dict[str, str]:
    """Headers carrying only `X-User-Role`, with `X-User-ID` absent."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str) -> Dict[str, str]:
    """Headers carrying only `X-User-ID`, with `X-User-Role` absent."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}
