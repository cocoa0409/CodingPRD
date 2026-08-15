"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
from . import constants as C

DEFAULTS = {
    "SHIPPER_NAME": "Acme Chemical Co",
    "FACILITY_NAME": "Acme Baton Rouge Plant",
    "SEGMENT_NAME": "Siding A",
    "SEGMENT_LENGTH_FEET": 1200,
    "SEGMENT_CAPACITY": 3,
    "PROJECT_NAME": "North Siding Extension",
    "ESTIMATED_COST_CENTS": 500000,
    "RAIL_WEIGHT_LB_PER_YARD": 115,
    "TIE_MATERIAL": "CONCRETE",
    "BALLAST_DEPTH_INCHES": 12,
    "CAR_MARK": "RBOX1001",
    "PLACED_AT": "2026-08-01T00:00:00Z",
    "PLACED_DATE": "2026-08-01",
    "CLAIMANT_NAME": "J. Doe",
    "INCIDENT_DATE": "2026-08-02",
    "CLAIM_AMOUNT_CENTS": 60000,
    "DEVICE_TYPE": "DERAIL",
    "LOCATION_DESCRIPTION": "East end, fouling point",
}


def create_agreement_payload(**overrides) -> dict:
    """Canonical agreement creation payload (PRD §3.1)."""
    defaults = {
        "shipper_name": DEFAULTS["SHIPPER_NAME"],
        "shipper_user_id": C.SHIPPER_USER_ID,
        "facility_name": DEFAULTS["FACILITY_NAME"],
        "term_start_date": C.TERM_START_DATE,
        "term_end_date": C.TERM_END_DATE,
        "renewal_notice_days": C.RENEWAL_NOTICE_DAYS,
        "renewal_term_months": C.RENEWAL_TERM_MONTHS,
        "shipper_cost_share_pct": C.SHIPPER_COST_SHARE_PCT,
        "liability_cap_cents": C.LIABILITY_CAP_CENTS,
        "shipper_indemnity_default_pct": C.SHIPPER_INDEMNITY_DEFAULT_PCT,
        "free_time_hours": C.FREE_TIME_HOURS,
        "demurrage_base_rate_cents": C.DEMURRAGE_BASE_RATE_CENTS,
        "demurrage_escalated_rate_cents": C.DEMURRAGE_ESCALATED_RATE_CENTS,
        "storage_rate_per_car_month_cents": C.STORAGE_RATE_PER_CAR_MONTH_CENTS,
        "inspection_cadence_days": C.INSPECTION_CADENCE_DAYS,
        "removal_period_days": C.REMOVAL_PERIOD_DAYS,
        "removal_penalty_per_day_cents": C.REMOVAL_PENALTY_PER_DAY_CENTS,
        "service_days_of_week": list(C.SERVICE_DAYS_OF_WEEK),
        "max_switches_per_day": C.MAX_SWITCHES_PER_DAY,
    }
    defaults.update(overrides)
    return defaults


def create_amendment_payload(amendment_type, expected_agreement_version, **overrides):
    """Amendment proposal payload (PRD §3.2); caller pins the type's new_* field."""
    defaults = {
        "amendment_type": amendment_type,
        "expected_agreement_version": expected_agreement_version,
    }
    defaults.update(overrides)
    return defaults


def create_project_payload(agreement_id, **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "project_name": DEFAULTS["PROJECT_NAME"],
        "estimated_cost_cents": DEFAULTS["ESTIMATED_COST_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def submit_spec_payload(**overrides) -> dict:
    defaults = {
        "rail_weight_lb_per_yard": DEFAULTS["RAIL_WEIGHT_LB_PER_YARD"],
        "tie_material": DEFAULTS["TIE_MATERIAL"],
        "ballast_depth_inches": DEFAULTS["BALLAST_DEPTH_INCHES"],
    }
    defaults.update(overrides)
    return defaults


def create_segment_payload(agreement_id, **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "segment_name": DEFAULTS["SEGMENT_NAME"],
        "length_feet": DEFAULTS["SEGMENT_LENGTH_FEET"],
        "storage_capacity_cars": DEFAULTS["SEGMENT_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(agreement_id, segment_id, **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "segment_id": segment_id,
        "scheduled_date": DEFAULTS["PLACED_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_device_payload(segment_id, **overrides) -> dict:
    defaults = {
        "segment_id": segment_id,
        "device_type": DEFAULTS["DEVICE_TYPE"],
        "location_description": DEFAULTS["LOCATION_DESCRIPTION"],
    }
    defaults.update(overrides)
    return defaults


def create_service_order_payload(agreement_id, segment_id, **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "segment_id": segment_id,
        "order_type": "SWITCHING",
        "service_date": C.MONDAY_DATE,
        "start_hour": 8,
        "end_hour": 10,
    }
    defaults.update(overrides)
    return defaults


def create_car_dwell_payload(agreement_id, **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "car_mark": DEFAULTS["CAR_MARK"],
        "car_ownership": "RAILROAD",
        "placed_at": DEFAULTS["PLACED_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_storage_placement_payload(segment_id, **overrides) -> dict:
    defaults = {
        "segment_id": segment_id,
        "car_mark": "STGX101",
        "placed_date": DEFAULTS["PLACED_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_liability_claim_payload(agreement_id, **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "claimant_name": DEFAULTS["CLAIMANT_NAME"],
        "incident_date": DEFAULTS["INCIDENT_DATE"],
        "claim_amount_cents": DEFAULTS["CLAIM_AMOUNT_CENTS"],
    }
    defaults.update(overrides)
    return defaults
