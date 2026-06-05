"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


# ─── Generic envelope-side assertions (PRD §2.4) ─────────────────


def assert_common_fields(data: dict):
    """Every persisted entity carries id, created_at, updated_at, version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be int >= 1, got {data.get('version')!r}"


# ─── Per-entity assertions ───────────────────────────────────────


def assert_patient(data: dict):
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["date_of_birth"], str)
    assert data["insurance_type"] in {"MEDICARE", "COMMERCIAL", "MEDICAID", "VA_TRICARE", "SELF_PAY"}
    assert isinstance(data["is_veteran"], bool)
    assert data["status"] in {"ACTIVE", "DISCHARGED", "INACTIVE"}


def assert_therapist(data: dict):
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["npi_number"], str) and len(data["npi_number"]) == 10
    assert isinstance(data["license_state"], str) and len(data["license_state"]) == 2
    assert isinstance(data["medicare_provider_enrolled"], bool)


def assert_veteran_referral(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["patient_id"])
    assert isinstance(data["referring_va_facility_code"], str)
    assert isinstance(data["referral_authorization_number"], str)
    assert isinstance(data["max_authorized_visits"], int)
    assert 1 <= data["max_authorized_visits"] <= 60
    assert isinstance(data["expires_on"], str)
    assert data["status"] in {"ISSUED", "CONSUMED", "EXPIRED", "CANCELLED"}


def assert_plan_of_care(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["patient_id"])
    assert is_valid_uuid(data["primary_therapist_id"])
    assert isinstance(data["diagnosis_icd10"], str)
    assert isinstance(data["certified_start_date"], str)
    assert isinstance(data["certified_end_date"], str)
    assert data["status"] in {"DRAFT", "ACTIVE", "RECERT_DUE", "DISCHARGED", "EXPIRED"}
    assert data["capped_status"] in {"UNDER_CAP", "AT_CAP_WARNING", "EXCEEDED"}
    assert isinstance(data["cumulative_billed_cents"], int)
    assert data["cumulative_billed_cents"] >= 0


def assert_evaluation(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["plan_of_care_id"])
    assert is_valid_uuid(data["therapist_id"])
    assert data["evaluation_kind"] in {"INITIAL", "RE_EVALUATION", "DISCHARGE"}
    assert isinstance(data["performed_on"], str)
    assert isinstance(data["functional_score"], int)
    assert 0 <= data["functional_score"] <= 100
    assert isinstance(data["minutes_spent"], int)
    assert 8 <= data["minutes_spent"] <= 240
    assert isinstance(data["billable_units"], int)
    assert data["billable_units"] >= 0


def assert_authorization_grant(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["plan_of_care_id"])
    assert isinstance(data["total_units_granted"], int)
    assert 1 <= data["total_units_granted"] <= 600
    assert isinstance(data["units_consumed"], int)
    assert data["units_consumed"] >= 0
    assert isinstance(data["units_finalized"], int)
    assert data["units_finalized"] >= 0
    assert isinstance(data["effective_from"], str)
    assert isinstance(data["effective_to"], str)
    assert data["status"] in {"ACTIVE", "EXHAUSTED", "EXPIRED", "CANCELLED"}


def assert_visit(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["authorization_grant_id"])
    assert is_valid_uuid(data["therapist_id"])
    assert isinstance(data["scheduled_start_utc"], str)
    assert isinstance(data["scheduled_end_utc"], str)
    assert isinstance(data["planned_minutes"], int)
    assert 8 <= data["planned_minutes"] <= 240
    assert isinstance(data["planned_units"], int)
    assert data["planned_units"] >= 0
    assert isinstance(data["billable_units"], int)
    assert data["billable_units"] >= 0
    assert isinstance(data["billed_cents"], int)
    assert data["billed_cents"] >= 0
    assert data["cpt_code"] in {
        "CPT_97110_THER_EX", "CPT_97112_NEURO_REED",
        "CPT_97140_MANUAL", "CPT_97530_THER_ACT",
    }
    assert data["status"] in {"SCHEDULED", "COMPLETED", "FINALIZED", "CANCELLED", "NO_SHOW"}


def assert_home_exercise_program(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["plan_of_care_id"])
    assert is_valid_uuid(data["prescribed_by_therapist_id"])
    assert isinstance(data["exercise_count"], int)
    assert 1 <= data["exercise_count"] <= 20
    assert isinstance(data["weekly_frequency"], int)
    assert 1 <= data["weekly_frequency"] <= 14
    assert isinstance(data["prescribed_on"], str)
    assert data["status"] in {"ACTIVE", "SUPERSEDED", "DISCONTINUED"}


def assert_mips_measure(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["patient_id"])
    assert is_valid_uuid(data["plan_of_care_id"])
    assert is_valid_uuid(data["reporting_therapist_id"])
    assert data["measure_code"] in {
        "MIPS128_FALL_RISK", "MIPS131_PAIN_ASSESSMENT", "MIPS182_FUNCTIONAL_OUTCOME",
    }
    assert isinstance(data["performance_period_start"], str)
    assert isinstance(data["performance_period_end"], str)
    assert isinstance(data["numerator_met"], bool)
    assert data["status"] in {"DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED"}


def assert_discharge_assessment(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["plan_of_care_id"])
    assert is_valid_uuid(data["assessing_therapist_id"])
    assert isinstance(data["final_functional_score"], int)
    assert 0 <= data["final_functional_score"] <= 100
    assert isinstance(data["goals_met_count"], int)
    assert 0 <= data["goals_met_count"] <= 20
    assert isinstance(data["total_goals_count"], int)
    assert 1 <= data["total_goals_count"] <= 20
    assert data["discharge_outcome"] in {"SUCCESSFUL", "PARTIAL", "UNSUCCESSFUL"}
    assert isinstance(data["assessed_on"], str)


# ─── Domain invariants ───────────────────────────────────────────


def assert_grant_consumption_invariant(data: dict):
    """units_consumed bound: should never exceed total_units_granted (PRD §3.4)."""
    assert data["units_consumed"] <= data["total_units_granted"], (
        f"units_consumed={data['units_consumed']} should not exceed "
        f"total_units_granted={data['total_units_granted']}"
    )
    assert data["units_finalized"] <= data["units_consumed"], (
        f"units_finalized={data['units_finalized']} should not exceed "
        f"units_consumed={data['units_consumed']}"
    )


def assert_capped_posture_consistent(data: dict):
    """Verify capped_status matches cumulative_billed_cents / capped_dollar_limit_cents (PRD §2.7)."""
    cum = data["cumulative_billed_cents"]
    cap = data.get("capped_dollar_limit_cents")
    posture = data["capped_status"]
    if cap is None:
        # DRAFT POC: no cap pinned yet, posture is UNDER_CAP (PRD §3.2).
        return
    if cum > cap:
        assert posture == "EXCEEDED", f"cum={cum} > cap={cap} → EXCEEDED expected, got {posture}"
    elif cum >= 0.90 * cap:
        assert posture == "AT_CAP_WARNING", \
            f"cum={cum} >= 0.90 * cap={cap} → AT_CAP_WARNING expected, got {posture}"
    else:
        assert posture == "UNDER_CAP", \
            f"cum={cum} < 0.90 * cap={cap} → UNDER_CAP expected, got {posture}"
