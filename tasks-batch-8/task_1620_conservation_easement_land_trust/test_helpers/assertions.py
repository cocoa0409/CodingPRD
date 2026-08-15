"""Entity assertions and domain invariant checkers (PRD §2.4, §2.5, §3).

Each assert_<entity>() verifies the system-managed common fields plus the
presence and typing of the entity's declared fields. EndowmentTransaction is
the deliberate exception: it carries id and created_at only — no updated_at
and no version (PRD §2.4).
"""
import re

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def is_iso_date(value) -> bool:
    """True for YYYY-MM-DD calendar-date strings (PRD §2.7)."""
    return bool(_ISO_DATE_RE.match(value)) if isinstance(value, str) else False


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a server-minted UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version starts at 1"


def _assert_nullable_date(data: dict, field: str):
    value = data.get(field)
    assert value is None or is_iso_date(value), f"{field} must be null or YYYY-MM-DD, got {value!r}"


def assert_easement(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["easement_name"], str) and data["easement_name"]
    assert isinstance(data["grantor_name"], str) and data["grantor_name"]
    assert isinstance(data["parcel_acreage"], int) and data["parcel_acreage"] > 0
    matrix = data["permitted_use_matrix"]
    assert isinstance(matrix, dict) and len(matrix) >= 1, "matrix needs at least one use-type entry"
    assert all(v in ("PERMITTED", "DISCRETIONARY", "PROHIBITED") for v in matrix.values())
    assert isinstance(data["monitoring_interval_months"], int)
    assert 6 <= data["monitoring_interval_months"] <= 36
    assert data["status"] in ("DRAFT", "RECORDED")
    assert data["posture"] in ("ENFORCEMENT_ACTIVE", "VIOLATION_OPEN", "MONITORING_DUE", "GOOD_STANDING")
    assert data["current_landowner_id"] is None or isinstance(data["current_landowner_id"], str)
    _assert_nullable_date(data, "recorded_on")
    _assert_nullable_date(data, "last_monitoring_completed_on")
    _assert_nullable_date(data, "next_monitoring_due_on")
    assert isinstance(data["open_violation_count"], int) and data["open_violation_count"] >= 0
    assert isinstance(data["amendment_count"], int) and data["amendment_count"] >= 0


def assert_landowner(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["easement_id"], str)
    assert data["status"] in ("ACTIVE", "PENDING_SUCCESSION", "SUPERSEDED")
    assert isinstance(data["owner_name"], str) and data["owner_name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert data.get("predecessor_landowner_id") is None or isinstance(data["predecessor_landowner_id"], str)
    _assert_nullable_date(data, "acquired_on")


def assert_baseline_report(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["easement_id"], str)
    assert isinstance(data["prepared_by_user_id"], str)
    assert isinstance(data["condition_narrative"], str)
    assert isinstance(data["photo_point_count"], int) and data["photo_point_count"] >= 0
    assert isinstance(data["review_round"], int) and data["review_round"] >= 0
    assert data["status"] in ("DRAFT", "SUBMITTED", "REVISION_REQUESTED", "ACCEPTED")


def assert_monitoring_visit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["easement_id"], str)
    assert isinstance(data["monitor_user_id"], str)
    assert is_iso_date(data["window_start_on"])
    assert is_iso_date(data["window_end_on"])
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED")


def assert_violation(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["easement_id"], str)
    assert isinstance(data["detected_by_user_id"], str)
    assert isinstance(data["violation_type"], str)
    assert data["severity"] in ("MINOR", "MATERIAL", "IRREPARABLE")
    assert is_iso_date(data["detected_on"])
    assert data["status"] in ("OPEN", "NOTICE_SENT", "CURE_IN_PROGRESS", "ESCALATED", "RESOLVED")
    _assert_nullable_date(data, "notice_served_on")
    _assert_nullable_date(data, "cure_deadline_on")
    _assert_nullable_date(data, "resolved_on")


def assert_amendment_request(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["easement_id"], str)
    assert isinstance(data["submitted_by_user_id"], str)
    assert isinstance(data["requested_changes"], list) and len(data["requested_changes"]) >= 1
    for change in data["requested_changes"]:
        assert change["new_level"] in ("PERMITTED", "DISCRETIONARY", "PROHIBITED")
    assert isinstance(data["affected_acreage"], int) and data["affected_acreage"] >= 1
    assert isinstance(data["materiality_score"], int) and 0 <= data["materiality_score"] <= 100
    assert data["review_path"] in ("STAFF", "BOARD")
    assert data["status"] in (
        "SUBMITTED", "STAFF_REVIEW", "REVISION_REQUESTED", "BOARD_REVIEW",
        "APPROVED", "REJECTED", "WITHDRAWN",
    )


def assert_use_authorization(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["easement_id"], str)
    assert isinstance(data["use_type"], str)
    assert isinstance(data["requested_by_landowner_id"], str)
    assert isinstance(data["justification"], str)
    assert data["status"] in ("REQUESTED", "APPROVED", "APPROVED_WITH_CONDITIONS", "DENIED")
    assert isinstance(data["conditions_breached"], bool)


def assert_enforcement_action(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["violation_id"], str)
    assert isinstance(data["easement_id"], str)
    assert data["status"] in ("PROPOSED", "EXECUTED", "BREACHED", "COMPLETED")


def assert_succession_notice(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["easement_id"], str)
    assert isinstance(data["successor_landowner_id"], str)
    assert isinstance(data["predecessor_landowner_id"], str)
    assert is_iso_date(data["transfer_on"])
    _assert_nullable_date(data, "notice_given_on")
    _assert_nullable_date(data, "ack_deadline_on")
    _assert_nullable_date(data, "recorded_on")
    assert data["status"] in ("NOTICE_GIVEN", "ACKNOWLEDGED", "RECORDED", "EXPIRED")


def assert_appraisal(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["easement_id"], str)
    assert isinstance(data["appraiser_user_id"], str)
    assert is_iso_date(data["effective_on"])
    assert is_iso_date(data["gift_on"])
    assert isinstance(data["contiguous_enhancement_applies"], bool)
    assert data["status"] in ("ENGAGED", "DELIVERED", "CERTIFIED", "WITHDRAWN")


def assert_endowment_fund(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["easement_id"], str)
    assert isinstance(data["spending_rate_bps"], int) and 100 <= data["spending_rate_bps"] <= 800
    assert isinstance(data["principal_floor_cents"], int) and data["principal_floor_cents"] >= 0
    assert data["status"] in ("INITIALIZING", "ACTIVE")
    assert isinstance(data["market_value_cents"], int)
    assert isinstance(data["fiscal_year"], int) and data["fiscal_year"] >= 1
    assert isinstance(data["prior_year_close_mv_cents"], int)
    assert isinstance(data["provisional_draws_ytd_cents"], int)
    assert isinstance(data["policy_draw_allowance_cents"], int)
    assert isinstance(data["carryover_allowance_cents"], int)
    assert isinstance(data["unitized_draw_capacity_cents"], int)


def assert_endowment_transaction(data: dict):
    """Append-only ledger event: id + created_at only, no updated_at/version
    (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a server-minted UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert "updated_at" not in data, "ledger entries must not expose updated_at"
    assert "version" not in data, "ledger entries must not expose version"
    assert isinstance(data["fund_id"], str)
    assert data["txn_type"] in ("CONTRIBUTION", "INVESTMENT_RETURN", "DRAW")
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["fiscal_year"], int) and data["fiscal_year"] >= 1
    assert is_iso_date(data["posted_on"])
