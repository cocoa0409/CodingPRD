"""Payload factories — one per entity, input fields only."""
import itertools

from .constants import (
    DEFAULT_RUBRIC_ITEMS,
    DEFAULT_WINDOW_START,
    DEFAULT_WINDOW_END,
    TEST_DEFAULTS,
)

# Monotonic suffixes keep externally-unique fields (candidate external_ref,
# instrument codes) collision-free inside a single test run.
_counter = itertools.count(1)


def _next() -> int:
    return next(_counter)


def create_vendor_payload(**overrides) -> dict:
    defaults = {"name": TEST_DEFAULTS["VENDOR_NAME"]}
    defaults.update(overrides)
    return defaults


def create_content_ledger_event_payload(**overrides) -> dict:
    defaults = {
        "direction": "DISTRIBUTE",
        "copies": 1,
        "note": "Shipped workbooks to client site.",
    }
    defaults.update(overrides)
    return defaults


def create_instrument_payload(vendor_id, **overrides) -> dict:
    defaults = {
        "vendor_id": vendor_id,
        "code": f"{TEST_DEFAULTS['INSTRUMENT_CODE']}-{_next()}",
        "instrument_type": "COGNITIVE_ABILITY",
        "title": TEST_DEFAULTS["INSTRUMENT_TITLE"],
        "max_score": TEST_DEFAULTS["INSTRUMENT_MAX_SCORE"],
        "pass_floor": TEST_DEFAULTS["INSTRUMENT_PASS_FLOOR"],
    }
    defaults.update(overrides)
    return defaults


def create_evidence_payload(**overrides) -> dict:
    defaults = {
        "evidence_type": "CRITERION",
        "title": "Criterion validity study",
        "issuer": "IO Psych Lab",
        "effective_from": TEST_DEFAULTS["EVIDENCE_FROM"],
        "effective_until": TEST_DEFAULTS["EVIDENCE_UNTIL"],
    }
    defaults.update(overrides)
    return defaults


def create_guide_payload(**overrides) -> dict:
    defaults = {
        "title": TEST_DEFAULTS["GUIDE_TITLE"],
        "rubric_items": [dict(item) for item in DEFAULT_RUBRIC_ITEMS],
    }
    defaults.update(overrides)
    return defaults


def create_guide_revision_payload(expected_superseded_guide_version, **overrides) -> dict:
    defaults = {
        "title": "Guide v2",
        "rubric_items": [
            {"competency_code": "COMM", "weight": 0.7, "scale_max": 5},
            {"competency_code": "ANAL", "weight": 0.3, "scale_max": 5},
        ],
        "expected_superseded_guide_version": expected_superseded_guide_version,
    }
    defaults.update(overrides)
    return defaults


def create_requisition_payload(**overrides) -> dict:
    defaults = {
        "title": TEST_DEFAULTS["REQUISITION_TITLE"],
        "department": TEST_DEFAULTS["REQUISITION_DEPARTMENT"],
        "openings_count": TEST_DEFAULTS["REQUISITION_OPENINGS"],
    }
    defaults.update(overrides)
    return defaults


def create_cycle_payload(instrument_id, guide_id, **overrides) -> dict:
    defaults = {
        "instrument_id": instrument_id,
        "guide_id": guide_id,
        "label": TEST_DEFAULTS["CYCLE_LABEL"],
        "administration_window_start": DEFAULT_WINDOW_START,
        "administration_window_end": DEFAULT_WINDOW_END,
    }
    defaults.update(overrides)
    return defaults


def patch_cycle_payload(expected_cycle_version, **overrides) -> dict:
    defaults = {"expected_cycle_version": expected_cycle_version}
    defaults.update(overrides)
    return defaults


def create_candidate_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "external_ref": f"C-{n}",
        "full_name": f"Cand {n}",
        "email": f"c{n}@x.com",
        "group_code": "GROUP_A",
    }
    defaults.update(overrides)
    return defaults


def create_invitation_payload(candidate_id, **overrides) -> dict:
    defaults = {"candidate_id": candidate_id}
    defaults.update(overrides)
    return defaults


def schedule_assessment_payload(**overrides) -> dict:
    defaults = {"scheduled_for": "2026-08-10T09:00:00Z"}
    defaults.update(overrides)
    return defaults


def complete_assessment_payload(**overrides) -> dict:
    defaults = {"raw_score": 72}
    defaults.update(overrides)
    return defaults


def feedback_payload(**overrides) -> dict:
    defaults = {"feedback_text": TEST_DEFAULTS["FEEDBACK_TEXT"]}
    defaults.update(overrides)
    return defaults


def create_accommodation_request_payload(**overrides) -> dict:
    defaults = {
        "request_type": "EXTENDED_TIME",
        "justification": "Candidate requires extended time due to documented need.",
        "requested_extension_days": 2,
    }
    defaults.update(overrides)
    return defaults


def approve_accommodation_payload(**overrides) -> dict:
    defaults = {"approved_extension_days": 2, "decision_note": "Approved per policy."}
    defaults.update(overrides)
    return defaults


def deny_accommodation_payload(**overrides) -> dict:
    defaults = {"decision_note": "Insufficient documentation."}
    defaults.update(overrides)
    return defaults


def create_interviewer_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "full_name": f"Ivy {n}",
        "email": f"ivy{n}@x.com",
        "department": TEST_DEFAULTS["REQUISITION_DEPARTMENT"],
    }
    defaults.update(overrides)
    return defaults


def create_calibration_payload(guide_id, **overrides) -> dict:
    defaults = {"guide_id": guide_id}
    defaults.update(overrides)
    return defaults


def certify_calibration_payload(**overrides) -> dict:
    defaults = {"practice_score": TEST_DEFAULTS["PRACTICE_SCORE"]}
    defaults.update(overrides)
    return defaults


def create_session_payload(candidate_id, interviewer_id, guide_id, **overrides) -> dict:
    defaults = {
        "candidate_id": candidate_id,
        "interviewer_id": interviewer_id,
        "guide_id": guide_id,
        "scheduled_start": "2026-08-12T10:00:00Z",
        "scheduled_end": "2026-08-12T11:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_scorecard_payload(**overrides) -> dict:
    defaults = {
        "ratings": [
            {"competency_code": "COMM", "rating": 4},
            {"competency_code": "ANAL", "rating": 5},
        ],
        "overall_recommendation": "YES",
    }
    defaults.update(overrides)
    return defaults


def void_scorecard_payload(**overrides) -> dict:
    defaults = {"void_reason": TEST_DEFAULTS["VOID_REASON"]}
    defaults.update(overrides)
    return defaults


def create_decision_payload(candidate_id, **overrides) -> dict:
    defaults = {
        "candidate_id": candidate_id,
        "decision": "ADVANCE",
        "rationale": TEST_DEFAULTS["DECISION_RATIONALE"],
    }
    defaults.update(overrides)
    return defaults


def create_snapshot_payload(**overrides) -> dict:
    defaults = {"snapshot_type": "PROVISIONAL"}
    defaults.update(overrides)
    return defaults


def freeze_cycle_payload(**overrides) -> dict:
    defaults = {"reason_note": TEST_DEFAULTS["FREEZE_REASON_NOTE"]}
    defaults.update(overrides)
    return defaults


def unfreeze_cycle_payload(**overrides) -> dict:
    defaults = {"resolution_note": TEST_DEFAULTS["RESOLUTION_NOTE"]}
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}
