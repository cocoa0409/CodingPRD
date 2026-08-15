"""Entity assertions and domain invariant checkers for the Problem Loan Workout API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be an int >= 1"


def _assert_ledger_fields(data: dict):
    # Append-only records: id + created_at, no updated_at / version.
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only record must not expose updated_at"
    assert "version" not in data, "append-only record must not expose version"


def assert_borrower(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["tax_id"], str) and data["tax_id"]
    assert isinstance(data["naics_code"], str)
    assert isinstance(data["internal_risk_rating"], int)
    assert 1 <= data["internal_risk_rating"] <= 10
    assert isinstance(data["guarantor_name"], str)
    assert isinstance(data["guarantor_net_worth_cents"], int)
    assert data["status"] in ("ACTIVE", "EXITED")


def assert_loan(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("borrower_id", ""))
    assert isinstance(data["loan_number"], str) and data["loan_number"]
    assert isinstance(data["original_principal_cents"], int)
    assert isinstance(data["current_principal_cents"], int)
    assert isinstance(data["contractual_rate_bps"], int)
    assert isinstance(data["days_past_due"], int)
    assert isinstance(data["is_tdr"], bool)
    assert isinstance(data["nonaccrual"], bool)
    assert isinstance(data["charged_off_principal_cents"], int)
    assert data["status"] in ("PERFORMING", "WATCHLIST", "WORKOUT", "FORECLOSURE", "RESOLVED")


def assert_workout_case(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("loan_id", ""))
    assert data["entry_trigger"] in (
        "DELINQUENCY_60", "RISK_RATING_DOWNGRADE", "COVENANT_DEFAULT", "MANUAL_REFERRAL")
    assert isinstance(data["risk_rating_at_entry"], int)
    assert isinstance(data["case_officer_id"], str)
    assert isinstance(data["loss_given_default_cents"], int)
    assert isinstance(data["impairment_reserve_cents"], int)
    assert isinstance(data["unapplied_cash_cents"], int)
    assert data["tdr_status"] in ("NOT_EVALUATED", "PENDING_EVALUATION", "TDR_CONFIRMED", "TDR_REJECTED")
    assert data["resolution_path"] in ("NONE", "FORECLOSURE", "DEED_IN_LIEU", "NOTE_SALE", "RETURN_TO_PERFORMING")
    assert data["status"] in (
        "WATCHLIST", "ACTION_PLAN", "NEGOTIATION", "IMPAIRMENT_REVIEW", "LEGAL", "RESOLUTION", "CLOSED")
    assert data.get("version_anchor") == data.get("version"), "version_anchor must equal version"


def assert_action_plan(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("case_id", ""))
    assert isinstance(data["plan_text"], str)
    assert isinstance(data["target_resolution_date"], str)
    assert isinstance(data["milestone_count"], int) and data["milestone_count"] >= 1
    assert isinstance(data["supersedes_plan_id"], str)
    assert isinstance(data["approval_round"], int)
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "SUPERSEDED")


def assert_proposal(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("case_id", ""))
    assert data["proposal_kind"] in ("FORBEARANCE", "MODIFICATION", "RESTRUCTURE")
    assert isinstance(data["concession_rate_bps"], int)
    assert isinstance(data["term_extension_months"], int)
    assert isinstance(data["principal_forgiveness_cents"], int)
    assert isinstance(data["borrower_concession_cents"], int)
    assert isinstance(data["negotiation_round"], int)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "UNDER_BORROWER_REVIEW", "COUNTERED", "RESUBMITTED",
        "COMMITTEE_REVIEW", "APPROVED", "CONSUMMATED", "REJECTED", "WITHDRAWN")


def assert_collateral_item(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("loan_id", ""))
    assert data["collateral_type"] in (
        "CRE_REAL_ESTATE", "EQUIPMENT", "INVENTORY", "RECEIVABLES", "SECURITIES")
    assert isinstance(data["description"], str)
    assert isinstance(data["liquidation_discount_bps"], int)
    assert isinstance(data["current_appraised_value_cents"], int)
    assert isinstance(data["current_liquidation_value_cents"], int)
    assert data["status"] in ("PLEDGED", "UNDER_REVALUATION", "RELEASED", "LIQUIDATED")


def assert_appraisal(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("collateral_id", ""))
    assert isinstance(data["appraised_value_cents"], int)
    assert isinstance(data["effective_date"], str)
    assert isinstance(data["appraiser_id"], str)
    assert data["status"] in ("DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED")


def assert_impairment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("case_id", ""))
    assert data["method"] in ("CECL", "TDR_DCF")
    assert isinstance(data["is_active"], bool)
    assert data["status"] in ("DRAFT", "FINALIZED", "SUPERSEDED")


def assert_legal_referral(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("case_id", ""))
    assert data["referral_kind"] in ("GUARANTOR_PURSUITS", "FORECLOSURE", "DEED_IN_LIEU", "NOTE_SALE_PREP")
    assert isinstance(data["statute_deadline"], str)
    assert data["status"] in ("PENDING_COUNSEL", "ACTIVE", "SETTLED", "DISMISSED")


def assert_charge_off(data: dict):
    _assert_ledger_fields(data)
    assert is_valid_uuid(data.get("case_id", ""))
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["reason_code"] in ("CONFIRMED_LOSS", "STATUTORY", "PARTIAL_IMPAIRMENT")
    assert isinstance(data.get("booked_at"), str)
    assert isinstance(data["is_partial"], bool)


def assert_recovery(data: dict):
    _assert_ledger_fields(data)
    assert is_valid_uuid(data.get("case_id", ""))
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["recovery_source"] in (
        "GUARANTOR_SETTLEMENT", "COLLATERAL_LIQUIDATION", "BORROWER_CURE", "NOTE_SALE_PROCEEDS")
    assert data["allocation_mode"] in ("CHRONOLOGICAL", "WATERFALL")
    assert isinstance(data.get("booked_at"), str)


def assert_exit_decision(data: dict):
    _assert_ledger_fields(data)
    assert is_valid_uuid(data.get("case_id", ""))
    assert data["chosen_path"] in ("FORECLOSURE", "DEED_IN_LIEU", "NOTE_SALE", "RETURN_TO_PERFORMING")
    assert isinstance(data["npv_foreclosure_cents"], int)
    assert isinstance(data["npv_deed_in_lieu_cents"], int)
    assert isinstance(data.get("decided_at"), str)


def assert_loan_principal_ledger_invariants(loan: dict):
    """Principal ledger invariants that must hold after any mutation."""
    assert loan["current_principal_cents"] >= 0, "current principal cannot go negative"
    assert loan["charged_off_principal_cents"] >= 0, "charged-off principal cannot go negative"
    assert loan["current_principal_cents"] + loan["charged_off_principal_cents"] <= loan["original_principal_cents"]


def assert_case_invariants(case: dict):
    """Workout case invariants: LGD and reserve never negative; version_anchor tracks version."""
    assert case["loss_given_default_cents"] >= 0, "LGD floored at zero"
    assert case["impairment_reserve_cents"] >= 0
    assert case["unapplied_cash_cents"] >= 0
    assert case["version_anchor"] == case["version"]
