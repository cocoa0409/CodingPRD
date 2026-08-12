"""Pre-built role headers for every role in the PRD.

All seven roles use opaque operator identifiers (PRD 2.1): X-User-ID is never
compared to any entity's id, only to recorded actor fields on segregation-of-
duties checks. Shared constants are therefore the canonical form; the
make_*_headers builders exist for tests that must control the operator id
(e.g., SoD self-approval scenarios).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "salvage_master_headers": build_user_headers("sm-01", "SalvageMaster"),
    "contracts_officer_headers": build_user_headers("co-01", "ContractsOfficer"),
    "marine_surveyor_headers": build_user_headers("surveyor-01", "MarineSurveyor"),
    "property_surveyor_headers": build_user_headers("surveyor-02", "MarineSurveyor"),
    "environmental_officer_headers": build_user_headers("env-01", "EnvironmentalOfficer"),
    "operations_director_headers": build_user_headers("opsdir-01", "OperationsDirector"),
    "arbitrator_headers": build_user_headers("arb-01", "Arbitrator"),
    "insurer_surveyor_headers": build_user_headers("ins-01", "InsurerSurveyor"),
}


def make_salvage_master_headers(user_id: str) -> dict:
    """SalvageMaster headers with a specific operator id."""
    return build_user_headers(user_id, "SalvageMaster")


def make_contracts_officer_headers(user_id: str) -> dict:
    """ContractsOfficer headers with a specific operator id."""
    return build_user_headers(user_id, "ContractsOfficer")


def make_marine_surveyor_headers(user_id: str) -> dict:
    """MarineSurveyor headers with a specific operator id."""
    return build_user_headers(user_id, "MarineSurveyor")


def make_environmental_officer_headers(user_id: str) -> dict:
    """EnvironmentalOfficer headers with a specific operator id."""
    return build_user_headers(user_id, "EnvironmentalOfficer")


def make_operations_director_headers(user_id: str) -> dict:
    """OperationsDirector headers with a specific operator id (SoD checks
    compare this id against the recorded author fields)."""
    return build_user_headers(user_id, "OperationsDirector")


def make_arbitrator_headers(user_id: str) -> dict:
    """Arbitrator headers with a specific operator id."""
    return build_user_headers(user_id, "Arbitrator")


def make_insurer_surveyor_headers(user_id: str) -> dict:
    """InsurerSurveyor headers with a specific operator id."""
    return build_user_headers(user_id, "InsurerSurveyor")
