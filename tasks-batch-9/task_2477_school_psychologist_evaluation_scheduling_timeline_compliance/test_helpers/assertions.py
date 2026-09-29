"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import PER_TYPE_CAP_DAYS
from .types import (
    OPEN_ASSESSMENT_STATUSES,
    AssessmentDomain,
    AssessmentStatus,
    BreachSeverity,
    BreachStatus,
    CaseloadStatus,
    ComplianceStatus,
    CredentialType,
    ExclusionStatus,
    ExclusionType,
    GradeBand,
    LicenseStatus,
    MeetingStatus,
    OrderStatus,
    PsychologistStatus,
    ReferralStatus,
    ReferralType,
    RemedyBasis,
    SeatStatus,
    SessionStatus,
)

_DATE_LENGTH = len("2026-08-01")


def _values(enum_cls):
    return [member.value for member in enum_cls]


def assert_common_fields(data: dict):
    """The four system-managed properties every resource type carries."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version starts at 1, got {data['version']}"


def assert_calendar_date(value, field_name: str):
    assert isinstance(value, str) and len(value) == _DATE_LENGTH, (
        f"{field_name} must be a YYYY-MM-DD calendar date, got {value!r}"
    )


def assert_school(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["building_code"], str) and data["building_code"]
    assert data["grade_band"] in _values(GradeBand)
    assert isinstance(data["concurrent_meeting_capacity"], int)
    assert data["concurrent_meeting_capacity"] >= 1
    assert isinstance(data["enrollment_count"], int)
    assert data["enrollment_count"] >= 0


def assert_psychologist(data: dict):
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["employee_number"], str)
    assert data["credential_type"] in _values(CredentialType)
    assert isinstance(data["languages_certified"], list)
    assert data["languages_certified"], "languages_certified is non-empty"
    assert isinstance(data["assigned_school_ids"], list)
    assert data["assigned_school_ids"], "assigned_school_ids is non-empty"
    assert isinstance(data["weekly_capacity_points"], int)
    assert data["weekly_capacity_points"] >= 1
    assert data["status"] in _values(PsychologistStatus)
    assert isinstance(data["open_case_points"], int)
    assert data["open_case_points"] >= 0
    assert data["caseload_status"] in _values(CaseloadStatus)
    assert isinstance(data["pressure_index_assigned_basis"], (int, float))
    assert isinstance(data["pressure_index_clock_weighted"], (int, float))
    assert_caseload_status_consistent(data)
    assert_two_decimal_places(
        data["pressure_index_assigned_basis"], "pressure_index_assigned_basis"
    )
    assert_two_decimal_places(
        data["pressure_index_clock_weighted"], "pressure_index_clock_weighted"
    )


def assert_referral(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["school_id"])
    assert isinstance(data["student_local_id"], str) and data["student_local_id"]
    assert data["referral_type"] in _values(ReferralType)
    assert isinstance(data["primary_language"], str) and data["primary_language"]
    assert isinstance(data["interpreter_required"], bool)
    assert isinstance(data["bilingual_evaluation_required"], bool)
    assert isinstance(data["requested_domains"], list) and data["requested_domains"]
    assert len(set(data["requested_domains"])) == len(data["requested_domains"]), (
        "requested_domains must be duplicate-free"
    )
    for domain in data["requested_domains"]:
        assert domain in _values(AssessmentDomain)
    assert isinstance(data["intervention_team_summary"], str)
    assert data["status"] in _values(ReferralStatus)
    if data["referral_type"] == ReferralType.REEVALUATION.value:
        assert data["prior_evaluation_id"] is not None, (
            "a REEVALUATION referral carries prior_evaluation_id"
        )
    else:
        assert data["prior_evaluation_id"] is None, (
            "an INITIAL referral carries no prior_evaluation_id"
        )


def assert_evaluation(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["referral_id"])
    assert data["assessment_status"] in _values(AssessmentStatus)
    assert data["compliance_status"] in _values(ComplianceStatus)
    assert data["referral_type"] in _values(ReferralType)
    assert isinstance(data["interpreter_required"], bool)
    assert isinstance(data["evaluation_domains"], list) and data["evaluation_domains"]
    assert_calendar_date(data["clock_start_date"], "clock_start_date")
    assert_calendar_date(data["base_due_date"], "base_due_date")
    assert_calendar_date(data["statutory_due_date"], "statutory_due_date")
    for field in (
        "credited_exclusion_days",
        "elapsed_statutory_days",
        "days_remaining",
        "caseload_points",
        "reassignment_count",
        "protocol_units_consumed",
    ):
        assert isinstance(data[field], int), f"{field} must be a whole number"
    assert data["elapsed_statutory_days"] >= 0, (
        "elapsed_statutory_days is reported as zero when the difference is negative"
    )
    assert data["credited_exclusion_days"] >= 0
    assert data["reassignment_count"] >= 0
    assert data["protocol_units_consumed"] >= 0
    assert data["caseload_points"] >= 3, "caseload_points starts from a base of three"
    assert_evaluation_clock_consistent(data)


def assert_timeline_exclusion(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["evaluation_id"])
    assert data["exclusion_type"] in _values(ExclusionType)
    assert_calendar_date(data["start_date"], "start_date")
    assert_calendar_date(data["end_date"], "end_date")
    assert data["end_date"] >= data["start_date"]
    assert isinstance(data["claim_note"], str)
    assert data["status"] in _values(ExclusionStatus)
    assert isinstance(data["days_claimed"], int) and data["days_claimed"] >= 1
    assert isinstance(data["days_credited"], int) and data["days_credited"] >= 0
    assert data["days_credited"] <= PER_TYPE_CAP_DAYS[data["exclusion_type"]], (
        "days_credited never exceeds the per-type ceiling"
    )
    if data["status"] == ExclusionStatus.CLAIMED.value:
        assert data["days_credited"] == 0
        assert data["decided_by_user_id"] is None
        assert data["decided_at"] is None


def assert_assessment_instrument(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["instrument_code"], str)
    assert isinstance(data["protocol_stock_count"], int)
    assert data["protocol_stock_count"] >= 0, "protocol stock is never negative"
    assert isinstance(data["protocol_units_per_administration"], int)
    assert data["protocol_units_per_administration"] >= 1
    assert isinstance(data["protocol_unit_cost_cents"], int)
    assert data["protocol_unit_cost_cents"] >= 1
    assert isinstance(data["license_seat_total"], int)
    assert data["license_seat_total"] >= 0
    assert isinstance(data["license_seats_free"], int)
    assert 0 <= data["license_seats_free"] <= data["license_seat_total"]
    assert_calendar_date(data["license_expires_on"], "license_expires_on")
    assert data["license_status"] in _values(LicenseStatus)
    assert isinstance(data["supported_language_editions"], list)
    assert data["supported_language_editions"]


def assert_protocol_order(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["instrument_id"])
    assert isinstance(data["quantity_requested"], int)
    assert data["quantity_requested"] >= 1
    assert isinstance(data["rush_flag"], bool)
    for field in (
        "unit_price_cents",
        "base_cents",
        "contract_discount_cents",
        "rush_surcharge_cents",
        "handling_fee_cents",
        "total_cost_cents",
        "received_quantity",
    ):
        assert isinstance(data[field], int), f"{field} must be whole cents"
        assert data[field] >= 0
    assert data["status"] in _values(OrderStatus)
    assert isinstance(data["auto_approved"], bool)
    assert_protocol_order_total(data)


def assert_scoring_license_seat(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["instrument_id"])
    assert is_valid_uuid(data["psychologist_id"])
    assert data["status"] in _values(SeatStatus)
    assert is_iso8601_timestamp(data["assigned_at"])
    if data["status"] == SeatStatus.ASSIGNED.value:
        assert data["released_at"] is None
    else:
        assert is_iso8601_timestamp(data["released_at"])


def assert_interpreter_session(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["evaluation_id"])
    assert isinstance(data["language_code"], str) and data["language_code"]
    assert isinstance(data["interpreter_name"], str)
    assert is_iso8601_timestamp(data["session_start_at"])
    assert is_iso8601_timestamp(data["session_end_at"])
    assert data["session_end_at"] > data["session_start_at"]
    assert data["status"] in _values(SessionStatus)
    assert isinstance(data["duration_minutes"], int)
    assert data["duration_minutes"] >= 1
    if data["status"] != SessionStatus.CANCELLED.value:
        assert data["cancellation_reason"] is None


def assert_eligibility_meeting(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["evaluation_id"])
    assert is_valid_uuid(data["school_id"])
    assert is_iso8601_timestamp(data["scheduled_start_at"])
    assert is_iso8601_timestamp(data["scheduled_end_at"])
    assert data["scheduled_end_at"] > data["scheduled_start_at"]
    assert data["status"] in _values(MeetingStatus)
    assert isinstance(data["reschedule_count"], int)
    assert 0 <= data["reschedule_count"] <= 2, "a meeting accepts at most two reschedules"
    if data["status"] == MeetingStatus.PROPOSED.value:
        assert data["parent_notice_sent_at"] is None
        assert data["notice_lead_days"] is None
    if data["status"] != MeetingStatus.HELD.value:
        assert data["held_at"] is None


def assert_timeline_breach(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["evaluation_id"])
    assert is_iso8601_timestamp(data["detected_at"])
    assert isinstance(data["breach_days"], int) and data["breach_days"] >= 1
    assert data["severity"] in _values(BreachSeverity)
    assert data["status"] in _values(BreachStatus)
    for field in (
        "minutes_breach_day_basis",
        "minutes_missed_service_basis",
        "additional_minutes",
        "remedy_minutes_awarded",
    ):
        assert isinstance(data[field], int), f"{field} must be whole minutes"
        assert data[field] >= 0
    assert data["minutes_breach_day_basis"] % 5 == 0, (
        "compensatory minutes are rounded to the nearest multiple of five"
    )
    assert data["minutes_missed_service_basis"] % 5 == 0, (
        "compensatory minutes are rounded to the nearest multiple of five"
    )
    assert_breach_severity_band(data)
    if data["remedy_basis"] is not None:
        assert data["remedy_basis"] in _values(RemedyBasis)
    if data["status"] in (BreachStatus.DETECTED.value, BreachStatus.VACATED.value):
        assert data["remedy_minutes_awarded"] == 0, (
            "remedy_minutes_awarded reads zero while DETECTED and once VACATED"
        )


# ---------------- domain invariant checkers ----------------


def assert_two_decimal_places(value, field_name: str):
    scaled = round(float(value) * 100)
    assert abs(float(value) * 100 - scaled) < 1e-6, (
        f"{field_name} must carry exactly two decimal places, got {value!r}"
    )


def assert_caseload_status_consistent(psychologist: dict):
    points = psychologist["open_case_points"]
    capacity = psychologist["weekly_capacity_points"]
    if points < capacity:
        expected = CaseloadStatus.BALANCED.value
    elif points == capacity:
        expected = CaseloadStatus.AT_CAP.value
    else:
        expected = CaseloadStatus.OVER_CAP.value
    assert psychologist["caseload_status"] == expected, (
        f"caseload_status for {points} points against a capacity of {capacity} "
        f"must be {expected}, got {psychologist['caseload_status']}"
    )


def assert_evaluation_clock_consistent(evaluation: dict):
    """days_remaining is 60 less elapsed_statutory_days."""
    assert evaluation["days_remaining"] == 60 - evaluation["elapsed_statutory_days"], (
        "days_remaining is 60 less elapsed_statutory_days"
    )


def assert_posture_matches_days_remaining(evaluation: dict):
    """The posture a system actor writes for the current remaining-day count.

    Only valid straight after a sweep or a cascade has written the posture: a
    plain read re-derives the day counts but never rewrites `compliance_status`.
    """
    remaining = evaluation["days_remaining"]
    if remaining < 0:
        expected = ComplianceStatus.BREACHED.value
    elif remaining <= 10:
        expected = ComplianceStatus.AT_RISK.value
    else:
        expected = ComplianceStatus.ON_TRACK.value
    assert evaluation["compliance_status"] == expected, (
        f"a posture derived from {remaining} remaining days must be {expected}, "
        f"got {evaluation['compliance_status']}"
    )


def assert_breach_severity_band(breach: dict):
    days = breach["breach_days"]
    if days <= 5:
        expected = BreachSeverity.MINOR.value
    elif days <= 15:
        expected = BreachSeverity.MODERATE.value
    else:
        expected = BreachSeverity.SEVERE.value
    assert breach["severity"] == expected, (
        f"{days} breach days classify as {expected}, got {breach['severity']}"
    )


def assert_protocol_order_total(order: dict):
    expected_base = order["unit_price_cents"] * order["quantity_requested"]
    assert order["base_cents"] == expected_base, (
        "base_cents is unit_price_cents multiplied by quantity_requested"
    )
    expected_total = (
        order["base_cents"]
        - order["contract_discount_cents"]
        + order["rush_surcharge_cents"]
        + order["handling_fee_cents"]
    )
    assert order["total_cost_cents"] == expected_total, (
        "total_cost_cents is base less discount plus rush plus handling"
    )
    if not order["rush_flag"]:
        assert order["rush_surcharge_cents"] == 0, (
            "rush_surcharge_cents is exactly zero when rush_flag is false"
        )


def assert_license_seat_conservation(instrument: dict, seats: list):
    assigned = [s for s in seats if s["status"] == SeatStatus.ASSIGNED.value]
    assert (
        len(assigned) + instrument["license_seats_free"]
        == instrument["license_seat_total"]
    ), (
        f"{len(assigned)} assigned seats plus {instrument['license_seats_free']} free "
        f"must equal the total of {instrument['license_seat_total']}"
    )


def assert_caseload_points_conserved(psychologists: list, evaluations: list):
    district_points = sum(p["open_case_points"] for p in psychologists)
    open_points = sum(
        e["caseload_points"]
        for e in evaluations
        if e["psychologist_id"] is not None
        and e["assessment_status"] in OPEN_ASSESSMENT_STATUSES
    )
    assert district_points == open_points, (
        f"the district total of {district_points} points must equal the "
        f"{open_points} points carried by open evaluations"
    )


def assert_compliance_run_summary(summary: dict):
    assert is_iso8601_timestamp(summary["run_at"])
    assert isinstance(summary["evaluated_count"], int)
    assert isinstance(summary["at_risk_evaluation_ids"], list)
    assert isinstance(summary["breached_evaluation_ids"], list)
    assert isinstance(summary["breach_ids"], list)
    assert isinstance(summary["sessions_completed_count"], int)
