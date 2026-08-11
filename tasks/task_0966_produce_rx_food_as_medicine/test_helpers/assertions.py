"""Entity assertions and domain invariant checkers (PRD §2.4, §2.8, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def _assert_mutable_common_fields(data: dict):
    _assert_common_fields(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_program(data: dict):
    _assert_mutable_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["status"] in ("DRAFT", "ACTIVE", "FROZEN", "CLOSED")
    for f in ("base_monthly_benefit_cents", "household_increment_cents",
              "max_household_size", "double_up_daily_cap_cents",
              "double_up_pool_cents", "double_up_matched_cents",
              "double_up_remaining_cents", "tier2_completions",
              "tier3_completions", "renewal_window_days", "ops_run_index"):
        assert isinstance(data[f], int), f"{f} must be an integer"
    assert isinstance(data["double_up_multiplier"], (int, float))
    assert isinstance(data["outcome_improvement_threshold"], (int, float))


def assert_funder(data: dict):
    _assert_mutable_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert isinstance(data["total_commitment_cents"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_funding_pool(data: dict):
    _assert_mutable_common_fields(data)
    assert is_valid_uuid(data.get("program_id", "")), "program_id must be a UUID"
    assert is_valid_uuid(data.get("funder_id", "")), "funder_id must be a UUID"
    for f in ("committed_cents", "disbursed_cents", "reserved_cents", "available_cents"):
        assert isinstance(data[f], int), f"{f} must be an integer"
    assert data["status"] in ("PENDING", "FUNDED", "SUSPENDED", "CLOSED")


def assert_clinic(data: dict):
    _assert_mutable_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["npi_number"], str) and data["npi_number"]
    assert isinstance(data["max_active_referrals"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_retailer(data: dict):
    _assert_mutable_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["kind"] in ("GROCERY", "FARMERS_MARKET", "MOBILE_MARKET")
    assert isinstance(data["double_up_eligible"], bool)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_patient(data: dict):
    _assert_mutable_common_fields(data)
    assert is_valid_uuid(data.get("clinic_id", "")), "clinic_id must be a UUID"
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["date_of_birth"], str) and data["date_of_birth"]
    assert isinstance(data["household_size"], int) and data["household_size"] >= 1
    assert data["consent_status"] in ("PENDING", "GRANTED", "REVOKED")


def assert_referral(data: dict):
    _assert_mutable_common_fields(data)
    assert is_valid_uuid(data.get("clinic_id", ""))
    assert is_valid_uuid(data.get("patient_id", ""))
    assert is_valid_uuid(data.get("program_id", ""))
    assert isinstance(data["diagnosis_code"], str) and data["diagnosis_code"]
    assert data["priority"] in ("STANDARD", "URGENT")
    assert isinstance(data["appeal_count"], int)
    assert data["status"] in ("SUBMITTED", "UNDER_REVIEW", "APPROVED",
                              "DECLINED", "WITHDRAWN", "EXPIRED")


def assert_enrollment(data: dict):
    _assert_mutable_common_fields(data)
    assert is_valid_uuid(data.get("program_id", ""))
    assert is_valid_uuid(data.get("patient_id", ""))
    assert is_valid_uuid(data.get("referral_id", ""))
    assert isinstance(data["household_size"], int) and data["household_size"] >= 1
    assert data["engagement_tier"] in ("T1", "T2", "T3")
    assert isinstance(data["lifetime_redeemed_cents"], int)
    assert isinstance(data["lifetime_match_cents"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED", "LAPSED",
                              "TERMINATED", "COMPLETED")


def assert_benefit_cycle(data: dict):
    _assert_mutable_common_fields(data)
    assert is_valid_uuid(data.get("program_id", ""))
    assert isinstance(data["period_index"], int)
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert data["status"] in ("SCHEDULED", "OPEN", "CLOSED")


def assert_voucher(data: dict):
    _assert_mutable_common_fields(data)
    assert is_valid_uuid(data.get("enrollment_id", ""))
    assert is_valid_uuid(data.get("benefit_cycle_id", ""))
    for f in ("face_value_cents", "redeemed_cents", "remaining_cents"):
        assert isinstance(data[f], int), f"{f} must be an integer"
    assert data["status"] in ("ISSUED", "EXHAUSTED", "EXPIRED", "VOIDED")


def assert_redemption(data: dict):
    _assert_mutable_common_fields(data)
    assert is_valid_uuid(data.get("retailer_id", ""))
    assert is_valid_uuid(data.get("enrollment_id", ""))
    assert isinstance(data["lines"], list) and len(data["lines"]) >= 1
    for line in data["lines"]:
        assert line["category"] in ("PRODUCE_ELIGIBLE", "STAPLE", "OTHER")
        assert isinstance(line["amount_cents"], int) and line["amount_cents"] > 0
    for f in ("subtotal_cents", "produce_eligible_cents", "match_cents",
              "voucher_applied_cents", "patient_pay_cents"):
        assert isinstance(data[f], int), f"{f} must be an integer"
    assert data["status"] in ("SETTLED", "VOIDED")


def assert_education_session(data: dict):
    _assert_mutable_common_fields(data)
    assert is_valid_uuid(data.get("program_id", ""))
    assert isinstance(data["topic"], str)
    assert isinstance(data["venue"], str)
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["educator_ref"], str)
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED")


def assert_education_completion(data: dict):
    """Append-only record: carries only id + created_at (PRD §2.4)."""
    _assert_common_fields(data)
    assert "updated_at" not in data, "append-only record must not expose updated_at"
    assert "version" not in data, "append-only record must not expose version"
    assert is_valid_uuid(data.get("enrollment_id", ""))
    assert is_valid_uuid(data.get("session_id", ""))
    assert isinstance(data["minutes_attended"], int) and data["minutes_attended"] > 0
    assert isinstance(data["passed"], bool)


def assert_biometric_reading(data: dict):
    """Append-only record: carries only id + created_at (PRD §2.4)."""
    _assert_common_fields(data)
    assert "updated_at" not in data, "append-only record must not expose updated_at"
    assert "version" not in data, "append-only record must not expose version"
    assert is_valid_uuid(data.get("enrollment_id", ""))
    assert data["kind"] in ("A1C", "WEIGHT_KG", "SYSTOLIC_BP")
    assert isinstance(data["value"], (int, float))
    assert data["source"] in ("CLINIC", "LAB_VERIFIED", "SELF_REPORT")


def assert_funder_report(data: dict):
    _assert_mutable_common_fields(data)
    assert is_valid_uuid(data.get("program_id", ""))
    assert is_valid_uuid(data.get("funding_pool_id", ""))
    assert data["basis"] in ("ACCRUAL", "CASH")
    for f in ("utilization_cents", "total_redeemed_cents", "total_match_cents",
              "active_enrollments", "a1c_improved_count", "revision_count"):
        assert isinstance(data[f], int), f"{f} must be an integer"
    assert data["status"] in ("DRAFT", "SUBMITTED", "RETURNED",
                              "ACCEPTED", "SUPERSEDED")


def assert_renewal(data: dict):
    _assert_mutable_common_fields(data)
    assert is_valid_uuid(data.get("enrollment_id", ""))
    assert isinstance(data["reason"], str)
    assert isinstance(data["resubmit_count"], int)
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED",
                              "DENIED", "SUPERSEDED")


def assert_pool_ledger_conserved(pool: dict):
    """PRD §2.8: available == committed - disbursed - reserved at all times."""
    assert pool["available_cents"] == (
        pool["committed_cents"] - pool["disbursed_cents"] - pool["reserved_cents"]
    ), (
        f"pool ledger drift: available {pool['available_cents']} != "
        f"committed {pool['committed_cents']} - disbursed {pool['disbursed_cents']} "
        f"- reserved {pool['reserved_cents']}"
    )


def assert_double_up_ledger_conserved(program: dict):
    """PRD §2.8: matched + remaining == double_up_pool_cents at all times."""
    assert program["double_up_matched_cents"] + program["double_up_remaining_cents"] == (
        program["double_up_pool_cents"]
    ), (
        f"Double-Up ledger drift: matched {program['double_up_matched_cents']} + "
        f"remaining {program['double_up_remaining_cents']} != "
        f"pool {program['double_up_pool_cents']}"
    )
