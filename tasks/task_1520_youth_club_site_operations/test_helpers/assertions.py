"""Entity assertions and domain invariant checkers (PRD Sections 2.5, 3.x)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_audit_fields(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601 UTC"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be ISO 8601 UTC"
    )
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer"


def assert_site(data: dict):
    _assert_audit_fields(data, "Site")
    assert isinstance(data["name"], str) and data["name"]
    for field in ("youth_capacity", "standard_ratio", "elevated_ratio",
                  "base_weekly_fee_cents", "registration_fee_cents", "max_arrears_cents"):
        assert isinstance(data[field], int), f"Site.{field} must be an integer"
    assert isinstance(data["meal_rates_cents"], dict)


def assert_member(data: dict):
    _assert_audit_fields(data, "Member")
    assert isinstance(data["site_id"], str) and data["site_id"]
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["date_of_birth"], str)
    assert isinstance(data["grade"], int)
    assert isinstance(data["household_size"], int)
    assert isinstance(data["household_income_cents"], int)
    assert isinstance(data["walker_ok"], bool)
    assert data["status"] in ("APPLIED", "ACTIVE", "SUSPENDED", "DENIED", "WITHDRAWN")
    assert data["eligibility_tier"] in (None, "FREE", "REDUCED", "PAID")
    assert data["weekly_fee_cents"] is None or isinstance(data["weekly_fee_cents"], int)
    assert isinstance(data["fee_balance_cents"], int)
    assert isinstance(data["behavior_points"], int)
    assert isinstance(data["discipline_watch"], bool)


def assert_guardian(data: dict):
    _assert_audit_fields(data, "Guardian")
    assert isinstance(data["member_id"], str) and data["member_id"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["status"] in ("ACTIVE", "REVOKED")


def assert_scholarship_fund(data: dict):
    _assert_audit_fields(data, "ScholarshipFund")
    assert isinstance(data["site_id"], str) and data["site_id"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["budget_cents"], int)
    assert isinstance(data["reserved_cents"], int)
    assert isinstance(data["disbursed_cents"], int)
    assert isinstance(data["available_cents"], int)
    assert data["status"] in ("OPEN", "CLOSED")


def assert_scholarship_award(data: dict):
    _assert_audit_fields(data, "ScholarshipAward")
    assert isinstance(data["fund_id"], str) and data["fund_id"]
    assert isinstance(data["member_id"], str) and data["member_id"]
    assert isinstance(data["discount_pct"], (int, float))
    assert isinstance(data["weekly_cap_cents"], int)
    assert isinstance(data["annual_cap_cents"], int)
    assert isinstance(data["disbursed_cents"], int)
    assert isinstance(data["remaining_cap_cents"], int)
    assert data["status"] in ("PENDING", "ACTIVE", "REVOKED", "CANCELLED", "EXHAUSTED")


def assert_club_day(data: dict):
    _assert_audit_fields(data, "ClubDay")
    assert isinstance(data["site_id"], str) and data["site_id"]
    assert isinstance(data["date"], str)
    assert data["status"] in ("OPEN", "CLOSED", "RECONCILED")
    assert isinstance(data["present_count"], int)
    assert isinstance(data["signed_out_count"], int)
    assert isinstance(data["missing_signout_count"], int)
    assert isinstance(data["meal_counts"], dict)
    assert data["posture"] in ("NORMAL", "RATIO_STRAINED", "OVER_CAPACITY")
    assert isinstance(data["weekly_fees_accrued"], bool)


def assert_attendance_record(data: dict):
    _assert_audit_fields(data, "AttendanceRecord")
    assert isinstance(data["club_day_id"], str) and data["club_day_id"]
    assert isinstance(data["member_id"], str) and data["member_id"]
    assert is_iso8601_timestamp(data.get("sign_in_at", ""))
    assert data.get("sign_out_at") is None or is_iso8601_timestamp(data["sign_out_at"])
    assert data["status"] in ("ON_SITE", "SIGNED_OUT", "MISSING_SIGNOUT")


def assert_program_area(data: dict):
    _assert_audit_fields(data, "ProgramArea")
    assert isinstance(data["site_id"], str) and data["site_id"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["capacity"], int)
    assert data["risk_tier"] in ("STANDARD", "ELEVATED")


def assert_rotation_assignment(data: dict):
    _assert_audit_fields(data, "RotationAssignment")
    assert isinstance(data["club_day_id"], str) and data["club_day_id"]
    assert isinstance(data["area_id"], str) and data["area_id"]
    assert data["block"] in ("BLOCK_A", "BLOCK_B", "BLOCK_C")
    assert data["kind"] in ("YOUTH", "STAFF")
    assert data["status"] in ("SCHEDULED", "CHECKED_IN", "COMPLETED", "CANCELLED", "MOVED")


def assert_transport_route(data: dict):
    _assert_audit_fields(data, "TransportRoute")
    assert isinstance(data["site_id"], str) and data["site_id"]
    assert isinstance(data["route_name"], str) and data["route_name"]
    assert isinstance(data["school_name"], str) and data["school_name"]
    assert isinstance(data["seat_capacity"], int)


def assert_ride_assignment(data: dict):
    _assert_audit_fields(data, "RideAssignment")
    assert isinstance(data["route_id"], str) and data["route_id"]
    assert isinstance(data["member_id"], str) and data["member_id"]
    assert isinstance(data["effective_start_date"], str)
    assert data["status"] in ("ACTIVE", "ENDED")


def assert_meal_claim(data: dict):
    _assert_audit_fields(data, "MealClaim")
    assert isinstance(data["site_id"], str) and data["site_id"]
    assert isinstance(data["claim_month"], str)
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED")
    assert isinstance(data["rate_snapshot"], dict)
    assert isinstance(data["provisional_total_cents"], int)


def assert_behavior_incident(data: dict):
    _assert_audit_fields(data, "BehaviorIncident")
    assert isinstance(data["member_id"], str) and data["member_id"]
    assert isinstance(data["incident_date"], str)
    assert data["category"] in ("LEVEL_1", "LEVEL_2", "LEVEL_3")
    assert data["points"] in (1, 3, 8)
    assert data["adjudication_status"] in ("REPORTED", "ADJUDICATED", "DISMISSED")
    assert data["suspension_status"] in (
        "NONE", "IMPOSED", "ACTIVE", "APPEALED", "SERVED", "RESCINDED"
    )


def assert_staff(data: dict):
    _assert_audit_fields(data, "Staff")
    assert isinstance(data["site_id"], str) and data["site_id"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["position"] in ("DIRECTOR", "FRONTLINE")
    assert data["status"] in ("HIRED", "ACTIVE")
    assert data["compliance_status"] in ("INCOMPLETE", "LAPSED", "EXPIRING", "COMPLIANT")


def assert_funder_report(data: dict):
    _assert_audit_fields(data, "FunderReport")
    assert isinstance(data["site_id"], str) and data["site_id"]
    assert isinstance(data["report_month"], str)
    assert data["funder_type"] in ("UNITED_WAY", "STATE_GRANT")
    assert data["status"] in ("DRAFT", "SUBMITTED", "ACCEPTED")
    assert isinstance(data["operating_days"], int)
    assert isinstance(data["member_days_attended"], int)
    assert isinstance(data["member_days_enrolled"], int)


# --- Domain invariants -------------------------------------------------------


def assert_fund_conservation(fund: dict):
    """PRD 3.3: budget always equals available + reserved + disbursed."""
    total = fund["available_cents"] + fund["reserved_cents"] + fund["disbursed_cents"]
    assert fund["budget_cents"] == total, (
        f"Fund conservation violated: budget {fund['budget_cents']} != "
        f"available {fund['available_cents']} + reserved {fund['reserved_cents']} "
        f"+ disbursed {fund['disbursed_cents']}"
    )


def assert_attendance_tally(day: dict, total_records: int):
    """PRD 3.4/3.9: the three counters partition the day's attendance records."""
    tally = (
        day["present_count"] + day["signed_out_count"] + day["missing_signout_count"]
    )
    assert tally == total_records, (
        f"Attendance tally drifted: {day['present_count']} + "
        f"{day['signed_out_count']} + {day['missing_signout_count']} != {total_records}"
    )
