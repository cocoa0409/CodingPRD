"""Entity assertions, semantic instant comparison and conservation invariants."""

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?"
    r"(Z|[+-]\d{2}:?\d{2})?$"
)


# ─── Instant comparison ────────────────────────────────────────────────────

def parse_instant(value: Any) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating any number of fractional digits.

    Timestamps are compared as instants and never as strings, so that two
    renderings of the same moment — with and without a fractional part, or with
    a differently spelled UTC designator — compare equal.
    """
    assert isinstance(value, str), f"Expected an ISO 8601 string, got {value!r}"
    match = _INSTANT_RE.match(value.strip())
    assert match, f"Not a parseable ISO 8601 instant: {value!r}"
    year, month, day, hour, minute, second = (int(match.group(i)) for i in range(1, 7))
    frac = match.group(7) or "0"
    micros = int((frac + "000000")[:6])
    dt = datetime(year, month, day, hour, minute, second, micros, tzinfo=timezone.utc)
    offset = match.group(8)
    if offset and offset not in ("Z", "+00:00", "-00:00", "+0000", "-0000"):
        sign = 1 if offset[0] == "+" else -1
        digits = offset[1:].replace(":", "")
        dt = dt - sign * timedelta(hours=int(digits[:2]), minutes=int(digits[2:4]))
    return dt


def assert_same_instant(actual: Any, expected: str, label: str = "timestamp") -> None:
    """Compare two ISO 8601 instants semantically rather than lexically."""
    assert actual is not None, f"{label} must not be null (expected {expected})"
    got = parse_instant(actual)
    want = parse_instant(expected)
    assert got == want, f"{label}: expected the instant {expected}, got {actual}"


def assert_instant_null(actual: Any, label: str = "timestamp") -> None:
    assert actual is None, f"{label} must be null, got {actual!r}"


def assert_is_instant(value: Any, label: str = "timestamp") -> None:
    assert is_iso8601_timestamp(value), (
        f"{label} must be an ISO 8601 UTC timestamp, got {value!r}"
    )


# ─── Numeric helpers ───────────────────────────────────────────────────────

def assert_pct(actual: Any, expected: float, label: str = "percentage") -> None:
    """Percentages carry one decimal place and are compared with tolerance."""
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        f"{label} must be numeric, got {actual!r}"
    )
    assert float(actual) == pytest.approx(expected, abs=0.05), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_score(actual: Any, expected: float, label: str = "score") -> None:
    """Risk scores carry two decimal places."""
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        f"{label} must be numeric, got {actual!r}"
    )
    assert float(actual) == pytest.approx(expected, abs=0.005), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_cents(actual: Any, expected: int, label: str = "amount") -> None:
    """Money is always whole cents expressed as an integer."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be an integer number of cents, got {actual!r}"
    )
    assert actual == expected, f"{label}: expected {expected} cents, got {actual}"


# ─── Common resource properties (PRD §2.4) ────────────────────────────────

def assert_common_fields(data: dict, label: str = "resource") -> None:
    assert is_valid_uuid(data.get("id", "")), (
        f"{label}.id must be a UUID with no type prefix, got {data.get('id')!r}"
    )
    assert_is_instant(data.get("created_at"), f"{label}.created_at")
    assert_is_instant(data.get("updated_at"), f"{label}.updated_at")
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer of at least 1, got {data.get('version')!r}"
    )


# ─── Per-entity assertions ─────────────────────────────────────────────────

def assert_worker(data: dict) -> None:
    assert_common_fields(data, "worker")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["employee_code"], str) and data["employee_code"]
    assert data["credential_level"] in ("CHW_BASIC", "CHW_SENIOR", "CHW_SUPERVISOR")
    assert data["employment_status"] == "ACTIVE"


def assert_patient(data: dict) -> None:
    assert_common_fields(data, "patient")
    assert isinstance(data["mrn"], str) and data["mrn"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["household_size"], int) and data["household_size"] >= 1
    assert isinstance(data["monthly_income_cents"], int)
    assert data["monthly_income_cents"] >= 0
    assert re.fullmatch(r"\d{5}", data["residence_zip"]), (
        f"residence_zip must be exactly five numeric characters, got {data['residence_zip']!r}"
    )
    assert isinstance(data["program_enrollments"], list)
    assert isinstance(data["categorical_exclusions"], list)
    assert isinstance(data["child_in_household"], bool)
    assert isinstance(data["address_safety_flag"], bool)
    assert data["enrollment_status"] in ("PROSPECTIVE", "ENROLLED", "DISENROLLED")
    assert data["gate_status"] in ("OPEN", "RECORDS_HOLD")
    assert data["risk_tier"] in ("NONE", "LOW", "MODERATE", "HIGH", "CRITICAL")
    assert isinstance(data["risk_score"], (int, float))
    assert isinstance(data["unfulfilled_referral_count"], int)


def assert_instrument(data: dict) -> None:
    assert_common_fields(data, "instrument")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["version_label"], str) and data["version_label"]
    assert isinstance(data["domain_weights"], dict) and data["domain_weights"]
    assert sum(data["domain_weights"].values()) == 100, (
        "instrument weights must sum to exactly 100"
    )
    assert isinstance(data["rescreen_cadence_days"], int)
    assert data["rescreen_cadence_days"] >= 1
    assert data["status"] in ("DRAFT", "PUBLISHED", "RETIRED")


def assert_screening(data: dict) -> None:
    assert_common_fields(data, "screening")
    assert is_valid_uuid(data["patient_id"])
    assert is_valid_uuid(data["instrument_id"])
    assert isinstance(data["domain_scores"], dict)
    assert_is_instant(data.get("anchor_screened_at"), "screening.anchor_screened_at")
    assert_is_instant(data.get("latest_response_at"), "screening.latest_response_at")
    assert isinstance(data["weighted_score"], (int, float))
    assert 0 <= float(data["weighted_score"]) <= 100
    assert data["risk_tier"] in ("LOW", "MODERATE", "HIGH", "CRITICAL")
    assert isinstance(data["amendment_count"], int) and data["amendment_count"] >= 0
    assert data["status"] in ("SUBMITTED", "AMENDED", "SUPERSEDED")


def assert_resource_org(data: dict) -> None:
    assert_common_fields(data, "resource org")
    assert isinstance(data["name"], str) and data["name"]
    assert data["org_type"] in ("FOOD", "HOUSING", "TRANSPORT")
    assert isinstance(data["service_zips"], list) and data["service_zips"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_offering(data: dict) -> None:
    assert_common_fields(data, "offering")
    assert is_valid_uuid(data["resource_org_id"])
    assert data["unit_type"] in ("FOOD_BOX", "HOUSING_VOUCHER", "TRANSPORT_RIDE")
    for field in (
        "capacity_total", "available_units", "allocated_units", "delivered_units",
        "released_units", "expired_units", "lifetime_allocated_units",
    ):
        assert isinstance(data[field], int), f"offering.{field} must be an integer"
        assert data[field] >= 0, f"offering.{field} must never go negative"
    assert data["availability_state"] in ("AVAILABLE", "EXHAUSTED")
    assert_offering_conservation(data)


def assert_criterion(data: dict) -> None:
    assert_common_fields(data, "criterion")
    assert is_valid_uuid(data["offering_id"])
    assert data["criterion_type"] in (
        "INCOME_BAND", "GEOGRAPHY", "HOUSEHOLD_SIZE",
        "PROGRAM_ENROLLMENT", "CATEGORICAL_EXCLUSION",
    )
    assert data["evaluation_rank"] in (1, 2, 3, 4, 5)


def assert_referral(data: dict) -> None:
    assert_common_fields(data, "referral")
    assert is_valid_uuid(data["patient_id"])
    assert is_valid_uuid(data["offering_id"])
    assert is_valid_uuid(data["opened_by_chw_id"])
    assert is_valid_uuid(data["root_referral_id"])
    assert data["urgency"] in ("ROUTINE", "URGENT", "EMERGENT")
    assert isinstance(data["units_requested"], int) and data["units_requested"] >= 1
    assert data["status"] in (
        "SENT", "ACCEPTED", "DECLINED", "SERVICE_DELIVERED", "CLOSED", "LAPSED"
    )
    assert_is_instant(data.get("sent_at"), "referral.sent_at")
    assert_is_instant(data.get("ack_deadline_at"), "referral.ack_deadline_at")
    assert_is_instant(data.get("hold_expires_at"), "referral.hold_expires_at")
    assert isinstance(data["reroute_count"], int) and data["reroute_count"] >= 0


def assert_home_visit(data: dict) -> None:
    assert_common_fields(data, "home visit")
    assert is_valid_uuid(data["patient_id"])
    assert is_valid_uuid(data["assigned_chw_id"])
    assert_is_instant(data.get("scheduled_start"), "visit.scheduled_start")
    assert_is_instant(data.get("scheduled_end"), "visit.scheduled_end")
    assert parse_instant(data["scheduled_end"]) > parse_instant(data["scheduled_start"])
    assert isinstance(data["two_person_required"], bool)
    assert data["scheduling_status"] in (
        "SCHEDULED", "EN_ROUTE", "COMPLETED", "NO_SHOW", "CANCELLED"
    )
    assert data["documentation_status"] in ("DRAFT", "ATTESTED", "AMENDED", "VOIDED")
    assert isinstance(data["amendment_count"], int) and data["amendment_count"] >= 0


def assert_goal(data: dict) -> None:
    assert_common_fields(data, "goal")
    assert is_valid_uuid(data["patient_id"])
    assert data["domain"] in (
        "FOOD", "HOUSING", "TRANSPORT", "EMPLOYMENT", "HEALTH_LITERACY"
    )
    assert data["direction"] in ("INCREASE_GOOD", "DECREASE_GOOD")
    assert isinstance(data["baseline_value"], (int, float))
    assert isinstance(data["target_value"], (int, float))
    assert isinstance(data["current_value"], (int, float))
    assert 0.0 <= float(data["progress_pct"]) <= 100.0, (
        f"progress_pct is clamped to 0.0..100.0, got {data['progress_pct']}"
    )
    assert data["status"] in ("ACTIVE", "MET", "NOT_MET", "DEFERRED")
    assert isinstance(data["review_cycle_days"], int) and data["review_cycle_days"] >= 1
    assert_is_instant(data.get("review_due_at"), "goal.review_due_at")
    assert isinstance(data["reopen_count"], int) and data["reopen_count"] >= 0


def assert_encounter(data: dict) -> None:
    assert_common_fields(data, "encounter")
    assert is_valid_uuid(data["patient_id"])
    assert is_valid_uuid(data["chw_id"])
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", data["encounter_date"])
    assert re.fullmatch(r"\d{4}-\d{2}", data["service_month"])
    assert data["service_month"] == data["encounter_date"][:7]
    for field in (
        "direct_minutes", "indirect_minutes", "travel_minutes",
        "documentation_minutes", "total_minutes", "raw_billable_minutes",
        "billable_minutes", "travel_reimbursement_cents",
    ):
        assert isinstance(data[field], int), f"encounter.{field} must be an integer"
        assert data[field] >= 0
    assert data["funding_source"] in ("UNFUNDED", "PAYER", "GRANT")
    assert data["status"] in ("DRAFT", "SUBMITTED", "LOCKED", "VOIDED")
    assert_encounter_minute_conservation(data)


def assert_payer_claim(data: dict) -> None:
    assert_common_fields(data, "payer claim")
    assert is_valid_uuid(data["patient_id"])
    assert re.fullmatch(r"\d{4}-\d{2}", data["service_month"])
    assert data["basis"] in ("PROVISIONAL", "FINAL")
    assert isinstance(data["claimed_minutes"], int)
    assert isinstance(data["claimed_encounter_count"], int)
    assert data["billing_code"] in ("CM-60", "CM-120")
    assert isinstance(data["units"], int)
    assert isinstance(data["allowed_amount_cents"], int)
    assert data["status"] in (
        "SUBMITTED", "PAID", "DENIED", "APPEALED", "OVERTURNED", "UPHELD"
    )
    assert data["units"] == data["claimed_minutes"] // 15, (
        "units is claimed_minutes divided by 15 and truncated downward"
    )
    assert data["allowed_amount_cents"] == data["units"] * 2150


def assert_grant_award(data: dict) -> None:
    assert_common_fields(data, "grant award")
    assert isinstance(data["funder_name"], str) and data["funder_name"]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", data["period_start"])
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", data["period_end"])
    assert data["period_end"] >= data["period_start"]
    assert isinstance(data["budget_cap_cents"], int) and data["budget_cap_cents"] >= 1
    assert 0 <= float(data["indirect_rate_pct"]) <= 100
    assert isinstance(data["allowable_cost_categories"], list)
    assert data["allowable_cost_categories"]
    assert data["status"] in ("OPEN", "CLOSED")
    assert_grant_budget_conservation(data)


def assert_charge_line(data: dict) -> None:
    assert_common_fields(data, "charge line")
    assert is_valid_uuid(data["grant_award_id"])
    assert is_valid_uuid(data["encounter_id"])
    for field in (
        "charged_minutes", "hourly_rate_cents", "direct_amount_cents",
        "indirect_amount_cents", "total_amount_cents",
    ):
        assert isinstance(data[field], int), f"charge line.{field} must be an integer"
    assert data["hourly_rate_cents"] in (4200, 3800)
    assert data["total_amount_cents"] == (
        data["direct_amount_cents"] + data["indirect_amount_cents"]
    ), "total_amount_cents is direct_amount_cents plus indirect_amount_cents"
    assert data["status"] in ("POSTED", "REVERSED")


def assert_escalation(data: dict) -> None:
    assert_common_fields(data, "escalation")
    assert is_valid_uuid(data["patient_id"])
    assert data["source_flag"] in (
        "CRITICAL_SDOH_FINDING", "RESOURCE_EXHAUSTED", "REFERRAL_UNFULFILLED",
        "GOAL_NOT_MET", "MANUAL",
    )
    assert data["status"] in (
        "OPEN_TIER_1", "OPEN_TIER_2", "OPEN_TIER_3", "ACKNOWLEDGED", "RESOLVED"
    )
    assert data["current_tier"] in (1, 2, 3)
    assert isinstance(data["opened_by_user_id"], str) and data["opened_by_user_id"]
    assert_is_instant(data.get("tier_entered_at"), "escalation.tier_entered_at")
    assert_is_instant(data.get("ack_deadline_at"), "escalation.ack_deadline_at")
    assert isinstance(data["promotion_count"], int) and data["promotion_count"] >= 0


# ─── Conservation invariants (PRD §2.10) ──────────────────────────────────

def assert_offering_conservation(offering: dict) -> None:
    """capacity_total == available + allocated + delivered, and the hold ledger."""
    partition = (
        offering["available_units"]
        + offering["allocated_units"]
        + offering["delivered_units"]
    )
    assert offering["capacity_total"] == partition, (
        f"capacity_total {offering['capacity_total']} must equal available "
        f"{offering['available_units']} + allocated {offering['allocated_units']} "
        f"+ delivered {offering['delivered_units']}"
    )
    ledger = (
        offering["allocated_units"]
        + offering["delivered_units"]
        + offering["released_units"]
        + offering["expired_units"]
    )
    assert offering["lifetime_allocated_units"] == ledger, (
        f"lifetime_allocated_units {offering['lifetime_allocated_units']} must equal "
        f"allocated + delivered + released + expired ({ledger})"
    )


def assert_grant_budget_conservation(award: dict) -> None:
    assert award["budget_cap_cents"] == (
        award["committed_cents"] + award["remaining_budget_cents"]
    ), (
        f"budget_cap_cents {award['budget_cap_cents']} must equal committed_cents "
        f"{award['committed_cents']} plus remaining_budget_cents "
        f"{award['remaining_budget_cents']}"
    )


def assert_encounter_minute_conservation(encounter: dict) -> None:
    total = (
        encounter["direct_minutes"]
        + encounter["indirect_minutes"]
        + encounter["travel_minutes"]
        + encounter["documentation_minutes"]
    )
    assert encounter["total_minutes"] == total, (
        f"total_minutes {encounter['total_minutes']} must equal the sum of the four "
        f"minute buckets ({total})"
    )


def assert_offering_counters(
    offering: dict,
    available: Optional[int] = None,
    allocated: Optional[int] = None,
    delivered: Optional[int] = None,
    released: Optional[int] = None,
    expired: Optional[int] = None,
    lifetime: Optional[int] = None,
    availability_state: Optional[str] = None,
) -> None:
    """Assert whichever inventory counters the caller pins, then the invariants."""
    checks = {
        "available_units": available,
        "allocated_units": allocated,
        "delivered_units": delivered,
        "released_units": released,
        "expired_units": expired,
        "lifetime_allocated_units": lifetime,
    }
    for field, expected in checks.items():
        if expected is not None:
            assert offering[field] == expected, (
                f"offering.{field}: expected {expected}, got {offering[field]}"
            )
    if availability_state is not None:
        assert offering["availability_state"] == availability_state, (
            f"offering.availability_state: expected {availability_state}, "
            f"got {offering['availability_state']}"
        )
    assert_offering_conservation(offering)
