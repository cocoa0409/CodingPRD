"""Payload factories — one per creatable entity, input fields only.

Uniqueness within a server lifetime is guaranteed by a short random suffix on
human-facing unique fields (email / code / labels); everything else defaults
to the canonical passing fixture values used across the suite.
"""
import uuid


def _uniq(tag: str) -> str:
    return f"{tag}-{uuid.uuid4().hex[:8]}"


def uniq_email(tag: str = "p") -> str:
    return f"{_uniq(tag)}@x.com"


def create_participant_payload(email=None, full_name="Test Participant", age_years=25,
                               region_code="US-W", platform_tags=None) -> dict:
    return {
        "email": email or uniq_email("p"),
        "full_name": full_name,
        "age_years": age_years,
        "region_code": region_code,
        "platform_tags": ["PC"] if platform_tags is None else platform_tags,
    }


def create_moderator_payload(display_name="Test Mod", email=None) -> dict:
    return {"display_name": display_name, "email": email or uniq_email("mod")}


def create_study_payload(title="Test Study", code=None, min_age=18, max_age=35,
                         allowed_regions=None, required_platforms=None,
                         cohort_capacity=10, incentive_budget_cents=1000000) -> dict:
    return {
        "title": title,
        "code": code or _uniq("S"),
        "min_age": min_age,
        "max_age": max_age,
        "allowed_regions": ["US-W"] if allowed_regions is None else allowed_regions,
        "required_platforms": ["PC"] if required_platforms is None else required_platforms,
        "cohort_capacity": cohort_capacity,
        "incentive_budget_cents": incentive_budget_cents,
    }


def create_application_payload(study_id) -> dict:
    return {"study_id": study_id}


def create_nda_payload(study_id, version_label="v1", body_text="NDA text") -> dict:
    return {"study_id": study_id, "version_label": version_label, "body_text": body_text}


def create_build_payload(study_id, build_label=None, max_keys=5, key_ttl_hours=None) -> dict:
    payload = {
        "study_id": study_id,
        "build_label": build_label or _uniq("b"),
        "max_keys": max_keys,
    }
    if key_ttl_hours is not None:
        payload["key_ttl_hours"] = key_ttl_hours
    return payload


def create_access_key_payload(build_id, participant_id) -> dict:
    return {"build_id": build_id, "participant_id": participant_id}


def create_station_payload(station_code=None, location="Lab A", equipment_tags=None) -> dict:
    return {
        "station_code": station_code or _uniq("ST"),
        "location": location,
        "equipment_tags": [] if equipment_tags is None else equipment_tags,
    }


def create_session_payload(study_id, starts_at, ends_at, seat_capacity=5,
                           mode="REMOTE", station_id=None) -> dict:
    payload = {
        "study_id": study_id,
        "mode": mode,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "seat_capacity": seat_capacity,
    }
    if station_id is not None:
        payload["station_id"] = station_id
    return payload


def create_booking_payload(session_id) -> dict:
    return {"session_id": session_id}


def create_instrument_payload(study_id, title="Survey", questions=None,
                              pass_threshold=50) -> dict:
    return {
        "study_id": study_id,
        "title": title,
        "questions": [{"question_key": "q1", "weight": 1, "max_points": 10}]
        if questions is None else questions,
        "pass_threshold": pass_threshold,
    }


def create_response_payload(instrument_id, session_id, answers=None) -> dict:
    return {
        "instrument_id": instrument_id,
        "session_id": session_id,
        "answers": [{"question_key": "q1", "points": 8}] if answers is None else answers,
    }


def create_ticket_payload(study_id, title="Issue", severity="MEDIUM", reach_count=10,
                          reproducibility_pct=0.5, session_id=None,
                          survey_response_id=None) -> dict:
    payload = {
        "study_id": study_id,
        "title": title,
        "severity": severity,
        "reach_count": reach_count,
        "reproducibility_pct": reproducibility_pct,
    }
    if session_id is not None:
        payload["session_id"] = session_id
    if survey_response_id is not None:
        payload["survey_response_id"] = survey_response_id
    return payload


def create_payout_payload(study_id, participant_id) -> dict:
    return {"study_id": study_id, "participant_id": participant_id}


def create_breach_payload(participant_id, study_id, evidence_summary="Leak evidence",
                          severity="MINOR") -> dict:
    return {
        "participant_id": participant_id,
        "study_id": study_id,
        "evidence_summary": evidence_summary,
        "severity": severity,
    }
