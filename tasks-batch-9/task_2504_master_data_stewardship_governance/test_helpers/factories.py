"""Payload factories — one per resource, request-body fields only."""

from typing import Any, Dict

from .constants import TEST_DEFAULTS


def domain_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "code": TEST_DEFAULTS["DOMAIN_CODE"],
        "name": TEST_DEFAULTS["DOMAIN_NAME"],
        "classification_level": TEST_DEFAULTS["CLASSIFICATION_LEVEL"],
        "notification_lead_days_floor": TEST_DEFAULTS["NOTIFICATION_LEAD_DAYS_FLOOR"],
        "expected_attribute_count": TEST_DEFAULTS["EXPECTED_ATTRIBUTE_COUNT"],
    }
    payload.update(overrides)
    return payload


def source_system_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "code": TEST_DEFAULTS["SOURCE_CODE"],
        "name": TEST_DEFAULTS["SOURCE_NAME"],
        "trust_tier": TEST_DEFAULTS["TRUST_TIER"],
    }
    payload.update(overrides)
    return payload


def steward_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "full_name": TEST_DEFAULTS["STEWARD_NAME"],
        "email": TEST_DEFAULTS["STEWARD_EMAIL"],
        "certification_level": "SENIOR",
    }
    payload.update(overrides)
    return payload


def source_registration_payload(
    domain_id: str, source_system_id: str, expected_domain_version: int, **overrides
) -> Dict[str, Any]:
    payload = {
        "domain_id": domain_id,
        "source_system_id": source_system_id,
        "role": "AUTHORITATIVE",
        "trust_rank": 1,
        "effective_from": TEST_DEFAULTS["EFFECTIVE_FROM"],
        "expected_domain_version": expected_domain_version,
    }
    payload.update(overrides)
    return payload


def steward_assignment_payload(
    domain_id: str, steward_id: str, expected_domain_version: int, **overrides
) -> Dict[str, Any]:
    payload = {
        "domain_id": domain_id,
        "steward_id": steward_id,
        "steward_role": "DATA_STEWARD",
        "effective_from": TEST_DEFAULTS["EFFECTIVE_FROM"],
        "expected_domain_version": expected_domain_version,
    }
    payload.update(overrides)
    return payload


def quality_rule_payload(domain_id: str, owner_steward_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "domain_id": domain_id,
        "owner_steward_id": owner_steward_id,
        "rule_code": TEST_DEFAULTS["RULE_CODE"],
        "dimension": "COMPLETENESS",
        "weight_points": TEST_DEFAULTS["WEIGHT_POINTS"],
        "threshold_pct": TEST_DEFAULTS["THRESHOLD_PCT"],
        "severity": TEST_DEFAULTS["SEVERITY"],
    }
    payload.update(overrides)
    return payload


def scorecard_run_payload(basis: str = "CERTIFIED", measurements=None, **overrides) -> Dict[str, Any]:
    payload = {
        "basis": basis,
        "measurements": measurements if measurements is not None else [],
    }
    payload.update(overrides)
    return payload


def master_record_payload(
    domain_id: str, source_system_id: str, **overrides
) -> Dict[str, Any]:
    payload = {
        "domain_id": domain_id,
        "source_system_id": source_system_id,
        "natural_key": "ERP-CUST-1001",
        "attributes": {
            "legal_name": "Acme Industrial",
            "tax_id": "TX-77",
            "billing_city": "Austin",
            "contact_email": "ops@acme.test",
        },
        "last_verified_at": "2026-07-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def merge_proposal_payload(
    survivor_master_record_id: str, duplicate_master_record_id: str, **overrides
) -> Dict[str, Any]:
    payload = {
        "survivor_master_record_id": survivor_master_record_id,
        "duplicate_master_record_id": duplicate_master_record_id,
        "name_similarity_pct": 90.00,
        "key_overlap_pct": 80.00,
    }
    payload.update(overrides)
    return payload


def change_request_payload(domain_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "domain_id": domain_id,
        "change_type": "REFERENCE_VALUE_ADD",
        "title": "Add customer segment SMB",
        "proposed_values": {"reference_value": "SEGMENT_SMB"},
    }
    payload.update(overrides)
    return payload


def consumer_subscription_payload(domain_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "domain_id": domain_id,
        "consumer_code": "BI_CUSTOMER_360",
        "reporting_asset_key": "RPT_CUST_360",
        "clearance_level": "INTERNAL",
        "criticality": "TIER1",
        "required_lead_days": 10,
    }
    payload.update(overrides)
    return payload
