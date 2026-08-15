"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

DEAL_STATUSES = ["SOURCING", "PSA_PENDING", "PSA_EXECUTED", "DUE_DILIGENCE",
                 "CLEAR_TO_CLOSE", "CLOSED", "TERMINATED"]
DEAL_POSTURES = ["SOURCING", "UNDER_REVIEW", "DD_OPEN", "DD_BLOCKED",
                 "CLEAR_TO_CLOSE", "CLOSED", "TERMINATED"]
TENANT_CREDIT_STATUSES = ["PENDING", "ANALYZED", "APPROVED", "REJECTED"]
PROPERTY_STATUSES = ["IDENTIFIED", "SURVEYED", "CLEAR", "FLAGGED"]
LEASE_STATUSES = ["DRAFT", "VERIFIED", "ESTOPPEL_PENDING", "ESTOPPELED",
                  "EXPIRED"]
MODEL_STATUSES = ["DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "SUPERSEDED"]
PSA_STATUSES = ["DRAFT", "EXECUTED", "AMENDED", "TERMINATED", "CLOSED"]
MILESTONE_STATUSES = ["PENDING", "IN_PROGRESS", "SATISFIED", "WAIVED",
                      "OVERDUE"]
MILESTONE_TYPES = ["TITLE_REVIEW", "SURVEY_REVIEW", "ENVIRONMENTAL", "PCA",
                   "ESTOPPEL_COLLECTION", "SNDA_COLLECTION",
                   "FINANCING_COMMITMENT", "FINAL_WALKTHROUGH"]
TITLE_REVIEW_STATUSES = ["RECEIVED", "UNDER_REVIEW", "EXCEPTIONS_RAISED",
                         "CLEARED", "REJECTED"]
EXCEPTION_STATUSES = ["OPEN", "CURE_PROPOSED", "CURED", "WAIVED", "SUPERSEDED"]
EA_STATUSES = ["ORDERED", "RECEIVED", "CLEARED", "CONDITIONAL", "FAILED"]
PCA_STATUSES = ["ORDERED", "RECEIVED", "ACCEPTED", "REJECTED"]
ESTOPPEL_STATUSES = ["REQUESTED", "RECEIVED", "CERTIFIED", "DEFICIENT",
                     "EXPIRED"]
SNDA_STATUSES = ["REQUESTED", "RECEIVED", "CERTIFIED", "REJECTED"]
FINANCING_STATUSES = ["DRAFT", "SUBMITTED", "COMMITTED", "DECLINED",
                      "WITHDRAWN", "LAPSED"]
STATEMENT_STATUSES = ["DRAFT", "ISSUED", "ACKNOWLEDGED", "TRUED_UP",
                      "SUPERSEDED"]
PRORATION_LINE_TYPES = ["BASE_RENT", "CAM", "TAX", "INSURANCE", "UTILITY"]
PRORATION_DIRECTIONS = ["BUYER_CREDIT", "SELLER_CREDIT"]
TRUE_UP_STATUSES = ["PROPOSED", "ESCROW_APPROVED", "FULLY_APPROVED",
                    "REJECTED", "APPLIED"]


def _assert_common_versioned(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_ts_prefix(value: str, expected_prefix: str):
    """Assert an ISO 8601 timestamp starts with the expected instant prefix
    (tolerates an optional three-fractional-digit suffix)."""
    assert isinstance(value, str), f"Expected timestamp string, got {value!r}"
    assert value.startswith(expected_prefix), (
        f"Expected timestamp starting with {expected_prefix!r}, got {value!r}"
    )


def assert_deal(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["deal_name"], str) and data["deal_name"]
    assert data["deal_type"] in ["SINGLE_TENANT", "MULTI_TENANT",
                                 "SALE_LEASEBACK", "PORTFOLIO"]
    assert data["sourcing_channel"] in ["BROKER", "OFF_MARKET", "AUCTION",
                                        "DIRECT"]
    assert isinstance(data["purchase_price_cents"], int)
    assert isinstance(data["earnest_money_cents"], int)
    assert data["status"] in DEAL_STATUSES
    assert data["posture"] in DEAL_POSTURES
    assert isinstance(data["earnest_money_released"], bool)


def assert_tenant(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["credit_rating"] in ["INVESTMENT_GRADE",
                                     "NON_INVESTMENT_GRADE", "UNRATED"]
    assert isinstance(data["credit_score"], int)
    assert isinstance(data["annual_revenue_cents"], int)
    assert isinstance(data["is_guaranteed"], bool)
    assert data["credit_assessment_status"] in TENANT_CREDIT_STATUSES


def assert_property(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["address"], str) and data["address"]
    assert data["property_type"] in ["RETAIL", "INDUSTRIAL", "OFFICE",
                                     "MEDICAL", "QSR"]
    assert isinstance(data["rentable_sqft"], int)
    assert isinstance(data["year_built"], int)
    assert data["status"] in PROPERTY_STATUSES


def assert_lease(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["property_id"], str)
    assert isinstance(data["tenant_id"], str)
    assert data["lease_type"] in ["NNN", "NN", "GROSS", "ABSOLUTE_NET"]
    assert isinstance(data["annual_base_rent_cents"], int)
    assert data["status"] in LEASE_STATUSES


def assert_underwriting_model(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["deal_id"], str)
    assert isinstance(data["model_version"], int)
    assert data["opex_allowance_variant"] in ["CONSERVATIVE", "MARKET"]
    assert data["status"] in MODEL_STATUSES


def assert_purchase_agreement(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["deal_id"], str)
    assert isinstance(data["psa_price_cents"], int)
    assert isinstance(data["earnest_money_cents"], int)
    assert isinstance(data["dd_period_days"], int)
    assert isinstance(data["financing_contingency_days"], int)
    assert isinstance(data["amendment_count"], int)
    assert data["status"] in PSA_STATUSES


def assert_milestone(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["deal_id"], str)
    assert data["milestone_type"] in MILESTONE_TYPES
    assert isinstance(data["waived"], bool)
    assert data["status"] in MILESTONE_STATUSES


def assert_title_review(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["deal_id"], str)
    assert isinstance(data["title_company"], str)
    assert data["survey_type"] in ["ALTA", "BOUNDARY", "TOPOGRAPHIC"]
    assert isinstance(data["exception_count"], int)
    assert data["status"] in TITLE_REVIEW_STATUSES


def assert_title_exception(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["title_review_id"], str)
    assert isinstance(data["exception_code"], str)
    assert data["severity"] in ["STANDARD", "MATERIAL", "FATAL"]
    assert isinstance(data["description"], str)
    assert isinstance(data["cure_cost_cents"], int)
    assert data["status"] in EXCEPTION_STATUSES


def assert_environmental_assessment(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["deal_id"], str)
    assert data["phase"] in ["PHASE_I", "PHASE_II"]
    assert isinstance(data["recognized_environmental_condition"], bool)
    assert isinstance(data["reliance_letter_received"], bool)
    assert data["status"] in EA_STATUSES


def assert_pca(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["deal_id"], str)
    assert isinstance(data["immediate_repair_cost_cents"], int)
    assert isinstance(data["capital_reserve_cents_per_sqft"], int)
    assert data["condition_rating"] in ["GOOD", "FAIR", "POOR", "CRITICAL"]
    assert data["status"] in PCA_STATUSES


def assert_estoppel(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["deal_id"], str)
    assert isinstance(data["lease_id"], str)
    assert isinstance(data["tenant_id"], str)
    assert isinstance(data["rent_confirmed_cents"], int)
    assert isinstance(data["default_confirmed"], bool)
    assert data["status"] in ESTOPPEL_STATUSES


def assert_snda(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["deal_id"], str)
    assert isinstance(data["lease_id"], str)
    assert isinstance(data["lender_name"], str)
    assert isinstance(data["non_disturbance_confirmed"], bool)
    assert data["status"] in SNDA_STATUSES


def assert_financing_application(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["deal_id"], str)
    assert data["loan_type"] in ["NEW_LOAN", "ASSUMPTION"]
    assert isinstance(data["loan_amount_cents"], int)
    assert isinstance(data["interest_rate_bps"], int)
    assert isinstance(data["amortization_months"], int)
    assert data["status"] in FINANCING_STATUSES


def assert_closing_statement(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["deal_id"], str)
    assert isinstance(data["statement_version"], int)
    assert isinstance(data["provisional"], bool)
    assert data["status"] in STATEMENT_STATUSES


def assert_proration(data: dict):
    """Proration lines are immutable: id + created_at only — no updated_at,
    no version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert "updated_at" not in data, "Proration must not carry updated_at"
    assert "version" not in data, "Proration must not carry version"
    assert isinstance(data["closing_statement_id"], str)
    assert data["line_type"] in PRORATION_LINE_TYPES
    assert isinstance(data["lease_id"], str)
    assert isinstance(data["annual_amount_cents"], int)
    assert isinstance(data["prorated_cents"], int)
    assert data["direction"] in PRORATION_DIRECTIONS


def assert_true_up_adjustment(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["closing_statement_id"], str)
    assert data["line_type"] in PRORATION_LINE_TYPES + ["REPAIR_CREDIT",
                                                        "OTHER"]
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["reason"], str) and data["reason"]
    assert isinstance(data["approved"], bool)
    assert data["status"] in TRUE_UP_STATUSES
