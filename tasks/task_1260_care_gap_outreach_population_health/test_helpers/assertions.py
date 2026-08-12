"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from datetime import datetime, timezone
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _parse_iso(ts: str) -> datetime:
    """Parse an ISO 8601 timestamp (supports trailing Z and fractional digits)."""
    if not isinstance(ts, str):
        raise AssertionError(f"Expected ISO timestamp string, got {type(ts)}: {ts!r}")
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def assert_timestamp_instant_equal(actual: str, expected_iso: str, label: str = "timestamp"):
    """Compare two timestamps by instant, tolerant of rendering (e.g. .000Z vs Z)."""
    actual_dt = _parse_iso(actual)
    expected_dt = _parse_iso(expected_iso)
    assert actual_dt == expected_dt, (
        f"{label}: expected instant {expected_iso}, got {actual}"
    )


def assert_registry(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["program_year"], int)
    assert data["status"] in ("ACTIVE", "ARCHIVED")
    assert is_iso8601_timestamp(data.get("current_business_date", "")), (
        "current_business_date must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)


def assert_measure(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["measure_code"], str)
    assert data["measure_domain"] in ("SCREENING", "MED_ADHERENCE")
    assert isinstance(data["lookback_days"], int)
    assert data["status"] in ("DRAFT", "PUBLISHED", "RETIRED")


def assert_cohort(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["cohort_code"], str)
    assert isinstance(data["min_age"], int)
    assert isinstance(data["max_age"], int)
    assert data["risk_tier_filter"] in ("ANY", "LOW", "MEDIUM", "HIGH")
    assert data["status"] in ("DRAFT", "ACTIVE", "RETIRED")


def assert_member(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["mrn"], str)
    assert data["risk_tier"] in ("LOW", "MEDIUM", "HIGH")
    assert data["enrollment_status"] in ("ENROLLED", "DISENROLLED", "DECEASED")
    assert isinstance(data["open_gap_count"], int) and data["open_gap_count"] >= 0


def assert_panel(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["status"] in ("BUILDING", "ACTIVE", "REBUILDING", "RETIRED")
    assert isinstance(data["member_count"], int) and data["member_count"] >= 0
    assert isinstance(data["version"], int)


def assert_care_gap(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["status"] in (
        "OPEN", "OUTREACH_IN_PROGRESS", "AWAITING_APPOINTMENT", "PENDING_EVIDENCE",
        "CLOSED", "REOPENED", "EXCLUDED", "EXPIRED",
    )
    assert isinstance(data["priority_score"], int)
    assert 0 <= data["priority_score"] <= 100, "priority_score must be clamped to [0,100]"
    assert data["priority_band"] in ("P1_URGENT", "P2_HIGH", "P3_ROUTINE", "P4_LOW")
    assert isinstance(data["attempt_count"], int) and data["attempt_count"] >= 0
    assert isinstance(data["version"], int)


def assert_campaign(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["status"] in ("DRAFT", "SCHEDULED", "ACTIVE", "PAUSED", "COMPLETED", "CANCELLED")
    assert data["channel"] in ("CALL", "TEXT", "MAIL")


def assert_outreach_attempt(data: dict):
    """Append-only ledger entry: id + created_at, no updated_at/version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "version" not in data, "outreach attempt must not carry a version field"
    assert "updated_at" not in data, "outreach attempt must not carry updated_at"
    assert data["outcome"] in (
        "CONTACTED", "LEFT_MESSAGE", "NO_ANSWER", "BAD_ADDRESS", "REFUSED", "REVERSED",
    )


def assert_appointment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["status"] in ("SCHEDULED", "CONFIRMED", "COMPLETED", "NO_SHOW", "CANCELLED")
    assert isinstance(data["version"], int)


def assert_transportation_assist(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["status"] in ("REQUESTED", "ARRANGED", "COMPLETED", "CANCELLED")
    assert isinstance(data["cost_cents"], int)


def assert_evidence(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["evidence_type"] in ("CHART_REVIEW", "CLAIMS_FEED", "MEMBER_ATTESTATION", "LAB_RESULT")
    assert data["status"] in ("SUBMITTED", "APPROVED", "REJECTED")


def assert_exclusion_request(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["exclusion_kind"] in (
        "MEDICAL_CONTRAINDICATION", "MEMBER_REFUSAL", "HOSPICE", "DECEASED",
    )
    assert data["status"] in ("SUBMITTED", "UNDER_REVIEW", "APPROVED", "DENIED", "REVOKED")


def assert_workload(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["assigned_member_count"], int) and data["assigned_member_count"] >= 0
    assert isinstance(data["closed_gap_count_period"], int)
    assert isinstance(data["period_key"], str)


def assert_payout(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["status"] in ("PROJECTED", "APPROVED", "PAID", "VOID")
    for field in ("base_amount_cents", "tier_multiplier_bps", "quality_bonus_cents", "total_payout_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents/bps"


def assert_performance_report(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["variant"] in ("PROVISIONAL", "FINAL")
    assert isinstance(data["denominator_count"], int) and data["denominator_count"] >= 0
    assert isinstance(data["numerator_count"], int) and data["numerator_count"] >= 0
    if data["denominator_count"] == 0:
        assert data["closure_rate_bps"] is None, "zero denominator yields null rate"
    else:
        assert isinstance(data["closure_rate_bps"], int)
