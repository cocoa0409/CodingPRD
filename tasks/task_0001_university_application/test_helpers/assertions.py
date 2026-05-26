"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_APPLICATION_STATES = {
    "DRAFT", "SUBMITTED", "UNDER_REVIEW", "ADMITTED", "WAITLISTED",
    "DENIED", "ENROLLED", "DECLINED", "WITHDRAWN",
}
_ADMISSION_TRACKS = {"EARLY_DECISION", "EARLY_ACTION", "REGULAR", "ROLLING"}
_RESIDENCIES = {"IN_STATE", "OUT_OF_STATE", "INTERNATIONAL"}
_YIELD_POSTURES = {"OPEN", "ON_TARGET", "OVER_TARGET"}
_RECOMMENDATION_STATES = {"INVITED", "SUBMITTED", "WAIVED"}
_AID_PACKAGE_STATES = {"DRAFT", "FINALIZED", "REVOKED"}
_WAITLIST_STATES = {"PENDING", "PROMOTED", "RELEASED"}
_APPLICANT_PROFILE_STATES = {"DRAFT", "LOCKED"}
_PROFILE_TYPES = {"FAFSA", "CSS_PROFILE"}


def _assert_common_fields(data: dict, entity_label: str) -> None:
    """Validate id + created_at + updated_at + version (common_fields: true)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_label}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_label}.version must be a positive integer"
    )


def assert_applicant(data: dict) -> None:
    _assert_common_fields(data, "Applicant")
    assert isinstance(data.get("email"), str) and len(data["email"]) > 0
    assert isinstance(data.get("full_name"), str) and len(data["full_name"]) > 0
    assert isinstance(data.get("gpa_unweighted"), (int, float))
    assert 0.0 <= float(data["gpa_unweighted"]) <= 4.0
    sat = data.get("sat_total")
    assert sat is None or (isinstance(sat, int) and 400 <= sat <= 1600)
    assert data.get("residency") in _RESIDENCIES
    assert data.get("profile_status") in _APPLICANT_PROFILE_STATES
    assert isinstance(data.get("submitted_application_count"), int)
    assert data["submitted_application_count"] >= 0


def assert_school(data: dict) -> None:
    _assert_common_fields(data, "School")
    assert isinstance(data.get("name"), str)
    assert isinstance(data.get("state_code"), str)
    assert data.get("admission_track") in _ADMISSION_TRACKS
    assert is_iso8601_timestamp(data.get("deadline_iso", ""))
    assert is_iso8601_timestamp(data.get("decision_release_iso", ""))
    assert isinstance(data.get("target_class_size"), int)
    assert 1 <= data["target_class_size"] <= 10000
    assert isinstance(data.get("assumed_yield_rate"), (int, float))
    assert 0.05 <= float(data["assumed_yield_rate"]) <= 1.00
    assert isinstance(data.get("in_state_tuition_cents"), int) and data["in_state_tuition_cents"] >= 0
    assert isinstance(data.get("out_of_state_tuition_cents"), int)
    assert isinstance(data.get("international_tuition_cents"), int)
    assert isinstance(data.get("admitted_count"), int) and data["admitted_count"] >= 0
    assert isinstance(data.get("enrolled_count"), int) and data["enrolled_count"] >= 0
    assert isinstance(data.get("declined_count"), int) and data["declined_count"] >= 0
    assert isinstance(data.get("denied_count"), int) and data["denied_count"] >= 0
    assert data.get("yield_posture") in _YIELD_POSTURES


def assert_application(data: dict) -> None:
    _assert_common_fields(data, "Application")
    assert is_valid_uuid(data.get("applicant_id", ""))
    assert is_valid_uuid(data.get("school_id", ""))
    assert data.get("status") in _APPLICATION_STATES


def assert_essay(data: dict) -> None:
    _assert_common_fields(data, "Essay")
    assert is_valid_uuid(data.get("application_id", ""))
    assert isinstance(data.get("prompt_code"), str)
    assert isinstance(data.get("word_count"), int)
    assert 1 <= data["word_count"] <= 650
    assert isinstance(data.get("text"), str)
    assert isinstance(data.get("completed"), bool)


def assert_recommendation_request(data: dict) -> None:
    _assert_common_fields(data, "RecommendationRequest")
    assert is_valid_uuid(data.get("applicant_id", ""))
    assert is_valid_uuid(data.get("school_id", ""))
    assert isinstance(data.get("recommender_email"), str)
    assert data.get("status") in _RECOMMENDATION_STATES


def assert_financial_aid_profile(data: dict) -> None:
    _assert_common_fields(data, "FinancialAidProfile")
    assert is_valid_uuid(data.get("applicant_id", ""))
    assert data.get("profile_type") in _PROFILE_TYPES
    assert isinstance(data.get("household_income_cents"), int)
    assert data["household_income_cents"] >= 0
    assert isinstance(data.get("household_size"), int)
    assert 1 <= data["household_size"] <= 20
    assert isinstance(data.get("expected_family_contribution_cents"), int)


def assert_aid_package(data: dict) -> None:
    _assert_common_fields(data, "AidPackage")
    assert is_valid_uuid(data.get("application_id", ""))
    assert data.get("status") in _AID_PACKAGE_STATES
    assert isinstance(data.get("grant_cents"), int) and data["grant_cents"] >= 0
    assert isinstance(data.get("loan_cents"), int) and data["loan_cents"] >= 0
    assert isinstance(data.get("work_study_cents"), int) and data["work_study_cents"] >= 0


def assert_waitlist_entry(data: dict) -> None:
    _assert_common_fields(data, "WaitlistEntry")
    assert is_valid_uuid(data.get("application_id", ""))
    assert isinstance(data.get("rank"), int) and data["rank"] >= 1
    assert data.get("status") in _WAITLIST_STATES
