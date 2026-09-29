"""Payload factories — one per record type, input fields only."""

import copy
from typing import List, Optional

from .constants import STANDARD_PARTICIPATING_STATES, TEST_DEFAULTS


def insurer_payload(**overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["INSURER_NAME"],
        "naic_code": TEST_DEFAULTS["NAIC_CODE"],
        "annual_premium_written_cents": TEST_DEFAULTS["ANNUAL_PREMIUM_WRITTEN_CENTS"],
        "policy_count_in_force": TEST_DEFAULTS["POLICY_COUNT_IN_FORCE"],
        "confirmed_complaints_12mo": TEST_DEFAULTS["CONFIRMED_COMPLAINTS_12MO"],
        "financial_stress_score": TEST_DEFAULTS["FINANCIAL_STRESS_SCORE"],
        "consumer_trend_score": TEST_DEFAULTS["CONSUMER_TREND_SCORE"],
    }
    payload.update(overrides)
    return payload


def analysis_cycle_payload(**overrides) -> dict:
    payload = {
        "cycle_label": "FY2026 Market Analysis",
        "reference_period_start": TEST_DEFAULTS["REFERENCE_PERIOD_START"],
        "reference_period_end": TEST_DEFAULTS["REFERENCE_PERIOD_END"],
        "target_slot_capacity": 2,
        "default_fieldwork_start": TEST_DEFAULTS["FIELDWORK_START_DATE"],
        "default_fieldwork_end": TEST_DEFAULTS["FIELDWORK_END_DATE"],
    }
    payload.update(overrides)
    return payload


def examination_payload(insurer_id: str, **overrides) -> dict:
    payload = {
        "insurer_id": insurer_id,
        "exam_type": "MARKET_CONDUCT_EXAM",
        "mode": "ON_SITE",
        "lead_state_code": TEST_DEFAULTS["LEAD_STATE_CODE"],
        "fieldwork_start_date": TEST_DEFAULTS["FIELDWORK_START_DATE"],
        "fieldwork_end_date": TEST_DEFAULTS["FIELDWORK_END_DATE"],
    }
    payload.update(overrides)
    return payload


def scope_area_payload(area: str = "CLAIMS", **overrides) -> dict:
    payload = {
        "area": area,
        "population_size": 4000,
        "sample_size": 10,
    }
    payload.update(overrides)
    return payload


def data_call_payload(**overrides) -> dict:
    payload = {
        "records_requested": 4000,
        "response_due_date": TEST_DEFAULTS["RESPONSE_DUE_DATE"],
    }
    payload.update(overrides)
    return payload


def data_call_response_payload(**overrides) -> dict:
    payload = {
        "records_received": 4000,
        "submitted_by_contact": TEST_DEFAULTS["SUBMITTED_BY_CONTACT"],
    }
    payload.update(overrides)
    return payload


def disposition_payload(disposition: str = "ACCEPTED", **overrides) -> dict:
    payload = {
        "disposition": disposition,
        "disposition_reason": "Production complete and on time.",
    }
    payload.update(overrides)
    return payload


def fieldwork_activity_payload(
    activity_type: str = "SYSTEM_WALKTHROUGH", area: str = "CLAIMS", **overrides
) -> dict:
    payload = {
        "activity_type": activity_type,
        "area": area,
        "participant_name": "R. Vance",
        "participant_title": "VP Claims Operations",
        "summary": "Walked the claims adjudication platform end to end with the carrier.",
        "evidence_ref": "WP-CLM-01",
    }
    payload.update(overrides)
    return payload


def file_review_payload(error_severity: str = "NONE", **overrides) -> dict:
    payload = {"error_severity": error_severity}
    payload.update(overrides)
    return payload


def bulk_review_payload(reviews: List[dict]) -> dict:
    return {"reviews": copy.deepcopy(reviews)}


def criticism_payload(
    exam_id: str,
    scope_area_id: str,
    severity: str = "MATERIAL",
    affected_file_count: int = 3,
    **overrides,
) -> dict:
    payload = {
        "exam_id": exam_id,
        "scope_area_id": scope_area_id,
        "statute_citation": TEST_DEFAULTS["STATUTE_CITATION"],
        "severity": severity,
        "affected_file_count": affected_file_count,
    }
    payload.update(overrides)
    return payload


def company_response_payload(position: str = "DISPUTE", **overrides) -> dict:
    payload = {
        "position": position,
        "narrative": (
            "The carrier disputes the extrapolation methodology applied to the "
            "claims sample."
        ),
    }
    payload.update(overrides)
    return payload


def rebuttal_payload(**overrides) -> dict:
    payload = {
        "rebuttal_note": (
            "The department is not persuaded and requests further documentation."
        )
    }
    payload.update(overrides)
    return payload


def criticism_finalize_payload(
    disposition: str = "SUSTAINED", penalty_units: Optional[int] = 20, **overrides
) -> dict:
    payload = {
        "disposition": disposition,
        "disposition_note": "Criticism sustained after review of the carrier rebuttal.",
    }
    if penalty_units is not None:
        payload["penalty_units"] = penalty_units
    payload.update(overrides)
    return payload


def corrective_action_plan_payload(expected_examination_version: int, **overrides) -> dict:
    payload = {
        "expected_examination_version": expected_examination_version,
        "milestone_count": 4,
        "completion_due_date": "2027-03-31",
        "narrative": TEST_DEFAULTS["NARRATIVE"],
    }
    payload.update(overrides)
    return payload


def plan_review_payload(decision: str = "APPROVE", **overrides) -> dict:
    payload = {
        "decision": decision,
        "review_note": "Milestones and dates are acceptable.",
    }
    payload.update(overrides)
    return payload


def consent_order_payload(
    expected_examination_version: int,
    order_number: str = "MC-2026-0001",
    penalty_variant: str = "TIERED_AGGREGATE",
    **overrides,
) -> dict:
    payload = {
        "expected_examination_version": expected_examination_version,
        "order_number": order_number,
        "penalty_variant": penalty_variant,
    }
    payload.update(overrides)
    return payload


def order_execution_payload(**overrides) -> dict:
    payload = {"signed_by": "M. Calder, Chief Compliance Officer"}
    payload.update(overrides)
    return payload


def collaboration_payload(states: Optional[List[dict]] = None, **overrides) -> dict:
    payload = {
        "call_reference": "MSC-2026-014",
        "participating_states": copy.deepcopy(
            states if states is not None else STANDARD_PARTICIPATING_STATES
        ),
    }
    payload.update(overrides)
    return payload


def publish_report_payload(**overrides) -> dict:
    payload = {"public_summary": TEST_DEFAULTS["PUBLIC_SUMMARY"]}
    payload.update(overrides)
    return payload


def abort_payload(**overrides) -> dict:
    payload = {"abort_reason": TEST_DEFAULTS["ABORT_REASON"]}
    payload.update(overrides)
    return payload


def clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}


def systematic_file_references(area: str, population_size: int, sample_size: int) -> List[str]:
    """The deterministic file references a systematic-interval draw produces.

    The interval is the population size divided by the sample size discarding the
    fractional part; the first file sits at population index 1 and each
    subsequent file one interval further along.
    """
    from .constants import AREA_PREFIX

    interval = population_size // sample_size
    return [
        f"{AREA_PREFIX[area]}-{1 + k * interval:06d}" for k in range(sample_size)
    ]
