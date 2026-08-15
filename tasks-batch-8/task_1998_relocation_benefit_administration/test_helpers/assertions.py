"""Entity assertions and domain invariant checkers (PRD §2.4, §2.6)."""
from datetime import datetime, timezone

import pytest
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def parse_timestamp(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp (with or without fractional digits)."""
    assert is_iso8601_timestamp(value), f"Not a valid ISO 8601 timestamp: {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assert_timestamp_equals_instant(value: str, year, month, day, hour=0, minute=0):
    """Assert a timestamp string denotes the given UTC instant, regardless of
    how many fractional digits the server chose to render (PRD §2.4/§2.5)."""
    actual = parse_timestamp(value)
    expected = datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
    assert actual == expected, f"Expected instant {expected.isoformat()}, got {value!r}"


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_employee(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["job_level"] in ["ASSOCIATE", "MANAGER", "DIRECTOR", "EXECUTIVE"]
    assert data["home_ownership"] in ["HOMEOWNER", "RENTER"]
    assert data["employment_status"] in ["ACTIVE", "TERMINATED"]
    if data["employment_status"] == "TERMINATED":
        assert is_iso8601_timestamp(data.get("termination_date", ""))
    else:
        assert data.get("termination_date") is None


def assert_policy(data: dict):
    _assert_common_fields(data)
    assert data["job_level"] in ["ASSOCIATE", "MANAGER", "DIRECTOR", "EXECUTIVE"]
    assert data["move_scope"] in ["DOMESTIC", "INTERNATIONAL"]
    assert data["home_ownership"] in ["HOMEOWNER", "RENTER"]
    for field in ("hhg_cap_cents", "temp_housing_cap_cents", "travel_cap_cents",
                  "loss_on_sale_cap_cents", "misc_cap_cents",
                  "marginal_bracket_threshold_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert isinstance(data["temp_housing_max_nights"], int)
    assert isinstance(data["home_sale_eligible"], bool)
    assert isinstance(data["repayment_window_months"], int)
    assert data["gross_up_method"] in ["FLAT_SUPPLEMENTAL", "MARGINAL_AGGREGATE"]
    assert data["loss_basis"] in ["APPRAISED", "PURCHASE_PRICE"]


def assert_vendor(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["service_regions"], list)
    assert data["status"] in ["ACTIVE", "SUSPENDED"]
    assert isinstance(data["rating_count"], int) and data["rating_count"] >= 0
    assert isinstance(data["rating_sum"], int) and data["rating_sum"] >= 0
    assert isinstance(data["completed_moves"], int) and data["completed_moves"] >= 0
    if data["rating_count"] == 0:
        assert data.get("avg_rating_lifetime") is None
    else:
        assert data["avg_rating_lifetime"] == pytest.approx(
            data["rating_sum"] / data["rating_count"], abs=0.005)


def assert_case(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("employee_id", ""))
    assert is_valid_uuid(data.get("policy_id", ""))
    assert data["move_scope"] in ["DOMESTIC", "INTERNATIONAL"]
    assert data["status"] in ["DRAFT", "AUTHORIZED", "IN_PROGRESS",
                              "CLOSED", "CLOSED_EARLY", "CANCELLED"]
    for field in ("total_committed_cents", "total_paid_cents",
                  "total_released_cents", "cumulative_taxable_paid_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer"
        assert data[field] >= 0, f"{field} must be non-negative"


def assert_case_ledger(case: dict, committed: int, paid: int, released: int):
    """Domain invariant: the three-column cost ledger holds exact totals."""
    assert case["total_committed_cents"] == committed, (
        f"total_committed_cents: expected {committed}, got {case['total_committed_cents']}")
    assert case["total_paid_cents"] == paid, (
        f"total_paid_cents: expected {paid}, got {case['total_paid_cents']}")
    assert case["total_released_cents"] == released, (
        f"total_released_cents: expected {released}, got {case['total_released_cents']}")


def assert_move_assignment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("case_id", ""))
    assert is_valid_uuid(data.get("vendor_id", ""))
    assert data["status"] in ["REQUESTED", "SURVEY_SCHEDULED", "ESTIMATE_SUBMITTED",
                              "ESTIMATE_APPROVED", "DELIVERED", "INVOICED",
                              "PAID", "CANCELLED"]


def assert_service_booking(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("case_id", ""))
    assert data["kind"] in ["TEMP_HOUSING", "TRAVEL"]
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["nights"], int)
    assert isinstance(data["total_cents"], int)
    assert data["status"] in ["HELD", "CONFIRMED", "COMPLETED", "CANCELLED"]
    if data["kind"] == "TEMP_HOUSING":
        assert data["total_cents"] == data["nights"] * data["amount_cents"]
    else:
        assert data["nights"] == 0
        assert data["total_cents"] == data["amount_cents"]


def assert_expense_claim(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("case_id", ""))
    assert data["category"] in ["MEALS", "LODGING", "TRANSPORT", "MISC"]
    assert data["payment_method"] in ["REIMBURSEMENT", "DIRECT_BILL"]
    assert isinstance(data["amount_cents"], int)
    assert data["taxable"] == (data["payment_method"] == "REIMBURSEMENT")
    assert isinstance(data["gross_up_cents"], int)
    assert isinstance(data["total_payment_cents"], int)
    assert data["status"] in ["SUBMITTED", "APPROVED", "REJECTED", "PAID"]


def assert_home_sale(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("case_id", ""))
    assert isinstance(data["appraised_value_cents"], int)
    assert isinstance(data["original_purchase_price_cents"], int)
    assert isinstance(data["list_price_cents"], int)
    assert data["status"] in ["LISTED", "SOLD", "SETTLED"]
    if data["status"] == "LISTED":
        assert data.get("gross_loss_cents") is None
        assert data.get("capped_benefit_cents") is None
        assert data.get("loss_basis_used") is None


def assert_repayment_agreement(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("case_id", ""))
    for field in ("total_owed_cents", "installments_count", "installment_cents",
                  "final_installment_cents", "paid_to_date_cents", "balance_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert data["status"] in ["DRAFT", "ACTIVE", "SETTLED", "DEFAULTED"]
    assert data["paid_to_date_cents"] + data["balance_cents"] == data["total_owed_cents"], (
        "invariant: paid_to_date_cents + balance_cents == total_owed_cents")
    if data["status"] in ("ACTIVE", "SETTLED", "DEFAULTED"):
        assert is_iso8601_timestamp(data.get("signed_at", ""))
        assert is_iso8601_timestamp(data.get("next_due_date", ""))


def assert_exception_request(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("case_id", ""))
    assert data["component"] in ["HHG", "TEMP_HOUSING", "TRAVEL", "MISC", "LOSS_ON_SALE"]
    assert isinstance(data["requested_cap_increase_cents"], int)
    assert isinstance(data["justification"], str)
    assert data["status"] in ["PENDING", "APPROVED", "REJECTED"]
    assert isinstance(data["appeal_count"], int) and data["appeal_count"] >= 0
