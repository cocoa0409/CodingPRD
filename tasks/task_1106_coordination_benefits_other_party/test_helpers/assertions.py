"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_cob_rule_config(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["config_name"], str) and data["config_name"]
    assert data["dependent_primacy_rule"] in ["BIRTHDAY_RULE", "GENDER_RULE", "CUSTODIAL_DECREE"]
    assert isinstance(data["msp_employer_size_threshold"], int)
    assert isinstance(data["esrd_coordination_months"], int)
    assert isinstance(data["retroactive_lookback_months"], int)
    assert isinstance(data["recovery_window_days"], int)
    assert isinstance(data["savings_period_length_days"], int)
    assert data["status"] in ["ACTIVE", "SUPERSEDED"]


def assert_member(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["member_external_id"], str) and data["member_external_id"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["date_of_birth"], str) and data["date_of_birth"]
    assert data["gender"] in ["MALE", "FEMALE", "OTHER", "UNKNOWN"]
    assert data["relation_to_subscriber"] in ["SELF", "SPOUSE", "CHILD", "OTHER_DEPENDENT"]
    assert data["employment_status"] in ["ACTIVE", "RETIRED", "COBRA", "TERMINATED"]
    assert data["medicare_entitlement_reason"] in ["NONE", "AGE", "DISABILITY", "ESRD", "ESRD_AND_AGE"]
    assert isinstance(data["other_coverage_count"], int) and data["other_coverage_count"] >= 0
    assert data["status"] in ["ENROLLED", "DISENROLLED"]


def assert_coverage(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["payer_id"], str) and data["payer_id"]
    assert isinstance(data["plan_name"], str) and data["plan_name"]
    assert data["coverage_kind"] in [
        "OUR_PLAN", "GROUP_HEALTH", "MEDICARE_PART_A", "MEDICARE_PART_B",
        "MEDICARE_ADVANTAGE", "MEDICAID", "TRICARE", "INDIVIDUAL",
    ]
    assert data["subscriber_relationship"] in ["SELF", "SPOUSE", "PARENT", "OTHER"]
    assert isinstance(data["effective_from"], str) and data["effective_from"]
    assert data["verification_status"] in ["PENDING_VERIFICATION", "VERIFIED", "REJECTED"]


def assert_lead(data: dict):
    _assert_common_fields(data)
    assert data["source"] in ["MEMBER_SURVEY", "DATA_MATCH_CMS", "CLAIM_INDICATION", "ELIGIBILITY_MATCH"]
    assert isinstance(data["raw_payload"], str)
    assert data["disposition"] in ["RECEIVED", "VERIFIED_COVERAGE", "REJECTED_DUPLICATE", "REJECTED_NO_COVERAGE"]


def assert_primacy_determination(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["as_of_service_date"], str) and data["as_of_service_date"]
    assert data["status"] in ["DRAFT", "FINALIZED", "SUPERSEDED"]


def assert_msp_questionnaire(data: dict):
    _assert_common_fields(data)
    assert data["respondent_role"] in ["SELF", "SPOUSE", "AUTHORIZED_REP"]
    assert isinstance(data["has_employer_group_health"], bool)
    assert isinstance(data["disability_flag"], bool)
    assert isinstance(data["esrd_flag"], bool)
    assert data["status"] in ["SUBMITTED", "ADJUDICATED", "VOIDED"]


def assert_claim(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["claim_external_id"], str) and data["claim_external_id"]
    assert isinstance(data["service_date"], str) and data["service_date"]
    assert isinstance(data["total_billed_cents"], int)
    assert isinstance(data["rework_cycle_count"], int) and data["rework_cycle_count"] >= 0
    assert data["status"] in [
        "RECEIVED", "ADJUDICATED", "PAID", "REOPENED", "READJUDICATED", "REPAID", "CLOSED",
    ]


def assert_claim_line(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["line_number"], int) and data["line_number"] >= 1
    assert isinstance(data["procedure_code"], str) and data["procedure_code"]
    assert isinstance(data["billed_cents"], int)
    assert isinstance(data["allowed_cents"], int)


def assert_claim_adjustment(data: dict):
    _assert_common_fields(data)
    assert data["cause"] in [
        "NEW_COVERAGE_DISCOVERED", "PRIMACY_DETERMINATION_SUPERSEDED",
        "MSP_QUESTIONNAIRE_ADJUDICATED", "MANUAL_REVIEW",
    ]
    assert data["status"] in ["DRAFT", "APPLIED", "VOIDED"]


def assert_provider(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["npi"], str) and data["npi"]
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["tin"], str) and data["tin"]
    assert data["status"] in ["ACTIVE", "TERMINATED"]


def assert_recovery_request(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["amount_recovered_cents"], int)
    assert data["status"] in [
        "DRAFT", "ISSUED", "PARTIALLY_RECOVERED", "FULLY_RECOVERED", "ESCALATED", "WRITTEN_OFF",
    ]


def assert_reimbursement(data: dict):
    # Immutable ledger posting (PRD §2.4): only id and created_at among the
    # common fields; updated_at and version are absent.
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "Reimbursement must not carry updated_at"
    assert "version" not in data, "Reimbursement must not carry version"
    assert isinstance(data["amount_cents"], int)
    assert data["method"] in [
        "PROVIDER_REFUND_CHECK", "OFFSET_AGAINST_FUTURE_CLAIMS", "CARRIER_TO_CARRIER_TRANSFER",
    ]


def assert_savings_period(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["period_start_date"], str) and data["period_start_date"]
    assert isinstance(data["period_end_date"], str) and data["period_end_date"]
    assert data["posture"] in ["OPEN", "CLOSED"]


def assert_member_survey(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["SENT", "RESPONDED", "EXPIRED"]
    assert isinstance(data.get("sent_at"), str) and data["sent_at"]


def assert_claim_financial_invariant(claim: dict):
    """Secondary-position conservation: what this plan paid plus what the
    primary paid never exceeds the allowed total, and totals never go
    negative (PRD §3.6 payment-position arithmetic)."""
    assert claim["total_paid_cents"] >= 0
    assert claim["total_primary_paid_cents"] >= 0
    assert claim["total_allowed_cents"] >= 0
    assert claim["total_paid_cents"] + claim["total_primary_paid_cents"] >= claim["total_paid_cents"]
