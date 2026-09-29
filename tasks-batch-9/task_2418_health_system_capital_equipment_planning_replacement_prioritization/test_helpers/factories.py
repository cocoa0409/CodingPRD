"""Payload factories — one per write surface, input fields only.

Defaults describe the canonical estate used across the suite: facility NRH in
region NORTH, a CT department, a CT scanner installed 2020-08-02 with an
eight-year expected life and OEM support running to 2029-06-01, and a 2027
plan-year cycle holding 500000000 cents.
"""

DEFAULTS = {
    "FACILITY_NAME": "North Regional Hospital",
    "FACILITY_CODE": "NRH",
    "FACILITY_REGION": "NORTH",
    "DEPARTMENT_NAME": "Diagnostic Imaging CT",
    "MODALITY": "CT",
    "ASSET_MODEL": "Aquilon CT-8",
    "ASSET_INSTALL_DATE": "2020-08-02T00:00:00Z",
    "ASSET_EXPECTED_LIFE_YEARS": 8,
    "ASSET_ACQUISITION_COST_CENTS": 100000000,
    "ASSET_OEM_SUPPORT_END_DATE": "2029-06-01T00:00:00Z",
    "PLAN_YEAR": 2027,
    "PLAN_YEAR_START": "2027-01-01T00:00:00Z",
    "TOTAL_CAPITAL_CENTS": 500000000,
    "JUSTIFICATION": "CT replacement, ageing detector array.",
    "CURRENT_ANNUAL_VOLUME": 1000,
    "PROJECTED_ANNUAL_VOLUME": 2000,
    "ESTIMATED_CAPITAL_CENTS": 100000000,
    "ANNUAL_SERVICE_CONTRACT_CENTS": 10000000,
    "DISPOSABLE_UNIT_CENTS": 500,
    "GPO_CONTRACT_CODE": "GPO-1",
    "VENDOR_NAME": "Aquilon Medical",
    "GPO_EXPIRES_ON": "2027-12-31T00:00:00Z",
    "QUOTE_LIST_PRICE_CENTS": 100000000,
    "QUOTE_SERVICE_ESCALATION_PCT": 0.04,
    "QUOTE_VALID_UNTIL": "2026-12-31T00:00:00Z",
    "DOWNTIME_START": "2026-10-05T00:00:00Z",
    "DOWNTIME_END": "2026-10-07T00:00:00Z",
}


def set_clock_payload(now: str, **overrides) -> dict:
    payload = {"now": now}
    payload.update(overrides)
    return payload


def create_facility_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["FACILITY_NAME"],
        "code": DEFAULTS["FACILITY_CODE"],
        "region": DEFAULTS["FACILITY_REGION"],
        "max_concurrent_construction": 1,
    }
    payload.update(overrides)
    return payload


def create_department_payload(facility_id: str, **overrides) -> dict:
    payload = {
        "facility_id": facility_id,
        "name": DEFAULTS["DEPARTMENT_NAME"],
        "modality_scope": DEFAULTS["MODALITY"],
    }
    payload.update(overrides)
    return payload


def create_asset_payload(facility_id: str, department_id: str, **overrides) -> dict:
    payload = {
        "facility_id": facility_id,
        "department_id": department_id,
        "modality": DEFAULTS["MODALITY"],
        "model_name": DEFAULTS["ASSET_MODEL"],
        "install_date": DEFAULTS["ASSET_INSTALL_DATE"],
        "expected_life_years": DEFAULTS["ASSET_EXPECTED_LIFE_YEARS"],
        "acquisition_cost_cents": DEFAULTS["ASSET_ACQUISITION_COST_CENTS"],
        "oem_support_end_date": DEFAULTS["ASSET_OEM_SUPPORT_END_DATE"],
    }
    payload.update(overrides)
    return payload


def create_cycle_payload(**overrides) -> dict:
    payload = {
        "plan_year": DEFAULTS["PLAN_YEAR"],
        "plan_year_start": DEFAULTS["PLAN_YEAR_START"],
        "total_capital_cents": DEFAULTS["TOTAL_CAPITAL_CENTS"],
        "contingency_pct": 0.00,
        "facility_contingency_pct": 0.00,
    }
    payload.update(overrides)
    return payload


def create_service_event_payload(event_date: str, category: str, **overrides) -> dict:
    payload = {"event_date": event_date, "category": category}
    payload.update(overrides)
    return payload


def create_request_payload(cycle_id: str, department_id: str, asset_id: str, **overrides) -> dict:
    payload = {
        "cycle_id": cycle_id,
        "department_id": department_id,
        "asset_id": asset_id,
        "clinical_justification": DEFAULTS["JUSTIFICATION"],
        "current_annual_volume": DEFAULTS["CURRENT_ANNUAL_VOLUME"],
        "projected_annual_volume": DEFAULTS["PROJECTED_ANNUAL_VOLUME"],
        "estimated_capital_cents": DEFAULTS["ESTIMATED_CAPITAL_CENTS"],
        "annual_service_contract_cents": DEFAULTS["ANNUAL_SERVICE_CONTRACT_CENTS"],
        "disposable_unit_cents": DEFAULTS["DISPOSABLE_UNIT_CENTS"],
    }
    payload.update(overrides)
    return payload


def screen_payload(decision: str, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def allocate_payload(allocation_method: str, expected_cycle_version: int, **overrides) -> dict:
    payload = {
        "allocation_method": allocation_method,
        "expected_cycle_version": expected_cycle_version,
    }
    payload.update(overrides)
    return payload


def create_member_payload(seat: str, voting_weight: int, **overrides) -> dict:
    payload = {
        "full_name": f"Committee {seat.title()}",
        "seat": seat,
        "voting_weight": voting_weight,
    }
    payload.update(overrides)
    return payload


def vote_payload(vote: str, expected_request_version: int, **overrides) -> dict:
    payload = {"vote": vote, "expected_request_version": expected_request_version}
    payload.update(overrides)
    return payload


def create_gpo_contract_payload(**overrides) -> dict:
    payload = {
        "contract_code": DEFAULTS["GPO_CONTRACT_CODE"],
        "vendor_name": DEFAULTS["VENDOR_NAME"],
        "small_tier_pct": 0.05,
        "mid_tier_pct": 0.12,
        "large_tier_pct": 0.18,
        "tier_mid_floor_cents": 100000000,
        "tier_large_floor_cents": 240000000,
        "multi_unit_addendum_pct": 0.03,
        "trade_in_cap_pct": 0.10,
        "expires_on": DEFAULTS["GPO_EXPIRES_ON"],
    }
    payload.update(overrides)
    return payload


def create_quote_payload(gpo_contract_id: str, **overrides) -> dict:
    payload = {
        "gpo_contract_id": gpo_contract_id,
        "vendor_name": DEFAULTS["VENDOR_NAME"],
        "list_price_cents": DEFAULTS["QUOTE_LIST_PRICE_CENTS"],
        "service_escalation_pct": DEFAULTS["QUOTE_SERVICE_ESCALATION_PCT"],
        "valid_until": DEFAULTS["QUOTE_VALID_UNTIL"],
    }
    payload.update(overrides)
    return payload


def create_project_payload(**overrides) -> dict:
    payload = {
        "downtime_start": DEFAULTS["DOWNTIME_START"],
        "downtime_end": DEFAULTS["DOWNTIME_END"],
    }
    payload.update(overrides)
    return payload


def create_audit_payload(
    installation_project_id: str, audit_window_start: str, audit_window_end: str, **overrides
) -> dict:
    payload = {
        "installation_project_id": installation_project_id,
        "audit_window_start": audit_window_start,
        "audit_window_end": audit_window_end,
    }
    payload.update(overrides)
    return payload


def collect_audit_payload(actual_annual_volume: int, actual_annual_opex_cents: int, **overrides) -> dict:
    payload = {
        "actual_annual_volume": actual_annual_volume,
        "actual_annual_opex_cents": actual_annual_opex_cents,
    }
    payload.update(overrides)
    return payload


def decommission_payload(disposition: str, **overrides) -> dict:
    payload = {"disposition": disposition}
    payload.update(overrides)
    return payload
