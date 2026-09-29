"""Entity assertions and domain invariant checkers drawn from the PRD."""

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import DECIMAL_TOLERANCE

VOLUNTEER_STATUSES = [
    "PROSPECT", "IN_TRAINING", "CERTIFIED", "PROBATION", "SUSPENDED", "RESIGNED",
]
CERTIFICATION_STATUSES = ["PENDING_EXAM", "PASSED", "FAILED", "EXPIRED", "REVOKED"]
PROPOSAL_STATUSES = [
    "DRAFT", "SUBMITTED", "IN_COMMITTEE", "REVISION_REQUESTED",
    "APPROVED", "DECLINED", "WITHDRAWN",
]
PROGRAMMING_STATUSES = [
    "APPROVED_UNSCHEDULED", "SCHEDULED", "ON_AIR_ACTIVE",
    "UNDER_REVIEW", "PROBATION", "CANCELLED",
]
COMPLIANCE_STANDINGS = ["CLEAR", "WATCH", "RESTRICTED"]
GRID_STATUSES = ["DRAFT", "IN_REVIEW", "PUBLISHED", "SUPERSEDED"]
SLOT_STATUSES = ["TENTATIVE", "CONFIRMED", "RELEASED", "PREEMPTED"]
AIR_STATUSES = ["SCHEDULED", "AIRED", "SUBSTITUTE_AIRED", "MISSED", "CANCELLED"]
LOG_STATUSES = ["NOT_REQUIRED", "PENDING", "SUBMITTED", "CERTIFIED", "DELINQUENT"]
ROYALTY_CLASSES = ["FEATURED", "INCIDENTAL", "EXEMPT"]
SPOT_STATUSES = [
    "DRAFT", "UNDER_REVIEW", "APPROVED", "APPROVED_WITH_EDITS", "REJECTED", "SUSPENDED",
]
PUBLIC_FILE_STATUSES = ["NOT_REQUIRED", "REQUIRED", "POSTED", "LATE_POSTED", "MISSING"]
INCIDENT_STATUSES = ["OPEN", "SUBSTANTIATED", "UNFOUNDED", "REMEDIATED"]
DRIVE_STATUSES = ["PLANNED", "ACTIVE", "CLOSED"]
SHIFT_STATUSES = ["SCHEDULED", "COMPLETED", "NO_SHOW", "CANCELLED"]
PREMIUM_STATUSES = ["AVAILABLE", "DEPLETED"]
PAYMENT_STATUSES = ["PENDING", "PAID", "LAPSED", "REFUNDED"]
PLEDGE_PREMIUM_STATUSES = [
    "RESERVED", "BACKORDERED", "NOT_ELIGIBLE", "WAIVED", "SHIPPED", "RELEASED", "RETURNED",
]


# --------------------------------------------------------------------------
# Shared record properties (PRD §2.5)
# --------------------------------------------------------------------------
def assert_common_fields(data: dict):
    """Assert the standard server-managed properties: id, created_at,
    updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1 on creation"


def assert_write_once_fields(data: dict):
    """Assert the reduced property set of a write-once evidence record: only
    id and created_at, with no updated_at and no version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "a write-once record carries no updated_at"
    assert "version" not in data, "a write-once record carries no version"


def assert_two_decimal_number(value, field_name="value"):
    """Two-decimal scores and percentages are JSON numbers, never strings."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{field_name} must be a JSON number, got {value!r}"
    )
    assert round(float(value), 2) == pytest.approx(float(value), abs=1e-9), (
        f"{field_name} must carry at most two decimals, got {value!r}"
    )


def assert_integer_cents(value, field_name="cents"):
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field_name} must be a whole number of cents, got {value!r}"
    )


# --------------------------------------------------------------------------
# Per-entity assertions
# --------------------------------------------------------------------------
def assert_volunteer(data: dict):
    assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["role_track"] in ["PROGRAMMER", "ENGINEER", "DEVELOPMENT"]
    assert isinstance(data["seniority_start_date"], str)
    assert isinstance(data["committee_seat"], bool)
    assert data["status"] in VOLUNTEER_STATUSES
    assert isinstance(data["continuous_service_months"], int)
    assert isinstance(data["current_certification_count"], int)
    assert isinstance(data["strike_count"], int)
    assert_two_decimal_number(data["seniority_score"], "seniority_score")
    assert data["seniority_score"] >= 0.00, "seniority_score is floored at 0.00"
    assert isinstance(data["needs_core_renewal"], bool)


def assert_certification(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["volunteer_id"])
    assert data["cert_type"] in [
        "BOARD_OPERATION", "STATION_POLICY", "BROADCAST_REGULATION", "UNDERWRITING_COPY",
    ]
    assert data["status"] in CERTIFICATION_STATUSES
    assert data["exam_score"] is None or isinstance(data["exam_score"], int)
    assert isinstance(data["attempt_count"], int) and data["attempt_count"] >= 0


def assert_proposal(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["proposer_volunteer_id"])
    assert isinstance(data["title"], str) and data["title"]
    assert data["format_code"] in ["MUSIC", "PUBLIC_AFFAIRS", "TALK", "NEWS", "CULTURAL"]
    assert isinstance(data["language_code"], str) and len(data["language_code"]) == 2
    assert data["requested_daypart"] in [
        "MORNING_DRIVE", "MIDDAY", "AFTERNOON_DRIVE", "EVENING", "OVERNIGHT",
    ]
    assert 15 <= data["requested_duration_minutes"] <= 720
    assert data["status"] in PROPOSAL_STATUSES
    assert isinstance(data["review_round"], int)
    assert isinstance(data["decline_majority"], bool)
    if data["composite_score"] is not None:
        assert_two_decimal_number(data["composite_score"], "composite_score")
        assert data["composite_score"] <= 5.00, "composite_score is capped at 5.00"


def assert_committee_vote(data: dict):
    assert_write_once_fields(data)
    assert is_valid_uuid(data["proposal_id"])
    assert is_valid_uuid(data["member_volunteer_id"])
    assert isinstance(data["review_round"], int)
    for field in ("format_fit_score", "diversity_score", "quality_score"):
        assert 1 <= data[field] <= 5, f"{field} is an integer from 1 through 5"
    assert data["recommendation"] in ["APPROVE", "REVISE", "DECLINE"]


def assert_program(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["proposal_id"])
    assert is_valid_uuid(data["host_volunteer_id"])
    assert data["programming_status"] in PROGRAMMING_STATUSES
    assert data["compliance_standing"] in COMPLIANCE_STANDINGS
    assert isinstance(data["compliance_penalty_points"], int)
    assert data["compliance_penalty_points"] >= 0
    if data["performance_score"] is not None:
        assert_two_decimal_number(data["performance_score"], "performance_score")
        assert 0.00 <= data["performance_score"] <= 100.00


def assert_schedule_grid(data: dict):
    assert_common_fields(data)
    assert isinstance(data["season_code"], str) and data["season_code"]
    assert data["status"] in GRID_STATUSES
    assert isinstance(data["total_assigned_minutes"], int)
    assert 0 <= data["total_assigned_minutes"] <= 10080
    assert_two_decimal_number(data["public_affairs_minutes_pct"], "public_affairs_minutes_pct")


def assert_slot_assignment(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["grid_id"])
    assert is_valid_uuid(data["program_id"])
    assert 0 <= data["day_of_week"] <= 6
    assert 0 <= data["start_minute"] <= 1425
    assert 15 <= data["duration_minutes"] <= 720
    assert data["start_minute"] + data["duration_minutes"] <= 1440
    assert data["status"] in SLOT_STATUSES


def assert_episode(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["program_id"])
    assert is_valid_uuid(data["slot_assignment_id"])
    assert data["air_status"] in AIR_STATUSES
    assert data["log_status"] in LOG_STATUSES
    assert isinstance(data["needs_substitute"], bool)
    assert isinstance(data["featured_performance_count"], int)
    assert isinstance(data["local_featured_count"], int)
    assert data["local_featured_count"] <= data["featured_performance_count"]
    for field in ("provisional_royalty_cents", "final_royalty_cents"):
        if data[field] is not None:
            assert_integer_cents(data[field], field)


def assert_playlist_entry(data: dict):
    assert_write_once_fields(data)
    assert is_valid_uuid(data["episode_id"])
    assert isinstance(data["sequence_number"], int) and data["sequence_number"] >= 1
    assert isinstance(data["artist"], str) and data["artist"]
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["duration_seconds"], int) and data["duration_seconds"] >= 1
    assert data["play_source"] in [
        "LIBRARY_CD", "LIBRARY_VINYL", "DIGITAL", "LIVE_PERFORMANCE", "PRODUCTION_MUSIC",
    ]
    assert isinstance(data["is_local_artist"], bool)
    assert isinstance(data["is_new_release"], bool)
    assert data["royalty_class"] in ROYALTY_CLASSES


def assert_underwriting_spot(data: dict):
    assert_common_fields(data)
    assert isinstance(data["underwriter_name"], str) and data["underwriter_name"]
    assert data["spot_class"] in [
        "UNDERWRITING", "POLITICAL_CANDIDATE", "ISSUE_ADVOCACY", "PSA",
    ]
    assert isinstance(data["copy_text"], str) and data["copy_text"]
    assert data["status"] in SPOT_STATUSES
    assert isinstance(data["noncommercial_risk_score"], int)
    assert 0 <= data["noncommercial_risk_score"] <= 100
    assert data["public_file_status"] in PUBLIC_FILE_STATUSES


def assert_compliance_incident(data: dict):
    assert_common_fields(data)
    assert data["category"] in [
        "INDECENCY", "POLITICAL_CONTENT", "PUBLIC_FILE", "SPONSOR_ID", "VOLUNTEER_CONFLICT",
    ]
    assert data["severity"] in ["MINOR", "MAJOR", "CRITICAL"]
    assert data["status"] in INCIDENT_STATUSES
    assert isinstance(data["penalty_points"], int) and data["penalty_points"] >= 0
    assert isinstance(data["safe_harbor_violation"], bool)
    assert data["sanction"] in ["NONE", "WARNING", "SUSPENSION", "TERMINATION"]


def assert_membership_drive(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert_integer_cents(data["goal_cents"], "goal_cents")
    assert data["goal_cents"] >= 1
    assert isinstance(data["phone_line_count"], int) and data["phone_line_count"] >= 1
    assert data["status"] in DRIVE_STATUSES
    for field in (
        "gross_pledged_cents", "pledged_total_cents", "fulfilled_total_cents",
        "refunded_total_cents", "lapsed_total_cents",
    ):
        assert_integer_cents(data[field], field)
    assert_two_decimal_number(data["attainment_pct"], "attainment_pct")


def assert_phone_bank_shift(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["drive_id"])
    assert is_valid_uuid(data["volunteer_id"])
    assert data["status"] in SHIFT_STATUSES
    assert isinstance(data["pledges_taken_count"], int)


def assert_premium_item(data: dict):
    assert_common_fields(data)
    assert isinstance(data["sku"], str) and data["sku"]
    assert isinstance(data["name"], str) and data["name"]
    assert_integer_cents(data["tier_threshold_cents"], "tier_threshold_cents")
    assert data["tier_threshold_cents"] >= 1
    assert_integer_cents(data["fair_market_value_cents"], "fair_market_value_cents")
    assert data["fair_market_value_cents"] >= 0
    for field in ("units_received_qty", "on_hand_qty", "reserved_qty", "shipped_qty"):
        assert isinstance(data[field], int) and data[field] >= 0, f"{field} is a whole unit count"
    assert data["status"] in PREMIUM_STATUSES
    assert_premium_unit_conservation(data)


def assert_pledge(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["drive_id"])
    assert isinstance(data["donor_name"], str) and data["donor_name"]
    assert_integer_cents(data["amount_cents"], "amount_cents")
    assert data["amount_cents"] >= 1
    assert data["payment_status"] in PAYMENT_STATUSES
    assert data["premium_status"] in PLEDGE_PREMIUM_STATUSES
    assert_integer_cents(data["tax_deductible_cents"], "tax_deductible_cents")
    assert data["tax_deductible_cents"] >= 0, "tax_deductible_cents is floored at 0"


# --------------------------------------------------------------------------
# Conserved totals (PRD §2.11)
# --------------------------------------------------------------------------
def assert_premium_unit_conservation(premium: dict):
    """`on_hand_qty` plus `shipped_qty` always equals `units_received_qty`."""
    total = premium["on_hand_qty"] + premium["shipped_qty"]
    assert total == premium["units_received_qty"], (
        "on_hand_qty + shipped_qty must equal units_received_qty, got "
        f"{premium['on_hand_qty']} + {premium['shipped_qty']} != {premium['units_received_qty']}"
    )


def assert_derived_premium_status(premium: dict):
    """A premium is AVAILABLE while on_hand_qty minus reserved_qty is greater
    than 0, and DEPLETED otherwise."""
    expected = "AVAILABLE" if premium["on_hand_qty"] - premium["reserved_qty"] > 0 else "DEPLETED"
    assert premium["status"] == expected, (
        f"Expected premium status {expected} for on_hand {premium['on_hand_qty']} / "
        f"reserved {premium['reserved_qty']}, got {premium['status']}"
    )


def assert_drive_money_partition(drive: dict):
    """The four narrower aggregates partition the gross by settlement state."""
    settled = (
        drive["fulfilled_total_cents"]
        + drive["refunded_total_cents"]
        + drive["lapsed_total_cents"]
    )
    assert settled <= drive["gross_pledged_cents"], (
        "fulfilled + refunded + lapsed may never exceed gross_pledged_cents"
    )


def assert_grid_airtime(grid: dict, live_slots: list):
    """A grid's `total_assigned_minutes` is the exact sum of `duration_minutes`
    over that grid's live occupations."""
    expected = sum(slot["duration_minutes"] for slot in live_slots)
    assert grid["total_assigned_minutes"] == expected, (
        f"Expected total_assigned_minutes {expected}, got {grid['total_assigned_minutes']}"
    )


def assert_two_decimals_equal(actual, expected, field_name="value"):
    assert actual == pytest.approx(expected, abs=DECIMAL_TOLERANCE), (
        f"Expected {field_name} {expected}, got {actual}"
    )


def _normalise_instant(value: str) -> str:
    """Reduce an ISO 8601 UTC instant to a comparable form. Timestamps are
    emitted in UTC with three fractional digits, so a whole-second instant is
    written either with or without a `.000` fraction; both denote one moment."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    text = value.replace("Z", "+00:00") if value.endswith("Z") else value
    if "." in text:
        head, _, tail = text.partition(".")
        # The fraction runs only as far as the digits; whatever follows is the
        # UTC offset (`+00:00`) and must be preserved intact.
        digits = ""
        for char in tail:
            if not char.isdigit():
                break
            digits += char
        offset = tail[len(digits):]
        fraction = digits[:6].rstrip("0")
        text = head + (f".{fraction}" if fraction else "") + offset
    return text


def assert_instant_equals(actual, expected, field_name="timestamp"):
    """Compare two ISO 8601 UTC instants for the same moment, tolerating the
    optional fractional-second digits the timestamp format carries."""
    assert _normalise_instant(actual) == _normalise_instant(expected), (
        f"Expected {field_name} {expected}, got {actual}"
    )
