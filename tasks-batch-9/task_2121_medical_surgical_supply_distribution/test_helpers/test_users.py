"""Pre-built role headers for every role named in PRD section 2.1.

`MaterialsManager` is the one role whose `X-User-ID` is a real entity id: the
PRD states that when `X-User-Role` is `MaterialsManager`, `X-User-ID` is the
`id` of the acting `SupplyRoom`. Every ownership-gated call must therefore be
made with `make_materials_manager_headers(room["id"])`; the shared constant
below is only usable where no supply-room scope check applies.

The other four roles carry opaque operator identifiers. Their per-instance
builders exist because two operations in this API are keyed on `X-User-ID`
rather than on role (the two-person rules of PRD section 2.8).
"""

from prd_bench_local_runner.testing import build_user_headers

# Canonical opaque operator identifiers used across the suite.
CONTRACT_ADMIN_USER_ID = "ca-1"
SECOND_CONTRACT_ADMIN_USER_ID = "ca-2"
CLINICIAN_USER_ID = "clin-1"
SECOND_CLINICIAN_USER_ID = "clin-2"
DISTRIBUTION_OPERATOR_USER_ID = "dc-op-1"
SECOND_DISTRIBUTION_OPERATOR_USER_ID = "dc-op-2"
MANUFACTURER_REP_USER_ID = "mfr-rep-1"

TEST_USERS = {
    # Opaque roles — the shared constant is the canonical form.
    "contract_admin_headers": build_user_headers(CONTRACT_ADMIN_USER_ID, "ContractAdmin"),
    "second_contract_admin_headers": build_user_headers(
        SECOND_CONTRACT_ADMIN_USER_ID, "ContractAdmin"
    ),
    "clinician_headers": build_user_headers(CLINICIAN_USER_ID, "Clinician"),
    "second_clinician_headers": build_user_headers(SECOND_CLINICIAN_USER_ID, "Clinician"),
    "distribution_operator_headers": build_user_headers(
        DISTRIBUTION_OPERATOR_USER_ID, "DistributionOperator"
    ),
    "second_distribution_operator_headers": build_user_headers(
        SECOND_DISTRIBUTION_OPERATOR_USER_ID, "DistributionOperator"
    ),
    "manufacturer_rep_headers": build_user_headers(
        MANUFACTURER_REP_USER_ID, "ManufacturerRep"
    ),
    # MaterialsManager fallback — safe ONLY for calls that are not scope-gated
    # (for example a role-authorisation rejection on an endpoint the role may
    # not call at all, or a 404 on a supply room that does not exist).
    "materials_manager_headers": build_user_headers(
        "00000000-0000-4000-8000-0000000000aa", "MaterialsManager"
    ),
}


def make_contract_admin_headers(user_id: str) -> dict:
    """For ContractAdmin. Pass a distinct operator id to exercise the
    two-person rule on chargeback reconciliation."""
    return build_user_headers(user_id, "ContractAdmin")


def make_materials_manager_headers(user_id: str) -> dict:
    """For MaterialsManager. `user_id` MUST be the acting SupplyRoom's `id`
    whenever the call is supply-room scope gated."""
    return build_user_headers(user_id, "MaterialsManager")


def make_clinician_headers(user_id: str) -> dict:
    """For Clinician."""
    return build_user_headers(user_id, "Clinician")


def make_distribution_operator_headers(user_id: str) -> dict:
    """For DistributionOperator. Pass a distinct operator id to exercise the
    two-person rule on cold-chain excursion release."""
    return build_user_headers(user_id, "DistributionOperator")


def make_manufacturer_rep_headers(user_id: str) -> dict:
    """For ManufacturerRep."""
    return build_user_headers(user_id, "ManufacturerRep")


def headers_without_auth() -> dict:
    """Headers carrying neither `X-User-ID` nor `X-User-Role`."""
    return {"Content-Type": "application/json"}
