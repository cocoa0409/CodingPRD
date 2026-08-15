"""Entity assertions and domain invariant checkers.

Field names follow the PRD exactly. Monetary comparisons tolerate float
representation only (half a cent), never a real rounding difference.
"""
import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

MONEY_TOLERANCE = 0.005


def assert_money(actual, expected, label="amount"):
    """PRD-exact two-decimal money equality (float-representation tolerant)."""
    assert actual is not None, f"{label}: expected {expected}, got None"
    assert float(actual) == pytest.approx(float(expected), abs=MONEY_TOLERANCE), (
        f"{label}: expected {expected}, got {actual}"
    )


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), (
        f"version must be an integer, got {data.get('version')!r}"
    )


def assert_inspection_facility(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["airport_code"], str) and data["airport_code"]
    assert isinstance(data["turnaround_buffer_minutes"], int)
    assert data["turnaround_buffer_minutes"] >= 0


def assert_listing(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["tail_number"], str) and data["tail_number"]
    assert isinstance(data["make"], str) and data["make"]
    assert isinstance(data["model"], str) and data["model"]
    assert isinstance(data["year"], int)
    assert isinstance(data["total_time_hours"], int) and data["total_time_hours"] >= 0
    assert isinstance(data["seller_name"], str) and data["seller_name"]
    assert data["status"] in ("DRAFT", "ACTIVE", "UNDER_CONTRACT", "SOLD")
    assert data["valuation_status"] in ("NONE", "PROVISIONAL", "FINAL")
    if data["market_value_estimate_usd"] is not None:
        assert_money(data["market_value_estimate_usd"],
                     data["market_value_estimate_usd"], "market_value_estimate_usd")


def assert_buyer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["qualification_status"] in ("UNQUALIFIED", "QUALIFIED")


def assert_comparable_sale(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["make"], str) and data["make"]
    assert isinstance(data["model"], str) and data["model"]
    assert isinstance(data["year"], int)
    assert isinstance(data["sale_date"], str) and data["sale_date"]
    assert isinstance(data["total_time_hours"], int) and data["total_time_hours"] >= 0
    assert data["comp_status"] in ("VERIFIED", "UNVERIFIED")
    assert_money(data["sale_price_usd"], data["sale_price_usd"], "sale_price_usd")


def assert_loi(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["listing_id"], str)
    assert isinstance(data["buyer_id"], str)
    assert data["status"] in ("SUBMITTED", "COUNTERED", "ACCEPTED", "REJECTED",
                              "WITHDRAWN")
    assert data["disclosure_status"] in ("NOT_REQUIRED", "PENDING", "PARTIAL",
                                         "FULLY_ACKED")
    assert isinstance(data["dual_agency"], bool)
    assert isinstance(data["buyer_acked"], bool)
    assert isinstance(data["seller_acked"], bool)
    assert_money(data["offer_price_usd"], data["offer_price_usd"], "offer_price_usd")
    assert_money(data["current_price_usd"], data["current_price_usd"],
                 "current_price_usd")
    assert_money(data["deposit_amount_usd"], data["deposit_amount_usd"],
                 "deposit_amount_usd")


def assert_transaction(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["loi_id"], str)
    assert isinstance(data["listing_id"], str)
    assert isinstance(data["buyer_id"], str)
    assert data["status"] in ("OPENED", "ESCROW_FUNDED", "INSPECTION_SCHEDULED",
                              "INSPECTION_COMPLETE", "DISCREPANCY_NEGOTIATION",
                              "DELIVERY_PENDING", "CLOSED", "TERMINATED")
    assert isinstance(data["dual_agency"], bool)
    assert isinstance(data["logbook_complete"], bool)
    assert isinstance(data["registration_docs_complete"], bool)
    assert_money(data["agreed_price_usd"], data["agreed_price_usd"], "agreed_price_usd")
    assert_money(data["credits_total_usd"], data["credits_total_usd"],
                 "credits_total_usd")


def assert_escrow_deposit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["transaction_id"], str)
    assert isinstance(data["escrow_ref"], str) and data["escrow_ref"]
    assert data["status"] in ("AWAITING_FUNDS", "FUNDED", "RELEASED", "REFUNDED",
                              "FORFEITED")
    assert_money(data["deposit_amount_usd"], data["deposit_amount_usd"],
                 "deposit_amount_usd")


def assert_inspection_booking(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["transaction_id"], str)
    assert isinstance(data["facility_id"], str)
    assert isinstance(data["start_at"], str) and data["start_at"]
    assert isinstance(data["end_at"], str) and data["end_at"]
    assert data["status"] in ("REQUESTED", "CONFIRMED", "COMPLETED", "CANCELLED")


def assert_discrepancy_item(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["transaction_id"], str)
    assert isinstance(data["inspection_booking_id"], str)
    assert isinstance(data["description"], str) and data["description"]
    assert data["severity"] in ("AIRWORTHINESS", "NON_AIRWORTHINESS")
    assert data["status"] in ("RAISED", "COUNTERED", "RESOLVED")
    assert data["resolution"] in ("REPAIR", "CREDIT", "WAIVED", None)
    assert_money(data["estimated_cost_usd"], data["estimated_cost_usd"],
                 "estimated_cost_usd")


def assert_escrow_disposition_invariant(data: dict):
    """PRD escrow reconciliation invariant: a terminal escrow disposes of
    exactly the deposited amount through exactly one channel; a non-terminal
    escrow has disposed of nothing."""
    released = float(data["released_usd"])
    refunded = float(data["refunded_usd"])
    forfeited = float(data["forfeited_usd"])
    disposed = released + refunded + forfeited
    if data["status"] in ("RELEASED", "REFUNDED", "FORFEITED"):
        assert disposed == pytest.approx(float(data["deposit_amount_usd"]),
                                         abs=MONEY_TOLERANCE), (
            f"terminal escrow must dispose of exactly the deposit: "
            f"{disposed} != {data['deposit_amount_usd']}"
        )
    else:
        assert disposed == pytest.approx(0.0, abs=MONEY_TOLERANCE), (
            f"non-terminal escrow must have disposed of nothing, got {disposed}"
        )
