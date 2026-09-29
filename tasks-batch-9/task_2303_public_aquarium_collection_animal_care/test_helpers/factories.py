"""Request-payload builders.

Every builder returns a plain dict containing only client-supplied input fields —
never a derived or system field — and accepts keyword overrides so a test can
vary exactly the one value it cares about. Unique code fields get a fresh suffix
on each call so repeated builds inside one test never collide.
"""
import itertools
from typing import Any, Dict, List, Optional

from .constants import CLOCK_EPOCH

_counter = itertools.count(1)


def unique_suffix() -> str:
    return f"{next(_counter):04d}"


# --------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------
def clock_payload(current_utc: str) -> Dict[str, Any]:
    return {"current_utc": current_utc}


# --------------------------------------------------------------------------
# Life support systems
# --------------------------------------------------------------------------
def life_support_system_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "system_code": f"LSS-{unique_suffix()}",
        "system_type": "RECIRCULATING_MARINE",
        "design_habitat": "COLD_MARINE",
        "redundancy_class": "N_PLUS_1",
        "redundancy_test_interval_days": 365,
    }
    payload.update(overrides)
    return payload


def water_quality_reading_payload(taken_at: str = CLOCK_EPOCH, **overrides: Any) -> Dict[str, Any]:
    """A reading that sits exactly on every COLD_MARINE target (all ratios 0)."""
    payload = {
        "taken_at": taken_at,
        "temperature_c": 12.0,
        "salinity_ppt": 33.0,
        "ph": 8.1,
        "dissolved_oxygen_mg_l": 7.5,
        "ammonia_mg_l": 0.0,
        "nitrite_mg_l": 0.0,
    }
    payload.update(overrides)
    return payload


def redundancy_test_payload(performed_at: str = CLOCK_EPOCH, result: str = "PASS", **overrides: Any) -> Dict[str, Any]:
    payload = {"performed_at": performed_at, "result": result}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Exhibits
# --------------------------------------------------------------------------
def exhibit_payload(life_support_system_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = {
        "exhibit_code": f"EXH-{unique_suffix()}",
        "name": "Kelp Forest",
        "habitat_type": "COLD_MARINE",
        "life_support_system_id": life_support_system_id,
        "display_volume_liters": 50000.0,
        "bioload_capacity_units": 100.0,
    }
    payload.update(overrides)
    return payload


def exhibit_patch_payload(expected_exhibit_version: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"expected_exhibit_version": expected_exhibit_version}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Species
# --------------------------------------------------------------------------
def species_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "scientific_name": f"Sebastes testus {unique_suffix()}",
        "common_name": "Test Rockfish",
        "taxon_group": "TELEOST",
        "protection_status": "UNLISTED",
        "sustainability_rating": "GREEN",
        "bioload_units_per_specimen": 10.0,
        "base_quarantine_days": 30,
        "wild_take_quota_annual": 10,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Institutions
# --------------------------------------------------------------------------
def institution_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "name": f"Partner Aquarium {unique_suffix()}",
        "institution_code": f"INST-{unique_suffix()}",
        "accreditation_status": "ACCREDITED",
        "welfare_audit_score": 90.00,
    }
    payload.update(overrides)
    return payload


def institution_patch_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Collection plan entries
# --------------------------------------------------------------------------
def collection_plan_entry_payload(
    exhibit_id: str,
    species_id: str,
    expected_exhibit_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "exhibit_id": exhibit_id,
        "species_id": species_id,
        "planned_count": 5,
        "sustainability_requirement": "GREEN_OR_YELLOW",
        "expected_exhibit_version": expected_exhibit_version,
    }
    payload.update(overrides)
    return payload


def plan_status_action_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Acquisition requests
# --------------------------------------------------------------------------
def acquisition_request_payload(
    collection_plan_entry_id: str,
    source_type: str = "CAPTIVE_BRED",
    requested_count: int = 1,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "collection_plan_entry_id": collection_plan_entry_id,
        "source_type": source_type,
        "requested_count": requested_count,
    }
    payload.update(overrides)
    return payload


def clearance_payload(expected_species_version: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"expected_species_version": expected_species_version}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Permits
# --------------------------------------------------------------------------
def permit_payload(
    acquisition_request_id: str,
    permit_type: str = "IMPORT",
    document_codes: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "acquisition_request_id": acquisition_request_id,
        "permit_type": permit_type,
        "authority_reference": f"AUTH-{unique_suffix()}",
        "document_codes": list(document_codes) if document_codes is not None else [],
    }
    payload.update(overrides)
    return payload


def permit_decision_payload(decision: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Specimens
# --------------------------------------------------------------------------
def specimen_payload(
    species_id: str,
    acquisition_request_id: str,
    arrival_at: str = CLOCK_EPOCH,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "accession_code": f"ACC-{unique_suffix()}",
        "species_id": species_id,
        "acquisition_request_id": acquisition_request_id,
        "arrival_at": arrival_at,
    }
    payload.update(overrides)
    return payload


def placement_payload(exhibit_id: str, expected_exhibit_version: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "exhibit_id": exhibit_id,
        "expected_exhibit_version": expected_exhibit_version,
    }
    payload.update(overrides)
    return payload


def removal_payload(expected_exhibit_version: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"expected_exhibit_version": expected_exhibit_version}
    payload.update(overrides)
    return payload


def mortality_payload(occurred_at: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"occurred_at": occurred_at}
    payload.update(overrides)
    return payload


def husbandry_log_payload(log_type: str, logged_at: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"log_type": log_type, "logged_at": logged_at}
    payload.update(overrides)
    return payload


def feeding_log_payload(logged_at: str, appetite_score: int = 5, behavior_code: str = "NORMAL", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "log_type": "FEEDING",
        "logged_at": logged_at,
        "appetite_score": appetite_score,
        "behavior_code": behavior_code,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Quarantine / veterinary
# --------------------------------------------------------------------------
def quarantine_review_payload(outcome: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"outcome": outcome}
    payload.update(overrides)
    return payload


def veterinary_case_payload(specimen_id: str, case_type: str, opened_at: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "specimen_id": specimen_id,
        "case_type": case_type,
        "opened_at": opened_at,
    }
    payload.update(overrides)
    return payload


def case_closure_payload(outcome: str, findings_severity: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"outcome": outcome, "findings_severity": findings_severity}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Transfers
# --------------------------------------------------------------------------
def transfer_request_payload(
    specimen_id: str,
    receiving_institution_id: str,
    proposed_transfer_at: str,
    welfare_conditions: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "specimen_id": specimen_id,
        "receiving_institution_id": receiving_institution_id,
        "proposed_transfer_at": proposed_transfer_at,
        "welfare_conditions": list(welfare_conditions)
        if welfare_conditions is not None
        else ["WATER_CHEMISTRY_MATCH", "TRANSPORT_OXYGEN_PLAN", "QUARANTINE_ON_ARRIVAL"],
    }
    payload.update(overrides)
    return payload


def transfer_decision_payload(decision: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Interaction sessions
# --------------------------------------------------------------------------
def interaction_session_payload(
    exhibit_id: str,
    starts_at: str,
    ends_at: str,
    program_type: str = "FEEDING_ENCOUNTER",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "exhibit_id": exhibit_id,
        "program_type": program_type,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "max_guests": 10,
    }
    payload.update(overrides)
    return payload


def session_transition_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Accreditation audits
# --------------------------------------------------------------------------
def accreditation_audit_payload(scheduled_for: str, scope: str = "FULL", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "audit_code": f"AUD-{unique_suffix()}",
        "scope": scope,
        "scheduled_for": scheduled_for,
    }
    payload.update(overrides)
    return payload


def audit_progression_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    payload.update(overrides)
    return payload
