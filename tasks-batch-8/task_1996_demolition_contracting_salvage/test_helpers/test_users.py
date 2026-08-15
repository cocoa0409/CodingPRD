"""Pre-built role headers for every role in the PRD §2.1.

All fourteen roles carry an opaque identity: X-User-ID is an operator id never
compared to any entity's id (PRD §2.1). Shared constants are therefore canonical;
the make_*_headers builders exist for tests that need a specific operator id
(for example the segregation-of-duties chains in PRD §2.8).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "contractor_admin_headers": build_user_headers("test-admin-1", "ContractorAdmin"),
    "site_supervisor_headers": build_user_headers("test-supervisor-1", "SiteSupervisor"),
    "surveyor_headers": build_user_headers("test-surveyor-1", "Surveyor"),
    "abatement_supervisor_headers": build_user_headers("test-abatement-1", "AbatementSupervisor"),
    "clearance_officer_headers": build_user_headers("test-clearance-1", "ClearanceOfficer"),
    "utility_coordinator_headers": build_user_headers("test-utility-1", "UtilityCoordinator"),
    "permit_coordinator_headers": build_user_headers("test-permit-1", "PermitCoordinator"),
    "authority_reviewer_headers": build_user_headers("test-authority-1", "AuthorityReviewer"),
    "structural_engineer_headers": build_user_headers("test-structeng-1", "StructuralEngineer"),
    "peer_review_engineer_headers": build_user_headers("test-peereng-1", "PeerReviewEngineer"),
    "salvage_estimator_headers": build_user_headers("test-salvage-1", "SalvageEstimator"),
    "environmental_monitor_headers": build_user_headers("test-monitor-1", "EnvironmentalMonitor"),
    "hauling_dispatcher_headers": build_user_headers("test-hauler-1", "HaulingDispatcher"),
    "municipal_inspector_headers": build_user_headers("test-inspector-1", "MunicipalInspector"),
}


def make_contractor_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ContractorAdmin")


def make_site_supervisor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SiteSupervisor")


def make_surveyor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Surveyor")


def make_abatement_supervisor_headers(user_id: str) -> dict:
    """For SoD-sensitive abatement steps — pass a specific operator id."""
    return build_user_headers(user_id, "AbatementSupervisor")


def make_clearance_officer_headers(user_id: str) -> dict:
    """For SoD-sensitive clearance certification — pass a specific operator id."""
    return build_user_headers(user_id, "ClearanceOfficer")


def make_utility_coordinator_headers(user_id: str) -> dict:
    """For SoD-sensitive verify/confirm steps — pass a specific operator id."""
    return build_user_headers(user_id, "UtilityCoordinator")


def make_permit_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PermitCoordinator")


def make_authority_reviewer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AuthorityReviewer")


def make_structural_engineer_headers(user_id: str) -> dict:
    """For SoD-sensitive engineering authoring — pass a specific operator id."""
    return build_user_headers(user_id, "StructuralEngineer")


def make_peer_review_engineer_headers(user_id: str) -> dict:
    """For SoD-sensitive engineering certification — pass a specific operator id."""
    return build_user_headers(user_id, "PeerReviewEngineer")


def make_salvage_estimator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SalvageEstimator")


def make_environmental_monitor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "EnvironmentalMonitor")


def make_hauling_dispatcher_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "HaulingDispatcher")


def make_municipal_inspector_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "MunicipalInspector")
