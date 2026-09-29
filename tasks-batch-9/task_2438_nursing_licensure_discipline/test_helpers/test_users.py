"""Pre-built role headers for every role in the PRD (§2.1).

Five of the six roles carry an opaque identity: the value of `X-User-ID` is an
operator identifier that is never compared to any persisted entity, so a shared
constant is the canonical form for them. The `Applicant` role is entity-backed —
`X-User-ID` is the `id` of the acting nurse — so ownership-gated calls MUST use
`make_applicant_headers(nurse_id)` with the real nurse identifier.
"""
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque identities — shared constants are canonical.
    "system_admin_headers": build_user_headers("adm-1", "SystemAdmin"),
    "licensure_analyst_headers": build_user_headers("ana-1", "LicensureAnalyst"),
    "investigator_headers": build_user_headers("inv-1", "Investigator"),
    "board_member_headers": build_user_headers("bm-presiding", "BoardMember"),
    "monitoring_coordinator_headers": build_user_headers("mc-1", "MonitoringCoordinator"),
    # Entity-backed identity — fallback for tests that never exercise ownership.
    "applicant_headers": build_user_headers("nurse-unowned", "Applicant"),
}


def make_system_admin_headers(user_id: str = "adm-1") -> Dict[str, str]:
    """Headers for a SystemAdmin (opaque operator identity)."""
    return build_user_headers(user_id, "SystemAdmin")


def make_licensure_analyst_headers(user_id: str = "ana-1") -> Dict[str, str]:
    """Headers for a LicensureAnalyst (opaque operator identity)."""
    return build_user_headers(user_id, "LicensureAnalyst")


def make_investigator_headers(user_id: str = "inv-1") -> Dict[str, str]:
    """Headers for an Investigator (opaque operator identity)."""
    return build_user_headers(user_id, "Investigator")


def make_board_member_headers(user_id: str = "bm-presiding") -> Dict[str, str]:
    """Headers for a BoardMember (opaque operator identity)."""
    return build_user_headers(user_id, "BoardMember")


def make_monitoring_coordinator_headers(user_id: str = "mc-1") -> Dict[str, str]:
    """Headers for a MonitoringCoordinator (opaque operator identity)."""
    return build_user_headers(user_id, "MonitoringCoordinator")


def make_applicant_headers(nurse_id: str) -> Dict[str, str]:
    """Headers for the nurse acting on their own record.

    Pass the real `Nurse.id`: every operation the Applicant role may perform is
    ownership-enforced against it.
    """
    return build_user_headers(nurse_id, "Applicant")


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Arbitrary role/identity pair, including deliberately invalid roles."""
    return build_user_headers(user_id, role)


ALL_ROLE_NAMES = [
    "SystemAdmin",
    "LicensureAnalyst",
    "Investigator",
    "BoardMember",
    "MonitoringCoordinator",
    "Applicant",
]
