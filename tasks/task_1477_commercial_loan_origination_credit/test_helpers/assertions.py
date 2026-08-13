"""Entity assertions and domain invariant checkers (PRD sections 2.2-2.4, 3.x)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    """Every resource carries id / created_at / updated_at / version (PRD 2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_bank_officer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]


def assert_borrower(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["naics_code"], str) and data["naics_code"]
    assert isinstance(data["is_reg_o_insider"], bool)
    assert isinstance(data["relationship_since"], str)
    assert data["status"] in ("ACTIVE", "SUSPENDED", "EXITED")
    for field in ("committed_exposure_cents", "funded_exposure_cents", "total_exposure_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"


def assert_exposure_conservation(borrower: dict):
    """total_exposure_cents is exactly committed + funded (PRD 3.1)."""
    assert borrower["total_exposure_cents"] == (
        borrower["committed_exposure_cents"] + borrower["funded_exposure_cents"]
    ), (
        f"total {borrower['total_exposure_cents']} != committed "
        f"{borrower['committed_exposure_cents']} + funded {borrower['funded_exposure_cents']}"
    )


def assert_loan_application(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("borrower_id", ""))
    assert is_valid_uuid(data.get("originating_officer_id", ""))
    assert data["product_type"] in (
        "CRE_TERM", "CRE_CONSTRUCTION", "CI_WORKING_CAPITAL", "EQUIPMENT", "AGRICULTURE",
    )
    assert isinstance(data["requested_amount_cents"], int) and data["requested_amount_cents"] > 0
    assert isinstance(data["term_months"], int)
    assert data["status"] in (
        "INTAKE", "SPREADING", "EXCEPTION_REVIEW", "APPRAISAL_REVIEW", "COMMITTEE_REVIEW",
        "TERM_SHEET_NEGOTIATION", "COMMITMENT", "DOCUMENTATION", "CLOSING", "FUNDED",
        "DECLINED", "WITHDRAWN", "EXPIRED",
    )
    for field in ("total_appraised_value_cents", "total_eligible_collateral_cents",
                  "total_liquidation_collateral_cents", "bank_hold_amount_cents",
                  "funded_amount_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"


def assert_financial_statement(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("loan_application_id", ""))
    assert isinstance(data["period_end_date"], str)
    for field in ("revenue_cents", "ebitda_cents", "addbacks_cents", "distributions_cents",
                  "maintenance_capex_cents", "existing_annual_debt_service_cents",
                  "total_assets_cents", "total_liabilities_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"
    assert data["status"] in ("SUBMITTED", "SPREAD", "FINAL", "SUPERSEDED")


def assert_policy_exception(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("loan_application_id", ""))
    assert data["rule_code"] in (
        "DSCR_MINIMUM", "STRESS_DSCR_MINIMUM", "SINGLE_BORROWER_LIMIT", "REG_O_INSIDER",
        "LTV_MAXIMUM", "COLLATERAL_COVERAGE_MIN", "COVENANT_BREACH", "REQUIRED_DOC_WAIVER",
    )
    assert data["severity"] in ("HIGH", "LOW")
    assert data["status"] in ("OPEN", "WAIVED", "RESOLVED_BY_CHANGE")


def assert_appraiser(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert isinstance(data["max_concurrent_engagements"], int)
    assert data["max_concurrent_engagements"] >= 1
    assert data["status"] in ("ELIGIBLE", "SUSPENDED")


def assert_appraisal(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("loan_application_id", ""))
    assert is_valid_uuid(data.get("appraiser_id", ""))
    assert data["collateral_class"] in (
        "REAL_ESTATE", "EQUIPMENT", "RECEIVABLES", "INVENTORY", "AGRICULTURAL",
    )
    assert isinstance(data["engagement_start_date"], str)
    assert isinstance(data["engagement_end_date"], str)
    assert data["status"] in ("ENGAGED", "REPORT_RECEIVED", "ACCEPTED", "REJECTED", "CANCELLED")


def assert_committee_session(data: dict):
    _assert_common_fields(data)
    assert data["level"] in ("SMALL", "STANDARD", "LARGE")
    assert isinstance(data["starts_at"], str)
    assert isinstance(data["ends_at"], str)
    assert data["status"] in ("SCHEDULED", "ADJOURNED")


def assert_committee_decision(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("loan_application_id", ""))
    assert is_valid_uuid(data.get("committee_session_id", ""))
    assert data["level_required"] in ("SMALL", "STANDARD", "LARGE")
    assert isinstance(data["votes_required"], int)
    assert isinstance(data["votes"], list)
    assert isinstance(data["votes_for"], int)
    assert isinstance(data["votes_against"], int)
    assert isinstance(data["chair_approved"], bool)
    assert data["status"] in ("OPEN", "APPROVED", "DECLINED", "REMANDED")


def assert_term_sheet(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("loan_application_id", ""))
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["rate_bps"], int)
    assert isinstance(data["term_months"], int)
    assert isinstance(data["expires_at"], str)
    assert isinstance(data["origination_fee_cents"], int)
    assert data["status"] in ("ISSUED", "ACCEPTED", "DECLINED", "SUPERSEDED", "EXPIRED")


def assert_commitment_letter(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("loan_application_id", ""))
    assert isinstance(data["committed_amount_cents"], int)
    assert isinstance(data["rate_bps"], int)
    assert isinstance(data["term_months"], int)
    assert isinstance(data["origination_fee_cents"], int)
    assert data["status"] in ("DRAFT", "ISSUED", "ACCEPTED", "FUNDED", "EXPIRED", "TERMINATED")


def assert_checklist_item(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("loan_application_id", ""))
    assert data["category"] in ("DOCUMENT", "CLOSING_CONDITION")
    assert isinstance(data["label"], str) and data["label"]
    assert isinstance(data["is_required"], bool)
    assert data["severity"] in ("STANDARD", "CRITICAL")
    assert data["status"] in ("PENDING", "RECEIVED", "APPROVED", "REJECTED", "WAIVED", "CANCELLED")


def assert_funding_authorization(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("loan_application_id", ""))
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["disbursement_date"], str)
    assert is_valid_uuid(data.get("requested_by_officer_id", ""))
    assert data["status"] in ("REQUESTED", "AUTHORIZED", "RELEASED", "CANCELLED")


def assert_covenant(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("loan_application_id", ""))
    assert data["covenant_type"] in ("DSCR_MIN", "LEVERAGE_MAX", "CAPEX_LIMIT", "DISTRIBUTION_BLOCK")
    assert data["frequency"] in ("ANNUAL", "QUARTERLY")
    assert data["status"] in ("MONITORING", "COMPLIANT", "BREACH_PENDING", "CURED", "WAIVED")


def assert_participation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("loan_application_id", ""))
    assert isinstance(data["participant_bank_name"], str) and data["participant_bank_name"]
    assert isinstance(data["allocated_amount_cents"], int) and data["allocated_amount_cents"] > 0
    assert data["status"] in ("PROPOSED", "COMMITTED", "FUNDED", "RELEASED")
