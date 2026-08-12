"""Payload factories — one per entity, input fields only (PRD section 3)."""

from .constants import STANDARD_TRACK

DEFAULTS = {
    "PROVIDER_NAME": "Dr. Priya Primary",
    "SPECIALIST_NAME": "Dr. Sam Specialist",
    "REVIEWER_NAME": "Dr. Quinn Reviewer",
    "QUESTION_TEXT": "Structured clinical question meeting the twenty character minimum.",
    "RECOMMENDATION_TEXT": "Clinical recommendation meeting the twenty character minimum.",
}


def create_specialty_track_payload(**overrides) -> dict:
    defaults = {"specialty_code": "CARDIOLOGY", **STANDARD_TRACK}
    defaults.update(overrides)
    return defaults


def create_referring_provider_payload(**overrides) -> dict:
    defaults = {"full_name": DEFAULTS["PROVIDER_NAME"], "npi": "1000000001"}
    defaults.update(overrides)
    return defaults


def create_specialist_payload(**overrides) -> dict:
    defaults = {"full_name": DEFAULTS["SPECIALIST_NAME"], "npi": "2000000001"}
    defaults.update(overrides)
    return defaults


def create_panel_membership_payload(specialist_id: str, specialty_track_id: str,
                                    **overrides) -> dict:
    defaults = {"specialist_id": specialist_id, "specialty_track_id": specialty_track_id}
    defaults.update(overrides)
    return defaults


def create_availability_window_payload(membership_id: str, window_start: str,
                                       window_end: str, **overrides) -> dict:
    defaults = {
        "membership_id": membership_id,
        "window_start": window_start,
        "window_end": window_end,
    }
    defaults.update(overrides)
    return defaults


def create_consult_request_payload(specialty_track_id: str, patient_ref: str = "PAT-0001",
                                   **overrides) -> dict:
    defaults = {
        "patient_ref": patient_ref,
        "specialty_track_id": specialty_track_id,
        "question_text": DEFAULTS["QUESTION_TEXT"],
        "icd10_primary": "I10",
        "urgency": "ROUTINE",
    }
    defaults.update(overrides)
    return defaults


def create_response_payload(disposition: str = "MANAGE_IN_PRIMARY_CARE",
                            **overrides) -> dict:
    defaults = {
        "disposition": disposition,
        "recommendation_text": DEFAULTS["RECOMMENDATION_TEXT"],
    }
    defaults.update(overrides)
    return defaults


def create_clarification_payload(body: str = "Please clarify the relevant history.",
                                 **overrides) -> dict:
    defaults = {"body": body}
    defaults.update(overrides)
    return defaults


def create_documentation_payload(record_type: str) -> dict:
    return {"record_type": record_type}


def create_revise_payload(**overrides) -> dict:
    defaults = {"recommendation_text": DEFAULTS["RECOMMENDATION_TEXT"]}
    defaults.update(overrides)
    return defaults


def create_quality_review_payload(response_id: str, **overrides) -> dict:
    defaults = {"response_id": response_id}
    defaults.update(overrides)
    return defaults


def create_complete_review_payload(timeliness_score: int = 5, appropriateness_score: int = 5,
                                   clarity_score: int = 5, verdict: str = "PASS",
                                   **overrides) -> dict:
    defaults = {
        "timeliness_score": timeliness_score,
        "appropriateness_score": appropriateness_score,
        "clarity_score": clarity_score,
        "verdict": verdict,
    }
    defaults.update(overrides)
    return defaults


def create_conversion_payload(appointment_start: str = "2026-06-10T10:00:00Z",
                              appointment_end: str = "2026-06-10T10:30:00Z",
                              **overrides) -> dict:
    defaults = {
        "appointment_start": appointment_start,
        "appointment_end": appointment_end,
    }
    defaults.update(overrides)
    return defaults


def create_measurement_payload(specialty_track_id: str, period_key: str = "2026-06",
                               **overrides) -> dict:
    defaults = {"specialty_track_id": specialty_track_id, "period_key": period_key}
    defaults.update(overrides)
    return defaults
