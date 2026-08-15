"""Entity assertions and domain invariant checkers (PRD §2.5, §2.6, §3)."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp tolerantly (with or without fractional digits)."""
    assert isinstance(value, str), f"expected ISO timestamp string, got {value!r}"
    assert is_iso8601_timestamp(value), f"not an ISO 8601 UTC timestamp: {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601 UTC"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601 UTC"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be a positive integer"
    )


def assert_family(data: dict):
    _assert_common(data, "Family")
    assert data["status"] in ("INTAKE", "ACTIVE", "SUSPENDED", "CLOSED")
    for field in (
        "total_charged_cents",
        "total_refunded_cents",
        "total_paid_cents",
        "outstanding_balance_cents",
    ):
        assert isinstance(data[field], int), f"Family.{field} must be integer cents"
    assert data["billing_status"] in ("CURRENT", "DELINQUENT")


def assert_inv_money(family: dict):
    """INV-MONEY: outstanding == charged - refunded - paid (PRD §2.6)."""
    expected = (
        family["total_charged_cents"]
        - family["total_refunded_cents"]
        - family["total_paid_cents"]
    )
    assert family["outstanding_balance_cents"] == expected, (
        f"INV-MONEY violated: outstanding {family['outstanding_balance_cents']} "
        f"!= {family['total_charged_cents']} - {family['total_refunded_cents']} "
        f"- {family['total_paid_cents']}"
    )


def assert_client(data: dict):
    _assert_common(data, "Client")
    assert data["track"] in ("INDIVIDUAL", "GROUP", "HYBRID")
    assert data["status"] in ("INTAKE", "ACTIVE", "PAUSED", "DISCHARGED")
    assert isinstance(data["checkin_streak"], int)
    assert "active_plan_id" in data
    if data["active_plan_id"] is not None:
        assert is_valid_uuid(data["active_plan_id"])


def assert_coach(data: dict):
    _assert_common(data, "Coach")
    assert data["credential_level"] in ("ASSOCIATE", "CERTIFIED", "SUPERVISOR")
    assert data["status"] in ("AVAILABLE", "SUPERVISION_DEFICIT", "INACTIVE")
    assert isinstance(data["active_caseload"], int)
    assert isinstance(data["caseload_cap"], int)
    assert isinstance(data["required_supervision_hours"], int)
    assert isinstance(data["verified_supervision_hours_30d"], (int, float))


def assert_intake(data: dict):
    _assert_common(data, "IntakeAssessment")
    assert data["status"] in (
        "DRAFT",
        "SUBMITTED",
        "UNDER_REVIEW",
        "APPROVED",
        "NEEDS_REVISION",
    )
    assert isinstance(data["baseline_score"], int)


def assert_plan(data: dict):
    _assert_common(data, "CoachingPlan")
    assert data["status"] in (
        "DRAFT",
        "PROPOSED",
        "ACTIVE",
        "COMPLETED",
        "TERMINATED",
        "SUPERSEDED",
    )
    assert data["cadence"] in ("WEEKLY", "BIWEEKLY")
    assert data["posture"] in ("SCHEDULABLE", "SCHEDULING_BLOCKED")
    assert isinstance(data["revision_number"], int)
    assert isinstance(data["revision_recommended"], bool)
    assert "activated_at" in data


def assert_goal(data: dict):
    _assert_common(data, "Goal")
    assert data["status"] in (
        "SET",
        "IN_PROGRESS",
        "ACHIEVED",
        "DROPPED",
        "CARRIED_FORWARD",
    )
    assert "carried_to_plan_id" in data
    assert "resolved_at" in data


def assert_package(data: dict):
    _assert_common(data, "Package")
    assert data["track"] in ("INDIVIDUAL", "GROUP")
    assert data["status"] in ("ACTIVE", "EXHAUSTED", "EXPIRED", "REFUNDED")
    for field in (
        "credits_total",
        "credits_consumed",
        "credits_forfeited",
        "credits_remaining",
        "reserved_count",
        "price_paid_cents",
        "unit_gross_cents",
        "per_credit_value_cents",
    ):
        assert isinstance(data[field], int), f"Package.{field} must be an integer"
    assert is_iso8601_timestamp(data["purchased_at"])
    assert is_iso8601_timestamp(data["expires_at"])
    assert "refund_cents" in data


def assert_inv_credits(package: dict):
    """INV-CREDITS: remaining == total - consumed - forfeited (PRD §3.5)."""
    expected = (
        package["credits_total"]
        - package["credits_consumed"]
        - package["credits_forfeited"]
    )
    assert package["credits_remaining"] == expected, (
        f"INV-CREDITS violated: remaining {package['credits_remaining']} != "
        f"{package['credits_total']} - {package['credits_consumed']} "
        f"- {package['credits_forfeited']}"
    )


def assert_session(data: dict):
    _assert_common(data, "Session")
    assert data["attendance_state"] in (
        "SCHEDULED",
        "COMPLETED",
        "CANCELLED_EARLY",
        "CANCELLED_LATE",
        "NO_SHOW",
    )
    assert data["billing_state"] in ("RESERVED", "CONSUMED", "RETURNED", "FORFEITED")
    assert isinstance(data["cancellation_fee_cents"], int)
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert is_iso8601_timestamp(data["scheduled_end"])
    assert "resolved_at" in data


def assert_checkin(data: dict):
    _assert_common(data, "CheckIn")
    assert data["status"] in (
        "PENDING",
        "SUBMITTED_ON_TIME",
        "SUBMITTED_LATE",
        "MISSED",
        "ACKNOWLEDGED",
    )
    assert is_iso8601_timestamp(data["due_at"])
    assert "submitted_at" in data


def assert_progress_snapshot(data: dict):
    """Append-only snapshot: carries id and created_at only — never version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "ProgressSnapshot.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "ProgressSnapshot.created_at must be ISO 8601 UTC"
    )
    assert "version" not in data, "snapshots must not carry version"
    assert "updated_at" not in data, "snapshots must not carry updated_at"
    for field in (
        "goals_considered",
        "goals_achieved",
        "checkins_considered",
        "checkins_on_time",
    ):
        assert isinstance(data[field], int), f"ProgressSnapshot.{field} must be int"
    assert "rolling_index" in data
    assert "cumulative_index" in data


def assert_contact(data: dict):
    _assert_common(data, "CoordinationContact")
    assert data["contact_type"] in ("SCHOOL", "CLINICIAN")
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_consent(data: dict):
    _assert_common(data, "ConsentGrant")
    assert data["scope"] in ("PROGRESS_ONLY", "GOALS_AND_PROGRESS", "FULL_PLAN")
    assert data["status"] in (
        "PENDING_SIGNATURE",
        "ACTIVE",
        "REVOKED",
        "EXPIRED",
        "SUPERSEDED",
    )
    assert "signed_at" in data
    assert is_iso8601_timestamp(data["expires_at"])


def assert_note(data: dict):
    _assert_common(data, "CoordinationNote")
    assert data["topic"] in ("PROGRESS", "GOALS", "PLAN_DETAIL")
    assert data["status"] in ("DRAFT", "FINALIZED", "SHARED", "SEALED")
    assert "shared_with_contact_id" in data
    assert "shared_at" in data


def assert_workshop(data: dict):
    _assert_common(data, "Workshop")
    assert data["status"] in ("DRAFT", "OPEN", "LOCKED", "COMPLETED", "CANCELLED")
    assert isinstance(data["capacity"], int)
    assert isinstance(data["seats_taken"], int)
    assert isinstance(data["price_cents"], int)
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])


def assert_enrollment(data: dict):
    _assert_common(data, "WorkshopEnrollment")
    assert data["status"] in ("ENROLLED", "WAITLISTED", "DROPPED", "REFUNDED")
    assert data["billing_source"] in ("PACKAGE_CREDIT", "MONEY", "NONE")
    assert isinstance(data["charged_cents"], int)
    assert "waitlist_position" in data


def assert_supervision_record(data: dict):
    _assert_common(data, "SupervisionRecord")
    assert data["status"] in ("SCHEDULED", "HELD", "VERIFIED", "CANCELLED")
    assert isinstance(data["hours"], (int, float))
    assert "verified_at" in data
