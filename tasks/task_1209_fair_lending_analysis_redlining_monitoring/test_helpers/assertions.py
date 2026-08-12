"""Entity assertions and domain invariant checkers (PRD sections 2 and 3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data):
    """PRD 2.4: id is a server-minted UUID; timestamps ISO 8601 with three
    fractional digits; version is an integer starting at 1."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_market(data):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["msa_code"], str) and data["msa_code"]
    assert isinstance(data["protected_group_population_share"], (int, float))
    assert isinstance(data["peer_group_code"], str) and data["peer_group_code"]


def assert_branch(data):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("market_id", "")), "market_id must be a UUID"
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["tract_minority_pct"], (int, float))
    assert isinstance(data["opened_on"], str) and data["opened_on"]
    assert data["status"] in ["ACTIVE", "CLOSED"]


def assert_loan_officer(data):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("branch_id", "")), "branch_id must be a UUID"
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["status"] in ["ACTIVE", "SUSPENDED"]
    assert isinstance(data["approved_exception_count"], int)
    assert isinstance(data["confirmed_override_count"], int)
    assert isinstance(data["validated_application_count"], int)
    assert isinstance(data["risk_score"], (int, float))
    assert data["monitoring_tier"] in ["GREEN", "WATCH", "RED"]


def assert_application(data):
    _assert_common_fields(data)
    for fk in ("market_id", "branch_id", "loan_officer_id"):
        assert is_valid_uuid(data.get(fk, "")), f"{fk} must be a UUID"
    assert data["product_type"] in ["CONVENTIONAL", "FHA", "VA"]
    assert data["applicant_group"] in ["PROTECTED_1", "PROTECTED_2", "CONTROL"]
    assert data["outcome"] in ["ORIGINATED", "DENIED", "WITHDRAWN", "APPROVED_NOT_ACCEPTED"]
    assert isinstance(data["note_rate_bps"], int)
    assert isinstance(data["loan_amount_cents"], int)
    assert isinstance(data["credit_score"], int)
    assert isinstance(data["dti_pct"], (int, float))
    assert isinstance(data["application_date"], str)
    assert isinstance(data["decision_date"], str)
    assert data["status"] in ["RECEIVED", "VALIDATED", "EXCLUDED"]
    assert data["has_exception"] in ["NONE", "REQUESTED", "APPROVED"]


def assert_pricing_exception(data):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("application_id", "")), "application_id must be a UUID"
    assert is_valid_uuid(data.get("loan_officer_id", "")), "loan_officer_id must be a UUID"
    assert data["kind"] in ["RATE_ABOVE_CAP", "RATE_BELOW_FLOOR", "FEE_WAIVER"]
    assert isinstance(data["requested_rate_bps"], int)
    assert isinstance(data["justification"], str)
    assert data["status"] in [
        "REQUESTED", "ESCALATED", "APPROVED", "DENIED", "WITHDRAWN", "EXPIRED", "RESCINDED",
    ]


def assert_underwriting_override(data):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("application_id", "")), "application_id must be a UUID"
    assert is_valid_uuid(data.get("loan_officer_id", "")), "loan_officer_id must be a UUID"
    assert data["original_decision"] in ["APPROVE", "DENY"]
    assert data["overridden_decision"] in ["APPROVE", "DENY"]
    assert isinstance(data["justification"], str)
    assert data["status"] in ["RECORDED", "CONFIRMED", "REVERSED"]


def assert_peer_benchmark(data):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("market_id", "")), "market_id must be a UUID"
    assert isinstance(data["period_start"], str)
    assert isinstance(data["period_end"], str)
    assert isinstance(data["peer_protected_origination_rate"], (int, float))
    assert isinstance(data["peer_origination_count"], int)
    assert isinstance(data["source"], str)


def assert_analysis_run(data):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("market_id", "")), "market_id must be a UUID"
    assert data["product_type"] in ["CONVENTIONAL", "FHA", "VA"]
    assert data["prohibited_basis"] in ["RACE", "ETHNICITY", "SEX", "AGE"]
    assert isinstance(data["period_start"], str)
    assert isinstance(data["period_end"], str)
    assert data["status"] in [
        "DRAFT", "DATA_LOCKED", "COMPUTED", "UNDER_REVIEW", "FINALIZED", "ARCHIVED",
    ]
    assert isinstance(data["open_finding_count"], int)


def assert_disparity_finding(data):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("analysis_run_id", "")), "analysis_run_id must be a UUID"
    assert data["kind"] in [
        "DENIAL_DISPARITY", "PRICING_DISPARITY", "PENETRATION_SHORTFALL",
        "OVERRIDE_ASYMMETRY", "MANUAL",
    ]
    assert data["source"] in ["AUTO", "MANUAL"]
    assert data["status"] in [
        "FLAGGED", "UNDER_REVIEW", "SUBSTANTIATED", "REFUTED", "CLOSED", "SUPERSEDED",
    ]
    assert isinstance(data["harmed_application_ids"], list)
    assert isinstance(data["reopen_count"], int)


def assert_matched_pair_review(data):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("finding_id", "")), "finding_id must be a UUID"
    assert is_valid_uuid(data.get("target_application_id", "")), (
        "target_application_id must be a UUID"
    )
    assert isinstance(data["selector_used"], bool)
    assert data["status"] in [
        "PENDING", "INITIAL_REVIEWED", "DISPUTED", "CONFIRMED", "SUPERSEDED",
    ]


def assert_corrective_action_plan(data):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("finding_id", "")), "finding_id must be a UUID"
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["pool_cents"], int)
    assert isinstance(data["remaining_cents"], int)
    assert isinstance(data["disbursed_cents"], int)
    assert isinstance(data["due_date"], str)
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "EXECUTING", "OVERDUE", "RETURNED",
        "COMPLETED", "SUPERSEDED", "CANCELLED",
    ]


def assert_remediation_payment(data):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("corrective_action_plan_id", "")), (
        "corrective_action_plan_id must be a UUID"
    )
    assert is_valid_uuid(data.get("application_id", "")), "application_id must be a UUID"
    assert isinstance(data["amount_cents"], int)
    assert data["origin"] in ["AUTO_ALLOCATED", "MANUAL"]
    assert data["status"] in ["PENDING", "DISBURSED", "VOIDED", "RETURNED"]


def assert_self_test(data):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("market_id", "")), "market_id must be a UUID"
    assert isinstance(data["window_start"], str)
    assert isinstance(data["window_end"], str)
    assert isinstance(data["privileged"], bool)
    assert data["disclosure_status"] in ["PRIVILEGED", "DISCLOSABLE"]
    assert data["status"] in [
        "ACTIVE", "CLOSED_NO_VIOLATION", "CLOSED_VIOLATION", "REMEDIATED", "PRIVILEGE_LOST",
    ]
    assert isinstance(data["cycles_open"], int)


def assert_board_report(data):
    _assert_common_fields(data)
    assert isinstance(data["period_start"], str)
    assert isinstance(data["period_end"], str)
    assert data["status"] in ["DRAFT", "SUBMITTED", "APPROVED", "RETURNED", "PUBLISHED"]
    for count_field in (
        "substantiated_finding_count", "caps_executing_count",
        "red_officer_count", "privileged_exclusion_count",
    ):
        assert isinstance(data[count_field], int), f"{count_field} must be an integer"


def assert_cap_funds_invariant(cap, payments):
    """PRD 2.10 funds-conservation invariant: pool_cents equals remaining_cents
    plus the sum of amount_cents over payments in PENDING or DISBURSED status."""
    allocated = sum(
        p["amount_cents"] for p in payments if p["status"] in ("PENDING", "DISBURSED")
    )
    assert cap["pool_cents"] == cap["remaining_cents"] + allocated, (
        f"Funds not conserved: pool {cap['pool_cents']} != remaining "
        f"{cap['remaining_cents']} + allocated {allocated}"
    )
    disbursed = sum(p["amount_cents"] for p in payments if p["status"] == "DISBURSED")
    assert cap["disbursed_cents"] == disbursed, (
        f"disbursed_cents {cap['disbursed_cents']} != sum of DISBURSED {disbursed}"
    )
