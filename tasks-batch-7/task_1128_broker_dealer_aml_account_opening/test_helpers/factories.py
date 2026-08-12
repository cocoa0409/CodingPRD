"""Payload factories — one per creatable resource, input fields only (PRD §3)."""
import uuid


def _tag() -> str:
    return uuid.uuid4().hex[:8].upper()


def create_rep_payload(**overrides) -> dict:
    defaults = {"full_name": f"Rep {_tag()}", "crd_number": f"CRD-{_tag()}"}
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "customer_type": "INDIVIDUAL",
        "full_name": f"Customer {_tag()}",
        "tax_id": f"TIN-{_tag()}",
        "country_risk_tier": "LOW",
        "is_pep": False,
        "date_of_birth": "1980-01-01",
    }
    defaults.update(overrides)
    return defaults


def submit_document_payload(**overrides) -> dict:
    defaults = {
        "doc_type": "GOVERNMENT_ID",
        "document_number": f"DOC-{_tag()}",
        "expiry_date": "2030-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_certification_payload(**overrides) -> dict:
    defaults: dict = {}
    defaults.update(overrides)
    return defaults


def add_owner_payload(**overrides) -> dict:
    """Owner payload; pass None for an optional KYC field to omit it from the body
    (tax_id/date_of_birth/address are optional at entry per PRD §3.2)."""
    defaults = {
        "full_name": f"Owner {_tag()}",
        "ownership_pct": 100.00,
        "is_control_person": True,
        "is_entity_owner": False,
        "tax_id": f"TIN-OWN-{_tag()}",
        "date_of_birth": "1965-01-01",
        "address": "1 Main St",
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_account_payload(customer_id, **overrides) -> dict:
    defaults = {"customer_id": customer_id, "product_set": ["CASH"]}
    defaults.update(overrides)
    return defaults


def create_edd_review_payload(**overrides) -> dict:
    defaults = {
        "period_start": "2026-04-01",
        "period_end": "2026-05-01",
        "trigger_reason": "periodic review",
    }
    defaults.update(overrides)
    return defaults


def post_transaction_payload(**overrides) -> dict:
    defaults = {"txn_type": "WIRE_OUT", "amount": 100.00}
    defaults.update(overrides)
    return defaults


def create_rule_payload(**overrides) -> dict:
    # min_transaction_count mirrors the PRD §3.5 server-side default of 1;
    # structuring-style callers pass 3 explicitly.
    defaults = {
        "rule_code": "STRUCTURING",
        "threshold_amount": 10000.00,
        "window_days": 2,
        "min_transaction_count": 1,
    }
    defaults.update(overrides)
    return defaults


def create_case_payload(account_id, expected_account_version, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "expected_account_version": expected_account_version,
    }
    defaults.update(overrides)
    return defaults


def create_sar_filing_payload(case_id, **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "narrative": "Suspicious activity narrative",
        "activity_start": "2026-05-01",
        "activity_end": "2026-05-01",
    }
    defaults.update(overrides)
    return defaults


def create_fincen_request_payload(subjects=None, **overrides) -> dict:
    defaults = {
        "request_reference": f"FIN-{_tag()}",
        "subjects": subjects if subjects is not None else [
            {"name": "Subject", "subject_type": "INDIVIDUAL"}
        ],
    }
    defaults.update(overrides)
    return defaults


def create_deposit_payload(**overrides) -> dict:
    defaults = {
        "certificate_number": f"CN-{_tag()}",
        "cusip": f"CU{_tag()}",
        "security_name": f"Security {_tag()}",
        "quantity": 10,
        "unit_price": 40.00,
    }
    defaults.update(overrides)
    return defaults


def create_lost_stolen_payload(**overrides) -> dict:
    tag = _tag()
    defaults = {"certificate_number": f"CN-{tag}", "cusip": f"CU{tag}"}
    defaults.update(overrides)
    return defaults


def create_engagement_payload(**overrides) -> dict:
    defaults = {
        "scope_unit": "AML_PROGRAM",
        "start_date": "2026-04-01",
        "end_date": "2026-06-01",
    }
    defaults.update(overrides)
    return defaults


def create_finding_payload(**overrides) -> dict:
    defaults = {"severity": "MEDIUM", "description": f"Finding {_tag()}"}
    defaults.update(overrides)
    return defaults
