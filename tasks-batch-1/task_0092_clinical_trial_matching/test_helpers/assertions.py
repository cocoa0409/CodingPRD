"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict) -> None:
    """Common resource properties carried by all eleven entity types (PRD §2.4):
    a UUID `id` with no type prefix, an ISO 8601 `created_at`/`updated_at`, and
    an integer `version`."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID with no type prefix, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_trial(data: dict) -> None:
    _assert_common(data)
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert isinstance(data["target_enrollment"], int) and data["target_enrollment"] >= 1
    assert data["randomization_method"] in ("SIMPLE", "PERMUTED_BLOCK")
    assert data["irb_status"] in ("NONE", "PENDING", "APPROVED", "REJECTED")
    assert data["posture"] in ("SETUP", "OPEN", "FROZEN")
    assert isinstance(data["enrolled_count"], int) and data["enrolled_count"] >= 0
    assert isinstance(data["active_safety_holds"], int) and data["active_safety_holds"] >= 0


def assert_criterion(data: dict) -> None:
    _assert_common(data)
    assert data["kind"] in ("INCLUSION", "EXCLUSION")
    assert data["attribute"] in (
        "age_years", "weight_kg", "hba1c", "prior_trials_count", "biomarker_positive",
    )
    assert data["comparator"] in ("GE", "GT", "LE", "LT", "EQ")


def assert_arm(data: dict) -> None:
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["allocation_weight"], int) and data["allocation_weight"] >= 1
    assert isinstance(data["assigned_count"], int) and data["assigned_count"] >= 0


def assert_consent_document(data: dict) -> None:
    _assert_common(data)
    assert isinstance(data["version_number"], int) and data["version_number"] >= 1
    assert data["status"] in ("DRAFT", "IRB_APPROVED", "ACTIVE", "SUPERSEDED")


def assert_irb_review(data: dict) -> None:
    _assert_common(data)
    assert data["scope"] in ("PROTOCOL", "CONSENT")
    assert data["decision"] in ("PENDING", "APPROVED", "REJECTED", "REVISE_REQUESTED")


def assert_participant(data: dict) -> None:
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["age_years"], int) and data["age_years"] >= 0
    assert isinstance(data["prior_trials_count"], int)
    assert isinstance(data["biomarker_positive"], bool)


def assert_screening(data: dict) -> None:
    _assert_common(data)
    assert data["match_result"] in ("ELIGIBLE", "INELIGIBLE")
    assert isinstance(data["failed_criteria_count"], int) and data["failed_criteria_count"] >= 0
    assert isinstance(data["match_score"], (int, float))
    assert 0.0 <= float(data["match_score"]) <= 1.0, "match_score is in the closed interval [0, 1] (PRD §3.3)"


def assert_enrollment(data: dict) -> None:
    _assert_common(data)
    assert data["enrollment_status"] in (
        "SCREENED", "CONSENTED", "RANDOMIZED", "ACTIVE", "COMPLETED", "WITHDRAWN",
    )
    assert data["safety_status"] in ("CLEAR", "FLAGGED", "HOLD")
    assert isinstance(data["completed_visits_count"], int) and data["completed_visits_count"] >= 0


def assert_visit(data: dict) -> None:
    _assert_common(data)
    assert isinstance(data["sequence_index"], int) and data["sequence_index"] >= 1
    assert isinstance(data["draw_window_minutes"], int) and data["draw_window_minutes"] >= 0
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED")
    assert isinstance(data["draw_in_window"], bool)
    assert isinstance(data["payable_amount_cents"], int)


def assert_adverse_event(data: dict) -> None:
    _assert_common(data)
    assert data["severity"] in ("MILD", "MODERATE", "SEVERE", "LIFE_THREATENING")
    assert isinstance(data["is_serious"], bool)
    assert data["report_status"] in (
        "REPORTED", "UNDER_REVIEW", "ADJUDICATED_RELATED", "ADJUDICATED_UNRELATED",
    )


def assert_compensation_payment(data: dict) -> None:
    _assert_common(data)
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["gross_cents"], int)
    assert isinstance(data["visit_ids"], list)
    assert data["status"] in ("PENDING", "PAID")
