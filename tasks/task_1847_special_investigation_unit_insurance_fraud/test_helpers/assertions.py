"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be int >= 1"


def assert_claim(data: dict):
    _assert_common(data)
    assert isinstance(data["policy_number"], str) and data["policy_number"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["adjuster_id"], str)
    assert isinstance(data["claimed_amount_cents"], int)
    assert data["status"] in ["PENDING", "UNDER_SIU_REVIEW", "PAYMENT_DELAYED",
                              "DENIED", "PAID", "CLOSED"]
    assert data.get("payment_hold_reason") in [None, "SIU_INVESTIGATION",
                                               "EUO_NONAPPEARANCE", "FRAUD_CONFIRMED"]
    assert isinstance(data["paid_amount_cents"], int) and data["paid_amount_cents"] >= 0


def assert_adjuster(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["email"], str)
    assert isinstance(data["state_licenses"], list)


def assert_referral(data: dict):
    _assert_common(data)
    assert isinstance(data["claim_id"], str)
    assert data["submitted_by_role"] in ["ADJUSTER", "PROVIDER", "EXTERNAL_TIP", "AUTOMATED_RULE"]
    assert isinstance(data["red_flag_codes"], list)
    assert isinstance(data["suspicion_score"], int)
    assert data["score_band"] in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    assert data["status"] in ["SUBMITTED", "TRIAGED", "ACCEPTED", "DECLINED", "DUPLICATE_LINKED"]


def assert_case(data: dict):
    _assert_common(data)
    assert isinstance(data["claim_id"], str)
    assert data["status"] in ["INTAKE", "OPEN", "UNDER_INVESTIGATION", "EUO_PENDING",
                              "DECISION_PENDING", "CLOSED_SUBSTANTIATED",
                              "CLOSED_UNSUBSTANTIATED", "CLOSED_INSUFFICIENT",
                              "REFERRED_TO_BUREAU"]
    assert isinstance(data.get("substantiated_fraud_cents", 0), int)
    assert isinstance(data.get("euo_required", False), bool)


def assert_investigator(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["badge_number"], str)
    assert isinstance(data["state_certifications"], list)
    assert isinstance(data["max_active_cases"], int)
    assert 1 <= data["max_active_cases"] <= 20
    assert isinstance(data["active_case_count"], int) and data["active_case_count"] >= 0
    assert data["status"] in ["ACTIVE", "SUSPENDED", "TERMINATED"]


def assert_assignment(data: dict):
    _assert_common(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["investigator_id"], str)
    assert data["status"] in ["ACTIVE", "REASSIGNED", "COMPLETED", "TERMINATED"]


def assert_evidence(data: dict):
    _assert_common(data)
    assert isinstance(data["case_id"], str)
    assert data["evidence_type"] in ["STATEMENT", "SURVEILLANCE", "RECORDS",
                                     "SOCIAL_MEDIA", "PRIOR_CLAIM_HISTORY"]
    assert data["materiality"] in ["IMMATERIAL", "SUPPORTING", "SUBSTANTIVE"]
    assert isinstance(data["fraud_amount_cents"], int)
    assert data["status"] in ["LOGGED", "UNDER_REVIEW", "ADMITTED", "EXCLUDED", "SEALED"]


def assert_euo_session(data: dict):
    _assert_common(data)
    assert isinstance(data["case_id"], str)
    assert data["status"] in ["SCHEDULED", "NOTICE_SENT", "CONDUCTED", "NO_SHOW",
                              "RESCHEDULED", "CANCELLED"]
    assert isinstance(data.get("no_show_count", 0), int)


def assert_bureau_referral(data: dict):
    _assert_common(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["state_code"], str)
    assert data["status"] in ["DRAFT", "FILED", "ACKNOWLEDGED", "REJECTED_BY_BUREAU", "LATE_FILED"]
    assert isinstance(data.get("late_filing", False), bool)


def assert_provider_pattern(data: dict):
    _assert_common(data)
    assert isinstance(data["provider_npi"], str)
    assert isinstance(data["ring_signature"], str)
    assert isinstance(data.get("linked_case_ids", []), list)
    assert isinstance(data["pattern_score"], int)
    assert 0 <= data["pattern_score"] <= 100
    assert data["escalation_status"] in ["MONITORING", "ESCALATED_TO_NICB", "CLEARED",
                                         "MERGED_INTO_RING"]


def assert_ledger(data: dict):
    _assert_common(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["target_amount_cents"], int)
    assert isinstance(data["recovered_amount_cents"], int)
    assert isinstance(data["outstanding_amount_cents"], int)
    assert data["status"] in ["OPEN", "PARTIALLY_RECOVERED", "FULLY_RECOVERED", "WRITTEN_OFF"]


def assert_payment(data: dict):
    _assert_common(data)
    assert isinstance(data["ledger_id"], str)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["method"] in ["CHECK", "ACH", "WIRE", "WAGE_GARNISHMENT", "POLICY_OFFSET"]
    assert data["status"] in ["PENDING", "CLEARED", "RETURNED", "REVERSED"]


def assert_training_record(data: dict):
    _assert_common(data)
    assert isinstance(data["investigator_id"], str)
    assert isinstance(data["course_code"], str)
    assert isinstance(data["credit_hours"], int) and data["credit_hours"] >= 1


def assert_report(data: dict):
    _assert_common(data)
    assert data["report_type"] in ["QUARTERLY_SIU_ACTIVITY", "ANNUAL_ANTI_FRAUD_PLAN",
                                   "BUREAU_LATE_FILING_SUMMARY"]
    assert data["status"] in ["DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED_BY_REGULATOR"]


def assert_ledger_invariants(ledger: dict):
    """Ledger conserved quantity: recovered + outstanding == target; outstanding >= 0."""
    assert ledger["outstanding_amount_cents"] >= 0, "outstanding must never be negative"
    assert (ledger["recovered_amount_cents"] + ledger["outstanding_amount_cents"]
            == ledger["target_amount_cents"]), \
        "recovered + outstanding must equal target"
