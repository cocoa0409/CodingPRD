"""Entity assertions and domain invariant checkers (PRD sections 2-3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    assert is_valid_uuid(str(data.get("id", ""))), "id must be a valid UUID"
    assert is_iso8601_timestamp(str(data.get("created_at", ""))), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(str(data.get("updated_at", ""))), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 0, \
        "version must be a non-negative integer"


def assert_association(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["charter_number"], str) and data["charter_number"]
    assert isinstance(data["review_index"], int) and data["review_index"] >= 0
    assert isinstance(data["active_disaster_declarations"], list)


def assert_borrower(data: dict):
    _assert_common(data)
    assert is_valid_uuid(str(data.get("association_id", "")))
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["tax_id"], str) and data["tax_id"]
    assert isinstance(data["county"], str) and data["county"]
    assert data["status"] in ("ACTIVE", "SUSPENDED", "TERMINATED")
    assert isinstance(data["patronage_eligible"], bool)
    assert isinstance(data["active_covenant_breach_count"], int)
    assert data["active_covenant_breach_count"] >= 0


def assert_loan(data: dict):
    _assert_common(data)
    assert is_valid_uuid(str(data.get("borrower_id", "")))
    assert isinstance(data["requested_commitment_cents"], int)
    assert data["requested_commitment_cents"] > 0
    assert data["approved_commitment_cents"] is None or \
        isinstance(data["approved_commitment_cents"], int)
    assert isinstance(data["rate_bps"], int)
    assert isinstance(data["season_year"], int)
    assert isinstance(data["maturity_date"], str)
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "ACTIVE",
                              "RESTRUCTURING", "PAID_OFF", "CHARGED_OFF",
                              "FORECLOSED")
    assert data["payment_posture"] in ("CURRENT", "WATCH", "DELINQUENT", "DEFAULT")
    assert isinstance(data["consecutive_delinquent_reviews"], int)
    assert isinstance(data["outstanding_principal_cents"], int)
    assert isinstance(data["accrued_interest_cents"], int)
    assert isinstance(data["borrowing_base_cents"], int)
    assert isinstance(data["pending_draw_cents"], int)


def assert_crop_budget(data: dict):
    _assert_common(data)
    assert is_valid_uuid(str(data.get("loan_account_id", "")))
    assert isinstance(data["season_year"], int)
    assert isinstance(data["crop_type"], str) and data["crop_type"]
    assert isinstance(data["acres"], int) and data["acres"] > 0
    assert isinstance(data["projected_revenue_cents"], int)
    assert isinstance(data["projected_expenses_cents"], int)
    assert data["status"] in ("DRAFT", "APPROVED", "SUPERSEDED", "ACTUALIZED")


def assert_collateral(data: dict):
    _assert_common(data)
    assert is_valid_uuid(str(data.get("loan_account_id", "")))
    assert data["collateral_type"] in ("CHATTEL_CROP", "EQUIPMENT", "REAL_ESTATE")
    assert isinstance(data["appraised_value_cents"], int)
    assert data["appraised_value_cents"] > 0
    assert isinstance(data["prior_lien_cents"], int)
    assert data["prior_lien_cents"] >= 0
    assert data["status"] in ("PLEDGED", "RELEASED")
    assert data["perfection_state"] in ("PERFECTED", "UNPERFECTED")


def assert_ucc_filing(data: dict):
    _assert_common(data)
    assert is_valid_uuid(str(data.get("collateral_id", "")))
    assert isinstance(data["filing_number"], str) and data["filing_number"]
    assert isinstance(data["jurisdiction"], str) and data["jurisdiction"]
    assert data["status"] in ("FILED", "CONTINUED", "LAPSED", "TERMINATED")
    assert isinstance(data["lapse_date"], str)


def assert_insurance_policy(data: dict):
    _assert_common(data)
    assert is_valid_uuid(str(data.get("borrower_id", "")))
    assert isinstance(data["policy_number"], str) and data["policy_number"]
    assert data["status"] in ("ACTIVE", "CANCELLED")
    assert data["assignment_status"] in ("UNASSIGNED", "ASSIGNED", "RELEASED")
    assert isinstance(data["coverage_amount_cents"], int)
    assert data["coverage_amount_cents"] > 0


def assert_insurance_claim(data: dict):
    _assert_common(data)
    assert is_valid_uuid(str(data.get("policy_id", "")))
    assert is_valid_uuid(str(data.get("loan_account_id", "")))
    assert isinstance(data["claimed_loss_cents"], int)
    assert data["claimed_loss_cents"] > 0
    assert data["status"] in ("REPORTED", "ADJUSTED", "APPROVED", "UNDER_APPEAL",
                              "PAID", "DENIED")


def assert_draw_request(data: dict):
    _assert_common(data)
    assert is_valid_uuid(str(data.get("loan_account_id", "")))
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["purpose"] in ("SEED", "FERTILIZER", "FUEL", "LABOR",
                               "EQUIPMENT_REPAIR", "LIVING_EXPENSE")
    assert data["status"] in ("REQUESTED", "APPROVED", "DENIED", "CANCELLED",
                              "DISBURSED", "RESCINDED")


def assert_repayment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(str(data.get("loan_account_id", "")))
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["source"] in ("HARVEST_PROCEEDS", "INSURANCE_INDEMNITY", "OTHER")
    assert isinstance(data["applied_interest_cents"], int)
    assert isinstance(data["applied_principal_cents"], int)
    assert data["status"] in ("APPLIED", "REVERSED")


def assert_covenant_evaluation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(str(data.get("loan_account_id", "")))
    assert is_valid_uuid(str(data.get("borrower_id", "")))
    assert isinstance(data["current_assets_cents"], int)
    assert isinstance(data["current_liabilities_cents"], int)
    assert isinstance(data["working_capital_cents"], int)
    assert isinstance(data["current_ratio_milli"], int)
    assert isinstance(data["required_ratio_milli"], int)
    assert data["outcome"] in ("COMPLIANT", "BREACH")
    assert isinstance(data["recorded_by_user_id"], str)
    assert data["status"] in ("RECORDED", "WAIVED", "VOIDED")


def assert_restructure_plan(data: dict):
    _assert_common(data)
    assert is_valid_uuid(str(data.get("loan_account_id", "")))
    assert data["plan_type"] in ("STANDARD", "DISASTER")
    assert data["amortization_style"] in ("EQUAL_INSTALLMENT", "BALLOON")
    assert isinstance(data["extension_months"], int)
    assert isinstance(data["new_rate_bps"], int)
    assert isinstance(data["capitalize_interest"], bool)
    assert isinstance(data["base_balance_cents"], int)
    assert isinstance(data["new_installment_cents"], int)
    assert isinstance(data["created_by_user_id"], str)
    assert data["status"] in ("PROPOSED", "COMMITTEE_REVIEW", "APPROVED",
                              "REJECTED", "EXECUTED", "SUPERSEDED", "WITHDRAWN")


def assert_deferral_request(data: dict):
    _assert_common(data)
    assert is_valid_uuid(str(data.get("loan_account_id", "")))
    assert isinstance(data["disaster_ref"], str) and data["disaster_ref"]
    assert data["status"] in ("SUBMITTED", "APPROVED", "DENIED", "IN_EFFECT",
                              "EXPIRED", "ENDED_EARLY")


def assert_patronage_distribution(data: dict):
    _assert_common(data)
    assert is_valid_uuid(str(data.get("association_id", "")))
    assert isinstance(data["fiscal_year"], int)
    assert isinstance(data["pool_cents"], int) and data["pool_cents"] > 0
    assert isinstance(data["allocated_cents"], int)
    assert isinstance(data["undistributed_cents"], int)
    assert isinstance(data["allocation_lines"], list)
    assert data["status"] in ("DECLARED", "ALLOCATED", "PAID")


def assert_margin_call_notice(data: dict):
    _assert_common(data)
    assert is_valid_uuid(str(data.get("loan_account_id", "")))
    assert isinstance(data["deficiency_cents"], int)
    assert data["status"] in ("ISSUED", "CURED", "ESCALATED")


def assert_financial_summary(data: dict):
    """The computed read of PRD section 3.6 carries the derived loan fields."""
    for field in ("outstanding_principal_cents", "accrued_interest_cents",
                  "borrowing_base_cents", "pending_draw_cents",
                  "available_credit_cents", "coverage_cents"):
        assert isinstance(data.get(field), int), f"{field} must be an integer"
    assert data["payment_posture"] in ("CURRENT", "WATCH", "DELINQUENT", "DEFAULT")
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "ACTIVE",
                              "RESTRUCTURING", "PAID_OFF", "CHARGED_OFF",
                              "FORECLOSED")


def assert_pool_invariant(distribution: dict):
    """PRD section 3.9: allocated + undistributed == pool, always."""
    assert distribution["allocated_cents"] + distribution["undistributed_cents"] \
        == distribution["pool_cents"], "patronage pool invariant violated"


def assert_allocation_line(line: dict):
    assert is_valid_uuid(str(line.get("borrower_id", "")))
    assert isinstance(line["interest_paid_cents"], int)
    assert isinstance(line["raw_share_cents"], (int, float))
    assert isinstance(line["final_share_cents"], int)
    assert isinstance(line["clawed_back"], bool)
