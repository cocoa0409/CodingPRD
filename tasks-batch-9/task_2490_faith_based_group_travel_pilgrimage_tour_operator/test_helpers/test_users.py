"""Caller identities for every role of PRD §4.

PRD §2.1: "Every request -- reads, writes and the clock-control capability
alike -- must carry two headers: `X-User-ID` ... and `X-User-Role`".

The `GroupLeader` role is entity-backed: its `X-User-ID` must be the `id` of
the acting `GroupLeaderAgreement` row, so leader headers are always built from
a live agreement id via `make_group_leader_headers`.

Several operations enforce segregation of duties by plain string comparison of
`X-User-ID` (§2.1, §3.8, §3.9), so distinct same-role identities are provided
for the proposer/ratifier and reviewer/decider pairs.
"""

from __future__ import annotations

from prd_bench_local_runner.testing import build_user_headers

# --- Canonical operator identities, one per role of §4 ---------------------

TEST_USERS: dict[str, dict[str, str]] = {
    "program_manager": build_user_headers("u-program-manager-1", "ProgramManager"),
    "risk_officer": build_user_headers("u-risk-officer-1", "RiskOfficer"),
    "air_desk_agent": build_user_headers("u-air-desk-1", "AirDeskAgent"),
    "land_contractor": build_user_headers("u-land-contractor-1", "LandContractor"),
    "finance_controller": build_user_headers("u-finance-controller-1", "FinanceController"),
    "protection_administrator": build_user_headers(
        "u-protection-admin-1", "ProtectionAdministrator"
    ),
}

# --- Second identities for the segregation-of-duties pairs -----------------

TEST_USERS.update(
    {
        # §3.9: a modification's ratifier must not be its proposer.
        "program_manager_second": build_user_headers("u-program-manager-2", "ProgramManager"),
        "risk_officer_second": build_user_headers("u-risk-officer-2", "RiskOfficer"),
        # §3.8: the waiver decider must not be the medical reviewer.
        "protection_reviewer": build_user_headers("u-prot-reviewer", "ProtectionAdministrator"),
        "protection_approver": build_user_headers("u-prot-approver", "ProtectionAdministrator"),
        "protection_nurse": build_user_headers("u-protection-nurse", "ProtectionAdministrator"),
        "protection_underwriter": build_user_headers(
            "u-protection-underwriter", "ProtectionAdministrator"
        ),
    }
)


def make_program_manager_headers(user_id: str = "u-program-manager-1") -> dict[str, str]:
    return build_user_headers(user_id, "ProgramManager")


def make_risk_officer_headers(user_id: str = "u-risk-officer-1") -> dict[str, str]:
    return build_user_headers(user_id, "RiskOfficer")


def make_air_desk_agent_headers(user_id: str = "u-air-desk-1") -> dict[str, str]:
    return build_user_headers(user_id, "AirDeskAgent")


def make_land_contractor_headers(user_id: str = "u-land-contractor-1") -> dict[str, str]:
    return build_user_headers(user_id, "LandContractor")


def make_finance_controller_headers(user_id: str = "u-finance-controller-1") -> dict[str, str]:
    return build_user_headers(user_id, "FinanceController")


def make_protection_administrator_headers(
    user_id: str = "u-protection-admin-1",
) -> dict[str, str]:
    return build_user_headers(user_id, "ProtectionAdministrator")


def make_group_leader_headers(agreement_id: str) -> dict[str, str]:
    """§2.1: a `GroupLeader`'s `X-User-ID` is the `id` of the acting agreement."""
    return build_user_headers(agreement_id, "GroupLeader")


def make_headers(user_id: str, role: str) -> dict[str, str]:
    """Arbitrary identity/role pair, for authorisation probes."""
    return build_user_headers(user_id, role)


ALL_ROLE_NAMES: tuple[str, ...] = (
    "ProgramManager",
    "RiskOfficer",
    "AirDeskAgent",
    "LandContractor",
    "FinanceController",
    "ProtectionAdministrator",
    "GroupLeader",
)

OPERATOR_ROLE_NAMES: tuple[str, ...] = ALL_ROLE_NAMES[:-1]

__all__ = [
    "TEST_USERS",
    "ALL_ROLE_NAMES",
    "OPERATOR_ROLE_NAMES",
    "make_program_manager_headers",
    "make_risk_officer_headers",
    "make_air_desk_agent_headers",
    "make_land_contractor_headers",
    "make_finance_controller_headers",
    "make_protection_administrator_headers",
    "make_group_leader_headers",
    "make_headers",
]
