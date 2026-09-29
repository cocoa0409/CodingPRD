"""Payload factories.

Each factory returns a valid request body for one create/action endpoint and
accepts ``**overrides`` so a test can perturb exactly the field it is probing.
"""

from typing import Any, List, Optional

Payload = dict[str, Any]


def _merge(base: Payload, overrides: Payload) -> Payload:
    base.update(overrides)
    return base


# --------------------------------------------------------------------------
# Equipment models (PRD §3.1)
# --------------------------------------------------------------------------


def equipment_model_payload(**overrides: Any) -> Payload:
    """An ELECTRIC fryer that supports all three controls packages."""
    return _merge(
        {
            "model_code": "FRY-900",
            "name": "Fryer 900",
            "category": "FRYER",
            "energy_type": "ELECTRIC",
            "base_price_cents": 1850020,
            "supported_controls_packages": [
                "STANDARD_DIAL",
                "TOUCH_PRO",
                "CONNECT_PLUS",
            ],
            "rated_throughput_units_per_hour": 120,
        },
        overrides,
    )


def dual_energy_model_payload(**overrides: Any) -> Payload:
    """A DUAL-energy griddle, which needs all three certification scopes."""
    return _merge(
        {
            "model_code": "GRL-500",
            "name": "Griddle 500",
            "category": "GRIDDLE",
            "energy_type": "DUAL",
            "base_price_cents": 1850020,
            "supported_controls_packages": [
                "STANDARD_DIAL",
                "TOUCH_PRO",
                "CONNECT_PLUS",
            ],
            "rated_throughput_units_per_hour": 90,
        },
        overrides,
    )


# --------------------------------------------------------------------------
# Certification listings (PRD §3.1)
# --------------------------------------------------------------------------


def certification_listing_payload(
    equipment_model_id: str,
    agency_code: str = "AGENCY_GAMMA",
    scopes: Optional[List[str]] = None,
    **overrides: Any,
) -> Payload:
    return _merge(
        {
            "equipment_model_id": equipment_model_id,
            "agency_code": agency_code,
            "scopes": list(scopes) if scopes is not None else ["SANITATION", "ELECTRICAL"],
        },
        overrides,
    )


def agency_decision_payload(decision: str, **overrides: Any) -> Payload:
    return _merge({"decision": decision}, overrides)


# --------------------------------------------------------------------------
# Chain accounts and configurations (PRD §3.3)
# --------------------------------------------------------------------------


def chain_account_payload(**overrides: Any) -> Payload:
    return _merge(
        {
            "account_code": "CHN-1",
            "name": "Skillet Chain",
            "contracted_unit_volume": 250,
        },
        overrides,
    )


def chain_configuration_payload(
    chain_account_id: str,
    equipment_model_id: str,
    expected_chain_account_version: int,
    **overrides: Any,
) -> Payload:
    return _merge(
        {
            "chain_account_id": chain_account_id,
            "equipment_model_id": equipment_model_id,
            "config_code": "CFG-1",
            "option_codes": ["SPLIT_TANK", "HIGH_ALT"],
            "controls_package": "TOUCH_PRO",
            "branding_kit": "FULL_WRAP",
            "expected_chain_account_version": expected_chain_account_version,
        },
        overrides,
    )


def engineering_decision_payload(decision: str, **overrides: Any) -> Payload:
    return _merge({"decision": decision}, overrides)


def branding_signoff_payload(**overrides: Any) -> Payload:
    return _merge({"approved_artwork_ref": "ART-1"}, overrides)


# --------------------------------------------------------------------------
# Performance validations (PRD §3.4)
# --------------------------------------------------------------------------


def performance_validation_payload(
    chain_configuration_id: str,
    expected_chain_configuration_version: int,
    **overrides: Any,
) -> Payload:
    return _merge(
        {
            "chain_configuration_id": chain_configuration_id,
            "menu_item_code": "FRIES",
            "target_throughput_units_per_hour": 60.0,
            "hold_temp_target_c": 175.0,
            "expected_chain_configuration_version": expected_chain_configuration_version,
        },
        overrides,
    )


def test_run_payload(
    units_produced: int, minutes: int, hold_temp_c: float, **overrides: Any
) -> Payload:
    return _merge(
        {
            "units_produced": units_produced,
            "minutes": minutes,
            "hold_temp_c": hold_temp_c,
        },
        overrides,
    )


# The three-run series that certifies 66.06 units per hour against a 175.0 °C
# hold-temperature target.
PASSING_TEST_RUNS = [(95, 90, 175.0), (108, 95, 174.0), (102, 92, 176.0)]


# --------------------------------------------------------------------------
# Programmes, site orders, lines and slots (PRD §3.6, §3.7)
# --------------------------------------------------------------------------


def construction_program_payload(chain_account_id: str, **overrides: Any) -> Payload:
    return _merge(
        {
            "chain_account_id": chain_account_id,
            "program_code": "PRG-1",
            "program_type": "NEW_BUILD",
            "site_count_planned": 5,
        },
        overrides,
    )


def site_order_payload(
    construction_program_id: str, chain_configuration_id: str, **overrides: Any
) -> Payload:
    return _merge(
        {
            "construction_program_id": construction_program_id,
            "chain_configuration_id": chain_configuration_id,
            "site_code": "SITE-1",
            "committed_delivery_date": "2026-09-25T00:00:00Z",
            "unit_count": 60,
        },
        overrides,
    )


def build_line_payload(**overrides: Any) -> Payload:
    return _merge(
        {
            "line_code": "LN-1",
            "plant_code": "P1",
            "daily_capacity_units": 20,
            "supported_energy_types": ["ELECTRIC", "DUAL"],
        },
        overrides,
    )


def production_slot_payload(
    build_line_id: str, site_order_id: str, **overrides: Any
) -> Payload:
    return _merge(
        {
            "build_line_id": build_line_id,
            "site_order_id": site_order_id,
            "window_start": "2026-09-07T00:00:00Z",
            "window_end": "2026-09-11T00:00:00Z",
            "units": 60,
        },
        overrides,
    )


def build_progress_payload(progress: str, **overrides: Any) -> Payload:
    return _merge({"progress": progress}, overrides)


def cancellation_payload(cancellation_reason: str, **overrides: Any) -> Payload:
    return _merge({"cancellation_reason": cancellation_reason}, overrides)


def fulfillment_event_payload(event: str, **overrides: Any) -> Payload:
    return _merge({"event": event}, overrides)


def commitment_waiver_payload(waiver_reason: str, **overrides: Any) -> Payload:
    return _merge({"waiver_reason": waiver_reason}, overrides)


# --------------------------------------------------------------------------
# Connected units and firmware campaigns (PRD §3.8)
# --------------------------------------------------------------------------


def connected_unit_payload(
    equipment_model_id: str, serial_number: str = "SN-1", **overrides: Any
) -> Payload:
    return _merge(
        {
            "equipment_model_id": equipment_model_id,
            "serial_number": serial_number,
            "service_tier": "BASE",
        },
        overrides,
    )


def telemetry_payload(
    fault_count_30d: int, missed_heartbeat_count: int, **overrides: Any
) -> Payload:
    return _merge(
        {
            "fault_count_30d": fault_count_30d,
            "missed_heartbeat_count": missed_heartbeat_count,
        },
        overrides,
    )


def recipe_push_payload(recipe_book_version: int, **overrides: Any) -> Payload:
    return _merge({"recipe_book_version": recipe_book_version}, overrides)


def coverage_action_payload(action: str, **overrides: Any) -> Payload:
    return _merge({"action": action}, overrides)


def firmware_campaign_payload(
    equipment_model_id: str, campaign_code: str = "FW-1", **overrides: Any
) -> Payload:
    return _merge(
        {
            "equipment_model_id": equipment_model_id,
            "campaign_code": campaign_code,
            "target_firmware_version": "2.0.0",
            "window_start": "2026-10-01T00:00:00Z",
            "window_end": "2026-10-05T00:00:00Z",
            "cohort_scope": "CANARY",
        },
        overrides,
    )


def unit_result_payload(connected_unit_id: str, outcome: str, **overrides: Any) -> Payload:
    return _merge(
        {"connected_unit_id": connected_unit_id, "outcome": outcome}, overrides
    )


def campaign_close_payload(disposition: str, **overrides: Any) -> Payload:
    return _merge({"disposition": disposition}, overrides)


# --------------------------------------------------------------------------
# Service partners, technicians and claims (PRD §3.9)
# --------------------------------------------------------------------------


def service_partner_payload(**overrides: Any) -> Payload:
    return _merge(
        {
            "partner_code": "SP-1",
            "name": "Metro Service",
            "region_code": "NE",
            "parts_stocking_level": "FULL",
        },
        overrides,
    )


def partner_authorization_payload(action: str, **overrides: Any) -> Payload:
    return _merge({"action": action}, overrides)


def technician_certification_payload(
    service_partner_id: str,
    equipment_model_id: str,
    technician_code: str = "T1",
    training_hours: float = 40,
    **overrides: Any,
) -> Payload:
    return _merge(
        {
            "service_partner_id": service_partner_id,
            "equipment_model_id": equipment_model_id,
            "technician_code": technician_code,
            "training_hours": training_hours,
        },
        overrides,
    )


def technician_grade_payload(exam_score: float, **overrides: Any) -> Payload:
    return _merge({"exam_score": exam_score}, overrides)


def warranty_claim_payload(
    connected_unit_id: str,
    service_partner_id: str,
    technician_certification_id: str,
    claim_code: str = "CLM-1",
    parts_cost_cents: int = 123000,
    labor_hours: float = 3.0,
    **overrides: Any,
) -> Payload:
    return _merge(
        {
            "connected_unit_id": connected_unit_id,
            "service_partner_id": service_partner_id,
            "technician_certification_id": technician_certification_id,
            "claim_code": claim_code,
            "parts_cost_cents": parts_cost_cents,
            "labor_hours": labor_hours,
        },
        overrides,
    )


def adjudication_payload(decision: str, **overrides: Any) -> Payload:
    return _merge({"decision": decision}, overrides)


def reversal_payload(reversal_reason: str, **overrides: Any) -> Payload:
    return _merge({"reversal_reason": reversal_reason}, overrides)
