"""Header builders for each of the PRD's seven roles.

PRD 2.1: "When `X-User-Role` is `PlantOperator`, `X-User-ID` is the `id` of the
acting `Plant`"; for the other six roles "`X-User-ID` is an opaque operator
identifier not tied to any persisted entity."  So PlantOperator headers must be
built from a live plant id, while the other six use stable opaque ids.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# --- Opaque operator identifiers ---------------------------------------------

CORPORATE_OPS_USER_ID = "ops-1"
CORPORATE_OPS_USER_ID_ALT = "ops-2"

QUALITY_ENGINEER_USER_ID = "qe-1"
QUALITY_ENGINEER_USER_ID_ALT = "qe-2"

CERTIFICATION_OFFICER_USER_ID = "co-1"
CERTIFICATION_OFFICER_USER_ID_ALT = "co-2"

ENVIRONMENTAL_COMPLIANCE_USER_ID = "ec-1"
ENVIRONMENTAL_COMPLIANCE_USER_ID_ALT = "ec-2"

CHANNEL_MANAGER_USER_ID = "cm-1"
CHANNEL_MANAGER_USER_ID_ALT = "cm-2"

CHANNEL_BUYER_USER_ID = "buyer-1"
CHANNEL_BUYER_USER_ID_ALT = "buyer-2"

UNKNOWN_PLANT_USER_ID = "00000000-0000-0000-0000-0000000000ff"


# --- Header builders ---------------------------------------------------------


def corporate_ops_headers(user_id: str = CORPORATE_OPS_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, "CorporateOps")


def plant_operator_headers(plant_id: str) -> Dict[str, str]:
    """PlantOperator identity IS the plant id it may act on (PRD 2.1)."""
    return build_user_headers(plant_id, "PlantOperator")


def quality_engineer_headers(
    user_id: str = QUALITY_ENGINEER_USER_ID,
) -> Dict[str, str]:
    return build_user_headers(user_id, "QualityEngineer")


def certification_officer_headers(
    user_id: str = CERTIFICATION_OFFICER_USER_ID,
) -> Dict[str, str]:
    return build_user_headers(user_id, "CertificationOfficer")


def environmental_compliance_headers(
    user_id: str = ENVIRONMENTAL_COMPLIANCE_USER_ID,
) -> Dict[str, str]:
    return build_user_headers(user_id, "EnvironmentalCompliance")


def channel_manager_headers(
    user_id: str = CHANNEL_MANAGER_USER_ID,
) -> Dict[str, str]:
    return build_user_headers(user_id, "ChannelManager")


def channel_buyer_headers(user_id: str = CHANNEL_BUYER_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, "ChannelBuyer")


def headers_for_role(role: str, user_id: str) -> Dict[str, str]:
    """Generic builder for role-matrix style checks."""
    return build_user_headers(user_id, role)


def headers_missing_user_id(role: str) -> Dict[str, str]:
    """Headers with an empty X-User-ID - PRD 2.1 ERR_UNAUTHENTICATED case."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def headers_missing_role(user_id: str) -> Dict[str, str]:
    """Headers with an empty X-User-Role - PRD 2.1 ERR_UNAUTHENTICATED case."""
    return {
        "X-User-ID": user_id,
        "X-User-Role": "",
        "Content-Type": "application/json",
    }


def headers_without_identity() -> Dict[str, str]:
    """No identity headers at all."""
    return {"Content-Type": "application/json"}


def headers_with_unknown_role(user_id: str = "someone") -> Dict[str, str]:
    """A role name outside the seven - PRD 2.1 ERR_UNAUTHORIZED case."""
    return build_user_headers(user_id, "NotARole")


ALL_ROLES = (
    "CorporateOps",
    "PlantOperator",
    "QualityEngineer",
    "CertificationOfficer",
    "EnvironmentalCompliance",
    "ChannelManager",
    "ChannelBuyer",
)

DEFAULT_USER_ID_BY_ROLE = {
    "CorporateOps": CORPORATE_OPS_USER_ID,
    "QualityEngineer": QUALITY_ENGINEER_USER_ID,
    "CertificationOfficer": CERTIFICATION_OFFICER_USER_ID,
    "EnvironmentalCompliance": ENVIRONMENTAL_COMPLIANCE_USER_ID,
    "ChannelManager": CHANNEL_MANAGER_USER_ID,
    "ChannelBuyer": CHANNEL_BUYER_USER_ID,
}
