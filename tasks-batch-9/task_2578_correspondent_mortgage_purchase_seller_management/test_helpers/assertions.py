"""Shape assertions for each resource plus the domain's conserved identities."""

from typing import Optional

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import ADVICE, COMMITMENT

# ─── Common properties ──────────────────────────────────────────────────────


def assert_common_fields(data: dict) -> None:
    """Every resource carries an identifier, two timestamps and a version."""
    assert is_valid_uuid(data["id"]), f"id is not a UUID: {data['id']}"
    assert is_iso8601_timestamp(
        data["created_at"]
    ), f"created_at is not ISO 8601: {data['created_at']}"
    assert is_iso8601_timestamp(
        data["updated_at"]
    ), f"updated_at is not ISO 8601: {data['updated_at']}"
    assert isinstance(data["version"], int), "version must be an integer"
    assert data["version"] >= 1, f"version must start at 1, got {data['version']}"


def assert_optional_timestamp(value: Optional[str], field: str) -> None:
    if value is not None:
        assert is_iso8601_timestamp(value), f"{field} is not ISO 8601: {value}"


# ─── Seller family ──────────────────────────────────────────────────────────


def assert_seller(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["legal_name"], str)
    assert isinstance(data["tin"], str)
    assert data["seller_type"] in ("BANK", "CREDIT_UNION", "NON_BANK_IMB")
    assert data["approval_status"] in (
        "APPLIED",
        "UNDER_REVIEW",
        "APPROVED",
        "DECLINED",
    )
    assert data["delivery_standing"] in (
        "NOT_ELIGIBLE",
        "GOOD_STANDING",
        "WATCH",
        "SUSPENDED",
        "TERMINATED",
    )
    assert data["approval_tier"] in (None, "STANDARD", "CONDITIONAL")
    assert data["suspension_reason"] in (
        None,
        "MANUAL_COUNTERPARTY_ACTION",
        "SCORECARD_DEFECT_RATE",
    )
    assert data["current_scorecard_grade"] in ("UNRATED", "A", "B", "C", "D")
    assert isinstance(data["servicing_retained_eligible"], bool)
    for money_field in (
        "approved_tangible_net_worth_cents",
        "mandatory_exposure_limit_cents",
        "open_mandatory_exposure_cents",
        "net_funded_cents",
        "fee_receivable_cents",
        "current_defect_rate_bps",
    ):
        assert isinstance(
            data[money_field], int
        ), f"{money_field} must be an integer, got {data[money_field]!r}"
    assert (
        data["open_mandatory_exposure_cents"] >= 0
    ), "open mandatory exposure can never fall below zero"
    assert data["fee_receivable_cents"] >= 0, "fee receivable can never be negative"


def assert_financial_statement(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["seller_id"])
    assert isinstance(data["fiscal_year_end"], str)
    assert isinstance(data["tangible_net_worth_cents"], int)
    assert isinstance(data["liquid_assets_cents"], int)
    assert isinstance(data["audited"], bool)
    assert data["status"] in ("SUBMITTED", "ACCEPTED", "REJECTED")


def assert_qc_review(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["seller_id"])
    assert data["review_type"] in ("PRE_APPROVAL", "ANNUAL_RECERT")
    assert data["status"] in ("OPEN", "COMPLETED")
    assert data["outcome"] in (None, "PASS", "CONDITIONAL_PASS", "FAIL")
    assert isinstance(data["findings_count"], int)
    assert isinstance(data["critical_findings_count"], int)
    assert (
        data["critical_findings_count"] <= data["findings_count"]
    ), "critical findings can never exceed total findings"
    assert_optional_timestamp(data["completed_at"], "completed_at")


# ─── Product family ─────────────────────────────────────────────────────────


def assert_product(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["product_code"], str)
    assert isinstance(data["base_price_pct"], (int, float))
    assert isinstance(data["min_fico"], int)
    assert isinstance(data["max_ltv_pct"], (int, float))
    assert isinstance(data["max_loan_amount_cents"], int)
    assert isinstance(data["allowed_commitment_types"], list)
    assert data["allowed_commitment_types"], "allowed commitment types cannot be empty"
    assert isinstance(data["allowed_occupancies"], list)
    assert data["allowed_occupancies"], "allowed occupancies cannot be empty"
    assert isinstance(data["srp_pct"], (int, float))
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_pricing_adjustment(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["product_id"])
    assert isinstance(data["adjustment_code"], str)
    assert isinstance(data["fico_min"], int)
    assert isinstance(data["fico_max"], int)
    assert isinstance(data["price_adjustment_bps"], int)
    assert (
        data["ltv_max_pct"] > data["ltv_min_pct"]
    ), "the adjustment band's upper LTV bound must exceed its lower bound"
    assert data["status"] in ("ACTIVE", "RETIRED")


# ─── Commitment ─────────────────────────────────────────────────────────────


def assert_commitment(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["seller_id"])
    assert is_valid_uuid(data["product_id"])
    assert data["commitment_type"] in ("MANDATORY", "BEST_EFFORTS")
    assert data["status"] in (
        "LOCKED",
        "PARTIALLY_FULFILLED",
        "FULFILLED",
        "PAIRED_OFF",
        "EXPIRED",
        "CANCELLED",
    )
    for money_field in (
        "notional_amount_cents",
        "allocated_amount_cents",
        "fulfilled_amount_cents",
        "paired_off_amount_cents",
        "cancelled_amount_cents",
        "available_amount_cents",
        "tolerance_cents",
        "pair_off_fee_cents",
    ):
        assert isinstance(
            data[money_field], int
        ), f"{money_field} must be an integer number of cents"
    assert isinstance(data["lock_term_days"], int)
    assert isinstance(data["llpa_bps_applied"], int)
    assert data["pair_off_method"] in (
        None,
        "MANDATORY_MARK_TO_MARKET",
        "BEST_EFFORTS_ADMIN_ONLY",
        "ADMINISTRATIVE_FLAT",
    )
    assert_commitment_amounts_conserved(data)
    assert_commitment_price_in_band(data["commitment_price_pct"])


def assert_commitment_amounts_conserved(commitment: dict) -> None:
    """The residual identity that must hold on every commitment read."""
    expected_available = (
        commitment["notional_amount_cents"]
        - commitment["allocated_amount_cents"]
        - commitment["fulfilled_amount_cents"]
        - commitment["paired_off_amount_cents"]
        - commitment["cancelled_amount_cents"]
    )
    assert commitment["available_amount_cents"] == expected_available, (
        "available amount must equal notional less allocated, fulfilled, paired off "
        f"and cancelled: expected {expected_available}, "
        f"got {commitment['available_amount_cents']}"
    )
    assert (
        commitment["available_amount_cents"] >= 0
    ), "the available amount can never become negative"


def assert_commitment_price_in_band(price_pct: float) -> None:
    assert price_pct >= COMMITMENT["PRICE_FLOOR_PCT"] - 1e-9, (
        f"commitment price {price_pct} fell below the price floor "
        f"{COMMITMENT['PRICE_FLOOR_PCT']}"
    )
    assert price_pct <= COMMITMENT["PRICE_CEILING_PCT"] + 1e-9, (
        f"commitment price {price_pct} rose above the price ceiling "
        f"{COMMITMENT['PRICE_CEILING_PCT']}"
    )


def assert_price_pct_precision(price_pct: float) -> None:
    """Price percentages are carried to three decimal places."""
    assert price_pct == pytest.approx(
        round(price_pct, 3), abs=1e-9
    ), f"price percentage {price_pct} carries more than three decimal places"


# ─── Loan and purchase review ───────────────────────────────────────────────


def assert_loan(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["commitment_id"])
    assert is_valid_uuid(data["seller_id"])
    assert is_valid_uuid(data["product_id"])
    assert isinstance(data["seller_loan_number"], str)
    assert isinstance(data["note_amount_cents"], int)
    assert isinstance(data["escrow_balance_cents"], int)
    assert data["occupancy"] in ("PRIMARY", "SECOND_HOME", "INVESTMENT")
    assert data["servicing_election"] in ("RETAINED", "RELEASED")
    assert data["purchase_status"] in (
        "DELIVERED",
        "IN_REVIEW",
        "SUSPENDED",
        "CLEARED_FOR_PURCHASE",
        "PURCHASED",
        "REJECTED",
        "REPURCHASE_DEMANDED",
        "REPURCHASED",
    )
    assert data["first_payment_status"] in ("PENDING", "PAID", "MISSED")
    for counter in (
        "review_cycle_count",
        "open_defect_count",
        "non_curable_defect_count",
        "open_suspense_count",
        "advice_count",
    ):
        assert isinstance(data[counter], int), f"{counter} must be an integer"
        assert data[counter] >= 0, f"{counter} must never go negative"
    assert is_iso8601_timestamp(data["delivered_at"])
    assert_optional_timestamp(data["purchased_at"], "purchased_at")


def assert_defect(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["loan_id"])
    assert isinstance(data["defect_code"], str)
    assert data["category"] in (
        "CREDIT",
        "INCOME",
        "COLLATERAL",
        "COMPLIANCE",
        "DOCUMENTATION",
    )
    assert data["severity"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert data["classification"] in ("CURABLE", "NON_CURABLE")
    assert data["status"] in ("OPEN", "CURED", "WAIVED", "EXPIRED")
    assert isinstance(data["price_adjustment_bps"], int)
    assert_optional_timestamp(data["cure_deadline_at"], "cure_deadline_at")
    assert_optional_timestamp(data["cured_at"], "cured_at")
    if data["classification"] == "NON_CURABLE":
        assert (
            data["cure_deadline_at"] is None
        ), "a non-curable defect must not carry a cure deadline"


def assert_suspense_condition(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["loan_id"])
    assert isinstance(data["condition_code"], str)
    assert data["status"] in ("OPEN", "CLEARED", "EXPIRED")
    assert is_iso8601_timestamp(data["due_at"])
    assert_optional_timestamp(data["cleared_at"], "cleared_at")


# ─── Purchase advice ────────────────────────────────────────────────────────


def assert_purchase_advice(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["loan_id"])
    assert data["status"] in ("ISSUED", "SUPERSEDED", "SETTLED", "VOIDED", "REVERSED")
    for money_field in (
        "principal_purchase_cents",
        "accrued_interest_cents",
        "escrow_funding_cents",
        "service_release_premium_cents",
        "defect_price_adjustment_cents",
        "wire_fee_cents",
        "net_wire_cents",
    ):
        assert isinstance(
            data[money_field], int
        ), f"{money_field} must be an integer number of cents"
    assert isinstance(data["volume_incentive_bps"], int)
    assert isinstance(data["accrued_days"], int)
    assert is_iso8601_timestamp(data["issued_at"])
    assert_optional_timestamp(data["settled_at"], "settled_at")
    assert_price_pct_precision(data["final_purchase_price_pct"])
    assert_advice_net_wire_identity(data)


def assert_advice_net_wire_identity(advice: dict) -> None:
    """The net wire is the sum of the five components less the wire fee."""
    expected = (
        advice["principal_purchase_cents"]
        + advice["accrued_interest_cents"]
        + advice["escrow_funding_cents"]
        + advice["service_release_premium_cents"]
        + advice["defect_price_adjustment_cents"]
        - advice["wire_fee_cents"]
    )
    assert advice["net_wire_cents"] == expected, (
        "net wire must equal principal plus interest plus escrow plus premium plus "
        f"the defect adjustment less the wire fee: expected {expected}, "
        f"got {advice['net_wire_cents']}"
    )
    assert (
        advice["wire_fee_cents"] == ADVICE["WIRE_FEE_CENTS"]
    ), f"the wire fee is a flat {ADVICE['WIRE_FEE_CENTS']} cents"
    assert (
        advice["defect_price_adjustment_cents"] <= 0
    ), "the defect price adjustment is never positive"


# ─── Repurchase and escrow ──────────────────────────────────────────────────


def assert_repurchase_demand(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["loan_id"])
    assert is_valid_uuid(data["seller_id"])
    assert data["reason"] in ("EPD", "DEFECT", "MISREPRESENTATION")
    assert data["status"] in (
        "ISSUED",
        "APPEALED",
        "UPHELD",
        "RESCINDED",
        "SATISFIED",
    )
    assert isinstance(data["demand_letter_reference"], str)
    for money_field in (
        "funding_recovery_cents",
        "admin_fee_cents",
        "repurchase_price_cents",
    ):
        assert isinstance(data[money_field], int)
    assert (
        data["repurchase_price_cents"]
        == data["funding_recovery_cents"] + data["admin_fee_cents"]
    ), "the repurchase price is the funding recovery plus the administrative fee"
    assert is_iso8601_timestamp(data["appeal_deadline_at"])
    assert_optional_timestamp(data["satisfied_at"], "satisfied_at")


def assert_escrow_transfer(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["loan_id"])
    assert data["status"] in ("PENDING", "COMPLETED", "REVERSED")
    assert isinstance(data["transfer_amount_cents"], int)
    assert is_iso8601_timestamp(data["transfer_due_at"])
    assert_optional_timestamp(data["completed_at"], "completed_at")
    assert data["reversal_reason"] in (None, "REPURCHASE_SATISFIED")


# ─── Scorecard ──────────────────────────────────────────────────────────────


def assert_seller_scorecard(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["seller_id"])
    assert isinstance(data["period_start"], str)
    assert isinstance(data["period_end"], str)
    assert data["status"] in ("OPEN", "CLOSED")
    for counter in (
        "purchased_loan_count",
        "purchased_upb_cents",
        "defective_loan_count",
        "defective_upb_cents",
        "defect_rate_bps",
        "upb_weighted_defect_rate_bps",
    ):
        assert isinstance(data[counter], int), f"{counter} must be an integer"
        assert data[counter] >= 0, f"{counter} must never go negative"
    assert (
        data["defective_loan_count"] <= data["purchased_loan_count"]
    ), "the defective loan count can never exceed the scored population"
    assert data["grade"] in ("UNRATED", "A", "B", "C", "D")
    assert isinstance(data["breach"], bool)
    assert data["standing_action_applied"] in (
        "NONE",
        "WATCH",
        "SUSPENDED",
        "RECOVERED",
    )
    assert_optional_timestamp(data["closed_at"], "closed_at")


# ─── Cross-resource invariants ──────────────────────────────────────────────


def assert_exposure_matches_open_mandatory(
    seller: dict, open_mandatory_commitments: list
) -> None:
    """Exposure is the notional sum over the seller's open mandatory lines."""
    expected = sum(c["notional_amount_cents"] for c in open_mandatory_commitments)
    assert seller["open_mandatory_exposure_cents"] == expected, (
        "open mandatory exposure must equal the notional sum over the seller's "
        f"mandatory commitments still open: expected {expected}, "
        f"got {seller['open_mandatory_exposure_cents']}"
    )


def assert_version_advanced_by(before: dict, after: dict, delta: int) -> None:
    assert after["version"] == before["version"] + delta, (
        f"expected version to advance by {delta} from {before['version']}, "
        f"got {after['version']}"
    )
