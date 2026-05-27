"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


def _assert_common(data: dict, include_full_quartet: bool = True) -> None:
    """id + created_at common to every entity; updated_at + version on all
    except Payment (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), \
        f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    if include_full_quartet:
        assert is_iso8601_timestamp(data.get("updated_at", "")), \
            f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
        assert isinstance(data.get("version"), int) and data["version"] >= 1, \
            f"version must be int >= 1, got {data.get('version')!r}"


def assert_borrower(data: dict) -> None:
    _assert_common(data)
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["ssn_last4"], str) and len(data["ssn_last4"]) == 4


def assert_loan(data: dict) -> None:
    _assert_common(data)
    assert isinstance(data["borrower_id"], str)
    assert is_iso8601_timestamp(data["origination_date"])
    assert isinstance(data["original_principal_cents"], int) and \
        data["original_principal_cents"] > 0
    assert isinstance(data["original_property_value_cents"], int) and \
        data["original_property_value_cents"] > 0
    assert isinstance(data["interest_rate_bps"], int) and \
        data["interest_rate_bps"] >= 0
    assert isinstance(data["term_months"], int) and data["term_months"] > 0
    assert isinstance(data["pmi_monthly_cents"], int) and \
        data["pmi_monthly_cents"] >= 0
    assert isinstance(data["scheduled_monthly_pi_cents"], int) and \
        data["scheduled_monthly_pi_cents"] >= 0
    assert isinstance(data["principal_balance_cents"], int) and \
        data["principal_balance_cents"] >= 0
    assert isinstance(data["accrued_interest_cents"], int)
    assert isinstance(data["escrow_monthly_cents"], int)
    assert isinstance(data["total_monthly_payment_cents"], int)
    assert data["status"] in {
        "CURRENT", "DELINQUENT", "FORBEARANCE",
        "FORECLOSURE", "REINSTATED", "PAID_OFF",
    }
    assert isinstance(data["days_past_due"], int) and data["days_past_due"] >= 0
    assert is_iso8601_timestamp(data["next_due_date"])
    assert isinstance(data["pmi_required"], bool)
    assert data["pmi_status"] in {
        "ACTIVE", "REMOVAL_PENDING", "REMOVED",
        "AUTO_TERMINATED", "NOT_APPLICABLE",
    }


def assert_escrow_account(data: dict) -> None:
    _assert_common(data)
    assert isinstance(data["loan_id"], str)
    assert isinstance(data["balance_cents"], int) and data["balance_cents"] >= 0
    assert isinstance(data["annual_tax_cents"], int) and \
        data["annual_tax_cents"] >= 0
    assert isinstance(data["annual_insurance_cents"], int) and \
        data["annual_insurance_cents"] >= 0
    assert isinstance(data["cushion_months"], int) and \
        0 <= data["cushion_months"] <= 2
    assert isinstance(data["shortage_cents"], int) and \
        data["shortage_cents"] >= 0
    assert isinstance(data["surplus_cents"], int) and \
        data["surplus_cents"] >= 0


def assert_payment(data: dict) -> None:
    """Payment is append-only per PRD §2.4 — id + created_at only;
    no updated_at, no version."""
    _assert_common(data, include_full_quartet=False)
    # Explicit absence of mutability fields (Payment is immutable per §2.4).
    assert "version" not in data, \
        "Payment row must not carry version (PRD §2.4 append-only)"
    assert isinstance(data["loan_id"], str)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert is_iso8601_timestamp(data["received_at"])
    assert data["status"] in {"POSTED", "SUSPENSE", "REVERSED"}
    assert is_iso8601_timestamp(data["posted_at"])
    alloc = data.get("allocation") or {}
    for k in ("interest_cents", "principal_cents", "escrow_cents",
              "pmi_cents", "late_fee_cents", "suspense_cents"):
        assert isinstance(alloc.get(k), int), \
            f"allocation.{k} must be int, got {alloc.get(k)!r}"
        assert alloc[k] >= 0


def assert_disbursement(data: dict) -> None:
    _assert_common(data)
    assert isinstance(data["escrow_account_id"], str)
    assert data["kind"] in {"TAX", "INSURANCE"}
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert is_iso8601_timestamp(data["scheduled_for"])
    assert data["status"] in {"SCHEDULED", "PAID", "FAILED", "CANCELLED"}
    assert data["failure_reason"] in {"INSUFFICIENT_FUNDS", "NONE"}


def assert_escrow_analysis(data: dict) -> None:
    _assert_common(data)
    assert isinstance(data["loan_id"], str)
    assert data["variant"] in {"ACTUAL_TRAILING_12", "FORECAST_NEXT_12"}
    assert isinstance(data["projected_low_point_cents"], int)
    assert isinstance(data["required_low_point_cents"], int)
    assert isinstance(data["shortage_cents"], int) and \
        data["shortage_cents"] >= 0
    assert isinstance(data["surplus_cents"], int) and \
        data["surplus_cents"] >= 0
    assert isinstance(data["new_escrow_monthly_cents"], int) and \
        data["new_escrow_monthly_cents"] >= 0


def assert_forbearance_plan(data: dict) -> None:
    _assert_common(data)
    assert isinstance(data["loan_id"], str)
    assert is_iso8601_timestamp(data["start_date"])
    assert is_iso8601_timestamp(data["end_date"])
    assert isinstance(data["reduced_payment_cents"], int) and \
        data["reduced_payment_cents"] >= 0
    assert isinstance(data["deferred_total_cents"], int) and \
        data["deferred_total_cents"] >= 0
    assert data["status"] in {
        "PROPOSED", "ACTIVE", "COMPLETED", "TERMINATED_EARLY",
    }


def assert_foreclosure_case(data: dict) -> None:
    _assert_common(data)
    assert isinstance(data["loan_id"], str)
    assert data["status"] in {
        "FILED", "MEDIATION_REQUIRED", "IN_MEDIATION",
        "MEDIATION_FAILED", "SALE_SCHEDULED", "COMPLETED", "WITHDRAWN",
    }
    assert isinstance(data["cure_amount_cents"], int) and \
        data["cure_amount_cents"] >= 0


def assert_mediation_session(data: dict) -> None:
    _assert_common(data)
    assert isinstance(data["foreclosure_case_id"], str)
    assert is_iso8601_timestamp(data["scheduled_for"])
    assert data["outcome"] in {
        "PENDING", "MODIFICATION_AGREED", "FORBEARANCE_AGREED", "NO_AGREEMENT",
    }


def assert_pmi_removal_request(data: dict) -> None:
    _assert_common(data)
    assert isinstance(data["loan_id"], str)
    assert data["status"] in {"PENDING", "APPROVED", "DENIED"}
    assert data["denial_reason"] in {
        "LTV_TOO_HIGH", "PAYMENT_HISTORY_NOT_CLEAN", "IN_DELINQUENCY", "NONE",
    }
    assert isinstance(data["computed_ltv_bps"], int) and \
        data["computed_ltv_bps"] >= 0
