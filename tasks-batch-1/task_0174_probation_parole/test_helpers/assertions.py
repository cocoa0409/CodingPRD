"""Entity assertions and domain invariant checkers.

Each assert_{entity} validates the response shape against the PRD contract.
Append-only Payment must NOT carry updated_at/version (PRD §2.4).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .constants import LSI_R_DOMAINS


def _assert_common(data: dict):
    """id + created_at + updated_at + version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_officer(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["badge_number"], str) and len(data["badge_number"]) > 0
    assert data["role_type"] in ("PROBATION", "PAROLE")
    assert isinstance(data["active"], bool)


def assert_supervisee(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["docket_number"], str) and len(data["docket_number"]) > 0
    assert data["supervision_type"] in ("PROBATION", "PAROLE")
    assert data["status"] in (
        "INTAKE", "ACTIVE", "ABSCONDED", "REVOCATION_PENDING",
        "REVOKED", "TERMINATED_EARLY", "COMPLETED", "TRANSFERRED_OUT",
    )
    assert data["supervision_level"] in (
        "ADMINISTRATIVE", "MINIMUM", "MEDIUM", "MAXIMUM",
    )
    assert isinstance(data["cumulative_violation_points"], int)
    assert isinstance(data["restitution_balance_cents"], int)
    assert isinstance(data["fee_balance_cents"], int)
    assert_supervisee_invariants(data)


def assert_supervisee_invariants(data: dict):
    """Domain invariants that must hold after any operation (PRD §2.8)."""
    assert data["cumulative_violation_points"] >= 0, "points never negative"
    assert data["restitution_balance_cents"] >= 0, "restitution balance never negative"
    assert data["fee_balance_cents"] >= 0, "fee balance never negative"


def assert_risk_assessment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("supervisee_id", ""))
    assert isinstance(data["total_score"], int)
    assert 0 <= data["total_score"] <= 54, "total_score in 0..54"
    assert data["derived_level"] in (
        "ADMINISTRATIVE", "MINIMUM", "MEDIUM", "MAXIMUM",
    )
    assert data["assessment_status"] in ("DRAFT", "ADOPTED", "SUPERSEDED")
    assert isinstance(data["domain_scores"], dict)


def assert_condition(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("supervisee_id", ""))
    assert data["condition_type"] in (
        "DRUG_TESTING", "CURFEW", "NO_CONTACT", "EMPLOYMENT",
        "TREATMENT", "ELECTRONIC_MONITORING", "TRAVEL_RESTRICTION",
    )
    assert data["minimum_level_required"] in (
        "ADMINISTRATIVE", "MINIMUM", "MEDIUM", "MAXIMUM",
    )
    assert data["status"] in (
        "PROPOSED", "ACTIVE", "SATISFIED", "WAIVED", "SUSPENDED",
    )


def assert_check_in(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("supervisee_id", ""))
    assert is_iso8601_timestamp(data.get("scheduled_for", ""))
    assert isinstance(data["window_minutes"], int) and data["window_minutes"] >= 1
    assert isinstance(data["requires_drug_test"], bool)
    assert data["status"] in ("SCHEDULED", "ATTENDED", "MISSED", "EXCUSED")
    assert data.get("punctuality") in ("ON_TIME", "LATE", None)


def assert_drug_test(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("check_in_id", ""))
    assert data["panel"] in ("FIVE_PANEL", "TEN_PANEL")
    assert data["result"] in ("NEGATIVE", "POSITIVE", "DILUTE", "REFUSED")
    assert isinstance(data["substances"], list)


def assert_violation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("supervisee_id", ""))
    assert data["violation_class"] in (
        "TECHNICAL", "MISDEMEANOR", "FELONY", "ABSCOND",
    )
    assert isinstance(data["points"], int) and data["points"] >= 0
    assert data["status"] in ("FILED", "SUSTAINED", "DISMISSED", "APPEALED")


def assert_sanction(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("violation_id", ""))
    assert data["sanction_type"] in (
        "VERBAL_WARNING", "INCREASED_REPORTING", "CURFEW_IMPOSITION",
        "JAIL_SHOCK", "REVOCATION_REFERRAL",
    )
    assert isinstance(data["imposed_days"], int) and data["imposed_days"] >= 0
    assert data["status"] in ("IMPOSED", "COMPLETED", "VACATED")


def assert_obligation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("supervisee_id", ""))
    assert data["obligation_type"] in ("RESTITUTION", "FEE")
    assert isinstance(data["principal_cents"], int) and data["principal_cents"] >= 1
    assert isinstance(data["paid_cents"], int) and data["paid_cents"] >= 0
    assert data["status"] in ("OPEN", "PARTIALLY_PAID", "PAID", "DISCHARGED")


def assert_payment(data: dict):
    """Payment is append-only (PRD §2.4): id + created_at only, NO version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "Payment must not carry a version field"
    assert "updated_at" not in data, "Payment must not carry an updated_at field"
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1


def assert_court_report(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("supervisee_id", ""))
    assert data["report_type"] in (
        "PROGRESS", "VIOLATION_SUMMARY", "EARLY_TERMINATION", "REVOCATION",
    )
    assert data["status"] in ("DRAFT", "FILED")
    assert isinstance(data["snapshot"], dict)


def assert_transfer(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("supervisee_id", ""))
    assert isinstance(data["receiving_state_code"], str)
    assert data["status"] in ("REQUESTED", "ACCEPTED", "REJECTED", "WITHDRAWN")


def assert_early_termination(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("supervisee_id", ""))
    assert isinstance(data["months_served"], int)
    assert isinstance(data["eligibility"], dict)
    assert data["status"] in ("SUBMITTED", "GRANTED", "DENIED")
