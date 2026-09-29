"""Request payload factories.

Each factory returns a valid payload for one endpoint and accepts keyword
overrides. Defaults are chosen so that a facility built from them starts in an
OPEN kitchen posture and a menu cycle built from the three standard components
meets the standard contract's nutrition floor and cost ceiling.
"""

from typing import Any, Dict, Optional

# --- Standard contract terms -------------------------------------------------
# Reused everywhere so that arithmetic expectations stay stable across tests.
STANDARD_CONTRACT_TERMS: Dict[str, Any] = {
    "contracted_kcal_per_meal_day": 2800,
    "contracted_protein_grams_per_meal_day": 55.0,
    "contracted_sodium_mg_cap_per_meal_day": 2400,
    "cost_ceiling_cents_per_meal_day": 320,
    "ld_cents_per_missed_meal": 750,
    "ld_monthly_cap_cents": 5000000,
    "substitution_allowance_pct": 0.3,
}


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Apply overrides; a value of None removes the key entirely so that
    'field absent' can be expressed."""
    out = dict(base)
    for key, value in overrides.items():
        if value is _OMIT:
            out.pop(key, None)
        else:
            out[key] = value
    return out


class _Omit:
    """Sentinel meaning 'leave this key out of the payload'."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<OMIT>"


_OMIT = _Omit()
OMIT = _OMIT


# --- Service contract --------------------------------------------------------


def service_contract_payload(**overrides: Any) -> Dict[str, Any]:
    base = {
        "contract_code": "CFS-STD-001",
        "vendor_name": "Aramark Correctional Services",
        **STANDARD_CONTRACT_TERMS,
    }
    return _merge(base, overrides)


# --- Facility ----------------------------------------------------------------


def facility_payload(contract_id: str, **overrides: Any) -> Dict[str, Any]:
    base = {
        "contract_id": contract_id,
        "facility_code": "FAC-STD-001",
        "name": "Main Unit Kitchen",
        "sharps_authorized_count": 6,
    }
    return _merge(base, overrides)


def sharps_audit_payload(counted_on_board: int) -> Dict[str, Any]:
    return {"counted_on_board": counted_on_board}


# --- Menu cycle and components ----------------------------------------------


def menu_cycle_payload(facility_id: str, **overrides: Any) -> Dict[str, Any]:
    base = {
        "facility_id": facility_id,
        "cycle_code": "CYC-STD-001",
        "cycle_length_days": 1,
    }
    return _merge(base, overrides)


def breakfast_item_payload(**overrides: Any) -> Dict[str, Any]:
    """Oatmeal Bake: 421.0 kcal/100 g over a 50 g portion."""
    base = {
        "cycle_day": 1,
        "meal_slot": "BREAKFAST",
        "component_name": "Oatmeal Bake",
        "kcal_per_100g": 421.0,
        "protein_grams_per_100g": 20.0,
        "sodium_mg_per_100g": 600.0,
        "portion_grams": 50,
        "raw_cost_cents": 95,
    }
    return _merge(base, overrides)


def lunch_item_payload(**overrides: Any) -> Dict[str, Any]:
    """Turkey Casserole: 306.0 kcal/100 g over a 225 g portion."""
    base = {
        "cycle_day": 1,
        "meal_slot": "LUNCH",
        "component_name": "Turkey Casserole",
        "kcal_per_100g": 306.0,
        "protein_grams_per_100g": 8.0,
        "sodium_mg_per_100g": 400.0,
        "portion_grams": 225,
        "raw_cost_cents": 110,
    }
    return _merge(base, overrides)


def dinner_item_payload(**overrides: Any) -> Dict[str, Any]:
    """Bean Rice Bowl: 380.0 kcal/100 g over a 500 g portion."""
    base = {
        "cycle_day": 1,
        "meal_slot": "DINNER",
        "component_name": "Bean Rice Bowl",
        "kcal_per_100g": 380.0,
        "protein_grams_per_100g": 6.1,
        "sodium_mg_per_100g": 160.0,
        "portion_grams": 500,
        "raw_cost_cents": 110,
    }
    return _merge(base, overrides)


STANDARD_DAY_ITEMS = (breakfast_item_payload, lunch_item_payload, dinner_item_payload)


# --- Inmate ------------------------------------------------------------------


def inmate_payload(facility_id: str, **overrides: Any) -> Dict[str, Any]:
    base = {
        "facility_id": facility_id,
        "booking_number": "BK-0001",
        "housing_unit": "GENERAL",
    }
    return _merge(base, overrides)


def movement_payload(movement_type: str, **overrides: Any) -> Dict[str, Any]:
    base = {"movement_type": movement_type}
    return _merge(base, overrides)


# --- Diet order --------------------------------------------------------------


def religious_diet_order_payload(
    inmate_id: str, expected_inmate_version: int, **overrides: Any
) -> Dict[str, Any]:
    base = {
        "inmate_id": inmate_id,
        "order_type": "RELIGIOUS",
        "diet_code": "KOSHER",
        "effective_from": "2026-08-01T00:00:00Z",
        "effective_to": "2026-09-01T00:00:00Z",
        "expected_inmate_version": expected_inmate_version,
    }
    return _merge(base, overrides)


def medical_diet_order_payload(
    inmate_id: str, expected_inmate_version: int, **overrides: Any
) -> Dict[str, Any]:
    base = {
        "inmate_id": inmate_id,
        "order_type": "MEDICAL",
        "diet_code": "RENAL",
        "clinical_indication": "Stage 3 chronic kidney disease",
        "effective_from": "2026-08-01T00:00:00Z",
        "effective_to": "2026-09-01T00:00:00Z",
        "expected_inmate_version": expected_inmate_version,
    }
    return _merge(base, overrides)


# --- Population count --------------------------------------------------------


def population_count_payload(facility_id: str, **overrides: Any) -> Dict[str, Any]:
    base = {
        "facility_id": facility_id,
        "general_population": 10,
        "segregation_population": 2,
        "satellite_population": 1,
        "medical_population": 0,
        "source": "FORMAL_COUNT",
    }
    return _merge(base, overrides)


# --- Meal forecast -----------------------------------------------------------


def meal_forecast_payload(
    facility_id: str, population_count_id: str, **overrides: Any
) -> Dict[str, Any]:
    base = {
        "facility_id": facility_id,
        "population_count_id": population_count_id,
        "service_date": "2026-08-05",
        "meal_slot": "LUNCH",
        "forecast_variant": "COUNT_DRIVEN",
    }
    return _merge(base, overrides)


# --- Production batch --------------------------------------------------------


def production_batch_payload(
    facility_id: str,
    meal_forecast_id: str,
    expected_facility_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    base = {
        "facility_id": facility_id,
        "meal_forecast_id": meal_forecast_id,
        "recipe_component": "Turkey Casserole",
        "planned_trays": 10,
        "scheduled_cook_start_at": "2026-08-05T06:00:00Z",
        "service_site": "MAIN_KITCHEN",
        "expected_facility_version": expected_facility_version,
    }
    return _merge(base, overrides)


def temperature_log_payload(
    log_point: str, temperature_f: float, **overrides: Any
) -> Dict[str, Any]:
    base = {
        "log_point": log_point,
        "temperature_f": temperature_f,
        "site": "MAIN_KITCHEN",
    }
    return _merge(base, overrides)


def advance_stage_payload(to_stage: str, **overrides: Any) -> Dict[str, Any]:
    base = {"to_stage": to_stage}
    return _merge(base, overrides)


def qa_decision_payload(qa_decision: str, reason: str) -> Dict[str, Any]:
    return {"qa_decision": qa_decision, "reason": reason}


# --- Kitchen worker ----------------------------------------------------------


def inmate_worker_payload(
    inmate_id: str, facility_id: str, **overrides: Any
) -> Dict[str, Any]:
    base = {
        "inmate_id": inmate_id,
        "facility_id": facility_id,
        "medical_clearance_expires_at": "2026-12-31T00:00:00Z",
        "sharps_eligible": True,
    }
    return _merge(base, overrides)


def assign_payload(work_area: str) -> Dict[str, Any]:
    return {"work_area": work_area}


# --- Tool issuance -----------------------------------------------------------


def tool_issuance_payload(
    facility_id: str, worker_id: str, **overrides: Any
) -> Dict[str, Any]:
    base = {
        "facility_id": facility_id,
        "issued_to_worker_id": worker_id,
        "tool_class": "SHARP_KNIFE",
        "tool_serial": "KNF-0001",
        "shadow_board_slot": 1,
    }
    return _merge(base, overrides)


def tool_return_payload(returned_count_verified: int = 1) -> Dict[str, Any]:
    return {"returned_count_verified": returned_count_verified}


def declare_unaccounted_payload(
    narrative: str = "Shift-end count came up one knife short.",
) -> Dict[str, Any]:
    return {"narrative": narrative}


# --- Contraband incident -----------------------------------------------------


def contraband_incident_payload(facility_id: str, **overrides: Any) -> Dict[str, Any]:
    base = {
        "facility_id": facility_id,
        "item_class": "YEAST_ALCOHOL",
        "severity": "MAJOR",
        "narrative": "Fermenting fruit mash found behind the proofing cabinet.",
    }
    return _merge(base, overrides)


def disposition_payload(disposition: str, **overrides: Any) -> Dict[str, Any]:
    base = {"disposition": disposition}
    return _merge(base, overrides)


# --- Meal service record -----------------------------------------------------


def meal_service_record_payload(
    facility_id: str, meal_forecast_id: str, **overrides: Any
) -> Dict[str, Any]:
    base = {
        "facility_id": facility_id,
        "meal_forecast_id": meal_forecast_id,
        "service_date": "2026-08-05",
        "meal_slot": "LUNCH",
        "trays_served_general": 10,
        "trays_served_segregation": 2,
        "trays_served_satellite": 1,
        "special_diet_trays_served": 0,
    }
    return _merge(base, overrides)


def close_service_record_payload(expected_service_contract_version: int) -> Dict[str, Any]:
    return {"expected_service_contract_version": expected_service_contract_version}


# --- Menu substitution -------------------------------------------------------


def menu_substitution_payload(
    menu_cycle_item_id: str, meal_service_record_id: str, **overrides: Any
) -> Dict[str, Any]:
    base = {
        "menu_cycle_item_id": menu_cycle_item_id,
        "meal_service_record_id": meal_service_record_id,
        "substitute_component_name": "Chicken Casserole",
        "substitute_kcal_per_100g": 306.0,
        "substitute_protein_grams_per_100g": 8.0,
        "substitute_sodium_mg_per_100g": 400.0,
        "substitute_portion_grams": 225,
        "substitute_cost_cents": 110,
        "reason": "SUPPLY_OUTAGE",
    }
    return _merge(base, overrides)


def substitution_decision_payload(decision: str, **overrides: Any) -> Dict[str, Any]:
    base = {"decision": decision}
    return _merge(base, overrides)


# --- Grievance ---------------------------------------------------------------


def grievance_payload(
    inmate_id: str, facility_id: str, **overrides: Any
) -> Dict[str, Any]:
    base = {
        "inmate_id": inmate_id,
        "facility_id": facility_id,
        "category": "PORTION_SIZE",
        "narrative": "Trays were consistently short at the segregation unit.",
    }
    return _merge(base, overrides)


def route_payload(route: str) -> Dict[str, Any]:
    return {"route": route}


def complete_branch_payload(branch: str, finding: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"branch": branch}
    if finding is not None:
        payload["finding"] = finding
    return payload


def respond_payload(remedy: str, **overrides: Any) -> Dict[str, Any]:
    base = {"remedy": remedy}
    return _merge(base, overrides)
