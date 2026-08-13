"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be a positive integer"
    )


def assert_cdi_program(data: dict):
    _assert_common(data)
    assert isinstance(data["facility_name"], str) and data["facility_name"]
    assert isinstance(data["program_code"], str) and data["program_code"]
    assert isinstance(data["baseline_cmi"], (int, float))
    assert isinstance(data["current_period_index"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED", "CLOSED")


def assert_escalation_policy(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("cdi_program_id", ""))
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["response_due_periods"], int) and data["response_due_periods"] >= 1
    assert isinstance(data["escalation_stage_periods"], int) and data["escalation_stage_periods"] >= 1
    assert isinstance(data["max_escalation_stage"], int)
    assert 1 <= data["max_escalation_stage"] <= 5
    assert isinstance(data["is_default"], bool)


def assert_provider(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("cdi_program_id", ""))
    assert isinstance(data["npi"], str) and data["npi"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["specialty"], str)
    assert isinstance(data["education_score"], int) and data["education_score"] >= 0
    assert isinstance(data["pattern_tally_json"], dict)
    assert data["education_flag"] in ("NONE", "WATCH", "COACHING", "INTENSIVE_REVIEW")


def assert_patient_case(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("cdi_program_id", ""))
    assert isinstance(data["mrn"], str) and data["mrn"]
    assert isinstance(data["admission_period"], int)
    assert isinstance(data["discharge_period"], int)
    assert data["discharge_period"] >= data["admission_period"]
    assert is_valid_uuid(data.get("attending_provider_id", ""))
    assert isinstance(data["initial_drg_code"], str) and data["initial_drg_code"]
    assert isinstance(data["initial_drg_weight"], (int, float))
    assert isinstance(data["working_drg_code"], str)
    assert isinstance(data["working_drg_weight"], (int, float))
    assert data["working_soi"] in (1, 2, 3, 4)
    assert data["working_rom"] in (1, 2, 3, 4)
    assert isinstance(data["priority_score"], (int, float))
    assert data["reconciliation_status"] in (
        "NOT_REQUIRED",
        "PENDING",
        "RESOLVED_CDI_PREVAILS",
        "RESOLVED_CODER_PREVAILS",
        "ESCALATED",
    )
    assert data["status"] in ("OPEN", "UNDER_REVIEW", "RECONCILED", "FINAL_CODED", "CLOSED")


def assert_cdi_review(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("patient_case_id", ""))
    assert is_valid_uuid(data.get("cdi_program_id", ""))
    assert isinstance(data["cdi_specialist_id"], str) and data["cdi_specialist_id"]
    assert isinstance(data["opened_period"], int)
    assert isinstance(data["opportunity_weight_delta"], (int, float))
    assert isinstance(data["opportunity_soi_delta"], int)
    assert isinstance(data["opportunity_rom_delta"], int)
    assert data.get("closed_reason") in (
        None,
        "OPPORTUNITY_CAPTURED",
        "NO_OPPORTUNITY",
        "SUPERSEDED",
        "CASE_DISCHARGED",
    )
    assert data["status"] in ("DRAFT", "ACTIVE", "ON_HOLD", "CLOSED")


def assert_cdi_query(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("cdi_review_id", ""))
    assert is_valid_uuid(data.get("patient_case_id", ""))
    assert is_valid_uuid(data.get("cdi_program_id", ""))
    assert is_valid_uuid(data.get("provider_id", ""))
    assert is_valid_uuid(data.get("escalation_policy_id", ""))
    assert isinstance(data["query_text"], str)
    assert isinstance(data["clinical_indicators"], list)
    assert isinstance(data["proposed_drg_code"], str)
    assert isinstance(data["proposed_drg_weight"], (int, float))
    assert data["proposed_soi"] in (1, 2, 3, 4)
    assert data["proposed_rom"] in (1, 2, 3, 4)
    assert isinstance(data["escalation_stage"], int) and data["escalation_stage"] >= 0
    assert data["status"] in (
        "DRAFT",
        "SENT",
        "RESPONDED",
        "ESCALATED",
        "NO_RESPONSE",
        "CANCELLED",
    )


def assert_query_response(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("cdi_query_id", ""))
    assert is_valid_uuid(data.get("patient_case_id", ""))
    assert isinstance(data["responder_provider_id"], str) and data["responder_provider_id"]
    assert data["response_type"] in (
        "AGREE",
        "DISAGREE",
        "CLARIFICATION_REQUESTED",
        "CLINICALLY_UNSUPPORTED",
    )
    assert isinstance(data["response_text"], str) and len(data["response_text"]) >= 1
    assert isinstance(data["responded_period"], int)
    assert isinstance(data["was_overdue"], bool)


def assert_reconciliation_event(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("patient_case_id", ""))
    assert is_valid_uuid(data.get("cdi_program_id", ""))
    assert isinstance(data["coder_user_id"], str) and data["coder_user_id"]
    assert isinstance(data["coder_drg_code"], str)
    assert isinstance(data["coder_drg_weight"], (int, float))
    assert isinstance(data["cdi_drg_code"], str)
    assert isinstance(data["cdi_drg_weight"], (int, float))
    assert data["status"] in (
        "OPEN",
        "RESOLVED_CDI_PREVAILS",
        "RESOLVED_CODER_PREVAILS",
        "ESCALATED",
    )


def assert_denial_risk_target(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("cdi_program_id", ""))
    assert isinstance(data["drg_code"], str) and data["drg_code"]
    assert isinstance(data["required_evidence_tags"], list)
    assert data["severity_floor"] in (1, 2, 3, 4)
    assert isinstance(data["active_from_period"], int)
    assert isinstance(data["active_to_period"], int)
    assert data["active_to_period"] >= data["active_from_period"]


def assert_provider_education_event(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("provider_id", ""))
    assert is_valid_uuid(data.get("cdi_program_id", ""))
    assert data["pattern_tag"] in (
        "LEADING_LANGUAGE",
        "NO_RESPONSE_PATTERN",
        "CLINICALLY_UNSUPPORTED_PATTERN",
        "OVERDUE_PATTERN",
    )
    assert isinstance(data["points_deducted"], int)
    assert 1 <= data["points_deducted"] <= 25
    assert isinstance(data["source_query_id"], str)
    assert isinstance(data["note"], str)
    assert isinstance(data["recorded_period"], int)


def assert_cmi_snapshot(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("cdi_program_id", ""))
    assert isinstance(data["as_of_period"], int)
    assert isinstance(data["case_count"], int) and data["case_count"] >= 0
    assert isinstance(data["unadjusted_cmi"], (int, float))
    assert isinstance(data["adjusted_cmi"], (int, float))
    assert isinstance(data["cdi_lift"], (int, float))
    assert isinstance(data["denial_target_misses"], int) and data["denial_target_misses"] >= 0


def assert_provider_education_invariants(data: dict):
    """Provider education invariants that must hold after any operation."""
    assert data["education_score"] >= 0, "education_score is floored at 0"
    score = data["education_score"]
    flag = data["education_flag"]
    if score >= 85:
        assert flag == "NONE", f"score {score} must yield NONE"
    elif score >= 70:
        assert flag == "WATCH", f"score {score} must yield WATCH"
    elif score >= 50:
        assert flag == "COACHING", f"score {score} must yield COACHING"
    else:
        assert flag == "INTENSIVE_REVIEW", f"score {score} must yield INTENSIVE_REVIEW"
