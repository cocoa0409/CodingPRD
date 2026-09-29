"""
Header builders for the seven roles (PRD 2.1).

Six roles carry opaque identities: their `X-User-ID` is "an opaque operator
identifier not tied to any persisted entity", recorded on the rows they touch
and compared only by the two segregation-of-duties gates. Each of those gets a
primary and a secondary identifier so a test can stage "a different engineer"
or "a second inspector" without inventing strings inline.

`CustomerRepresentative` is entity-backed: its `X-User-ID` is the `id` of the
acting `CustomerProgram`. It therefore has no meaningful shared constant for
ownership-gated calls — use `make_customer_representative_headers(program_id)`
with the real program id. The shared `TEST_USERS` entry exists only for the
tests that deliberately present a foreign or unresolvable program identity.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_CUSTOMER_REPRESENTATIVE,
    ROLE_DESIGN_ENGINEER,
    ROLE_ENGINEERING_MANAGER,
    ROLE_PLANT_ADMIN,
    ROLE_PROCESS_TECHNICIAN,
    ROLE_PROGRAM_MANAGER,
    ROLE_QUALITY_INSPECTOR,
)

# Opaque operator identifiers, matching the personas the workflows describe.
DESIGN_ENGINEER_PRIMARY = "de-01"
DESIGN_ENGINEER_SECONDARY = "de-02"
ENGINEERING_MANAGER_PRIMARY = "em-01"
ENGINEERING_MANAGER_SECONDARY = "em-02"
PROCESS_TECHNICIAN_PRIMARY = "pt-01"
PROCESS_TECHNICIAN_SECONDARY = "pt-02"
QUALITY_INSPECTOR_PRIMARY = "qi-01"
QUALITY_INSPECTOR_SECONDARY = "qi-02"
QUALITY_INSPECTOR_THIRD = "qi-03"
PROGRAM_MANAGER_PRIMARY = "pm-01"
PROGRAM_MANAGER_SECONDARY = "pm-02"
PLANT_ADMIN_PRIMARY = "pa-01"

TEST_USERS: Dict[str, Dict[str, str]] = {
    "design_engineer": build_user_headers(DESIGN_ENGINEER_PRIMARY, ROLE_DESIGN_ENGINEER),
    "design_engineer_alt": build_user_headers(
        DESIGN_ENGINEER_SECONDARY, ROLE_DESIGN_ENGINEER
    ),
    "engineering_manager": build_user_headers(
        ENGINEERING_MANAGER_PRIMARY, ROLE_ENGINEERING_MANAGER
    ),
    "engineering_manager_alt": build_user_headers(
        ENGINEERING_MANAGER_SECONDARY, ROLE_ENGINEERING_MANAGER
    ),
    "process_technician": build_user_headers(
        PROCESS_TECHNICIAN_PRIMARY, ROLE_PROCESS_TECHNICIAN
    ),
    "process_technician_alt": build_user_headers(
        PROCESS_TECHNICIAN_SECONDARY, ROLE_PROCESS_TECHNICIAN
    ),
    "quality_inspector": build_user_headers(
        QUALITY_INSPECTOR_PRIMARY, ROLE_QUALITY_INSPECTOR
    ),
    "quality_inspector_alt": build_user_headers(
        QUALITY_INSPECTOR_SECONDARY, ROLE_QUALITY_INSPECTOR
    ),
    "quality_inspector_third": build_user_headers(
        QUALITY_INSPECTOR_THIRD, ROLE_QUALITY_INSPECTOR
    ),
    "program_manager": build_user_headers(PROGRAM_MANAGER_PRIMARY, ROLE_PROGRAM_MANAGER),
    "program_manager_alt": build_user_headers(
        PROGRAM_MANAGER_SECONDARY, ROLE_PROGRAM_MANAGER
    ),
    "plant_admin": build_user_headers(PLANT_ADMIN_PRIMARY, ROLE_PLANT_ADMIN),
    # Entity-backed role: only safe where the call is NOT ownership-gated, or
    # where the test wants the ownership check to fail.
    "customer_representative_unowned": build_user_headers(
        "00000000-0000-4000-8000-000000000999", ROLE_CUSTOMER_REPRESENTATIVE
    ),
}

DESIGN_ENGINEER_HEADERS = TEST_USERS["design_engineer"]
DESIGN_ENGINEER_ALT_HEADERS = TEST_USERS["design_engineer_alt"]
ENGINEERING_MANAGER_HEADERS = TEST_USERS["engineering_manager"]
ENGINEERING_MANAGER_ALT_HEADERS = TEST_USERS["engineering_manager_alt"]
PROCESS_TECHNICIAN_HEADERS = TEST_USERS["process_technician"]
PROCESS_TECHNICIAN_ALT_HEADERS = TEST_USERS["process_technician_alt"]
QUALITY_INSPECTOR_HEADERS = TEST_USERS["quality_inspector"]
QUALITY_INSPECTOR_ALT_HEADERS = TEST_USERS["quality_inspector_alt"]
QUALITY_INSPECTOR_THIRD_HEADERS = TEST_USERS["quality_inspector_third"]
PROGRAM_MANAGER_HEADERS = TEST_USERS["program_manager"]
PROGRAM_MANAGER_ALT_HEADERS = TEST_USERS["program_manager_alt"]
PLANT_ADMIN_HEADERS = TEST_USERS["plant_admin"]
CUSTOMER_REP_UNOWNED_HEADERS = TEST_USERS["customer_representative_unowned"]


def make_customer_representative_headers(program_id: str) -> Dict[str, str]:
    """A CustomerRepresentative acts as the program whose id it presents.

    Pass the real `CustomerProgram.id`; every ownership check compares the
    resource's program foreign key against this value.
    """
    return build_user_headers(program_id, ROLE_CUSTOMER_REPRESENTATIVE)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Arbitrary identifier/role pairing, for identity-sensitive scenarios."""
    return build_user_headers(user_id, role)


def headers_without_role(user_id: str = DESIGN_ENGINEER_PRIMARY) -> Dict[str, str]:
    """Headers that omit `X-User-Role` entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role: str = ROLE_DESIGN_ENGINEER) -> Dict[str, str]:
    """Headers that omit `X-User-ID` entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}
