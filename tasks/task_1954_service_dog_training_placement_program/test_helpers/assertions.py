"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from datetime import datetime

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, entity: str):
    assert isinstance(data, dict), f"{entity} payload must be an object"
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be a positive integer"
    )


def assert_timestamp_instant(value: str, expected_iso: str, label: str):
    """Two timestamps denote the same instant (PRD §2.4/§2.5 pin the instant;
    the rendering of fractional digits is left to the serializer)."""
    def _parse(v: str) -> datetime:
        return datetime.fromisoformat(v.replace("Z", "+00:00"))

    assert _parse(value) == _parse(expected_iso), (
        f"{label} must be the instant {expected_iso}, got {value}"
    )


def assert_date_prefix(value: str, expected_date: str, label: str):
    """Date portion matches (PRD date arithmetic is stated in days; the time
    rendering of date-typed fields is left to the serializer)."""
    assert isinstance(value, str) and value[:10] == expected_date, (
        f"{label} must fall on {expected_date}, got {value}"
    )


def assert_applicant(data: dict):
    _assert_common(data, "Applicant")
    assert data["application_status"] in [
        "SUBMITTED", "IN_REVIEW", "NEEDS_INFO", "WAITLISTED", "MATCH_ELIGIBLE",
        "MATCHED", "TEAM_TRAINING", "PLACED", "DENIED", "WITHDRAWN",
    ]
    assert data["placement_track"] in ["MOBILITY", "PTSD", "AUTISM", "FACILITY"]
    assert isinstance(data["household_income_cents"], int)


def assert_assessment(data: dict):
    _assert_common(data, "TaskAssessment")
    assert data["status"] in ["DRAFT", "FINALIZED_ACCEPTED", "FINALIZED_REJECTED"]
    assert isinstance(data["required_tasks"], list) and len(data["required_tasks"]) >= 1
    assert 0 <= data["home_environment_score"] <= 10


def assert_waitlist_entry(data: dict):
    _assert_common(data, "WaitlistEntry")
    assert data["status"] in ["PENDING", "ELIGIBLE", "MATCHED", "SUSPENDED", "CLOSED"]
    assert isinstance(data["raised_cents"], int) and data["raised_cents"] >= 0
    assert isinstance(data["dissolved_match_count"], int)
    assert data["dissolved_match_count"] >= 0


def assert_contribution(data: dict):
    _assert_common(data, "Contribution")
    assert data["status"] in ["PLEDGED", "RECEIVED", "REFUNDED", "VOID"]
    assert isinstance(data["amount_cents"], int)


def assert_raiser(data: dict):
    _assert_common(data, "PuppyRaiser")
    assert data["status"] in [
        "APPLIED", "VETTED", "APPROVED", "ACTIVE", "ON_HIATUS", "INACTIVE",
    ]
    assert isinstance(data["current_dog_count"], int) and data["current_dog_count"] >= 0


def assert_trainer(data: dict):
    _assert_common(data, "Trainer")
    assert data["status"] in ["PROBATION", "CERTIFIED", "SUSPENDED", "INACTIVE"]


def assert_dog(data: dict):
    _assert_common(data, "Dog")
    assert data["status"] in [
        "REGISTERED", "IN_HEALTH_SCREENING", "CLEARED", "RAISER_PLACED",
        "RECALLED", "IN_ADVANCED_TRAINING", "MATCH_READY", "MATCHED",
        "TEAM_TRAINING", "PLACED", "CAREER_CHANGED", "RETIRED",
    ]
    assert data["origin"] in ["BRED", "DONATED"]


def assert_screening(data: dict):
    _assert_common(data, "HealthScreening")
    assert data["status"] in ["DRAFT", "CLEARED", "FAILED"]


def assert_raiser_placement(data: dict):
    _assert_common(data, "RaiserPlacement")
    assert data["status"] in ["ACTIVE", "COMPLETED", "EARLY_RETURN"]


def assert_milestone(data: dict):
    """Append-only: id + created_at present; updated_at/version absent (PRD §2.4)."""
    assert isinstance(data, dict), "TrainingMilestone payload must be an object"
    assert is_valid_uuid(data.get("id", "")), "TrainingMilestone.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "TrainingMilestone.created_at must be ISO 8601"
    )
    assert "version" not in data, "TrainingMilestone must not carry version"
    assert "updated_at" not in data, "TrainingMilestone must not carry updated_at"
    assert data["category"] in [
        "OBEDIENCE", "TASK_WORK", "PUBLIC_MANNERS", "SOCIALIZATION",
    ]
    assert 0 <= data["score"] <= 100


def assert_match(data: dict):
    _assert_common(data, "MatchRecord")
    assert data["status"] in [
        "PROPOSED", "ACCEPTED", "REJECTED", "DISSOLVED", "COMPLETED",
    ]


def assert_class(data: dict):
    _assert_common(data, "TeamTrainingClass")
    assert data["status"] in [
        "PLANNED", "ENROLLING", "IN_SESSION", "GRADUATION_REVIEW",
        "COMPLETED", "CANCELLED",
    ]
    assert isinstance(data["enrolled_count"], int) and data["enrolled_count"] >= 0


def assert_enrollment(data: dict):
    _assert_common(data, "Enrollment")
    assert data["status"] in ["ENROLLED", "GRADUATED", "FAILED", "WITHDRAWN"]
    assert isinstance(data["sessions_attended"], int)


def assert_pat(data: dict):
    _assert_common(data, "PublicAccessTest")
    assert data["status"] in ["SCHEDULED", "SCORED_PASS", "SCORED_FAIL", "INVALIDATED"]


def assert_partnership(data: dict):
    _assert_common(data, "Partnership")
    assert data["status"] in [
        "ACTIVE", "RECERT_DUE", "SUSPENDED", "RETIRED", "DISSOLVED",
    ]


def assert_followup(data: dict):
    _assert_common(data, "FollowUp")
    assert data["status"] in ["SCHEDULED", "COMPLETED", "MISSED", "WAIVED"]


def assert_recertification(data: dict):
    _assert_common(data, "Recertification")
    assert data["status"] in [
        "SCHEDULED", "COMPLETED_PASS", "REMEDIATION", "FAILED_FINAL",
    ]


def assert_support_request(data: dict):
    _assert_common(data, "SupportRequest")
    assert data["status"] in [
        "OPEN", "TRIAGED", "IN_PROGRESS", "RESOLVED", "CLOSED", "REOPENED",
    ]
