"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
from .constants import (
    DEFAULT_SITE_PAYLOAD,
    DEFAULT_CONTRACT_TERMS,
    DEFAULT_PERIOD_WINDOW,
    DEFAULT_TICKET_DATE,
)


def create_site_payload(**overrides) -> dict:
    defaults = dict(DEFAULT_SITE_PAYLOAD)
    defaults.update(overrides)
    return defaults


def create_vendor_payload(**overrides) -> dict:
    defaults = {"name": "HaulerCo", "vendor_type": "HAULER"}
    defaults.update(overrides)
    return defaults


def create_contract_payload(site_id: str, vendor_id: str, **overrides) -> dict:
    defaults = {"site_id": site_id, "vendor_id": vendor_id}
    defaults.update(DEFAULT_CONTRACT_TERMS)
    defaults.update(overrides)
    return defaults


def create_ticket_payload(site_id: str, vendor_id: str, contract_id: str, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "vendor_id": vendor_id,
        "contract_id": contract_id,
        "material_stream": "MIXED_RECYCLABLES",
        "disposal_route": "RECYCLING",
        "gross_weight_lbs": 3000,
        "tare_weight_lbs": 1000,
        "ticket_date": DEFAULT_TICKET_DATE,
        "external_ticket_ref": "T-1",
    }
    defaults.update(overrides)
    return defaults


def create_audit_payload(site_id: str, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "audit_date": "2026-08-06",
        "auditor_name": "Aud A",
        "stream_findings": [
            {
                "material_stream": "MIXED_RECYCLABLES",
                "sampled_weight_lbs": 500,
                "contamination_pct": 3,
            }
        ],
    }
    defaults.update(overrides)
    return defaults


def create_contamination_event_payload(site_id: str, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "event_date": DEFAULT_TICKET_DATE,
        "material_stream": "MIXED_RECYCLABLES",
        "contamination_pct": 3,
    }
    defaults.update(overrides)
    return defaults


def create_goal_payload(site_id: str, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "metric": "DIVERSION_RATE",
        "target_value": 80,
        "window_start": "2026-08-01",
        "window_end": "2026-09-01",
    }
    defaults.update(overrides)
    return defaults


def create_period_payload(site_id: str, **overrides) -> dict:
    defaults = {"site_id": site_id}
    defaults.update(DEFAULT_PERIOD_WINDOW)
    defaults.update(overrides)
    return defaults


def create_application_payload(site_id: str, reporting_period_id: str,
                                expected_site_version: int, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "level_requested": "BRONZE",
        "reporting_period_id": reporting_period_id,
        "expected_site_version": expected_site_version,
    }
    defaults.update(overrides)
    return defaults
