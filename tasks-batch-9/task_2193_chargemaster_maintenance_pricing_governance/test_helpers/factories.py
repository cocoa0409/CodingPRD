"""Payload factories, one per entity, carrying only client-supplied input fields."""
import itertools

_seq = itertools.count(1)
_rev_code_seq = itertools.count(1000)


def unique_suffix() -> str:
    return f"{next(_seq):06d}"


def unique_revenue_code_value() -> str:
    """A four-digit UB-04 revenue-code string, unique within one test run."""
    return f"{next(_rev_code_seq) % 10000:04d}"


def create_facility_payload(**overrides) -> dict:
    payload = {
        "name": f"Test Hospital {unique_suffix()}",
        "cms_certification_number": f"CCN{unique_suffix()}",
    }
    payload.update(overrides)
    return payload


def create_revenue_code_payload(**overrides) -> dict:
    payload = {
        "code": unique_revenue_code_value(),
        "description": "General Classification",
        "requires_hcpcs": False,
        "allowed_code_types": ["CPT", "HCPCS", "REV_ONLY", "CDM_INTERNAL"],
        "pricing_class": "PROCEDURE",
    }
    payload.update(overrides)
    return payload


def create_department_payload(facility_id: str, manager_user_id: str, **overrides) -> dict:
    payload = {
        "facility_id": facility_id,
        "name": f"Cardiac Cath Lab {unique_suffix()}",
        "cost_center_code": f"CC{unique_suffix()}",
        "manager_user_id": manager_user_id,
    }
    payload.update(overrides)
    return payload


def create_price_rule_payload(facility_id: str, revenue_code_id: str, **overrides) -> dict:
    payload = {
        "facility_id": facility_id,
        "revenue_code_id": revenue_code_id,
        "pricing_method": "COST_PLUS_MARKUP",
        "effective_from": "2026-08-01T00:00:00Z",
        "effective_to": None,
    }
    payload.update(overrides)
    return payload


def create_payer_contract_payload(facility_id: str, **overrides) -> dict:
    payload = {
        "facility_id": facility_id,
        "payer_code": f"BCBS_{unique_suffix()}",
        "product_line": "COMMERCIAL",
        "reimbursement_method": "PERCENT_OF_CHARGE",
        "percent_of_charge_bp": 5000,
        "term_start_date": "2026-01-01T00:00:00Z",
        "term_end_date": "2026-12-31T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_charge_item_payload(
    facility_id: str, department_id: str, revenue_code_id: str, **overrides
) -> dict:
    payload = {
        "facility_id": facility_id,
        "department_id": department_id,
        "revenue_code_id": revenue_code_id,
        "cdm_number": f"CDM{unique_suffix()}",
        "description": "Cardiac Catheterization Left Heart",
        "code_type": "CDM_INTERNAL",
        "code_value": None,
        "cost_basis_cents": 10000,
        "medicare_rate_cents": 8000,
        "market_p75_cents": 100000,
        "effective_from": "2026-08-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_change_request_payload(
    department_id: str, charge_item_id: str, request_type: str, **overrides
) -> dict:
    payload = {
        "department_id": department_id,
        "charge_item_id": charge_item_id,
        "request_type": request_type,
        "justification": "Cost basis moved with the new supply contract.",
    }
    payload.update(overrides)
    return payload


def create_code_update_cycle_payload(facility_id: str, **overrides) -> dict:
    payload = {
        "facility_id": facility_id,
        "cycle_year": 2027,
        "code_set": "CPT",
    }
    payload.update(overrides)
    return payload


def create_code_update_entry_payload(action: str, **overrides) -> dict:
    payload = {
        "action": action,
        "old_code_value": None if action == "ADD" else "99213",
        "new_code_value": None if action == "DELETE" else "99214",
    }
    payload.update(overrides)
    return payload


def create_charge_capture_batch_payload(
    facility_id: str, department_id: str, **overrides
) -> dict:
    payload = {
        "facility_id": facility_id,
        "department_id": department_id,
        "window_start_date": "2026-07-01T00:00:00Z",
        "window_end_date": "2026-07-31T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_captured_charge_payload(cdm_number: str, **overrides) -> dict:
    payload = {
        "submitted_cdm_number": cdm_number,
        "encounter_id": f"ENC{unique_suffix()}",
        "payer_code": "BCBS_STATE",
        "service_datetime": "2026-07-10T09:00:00Z",
        "quantity": 1,
        "posted_charge_cents": 32000,
    }
    payload.update(overrides)
    return payload


def create_price_change_analysis_payload(change_request_id: str, variant: str, **overrides) -> dict:
    payload = {
        "change_request_id": change_request_id,
        "variant": variant,
    }
    payload.update(overrides)
    return payload


def create_transparency_file_payload(
    facility_id: str, expected_facility_version: int, **overrides
) -> dict:
    payload = {
        "facility_id": facility_id,
        "file_format": "JSON",
        "expected_facility_version": expected_facility_version,
    }
    payload.update(overrides)
    return payload
