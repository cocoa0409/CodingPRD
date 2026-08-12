"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_employer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    for field in (
        "annual_self_only_premium_cents",
        "tobacco_surcharge_cents",
        "pmpm_fee_cents",
        "coaching_session_fee_cents",
        "k_anonymity_threshold",
        "kiosk_capacity",
        "invoice_approval_limit_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_employee(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["employer_id"], str)
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["full_name"], str)
    assert isinstance(data["department"], str)
    assert isinstance(data["hire_date"], str)
    assert isinstance(data["tobacco_attested"], bool)


def assert_program(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("DRAFT", "ACTIVE", "CLOSED", "SETTLED")
    for field in (
        "bronze_threshold",
        "silver_threshold",
        "gold_threshold",
        "bronze_award_cents",
        "silver_award_cents",
        "gold_award_cents",
        "coaching_required_sessions",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_enrollment(data: dict):
    _assert_common_fields(data)
    assert data["participation_status"] in ("INVITED", "ACTIVE", "SUSPENDED", "TERMINATED")
    assert data["verification_status"] in ("PENDING", "VERIFIED", "FLAGGED")
    assert isinstance(data["points_balance_provisional"], int)
    assert isinstance(data["points_balance_settled"], int)
    assert isinstance(data["auto_referral_count"], int)


def assert_health_assessment(data: dict):
    # Immutable scoring record: carries only id + created_at among system fields (PRD §2.4).
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "HealthAssessment must not carry updated_at"
    assert "version" not in data, "HealthAssessment must not carry version"
    assert isinstance(data["risk_score"], int)
    assert data["risk_band"] in ("LOW", "MODERATE", "HIGH")


def assert_biometric_screening(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("SCHEDULED", "RESULTED", "NO_SHOW")
    assert isinstance(data["clinic_location"], str)
    assert isinstance(data["slot_start"], str)
    assert isinstance(data["slot_end"], str)


def assert_challenge(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("DRAFT", "PUBLISHED", "ACTIVE", "COMPLETED")
    assert data["activity_type"] in ("STEPS", "MINUTES", "VISITS")
    assert isinstance(data["goal_quantity"], int)
    assert isinstance(data["points_reward"], int)
    assert isinstance(data["completed_count"], int)


def assert_challenge_participation(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("JOINED", "COMPLETED", "FAILED")
    assert isinstance(data["progress_quantity"], int)


def assert_activity_event(data: dict):
    # Immutable ingestion record: carries only id + created_at among system fields (PRD §2.4).
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "ActivityEvent must not carry updated_at"
    assert "version" not in data, "ActivityEvent must not carry version"
    assert data["activity_type"] in ("STEPS", "MINUTES", "VISITS")
    assert isinstance(data["quantity"], int)
    assert isinstance(data["points_granted"], int)


def assert_points_ledger_entry(data: dict):
    _assert_common_fields(data)
    assert data["kind"] in ("EARNED", "BONUS", "ADJUSTED")
    assert data["status"] in ("PROVISIONAL", "POSTED", "EXPIRED")
    assert isinstance(data["points_delta"], int)


def assert_incentive_award(data: dict):
    _assert_common_fields(data)
    assert data["tier"] in ("NONE", "BRONZE", "SILVER", "GOLD")
    assert data["applied_variant"] in ("STANDARD", "REASONABLE_ALTERNATIVE")
    assert data["status"] in ("PROJECTED", "CONFIRMED", "APPLIED", "DISPUTED")
    for field in (
        "standard_award_cents",
        "award_cents",
        "surcharge_cents",
        "net_annual_differential_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_coaching_referral(data: dict):
    _assert_common_fields(data)
    assert data["reason"] in ("HIGH_RISK", "TOBACCO_CESSATION", "RA_REQUEST")
    assert data["source"] in ("MANUAL", "AUTO_RISK")
    assert data["status"] in ("REFERRED", "ENGAGED", "DISCHARGED", "DECLINED")
    assert isinstance(data["sessions_completed"], int)
    assert isinstance(data["session_dates"], list)
    assert isinstance(data["referral_round"], int)


def assert_vendor_invoice(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "PAID", "DISPUTED")
    assert isinstance(data["line_items"], list)
    assert isinstance(data["total_cents"], int)
    for line in data["line_items"]:
        assert line["line_type"] in ("MEMBER_MONTH", "COACHING_SESSION", "ADJUSTMENT")
        assert isinstance(line["amount_cents"], int)


def assert_aggregate_report(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("GENERATED", "PUBLISHED")
    assert isinstance(data["cohort_size"], int)
    assert isinstance(data["avg_settled_points"], (int, float))
    assert isinstance(data["participation_rate"], (int, float))
    assert isinstance(data["tobacco_rate"], (int, float))


def assert_enrollment_balance_invariants(data: dict):
    """Domain invariants from PRD §2.8: provisional = settled + not-yet-finalized activity."""
    assert data["points_balance_provisional"] >= data["points_balance_settled"], (
        "provisional balance must be >= settled balance whenever entries are positive-only"
    )


def assert_invoice_total_invariant(data: dict):
    """PRD §2.9: total_cents is the exact sum of the already-rounded line amounts."""
    assert data["total_cents"] == sum(line["amount_cents"] for line in data["line_items"]), (
        "total_cents must equal the exact sum of line_items amounts"
    )
