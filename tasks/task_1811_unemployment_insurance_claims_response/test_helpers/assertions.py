"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{label}.version must be a positive integer"


def assert_employer(data: dict):
    _assert_common(data, "EmployerAccount")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["fein"], str) and len(data["fein"]) == 9
    assert data["merit_rating_method"] in ("RESERVE_RATIO", "BENEFIT_RATIO")
    assert isinstance(data["reserve_balance_cents"], int)
    assert isinstance(data["taxable_payroll_cents"], int)
    assert isinstance(data["current_tax_rate_bps"], int)
    assert isinstance(data["protest_credits_cents"], int)
    assert data["compliance_posture"] in ("CLEAR", "WATCH", "SANCTIONED")
    assert isinstance(data["late_response_strikes"], int)


def assert_tpa_engagement(data: dict):
    _assert_common(data, "TpaEngagement")
    assert is_valid_uuid(data.get("employer_id", ""))
    assert isinstance(data["tpa_name"], str) and data["tpa_name"]
    assert data["authority_scope"] in (
        "RESPONSE_ONLY", "RESPONSE_AND_HEARING", "FULL")
    assert is_iso8601_timestamp(data.get("effective_from", ""))
    assert is_iso8601_timestamp(data.get("effective_to", ""))
    assert data["oversight_status"] in (
        "ACTIVE", "SUSPENDED", "REINSTATED", "TERMINATED")
    assert isinstance(data["breach_count"], int) and data["breach_count"] >= 0


def assert_state_rule(data: dict):
    _assert_common(data, "StateRule")
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["response_window_days"], int)
    assert data["window_basis"] in ("CALENDAR", "BUSINESS")
    assert isinstance(data["appeal_window_days"], int)
    assert isinstance(data["protest_window_days"], int)
    assert data["weekend_shift"] in ("NEXT_BUSINESS_DAY", "NONE")


def assert_separation(data: dict):
    _assert_common(data, "ClaimantSeparation")
    assert is_valid_uuid(data.get("employer_id", ""))
    assert isinstance(data["claimant_name"], str) and data["claimant_name"]
    assert isinstance(data["ssn_last4"], str) and len(data["ssn_last4"]) == 4
    assert is_iso8601_timestamp(data.get("last_day_worked", ""))
    assert data["separation_reason"] in (
        "VOLUNTARY_QUIT", "DISCHARGE_MISCONDUCT", "DISCHARGE_NON_MISCONDUCT",
        "LAYOFF", "LEAVE_OF_ABSENCE")
    assert data["reason_coding_confidence"] in ("UNREVIEWED", "CONFIRMED", "DISPUTED")


def assert_claim(data: dict):
    _assert_common(data, "UiClaim")
    assert is_valid_uuid(data.get("employer_id", ""))
    assert is_valid_uuid(data.get("separation_id", ""))
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["state_claim_number"], str)
    assert is_iso8601_timestamp(data.get("notice_received_at", ""))
    assert is_iso8601_timestamp(data.get("response_due_at", ""))
    assert is_iso8601_timestamp(data.get("benefit_year_begin", ""))
    assert isinstance(data["weekly_benefit_amount_cents"], int)
    assert isinstance(data["max_benefit_cents"], int)
    assert isinstance(data["charged_amount_cents"], int)
    assert data["status"] in (
        "NOTICE_RECEIVED", "RESPONSE_IN_PROGRESS", "RESPONSE_SUBMITTED",
        "LATE_RESPONSE", "UNDER_ADJUDICATION", "DETERMINED", "HEARING_PENDING",
        "CLOSED", "WITHDRAWN")
    assert data.get("response_channel") in (None, "SELF", "TPA")
    assert data["adjudication_posture"] in ("STANDARD", "EXPEDITED")


def assert_response(data: dict):
    _assert_common(data, "ClaimResponse")
    assert is_valid_uuid(data.get("claim_id", ""))
    assert data["response_type"] in ("PROTEST", "NO_PROTEST", "INFORMATION_ONLY")
    assert data["separation_reason_code"] in (
        "VOLUNTARY_QUIT", "DISCHARGE_MISCONDUCT", "DISCHARGE_NON_MISCONDUCT",
        "LAYOFF", "LEAVE_OF_ABSENCE")
    assert isinstance(data["narrative"], str)
    assert isinstance(data["completeness_score"], int)
    assert 0 <= data["completeness_score"] <= 100
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED_INSUFFICIENT", "SUPERSEDED")


def assert_evidence(data: dict):
    _assert_common(data, "EvidenceDocument")
    assert is_valid_uuid(data.get("claim_id", ""))
    assert data["doc_category"] in (
        "WRITTEN_WARNING", "SIGNED_POLICY", "FINAL_INCIDENT_REPORT",
        "ATTENDANCE_RECORD", "PERFORMANCE_REVIEW", "RESIGNATION_LETTER", "OTHER")
    assert is_iso8601_timestamp(data.get("doc_date", ""))
    assert isinstance(data["authenticated"], bool)
    assert isinstance(data["weight_points"], int)


def assert_determination(data: dict):
    _assert_common(data, "Determination")
    assert is_valid_uuid(data.get("claim_id", ""))
    assert data["outcome"] in ("ALLOWED", "DENIED", "ALLOWED_NO_CHARGE")
    assert is_iso8601_timestamp(data.get("mailed_at", ""))
    assert is_iso8601_timestamp(data.get("appeal_due_at", ""))
    assert data["status"] in (
        "ISSUED", "APPEALED_BY_EMPLOYER", "APPEALED_BY_CLAIMANT", "FINAL",
        "REVERSED")


def assert_appeal(data: dict):
    _assert_common(data, "Appeal")
    assert is_valid_uuid(data.get("determination_id", ""))
    assert data["appellant"] in ("EMPLOYER", "CLAIMANT")
    assert is_iso8601_timestamp(data.get("filed_at", ""))
    assert data["timeliness"] in ("ON_TIME", "LATE")
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1
    assert data["status"] in (
        "FILED", "DOCKETED", "HEARD", "DECIDED_AFFIRMED", "DECIDED_REVERSED",
        "REMANDED", "WITHDRAWN", "DISMISSED_UNTIMELY")


def assert_hearing(data: dict):
    _assert_common(data, "Hearing")
    assert is_valid_uuid(data.get("appeal_id", ""))
    assert is_valid_uuid(data.get("claim_id", ""))
    assert is_iso8601_timestamp(data.get("scheduled_start", ""))
    assert is_iso8601_timestamp(data.get("scheduled_end", ""))
    assert isinstance(data["referee_id"], str)
    assert isinstance(data["continuance_count"], int) and data["continuance_count"] >= 0
    assert data["status"] in (
        "SCHEDULED", "PREP_IN_PROGRESS", "READY", "HELD", "CONTINUED", "CLOSED")


def assert_witness(data: dict):
    _assert_common(data, "Witness")
    assert is_valid_uuid(data.get("hearing_id", ""))
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["witness_role"] in (
        "DIRECT_SUPERVISOR", "HR_CUSTODIAN", "POLICY_AUTHOR", "CLAIMANT", "OTHER")
    assert is_iso8601_timestamp(data.get("availability_start", ""))
    assert is_iso8601_timestamp(data.get("availability_end", ""))
    assert data["prep_status"] in (
        "UNPREPARED", "BRIEFED", "EXHIBITS_REVIEWED", "READY")


def assert_statement(data: dict):
    _assert_common(data, "ChargeStatement")
    assert is_valid_uuid(data.get("employer_id", ""))
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["quarter"], str)
    assert is_iso8601_timestamp(data.get("issued_at", ""))
    assert is_iso8601_timestamp(data.get("protest_due_at", ""))
    assert isinstance(data["total_charged_cents"], int)
    assert data["status"] in ("ISSUED", "UNDER_AUDIT", "AUDIT_COMPLETE", "RECONCILED")


def assert_line_item(data: dict):
    _assert_common(data, "ChargeLineItem")
    assert is_valid_uuid(data.get("statement_id", ""))
    assert is_valid_uuid(data.get("claim_id", ""))
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["benefit_weeks"], int)
    assert data["erroneous_reason"] in (
        "NONE", "CLAIMANT_NOT_SEPARATED", "WRONG_EMPLOYER", "ALREADY_PROTESTED",
        "EXCEEDS_MAX_BENEFIT", "DUPLICATE_LINE")
    assert data["status"] in ("PENDING", "PROTESTED", "SUSTAINED", "REVERSED", "WAIVED")


def assert_protest(data: dict):
    _assert_common(data, "ChargeProtest")
    assert is_valid_uuid(data.get("line_item_id", ""))
    assert is_valid_uuid(data.get("statement_id", ""))
    assert is_iso8601_timestamp(data.get("filed_at", ""))
    assert data["timeliness"] in ("ON_TIME", "LATE")
    assert data["protest_basis"] in (
        "CLAIMANT_NOT_SEPARATED", "WRONG_EMPLOYER", "ALREADY_PROTESTED",
        "EXCEEDS_MAX_BENEFIT", "DUPLICATE_LINE")
    assert isinstance(data["evidence_strength"], int)
    assert 0 <= data["evidence_strength"] <= 100
    assert data["status"] in (
        "FILED", "UNDER_REVIEW", "SUSTAINED", "DENIED", "WITHDRAWN",
        "DISMISSED_UNTIMELY")


def assert_model(data: dict):
    _assert_common(data, "ExperienceRatingModel")
    assert is_valid_uuid(data.get("employer_id", ""))
    assert isinstance(data["model_year"], int)
    assert data["variant"] in ("RESERVE_RATIO", "BENEFIT_RATIO")
    assert data["kind"] in ("OFFICIAL", "WHAT_IF")
    assert isinstance(data["projected_rate_bps"], int)
    assert isinstance(data["projected_liability_cents"], int)
    assert data["status"] in ("DRAFT", "FINALIZED", "SUPERSEDED")
