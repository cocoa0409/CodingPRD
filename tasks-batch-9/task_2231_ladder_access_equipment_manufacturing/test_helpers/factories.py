"""Payload factories — one per resource, input fields only.

Each factory returns the required input fields with sensible defaults and folds
`**overrides` on top. Optional fields are only present when a caller supplies
them, so that server-side defaults stay observable.
"""

import itertools
from typing import Any, Dict, List, Optional

from .constants import CLOCK_START_UTC, TEST_DEFAULTS

_counter = itertools.count(1)


def unique_suffix() -> str:
    """A monotonically increasing suffix for globally unique business codes."""
    return f"{next(_counter):04d}"


# ---------------------------------------------------------------------------
# Product (PRD §3.1)
# ---------------------------------------------------------------------------
def create_product_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "model_code": f"LDR-{unique_suffix()}",
        "product_type": "EXTENSION_LADDER",
        "material": "ALUMINUM_EXTRUSION",
        "duty_rating": "TYPE_IA",
        "working_length_ft": 24.0,
        "retail_sku": f"SKU-{unique_suffix()}",
    }
    payload.update(overrides)
    return payload


def freeze_design_payload(frozen_revision_id: str, **overrides) -> Dict[str, Any]:
    payload = {"frozen_revision_id": frozen_revision_id}
    payload.update(overrides)
    return payload


def stop_ship_payload(reason_code: str = "FIELD_INCIDENT_REVIEW", **overrides) -> Dict[str, Any]:
    payload = {"reason_code": reason_code}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Design revision (PRD §3.2)
# ---------------------------------------------------------------------------
def create_design_revision_payload(
    product_id: str,
    expected_product_version: int,
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "product_id": product_id,
        "revision_label": f"REV-{unique_suffix()}",
        "joint_type": "RIVETED",
        "structural_margin_pct": TEST_DEFAULTS["STRUCTURAL_MARGIN_PCT"],
        "rail_section_modulus_in3": TEST_DEFAULTS["RAIL_SECTION_MODULUS_IN3"],
        "expected_product_version": expected_product_version,
    }
    payload.update(overrides)
    return payload


def review_design_revision_payload(
    decision: str = "APPROVE", reviewer_notes: Optional[str] = None, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if reviewer_notes is not None:
        payload["reviewer_notes"] = reviewer_notes
    payload.update(overrides)
    return payload


def revise_design_revision_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Product document (PRD §3.3)
# ---------------------------------------------------------------------------
def create_product_document_payload(
    product_id: str, doc_kind: str = "DUTY_RATING_LABEL", **overrides
) -> Dict[str, Any]:
    payload = {
        "product_id": product_id,
        "doc_kind": doc_kind,
        "document_version": "A",
        "text_digest": f"digest-{unique_suffix()}",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Test bench and reservations (PRD §3.4)
# ---------------------------------------------------------------------------
def create_test_bench_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "bench_code": f"BENCH-{unique_suffix()}",
        "max_load_capacity_lb": TEST_DEFAULTS["BENCH_CAPACITY_LB"],
        "cooldown_minutes": TEST_DEFAULTS["BENCH_COOLDOWN_MINUTES"],
    }
    payload.update(overrides)
    return payload


def create_bench_reservation_payload(
    test_bench_id: str,
    test_campaign_id: str,
    start_at: str = "2026-08-05T08:00:00Z",
    end_at: str = "2026-08-05T12:00:00Z",
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "test_bench_id": test_bench_id,
        "test_campaign_id": test_campaign_id,
        "start_at": start_at,
        "end_at": end_at,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Test campaign and load tests (PRD §3.4, §3.5)
# ---------------------------------------------------------------------------
def create_test_campaign_payload(
    product_id: str,
    design_revision_id: str,
    purpose: str = "DESIGN_QUALIFICATION",
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "product_id": product_id,
        "design_revision_id": design_revision_id,
        "purpose": purpose,
    }
    payload.update(overrides)
    return payload


def create_audit_campaign_payload(
    product_id: str,
    design_revision_id: str,
    listing_record_id: str,
    sampled_lot_id: str,
    sample_window_start: str,
    sample_window_end: str,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "product_id": product_id,
        "design_revision_id": design_revision_id,
        "purpose": "PERIODIC_AUDIT",
        "listing_record_id": listing_record_id,
        "sampled_lot_id": sampled_lot_id,
        "sample_window_start": sample_window_start,
        "sample_window_end": sample_window_end,
    }
    payload.update(overrides)
    return payload


def start_campaign_payload(bench_reservation_id: str, **overrides) -> Dict[str, Any]:
    payload = {"bench_reservation_id": bench_reservation_id}
    payload.update(overrides)
    return payload


def create_load_test_payload(
    test_code: str = "STATIC_VERTICAL",
    applied_load_lb: float = 1400.00,
    measured_deflection_in: float = 1.200,
    permanent_set_in: float = 0.010,
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "test_code": test_code,
        "applied_load_lb": applied_load_lb,
        "measured_deflection_in": measured_deflection_in,
        "permanent_set_in": permanent_set_in,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Production lot and joint samples (PRD §3.6)
# ---------------------------------------------------------------------------
def create_production_lot_payload(
    product_id: str, design_revision_id: str, **overrides
) -> Dict[str, Any]:
    payload = {
        "product_id": product_id,
        "design_revision_id": design_revision_id,
        "lot_code": f"LOT-{unique_suffix()}",
        "planned_units": TEST_DEFAULTS["PLANNED_UNITS"],
    }
    payload.update(overrides)
    return payload


def start_production_payload(
    produced_units: int = TEST_DEFAULTS["PRODUCED_UNITS"], **overrides
) -> Dict[str, Any]:
    payload = {"produced_units": produced_units}
    payload.update(overrides)
    return payload


def create_joint_sample_payload(
    sample_seq: int, pull_force_lbf: float, **overrides
) -> Dict[str, Any]:
    payload = {"sample_seq": sample_seq, "pull_force_lbf": pull_force_lbf}
    payload.update(overrides)
    return payload


def quarantine_payload(reason_code: str = "JOINT_INTEGRITY", **overrides) -> Dict[str, Any]:
    payload = {"reason_code": reason_code}
    payload.update(overrides)
    return payload


def disposition_payload(disposition: str = "RELEASE", **overrides) -> Dict[str, Any]:
    payload = {"disposition": disposition}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Listing body and listing record (PRD §3.5)
# ---------------------------------------------------------------------------
def create_listing_body_payload(
    accredited_standards: Optional[List[str]] = None, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "body_code": f"NRTL-{unique_suffix()}",
        "accredited_standards": (
            list(accredited_standards)
            if accredited_standards is not None
            else ["ANSI_ASC_A14_2", "EN_131_2"]
        ),
        "audit_interval_days": TEST_DEFAULTS["AUDIT_INTERVAL_DAYS"],
    }
    payload.update(overrides)
    return payload


def create_listing_record_payload(
    product_id: str,
    listing_body_id: str,
    standard_code: str = "ANSI_ASC_A14_2",
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "product_id": product_id,
        "listing_body_id": listing_body_id,
        "standard_code": standard_code,
    }
    payload.update(overrides)
    return payload


def suspend_listing_payload(
    suspension_reason: str = "BODY_REQUEST", **overrides
) -> Dict[str, Any]:
    payload = {"suspension_reason": suspension_reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Consumer registration (PRD §3.8)
# ---------------------------------------------------------------------------
def create_consumer_registration_payload(
    production_lot_id: str, **overrides
) -> Dict[str, Any]:
    payload = {
        "production_lot_id": production_lot_id,
        "consumer_email": f"buyer{unique_suffix()}@example.com",
        "purchase_channel": "BIG_BOX_RETAIL",
        "purchase_date": CLOCK_START_UTC,
        "serial_suffix": f"SN{unique_suffix()}",
    }
    payload.update(overrides)
    return payload


def acknowledge_payload(remedy_choice: str = "REPAIR_KIT", **overrides) -> Dict[str, Any]:
    payload = {"remedy_choice": remedy_choice}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Field incident and corrective action (PRD §3.8)
# ---------------------------------------------------------------------------
def create_field_incident_payload(
    product_id: str,
    incident_type: str = "RAIL_FRACTURE",
    injury_severity: str = "HOSPITALIZATION",
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "product_id": product_id,
        "incident_type": incident_type,
        "injury_severity": injury_severity,
        "occurred_at": CLOCK_START_UTC,
        "narrative": "Left rail fractured during normal use.",
    }
    payload.update(overrides)
    return payload


def resolve_investigation_payload(
    finding: str = "ROOT_CAUSE_IDENTIFIED",
    root_cause_code: Optional[str] = "RIVET_SHEAR_MARGIN",
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"finding": finding}
    if root_cause_code is not None:
        payload["root_cause_code"] = root_cause_code
    payload.update(overrides)
    return payload


def create_corrective_action_payload(
    field_incident_id: str, expected_field_incident_version: int, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "field_incident_id": field_incident_id,
        "action_summary": "Increase rivet count at rail-to-rung joint.",
        "expected_field_incident_version": expected_field_incident_version,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Recall event (PRD §3.9)
# ---------------------------------------------------------------------------
def create_recall_event_payload(
    product_id: str, affected_revision_ids: List[str], **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "product_id": product_id,
        "remedy_type": "REPAIR_KIT",
        "affected_revision_ids": list(affected_revision_ids),
        "hazard_description": "Rail may fracture under rated load.",
    }
    payload.update(overrides)
    return payload
