"""Entity assertions and domain invariant checkers."""

from datetime import datetime

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    COMPLIANCE_CLEAR_FLOOR,
    QUALIFICATION_SCORE_CAP,
    REQUIRED_DISCLOSURE_COUNT,
    SEVERITY_PENALTY_POINTS,
)


# ---------------------------------------------------------------------------
# Shared shape helpers
# ---------------------------------------------------------------------------


def assert_common_fields(data: dict) -> None:
    """Ordinary resources carry id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def assert_append_only_shape(data: dict) -> None:
    """Append-only event rows carry only id and created_at of the system fields."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert "version" not in data, "append-only rows have no version field"
    assert "updated_at" not in data, "append-only rows have no updated_at field"


def assert_rate_precision(value) -> None:
    """Rates derived from counts are stored to four decimal places."""
    assert isinstance(value, (int, float)), f"rate must be numeric, got {value!r}"
    assert round(float(value), 4) == float(
        value
    ), f"rate {value!r} carries more than four decimal places"


def _as_instant(value: str) -> datetime:
    assert isinstance(value, str), f"expected an ISO 8601 instant, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assert_instant_equals(actual, expected: str, field: str = "instant") -> None:
    """Compare two UTC instants by value rather than by text.

    Fractional-digit width is not part of what is being asserted, so
    ``2026-08-14T09:00:00Z`` and ``2026-08-14T09:00:00.000Z`` compare equal.
    """
    assert _as_instant(actual) == _as_instant(
        expected
    ), f"{field} should be {expected}, got {actual}"


def assert_cents(value, field: str) -> None:
    assert isinstance(value, int) and not isinstance(
        value, bool
    ), f"{field} must be a whole-cent integer, got {value!r}"


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------


def assert_tour_channel(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert data["channel_code"] in [
        "OFF_PROPERTY_CONTACT",
        "IN_HOUSE_REFERRAL",
        "MINI_VAC_PACKAGE",
        "TELEMARKETING",
        "OWNER_UPGRADE",
    ]
    assert 0 <= data["incentive_gift_value_cents"] <= 100000
    assert 18 <= data["min_age"] <= 99
    assert data["min_household_income_cents"] >= 0
    assert 0 <= data["min_qualification_score"] <= 100
    assert isinstance(data["requires_married_household"], bool)
    assert data["status"] in ["ACTIVE", "SUSPENDED"]
    for counter in ("booked_count", "toured_count", "no_show_count"):
        assert data[counter] >= 0, f"{counter} must not be negative"
    assert_cents(data["gift_liability_cents"], "gift_liability_cents")
    assert data["gift_liability_cents"] >= 0
    assert_rate_precision(data["historical_no_show_rate"])


def assert_sales_gallery(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert 3 <= len(data["site_code"]) <= 8
    assert 1 <= data["concurrent_tour_capacity"] <= 20
    assert 30 <= data["presentation_minutes"] <= 480
    assert 0 <= data["buffer_minutes"] <= 120
    assert data["status"] in ["OPEN", "RESTRICTED", "CLOSED"]
    assert data["booked_slot_count"] >= 0
    assert data["available_rep_count"] >= 0


def assert_sales_representative(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["gallery_id"])
    assert isinstance(data["full_name"], str) and 1 <= len(data["full_name"]) <= 120
    assert 4 <= len(data["license_number"]) <= 32
    assert 1 <= data["rotation_position"] <= 99
    assert data["status"] in ["ACTIVE", "ON_TOUR", "RETRAINING", "SUSPENDED"]
    for counter in (
        "tours_taken_count",
        "executed_agreement_count",
        "rescinded_agreement_count",
        "compliance_strike_count",
    ):
        assert data[counter] >= 0, f"{counter} must not be negative"
    if data.get("cancellation_rate") is not None:
        assert_rate_precision(data["cancellation_rate"])


def assert_prospect(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["household_name"], str)
    assert 18 <= data["primary_age"] <= 99
    assert data["household_income_cents"] >= 0
    assert data["marital_status"] in ["MARRIED", "SINGLE"]
    assert isinstance(data["is_existing_owner"], bool)


def assert_tour_booking(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in [
        "SCHEDULED",
        "RESCHEDULE_PENDING",
        "CHECKED_IN",
        "TOURED",
        "NO_SHOW",
        "CANCELLED",
    ]
    assert is_iso8601_timestamp(data["scheduled_start_utc"])
    assert is_iso8601_timestamp(data["scheduled_end_utc"])
    assert 0 <= data["qualification_score"] <= QUALIFICATION_SCORE_CAP
    assert data["qualification_penalty_points"] >= 0
    assert isinstance(data["gift_issued"], bool)
    assert_cents(data["gift_value_cents"], "gift_value_cents")
    assert 0 <= data["reschedule_count"] <= 2


def assert_sales_presentation(data: dict) -> None:
    assert_common_fields(data)
    assert data["required_disclosure_count"] == REQUIRED_DISCLOSURE_COUNT
    assert 0 <= data["disclosure_ack_count"] <= REQUIRED_DISCLOSURE_COUNT
    assert data["disclosure_status"] in ["PENDING", "PARTIAL", "COMPLETE"]
    assert data["review_status"] in ["UNREVIEWED", "CLEARED", "FLAGGED"]
    assert data["prohibited_claim_points"] >= 0
    assert data["flag_count"] >= 0
    assert 0 <= data["compliance_score"] <= 100
    assert is_iso8601_timestamp(data["window_start_utc"])
    assert is_iso8601_timestamp(data["window_end_utc"])


def assert_disclosure_acknowledgment(data: dict) -> None:
    assert_append_only_shape(data)
    assert data["disclosure_code"] in [
        "RESCISSION_RIGHTS",
        "PUBLIC_OFFERING_STATEMENT_DELIVERY",
        "NOT_AN_INVESTMENT",
        "MAINTENANCE_FEE_ESCALATION",
    ]
    assert isinstance(data["acknowledged_by_prospect"], bool)
    assert data["recording_timestamp_offset_seconds"] >= 0
    assert isinstance(data["counts_toward_required"], bool)
    assert is_iso8601_timestamp(data["acknowledged_at"])


def assert_prohibited_claim_finding(data: dict) -> None:
    assert_append_only_shape(data)
    assert data["claim_code"] in [
        "GUARANTEED_RESALE",
        "GUARANTEED_APPRECIATION",
        "RENTAL_INCOME_PROMISE",
        "UNLIMITED_AVAILABILITY",
    ]
    assert data["severity"] in ["MINOR", "MAJOR", "EGREGIOUS"]
    assert data["penalty_points"] == SEVERITY_PENALTY_POINTS[data["severity"]]
    assert isinstance(data["reported_by_user_id"], str)
    assert is_iso8601_timestamp(data["detected_at"])


def assert_purchase_agreement(data: dict) -> None:
    assert_common_fields(data)
    assert data["product_type"] in ["DEEDED_INTEREST", "RIGHT_TO_USE"]
    assert data["state_code"] in ["FL", "NV", "CA", "TX", "HI"]
    assert data["rescission_status"] in ["OPEN", "EXPIRED", "RESCINDED"]
    assert data["fulfillment_status"] in [
        "AWAITING_FUNDING",
        "FUNDED",
        "RECORDED",
        "DOCS_DELIVERED",
        "VOIDED",
        "TRADED_IN",
    ]
    assert data["anchor_mode"] in [
        "LATER_OF_EXECUTION_OR_POS",
        "EXECUTION",
        "POS_DELIVERY",
    ]
    assert data["refund_policy"] in ["STATUTORY_FULL", "CONTRACTUAL_NET_OF_GIFT"]
    assert isinstance(data["business_day_rolled"], bool)
    for money in (
        "purchase_price_cents",
        "down_payment_cents",
        "trade_in_equity_credit_cents",
        "total_due_cents",
        "down_payment_required_cents",
        "base_financed_cents",
        "doc_stamp_cents",
        "closing_cost_fee_cents",
        "financed_amount_cents",
        "escrow_collected_cents",
        "total_collected_cents",
        "retained_cents",
    ):
        assert_cents(data[money], money)
        assert data[money] >= 0, f"{money} must not be negative"
    assert is_iso8601_timestamp(data["executed_at"])
    assert is_iso8601_timestamp(data["rescission_anchor_utc"])
    assert is_iso8601_timestamp(data["rescission_deadline_utc"])


def assert_financing_application(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in [
        "SUBMITTED",
        "APPROVED",
        "DECLINED",
        "WITHDRAWN",
        "CANCELLED",
    ]
    assert data["requested_amount_cents"] >= 1
    assert 300 <= data["applicant_fico"] <= 850
    assert data["term_months"] in [60, 120, 180]


def assert_rescission_request(data: dict) -> None:
    assert_common_fields(data)
    assert data["delivery_method"] in ["HAND_DELIVERED", "CERTIFIED_MAIL", "EMAIL"]
    assert data["timeliness_basis"] in ["POSTMARK", "RECEIPT"]
    assert isinstance(data["is_timely"], bool)
    assert data["status"] in ["RECEIVED", "VALIDATED", "REJECTED_LATE", "REFUNDED"]
    assert is_iso8601_timestamp(data["received_at"])
    assert is_iso8601_timestamp(data["effective_utc"])


def assert_refund_disbursement(data: dict) -> None:
    assert_common_fields(data)
    assert data["method"] in ["ACH", "CHECK", "CARD_REVERSAL"]
    assert data["refund_policy_applied"] in [
        "STATUTORY_FULL",
        "CONTRACTUAL_NET_OF_GIFT",
    ]
    assert data["status"] in ["PENDING", "ISSUED"]
    for money in (
        "base_refund_cents",
        "gift_recapture_cents",
        "doc_fee_retained_cents",
        "disbursed_amount_cents",
    ):
        assert_cents(data[money], money)
        assert data[money] >= 0, f"{money} must not be negative"


def assert_closing_package(data: dict) -> None:
    assert_common_fields(data)
    assert data["instrument_type"] in ["DEED", "RTU_CERTIFICATE"]
    assert data["status"] in ["AWAITING_RECORDING", "RECORDED", "DELIVERED"]


def assert_retraining_assignment(data: dict) -> None:
    assert_common_fields(data)
    assert data["trigger_reason"] in [
        "CANCELLATION_RATE_BREACH",
        "PROHIBITED_CLAIM_POINTS",
        "DISCLOSURE_GAP",
    ]
    assert 1 <= data["required_module_count"] <= 10
    assert data["status"] in ["ASSIGNED", "IN_PROGRESS", "COMPLETED", "FAILED"]
    assert 1 <= data["cycle_index"] <= 3
    assert is_iso8601_timestamp(data["assigned_at"])


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------


def assert_compliance_score_expression(presentation: dict) -> None:
    """compliance_score is 100 less claim points less 10 per missing disclosure,
    floored at 0."""
    gap = presentation["required_disclosure_count"] - presentation[
        "disclosure_ack_count"
    ]
    expected = max(0, 100 - presentation["prohibited_claim_points"] - 10 * gap)
    assert presentation["compliance_score"] == expected, (
        f"compliance_score should be {expected}, got "
        f"{presentation['compliance_score']}"
    )


def assert_not_auto_flagged_at_floor(presentation: dict) -> None:
    """The clear floor is inclusive on the passing side."""
    assert presentation["compliance_score"] >= COMPLIANCE_CLEAR_FLOOR


def assert_escrow_conservation(agreement: dict, disbursement: dict) -> None:
    """escrow_collected_cents == disbursed_amount_cents + retained_cents."""
    assert agreement["escrow_collected_cents"] == (
        disbursement["disbursed_amount_cents"] + agreement["retained_cents"]
    ), (
        f"escrow {agreement['escrow_collected_cents']} must equal disbursed "
        f"{disbursement['disbursed_amount_cents']} plus retained "
        f"{agreement['retained_cents']}"
    )
    assert agreement["retained_cents"] == (
        disbursement["gift_recapture_cents"] + disbursement["doc_fee_retained_cents"]
    ), "retained_cents must be the recapture plus the retained document fee"


def assert_agreement_financials_chain(agreement: dict) -> None:
    """The six pinned financial steps, re-checked against each other."""
    assert agreement["total_due_cents"] == max(
        0,
        agreement["purchase_price_cents"] - agreement["trade_in_equity_credit_cents"],
    )
    assert agreement["base_financed_cents"] == max(
        0, agreement["total_due_cents"] - agreement["down_payment_cents"]
    )
    if agreement["base_financed_cents"] == 0:
        assert agreement["doc_stamp_cents"] == 0
        assert agreement["closing_cost_fee_cents"] == 0
        assert agreement["financed_amount_cents"] == 0
    else:
        assert agreement["closing_cost_fee_cents"] == (
            129900 + agreement["doc_stamp_cents"]
        )
        assert agreement["financed_amount_cents"] == (
            agreement["base_financed_cents"] + agreement["closing_cost_fee_cents"]
        )
    assert agreement["escrow_collected_cents"] == agreement["down_payment_cents"]
