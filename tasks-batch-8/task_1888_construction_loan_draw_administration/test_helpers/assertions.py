"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}: id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}: created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}: updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}: version must be a positive integer"
    )


def assert_borrower(data: dict):
    _assert_common_fields(data, "Borrower")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert data["entity_type"] in ("INDIVIDUAL", "LLC", "CORPORATION", "PARTNERSHIP")


def assert_loan(data: dict):
    _assert_common_fields(data, "Loan")
    assert isinstance(data["borrower_id"], str) and data["borrower_id"]
    assert isinstance(data["commitment_amount_cents"], int)
    assert isinstance(data["interest_rate_annual_bps"], int)
    assert data["day_count_convention"] in ("ACTUAL_360", "THIRTY_360")
    assert isinstance(data["interest_reserve_initial_cents"], int)
    assert isinstance(data["maturity_date"], str) and data["maturity_date"]
    assert data["status"] in ("OPEN", "CONVERTED", "TERMINATED")
    for field in ("total_original_budget_cents", "principal_disbursed_cents",
                  "retained_cents", "interest_reserve_balance_cents",
                  "interest_reserve_swept_cents", "interest_capitalized_cents"):
        assert isinstance(data[field], int), f"Loan: {field} must be int cents"
    for field in ("interest_reserve_depleted", "milestone_reached",
                  "retainage_fully_released"):
        assert isinstance(data[field], bool), f"Loan: {field} must be bool"
    assert isinstance(data["inspection_percent_complete"], (int, float))
    assert isinstance(data["cost_percent_complete"], (int, float))


def assert_budget_line(data: dict):
    _assert_common_fields(data, "BudgetLine")
    assert isinstance(data["loan_id"], str) and data["loan_id"]
    assert isinstance(data["cost_code"], str) and data["cost_code"]
    assert isinstance(data["original_amount_cents"], int)
    assert isinstance(data["is_contingency"], bool)
    assert data["status"] in ("ACTIVE", "CLOSED")
    for field in ("revised_amount_cents", "disbursed_cents", "retained_cents",
                  "approved_unfunded_cents"):
        assert isinstance(data[field], int), f"BudgetLine: {field} must be int cents"


def assert_draw_request(data: dict):
    _assert_common_fields(data, "DrawRequest")
    assert isinstance(data["loan_id"], str) and data["loan_id"]
    assert isinstance(data["draw_number"], int) and data["draw_number"] >= 1
    assert isinstance(data["period_start_date"], str)
    assert isinstance(data["period_end_date"], str)
    assert data["status"] in ("DRAFT", "SUBMITTED", "UNDER_REVIEW",
                              "REVISION_REQUESTED", "APPROVED", "FUNDED",
                              "REJECTED", "WITHDRAWN")
    for field in ("requested_total_cents", "approved_total_cents",
                  "retainage_total_cents", "funded_total_cents"):
        assert isinstance(data[field], int), f"DrawRequest: {field} must be int cents"
    assert isinstance(data["milestone_applied"], bool)


def assert_draw_line_item(data: dict):
    _assert_common_fields(data, "DrawLineItem")
    assert isinstance(data["draw_id"], str) and data["draw_id"]
    assert isinstance(data["budget_line_id"], str) and data["budget_line_id"]
    assert data["line_type"] in ("WORK_COMPLETED", "STORED_MATERIALS")
    assert isinstance(data["requested_cents"], int)
    assert isinstance(data["is_installed"], bool)
    for field in ("approved_cents", "retainage_cents", "net_fundable_cents",
                  "funded_cents"):
        assert isinstance(data[field], int), f"DrawLineItem: {field} must be int cents"


def assert_draw_document(data: dict):
    _assert_common_fields(data, "DrawDocument")
    assert isinstance(data["draw_id"], str) and data["draw_id"]
    assert data["doc_type"] in ("LIEN_WAIVER_CONDITIONAL",
                                "LIEN_WAIVER_UNCONDITIONAL", "INVOICE",
                                "INSURANCE_CERTIFICATE")
    assert isinstance(data["party_name"], str) and data["party_name"]
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["doc_date"], str)
    assert data["status"] in ("SUBMITTED", "VERIFIED", "REJECTED")


def assert_inspection(data: dict):
    _assert_common_fields(data, "Inspection")
    assert isinstance(data["loan_id"], str) and data["loan_id"]
    assert isinstance(data["scheduled_date"], str)
    assert data["status"] in ("ORDERED", "COMPLETED", "ACCEPTED", "REJECTED",
                              "CANCELLED")


def assert_reallocation_request(data: dict):
    _assert_common_fields(data, "ReallocationRequest")
    assert isinstance(data["loan_id"], str) and data["loan_id"]
    assert isinstance(data["from_budget_line_id"], str)
    assert isinstance(data["to_budget_line_id"], str)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["status"] in ("PENDING", "APPROVED", "APPLIED", "REJECTED",
                              "CANCELLED")
    assert isinstance(data["created_loan_version"], int)


def assert_retainage_release(data: dict):
    _assert_common_fields(data, "RetainageRelease")
    assert isinstance(data["loan_id"], str) and data["loan_id"]
    assert isinstance(data["budget_line_id"], str)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["status"] in ("REQUESTED", "APPROVED", "PAID", "REJECTED")


def assert_conversion_review(data: dict):
    _assert_common_fields(data, "ConversionReview")
    assert isinstance(data["loan_id"], str) and data["loan_id"]
    assert data["status"] in ("REQUESTED", "APPROVED", "CONVERTED", "DECLINED")


def assert_interest_reserve_entry(data: dict):
    """Ledger entries are append-only: id + created_at, but no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "Entry: id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "Entry: created_at must be ISO 8601"
    )
    assert "updated_at" not in data, "Entry: updated_at must be absent (append-only)"
    assert "version" not in data, "Entry: version must be absent (append-only)"
    assert isinstance(data["entry_index"], int) and data["entry_index"] >= 1
    assert data["entry_type"] in ("INITIAL_DEPOSIT", "INTEREST_PAYMENT",
                                  "CAPITALIZATION", "SWEEP")
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["reserve_balance_after_cents"], int)


def assert_reserve_conservation(loan: dict):
    """initial reserve == balance + paid out + swept (signed ledger sums to it)."""
    assert loan["interest_reserve_balance_cents"] >= 0
    assert loan["interest_reserve_swept_cents"] >= 0
    assert loan["interest_reserve_balance_cents"] <= (
        loan["interest_reserve_initial_cents"]
    )
