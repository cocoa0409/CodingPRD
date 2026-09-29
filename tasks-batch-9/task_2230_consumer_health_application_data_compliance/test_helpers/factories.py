"""Payload factories. Each returns only client-supplied input fields."""

from __future__ import annotations

import itertools
from typing import Any

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


def create_app_product_payload(**overrides: Any) -> dict[str, Any]:
    """A registrable consumer health application product."""
    payload: dict[str, Any] = {
        "product_name": "SleepSense",
        "company_legal_name": "SleepSense Inc",
        "primary_state_code": "WA",
        "consumer_count": 40000,
        "annual_revenue_cents": 900000000,
        "hipaa_covered_transaction_ratio": 0.10,
    }
    payload.update(overrides)
    return payload


def create_applicability_assessment_payload(app_product_id: str, **overrides: Any) -> dict[str, Any]:
    """A DRAFT applicability assessment for a product."""
    payload: dict[str, Any] = {
        "app_product_id": app_product_id,
        "entity_status_claim": "NOT_COVERED",
        "analyst_note": "Consumer wellness app",
    }
    payload.update(overrides)
    return payload


def create_data_element_payload(app_product_id: str, **overrides: Any) -> dict[str, Any]:
    """A directly collected diagnosis element."""
    payload: dict[str, Any] = {
        "app_product_id": app_product_id,
        "element_key": f"apnea_dx_{_seq()}",
        "display_name": "Sleep apnea diagnosis",
        "source_kind": "USER_PROVIDED",
        "health_signal_kind": "DIAGNOSIS",
    }
    payload.update(overrides)
    return payload


def create_processing_purpose_payload(app_product_id: str, **overrides: Any) -> dict[str, Any]:
    """A primary-service collection purpose."""
    payload: dict[str, Any] = {
        "app_product_id": app_product_id,
        "purpose_key": f"core_service_{_seq()}",
        "description_text": "Deliver the core sleep tracking service",
        "purpose_kind": "PRIMARY_SERVICE",
        "activity_kind": "COLLECT",
    }
    payload.update(overrides)
    return payload


def create_element_purpose_mapping_payload(
    data_element_id: str, processing_purpose_id: str, **overrides: Any
) -> dict[str, Any]:
    """A proposed mapping of one element onto one purpose."""
    payload: dict[str, Any] = {
        "data_element_id": data_element_id,
        "processing_purpose_id": processing_purpose_id,
        "disclosure_specificity": "ELEMENT_NAMED",
    }
    payload.update(overrides)
    return payload


def create_consumer_payload(app_product_id: str, **overrides: Any) -> dict[str, Any]:
    """An adult consumer registration."""
    payload: dict[str, Any] = {
        "app_product_id": app_product_id,
        "external_ref": f"acct-{_seq()}",
        "residency_state_code": "WA",
        "age_band": "ADULT",
    }
    payload.update(overrides)
    return payload


def create_consent_record_payload(
    consumer_id: str, expected_consumer_version: int, **overrides: Any
) -> dict[str, Any]:
    """A new consent record opened against a consumer at a known version."""
    payload: dict[str, Any] = {
        "consumer_id": consumer_id,
        "expected_consumer_version": expected_consumer_version,
    }
    payload.update(overrides)
    return payload


def create_privacy_policy_version_payload(
    app_product_id: str,
    applicability_assessment_id: str,
    expected_app_product_version: int,
    **overrides: Any,
) -> dict[str, Any]:
    """A DRAFT privacy policy version at element-level granularity."""
    payload: dict[str, Any] = {
        "app_product_id": app_product_id,
        "applicability_assessment_id": applicability_assessment_id,
        "version_label": "v1",
        "specificity_mode": "ELEMENT_LEVEL",
        "disclosed_category_count": 1,
        "disclosed_purpose_count": 1,
        "disclosed_third_party_count": 0,
        "named_third_party_count": 0,
        "effective_from": "2026-09-01",
        "expected_app_product_version": expected_app_product_version,
    }
    payload.update(overrides)
    return payload


def create_consumer_request_payload(consumer_id: str, **overrides: Any) -> dict[str, Any]:
    """An in-app access rights request."""
    payload: dict[str, Any] = {
        "consumer_id": consumer_id,
        "request_kind": "ACCESS",
        "submitted_channel": "IN_APP",
    }
    payload.update(overrides)
    return payload


def create_vendor_payload(app_product_id: str, **overrides: Any) -> dict[str, Any]:
    """A third-party recipient vendor whose contract carries both clauses."""
    payload: dict[str, Any] = {
        "app_product_id": app_product_id,
        "vendor_name": f"AdCo-{_seq()}",
        "vendor_kind": "THIRD_PARTY_RECIPIENT",
        "flow_down_clause": True,
        "audit_rights_clause": True,
        "deletion_sla_days": 30,
    }
    payload.update(overrides)
    return payload


def create_geofence_zone_payload(app_product_id: str, **overrides: Any) -> dict[str, Any]:
    """A sensitive health facility zone."""
    payload: dict[str, Any] = {
        "app_product_id": app_product_id,
        "zone_name": f"Clinic-{_seq()}",
        "state_code": "TX",
        "facility_kind": "SENSITIVE_HEALTH",
        "center_label": "Main entrance",
        "radius_meters": 300,
    }
    payload.update(overrides)
    return payload


def create_geofence_campaign_payload(
    geofence_zone_id: str, processing_purpose_id: str, **overrides: Any
) -> dict[str, Any]:
    """A planned location campaign clear of the zone."""
    payload: dict[str, Any] = {
        "geofence_zone_id": geofence_zone_id,
        "processing_purpose_id": processing_purpose_id,
        "campaign_name": f"Campaign-{_seq()}",
        "target_radius_meters": 200,
        "distance_to_zone_center_meters": 2000,
        "window_start_at": "2026-09-01T00:00:00Z",
        "window_end_at": "2026-09-05T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_breach_incident_payload(app_product_id: str, **overrides: Any) -> dict[str, Any]:
    """An unprotected breach of health data."""
    payload: dict[str, Any] = {
        "app_product_id": app_product_id,
        "incident_label": f"Incident-{_seq()}",
        "discovered_at": "2026-08-05T00:00:00Z",
        "breach_scope": "CHD_ONLY",
        "protection_state": "UNPROTECTED",
        "affected_consumer_count": 120,
        "affected_state_max_count": 40,
    }
    payload.update(overrides)
    return payload


def create_security_risk_assessment_payload(app_product_id: str, **overrides: Any) -> dict[str, Any]:
    """A DRAFT security risk assessment with moderate maturity scores."""
    payload: dict[str, Any] = {
        "app_product_id": app_product_id,
        "assessment_label": f"Annual review {_seq()}",
        "admin_control_score": 60,
        "technical_control_score": 60,
        "physical_control_score": 70,
        "vendor_oversight_score": 75,
        "documented_gap_count": 1,
        "remediation_plan_present": False,
    }
    payload.update(overrides)
    return payload


def set_clock_payload(to_iso8601: str) -> dict[str, Any]:
    """Body for the logical-clock control endpoint."""
    return {"to_iso8601": to_iso8601}
