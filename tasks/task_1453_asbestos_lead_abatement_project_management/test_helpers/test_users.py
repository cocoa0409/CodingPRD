"""Pre-built role headers for every role in the PRD (section 2.1).

ContractorAdmin, IndustrialHygienist, and RegulatorClerk are opaque roles:
their X-User-ID is never compared to an entity id, so the shared constants
are canonical. Supervisor is entity-backed by Worker and FacilityOperator is
entity-backed by DisposalFacility: any ownership-gated call MUST be built
with make_supervisor_headers(worker["id"]) /
make_facility_operator_headers(facility["id"]) so X-User-ID equals the acting
entity's id. The shared supervisor/facility-operator constants exist only for
tests whose outcome does not depend on entity identity (e.g. 404 probes).
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque roles — canonical shared form.
    "contractor_admin_headers": build_user_headers("admin_1", "ContractorAdmin"),
    "industrial_hygienist_headers": build_user_headers("ih_1", "IndustrialHygienist"),
    "regulator_clerk_headers": build_user_headers("reg_1", "RegulatorClerk"),
    # Entity-backed roles — fallback only for non-ownership tests.
    "supervisor_headers": build_user_headers("sup_fallback", "Supervisor"),
    "facility_operator_headers": build_user_headers("fac_fallback", "FacilityOperator"),
}


def make_contractor_admin_headers(user_id: str) -> dict:
    """ContractorAdmin (opaque): any user id is acceptable."""
    return build_user_headers(user_id, "ContractorAdmin")


def make_industrial_hygienist_headers(user_id: str) -> dict:
    """IndustrialHygienist (opaque): recorded as result_recorded_by_user_id."""
    return build_user_headers(user_id, "IndustrialHygienist")


def make_regulator_clerk_headers(user_id: str) -> dict:
    """RegulatorClerk (opaque): any user id is acceptable."""
    return build_user_headers(user_id, "RegulatorClerk")


def make_supervisor_headers(user_id: str) -> dict:
    """Supervisor (entity-backed by Worker). Pass the acting Worker's id
    whenever the call is identity-bearing (containment verify, manifest seal,
    complete-work)."""
    return build_user_headers(user_id, "Supervisor")


def make_facility_operator_headers(user_id: str) -> dict:
    """FacilityOperator (entity-backed by DisposalFacility). Pass the acting
    DisposalFacility's id: deliver/confirm/reject require X-User-ID to equal
    the manifest's facility_id."""
    return build_user_headers(user_id, "FacilityOperator")
