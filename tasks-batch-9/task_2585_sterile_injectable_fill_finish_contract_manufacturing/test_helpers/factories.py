"""Request-payload builders, one per write endpoint of PRD section 4.

Each factory carries only the client-supplied input fields of its resource.
Server-owned fields — the identifier, the audit stamps, the derived ledgers, the
computed classifications and the postures of PRD 2.4, 2.5 and 2.6 — are
deliberately absent, so a test that wants to prove they are ignored has to add
them itself.

Every default is a value the specification either names or leaves free; the
numbers that the PRD works through by hand (a 10000-container VIAL batch, a
6000-unit media fill, an 8500-unit fill) are the defaults here so the worked
examples reproduce without each caller restating them.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

Json = Dict[str, Any]


# ---------------------------------------------------------------------------
# The logical clock (PRD 2.4)
# ---------------------------------------------------------------------------
def clock_payload(to_iso8601: str) -> Json:
    """Body for `POST /_clock/set_current_utc`."""
    return {"to_iso8601": to_iso8601}


# ---------------------------------------------------------------------------
# Filling suites (PRD 3.2)
# ---------------------------------------------------------------------------
def filling_suite_payload(
    suite_code: str = "FS-1",
    grade: str = "B",
    changeover_minutes_same_product: int = 60,
    changeover_minutes_product_change: int = 240,
    max_committed_minutes: int = 20000,
    **overrides: Any,
) -> Json:
    """Body for `POST /filling-suites`."""
    payload: Json = {
        "suite_code": suite_code,
        "grade": grade,
        "changeover_minutes_same_product": changeover_minutes_same_product,
        "changeover_minutes_product_change": changeover_minutes_product_change,
        "max_committed_minutes": max_committed_minutes,
    }
    payload.update(overrides)
    return payload


def cleaning_validation_payload(
    molecule_name: str = "MOL-A",
    residue_ug_per_swab: int = 12,
    **overrides: Any,
) -> Json:
    """Body for `POST /filling-suites/{id}/cleaning-validation`."""
    payload: Json = {
        "molecule_name": molecule_name,
        "residue_ug_per_swab": residue_ug_per_swab,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Media fills (PRD 3.2)
# ---------------------------------------------------------------------------
def media_fill_payload(
    suite_id: str,
    scheduled_run_date: str = "2026-09-02T08:00:00Z",
    **overrides: Any,
) -> Json:
    """Body for `POST /media-fills`."""
    payload: Json = {
        "suite_id": suite_id,
        "scheduled_run_date": scheduled_run_date,
    }
    payload.update(overrides)
    return payload


def media_fill_execute_payload(
    units_filled: int = 6000,
    participating_operator_names: Optional[List[str]] = None,
    **overrides: Any,
) -> Json:
    """Body for `POST /media-fills/{id}/execute`."""
    payload: Json = {
        "units_filled": units_filled,
        "participating_operator_names": list(
            participating_operator_names
            if participating_operator_names is not None
            else ["OP-A", "OP-B"]
        ),
    }
    payload.update(overrides)
    return payload


def media_fill_read_payload(contaminated_units: int = 0, **overrides: Any) -> Json:
    """Body for `POST /media-fills/{id}/read`."""
    payload: Json = {"contaminated_units": contaminated_units}
    payload.update(overrides)
    return payload


def media_fill_adjudicate_payload(
    outcome: str = "PASSED",
    adjudication_rationale: str = "Single unit traced to an incubator artefact.",
    **overrides: Any,
) -> Json:
    """Body for `POST /media-fills/{id}/adjudicate`."""
    payload: Json = {
        "outcome": outcome,
        "adjudication_rationale": adjudication_rationale,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Personnel qualifications (PRD 3.3)
# ---------------------------------------------------------------------------
def qualification_payload(
    operator_name: str,
    suite_id: str,
    qualification_type: str = "ASEPTIC_INTERVENTION",
    expires_on: str = "2027-06-01T00:00:00Z",
    media_fill_id: Optional[str] = None,
    **overrides: Any,
) -> Json:
    """Body for `POST /personnel-qualifications`."""
    payload: Json = {
        "operator_name": operator_name,
        "suite_id": suite_id,
        "qualification_type": qualification_type,
        "expires_on": expires_on,
        "media_fill_id": media_fill_id,
    }
    payload.update(overrides)
    return payload


def revoke_payload(
    revoke_reason: str = "Operator left the aseptic roster.", **overrides: Any
) -> Json:
    """Body for `POST /personnel-qualifications/{id}/revoke`."""
    payload: Json = {"revoke_reason": revoke_reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Client projects (PRD 3.1, 3.9)
# ---------------------------------------------------------------------------
def client_project_payload(
    primary_suite_id: str,
    client_name: str = "Sponsor A",
    molecule_name: str = "MOL-A",
    dosage_form: str = "VIAL",
    target_fill_weight_mg: int = 1000,
    historical_reject_rate_ppm: int = 2500,
    reserved_unit_budget: int = 30000,
    **overrides: Any,
) -> Json:
    """Body for `POST /client-projects`."""
    payload: Json = {
        "client_name": client_name,
        "molecule_name": molecule_name,
        "dosage_form": dosage_form,
        "primary_suite_id": primary_suite_id,
        "target_fill_weight_mg": target_fill_weight_mg,
        "historical_reject_rate_ppm": historical_reject_rate_ppm,
        "reserved_unit_budget": reserved_unit_budget,
    }
    payload.update(overrides)
    return payload


def advance_tech_transfer_payload(
    to_stage: str,
    analytical_method_transfer_status: str,
    **overrides: Any,
) -> Json:
    """Body for `POST /client-projects/{id}/advance-tech-transfer`."""
    payload: Json = {
        "to_stage": to_stage,
        "analytical_method_transfer_status": analytical_method_transfer_status,
    }
    payload.update(overrides)
    return payload


def release_hold_payload(
    release_rationale: str = "Critical deviation closed; project resumes.",
    **overrides: Any,
) -> Json:
    """Body for `POST /client-projects/{id}/release-hold`."""
    payload: Json = {"release_rationale": release_rationale}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Component lots and reservations (PRD 3.4)
# ---------------------------------------------------------------------------
def component_lot_payload(
    client_project_id: str,
    component_type: str = "VIAL",
    lot_code: str = "VL-1",
    quantity_received: int = 30000,
    sterilization_expiry: str = "2027-01-01T00:00:00Z",
    **overrides: Any,
) -> Json:
    """Body for `POST /component-lots`."""
    payload: Json = {
        "client_project_id": client_project_id,
        "component_type": component_type,
        "lot_code": lot_code,
        "quantity_received": quantity_received,
        "sterilization_expiry": sterilization_expiry,
    }
    payload.update(overrides)
    return payload


def sterilization_validation_payload(
    outcome: str = "RELEASED", f0_minutes: float = 15, **overrides: Any
) -> Json:
    """Body for `POST /component-lots/{id}/sterilization-validation`."""
    payload: Json = {"outcome": outcome, "f0_minutes": f0_minutes}
    payload.update(overrides)
    return payload


def component_reservation_payload(
    batch_order_id: str,
    component_lot_id: str,
    quantity_reserved: int,
    expected_component_lot_version: int,
    **overrides: Any,
) -> Json:
    """Body for `POST /component-reservations`."""
    payload: Json = {
        "batch_order_id": batch_order_id,
        "component_lot_id": component_lot_id,
        "quantity_reserved": quantity_reserved,
        "expected_component_lot_version": expected_component_lot_version,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Batch orders (PRD 3.5, 3.6, 3.8)
# ---------------------------------------------------------------------------
def batch_order_payload(
    client_project_id: str,
    suite_id: str,
    lead_operator_qualification_id: str,
    expected_suite_version: int,
    batch_number: str = "B-001",
    planned_start: str = "2026-09-10T08:00:00Z",
    planned_end: str = "2026-09-10T16:00:00Z",
    target_fill_units: int = 10000,
    **overrides: Any,
) -> Json:
    """Body for `POST /batch-orders`."""
    payload: Json = {
        "client_project_id": client_project_id,
        "suite_id": suite_id,
        "lead_operator_qualification_id": lead_operator_qualification_id,
        "batch_number": batch_number,
        "planned_start": planned_start,
        "planned_end": planned_end,
        "target_fill_units": target_fill_units,
        "expected_suite_version": expected_suite_version,
    }
    payload.update(overrides)
    return payload


def complete_fill_payload(filled_unit_count: int = 8500, **overrides: Any) -> Json:
    """Body for `POST /batch-orders/{id}/complete-fill`."""
    payload: Json = {"filled_unit_count": filled_unit_count}
    payload.update(overrides)
    return payload


def cancel_payload(
    cancellation_reason: str = "Sponsor withdrew the campaign.", **overrides: Any
) -> Json:
    """Body for `POST /batch-orders/{id}/cancel`."""
    payload: Json = {"cancellation_reason": cancellation_reason}
    payload.update(overrides)
    return payload


def qp_release_payload(
    decision: str = "RELEASE",
    rationale: str = "Record reviewed and clean; batch is fit for release.",
    **overrides: Any,
) -> Json:
    """Body for `POST /batch-orders/{id}/qp-release`."""
    payload: Json = {"decision": decision, "rationale": rationale}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# In-process controls (PRD 3.6)
# ---------------------------------------------------------------------------
def fill_weight_check_payload(
    batch_order_id: str,
    measured_fill_weights_mg: Optional[List[float]] = None,
    sample_size: int = 40,
    destructive_sample_units: int = 40,
    reject_unit_count: int = 0,
    **overrides: Any,
) -> Json:
    """Body for a FILL_WEIGHT `POST /in-process-checks`."""
    payload: Json = {
        "batch_order_id": batch_order_id,
        "check_type": "FILL_WEIGHT",
        "sample_size": sample_size,
        "reject_unit_count": reject_unit_count,
        "destructive_sample_units": destructive_sample_units,
        "measured_fill_weights_mg": list(
            measured_fill_weights_mg
            if measured_fill_weights_mg is not None
            else [1000, 1020, 985, 1028, 1012]
        ),
    }
    payload.update(overrides)
    return payload


def cci_check_payload(
    batch_order_id: str,
    sample_size: int = 20,
    reject_unit_count: int = 0,
    destructive_sample_units: int = 20,
    **overrides: Any,
) -> Json:
    """Body for a CCI `POST /in-process-checks`."""
    payload: Json = {
        "batch_order_id": batch_order_id,
        "check_type": "CCI",
        "sample_size": sample_size,
        "reject_unit_count": reject_unit_count,
        "destructive_sample_units": destructive_sample_units,
    }
    payload.update(overrides)
    return payload


def visual_check_payload(
    batch_order_id: str,
    sample_size: int = 8500,
    reject_unit_count: int = 166,
    destructive_sample_units: int = 0,
    **overrides: Any,
) -> Json:
    """Body for a VISUAL_INSPECTION `POST /in-process-checks`."""
    payload: Json = {
        "batch_order_id": batch_order_id,
        "check_type": "VISUAL_INSPECTION",
        "sample_size": sample_size,
        "reject_unit_count": reject_unit_count,
        "destructive_sample_units": destructive_sample_units,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Environmental monitoring (PRD 3.7)
# ---------------------------------------------------------------------------
def em_sample_payload(
    suite_id: str,
    sample_type: str = "VIABLE_AIR",
    cfu_count: int = 0,
    batch_order_id: Optional[str] = None,
    **overrides: Any,
) -> Json:
    """Body for `POST /em-samples`."""
    payload: Json = {
        "suite_id": suite_id,
        "sample_type": sample_type,
        "cfu_count": cfu_count,
        "batch_order_id": batch_order_id,
    }
    payload.update(overrides)
    return payload


def investigate_payload(
    investigator_note: str = "Sampling head traced and the room requalified.",
    **overrides: Any,
) -> Json:
    """Body for `POST /em-samples/{id}/investigate`."""
    payload: Json = {"investigator_note": investigator_note}
    payload.update(overrides)
    return payload


def close_investigation_payload(
    root_cause: str = "Transient gowning breach by a visiting engineer.",
    **overrides: Any,
) -> Json:
    """Body for `POST /em-samples/{id}/close-investigation`."""
    payload: Json = {"root_cause": root_cause}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Deviations and CAPA (PRD 3.7)
# ---------------------------------------------------------------------------
def deviation_payload(
    batch_order_id: str,
    summary: str = "Isolator glove integrity questioned during the fill.",
    em_sample_id: Optional[str] = None,
    **overrides: Any,
) -> Json:
    """Body for `POST /deviations`."""
    payload: Json = {
        "batch_order_id": batch_order_id,
        "summary": summary,
        "em_sample_id": em_sample_id,
    }
    payload.update(overrides)
    return payload


def classify_payload(
    classification: str = "MAJOR",
    classification_rationale: str = "Product contact surface implicated.",
    **overrides: Any,
) -> Json:
    """Body for `POST /deviations/{id}/classify`."""
    payload: Json = {
        "classification": classification,
        "classification_rationale": classification_rationale,
    }
    payload.update(overrides)
    return payload


def submit_capa_payload(
    capa_summary: str = "Glove change frequency doubled and operators retrained.",
    **overrides: Any,
) -> Json:
    """Body for `POST /deviations/{id}/submit-capa`."""
    payload: Json = {"capa_summary": capa_summary}
    payload.update(overrides)
    return payload


def decide_capa_payload(
    outcome: str = "APPROVED",
    decision_note: str = "Corrective action is effective and verified.",
    **overrides: Any,
) -> Json:
    """Body for `POST /deviations/{id}/decide-capa`."""
    payload: Json = {"outcome": outcome, "decision_note": decision_note}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Batch record reviews (PRD 3.8)
# ---------------------------------------------------------------------------
def batch_record_review_payload(batch_order_id: str, **overrides: Any) -> Json:
    """Body for `POST /batch-record-reviews`."""
    payload: Json = {"batch_order_id": batch_order_id}
    payload.update(overrides)
    return payload


def record_findings_payload(
    open_findings_count: int,
    findings_note: str = "Two documentation gaps raised against the record.",
    **overrides: Any,
) -> Json:
    """Body for `POST /batch-record-reviews/{id}/record-findings`."""
    payload: Json = {
        "open_findings_count": open_findings_count,
        "findings_note": findings_note,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Audit engagements (PRD 3.9)
# ---------------------------------------------------------------------------
def audit_engagement_payload(
    client_project_id: str,
    audit_kind: str = "CLIENT_AUDIT",
    requested_window_start: str = "2026-09-20T09:00:00Z",
    **overrides: Any,
) -> Json:
    """Body for `POST /audit-engagements`."""
    payload: Json = {
        "client_project_id": client_project_id,
        "audit_kind": audit_kind,
        "requested_window_start": requested_window_start,
    }
    payload.update(overrides)
    return payload


def host_audit_payload(
    outcome: str = "HOSTED", finding_count: int = 4, **overrides: Any
) -> Json:
    """Body for `POST /audit-engagements/{id}/host`."""
    payload: Json = {"outcome": outcome, "finding_count": finding_count}
    payload.update(overrides)
    return payload
