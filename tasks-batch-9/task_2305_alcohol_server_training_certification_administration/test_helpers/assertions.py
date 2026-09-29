"""Entity assertions and domain invariant checkers for the training platform."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# --------------------------------------------------------------------------------------
# Timestamp helpers
# --------------------------------------------------------------------------------------

def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp, tolerating a trailing Z and fractional digits."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 timestamp, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_same_instant(actual: str, expected: str, label: str = "timestamp"):
    """Compare two UTC timestamps as instants.

    Timestamps are rendered in ISO 8601 with three fractional digits, so a literal string
    comparison against an expectation written without fractional digits would be wrong even
    when the instant matches. Compare the instants themselves.
    """
    assert actual is not None, f"{label} must be present, got None"
    got = parse_instant(actual)
    want = parse_instant(expected)
    assert got == want, f"Expected {label} {expected}, got {actual}"


def assert_audit_fields(data: dict, expected_version: int = None):
    """id is a server-generated UUID string; created_at and updated_at are ISO 8601."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID string, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), \
        f"version must be an integer, got {data.get('version')!r}"
    assert data["version"] >= 1, f"version starts at 1, got {data['version']}"
    if expected_version is not None:
        assert data["version"] == expected_version, \
            f"Expected version {expected_version}, got {data['version']}"


# --------------------------------------------------------------------------------------
# Per-resource assertions
# --------------------------------------------------------------------------------------

def assert_state_jurisdiction(data: dict):
    assert_audit_fields(data)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["state_code"].isupper()
    assert data["mandate_type"] in ["MANDATORY", "CONDITIONAL", "VOLUNTARY"]
    assert isinstance(data["mandated_tracks"], list)
    for track in data["mandated_tracks"]:
        assert track in ["ON_PREMISE", "OFF_PREMISE"]
    assert isinstance(data["certificate_validity_months"], int)
    assert isinstance(data["renewal_grace_days"], int)
    assert isinstance(data["new_hire_training_days"], int)
    assert isinstance(data["registry_submission_required"], bool)
    assert isinstance(data["registry_deadline_days"], int)
    assert isinstance(data["registry_late_fee_cents_per_day"], int)
    assert isinstance(data["max_retakes_allowed"], int)
    assert isinstance(data["retake_cooling_off_hours"], int)
    assert isinstance(data["proctor_separation_required"], bool)
    assert isinstance(data["reminder_lead_days"], int)
    assert isinstance(data["certificates_issued_count"], int)
    assert_percentage(data["min_passing_score_pct"], "min_passing_score_pct")


def assert_course(data: dict):
    assert_audit_fields(data)
    assert isinstance(data["title"], str) and 1 <= len(data["title"]) <= 160
    assert data["track"] in ["ON_PREMISE", "OFF_PREMISE"]
    assert data["delivery_mode"] in ["CLASSROOM", "ONLINE"]
    assert float(data["contact_hours"]) > 0
    assert 10 <= data["question_count"] <= 200
    assert isinstance(data["version_label"], str) and 1 <= len(data["version_label"]) <= 32
    assert data["status"] in ["DRAFT", "PUBLISHED", "RETIRED"]
    assert isinstance(data["content_revision_count"], int)


def assert_course_approval(data: dict):
    assert_audit_fields(data)
    assert is_valid_uuid(data["course_id"])
    assert is_valid_uuid(data["state_jurisdiction_id"])
    assert data["approval_status"] in [
        "SUBMITTED", "CHANGES_REQUESTED", "APPROVED", "REJECTED",
        "STALE", "SUPERSEDED", "EXPIRED",
    ]
    assert isinstance(data["review_round"], int) and data["review_round"] >= 1


def assert_trainer(data: dict):
    assert_audit_fields(data)
    assert isinstance(data["full_name"], str) and 1 <= len(data["full_name"]) <= 120
    assert "@" in data["email"]
    assert data["trainer_status"] in ["PROVISIONAL", "CERTIFIED", "SUSPENDED", "LAPSED"]
    assert isinstance(data["certified_tracks"], list)
    assert isinstance(data["certified_state_codes"], list)
    assert isinstance(data["sessions_taught_count"], int)
    assert isinstance(data["graded_enrollments_count"], int)
    assert_percentage(data["pass_rate_pct"], "pass_rate_pct")


def assert_class_session(data: dict):
    assert_audit_fields(data)
    assert is_valid_uuid(data["course_id"])
    assert is_valid_uuid(data["state_jurisdiction_id"])
    assert is_valid_uuid(data["trainer_id"])
    assert is_iso8601_timestamp(data["scheduled_start_at"])
    assert is_iso8601_timestamp(data["scheduled_end_at"])
    assert parse_instant(data["scheduled_end_at"]) > parse_instant(data["scheduled_start_at"])
    assert 1 <= data["capacity"] <= 40
    assert data["session_status"] in [
        "SCHEDULED", "ROSTER_LOCKED", "EXAM_OPEN", "COMPLETED", "CANCELLED",
    ]
    assert isinstance(data["enrolled_count"], int) and data["enrolled_count"] >= 0
    assert isinstance(data["passed_count"], int) and data["passed_count"] >= 0
    assert data["enrolled_count"] <= data["capacity"]


def assert_alcohol_server(data: dict):
    assert_audit_fields(data)
    assert isinstance(data["full_name"], str) and 1 <= len(data["full_name"]) <= 120
    assert "@" in data["email"]
    assert is_valid_uuid(data["state_jurisdiction_id"])
    assert data["work_eligibility"] in ["UNCERTIFIED", "ELIGIBLE", "GRACE", "RESTRICTED"]
    assert isinstance(data["certification_count"], int) and data["certification_count"] >= 0


def assert_enrollment(data: dict):
    assert_audit_fields(data)
    assert is_valid_uuid(data["class_session_id"])
    assert is_valid_uuid(data["alcohol_server_id"])
    assert data["paid_by"] in ["SELF_PAY", "EMPLOYER_CREDIT"]
    assert isinstance(data["seat_credit_charged"], bool)
    assert data["enrollment_state"] in [
        "REGISTERED", "ATTENDED", "NO_SHOW", "EXAM_SCHEDULED", "EXAM_IN_PROGRESS",
        "EXAM_FAILED", "PASSED", "INCOMPLETE", "WITHDRAWN",
    ]
    assert isinstance(data["attempt_count"], int) and data["attempt_count"] >= 0
    if data.get("best_score_pct") is not None:
        assert_percentage(data["best_score_pct"], "best_score_pct")


def assert_exam_attempt(data: dict):
    assert_audit_fields(data)
    assert is_valid_uuid(data["enrollment_id"])
    assert isinstance(data["attempt_number"], int) and data["attempt_number"] >= 1
    assert isinstance(data["question_count"], int)
    assert data["outcome"] in ["IN_PROGRESS", "PASS", "FAIL", "VOIDED"]
    assert is_iso8601_timestamp(data["started_at"])
    if data.get("score_pct") is not None:
        assert_percentage(data["score_pct"], "score_pct")
    if data.get("raw_correct_count") is not None:
        assert 0 <= data["raw_correct_count"] <= data["question_count"]


def assert_certificate(data: dict):
    assert_audit_fields(data)
    assert is_valid_uuid(data["alcohol_server_id"])
    assert is_valid_uuid(data["enrollment_id"])
    assert is_valid_uuid(data["state_jurisdiction_id"])
    assert data["track"] in ["ON_PREMISE", "OFF_PREMISE"]
    assert isinstance(data["certificate_number"], str) and data["certificate_number"]
    assert is_iso8601_timestamp(data["issued_at"])
    assert is_iso8601_timestamp(data["expires_at"])
    assert data["expiry_anchor_mode"] in ["ISSUANCE_ANCHORED", "ANNIVERSARY_ANCHORED"]
    assert data["validity_state"] in [
        "ACTIVE", "GRACE", "LAPSED", "SUSPENDED", "SUPERSEDED",
    ]
    assert data["registry_state"] in [
        "NOT_REQUIRED", "PENDING_SUBMISSION", "SUBMITTED", "ACCEPTED", "RESUBMIT_REQUIRED",
    ]
    assert isinstance(data["reminder_sent_count"], int)


def assert_certificate_number_format(number: str, state_code: str, year: int, ordinal: int):
    """The number is the state_code, a hyphen, the four-digit year, a hyphen, and the
    counter rendered as five digits with leading zeros."""
    expected = f"{state_code}-{year:04d}-{ordinal:05d}"
    assert number == expected, f"Expected certificate_number {expected}, got {number}"


def assert_registry_submission(data: dict):
    assert_audit_fields(data)
    assert is_valid_uuid(data["certificate_id"])
    assert isinstance(data["attempt_number"], int) and data["attempt_number"] >= 1
    assert data["submission_state"] in ["TRANSMITTED", "ACCEPTED", "REJECTED"]
    assert is_iso8601_timestamp(data["transmitted_at"])
    assert isinstance(data["late_days"], int) and data["late_days"] >= 0
    assert_cents(data["penalty_fee_cents"], "penalty_fee_cents")
    assert data["rejection_code"] in [
        "NONE", "DUPLICATE_SERVER_RECORD", "INVALID_COURSE_APPROVAL", "NAME_MISMATCH",
    ]


def assert_employer_account(data: dict):
    assert_audit_fields(data)
    assert isinstance(data["legal_name"], str) and 1 <= len(data["legal_name"]) <= 160
    assert len(data["billing_state_code"]) == 2 and data["billing_state_code"].isupper()
    assert data["account_status"] in ["ACTIVE", "DELINQUENT", "SUSPENDED"]
    assert data["dram_shop_discount_status"] in [
        "NOT_DOCUMENTED", "ELIGIBLE", "DOCUMENTED", "EXPIRED",
    ]
    assert_seat_credit_ledger(data)
    assert_percentage(data["last_purchase_discount_pct"], "last_purchase_discount_pct")
    assert_percentage(data["account_compliance_rate_pct"], "account_compliance_rate_pct")
    assert_cents(data["last_purchase_total_charged_cents"], "last_purchase_total_charged_cents")
    assert_cents(data["lifetime_charged_cents"], "lifetime_charged_cents")
    assert isinstance(data["location_count"], int) and data["location_count"] >= 0


def assert_employer_location(data: dict):
    assert_audit_fields(data)
    assert is_valid_uuid(data["employer_account_id"])
    assert isinstance(data["location_name"], str) and 1 <= len(data["location_name"]) <= 120
    assert is_valid_uuid(data["state_jurisdiction_id"])
    assert data["premise_type"] in ["ON_PREMISE", "OFF_PREMISE"]
    assert_cents(data["annual_premium_cents"], "annual_premium_cents")
    assert data["training_requirement"] in ["MANDATED", "VOLUNTARY"]
    assert_location_metrics(data)


def assert_server_assignment(data: dict):
    assert_audit_fields(data)
    assert is_valid_uuid(data["employer_location_id"])
    assert is_valid_uuid(data["alcohol_server_id"])
    assert isinstance(data["role_title"], str) and 1 <= len(data["role_title"]) <= 80
    assert data["assignment_state"] in ["ACTIVE", "WORK_RESTRICTED", "ENDED"]
    assert data["restriction_reason"] in [
        "NONE", "CERTIFICATE_LAPSED", "REGISTRY_SUSPENDED", "NO_CERTIFICATE",
    ]
    assert is_iso8601_timestamp(data["assigned_at"])


def assert_dram_shop_document(data: dict):
    assert_audit_fields(data)
    assert is_valid_uuid(data["employer_account_id"])
    assert isinstance(data["insurer_name"], str) and 1 <= len(data["insurer_name"]) <= 120
    assert isinstance(data["policy_number"], str) and 1 <= len(data["policy_number"]) <= 64
    assert parse_instant(data["coverage_period_end"]) > parse_instant(data["coverage_period_start"])
    assert is_iso8601_timestamp(data["snapshot_at"])
    assert_percentage(data["strict_compliance_rate_pct"], "strict_compliance_rate_pct")
    assert isinstance(data["months_documented"], int) and data["months_documented"] >= 0
    assert data["discount_tier"] in ["NONE", "TIER_1", "TIER_2", "TIER_3"]
    assert_percentage(data["discount_pct"], "discount_pct")
    assert 0.00 <= float(data["discount_pct"]) <= 12.00
    assert_cents(data["discount_credit_cents"], "discount_credit_cents")
    assert data["document_state"] in ["ISSUED", "SUPERSEDED", "VOIDED"]
    assert isinstance(data["location_count"], int)


def assert_compliance_run(data: dict):
    """A compliance run is immutable: only id and created_at, with no updated_at or version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID string"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "a compliance run must not carry updated_at"
    assert "version" not in data, "a compliance run must not carry version"
    assert is_iso8601_timestamp(data["run_at"])
    for counter in [
        "trainers_lapsed_count", "approvals_expired_count", "certificates_graced_count",
        "certificates_lapsed_count", "reminders_sent_count", "assignments_restricted_count",
        "assignments_restored_count", "locations_recomputed_count", "documents_voided_count",
    ]:
        assert isinstance(data[counter], int) and data[counter] >= 0, \
            f"{counter} must be a non-negative integer, got {data.get(counter)!r}"


def assert_compliance_dashboard(data: dict, location_id: str = None):
    for field in [
        "employer_location_id", "training_requirement", "assigned_server_count",
        "compliant_server_count", "grace_server_count", "restricted_server_count",
        "compliance_rate_strict_pct", "compliance_rate_grace_inclusive_pct",
        "compliance_posture",
    ]:
        assert field in data, f"the dashboard must expose {field}"
    if location_id is not None:
        assert data["employer_location_id"] == location_id
    assert_location_metrics(data)


# --------------------------------------------------------------------------------------
# Domain invariants
# --------------------------------------------------------------------------------------

def assert_percentage(value, label="percentage"):
    """Percentage-valued fields are numbers carried to exactly two decimal places."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), \
        f"{label} must be numeric, got {value!r}"
    assert round(float(value), 2) == float(value), \
        f"{label} must be carried to two decimal places, got {value!r}"


def assert_cents(value, label="cents"):
    """Money is held in integer cents."""
    assert isinstance(value, int) and not isinstance(value, bool), \
        f"{label} must be an integer number of cents, got {value!r}"
    assert value >= 0, f"{label} must not be negative, got {value}"


def assert_seat_credit_ledger(account: dict):
    """seat_credit_balance equals purchased minus consumed plus refunded, at all times."""
    expected = (account["seat_credits_purchased_total"]
                - account["seat_credits_consumed_total"]
                + account["seat_credits_refunded_total"])
    assert account["seat_credit_balance"] == expected, (
        "seat_credit_balance must equal purchased - consumed + refunded; got "
        f"{account['seat_credit_balance']} against {expected}"
    )


def assert_location_metrics(location: dict):
    """Counts and both rate variants must agree with the location's live headcount."""
    assigned = location["assigned_server_count"]
    compliant = location["compliant_server_count"]
    grace = location["grace_server_count"]
    restricted = location["restricted_server_count"]
    for name, value in [
        ("assigned_server_count", assigned), ("compliant_server_count", compliant),
        ("grace_server_count", grace), ("restricted_server_count", restricted),
    ]:
        assert isinstance(value, int) and value >= 0, f"{name} must be a count, got {value!r}"
    assert compliant <= assigned and grace <= assigned and restricted <= assigned
    assert_percentage(location["compliance_rate_strict_pct"], "compliance_rate_strict_pct")
    assert_percentage(location["compliance_rate_grace_inclusive_pct"],
                      "compliance_rate_grace_inclusive_pct")
    assert location["compliance_posture"] in [
        "COMPLIANT", "AT_RISK", "NON_COMPLIANT", "NOT_APPLICABLE",
    ]
    if assigned == 0:
        assert float(location["compliance_rate_strict_pct"]) == 100.00
        assert float(location["compliance_rate_grace_inclusive_pct"]) == 100.00


def assert_posture_matches_grace_inclusive_rate(location: dict):
    """compliance_posture is thresholded off the grace-inclusive rate."""
    rate = float(location["compliance_rate_grace_inclusive_pct"])
    if location["training_requirement"] == "VOLUNTARY":
        expected = "NOT_APPLICABLE"
    elif rate >= 95.00:
        expected = "COMPLIANT"
    elif rate >= 80.00:
        expected = "AT_RISK"
    else:
        expected = "NON_COMPLIANT"
    assert location["compliance_posture"] == expected, (
        f"Expected compliance_posture {expected} at grace-inclusive rate {rate}, "
        f"got {location['compliance_posture']}"
    )
