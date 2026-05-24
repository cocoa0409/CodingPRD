"""Entity assertions for the University Application Platform."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


_APPLICANT_PROFILE_STATUSES = {"DRAFT", "READY"}
_APPLICATION_STATUSES = {
    "DRAFT", "SUBMITTED", "UNDER_REVIEW", "ADMITTED", "WAITLISTED", "DENIED",
    "DEFERRED", "WITHDRAWN", "ENROLLED", "DECLINED_OFFER",
}
_APPLICATION_PLANS = {"EARLY_DECISION", "EARLY_ACTION", "REGULAR", "ROLLING"}
_RECOMMENDER_INVITE_STATUSES = {"INVITED", "ACCEPTED", "DECLINED"}
_LETTER_STATUSES = {"REQUESTED", "IN_PROGRESS", "SUBMITTED", "WAIVED"}
_RELATIONSHIPS = {"TEACHER", "COUNSELOR", "OTHER"}
_FA_PROFILE_STATUSES = {"DRAFT", "SUBMITTED"}
_AID_OFFER_VARIANTS = {"FEDERAL", "INSTITUTIONAL"}
_SCHOOL_POSTURES = {"OPEN", "AT_TARGET", "OVER_TARGET"}


def _assert_common_fields(data: dict, entity_label: str):
    assert is_valid_uuid(data.get("id", "")), \
        f"{entity_label}.id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity_label}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity_label}.updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), \
        f"{entity_label}.version must be int, got {type(data.get('version'))}"
    assert data["version"] >= 1, \
        f"{entity_label}.version must be >= 1, got {data['version']}"


def assert_applicant(data: dict):
    _assert_common_fields(data, "Applicant")
    assert isinstance(data.get("email"), str) and len(data["email"]) > 0
    assert isinstance(data.get("full_name"), str)
    assert isinstance(data.get("gpa"), (int, float))
    assert 0.0 <= data["gpa"] <= 4.0
    sat = data.get("sat_total")
    assert sat is None or (isinstance(sat, int) and 400 <= sat <= 1600)
    assert data.get("profile_status") in _APPLICANT_PROFILE_STATUSES


def assert_recommender(data: dict):
    _assert_common_fields(data, "Recommender")
    assert isinstance(data.get("applicant_id"), str) and is_valid_uuid(data["applicant_id"])
    assert isinstance(data.get("email"), str) and len(data["email"]) > 0
    assert isinstance(data.get("full_name"), str)
    assert data.get("relationship") in _RELATIONSHIPS
    assert data.get("invite_status") in _RECOMMENDER_INVITE_STATUSES


def assert_school(data: dict):
    _assert_common_fields(data, "School")
    assert isinstance(data.get("name"), str) and len(data["name"]) > 0
    assert isinstance(data.get("target_class_size"), int) and data["target_class_size"] >= 1
    assert is_iso8601_timestamp(data["ed_deadline_iso"])
    assert is_iso8601_timestamp(data["ea_deadline_iso"])
    assert is_iso8601_timestamp(data["rd_deadline_iso"])
    assert isinstance(data.get("rolling_open"), bool)
    assert isinstance(data.get("requires_css_profile"), bool)
    assert isinstance(data.get("confirmed_enrollment_count"), int)
    assert data["confirmed_enrollment_count"] >= 0
    assert data.get("posture") in _SCHOOL_POSTURES


def assert_application(data: dict):
    _assert_common_fields(data, "Application")
    assert is_valid_uuid(data.get("applicant_id", ""))
    assert is_valid_uuid(data.get("school_id", ""))
    assert data.get("plan") in _APPLICATION_PLANS
    assert data.get("status") in _APPLICATION_STATUSES
    if data.get("submitted_at") is not None:
        assert is_iso8601_timestamp(data["submitted_at"])
    if data.get("decision_at") is not None:
        assert is_iso8601_timestamp(data["decision_at"])
    rank = data.get("waitlist_rank")
    assert rank is None or (isinstance(rank, int) and rank >= 1)
    if data.get("waitlist_added_at") is not None:
        assert is_iso8601_timestamp(data["waitlist_added_at"])


def assert_essay_submission(data: dict):
    _assert_common_fields(data, "EssaySubmission")
    assert is_valid_uuid(data.get("application_id", ""))
    assert isinstance(data.get("prompt_code"), str)
    assert isinstance(data.get("body"), str)
    assert isinstance(data.get("word_count"), int)
    assert data["word_count"] >= 1
    assert isinstance(data.get("locked"), bool)


def assert_recommendation_letter(data: dict):
    _assert_common_fields(data, "RecommendationLetter")
    assert is_valid_uuid(data.get("application_id", ""))
    assert is_valid_uuid(data.get("recommender_id", ""))
    assert data.get("status") in _LETTER_STATUSES
    body = data.get("body")
    assert body is None or isinstance(body, str)
    submitted_at = data.get("submitted_at")
    assert submitted_at is None or is_iso8601_timestamp(submitted_at)


def assert_financial_aid_profile(data: dict):
    _assert_common_fields(data, "FinancialAidProfile")
    assert is_valid_uuid(data.get("applicant_id", ""))
    assert isinstance(data.get("fafsa_efc_cents"), int) and data["fafsa_efc_cents"] >= 0
    css = data.get("css_efc_cents")
    assert css is None or (isinstance(css, int) and css >= 0)
    assert isinstance(data.get("family_income_cents"), int)
    assert data["family_income_cents"] >= 0
    assert data.get("status") in _FA_PROFILE_STATUSES


def assert_aid_offer(data: dict):
    _assert_common_fields(data, "AidOffer")
    assert is_valid_uuid(data.get("application_id", ""))
    assert data.get("variant") in _AID_OFFER_VARIANTS
    for field in (
        "cost_of_attendance_cents", "demonstrated_need_cents",
        "grant_cents", "loan_cents", "work_study_cents", "net_price_cents",
    ):
        assert isinstance(data.get(field), int), \
            f"AidOffer.{field} must be int, got {type(data.get(field))}"
        assert data[field] >= 0, \
            f"AidOffer.{field} must be >= 0, got {data[field]}"
    # PRD §3.6: net_price is floored at 0; grant capped at demonstrated need.
    assert data["grant_cents"] <= data["demonstrated_need_cents"]


def assert_admission_cycle(data: dict):
    _assert_common_fields(data, "AdmissionCycle")
    assert is_valid_uuid(data.get("school_id", ""))
    assert is_iso8601_timestamp(data["clock_iso"])
    last = data.get("last_yield_run_at")
    assert last is None or is_iso8601_timestamp(last)
    assert isinstance(data.get("yield_run_count"), int)
    assert data["yield_run_count"] >= 0
    assert isinstance(data.get("cooldown_ms"), int)
    assert data["cooldown_ms"] >= 0
