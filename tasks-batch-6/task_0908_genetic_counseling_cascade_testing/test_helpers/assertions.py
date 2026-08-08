"""Entity assertions and domain invariant checkers.

These validate response structure against the PRD contract using the framework's
generic format checkers. They intentionally avoid asserting the value of nullable
computed fields (prior_risk_pct, carrier_result, ...) that are unset until a workflow
step populates them.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_family(data: dict):
    _assert_common(data)
    assert isinstance(data["family_name"], str) and len(data["family_name"]) > 0
    for f in ("outreach_budget_cents", "outreach_reserved_cents",
              "outreach_spent_cents", "outreach_available_cents",
              "cascade_invitations_sent_count", "cascade_cases_count"):
        assert isinstance(data[f], int), f"{f} must be an integer cent/count value"
    assert isinstance(data["cascade_uptake_pct"], (int, float))
    assert_family_ledger_invariant(data)


def assert_family_ledger_invariant(data: dict):
    """PRD 2.7 invariant: budget == available + reserved + spent."""
    assert data["outreach_budget_cents"] == (
        data["outreach_available_cents"]
        + data["outreach_reserved_cents"]
        + data["outreach_spent_cents"]
    ), "outreach ledger must reconcile: budget == available + reserved + spent"
    assert data["outreach_reserved_cents"] >= 0
    assert data["outreach_spent_cents"] >= 0


def assert_counselor(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["npi"], str)


def assert_lab(data: dict):
    _assert_common(data)
    assert isinstance(data["lab_name"], str)
    assert isinstance(data["max_concurrent_capacity"], int)
    assert isinstance(data["current_processing_load"], int)
    assert data["current_processing_load"] >= 0


def assert_case(data: dict):
    _assert_common(data)
    assert data["clinical_status"] in [
        "INTAKE", "RISK_ASSESSED", "TESTING", "DISCLOSED", "SURVEILLANCE", "WITHDRAWN"]
    assert data["billing_status"] in [
        "UNBILLED", "PENDING_AUTH", "AUTHORIZED", "BILLED", "PAID", "DENIED"]
    assert isinstance(data["sessions_used"], int)
    assert isinstance(data["sessions_remaining"], int)
    assert isinstance(data["covered_sessions"], int)
    assert_session_credit_invariant(data)


def assert_session_credit_invariant(data: dict):
    """PRD 2.8 invariant: covered_sessions == sessions_remaining + sessions_used."""
    assert data["covered_sessions"] == data["sessions_remaining"] + data["sessions_used"], \
        "session credit ledger must reconcile: covered == remaining + used"


def assert_pedigree_member(data: dict):
    _assert_common(data)
    assert data["degree"] in [0, 1, 2, 3]
    assert isinstance(data["affected"], bool)
    assert isinstance(data["is_at_risk"], bool)


def assert_consent(data: dict):
    _assert_common(data)
    assert data["status"] in ["PENDING", "SIGNED", "REVOKED"]
    assert data["consent_type"] in ["TESTING", "RESULT_DISCLOSURE", "CASCADE_CONTACT", "DATA_SHARING"]


def assert_session(data: dict):
    _assert_common(data)
    assert data["status"] in ["SCHEDULED", "COMPLETED", "CANCELLED", "NO_SHOW"]


def assert_order(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "SUBMITTED", "RESULTED", "CANCELLED"]
    assert isinstance(data["list_price_cents"], int)


def assert_result(data: dict):
    _assert_common(data)
    assert data["status"] in ["PENDING", "RELEASED", "DISCLOSED"]
    assert data["classification"] in [
        "PATHOGENIC", "LIKELY_PATHOGENIC", "VUS", "LIKELY_BENIGN", "BENIGN"]


def assert_invitation(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "SENT", "DECLINED", "ACCEPTED", "EXPIRED"]
    assert isinstance(data["estimated_cost_cents"], int)


def assert_claim(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "AUTHORIZED", "SUBMITTED", "PAID", "DENIED", "VOID"]
    assert isinstance(data["billed_total_cents"], int)


def assert_surveillance_plan(data: dict):
    _assert_common(data)
    assert data["status"] in ["ACTIVE", "SUPERSEDED", "COMPLETED", "CANCELLED"]
    assert data["risk_tier"] in ["LOW", "MODERATE", "HIGH"]
    assert isinstance(data["screening_interval_months"], int)


def assert_referral(data: dict):
    _assert_common(data)
    assert data["status"] in ["PENDING", "COMPLETED", "CANCELLED"]
    assert data["specialty"] in [
        "BREAST_SURGERY", "GI_ONCOLOGY", "GYN_ONCOLOGY", "CARDIOLOGY",
        "ENDOCRINOLOGY", "HIGH_RISK_CLINIC"]
