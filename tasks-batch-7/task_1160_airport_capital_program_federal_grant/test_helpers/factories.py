"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
import itertools

# loc_id must be exactly 3 uppercase A-Z letters and unique across sponsors (PRD §3.1).
_loc_id_counter = itertools.count(0)


def _next_loc_id() -> str:
    n = next(_loc_id_counter)
    # Spread over A-Z letter triples: ZAA, ZAB, ... (more than enough for one test run)
    return "Z" + chr(ord("A") + (n // 26) % 26) + chr(ord("A") + n % 26)


DEFAULTS = {
    "SPONSOR_NAME": "Sponsor A",
    "AIRPORT_SIZE_TIER": "SMALL_HUB",
    "NPE_ENTITLEMENT_TOTAL": 5_000_000,
    "FACILITY_NAME": "Runway 09/27",
    "FACILITY_TYPE": "RUNWAY",
    "FISCAL_YEAR": 2027,
    "PROJECT_TITLE": "Runway rehab",
    "PROJECT_TYPE": "PRESERVATION",
    "ESTIMATED_COST": 1_000_000,
    "CONTRACTOR_NAME": "BuildCo",
    "AWARDED_VALUE": 500_000,
    "DBE_GOAL_PCT": 12.50,
    "RETAINAGE_PCT": 0.10,
    "INVOICE_NUMBER": "INV-1",
    "INVOICE_PERIOD": "2026-05",
    "GROSS_AMOUNT": 100_000,
    "ASSET_DESCRIPTION": "Sweeper",
    "ACQUISITION_FEDERAL_SHARE": 100_000,
    "USEFUL_LIFE_YEARS": 10,
    "IN_SERVICE_DATE": "2020-05-01T00:00:00Z",
    "FINDING_CODE": "MISSING_DOCUMENTATION",
    "FINDING_SEVERITY": "MEDIUM",
}


def create_sponsor_payload(**overrides) -> dict:
    defaults = {
        "sponsor_name": DEFAULTS["SPONSOR_NAME"],
        "loc_id": _next_loc_id(),
        "airport_size_tier": DEFAULTS["AIRPORT_SIZE_TIER"],
        "npe_entitlement_total": DEFAULTS["NPE_ENTITLEMENT_TOTAL"],
    }
    defaults.update(overrides)
    return defaults


def create_facility_payload(sponsor_id, **overrides) -> dict:
    defaults = {
        "sponsor_id": sponsor_id,
        "facility_name": DEFAULTS["FACILITY_NAME"],
        "facility_type": DEFAULTS["FACILITY_TYPE"],
    }
    defaults.update(overrides)
    return defaults


def create_program_payload(sponsor_id, **overrides) -> dict:
    defaults = {
        "sponsor_id": sponsor_id,
        "fiscal_year": DEFAULTS["FISCAL_YEAR"],
    }
    defaults.update(overrides)
    return defaults


def create_project_payload(program_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "title": DEFAULTS["PROJECT_TITLE"],
        "project_type": DEFAULTS["PROJECT_TYPE"],
        "estimated_cost": DEFAULTS["ESTIMATED_COST"],
        "safety_score": 20,
        "capacity_score": 10,
        "preservation_score": 10,
        "security_score": 10,
        "environmental_score": 10,
        "runway_safety_noncompliant": False,
        "multi_airport_system": False,
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(sponsor_id, program_id, project_ids, **overrides) -> dict:
    defaults = {
        "sponsor_id": sponsor_id,
        "program_id": program_id,
        "project_ids": list(project_ids),
    }
    defaults.update(overrides)
    return defaults


def create_amendment_payload(added_scope_cost, reason, expected_grant_version,
                             **overrides) -> dict:
    defaults = {
        "added_scope_cost": added_scope_cost,
        "reason": reason,
        "expected_grant_version": expected_grant_version,
    }
    defaults.update(overrides)
    return defaults


def create_contractor_payload(sponsor_id, **overrides) -> dict:
    defaults = {
        "sponsor_id": sponsor_id,
        "contractor_name": DEFAULTS["CONTRACTOR_NAME"],
        "dbe_certified": False,
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(grant_id, cip_project_id, contractor_id, **overrides) -> dict:
    defaults = {
        "grant_id": grant_id,
        "cip_project_id": cip_project_id,
        "contractor_id": contractor_id,
        "awarded_value": DEFAULTS["AWARDED_VALUE"],
        "dbe_goal_pct": DEFAULTS["DBE_GOAL_PCT"],
        "retainage_pct": DEFAULTS["RETAINAGE_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_dbe_report_payload(contract_id, reporting_period, dbe_paid_amount,
                              total_paid_amount, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "reporting_period": reporting_period,
        "dbe_paid_amount": dbe_paid_amount,
        "total_paid_amount": total_paid_amount,
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(contract_id, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "invoice_number": DEFAULTS["INVOICE_NUMBER"],
        "period": DEFAULTS["INVOICE_PERIOD"],
        "gross_amount": DEFAULTS["GROSS_AMOUNT"],
    }
    defaults.update(overrides)
    return defaults


def create_drawdown_payload(grant_id, invoice_ids, **overrides) -> dict:
    defaults = {
        "grant_id": grant_id,
        "invoice_ids": list(invoice_ids),
    }
    defaults.update(overrides)
    return defaults


def create_audit_finding_payload(grant_id, **overrides) -> dict:
    defaults = {
        "grant_id": grant_id,
        "finding_code": DEFAULTS["FINDING_CODE"],
        "severity": DEFAULTS["FINDING_SEVERITY"],
        "description": "missing payroll records",
    }
    defaults.update(overrides)
    return defaults


def create_grant_asset_payload(grant_id, **overrides) -> dict:
    defaults = {
        "grant_id": grant_id,
        "asset_kind": "EQUIPMENT",
        "description": DEFAULTS["ASSET_DESCRIPTION"],
        "acquisition_federal_share": DEFAULTS["ACQUISITION_FEDERAL_SHARE"],
        "useful_life_years": DEFAULTS["USEFUL_LIFE_YEARS"],
        "in_service_date": DEFAULTS["IN_SERVICE_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_phase_payload(grant_id, cip_project_id, facility_id, contractor_id,
                         **overrides) -> dict:
    defaults = {
        "grant_id": grant_id,
        "cip_project_id": cip_project_id,
        "facility_id": facility_id,
        "contractor_id": contractor_id,
        "closure_type": "FULL_CLOSURE",
        "start_utc": "2026-06-01T00:00:00Z",
        "end_utc": "2026-06-03T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
