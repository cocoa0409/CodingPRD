"""Pre-built role headers for the six roles of the PRD (§2.1, §2.4).

Five roles carry an opaque operator identifier in `X-User-ID`, so the shared
constants below are stable and reusable.  `Homeowner` is different: its
`X-User-ID` is the acting `Homeowner.id`, so every ownership-gated homeowner call
must build its headers from the real account row with
`make_homeowner_headers()`.  The shared `homeowner_headers` entry below carries a
placeholder identifier and is useful only where ownership is not the point of the
call.

Distinct opaque identifiers matter for the segregation-of-duties rules (PRD
§2.10), which compare the acting `X-User-ID` against a previously recorded one:
`INSTALLER_TECH_USER_ID` certifies the install, `SECOND_INSTALLER_TECH_USER_ID`
is a different technician, `ADJUSTER_USER_ID` and `SECOND_ADJUSTER_USER_ID` are
two different adjusters, and `INSURER_ANALYST_USER_ID` pays.
"""

from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers, used consistently across the whole suite.
INSTALLER_TECH_USER_ID = "tech-01"
SECOND_INSTALLER_TECH_USER_ID = "tech-02"
GATEWAY_USER_ID = "gw-01"
ADJUSTER_USER_ID = "adj-01"
SECOND_ADJUSTER_USER_ID = "adj-02"
INSURER_ANALYST_USER_ID = "ins-01"
SECOND_INSURER_ANALYST_USER_ID = "ins-02"
PROGRAM_ADMIN_USER_ID = "admin-01"

# A placeholder homeowner identifier for calls where ownership is irrelevant.
UNOWNED_HOMEOWNER_USER_ID = "unowned-homeowner-id"

TEST_USERS = {
    "installer_tech_headers": build_user_headers(
        INSTALLER_TECH_USER_ID, "InstallerTech"
    ),
    "second_installer_tech_headers": build_user_headers(
        SECOND_INSTALLER_TECH_USER_ID, "InstallerTech"
    ),
    "gateway_headers": build_user_headers(GATEWAY_USER_ID, "DeviceGateway"),
    "adjuster_headers": build_user_headers(ADJUSTER_USER_ID, "ClaimsAdjuster"),
    "second_adjuster_headers": build_user_headers(
        SECOND_ADJUSTER_USER_ID, "ClaimsAdjuster"
    ),
    "insurer_analyst_headers": build_user_headers(
        INSURER_ANALYST_USER_ID, "InsurerAnalyst"
    ),
    "second_insurer_analyst_headers": build_user_headers(
        SECOND_INSURER_ANALYST_USER_ID, "InsurerAnalyst"
    ),
    "program_admin_headers": build_user_headers(PROGRAM_ADMIN_USER_ID, "ProgramAdmin"),
    # Entity-backed role: a fallback for calls that do not turn on ownership.
    "homeowner_headers": build_user_headers(UNOWNED_HOMEOWNER_USER_ID, "Homeowner"),
}


# --- The entity-backed role ------------------------------------------------
def make_homeowner_headers(homeowner_id: str) -> dict:
    """For `Homeowner`, `X-User-ID` is the acting `Homeowner.id`."""
    return build_user_headers(homeowner_id, "Homeowner")


# --- Per-identifier builders for the opaque roles ---------------------------
def make_installer_tech_headers(user_id: str = INSTALLER_TECH_USER_ID) -> dict:
    return build_user_headers(user_id, "InstallerTech")


def make_gateway_headers(user_id: str = GATEWAY_USER_ID) -> dict:
    return build_user_headers(user_id, "DeviceGateway")


def make_insurer_analyst_headers(user_id: str = INSURER_ANALYST_USER_ID) -> dict:
    return build_user_headers(user_id, "InsurerAnalyst")


def make_claims_adjuster_headers(user_id: str = ADJUSTER_USER_ID) -> dict:
    return build_user_headers(user_id, "ClaimsAdjuster")


def make_program_admin_headers(user_id: str = PROGRAM_ADMIN_USER_ID) -> dict:
    return build_user_headers(user_id, "ProgramAdmin")


def make_headers(user_id: str, role: str) -> dict:
    """Free-form builder for role-authorization sweeps."""
    return build_user_headers(user_id, role)
