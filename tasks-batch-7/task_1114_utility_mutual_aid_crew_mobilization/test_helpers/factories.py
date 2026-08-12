"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "HOST_NAME": "Host Power",
    "HOST_CODE": "HST",
    "HOST_REGION": "Coastal",
    "RSP_NAME": "Responder Electric",
    "RSP_CODE": "RSP",
    "RSP_REGION": "Inland",
    "EVENT_NAME": "Hurricane Idalia",
    "EVENT_TYPE": "STORM",
    "DECLARED_START": "2026-05-02",
    "PREMIUM_START": "2026-05-02",
    "PREMIUM_END": "2026-05-20",
    "MOBILIZATION_DEADLINE": "2026-05-10T18:00:00Z",
    "EFFECTIVE_START": "2026-05-01",
    "EFFECTIVE_END": "2026-05-31",
    "HOURLY_RATE_CENTS": 12000,
    "STORM_PREMIUM_BPS": 1000,
    "PER_DIEM_RATE_CENTS": 8950,
    "PER_DIEM_METHOD": "STANDARD",
    "FEE_BPS": 800,
    "EARLIEST_START": "2026-05-03",
    "LATEST_END": "2026-05-15",
    "CREW_TYPE": "LINE",
    "HOME_BASE": "Depot 7",
    "HOTEL_NAME": "Storm Inn",
    "BLOCK_CODE": "BLK-1",
    "TOTAL_ROOMS": 2,
    "NIGHTLY_RATE_CENTS": 15000,
    "CHECK_IN": "2026-05-03",
    "CHECK_OUT": "2026-05-08",
    "WORK_DATE": "2026-05-04",
    "CLAIM_DATE": "2026-05-03",
    "CONDUCTOR_REF": "OFF-1",
    "SUPERVISOR_REF": "SUP-1",
    "CERTIFIER_REF": "HC-1",
    "APPROVER_REF": "FIN-9",
    "RULES_VERSION": "HR-2026.1",
    "PERIOD_START": "2026-05-01",
    "PERIOD_END": "2026-05-31",
}


def create_utility_company_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["HOST_NAME"],
        "company_code": DEFAULTS["HOST_CODE"],
        "role_capability": "BOTH",
        "home_region": DEFAULTS["HOST_REGION"],
    }
    defaults.update(overrides)
    return defaults


def create_event_payload(**overrides) -> dict:
    defaults = {
        "event_name": DEFAULTS["EVENT_NAME"],
        "host_utility_id": None,  # caller must supply
        "event_type": DEFAULTS["EVENT_TYPE"],
        "declared_start_date": DEFAULTS["DECLARED_START"],
        "premium_window_start": DEFAULTS["PREMIUM_START"],
        "premium_window_end": DEFAULTS["PREMIUM_END"],
        "mobilization_deadline": DEFAULTS["MOBILIZATION_DEADLINE"],
    }
    defaults.update(overrides)
    return defaults


def create_billing_rate_schedule_payload(**overrides) -> dict:
    defaults = {
        "event_id": None,  # caller must supply
        "effective_start_date": DEFAULTS["EFFECTIVE_START"],
        "effective_end_date": DEFAULTS["EFFECTIVE_END"],
        "rate_lines": [{"crew_type": "LINE", "hourly_rate_cents": DEFAULTS["HOURLY_RATE_CENTS"]}],
        "storm_premium_bps": DEFAULTS["STORM_PREMIUM_BPS"],
        "per_diem_rate_cents": DEFAULTS["PER_DIEM_RATE_CENTS"],
        "per_diem_method": DEFAULTS["PER_DIEM_METHOD"],
        "mobilization_fee_tiers": [{"min_subtotal_cents": 0, "fee_bps": DEFAULTS["FEE_BPS"]}],
    }
    defaults.update(overrides)
    return defaults


def create_assistance_request_payload(**overrides) -> dict:
    defaults = {
        "event_id": None,  # caller must supply
        "responding_utility_id": None,  # caller must supply
        "requested_crews": [{"crew_type": "LINE", "count": 2}],
        "required_minimum_crews": 1,
        "earliest_start_date": DEFAULTS["EARLIEST_START"],
        "latest_end_date": DEFAULTS["LATEST_END"],
    }
    defaults.update(overrides)
    return defaults


def create_crew_payload(**overrides) -> dict:
    defaults = {
        "request_id": None,  # caller must supply
        "crew_type": DEFAULTS["CREW_TYPE"],
        "home_base": DEFAULTS["HOME_BASE"],
        "roster": [{"member_ref": "M1", "member_role": "foreman"}],
        "equipment_units": [],
    }
    defaults.update(overrides)
    return defaults


def create_safety_briefing_payload(**overrides) -> dict:
    defaults = {
        "crew_id": None,  # caller must supply
        "event_id": None,  # caller must supply
        "conductor_operator_ref": DEFAULTS["CONDUCTOR_REF"],
        "host_rules_version": DEFAULTS["RULES_VERSION"],
        "topics": ["grounding"],
    }
    defaults.update(overrides)
    return defaults


def create_timesheet_payload(**overrides) -> dict:
    defaults = {
        "crew_id": None,  # caller must supply
        "work_date": DEFAULTS["WORK_DATE"],
        "day_classification": "WORK",
        "reported_work_minutes": 480,
    }
    defaults.update(overrides)
    return defaults


def create_lodging_block_payload(**overrides) -> dict:
    defaults = {
        "event_id": None,  # caller must supply
        "hotel_name": DEFAULTS["HOTEL_NAME"],
        "block_code": DEFAULTS["BLOCK_CODE"],
        "total_rooms": DEFAULTS["TOTAL_ROOMS"],
        "nightly_rate_cents": DEFAULTS["NIGHTLY_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_lodging_assignment_payload(**overrides) -> dict:
    defaults = {
        "block_id": None,  # caller must supply
        "crew_id": None,  # caller must supply
        "room_count": 1,
        "check_in_date": DEFAULTS["CHECK_IN"],
        "check_out_date": DEFAULTS["CHECK_OUT"],
    }
    defaults.update(overrides)
    return defaults


def create_per_diem_claim_payload(**overrides) -> dict:
    defaults = {
        "crew_id": None,  # caller must supply
        "claim_date": DEFAULTS["CLAIM_DATE"],
        "member_count": 1,
        "meals_provided_count": 0,
        "day_factor_type": "TRAVEL",
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(**overrides) -> dict:
    defaults = {
        "request_id": None,  # caller must supply
        "rate_schedule_id": None,  # caller must supply
        "billing_period_start": DEFAULTS["PERIOD_START"],
        "billing_period_end": DEFAULTS["PERIOD_END"],
    }
    defaults.update(overrides)
    return defaults


def create_after_action_report_payload(**overrides) -> dict:
    defaults = {
        "event_id": None,  # caller must supply
        "summary": "Idalia response",
    }
    defaults.update(overrides)
    return defaults
