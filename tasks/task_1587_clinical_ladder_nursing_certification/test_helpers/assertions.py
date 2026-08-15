"""Entity assertions and domain invariant checkers (PRD §2.4, §3.1-§3.7)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601 UTC"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601 UTC"
    )
    assert isinstance(data.get("version"), int), f"{entity}.version must be int"


def _assert_append_only_fields(data: dict, entity: str):
    """PRD §2.4: AdvancementDecision and RetentionSnapshot carry only id and
    created_at from the common set; updated_at and version are absent."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601 UTC"
    )
    assert "updated_at" not in data, f"{entity} must not expose updated_at"
    assert "version" not in data, f"{entity} must not expose version"


def assert_nurse(data: dict):
    _assert_common_fields(data, "Nurse")
    assert isinstance(data["employee_code"], str) and data["employee_code"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["home_unit"], str) and data["home_unit"]
    assert data["current_level"] in ("CN_I", "CN_II", "CN_III", "CN_IV")
    assert data["differential_status"] in (
        "INACTIVE", "ACTIVE", "SUSPENDED", "TERMINATED",
    )


def assert_ladder_criterion(data: dict):
    _assert_common_fields(data, "LadderCriterion")
    assert data["target_level"] in ("CN_II", "CN_III", "CN_IV")
    assert isinstance(data["min_portfolio_score"], int)
    assert isinstance(data["min_participation_points"], int)
    assert data["required_certification_track"] in (
        "NONE", "BASIC", "SPECIALTY", "ADVANCED",
    )
    assert isinstance(data["differential_monthly_cents"], int)


def assert_participation_event(data: dict):
    _assert_common_fields(data, "ParticipationEvent")
    assert data["event_kind"] in (
        "COMMITTEE_SEAT", "QI_PROJECT", "PEER_EDUCATION",
        "EBP_RESEARCH", "PRECEPTORSHIP",
    )
    assert isinstance(data["points"], int)
    assert data["status"] in ("PENDING_VERIFICATION", "VERIFIED", "VOIDED")


def assert_certification(data: dict):
    _assert_common_fields(data, "Certification")
    assert data["track"] in ("BASIC", "SPECIALTY", "ADVANCED")
    assert isinstance(data["exam_fee_cents"], int)
    assert data["status"] in ("CURRENT", "LAPSED", "REVOKED")


def assert_reimbursement_claim(data: dict):
    _assert_common_fields(data, "ReimbursementClaim")
    assert isinstance(data["claimed_amount_cents"], int)
    assert data["status"] in ("SUBMITTED", "APPROVED", "PAID", "DENIED")


def assert_certification_bonus(data: dict):
    _assert_common_fields(data, "CertificationBonus")
    assert isinstance(data["bonus_amount_cents"], int)
    assert data["status"] in ("ACCRUED", "PAID", "CLAWED_BACK")


def assert_application(data: dict):
    _assert_common_fields(data, "Application")
    assert data["target_level"] in ("CN_II", "CN_III", "CN_IV")
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "IN_REVIEW", "RETURNED_FOR_REVISION",
        "APPROVED", "DENIED", "WITHDRAWN",
    )
    assert isinstance(data["review_cycle"], int)


def assert_review_assignment(data: dict):
    _assert_common_fields(data, "ReviewAssignment")
    assert data["status"] in ("PENDING", "SCORED", "RECUSED", "EXPIRED")


def assert_advancement_decision(data: dict):
    _assert_append_only_fields(data, "AdvancementDecision")
    assert data["outcome"] in ("APPROVE", "DENY")
    assert isinstance(data["criterion_version_snapshot"], int)


def assert_anniversary_review(data: dict):
    _assert_common_fields(data, "AnniversaryReview")
    assert isinstance(data["review_year"], int)
    assert data["outcome"] in ("OPEN", "SUSTAIN", "DEMOTE", "LAPSE")


def assert_budget_line(data: dict):
    _assert_common_fields(data, "BudgetLine")
    assert isinstance(data["unit"], str) and data["unit"]
    assert isinstance(data["fiscal_year"], int)
    assert isinstance(data["allocated_cents"], int)
    assert data["forecast_variant"] in ("PROVISIONAL", "FINAL")


def assert_retention_snapshot(data: dict):
    _assert_append_only_fields(data, "RetentionSnapshot")
    assert isinstance(data["unit"], str) and data["unit"]
    assert isinstance(data["headcount_by_level"], dict)


def assert_nurse_invariants(data: dict):
    """Domain invariants on a nurse record that must hold at all times."""
    risk = data.get("retention_risk_score")
    assert risk is not None, "Nurse.retention_risk_score must be present"
    assert 0 <= risk <= 100, f"retention_risk_score {risk} outside 0..100"
