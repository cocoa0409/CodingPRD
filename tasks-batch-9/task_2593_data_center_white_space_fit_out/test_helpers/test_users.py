"""Pre-built role headers for every role in the PRD.

Every request carries `X-User-Role` and `X-User-ID`. For the eight staff roles the
user id is an opaque operator identifier; for `TenantRepresentative` it is the id of
the acting `Tenant`, so that role always needs a per-instance builder.
"""
from prd_bench_local_runner.testing import build_user_headers

from .constants import USER_IDS

# Shared constants — the canonical form for the eight opaque staff roles.
TEST_USERS = {
    "facility_planner_headers": build_user_headers(
        USER_IDS["FACILITY_PLANNER"], "FacilityPlanner"
    ),
    "electrical_contractor_headers": build_user_headers(
        USER_IDS["ELECTRICAL_CONTRACTOR"], "ElectricalContractor"
    ),
    "mechanical_contractor_headers": build_user_headers(
        USER_IDS["MECHANICAL_CONTRACTOR"], "MechanicalContractor"
    ),
    "commissioning_agent_headers": build_user_headers(
        USER_IDS["COMMISSIONING_AGENT"], "CommissioningAgent"
    ),
    "commissioning_agent_2_headers": build_user_headers(
        USER_IDS["COMMISSIONING_AGENT_2"], "CommissioningAgent"
    ),
    "witness_authority_headers": build_user_headers(
        USER_IDS["WITNESS_AUTHORITY"], "WitnessAuthority"
    ),
    "change_manager_headers": build_user_headers(
        USER_IDS["CHANGE_MANAGER"], "ChangeManager"
    ),
    "change_manager_2_headers": build_user_headers(
        USER_IDS["CHANGE_MANAGER_2"], "ChangeManager"
    ),
    "operations_manager_headers": build_user_headers(
        USER_IDS["OPERATIONS_MANAGER"], "OperationsManager"
    ),
    "security_administrator_headers": build_user_headers(
        USER_IDS["SECURITY_ADMINISTRATOR"], "SecurityAdministrator"
    ),
}


# --------------------------------------------------------------------------
# Per-instance builders
# --------------------------------------------------------------------------
def make_tenant_representative_headers(tenant_id: str) -> dict:
    """For TenantRepresentative: `X-User-ID` is the id of the acting Tenant, so the
    real Tenant.id must always be threaded through here for ownership checks."""
    return build_user_headers(tenant_id, "TenantRepresentative")


def make_facility_planner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FacilityPlanner")


def make_electrical_contractor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ElectricalContractor")


def make_mechanical_contractor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "MechanicalContractor")


def make_commissioning_agent_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CommissioningAgent")


def make_witness_authority_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "WitnessAuthority")


def make_change_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ChangeManager")


def make_operations_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "OperationsManager")


def make_security_administrator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SecurityAdministrator")


def make_headers(user_id: str, role: str) -> dict:
    """Arbitrary role/user pair, including roles that are not among the nine."""
    return build_user_headers(user_id, role)


def headers_without_role(user_id: str) -> dict:
    """Headers with `X-User-ID` but no `X-User-Role` at all."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role: str) -> dict:
    """Headers naming a role but carrying no `X-User-ID`."""
    return {"X-User-Role": role, "Content-Type": "application/json"}
