"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from datetime import datetime, timezone

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 timestamp (accepting a trailing Z) for comparisons.

    PRD §2.4 pins the format of server-managed timestamps; input-supplied
    datetimes (windows, due dates) are compared as instants so any faithful
    serialization of the same instant matches.
    """
    assert isinstance(value, str), f"expected timestamp string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _assert_common_fields(data: dict):
    """Primary resources carry id, created_at, updated_at, version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only_fields(data: dict):
    """Payment and TruckLoad carry only id + created_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only rows must not expose updated_at"
    assert "version" not in data, "append-only rows must not expose version"


def assert_band_program(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["season_name"], str) and data["season_name"]
    assert data["status"] in ["SETUP", "ENROLLMENT_OPEN", "SEASON_ACTIVE", "CLOSED"]
    assert data["rental_fee_mode"] in ["FLAT", "PRORATED"]
    assert data["scoring_mode"] in ["RAW_WEIGHTED", "RANK_NORMALIZED"]
    for field in ("music_budget_cents", "repair_budget_cents", "subsidy_pool_cents",
                  "delinquency_grace_cents", "music_spent_cents", "repair_spent_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"


def assert_student(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["grade"] in (9, 10, 11, 12)
    assert data["section"] in ["WOODWIND", "BRASS", "PERCUSSION", "GUARD"]
    assert isinstance(data["is_section_leader"], bool)
    assert data["enrollment_status"] in ["APPLIED", "ENROLLED", "SUSPENDED", "WITHDRAWN"]
    assert isinstance(data["account_balance_cents"], int)
    assert isinstance(data["is_delinquent"], bool)


def assert_instrument(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["serial_number"], str) and data["serial_number"]
    assert isinstance(data["instrument_type"], str) and data["instrument_type"]
    assert data["condition_grade"] in ["EXCELLENT", "GOOD", "FAIR", "POOR", "UNPLAYABLE"]
    assert isinstance(data["replacement_value_cents"], int)
    assert data["status"] in ["AVAILABLE", "CHECKED_OUT", "RETURN_PENDING_INSPECTION",
                              "IN_MAINTENANCE", "RETIRED"]


def assert_instrument_assignment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["student_id"], str)
    assert isinstance(data["instrument_id"], str)
    assert data["status"] in ["ACTIVE", "OVERDUE", "RETURNED"]
    assert data["fee_variant"] in ["FLAT", "PRORATED"]
    assert isinstance(data["accrued_fee_cents"], int)
    assert isinstance(data["late_fee_cents"], int)


def assert_uniform(data: dict):
    _assert_common_fields(data)
    assert data["garment_type"] in ["JACKET", "BIBBERS", "SHAKO", "PLUME", "GLOVES"]
    assert isinstance(data["size_label"], str)
    assert data["status"] in ["IN_STORAGE", "ISSUED", "RETURNED_DIRTY", "AT_CLEANER",
                              "RETIRED"]
    assert isinstance(data["cleaning_count"], int)


def assert_uniform_assignment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["student_id"], str)
    assert isinstance(data["uniform_id"], str)
    assert data["status"] in ["ISSUED", "RETURNED"]
    assert isinstance(data["cleaning_fee_cents"], int)


def assert_cleaning_batch(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["program_id"], str)
    assert data["status"] in ["OPEN", "SENT", "RECONCILED"]
    assert isinstance(data["garment_count"], int)


def assert_music_arrangement(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["title"], str)
    assert data["license_type"] in ["STANDARD", "CUSTOM_ARRANGEMENT",
                                    "COMPETITION_EXCERPT"]
    assert isinstance(data["cost_cents"], int)
    assert data["status"] in ["QUOTED", "APPROVED", "LICENSED_ACTIVE", "EXPIRED",
                              "REJECTED"]


def assert_event(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["program_id"], str)
    assert data["event_type"] in ["REHEARSAL", "SECTIONAL", "COMPETITION",
                                  "PERFORMANCE", "FUNDRAISER"]
    assert isinstance(data["facility"], str)
    assert isinstance(data["is_outdoor"], bool)
    assert data["status"] in ["SCHEDULED", "WEATHER_WATCH", "INDOOR_RELOCATED",
                              "POSTPONED", "COMPLETED", "CANCELLED"]


def assert_trip(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["event_id"], str)
    assert isinstance(data["program_id"], str)
    assert data["status"] in ["PLANNING", "ROSTER_OPEN", "ROSTER_LOCKED", "FINALIZED",
                              "COMPLETED", "CANCELLED", "SUPERSEDED"]
    assert isinstance(data["capacity"], int)
    assert isinstance(data["estimated_cost_cents"], int)
    assert isinstance(data["registered_count"], int)
    assert isinstance(data["confirmed_count"], int)


def assert_trip_enrollment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["trip_id"], str)
    assert isinstance(data["student_id"], str)
    assert data["attendance_status"] in ["REGISTERED", "WAITLISTED", "CONFIRMED",
                                         "EXCUSED", "ATTENDED", "NO_SHOW"]
    assert data["payment_status"] in ["UNPAID", "PARTIAL", "PAID", "REFUNDED"]
    assert isinstance(data["provisional_share_cents"], int)
    assert isinstance(data["amount_due_cents"], int)
    assert isinstance(data["net_paid_cents"], int)
    assert isinstance(data["refunded_cents"], int)


def assert_payment(data: dict):
    _assert_append_only_fields(data)
    assert isinstance(data["student_id"], str)
    assert data["kind"] in ["PAYMENT", "REFUND", "WAIVER", "MANUAL_DEBIT",
                            "RENTAL_FEE_DEBIT", "LATE_FEE_DEBIT", "CLEANING_FEE_DEBIT",
                            "TRIP_SHARE_DEBIT", "FUNDRAISING_CREDIT"]
    assert isinstance(data["amount_cents"], int)


def assert_fundraiser(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["name"], str)
    assert isinstance(data["goal_cents"], int)
    assert data["status"] in ["OPEN", "CREDITED"]


def assert_audition(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["program_id"], str)
    assert data["section"] in ["WOODWIND", "BRASS", "PERCUSSION", "GUARD"]
    assert isinstance(data["chair_capacity"], int)
    assert data["scoring_mode"] in ["RAW_WEIGHTED", "RANK_NORMALIZED"]
    assert data["status"] in ["SCORING_OPEN", "SCORES_FINALIZED",
                              "PLACEMENTS_PUBLISHED", "UNDER_CHALLENGE"]


def assert_audition_entry(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["audition_id"], str)
    assert isinstance(data["student_id"], str)
    assert isinstance(data["judge_scores"], list)
    for row in data["judge_scores"]:
        assert isinstance(row["judge_id"], str)
        for field in ("musicianship", "marching", "leadership"):
            assert isinstance(row[field], int), f"{field} must be an integer score"


def assert_chair_placement(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["audition_id"], str)
    assert isinstance(data["entry_id"], str)
    assert isinstance(data["is_alternate"], bool)
    if data["is_alternate"]:
        assert data["chair_number"] is None
    else:
        assert isinstance(data["chair_number"], int)
    assert data["status"] in ["PUBLISHED", "SUPERSEDED"]


def assert_truck_charter(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["vehicle_label"], str)
    assert data["status"] in ["RESERVED", "LOADED", "DEPARTED", "RETURNED", "CANCELLED"]
    for field in ("capacity_weight_lb", "capacity_volume_cuft", "loaded_weight_lb",
                  "loaded_volume_cuft"):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_truck_load(data: dict):
    _assert_append_only_fields(data)
    assert isinstance(data["charter_id"], str)
    assert isinstance(data["description"], str)
    assert isinstance(data["weight_lb"], int)
    assert isinstance(data["volume_cuft"], int)


def assert_student_balance(data: dict, expected_cents: int):
    """Ledger-derived balance invariant (PRD §2.7)."""
    assert data["account_balance_cents"] == expected_cents, (
        f"account_balance_cents must equal {expected_cents}, "
        f"got {data.get('account_balance_cents')}"
    )
