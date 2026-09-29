"""Entity assertions and domain invariant checkers."""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

FISCAL_PERIOD_STATUSES = ["OPEN", "REVIEW_LOCKED", "CLOSED"]
POSTURES = ["HEALTHY", "WATCH", "CONSTRAINED", "CRITICAL"]
TIER_STATUSES = ["DRAFT", "PUBLISHED"]
MEMBER_STATUSES = ["PENDING", "ACTIVE", "GRACE", "LAPSED", "CANCELLED"]
FUNDER_STATUSES = ["PROSPECT", "CLEARED", "RESTRICTED"]
DISCLOSURE_STATUSES = ["ACTIVE", "REATTESTATION_REQUIRED", "SUPERSEDED", "VOID"]
GIFT_OFFER_STATUSES = [
    "PROPOSED",
    "INDEPENDENCE_REVIEW",
    "CONDITIONS_REQUESTED",
    "CLEARED",
    "DECLINED",
    "ACCEPTED",
]
PROPOSAL_STATUSES = [
    "DRAFT",
    "INDEPENDENCE_REVIEW",
    "REVISION_REQUESTED",
    "CLEARED",
    "SUBMITTED",
    "AWARDED",
    "SUSPENDED",
    "DECLINED",
    "WITHDRAWN",
    "CLOSED",
]
REPORT_STATUSES = ["SCHEDULED", "SUBMITTED", "ACCEPTED", "RETURNED", "OVERDUE", "WAIVED"]
SETTLEMENT_STATUSES = ["INITIATED", "SETTLED", "FAILED", "REFUNDED"]
ACKNOWLEDGMENT_STATUSES = ["UNACKNOWLEDGED", "RECEIPTED", "DISCLOSED"]
COLLABORATION_STATUSES = ["DRAFT", "ACTIVE", "SETTLED", "DISSOLVED"]
PARTNER_STATUSES = ["CONFIRMED", "WITHDRAWN"]
REVENUE_STREAMS = ["MEMBERSHIP", "MAJOR_GIFT", "GRANTS", "EVENTS", "SYNDICATION"]


def _assert_identity(data: Dict[str, Any], entity: str) -> None:
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity}.created_at must be an ISO 8601 timestamp"


def _assert_common_fields(data: Dict[str, Any], entity: str) -> None:
    """Every resource but an influence contact carries updated_at and version."""
    _assert_identity(data, entity)
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{entity}.updated_at must be an ISO 8601 timestamp"
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"
    assert data["version"] >= 1, f"{entity}.version starts at 1"


def assert_fiscal_period(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "FiscalPeriod")
    assert isinstance(data["label"], str) and 1 <= len(data["label"]) <= 32
    assert data["status"] in FISCAL_PERIOD_STATUSES
    assert isinstance(data["monthly_expense_base_cents"], int)
    assert data["monthly_expense_base_cents"] >= 1
    assert isinstance(data["reserve_balance_cents"], int)
    assert data["reserve_balance_cents"] >= 0
    assert isinstance(data["recognized_revenue_cents"], int)
    assert isinstance(data["stream_shares_bps"], dict)
    for stream in REVENUE_STREAMS:
        assert stream in data["stream_shares_bps"], (
            f"stream_shares_bps must be keyed by the five revenue streams, "
            f"missing {stream}"
        )
    assert isinstance(data["concentration_hhi"], int)
    assert 0 <= data["concentration_hhi"] <= 10000
    assert isinstance(data["top_source_share_bps"], int)
    assert data["reserve_months_target"] in (3, 4, 5)
    assert isinstance(data["operating_reserve_target_cents"], int)
    assert isinstance(data["reserve_months_ratio_bps"], int)
    assert data["sustainability_posture"] in POSTURES
    assert data["restricted_release_cap_pct_bps"] in (0, 2500, 6000, 10000)
    assert isinstance(data["board_override_active"], bool)


def assert_membership_tier(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "MembershipTier")
    assert isinstance(data["tier_code"], str) and 2 <= len(data["tier_code"]) <= 32
    assert data["renewal_cadence"] in ("MONTHLY", "ANNUAL")
    assert isinstance(data["contribution_amount_cents"], int)
    assert data["contribution_amount_cents"] >= 100
    assert isinstance(data["grace_period_days"], int)
    assert 0 <= data["grace_period_days"] <= 120
    assert isinstance(data["benefits"], list) and len(data["benefits"]) <= 8
    assert data["benefit_count"] == len(data["benefits"])
    assert isinstance(data["insubstantial_benefit_codes"], list)
    assert isinstance(data["quid_pro_quo_per_period_cents"], int)
    assert isinstance(data["insubstantial_threshold_cents"], int)
    assert data["status"] in TIER_STATUSES


def assert_member(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Member")
    assert is_valid_uuid(data["tier_id"])
    assert "@" in data["email"]
    assert isinstance(data["full_name"], str)
    assert data["status"] in MEMBER_STATUSES
    assert isinstance(data["lifetime_giving_cents"], int)
    assert isinstance(data["consecutive_renewals"], int)
    assert isinstance(data["is_major_donor"], bool)
    assert isinstance(data["cultivation_locked"], bool)


def assert_coverage_area(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "CoverageArea")
    assert isinstance(data["area_code"], str) and 2 <= len(data["area_code"]) <= 32
    assert data["disclosure_status"] in ("CURRENT", "STALE")
    assert data["publication_gate"] in ("OPEN", "BLOCKED")
    assert isinstance(data["restricted_grant_count"], int)
    assert isinstance(data["disclosed_funder_count"], int)


def assert_funder(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Funder")
    assert isinstance(data["legal_name"], str)
    assert data["funder_type"] in ("FOUNDATION", "INDIVIDUAL", "CORPORATE", "GOVERNMENT")
    assert isinstance(data["self_attested_advocacy"], bool)
    assert data["risk_basis"] in ("SELF_ATTESTED", "AUDITED")
    assert isinstance(data["prior_editorial_requests_count"], int)
    assert isinstance(data["reporting_reliability_bps"], int)
    assert 0 <= data["reporting_reliability_bps"] <= 10000
    assert isinstance(data["independence_risk_score"], int)
    assert 0 <= data["independence_risk_score"] <= 100
    assert data["status"] in FUNDER_STATUSES
    assert isinstance(data["cultivated_by_user_id"], str)
    assert isinstance(data["lifetime_committed_cents"], int)


def assert_firewall_disclosure(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "FirewallDisclosure")
    assert is_valid_uuid(data["funder_id"])
    assert is_valid_uuid(data["coverage_area_id"])
    assert 20 <= len(data["disclosure_text"]) <= 2000
    assert data["status"] in DISCLOSURE_STATUSES
    assert isinstance(data["attested_by_user_id"], str)
    assert is_iso8601_timestamp(data["attested_at"])
    if data["reattestation_reason"] is not None:
        assert data["reattestation_reason"] in ("FUNDER_RESTRICTED", "INFLUENCE_CONTACT")


def assert_influence_contact(data: Dict[str, Any]) -> None:
    """An influence contact carries only id and created_at, never updated_at
    or version."""
    _assert_identity(data, "InfluenceContact")
    assert "updated_at" not in data, "an influence contact carries no updated_at"
    assert "version" not in data, "an influence contact carries no version"
    assert is_valid_uuid(data["funder_id"])
    assert data["contact_type"] in (
        "ROUTINE_STEWARDSHIP",
        "COVERAGE_INQUIRY",
        "CONDITION_ATTEMPT",
        "EDITORIAL_DIRECTION_REQUEST",
    )
    assert 10 <= len(data["summary"]) <= 1000
    assert isinstance(data["logged_by_user_id"], str)
    assert data["severity_weight"] in (0, 1, 2, 3)
    assert isinstance(data["triggered_restriction"], bool)


def assert_gift_offer(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "GiftOffer")
    assert is_valid_uuid(data["funder_id"])
    assert is_valid_uuid(data["fiscal_period_id"])
    assert isinstance(data["offered_amount_cents"], int)
    assert data["offered_amount_cents"] >= 100000
    assert data["designation"] in (
        "UNRESTRICTED",
        "PROGRAM_RESTRICTED",
        "PROJECT_RESTRICTED",
    )
    assert data["status"] in GIFT_OFFER_STATUSES
    assert isinstance(data["stewardship_fee_cents"], int)
    assert isinstance(data["net_acceptable_amount_cents"], int)
    assert isinstance(data["board_ratification_required"], bool)
    assert isinstance(data["acceptance_gate_score"], int)
    assert isinstance(data["solicited_by_user_id"], str)
    assert isinstance(data["conditions_round_count"], int)


def assert_grant_proposal(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "GrantProposal")
    assert is_valid_uuid(data["funder_id"])
    assert is_valid_uuid(data["fiscal_period_id"])
    assert isinstance(data["requested_amount_cents"], int)
    assert data["requested_amount_cents"] >= 100000
    assert data["restriction_type"] in (
        "UNRESTRICTED",
        "PROGRAM_RESTRICTED",
        "PROJECT_RESTRICTED",
    )
    assert data["reporting_cadence"] in ("NONE", "SEMIANNUAL", "ANNUAL")
    assert isinstance(data["award_probability_bps"], int)
    assert 0 <= data["award_probability_bps"] <= 10000
    assert data["status"] in PROPOSAL_STATUSES
    assert isinstance(data["revision_round_count"], int)
    assert data["compliance_flag"] in ("COMPLIANT", "DELINQUENT")
    assert isinstance(data["report_count"], int)
    assert isinstance(data["drafted_by_user_id"], str)
    if data["suspended_reason"] is not None:
        assert data["suspended_reason"] in ("FIREWALL_BREACH", "REPORT_DELINQUENCY")
    assert_grant_ledger_invariant(data)


def assert_grant_ledger_invariant(data: Dict[str, Any]) -> None:
    """awarded_amount_cents always equals released plus unreleased plus returned."""
    for field in (
        "awarded_amount_cents",
        "released_cents",
        "unreleased_cents",
        "returned_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer count of cents"
        assert data[field] >= 0, f"{field} must not be negative"
    total = data["released_cents"] + data["unreleased_cents"] + data["returned_cents"]
    assert data["awarded_amount_cents"] == total, (
        "awarded_amount_cents must equal released_cents plus unreleased_cents plus "
        f"returned_cents, got {data['awarded_amount_cents']} != {total}"
    )


def assert_grant_report(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "GrantReport")
    assert is_valid_uuid(data["grant_proposal_id"])
    assert isinstance(data["sequence_no"], int) and data["sequence_no"] >= 1
    assert isinstance(data["period_start"], str)
    assert isinstance(data["period_end"], str)
    assert isinstance(data["due_date"], str)
    assert data["status"] in REPORT_STATUSES
    assert isinstance(data["allocated_release_cents"], int)
    assert isinstance(data["consumed_release_cents"], int)


def assert_contribution(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Contribution")
    assert is_valid_uuid(data["fiscal_period_id"])
    assert data["revenue_stream"] in REVENUE_STREAMS
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert isinstance(data["received_date"], str)
    assert data["settlement_status"] in SETTLEMENT_STATUSES
    assert data["acknowledgment_status"] in ACKNOWLEDGMENT_STATUSES
    assert isinstance(data["quid_pro_quo_cents"], int)
    assert isinstance(data["deductible_cents"], int)
    assert data["quid_pro_quo_cents"] >= 0 and data["deductible_cents"] >= 0


def assert_collaboration(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Collaboration")
    assert is_valid_uuid(data["coverage_area_id"])
    assert is_valid_uuid(data["fiscal_period_id"])
    assert isinstance(data["total_cost_cents"], int) and data["total_cost_cents"] >= 1
    assert 0 <= data["lead_credit_bps"] <= 10000
    assert 0 <= data["lead_cost_share_bps"] <= 10000
    assert data["status"] in COLLABORATION_STATUSES
    assert isinstance(data["partner_count"], int)
    assert isinstance(data["lead_cost_cents"], int)
    assert isinstance(data["allocated_cost_cents"], int)
    assert isinstance(data["syndication_revenue_cents"], int)


def assert_collaboration_partner(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "CollaborationPartner")
    assert is_valid_uuid(data["collaboration_id"])
    assert isinstance(data["partner_org_name"], str)
    assert 1 <= data["credit_share_bps"] <= 10000
    assert 1 <= data["cost_share_bps"] <= 10000
    assert isinstance(data["cost_owed_cents"], int)
    assert isinstance(data["remainder_rank"], int)
    assert data["status"] in PARTNER_STATUSES


def assert_cost_conservation(
    collaboration: Dict[str, Any], partners: List[Dict[str, Any]]
) -> None:
    """allocated_cost_cents is lead_cost_cents plus the cost_owed_cents of every
    CONFIRMED partner, and equals total_cost_cents exactly."""
    confirmed = [p for p in partners if p["status"] == "CONFIRMED"]
    summed = collaboration["lead_cost_cents"] + sum(
        p["cost_owed_cents"] for p in confirmed
    )
    assert collaboration["allocated_cost_cents"] == summed, (
        "allocated_cost_cents must equal lead_cost_cents plus every CONFIRMED "
        f"partner's cost_owed_cents, got {collaboration['allocated_cost_cents']} "
        f"!= {summed}"
    )
    assert collaboration["allocated_cost_cents"] == collaboration["total_cost_cents"], (
        "allocated_cost_cents must equal total_cost_cents exactly, got "
        f"{collaboration['allocated_cost_cents']} != {collaboration['total_cost_cents']}"
    )


def assert_sustainability(data: Dict[str, Any]) -> None:
    """The sustainability read's documented response shape."""
    assert data["basis"] in ("RECOGNIZED", "PIPELINE")
    for field in (
        "recognized_revenue_cents",
        "membership_share_bps",
        "major_gift_share_bps",
        "grants_share_bps",
        "events_share_bps",
        "syndication_share_bps",
        "concentration_hhi",
        "top_source_share_bps",
        "reserve_months_target",
        "operating_reserve_target_cents",
        "reserve_months_ratio_bps",
        "restricted_release_cap_pct_bps",
    ):
        assert isinstance(data[field], int), f"sustainability.{field} must be an integer"
    assert data["sustainability_posture"] in POSTURES
    assert data["reserve_months_target"] in (3, 4, 5)


def assert_sweep_report(data: Dict[str, Any]) -> None:
    """The sweep reports what it did as swept_at plus five counters."""
    assert isinstance(data["swept_at"], str)
    for counter in (
        "members_moved_to_grace",
        "members_moved_to_lapsed",
        "reports_moved_to_overdue",
        "proposals_suspended",
        "funders_restricted",
    ):
        assert isinstance(data[counter], int), f"sweep.{counter} must be an integer"
        assert data[counter] >= 0


def assert_transparency_report(data: Dict[str, Any]) -> None:
    assert isinstance(data["area_code"], str)
    assert data["publication_gate"] in ("OPEN", "BLOCKED")
    assert data["disclosure_status"] in ("CURRENT", "STALE")
    assert isinstance(data["disclosed_funder_count"], int)
    assert isinstance(data["restricted_grant_count"], int)
    assert isinstance(data["disclosed_funder_ids"], list)
    assert isinstance(data["total_committed_cents"], int)
