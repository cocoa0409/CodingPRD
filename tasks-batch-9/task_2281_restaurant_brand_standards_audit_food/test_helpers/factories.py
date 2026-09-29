"""Payload factories — one per resource, input fields only."""
from .constants import TEST_DEFAULTS


def brand_payload(**overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["BRAND_NAME"],
        "brand_code": TEST_DEFAULTS["BRAND_CODE"],
        "unannounced_min_ratio_pct": TEST_DEFAULTS["UNANNOUNCED_MIN_RATIO_PCT"],
    }
    payload.update(overrides)
    return payload


def franchisee_payload(brand_id, **overrides) -> dict:
    payload = {
        "brand_id": brand_id,
        "legal_name": TEST_DEFAULTS["FRANCHISEE_LEGAL_NAME"],
        "contact_email": TEST_DEFAULTS["FRANCHISEE_CONTACT_EMAIL"],
        "agreement_signed_at": TEST_DEFAULTS["AGREEMENT_SIGNED_AT"],
    }
    payload.update(overrides)
    return payload


def auditor_payload(**overrides) -> dict:
    payload = {
        "full_name": TEST_DEFAULTS["AUDITOR_NAME"],
        "employee_code": TEST_DEFAULTS["AUDITOR_CODE"],
    }
    payload.update(overrides)
    return payload


def location_payload(brand_id, franchisee_id, **overrides) -> dict:
    payload = {
        "brand_id": brand_id,
        "franchisee_id": franchisee_id,
        "store_number": TEST_DEFAULTS["STORE_NUMBER"],
        "region_code": TEST_DEFAULTS["REGION_CODE"],
    }
    payload.update(overrides)
    return payload


def rubric_version_payload(brand_id, expected_brand_version, **overrides) -> dict:
    payload = {
        "brand_id": brand_id,
        "version_label": TEST_DEFAULTS["RUBRIC_LABEL"],
        "effective_from": TEST_DEFAULTS["RUBRIC_EFFECTIVE_FROM"],
        "total_points": TEST_DEFAULTS["RUBRIC_TOTAL_POINTS"],
        "expected_brand_version": expected_brand_version,
    }
    payload.update(overrides)
    return payload


def rubric_item_payload(item_code, section, max_points, display_order, **overrides) -> dict:
    payload = {
        "item_code": item_code,
        "section": section,
        "max_points": max_points,
        "display_order": display_order,
    }
    payload.update(overrides)
    return payload


def audit_visit_payload(location_id, auditor_id, rubric_version_id,
                        scheduled_start_at, scheduled_end_at,
                        visit_type="UNANNOUNCED", **overrides) -> dict:
    payload = {
        "location_id": location_id,
        "auditor_id": auditor_id,
        "rubric_version_id": rubric_version_id,
        "visit_type": visit_type,
        "scheduled_start_at": scheduled_start_at,
        "scheduled_end_at": scheduled_end_at,
    }
    payload.update(overrides)
    return payload


def scored_item_payload(rubric_item_id, points_awarded, **overrides) -> dict:
    payload = {
        "rubric_item_id": rubric_item_id,
        "points_awarded": points_awarded,
    }
    payload.update(overrides)
    return payload


def rescore_payload(scored_item_id, points_awarded, expected_visit_version, **overrides) -> dict:
    payload = {
        "scored_item_id": scored_item_id,
        "points_awarded": points_awarded,
        "expected_visit_version": expected_visit_version,
    }
    payload.update(overrides)
    return payload


def void_payload(void_reason="SCHEDULING_ERROR", **overrides) -> dict:
    payload = {"void_reason": void_reason}
    payload.update(overrides)
    return payload


def evidence_photo_payload(captured_at, corrective_action_id=None,
                           dispute_id=None, **overrides) -> dict:
    payload = {
        "file_uri": TEST_DEFAULTS["PHOTO_URI"],
        "captured_at": captured_at,
    }
    if corrective_action_id is not None:
        payload["corrective_action_id"] = corrective_action_id
    if dispute_id is not None:
        payload["dispute_id"] = dispute_id
    payload.update(overrides)
    return payload


def verify_payload(outcome="ACCEPTED", **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


def dispute_payload(scored_item_id, requested_points, **overrides) -> dict:
    payload = {
        "scored_item_id": scored_item_id,
        "requested_points": requested_points,
        "reason": "The cooler probe was recalibrated the same morning; score is unfair.",
    }
    payload.update(overrides)
    return payload


def request_info_payload(**overrides) -> dict:
    payload = {"information_requested": "Provide the probe calibration log."}
    payload.update(overrides)
    return payload


def resolve_dispute_payload(outcome, **overrides) -> dict:
    payload = {
        "outcome": outcome,
        "rationale": "Reviewed the calibration log and the photographic evidence.",
    }
    payload.update(overrides)
    return payload


def health_inspection_payload(location_id, inspection_date, points_scored,
                              letter_grade, points_possible=100, **overrides) -> dict:
    payload = {
        "location_id": location_id,
        "authority_name": TEST_DEFAULTS["AUTHORITY_NAME"],
        "inspection_date": inspection_date,
        "points_scored": points_scored,
        "points_possible": points_possible,
        "letter_grade": letter_grade,
    }
    payload.update(overrides)
    return payload


def disregard_payload(disregard_reason="DATA_ERROR", **overrides) -> dict:
    payload = {"disregard_reason": disregard_reason}
    payload.update(overrides)
    return payload


def calibration_record_payload(shadow_visit_id, **overrides) -> dict:
    payload = {"shadow_visit_id": shadow_visit_id}
    payload.update(overrides)
    return payload
