"""Payload factories — one per entity, input fields only (PRD §3)."""


def create_dwelling_payload(**overrides) -> dict:
    defaults = {
        "street_address": "12 Elm St",
        "year_built": 1950,
        "owner_name": "Acme LLC",
        "jurisdiction": "COUNTY_A",
    }
    defaults.update(overrides)
    return defaults


def create_child_payload(primary_dwelling_id: str, **overrides) -> dict:
    defaults = {
        "full_name": "Test Child",
        "date_of_birth": "2022-03-01",
        "guardian_name": "Test Guardian",
        "primary_dwelling_id": primary_dwelling_id,
        "income_tier": "LOW",
    }
    defaults.update(overrides)
    return defaults


def create_blood_lead_test_payload(child_id: str, **overrides) -> dict:
    defaults = {
        "child_id": child_id,
        "bll_ug_dl": 22.0,
        "specimen_type": "VENOUS",
        "test_kind": "DIAGNOSTIC",
        "collected_at": "2026-05-02T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_case_payload(child_id: str, dwelling_id: str, qualifying_test_id: str, **overrides) -> dict:
    defaults = {
        "child_id": child_id,
        "dwelling_id": dwelling_id,
        "qualifying_test_id": qualifying_test_id,
    }
    defaults.update(overrides)
    return defaults


def create_inspector_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Ivy Inspector",
        "certification_id_number": "RA-001",
    }
    defaults.update(overrides)
    return defaults


def create_investigation_payload(case_id: str, dwelling_id: str, inspector_id: str, **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "dwelling_id": dwelling_id,
        "inspector_id": inspector_id,
        "scheduled_start": "2026-05-05T09:00:00Z",
        "scheduled_end": "2026-05-05T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_finding_payload(**overrides) -> dict:
    defaults = {
        "hazard_type": "PAINT",
        "location": "north window",
        "measurement_value": 120.0,
        "severity": "HIGH",
    }
    defaults.update(overrides)
    return defaults


def create_clearance_test_payload(order_id: str, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "floor_result_ug_ft2": 5.0,
        "sill_result_ug_ft2": 40.0,
        "trough_result_ug_ft2": 100.0,
    }
    defaults.update(overrides)
    return defaults


def create_relocation_unit_payload(**overrides) -> dict:
    defaults = {
        "address": "200 Motel Way",
        "bedroom_count": 2,
    }
    defaults.update(overrides)
    return defaults


def create_relocation_placement_payload(case_id: str, relocation_unit_id: str, **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "relocation_unit_id": relocation_unit_id,
        "start_date": "2026-06-01",
        "end_date": "2026-06-30",
        "occupant_count": 2,
    }
    defaults.update(overrides)
    return defaults


def create_contractor_payload(**overrides) -> dict:
    defaults = {
        "business_name": "LeadAway Inc",
        "rrp_certification_number": "RRP-77",
    }
    defaults.update(overrides)
    return defaults


def create_grant_fund_payload(**overrides) -> dict:
    defaults = {
        "fund_name": "HUD LHC 2026",
        "fiscal_year": 2026,
        "total_budget_cents": 5000000,
    }
    defaults.update(overrides)
    return defaults


def create_remediation_project_payload(order_id: str, contractor_id: str, grant_fund_id: str, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "contractor_id": contractor_id,
        "grant_fund_id": grant_fund_id,
    }
    defaults.update(overrides)
    return defaults
