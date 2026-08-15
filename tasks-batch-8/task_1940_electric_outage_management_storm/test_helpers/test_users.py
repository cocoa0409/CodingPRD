"""Pre-built role headers for every role named in PRD 2.1.

`FieldCrewLead` is entity-backed: its `X-User-ID` must equal the `id` of the
acting `Crew` row. All other roles are opaque identities.
"""
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque identities — the shared constant is the canonical form.
    "emergency_director_headers": build_user_headers("ed-op-1", "EmergencyDirector"),
    "dispatcher_headers": build_user_headers("disp-op-1", "Dispatcher"),
    "telemetry_gateway_headers": build_user_headers("tg-op-1", "TelemetryGateway"),
    "system_operator_headers": build_user_headers("so-op-1", "SystemOperator"),
    "system_operator_2_headers": build_user_headers("so-op-2", "SystemOperator"),
    "mutual_aid_coordinator_headers": build_user_headers(
        "mac-op-1", "MutualAidCoordinator"
    ),
    "materials_manager_headers": build_user_headers("mm-op-1", "MaterialsManager"),
    "claims_officer_headers": build_user_headers("co-1", "ClaimsOfficer"),
    "claims_officer_2_headers": build_user_headers("co-2", "ClaimsOfficer"),
    "regulator_headers": build_user_headers("reg-op-1", "Regulator"),
    # Entity-backed identity — fallback only; the canonical form comes from
    # make_field_crew_lead_headers(crew_id) after creating the Crew row.
    "field_crew_lead_headers": build_user_headers("fcl-op-1", "FieldCrewLead"),
}


def make_field_crew_lead_headers(crew_id: str) -> Dict[str, str]:
    """For FieldCrewLead (entity_backed:Crew). Pass the acting Crew's id."""
    return build_user_headers(crew_id, "FieldCrewLead")


def make_emergency_director_headers(user_id: str = "ed-op-1") -> Dict[str, str]:
    return build_user_headers(user_id, "EmergencyDirector")


def make_dispatcher_headers(user_id: str = "disp-op-1") -> Dict[str, str]:
    return build_user_headers(user_id, "Dispatcher")


def make_telemetry_gateway_headers(user_id: str = "tg-op-1") -> Dict[str, str]:
    return build_user_headers(user_id, "TelemetryGateway")


def make_system_operator_headers(user_id: str = "so-op-1") -> Dict[str, str]:
    return build_user_headers(user_id, "SystemOperator")


def make_mutual_aid_coordinator_headers(user_id: str = "mac-op-1") -> Dict[str, str]:
    return build_user_headers(user_id, "MutualAidCoordinator")


def make_materials_manager_headers(user_id: str = "mm-op-1") -> Dict[str, str]:
    return build_user_headers(user_id, "MaterialsManager")


def make_claims_officer_headers(user_id: str = "co-1") -> Dict[str, str]:
    return build_user_headers(user_id, "ClaimsOfficer")


def make_regulator_headers(user_id: str = "reg-op-1") -> Dict[str, str]:
    return build_user_headers(user_id, "Regulator")


# Headers carrying neither X-User-ID nor X-User-Role — exercises the
# authentication gate directly.
NO_AUTH_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}
