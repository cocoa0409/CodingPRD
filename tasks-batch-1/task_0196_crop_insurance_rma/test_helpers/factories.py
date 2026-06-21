"""Payload factories — one per entity, input fields only.

Each factory supplies sensible defaults and accepts **overrides. Only fields the
PRD declares as client input appear here; computed / system fields are omitted.
"""

DEFAULTS = {
    "CROP_CODE": "CORN",
    "COUNTY_CODE": "19153",
    "CROP_YEAR": 2026,
    "PROJECTED_PRICE": 4.00,
    "BASE_PREMIUM_RATE": 0.085,
    "PP_COVERAGE_FACTOR": 0.60,
    "FINAL_PLANTING_DATE": "2026-05-31T00:00:00Z",
    "ACREAGE_REPORTING_DEADLINE": "2026-07-15T00:00:00Z",
    "APH_YIELD": 180,
    "COVERAGE_LEVEL": 0.75,
    "HARVEST_DATE": "2026-10-15T00:00:00Z",
}


def create_producer_payload(**overrides) -> dict:
    defaults = {"name": "Test Producer", "tax_id": "TX-TEST"}
    defaults.update(overrides)
    return defaults


def create_agent_payload(role_kind="SELLING", **overrides) -> dict:
    defaults = {
        "name": "Test Agent",
        "license_number": "LIC-TEST",
        "role_kind": role_kind,
    }
    defaults.update(overrides)
    return defaults


def create_commodity_program_payload(**overrides) -> dict:
    defaults = {
        "crop_code": DEFAULTS["CROP_CODE"],
        "county_code": DEFAULTS["COUNTY_CODE"],
        "crop_year": DEFAULTS["CROP_YEAR"],
        "projected_price": DEFAULTS["PROJECTED_PRICE"],
        "base_premium_rate": DEFAULTS["BASE_PREMIUM_RATE"],
        "pp_coverage_factor": DEFAULTS["PP_COVERAGE_FACTOR"],
        "final_planting_date": DEFAULTS["FINAL_PLANTING_DATE"],
        "acreage_reporting_deadline": DEFAULTS["ACREAGE_REPORTING_DEADLINE"],
    }
    defaults.update(overrides)
    return defaults


def create_policy_payload(producer_id: str, agent_id: str, **overrides) -> dict:
    defaults = {
        "producer_id": producer_id,
        "agent_id": agent_id,
        "crop_year": DEFAULTS["CROP_YEAR"],
    }
    defaults.update(overrides)
    return defaults


def create_coverage_election_payload(policy_id: str, commodity_program_id: str,
                                     plan_type="YP", **overrides) -> dict:
    defaults = {
        "policy_id": policy_id,
        "commodity_program_id": commodity_program_id,
        "plan_type": plan_type,
        "aph_yield": DEFAULTS["APH_YIELD"],
        "coverage_level": DEFAULTS["COVERAGE_LEVEL"],
    }
    defaults.update(overrides)
    return defaults


def create_unit_payload(coverage_election_id: str, unit_number="0001-0001",
                        acres=100, share=1, **overrides) -> dict:
    defaults = {
        "coverage_election_id": coverage_election_id,
        "unit_number": unit_number,
        "acres": acres,
        "share": share,
    }
    defaults.update(overrides)
    return defaults


def create_acreage_report_payload(unit_id: str, expected_unit_version,
                                  planted_acres=100, prevented_acres=0,
                                  planting_date="2026-05-10T00:00:00Z",
                                  **overrides) -> dict:
    defaults = {
        "unit_id": unit_id,
        "planted_acres": planted_acres,
        "prevented_acres": prevented_acres,
        "planting_date": planting_date,
        "expected_unit_version": expected_unit_version,
    }
    defaults.update(overrides)
    return defaults


def create_loss_claim_payload(unit_id: str, assigned_adjuster_id: str,
                              production_to_count_bu=10000, **overrides) -> dict:
    defaults = {
        "unit_id": unit_id,
        "harvest_date": DEFAULTS["HARVEST_DATE"],
        "production_to_count_bu": production_to_count_bu,
        "assigned_adjuster_id": assigned_adjuster_id,
    }
    defaults.update(overrides)
    return defaults


def create_pp_claim_payload(unit_id: str, claimed_prevented_acres,
                            cause="EXCESS_MOISTURE", **overrides) -> dict:
    defaults = {
        "unit_id": unit_id,
        "claimed_prevented_acres": claimed_prevented_acres,
        "cause": cause,
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
