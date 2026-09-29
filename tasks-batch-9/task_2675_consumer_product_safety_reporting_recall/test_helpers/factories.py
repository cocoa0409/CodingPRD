"""Payload factories whose defaults are all legal under the contract."""

import itertools
from typing import Any, Dict

_counter = itertools.count(1)


def _seq() -> int:
    """A monotonic sequence used to keep unique fields distinct."""
    return next(_counter)


def product_model_payload(**overrides: Any) -> Dict[str, Any]:
    """A registry entry for one product model."""
    payload = {
        "model_code": f"TOAST-X{_seq()}",
        "brand": "Hearthline",
        "category": "KITCHEN_APPLIANCE",
        "units_distributed": 100,
        "units_registered": 60,
    }
    payload.update(overrides)
    return payload


def retailer_payload(**overrides: Any) -> Dict[str, Any]:
    """A registry entry for one retailer."""
    payload = {
        "name": f"MegaMart {_seq()}",
        "channel_type": "BIG_BOX",
        "store_count": 120,
    }
    payload.update(overrides)
    return payload


def incident_payload(product_model_id: str, **overrides: Any) -> Dict[str, Any]:
    """An incoming consumer incident report."""
    payload = {
        "product_model_id": product_model_id,
        "report_channel": "CONSUMER_HOTLINE",
        "incident_date": "2026-01-12T00:00:00Z",
        "narrative": "Consumer reports the unit overheated during normal use.",
    }
    payload.update(overrides)
    return payload


def classify_payload(**overrides: Any) -> Dict[str, Any]:
    """A hazard classification for one incident."""
    payload = {
        "injury_class": "HOSPITALIZATION",
        "hazard_code": "BURN",
        "injury_verified": True,
    }
    payload.update(overrides)
    return payload


def dispose_payload(**overrides: Any) -> Dict[str, Any]:
    """A disposition closing one incident without escalating it."""
    payload = {"disposition": "CLOSED_NO_ACTION"}
    payload.update(overrides)
    return payload


def hazard_pattern_payload(
    product_model_id: str, expected_product_model_version: int, **overrides: Any
) -> Dict[str, Any]:
    """An analysis over one product model's incidents inside one window."""
    payload = {
        "product_model_id": product_model_id,
        "window_start": "2026-01-01T00:00:00Z",
        "window_end": "2026-02-28T00:00:00Z",
        "analysis_basis": "PRELIMINARY",
        "expected_product_model_version": expected_product_model_version,
    }
    payload.update(overrides)
    return payload


def adjudicate_payload(**overrides: Any) -> Dict[str, Any]:
    """An adjudication of one analysed hazard pattern."""
    payload = {"decision": "CONFIRMED"}
    payload.update(overrides)
    return payload


def evaluation_payload(hazard_pattern_id: str, **overrides: Any) -> Dict[str, Any]:
    """A reportability evaluation opened on a confirmed pattern."""
    payload = {
        "hazard_pattern_id": hazard_pattern_id,
        "standard_basis": "DEFECT",
    }
    payload.update(overrides)
    return payload


def determination_payload(**overrides: Any) -> Dict[str, Any]:
    """A reportability determination supported by its scores."""
    payload = {
        "determination": "REPORTABLE",
        "defect_score": 8,
        "risk_score": 7,
        "determination_note": (
            "Base plate weld defect creates a foreseeable burn hazard in normal use."
        ),
    }
    payload.update(overrides)
    return payload


def section_report_payload(
    reportability_evaluation_id: str, **overrides: Any
) -> Dict[str, Any]:
    """A statutory report drafted against a reportable evaluation."""
    payload = {
        "reportability_evaluation_id": reportability_evaluation_id,
        "corrective_action_type": "REFUND",
        "corrective_action_summary": (
            "Full purchase-price refund plus a prepaid return label for every unit "
            "in commerce."
        ),
    }
    payload.update(overrides)
    return payload


def review_payload(**overrides: Any) -> Dict[str, Any]:
    """A review decision on a filed statutory report."""
    payload = {"decision": "ACCEPTED"}
    payload.update(overrides)
    return payload


def recall_payload(section_report_id: str, **overrides: Any) -> Dict[str, Any]:
    """A corrective action plan against an accepted statutory report."""
    payload = {
        "section_report_id": section_report_id,
        "remedy_options": ["REFUND", "REPAIR"],
        "units_in_commerce": 100,
        "participation_goal_pct": 30.00,
        "correction_deadline_at": "2026-09-30T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def retailer_notification_payload(
    recall_id: str, retailer_id: str, **overrides: Any
) -> Dict[str, Any]:
    """An enrollment of one retailer in one recall's stop-sale list."""
    payload = {"recall_id": recall_id, "retailer_id": retailer_id}
    payload.update(overrides)
    return payload


def acknowledge_payload(**overrides: Any) -> Dict[str, Any]:
    """An acknowledgement reporting the units still held on shelf."""
    payload = {"units_on_shelf_reported": 0}
    payload.update(overrides)
    return payload


def audit_visit_payload(
    retailer_notification_id: str, **overrides: Any
) -> Dict[str, Any]:
    """A shelf audit visit inside a half-open window."""
    payload = {
        "retailer_notification_id": retailer_notification_id,
        "window_start": "2026-03-17T09:00:00Z",
        "window_end": "2026-03-17T17:00:00Z",
    }
    payload.update(overrides)
    return payload


def complete_visit_payload(**overrides: Any) -> Dict[str, Any]:
    """An audit verdict with the shelf units found."""
    payload = {"verdict": "PASS", "shelf_units_found": 0}
    payload.update(overrides)
    return payload


def consumer_notice_payload(recall_id: str, **overrides: Any) -> Dict[str, Any]:
    """A consumer notice scheduled on one channel."""
    payload = {
        "recall_id": recall_id,
        "channel": "DIRECT_NOTICE",
        "scheduled_for": "2026-03-14T00:00:00Z",
        "reach_count": 60,
    }
    payload.update(overrides)
    return payload


def remedy_claim_payload(recall_id: str, **overrides: Any) -> Dict[str, Any]:
    """A consumer remedy claim against a recall."""
    payload = {
        "recall_id": recall_id,
        "consumer_ref": f"CR-{_seq():04d}",
        "remedy_type": "REFUND",
        "quantity": 30,
        "unit_price_cents": 4999,
        "shipping_cents_per_unit": 899,
    }
    payload.update(overrides)
    return payload


def progress_report_payload(recall_id: str, **overrides: Any) -> Dict[str, Any]:
    """A monthly effectiveness reporting period on a recall."""
    payload = {
        "recall_id": recall_id,
        "period_start": "2026-03-13T00:00:00Z",
        "period_end": "2026-04-12T00:00:00Z",
        "effectiveness_basis": "UNITS_BASIS",
    }
    payload.update(overrides)
    return payload


def penalty_case_payload(section_report_id: str, **overrides: Any) -> Dict[str, Any]:
    """A civil penalty docket against a filed statutory report."""
    payload = {"section_report_id": section_report_id, "violation_count": 4}
    payload.update(overrides)
    return payload


def offer_payload(
    amount_cents: int, offered_by: str, expected_case_version: int, **overrides: Any
) -> Dict[str, Any]:
    """A settlement offer from one party, pinning the case version."""
    payload = {
        "amount_cents": amount_cents,
        "offered_by": offered_by,
        "expected_case_version": expected_case_version,
    }
    payload.update(overrides)
    return payload


def offer_resolution_payload(**overrides: Any) -> Dict[str, Any]:
    """A disposition of the standing agency offer."""
    payload = {"resolution": "ACCEPTED"}
    payload.update(overrides)
    return payload
