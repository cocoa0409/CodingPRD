"""Payload factories — one per entity, input fields only (PRD §3, §4)."""

DEFAULTS = {
    "CODE_VERSION_LABEL": "CoC v1.0",
    "CODE_EFFECTIVE_FROM": "2026-01-01T00:00:00Z",
    "ZT_CATEGORIES": ["FORCED_LABOR"],
    "SUPPLIER_LEGAL_NAME": "Test Supplier Ltd",
    "SUPPLIER_COUNTRY": "US",
    "SUPPLIER_SECTOR": "FOOD",
    "SIGNER_NAME": "A Signatory",
    "SIGNER_TITLE": "CEO",
    "FACILITY_NAME": "Test Facility",
    "FACILITY_COUNTRY": "US",
    "WORKER_COUNT": 10,
    "PROCESSES": ["packing"],
    "AUDITOR_NAME": "Lead Auditor",
    "AUDITOR_FIRM": "AuditCo",
    "AUDITOR_CERTS": ["SA8000"],
    "AUDITOR_COUNTRIES": ["US"],
    "AUDIT_TYPE": "INITIAL",
    "ANNOUNCEMENT": "ANNOUNCED",
    "AUDIT_START": "2026-09-01T00:00:00Z",
    "AUDIT_END": "2026-09-02T00:00:00Z",
    "FINDING_DESCRIPTION": "Finding recorded during fieldwork",
    "CAP_ACTION_DESCRIPTION": "Remediate the finding",
    "CAP_ACTION_OWNER": "HR",
    "CAP_ACTION_DUE": "2026-10-01T00:00:00Z",
    "GRIEVANCE_CHANNEL": "HOTLINE",
    "GRIEVANCE_CATEGORY": "WAGES",
    "GRIEVANCE_SEVERITY": "CRITICAL",
    "GRIEVANCE_DESCRIPTION": "Worker grievance narrative",
    "CLAIM_PROGRAM": "SMETA",
    "CLAIM_REF": "EXT-2026-001",
    "CLAIM_DATE": "2026-07-01T00:00:00Z",
    "CLAIM_SCORE": 80,
}


def create_code_version_payload(**overrides) -> dict:
    defaults = {
        "version_label": DEFAULTS["CODE_VERSION_LABEL"],
        "effective_from": DEFAULTS["CODE_EFFECTIVE_FROM"],
        "zero_tolerance_categories": list(DEFAULTS["ZT_CATEGORIES"]),
    }
    defaults.update(overrides)
    return defaults


def create_supplier_payload(**overrides) -> dict:
    defaults = {
        "legal_name": DEFAULTS["SUPPLIER_LEGAL_NAME"],
        "country_code": DEFAULTS["SUPPLIER_COUNTRY"],
        "sector": DEFAULTS["SUPPLIER_SECTOR"],
    }
    defaults.update(overrides)
    return defaults


def create_code_acknowledgment_payload(
    supplier_id, code_version_id, expected_supplier_version, **overrides
) -> dict:
    defaults = {
        "supplier_id": supplier_id,
        "code_version_id": code_version_id,
        "signer_name": DEFAULTS["SIGNER_NAME"],
        "signer_title": DEFAULTS["SIGNER_TITLE"],
        "expected_supplier_version": expected_supplier_version,
    }
    defaults.update(overrides)
    return defaults


def create_facility_payload(supplier_id, **overrides) -> dict:
    defaults = {
        "supplier_id": supplier_id,
        "name": DEFAULTS["FACILITY_NAME"],
        "country_code": DEFAULTS["FACILITY_COUNTRY"],
        "worker_count": DEFAULTS["WORKER_COUNT"],
        "processes": list(DEFAULTS["PROCESSES"]),
    }
    defaults.update(overrides)
    return defaults


def create_auditor_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["AUDITOR_NAME"],
        "firm_name": DEFAULTS["AUDITOR_FIRM"],
        "certifications": list(DEFAULTS["AUDITOR_CERTS"]),
        "country_codes_covered": list(DEFAULTS["AUDITOR_COUNTRIES"]),
    }
    defaults.update(overrides)
    return defaults


def create_audit_payload(facility_id, auditor_id, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "auditor_id": auditor_id,
        "audit_type": DEFAULTS["AUDIT_TYPE"],
        "announcement": DEFAULTS["ANNOUNCEMENT"],
        "scheduled_start": DEFAULTS["AUDIT_START"],
        "scheduled_end": DEFAULTS["AUDIT_END"],
    }
    defaults.update(overrides)
    return defaults


def create_finding_payload(**overrides) -> dict:
    defaults = {
        "classification": "MAJOR",
        "category": "WAGES",
        "description": DEFAULTS["FINDING_DESCRIPTION"],
    }
    defaults.update(overrides)
    return defaults


def cap_action(**overrides) -> dict:
    defaults = {
        "description": DEFAULTS["CAP_ACTION_DESCRIPTION"],
        "owner": DEFAULTS["CAP_ACTION_OWNER"],
        "due_date": DEFAULTS["CAP_ACTION_DUE"],
    }
    defaults.update(overrides)
    return defaults


def create_cap_payload(finding_id, actions=None, **overrides) -> dict:
    defaults = {
        "finding_id": finding_id,
        "actions": actions if actions is not None else [cap_action()],
    }
    defaults.update(overrides)
    return defaults


def create_grievance_payload(facility_id, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "channel": DEFAULTS["GRIEVANCE_CHANNEL"],
        "category": DEFAULTS["GRIEVANCE_CATEGORY"],
        "severity": DEFAULTS["GRIEVANCE_SEVERITY"],
        "description": DEFAULTS["GRIEVANCE_DESCRIPTION"],
    }
    defaults.update(overrides)
    return defaults


def create_interview_record_payload(**overrides) -> dict:
    defaults = {
        "interview_count": 4,
        "forced_labor_indicators": False,
        "recruitment_fee_indicators": False,
    }
    defaults.update(overrides)
    return defaults


def fee_item(**overrides) -> dict:
    defaults = {"worker_ref": "W1", "amount_minor_units": 300, "currency": "BDT"}
    defaults.update(overrides)
    return defaults


def create_fee_review_payload(**overrides) -> dict:
    defaults = {"workers_assessed": 1, "fee_items": []}
    defaults.update(overrides)
    return defaults


def create_reimbursement_payload(amount_cents, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_claim_payload(facility_id, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "program_name": DEFAULTS["CLAIM_PROGRAM"],
        "external_audit_ref": DEFAULTS["CLAIM_REF"],
        "external_audit_date": DEFAULTS["CLAIM_DATE"],
        "external_score": DEFAULTS["CLAIM_SCORE"],
    }
    defaults.update(overrides)
    return defaults
