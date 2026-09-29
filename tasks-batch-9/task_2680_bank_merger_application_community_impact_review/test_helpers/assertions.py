"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

INSTITUTION_STATUSES = ["ACTIVE", "MERGED_OUT"]
BRANCH_STATUSES = ["OPEN", "DESIGNATED_FOR_DIVESTITURE", "DESIGNATED_FOR_CLOSURE",
                   "DIVESTED", "CLOSED"]
FILING_STATUSES = ["DRAFT", "SUBMITTED", "UNDER_REVIEW", "RETURNED_FOR_AMENDMENT",
                   "RECOMMENDED", "DECIDED", "CONSUMMATED", "DENIED"]
PUBLIC_REVIEW_STATUSES = ["NOT_OPEN", "OPEN_FOR_COMMENT", "PROTEST_PENDING",
                          "HEARING_PENDING", "HEARING_GRANTED", "COMMENT_CLOSED", "CLEARED"]
COMPETITIVE_POSTURES = ["NOT_ANALYZED", "CLEARED", "CLEARED_WITH_DIVESTITURE",
                        "MITIGATION_REQUIRED", "BLOCKED"]
SCREEN_RESULTS = ["PASS", "MITIGATION_REQUIRED", "PRESUMPTIVE_VIOLATION"]
CAPITAL_FLAGS = ["WELL_CAPITALIZED", "ADEQUATELY_CAPITALIZED", "UNDERCAPITALIZED"]


def assert_common_fields(data: dict, entity_label: str = "record"):
    """Every persisted record carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity_label}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity_label}.updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), \
        f"{entity_label}.version must be an integer, got {data.get('version')!r}"
    assert data["version"] >= 1, f"{entity_label}.version starts at 1, got {data['version']}"


def assert_institution(data: dict):
    assert_common_fields(data, "Institution")
    assert isinstance(data["legal_name"], str) and 1 <= len(data["legal_name"]) <= 160
    assert data["charter_type"] in ["NATIONAL", "STATE_MEMBER", "STATE_NONMEMBER", "SAVINGS"]
    assert data["primary_regulator"] in ["OCC", "FRB", "FDIC"]
    assert data["latest_cra_rating"] in ["OUTSTANDING", "SATISFACTORY", "NEEDS_TO_IMPROVE",
                                         "SUBSTANTIAL_NONCOMPLIANCE"]
    assert data["status"] in INSTITUTION_STATUSES
    for field in ("cet1_capital_usd", "tier1_capital_usd", "total_capital_usd",
                  "risk_weighted_assets_usd", "average_total_assets_usd", "total_loans_usd",
                  "total_deposits_usd", "branch_count"):
        assert isinstance(data[field], int), f"Institution.{field} must be an integer"
        assert data[field] >= 0, f"Institution.{field} must be >= 0"


def assert_deposit_market(data: dict):
    assert_common_fields(data, "DepositMarket")
    assert 2 <= len(data["market_code"]) <= 32
    assert isinstance(data["market_name"], str)
    assert data["market_type"] in ["MSA", "RURAL_COUNTY"]
    for field in ("total_deposits_usd", "participant_count", "hhi_current"):
        assert isinstance(data[field], int), f"DepositMarket.{field} must be an integer"
        assert data[field] >= 0


def assert_branch(data: dict):
    assert_common_fields(data, "Branch")
    assert is_valid_uuid(data["institution_id"])
    assert is_valid_uuid(data["market_id"])
    assert isinstance(data["branch_name"], str) and data["branch_name"]
    assert isinstance(data["deposits_usd"], int) and data["deposits_usd"] > 0
    assert data["service_type"] in ["FULL_SERVICE", "LIMITED_SERVICE"]
    assert data["status"] in BRANCH_STATUSES


def assert_merger_application(data: dict):
    assert_common_fields(data, "MergerApplication")
    assert is_valid_uuid(data["acquirer_id"])
    assert is_valid_uuid(data["target_id"])
    assert data["acquirer_id"] != data["target_id"], "acquirer and target must differ"
    assert data["structure"] in ["STATUTORY_MERGER", "PURCHASE_AND_ASSUMPTION", "HOLDCO_ACQUISITION"]
    assert data["consideration_type"] in ["ALL_CASH", "ALL_STOCK", "MIXED"]
    assert isinstance(data["total_consideration_usd"], int) and data["total_consideration_usd"] > 0
    for field in ("officer_experience_score", "risk_management_score",
                  "compliance_history_score", "integration_readiness_score"):
        assert 0 <= data[field] <= 100, f"MergerApplication.{field} must be 0..100"
    assert data["management_rating"] in ["SATISFACTORY", "CONDITIONAL", "UNSATISFACTORY"]
    assert data["filing_status"] in FILING_STATUSES
    assert data["public_review_status"] in PUBLIC_REVIEW_STATUSES
    assert data["competitive_posture"] in COMPETITIVE_POSTURES
    assert data["post_closing_monitoring_status"] in ["NOT_APPLICABLE", "MONITORING", "ESCALATED"]
    assert data["substantive_protest_count"] >= 0
    assert data["unresolved_protest_count"] >= 0
    assert data["unresolved_protest_count"] <= data["substantive_protest_count"], \
        "unresolved protests are a subset of substantive protests"
    assert data["amendment_round"] >= 0


def assert_pro_forma_schedule(data: dict):
    assert_common_fields(data, "ProFormaCapitalSchedule")
    assert is_valid_uuid(data["application_id"])
    assert data["basis"] in ["REGULATORY_ADJUSTED", "INTERNAL_STRESS"]
    assert data["capital_adequacy_flag"] in CAPITAL_FLAGS
    assert data["status"] in ["CURRENT", "SUPERSEDED"]
    for field in ("pro_forma_cet1_ratio_pct", "pro_forma_tier1_leverage_pct"):
        assert isinstance(data[field], (int, float)), f"{field} must be numeric"


def assert_competitive_analysis(data: dict):
    assert_common_fields(data, "CompetitiveAnalysis")
    assert is_valid_uuid(data["application_id"])
    assert is_valid_uuid(data["market_id"])
    assert data["screen_result"] in SCREEN_RESULTS
    for field in ("combined_market_deposits_usd", "hhi_pre_merger", "hhi_post_unmitigated",
                  "hhi_delta_unmitigated", "required_divestiture_deposits_usd",
                  "designated_divestiture_deposits_usd", "hhi_post_mitigated"):
        assert isinstance(data[field], int), f"CompetitiveAnalysis.{field} must be an integer"
    assert isinstance(data["mitigation_satisfied"], bool)
    assert data["hhi_delta_unmitigated"] == data["hhi_post_unmitigated"] - data["hhi_pre_merger"], \
        "hhi_delta_unmitigated is the difference of the two index values"


def assert_comment_period(data: dict):
    assert_common_fields(data, "PublicCommentPeriod")
    assert is_valid_uuid(data["application_id"])
    assert is_iso8601_timestamp(data["opens_at"])
    assert is_iso8601_timestamp(data["closes_at"])
    assert 1 <= data["duration_days"] <= 90
    assert data["status"] in ["OPEN", "EXTENDED", "CLOSED"]
    assert data["extension_count"] >= 0
    assert data["extended_days_total"] >= 0
    assert data["comment_count"] >= 0
    assert data["substantive_protest_count"] >= 0


def assert_public_comment(data: dict):
    assert_common_fields(data, "PublicComment")
    assert is_valid_uuid(data["period_id"])
    assert isinstance(data["commenter_user_id"], str) and data["commenter_user_id"]
    assert isinstance(data["commenter_name"], str) and data["commenter_name"]
    assert data["commenter_type"] in ["INDIVIDUAL", "COMMUNITY_ORGANIZATION", "TRADE_GROUP", "GOVERNMENT"]
    assert data["stance"] in ["SUPPORT", "OPPOSE", "PROTEST"]
    assert isinstance(data["substantive"], bool)
    assert 1 <= len(data["body"]) <= 4000
    assert is_iso8601_timestamp(data["received_at"])
    assert data["status"] in ["RECEIVED", "ACKNOWLEDGED", "RESPONDED", "UNTIMELY"]


def assert_hearing_request(data: dict):
    assert_common_fields(data, "HearingRequest")
    assert is_valid_uuid(data["application_id"])
    assert is_valid_uuid(data["comment_id"])
    assert isinstance(data["requester_user_id"], str) and data["requester_user_id"]
    assert is_iso8601_timestamp(data["requested_at"])
    assert 1 <= len(data["basis"]) <= 2000
    assert data["status"] in ["PENDING", "GRANTED", "DENIED", "WITHDRAWN"]
    assert data["extension_days_granted"] >= 0


def assert_benefits_plan(data: dict):
    assert_common_fields(data, "CommunityBenefitsPlan")
    assert is_valid_uuid(data["application_id"])
    assert 1 <= data["term_years"] <= 10
    assert data["measurement_basis"] in ["CUMULATIVE_TO_DATE", "ANNUAL_PRO_RATA"]
    assert data["compliance_status"] in ["COMPLIANT", "WATCH", "DEFICIENT"]
    assert data["status"] in ["PROPOSED", "EXECUTED", "SUPERSEDED"]
    for field in ("total_committed_usd", "annual_target_total_usd", "quarterly_target_total_usd",
                  "credited_to_date_usd", "remaining_commitment_usd",
                  "consecutive_deficient_periods", "filed_report_count"):
        assert isinstance(data[field], int), f"CommunityBenefitsPlan.{field} must be an integer"
        assert data[field] >= 0


def assert_benefits_plan_ledger_identity(plan: dict):
    """credited_to_date_usd plus remaining_commitment_usd always equals total_committed_usd."""
    assert plan["credited_to_date_usd"] + plan["remaining_commitment_usd"] == plan["total_committed_usd"], (
        f"ledger identity broken: {plan['credited_to_date_usd']} + "
        f"{plan['remaining_commitment_usd']} != {plan['total_committed_usd']}"
    )


def assert_line_item(data: dict):
    assert_common_fields(data, "CommitmentLineItem")
    assert is_valid_uuid(data["plan_id"])
    assert data["category"] in ["MORTGAGE_LENDING", "SMALL_BUSINESS_LENDING", "PHILANTHROPY",
                                "BRANCH_RETENTION", "CDFI_INVESTMENT"]
    assert isinstance(data["committed_usd"], int) and data["committed_usd"] > 0
    for field in ("annual_target_usd", "final_year_target_usd", "credited_usd"):
        assert isinstance(data[field], int), f"CommitmentLineItem.{field} must be an integer"
    assert data["credited_usd"] <= data["committed_usd"], \
        "credited_usd can never exceed the item's committed_usd"


def assert_approval_decision(data: dict):
    assert_common_fields(data, "ApprovalDecision")
    assert is_valid_uuid(data["application_id"])
    assert data["decision"] in ["APPROVED", "CONDITIONALLY_APPROVED", "DENIED"]
    assert isinstance(data["decided_by_user_id"], str) and data["decided_by_user_id"]
    assert is_iso8601_timestamp(data["decided_at"])
    assert isinstance(data["expedited_processing"], bool)
    assert isinstance(data["waiting_period_days"], int) and data["waiting_period_days"] >= 0
    assert data["status"] in ["ISSUED", "CONSUMMATED", "LAPSED", "CLOSED"]


def assert_approval_condition(data: dict):
    assert_common_fields(data, "ApprovalCondition")
    assert is_valid_uuid(data["decision_id"])
    assert data["condition_type"] in ["DIVESTITURE", "COMMUNITY_BENEFITS", "CAPITAL_MAINTENANCE",
                                       "BRANCH_RETENTION", "SYSTEMS_CONVERSION"]
    assert data["timing"] in ["PRE_CONSUMMATION", "POST_CLOSING"]
    assert 1 <= len(data["description"]) <= 2000
    assert data["status"] in ["OPEN", "SATISFIED", "BREACHED"]


def assert_conversion_plan(data: dict):
    assert_common_fields(data, "SystemsConversionPlan")
    assert is_valid_uuid(data["application_id"])
    assert isinstance(data["affected_customer_count"], int) and data["affected_customer_count"] > 0
    assert data["status"] in ["DRAFT", "DISCLOSED", "CONVERTED"]


def assert_performance_report(data: dict):
    assert_common_fields(data, "CommitmentPerformanceReport")
    assert is_valid_uuid(data["plan_id"])
    assert 4 <= len(data["period_label"]) <= 16
    assert isinstance(data["period_index"], int) and data["period_index"] >= 1
    assert isinstance(data["achieved_by_category"], dict) and data["achieved_by_category"]
    assert isinstance(data["credited_usd"], int) and data["credited_usd"] >= 0
    assert isinstance(data["excess_uncredited_usd"], int) and data["excess_uncredited_usd"] >= 0
    assert data["measurement_basis"] in ["CUMULATIVE_TO_DATE", "ANNUAL_PRO_RATA"]
    assert is_iso8601_timestamp(data["filed_at"])
    assert data["status"] in ["FILED", "ACCEPTED", "DEFICIENT"]


def assert_no_pagination_meta(meta: dict):
    """Single-resource responses omit all four pagination fields."""
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field not in meta, f"single-resource meta must omit {field}"


def normalize_instant(value: str) -> str:
    """Reduce an ISO 8601 UTC instant to a canonical form for equality comparison."""
    assert isinstance(value, str), f"expected an ISO 8601 timestamp string, got {value!r}"
    text = value.strip()
    assert text.endswith("Z"), f"expected a UTC instant ending in Z, got {value!r}"
    body = text[:-1]
    if "." in body:
        body, fraction = body.split(".", 1)
        fraction = fraction.rstrip("0")
        if fraction:
            return f"{body}.{fraction}Z"
    return f"{body}Z"


def assert_same_instant(actual, expected, label: str = "instant"):
    """Assert two UTC instants are the same moment, ignoring fractional-digit rendering."""
    assert actual is not None, f"{label} is null but should be {expected}"
    assert normalize_instant(actual) == normalize_instant(expected), (
        f"{label} should be {expected}, got {actual}"
    )
