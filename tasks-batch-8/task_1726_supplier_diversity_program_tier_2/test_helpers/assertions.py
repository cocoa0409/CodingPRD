"""Entity assertions and domain invariant checkers (PRD resource-identity and
business-workflow rules)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import RISK_SCORE_CAP


def _assert_common(data: dict):
    """PRD: every persisted resource carries id / created_at / updated_at and an
    integer version starting at 1."""
    assert is_valid_uuid(data.get("id", "")), \
        f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be an ISO 8601 UTC timestamp"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be an ISO 8601 UTC timestamp"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be an integer >= 1"


def assert_business_unit(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["lead_user_id"], str) and data["lead_user_id"]
    assert isinstance(data["inclusion_min_diverse_bidders"], int)
    assert 0 <= data["inclusion_min_diverse_bidders"] <= 10
    assert isinstance(data["lifetime_imported_spend_cents"], int)
    assert isinstance(data["lifetime_voided_spend_cents"], int)


def assert_supplier(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["tax_id"], str) and data["tax_id"]
    assert data["kind"] in ("DIVERSE", "PRIME", "BOTH")
    assert data["status"] in ("REGISTERED", "ACTIVE", "SUSPENDED")
    assert isinstance(data["diverse_eligible"], bool)
    assert isinstance(data["risk_score_standard"], int)
    assert isinstance(data["risk_score_conservative"], int)
    assert 0 <= data["risk_score_standard"] <= RISK_SCORE_CAP
    assert 0 <= data["risk_score_conservative"] <= RISK_SCORE_CAP


def assert_certification(data: dict):
    _assert_common(data)
    assert isinstance(data["supplier_id"], str) and data["supplier_id"]
    assert data["cert_type"] in (
        "MBE", "WBE", "VET", "SDVET", "LGBTQBE", "DOBE", "SBA8A", "SELF_CERT")
    assert isinstance(data["certifying_body"], str) and data["certifying_body"]
    assert isinstance(data["certificate_number"], str)
    assert isinstance(data["valid_from"], str)
    assert isinstance(data["valid_to"], str)
    assert data["status"] in (
        "SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED", "VERIFIED",
        "REJECTED", "EXPIRED", "REVOKED")


def assert_spend_record(data: dict):
    _assert_common(data)
    assert isinstance(data["supplier_id"], str) and data["supplier_id"]
    assert isinstance(data["business_unit_id"], str) and data["business_unit_id"]
    assert isinstance(data["amount_cents"], int)
    assert data["amount_cents"] > 0
    assert isinstance(data["transaction_date"], str)
    assert isinstance(data["payment_date"], str)
    assert data["status"] in ("POSTED", "VOIDED")


def assert_tier2_report(data: dict):
    _assert_common(data)
    assert isinstance(data["prime_supplier_id"], str) and data["prime_supplier_id"]
    assert isinstance(data["business_unit_id"], str) and data["business_unit_id"]
    assert isinstance(data["reporting_period"], str)
    assert isinstance(data["total_subcontracted_cents"], int)
    assert isinstance(data["total_diverse_tier2_cents"], int)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "RETURNED", "APPROVED", "SUPERSEDED")


def assert_program_goal(data: dict):
    _assert_common(data)
    assert isinstance(data["business_unit_id"], str) and data["business_unit_id"]
    assert isinstance(data["fiscal_year"], int)
    assert data["cert_category"] in (
        "ALL", "MBE", "WBE", "VET", "SDVET", "LGBTQBE", "DOBE", "SBA8A",
        "SELF_CERT")
    assert data["goal_type"] in ("PERCENT_OF_SPEND", "ABSOLUTE_AMOUNT")
    assert isinstance(data["target_value"], (int, float))
    assert data["status"] in ("DRAFT", "PUBLISHED", "SUPERSEDED")


def assert_scorecard(data: dict):
    _assert_common(data)
    assert isinstance(data["business_unit_id"], str) and data["business_unit_id"]
    assert isinstance(data["reporting_period"], str)
    assert data["attribution_basis"] in ("ACCRUAL", "CASH")
    assert isinstance(data["total_spend_cents"], int)
    assert isinstance(data["direct_diverse_spend_cents"], int)
    assert isinstance(data["tier2_diverse_spend_cents"], int)
    assert isinstance(data["spend_by_category"], dict)
    assert data["rating"] in ("EXCEEDS", "MEETS", "NEAR", "BELOW", "NO_GOAL")
    assert data["status"] in ("GENERATED", "PUBLISHED")
    if data.get("attainment_pct") is not None:
        assert isinstance(data["attainment_pct"], (int, float))


def assert_sourcing_event(data: dict):
    _assert_common(data)
    assert isinstance(data["business_unit_id"], str) and data["business_unit_id"]
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["estimated_value_cents"], int)
    assert data["estimated_value_cents"] > 0
    assert isinstance(data["required_diverse_bidders"], int)
    assert 0 <= data["required_diverse_bidders"] <= 10
    assert isinstance(data["diverse_bid_count"], int)
    assert data["diverse_bid_count"] >= 0
    assert data["status"] in ("DRAFT", "OPEN", "AWARDED", "CANCELLED")


def assert_bidder_invitation(data: dict):
    _assert_common(data)
    assert isinstance(data["sourcing_event_id"], str)
    assert isinstance(data["supplier_id"], str) and data["supplier_id"]
    assert data["status"] in (
        "INVITED", "BID_SUBMITTED", "DECLINED", "NO_RESPONSE", "WON", "LOST",
        "WITHDRAWN")


def assert_development_engagement(data: dict):
    _assert_common(data)
    assert isinstance(data["supplier_id"], str) and data["supplier_id"]
    assert data["track"] in (
        "MENTORING", "CAPABILITY_BUILDING", "ACCESS_TO_CAPITAL")
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert isinstance(data["capacity_score_before"], int)
    assert 0 <= data["capacity_score_before"] <= 100
    assert data["status"] in ("ENROLLED", "ACTIVE", "COMPLETED", "WITHDRAWN")


def assert_audit_case(data: dict):
    _assert_common(data)
    assert isinstance(data["supplier_id"], str) and data["supplier_id"]
    assert isinstance(data["certification_id"], str) and data["certification_id"]
    assert isinstance(data["auditor_user_id"], str) and data["auditor_user_id"]
    assert data["status"] in ("OPEN", "CONFIRMED", "FAILED")
    if data.get("outcome") is not None:
        assert data["outcome"] in ("CONFIRMED", "FAILED")


def assert_net_posted_invariant(business_unit: dict, posted_sum: int):
    """PRD ledger conservation: the sum of amount_cents over records currently
    POSTED always equals lifetime_imported_spend_cents minus
    lifetime_voided_spend_cents."""
    net = (business_unit["lifetime_imported_spend_cents"]
           - business_unit["lifetime_voided_spend_cents"])
    assert net == posted_sum, (
        f"Net posted spend invariant violated: imported "
        f"{business_unit['lifetime_imported_spend_cents']} - voided "
        f"{business_unit['lifetime_voided_spend_cents']} = {net}, "
        f"but POSTED records sum to {posted_sum}")
