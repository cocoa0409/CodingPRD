"""Payload factories — one per entity, input fields only (PRD §3)."""
import uuid

DEFAULTS = {
    "CUSTOMER_NAME": "Acme Corp",
    "CREDIT_LIMIT_CENTS": 1_000_000_000,
    "MACHINE_TYPE": "LATHE",
    "YEAR_OF_MANUFACTURE": 2018,
    "CONTROL_GENERATION": "LEGACY",
    "SPINDLE_HOURS": 40_000,
    "PD_MICRONS": 10.0,
    "SR_MICRONS": 8.0,
    "BL_MICRONS": 6.0,
    "SCOPE_NOTES": "as-found scope",
    "DECISION": "MECHANICAL_REBUILD",
    "ENGINEER_ID": "eng-1",
    "TRAINER_ID": "tr-1",
    "PART_DESCRIPTION": "Ball screw",
    "UNIT_COST_CENTS": 1_250_000,
    "STOCK_QUANTITY": 10,
    "LEAD_TIME_DAYS": 14,
    "LINE_QUANTITY": 1,
    "RE_COST_CENTS": 500_000,
    "REPEATABILITY_MICRONS": 5.0,
    "VALUATION_VARIANT": "MARKET_COMPARABLE",
    "CLAIM_TYPE": "ACCURACY_DRIFT",
    "MEASURED_POSITIONING_MICRONS": 30.0,
    "WINDOW_STARTS_AT": "2026-06-01T00:00:00Z",
    "WINDOW_ENDS_AT": "2026-07-01T00:00:00Z",
    "STAGE_SHIP_DATE": "2026-06-10T00:00:00Z",
    "STAGE_RETURN_DATE": "2026-06-15T00:00:00Z",
}

PASSING_SAMPLES = [8, -8, 8, -8, 0]
FAILING_SAMPLES = [25, 0, 0, 0, 0]


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["CUSTOMER_NAME"],
        "credit_limit_cents": DEFAULTS["CREDIT_LIMIT_CENTS"],
        "region": "midwest",
    }
    defaults.update(overrides)
    return defaults


def create_machine_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "serial_number": _unique("SN"),
        "machine_type": DEFAULTS["MACHINE_TYPE"],
        "year_of_manufacture": DEFAULTS["YEAR_OF_MANUFACTURE"],
        "control_generation": DEFAULTS["CONTROL_GENERATION"],
        "spindle_hours": DEFAULTS["SPINDLE_HOURS"],
    }
    defaults.update(overrides)
    return defaults


def create_assessment_payload(expected_machine_version: int, **overrides) -> dict:
    defaults = {
        "positioning_deviation_microns": DEFAULTS["PD_MICRONS"],
        "spindle_runout_microns": DEFAULTS["SR_MICRONS"],
        "backlash_microns": DEFAULTS["BL_MICRONS"],
        "scope_notes": DEFAULTS["SCOPE_NOTES"],
        "expected_machine_version": expected_machine_version,
    }
    defaults.update(overrides)
    return defaults


def create_decision_payload(**overrides) -> dict:
    defaults = {
        "decision": DEFAULTS["DECISION"],
        "assigned_engineer_id": DEFAULTS["ENGINEER_ID"],
    }
    defaults.update(overrides)
    return defaults


def create_quote_payload(expected_project_version: int) -> dict:
    return {"expected_project_version": expected_project_version}


def create_part_payload(**overrides) -> dict:
    defaults = {
        "part_number": _unique("P"),
        "description": DEFAULTS["PART_DESCRIPTION"],
        "oem_status": "ACTIVE",
        "unit_cost_cents": DEFAULTS["UNIT_COST_CENTS"],
        "stock_quantity": DEFAULTS["STOCK_QUANTITY"],
        "lead_time_days": DEFAULTS["LEAD_TIME_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def create_part_line_payload(part_id: str, **overrides) -> dict:
    defaults = {
        "part_id": part_id,
        "quantity": DEFAULTS["LINE_QUANTITY"],
    }
    defaults.update(overrides)
    return defaults


def create_fabricate_payload(**overrides) -> dict:
    defaults = {"re_cost_cents": DEFAULTS["RE_COST_CENTS"]}
    defaults.update(overrides)
    return defaults


def create_record_payload(samples=None, **overrides) -> dict:
    defaults = {
        "samples_microns": samples if samples is not None else PASSING_SAMPLES,
        "repeatability_microns": DEFAULTS["REPEATABILITY_MICRONS"],
    }
    defaults.update(overrides)
    return defaults


def create_begin_training_payload(**overrides) -> dict:
    defaults = {"trainer_id": DEFAULTS["TRAINER_ID"]}
    defaults.update(overrides)
    return defaults


def create_downtime_window_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "starts_at": DEFAULTS["WINDOW_STARTS_AT"],
        "ends_at": DEFAULTS["WINDOW_ENDS_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_shipment_stage_payload(window_id: str, **overrides) -> dict:
    defaults = {
        "window_id": window_id,
        "stage_sequence": 1,
        "planned_ship_date": DEFAULTS["STAGE_SHIP_DATE"],
        "planned_return_date": DEFAULTS["STAGE_RETURN_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_warranty_claim_payload(**overrides) -> dict:
    defaults = {
        "claim_type": DEFAULTS["CLAIM_TYPE"],
        "measured_positioning_microns": DEFAULTS["MEASURED_POSITIONING_MICRONS"],
    }
    defaults.update(overrides)
    return defaults


def create_trade_in_offer_payload(expected_machine_version: int, **overrides) -> dict:
    defaults = {
        "valuation_variant": DEFAULTS["VALUATION_VARIANT"],
        "expected_machine_version": expected_machine_version,
    }
    defaults.update(overrides)
    return defaults


def create_escalation_resolve_payload(action: str = "RETRY") -> dict:
    return {"action": action}
