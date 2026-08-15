"""Payload factories — one per entity, input fields only (PRD §3)."""
import itertools

# Unique-per-test permit numbers: the counter makes payload reuse safe even
# though every test runs against a fresh database.
_permit_seq = itertools.count(1)

DEFAULTS = {
    "FACILITY_NAME": "Test Facility",
    "RECEIVING_WATER": "Mill River",
    "EFFECTIVE_DATE": "2026-01-01T00:00:00Z",
    "EXPIRATION_DATE": "2030-12-31T00:00:00Z",
    "OUTFALL_NUMBER": "001",
    "PARAMETER_CODE": "TSS",
    "LIMIT_TYPE": "DAILY_MAX",
    "LIMIT_VALUE": 10.0,
    "UNIT": "MG_L",
    "MONITORING_FREQUENCY": "WEEKLY",
    "LIMIT_EFFECTIVE_FROM": "2026-01-01T00:00:00Z",
    "MDL": 0.02,
    "FLOW_MGD": 1.0,
    "PLAN_TITLE": "SWPPP Plan",
    "VERSION_LABEL": "rev-2026-A",
    "INSPECTION_FREQUENCY_DAYS": 30,
}


def next_permit_number(prefix: str = "NPDES-T") -> str:
    return f"{prefix}-{next(_permit_seq):04d}"


def create_permit_payload(**overrides) -> dict:
    defaults = {
        "permit_number": next_permit_number(),
        "facility_name": DEFAULTS["FACILITY_NAME"],
        "receiving_water_body": DEFAULTS["RECEIVING_WATER"],
        "effective_date": DEFAULTS["EFFECTIVE_DATE"],
        "expiration_date": DEFAULTS["EXPIRATION_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_outfall_payload(permit_id: str, **overrides) -> dict:
    defaults = {
        "permit_id": permit_id,
        "outfall_number": DEFAULTS["OUTFALL_NUMBER"],
    }
    defaults.update(overrides)
    return defaults


def create_effluent_limit_payload(outfall_id: str, expected_outfall_version: int, **overrides) -> dict:
    defaults = {
        "outfall_id": outfall_id,
        "parameter_code": DEFAULTS["PARAMETER_CODE"],
        "limit_type": DEFAULTS["LIMIT_TYPE"],
        "limit_value": DEFAULTS["LIMIT_VALUE"],
        "unit": DEFAULTS["UNIT"],
        "monitoring_frequency": DEFAULTS["MONITORING_FREQUENCY"],
        "effective_from": DEFAULTS["LIMIT_EFFECTIVE_FROM"],
        "expected_outfall_version": expected_outfall_version,
    }
    defaults.update(overrides)
    # Optional fields are omitted entirely when not supplied (PRD: optional inputs).
    for optional in ("effective_to", "average_method", "supersedes_limit_id"):
        if defaults.get(optional) is None:
            defaults.pop(optional, None)
    return defaults


def create_sampling_event_payload(outfall_id: str, parameter_code: str,
                                  scheduled_for: str, **overrides) -> dict:
    defaults = {
        "outfall_id": outfall_id,
        "parameter_code": parameter_code,
        "scheduled_for": scheduled_for,
    }
    defaults.update(overrides)
    if defaults.get("collection_window_hours") is None:
        defaults.pop("collection_window_hours", None)
    return defaults


def create_custody_event_payload(event_type: str, event_at: str, **overrides) -> dict:
    defaults = {"event_type": event_type, "event_at": event_at}
    defaults.update(overrides)
    for optional in ("from_party", "to_party", "note"):
        if defaults.get(optional) is None:
            defaults.pop(optional, None)
    return defaults


def create_lab_result_payload(sampling_event_id: str, parameter_code: str,
                              reported_value: float, analyzed_at: str, **overrides) -> dict:
    defaults = {
        "sampling_event_id": sampling_event_id,
        "parameter_code": parameter_code,
        "reported_value": reported_value,
        "unit": DEFAULTS["UNIT"],
        "method_detection_limit": DEFAULTS["MDL"],
        "flow_mgd": DEFAULTS["FLOW_MGD"],
        "analyzed_at": analyzed_at,
    }
    defaults.update(overrides)
    if defaults.get("qualifier") is None:
        defaults.pop("qualifier", None)
    return defaults


def create_dmr_payload(outfall_id: str, period_start: str, period_end: str) -> dict:
    return {
        "outfall_id": outfall_id,
        "period_start": period_start,
        "period_end": period_end,
    }


def create_swppp_plan_payload(permit_id: str, **overrides) -> dict:
    defaults = {
        "permit_id": permit_id,
        "plan_title": DEFAULTS["PLAN_TITLE"],
        "version_label": DEFAULTS["VERSION_LABEL"],
        "inspection_frequency_days": DEFAULTS["INSPECTION_FREQUENCY_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(plan_id: str, scheduled_for: str) -> dict:
    return {"plan_id": plan_id, "scheduled_for": scheduled_for}


def create_renewal_application_payload(permit_id: str, proposed_expiration_date: str) -> dict:
    return {"permit_id": permit_id, "proposed_expiration_date": proposed_expiration_date}


def create_consent_order_payload(exceedance_id: str, **overrides) -> dict:
    defaults = {
        "exceedance_id": exceedance_id,
        "assessment_variant": "PER_DAY",
        "base_penalty_cents": 1000,
        "statutory_cap_cents": 5_000_000,
        "daily_accrual_cents": 0,
    }
    defaults.update(overrides)
    for optional in ("avoided_cost_cents", "gravity_factor"):
        if defaults.get(optional) is None:
            defaults.pop(optional, None)
    return defaults


def create_payment_payload(direction: str, amount_cents: int) -> dict:
    return {"direction": direction, "amount_cents": amount_cents}
