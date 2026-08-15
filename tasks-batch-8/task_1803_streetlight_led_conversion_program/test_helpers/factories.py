"""Payload factories — one per entity, input fields only."""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


def create_program_payload(**overrides) -> dict:
    defaults = {
        "program_name": f"LED-{_seq()}",
        "program_budget_cents": TEST_DEFAULTS["PROGRAM_BUDGET_CENTS"],
        "fy_rebate_cap_cents": TEST_DEFAULTS["FY_REBATE_CAP_CENTS"],
        "rebate_cents_per_kwh": TEST_DEFAULTS["REBATE_CENTS_PER_KWH"],
    }
    defaults.update(overrides)
    return defaults


def create_district_payload(program_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "district_name": f"D{_seq()}",
        "zone": "RESIDENTIAL",
    }
    defaults.update(overrides)
    return defaults


def create_pole_payload(district_id, **overrides) -> dict:
    defaults = {
        "district_id": district_id,
        "pole_number": f"P-{_seq():04d}",
        "ownership_type": "UTILITY_OWNED",
        "fixture_class": "COBRA_HEAD",
        "nameplate_wattage": TEST_DEFAULTS["NAMEPLATE_WATTAGE"],
    }
    defaults.update(overrides)
    return defaults


def submit_audit_payload(expected_pole_version, **overrides) -> dict:
    defaults = {
        "audited_wattage": TEST_DEFAULTS["NAMEPLATE_WATTAGE"],
        "expected_pole_version": expected_pole_version,
    }
    defaults.update(overrides)
    return defaults


def resubmit_audit_payload(**overrides) -> dict:
    defaults = {
        "audited_wattage": 240,
        "auditor_notes": "re-read meter",
    }
    defaults.update(overrides)
    return defaults


def create_crew_payload(program_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "crew_name": f"Crew-{_seq()}",
        "base_stops_per_shift": TEST_DEFAULTS["BASE_STOPS_PER_SHIFT"],
        "hourly_rate_cents": TEST_DEFAULTS["HOURLY_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_route_payload(district_id, crew_id, **overrides) -> dict:
    defaults = {
        "district_id": district_id,
        "crew_id": crew_id,
        "window_start_date": "2026-08-03",
        "window_end_date": "2026-08-03",
        "traffic_control_required": False,
    }
    defaults.update(overrides)
    return defaults


def add_stop_payload(pole_id, sequence_number, **overrides) -> dict:
    defaults = {
        "pole_id": pole_id,
        "sequence_number": sequence_number,
        "difficulty_class": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


def dispatch_work_order_payload(**overrides) -> dict:
    defaults = {
        "new_fixture_wattage": TEST_DEFAULTS["LED_WATTAGE"],
        "new_cct_kelvin": 2700,
        "shielding": "FULL_CUTOFF",
    }
    defaults.update(overrides)
    return defaults


def create_rate_schedule_payload(program_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "ownership_class": "MUNICIPAL",
        "effective_from": "2026-01-01",
        "tier_rates": {"T1": 700, "T2": 1100, "T3": 1500, "T4": 2000, "T5": 2600},
    }
    defaults.update(overrides)
    return defaults


def create_tariff_account_payload(district_id, **overrides) -> dict:
    defaults = {
        "district_id": district_id,
        "account_number": f"AC-{_seq()}",
        "ownership_class": "MUNICIPAL",
    }
    defaults.update(overrides)
    return defaults


def create_outage_ticket_payload(pole_id, **overrides) -> dict:
    defaults = {
        "pole_id": pole_id,
        "description": f"outage {_seq()}",
        "hazard_flag": False,
    }
    defaults.update(overrides)
    return defaults


def dispatch_ticket_payload(crew_id) -> dict:
    return {"crew_id": crew_id}


def resolve_ticket_payload(**overrides) -> dict:
    defaults = {"resolution_code": "LIGHT_OUT_FIXED"}
    defaults.update(overrides)
    return defaults


def create_salvage_batch_payload(program_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "batch_label": f"BATCH-{_seq()}",
    }
    defaults.update(overrides)
    return defaults


def add_salvage_item_payload(salvage_item_id, **overrides) -> dict:
    defaults = {
        "salvage_item_id": salvage_item_id,
        "weight_lbs": 10.0,
        "mercury_flag": False,
    }
    defaults.update(overrides)
    return defaults


def seal_salvage_batch_payload(**overrides) -> dict:
    defaults = {"contaminated_flag": False}
    defaults.update(overrides)
    return defaults


def create_savings_report_payload(program_id, expected_program_version, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "period": "2026-08",
        "method": "METERED_ACTUAL",
        "fiscal_year_label": "FY2026",
        "expected_program_version": expected_program_version,
    }
    defaults.update(overrides)
    return defaults


def create_compliance_exception_payload(pole_id, **overrides) -> dict:
    defaults = {
        "pole_id": pole_id,
        "exception_kind": "CCT_WAIVER",
        "requested_cct_kelvin": 5000,
        "valid_until": "2027-01-01",
    }
    defaults.update(overrides)
    return defaults
