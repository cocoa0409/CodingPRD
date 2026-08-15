"""Payload factories — one per creatable resource, input fields only."""
import itertools

from .constants import ALL_ATTRIBUTES, TEST_DEFAULTS

_counter = itertools.count(1)


def _next(tag: str) -> str:
    return f"{tag}-{next(_counter)}"


def create_client_payload(**overrides) -> dict:
    n = _next("client")
    defaults = {
        "name": f"Client {n}",
        "contact_email": f"{n}@acme.example.com",
    }
    defaults.update(overrides)
    return defaults


def topup_payload(hours=TEST_DEFAULTS["TOPUP_HOURS"]) -> dict:
    return {"hours": hours}


def create_study_payload(client_id, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "product_name": f"Product {_next('prod')}",
        "study_type": "REAL_TIME",
        "storage_temp_c": TEST_DEFAULTS["STORAGE_TEMP_C"],
        "target_shelf_life_days": TEST_DEFAULTS["TARGET_SHELF_LIFE_DAYS"],
        "sensory_fail_threshold": TEST_DEFAULTS["SENSORY_FAIL_THRESHOLD"],
        "min_detectable_difference": TEST_DEFAULTS["MIN_DETECTABLE_DIFFERENCE"],
        "planned_start_utc": TEST_DEFAULTS["PLANNED_START"],
    }
    defaults.update(overrides)
    return defaults


def update_study_payload(expected_study_version, **overrides) -> dict:
    payload = {"expected_study_version": expected_study_version}
    payload.update(overrides)
    return payload


def create_arm_payload(study_id, packaging_variant="STANDARD_FILM",
                       is_control=True) -> dict:
    return {
        "study_id": study_id,
        "packaging_variant": packaging_variant,
        "is_control": is_control,
    }


def create_time_point_payload(study_id, day_index=0) -> dict:
    return {"study_id": study_id, "day_index": day_index}


def create_chamber_payload(**overrides) -> dict:
    defaults = {
        "chamber_code": _next("CH"),
        "temp_c": TEST_DEFAULTS["STORAGE_TEMP_C"],
        "capacity_units": TEST_DEFAULTS["CHAMBER_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def pull_payload(chamber_id, arm_id, quantity=1, unit_purpose="EVALUATION") -> dict:
    return {
        "chamber_id": chamber_id,
        "arm_id": arm_id,
        "quantity": quantity,
        "unit_purpose": unit_purpose,
    }


def create_panelist_payload(**overrides) -> dict:
    n = _next("panelist")
    defaults = {
        "full_name": f"Panelist {n}",
        "email": f"{n}@lab.example.com",
        "qualified_attributes": list(ALL_ATTRIBUTES),
    }
    defaults.update(overrides)
    return defaults


def create_session_payload(study_id, time_point_id, arm_id,
                           scheduled_start_utc="2026-08-01T10:00:00Z",
                           scheduled_end_utc="2026-08-01T11:00:00Z") -> dict:
    return {
        "study_id": study_id,
        "time_point_id": time_point_id,
        "arm_id": arm_id,
        "scheduled_start_utc": scheduled_start_utc,
        "scheduled_end_utc": scheduled_end_utc,
    }


def create_assignment_payload(session_id, panelist_id) -> dict:
    return {"session_id": session_id, "panelist_id": panelist_id}


def create_score_payload(assignment_id, attribute="OVERALL", score=9) -> dict:
    return {"assignment_id": assignment_id, "attribute": attribute, "score": score}


def create_lab_result_payload(study_id, arm_id, time_point_id,
                              test_type="APC", measured_value=3.0) -> dict:
    return {
        "study_id": study_id,
        "arm_id": arm_id,
        "time_point_id": time_point_id,
        "test_type": test_type,
        "measured_value": measured_value,
    }


def create_recommendation_payload(study_id, arm_id, expected_study_version) -> dict:
    return {
        "study_id": study_id,
        "arm_id": arm_id,
        "expected_study_version": expected_study_version,
    }


def create_report_payload(study_id, title=None) -> dict:
    return {"study_id": study_id, "title": title or f"Report {_next('rep')}"}


def create_claim_payload(report_id, claim_type="SHELF_LIFE_DAYS",
                         claim_text=None, claimed_value=42, arm_id=None) -> dict:
    payload = {
        "report_id": report_id,
        "claim_type": claim_type,
        "claim_text": claim_text or f"Claim {_next('claim')}",
        "claimed_value": claimed_value,
    }
    if arm_id is not None:
        payload["arm_id"] = arm_id
    return payload
