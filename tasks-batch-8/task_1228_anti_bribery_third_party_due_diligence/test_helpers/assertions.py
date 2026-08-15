"""Entity assertions and domain invariant checkers (PRD §2.4 common fields)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def assert_country_risk_profile(data: dict):
    _assert_common(data)
    assert isinstance(data["country_code"], str) and len(data["country_code"]) == 2
    assert isinstance(data["cpi_score"], int) and 0 <= data["cpi_score"] <= 100
    assert isinstance(data["sanctioned"], bool)


def assert_risk_scoring_policy(data: dict):
    _assert_common(data)
    assert data["policy_status"] in ("DRAFT", "ACTIVE", "SUPERSEDED")
    for field in ("w_country", "w_industry", "w_touchpoint",
                  "tier_medium_min", "tier_high_min", "tier_critical_min"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert data["w_country"] + data["w_industry"] + data["w_touchpoint"] == 100


def assert_third_party(data: dict):
    _assert_common(data)
    assert data["onboarding_status"] in (
        "DRAFT", "SCREENING", "DD_REVIEW", "ENHANCED_REVIEW",
        "APPROVED", "REJECTED", "SUSPENDED", "TERMINATED",
    )
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["country_code"], str)
    assert data["industry"] in (
        "TECHNOLOGY", "LOGISTICS", "CONSULTING", "CONSTRUCTION", "GOVERNMENT_RELATIONS",
    )
    assert data["government_touchpoint"] in ("NONE", "INDIRECT", "DIRECT")
    assert isinstance(data["sponsor_user_id"], str) and data["sponsor_user_id"]
    assert isinstance(data["gov_gift_rolling_12m_cents"], int)
    assert data["gov_gift_rolling_12m_cents"] >= 0
    if data.get("risk_score_provisional") is not None:
        assert 0 <= data["risk_score_provisional"] <= 100
    if data.get("risk_score_final") is not None:
        assert 0 <= data["risk_score_final"] <= 100
    if data.get("risk_tier") is not None:
        assert data["risk_tier"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")


def assert_screening_check(data: dict):
    _assert_common(data)
    assert data["check_type"] in ("PEP", "ADVERSE_MEDIA", "SANCTIONS")
    assert data["check_status"] in (
        "QUEUED", "CLEAR", "POTENTIAL_HIT", "HIT_CONFIRMED", "HIT_DISMISSED",
    )


def assert_questionnaire(data: dict):
    _assert_common(data)
    assert data["questionnaire_status"] in (
        "ISSUED", "SUBMITTED", "RETURNED", "ACCEPTED", "SUPERSEDED",
    )
    if data.get("red_flag_count") is not None:
        assert 0 <= data["red_flag_count"] <= 3


def assert_red_flag(data: dict):
    _assert_common(data)
    assert data["source_type"] in ("SCREENING", "QUESTIONNAIRE", "AUDIT", "SYSTEM", "MANUAL")
    assert data["severity"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert data["flag_status"] in ("OPEN", "UNDER_ENHANCED_REVIEW", "CLEARED", "SUBSTANTIATED")


def assert_escalation_case(data: dict):
    _assert_common(data)
    assert data["case_status"] in ("ENHANCED_DD", "DECIDED")
    if data.get("decision_outcome") is not None:
        assert data["decision_outcome"] in ("APPROVE_WITH_CONDITIONS", "REJECT", "TERMINATE")


def assert_contract(data: dict):
    _assert_common(data)
    assert data["contract_status"] in ("DRAFT", "PENDING_CLAUSES", "ACTIVE", "EXPIRED", "TERMINATED")
    assert isinstance(data["contract_value_cents"], int) and data["contract_value_cents"] > 0
    assert isinstance(data["approved_payments_total_cents"], int)
    assert data["approved_payments_total_cents"] >= 0, "payment ledger must never go negative"


def assert_certification(data: dict):
    _assert_common(data)
    assert data["cert_type"] in ("ANNUAL_ABAC", "CODE_OF_CONDUCT")
    assert data["cert_status"] in ("PENDING", "SUBMITTED", "VERIFIED", "REJECTED", "LAPSED")


def assert_payment_request(data: dict):
    _assert_common(data)
    assert data["payment_type"] in ("COMMISSION", "SUCCESS_FEE", "REIMBURSEMENT")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["payment_status"] in ("SUBMITTED", "APPROVED", "BLOCKED", "REVERSED")
    assert isinstance(data["submitted_by_user_id"], str) and data["submitted_by_user_id"]


def assert_gift_entry(data: dict):
    _assert_common(data)
    assert data["entry_type"] in ("GIFT", "HOSPITALITY", "TRAVEL")
    assert isinstance(data["recipient_is_government_official"], bool)
    assert isinstance(data["value_cents"], int) and data["value_cents"] > 0
    assert isinstance(data["value_usd_cents"], int) and data["value_usd_cents"] > 0
    assert data["entry_status"] in ("PENDING_APPROVAL", "APPROVED", "REJECTED", "VOIDED")
    assert isinstance(data["requires_enhanced_approval"], bool)


def assert_rediligence_cycle(data: dict):
    _assert_common(data)
    assert data["cycle_status"] in ("SCHEDULED", "IN_PROGRESS", "OVERDUE", "COMPLETED")
    assert data["trigger_source"] in ("SCHEDULED", "MANUAL")
    if data.get("outcome") is not None:
        assert data["outcome"] in ("REAFFIRM", "DOWNGRADE", "TERMINATE")


def assert_audit_exercise(data: dict):
    _assert_common(data)
    assert data["audit_status"] in ("NOTICED", "IN_FIELDWORK", "FINDINGS_ISSUED", "CLOSED")
    assert isinstance(data["notice_date"], str) and data["notice_date"]


def assert_training_assignment(data: dict):
    _assert_common(data)
    assert data["training_status"] in ("ASSIGNED", "OVERDUE", "COMPLETED")
    assert isinstance(data["assignee_user_id"], str) and data["assignee_user_id"]
    assert isinstance(data["course_code"], str) and data["course_code"]


def assert_ledger_invariant(contract: dict):
    """The approved-payments ledger never goes negative (PRD §3.7)."""
    assert contract["approved_payments_total_cents"] >= 0
