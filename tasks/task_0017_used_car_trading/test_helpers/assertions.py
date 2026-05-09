"""Per-entity structural assertions and domain invariant checkers.

Each ``assert_<entity>`` validates the response payload's structure (id format,
timestamp formats, enum membership, type of numeric fields). Tests use these
helpers immediately after ``validate_success(...)`` to confirm the implementer
emitted the field shape PRD §2.4 / §3 promise.

Append-only entities (Bid, Reservation, ExternalEvent, AuditLog) per PRD §2.4
carry only id + created_at — these helpers MUST NOT demand updated_at or
version on those rows.
"""

from typing import Any, Dict, List

import pytest

from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ──────────────────────────────────────────────────────────
# Common-fields helpers
# ──────────────────────────────────────────────────────────


def assert_common_versioned_fields(data: Dict[str, Any]) -> None:
    """For entities with PRD §2.4 common fields: id + created_at + updated_at + version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be UUID v4: {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601: {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601: {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be int >= 1: {data.get('version')!r}"
    )


def assert_append_only_fields(data: Dict[str, Any]) -> None:
    """For PRD §2.4 append-only entities: id + created_at only."""
    assert is_valid_uuid(data.get("id", "")), f"id must be UUID v4: {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601: {data.get('created_at')!r}"


# ──────────────────────────────────────────────────────────
# Per-entity assertions
# ──────────────────────────────────────────────────────────


def assert_seller(data: Dict[str, Any]) -> None:
    assert_common_versioned_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["id_document_number"], str) and data["id_document_number"]
    assert isinstance(data["phone"], str) and data["phone"]
    assert data["kyc_status"] in {"PENDING", "VERIFIED", "REJECTED"}
    assert isinstance(data["total_listings"], int) and data["total_listings"] >= 0


def assert_buyer(data: Dict[str, Any]) -> None:
    assert_common_versioned_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["id_document_number"], str) and data["id_document_number"]
    assert isinstance(data["phone"], str)
    assert isinstance(data["deposit_balance_cents"], int)
    assert isinstance(data["deposit_held_cents"], int)
    assert data["deposit_balance_cents"] >= 0
    assert data["deposit_held_cents"] >= 0
    # PRD §3.1: "the running invariant is that those two fields remain equal at all times".
    assert data["deposit_balance_cents"] == data["deposit_held_cents"], (
        f"PRD §3.1 invariant: deposit_balance_cents ({data['deposit_balance_cents']}) "
        f"must equal deposit_held_cents ({data['deposit_held_cents']})"
    )


def assert_vehicle(data: Dict[str, Any]) -> None:
    assert_common_versioned_fields(data)
    assert isinstance(data["vin"], str) and len(data["vin"]) == 17
    assert isinstance(data["make"], str) and data["make"]
    assert isinstance(data["model"], str) and data["model"]
    assert isinstance(data["model_year"], int)
    assert isinstance(data["declared_mileage_km"], int) and data["declared_mileage_km"] >= 0
    if data.get("verified_mileage_km") is not None:
        assert isinstance(data["verified_mileage_km"], int)
        assert data["verified_mileage_km"] >= 0
    assert isinstance(data["color"], str) and data["color"]
    assert data["vehicle_status"] in {
        "REGISTERED",
        "ASSESSED",
        "LISTED",
        "SOLD",
        "ARCHIVED",
    }
    assert isinstance(data["ownership_seller_id"], str) and data["ownership_seller_id"]
    if data.get("assessment_score") is not None:
        assert isinstance(data["assessment_score"], int)
        assert 0 <= data["assessment_score"] <= 100
    if data.get("valuation_cents") is not None:
        assert isinstance(data["valuation_cents"], int)
        assert data["valuation_cents"] >= 0


def assert_assessment_report(data: Dict[str, Any]) -> None:
    assert_common_versioned_fields(data)
    assert isinstance(data["vehicle_id"], str) and data["vehicle_id"]
    assert isinstance(data["vin_history_records"], list)
    assert isinstance(data["accident_count"], int) and data["accident_count"] >= 0
    assert (
        isinstance(data["major_accident_count"], int)
        and data["major_accident_count"] >= 0
    )
    assert isinstance(data["maintenance_count"], int) and data["maintenance_count"] >= 0
    assert data["status"] in {"DRAFT", "ONSITE_PENDING", "FINALIZED", "SUPERSEDED"}
    assert isinstance(data["mileage_discrepancy_flag"], bool)


def assert_listing(data: Dict[str, Any]) -> None:
    assert_common_versioned_fields(data)
    assert isinstance(data["vehicle_id"], str) and data["vehicle_id"]
    assert isinstance(data["seller_id"], str) and data["seller_id"]
    assert isinstance(data["assessment_report_id"], str) and data["assessment_report_id"]
    assert data["sale_mode"] in {"AUCTION", "FIXED_PRICE"}
    assert isinstance(data["ask_price_cents"], int) and data["ask_price_cents"] > 0
    if data["sale_mode"] == "AUCTION":
        # reserve_price_cents may be null in AUCTION too; PRD says optional.
        if data.get("reserve_price_cents") is not None:
            assert isinstance(data["reserve_price_cents"], int)
    else:
        # PRD §3.2: "required to be null for FIXED_PRICE".
        assert data.get("reserve_price_cents") is None, (
            "PRD §3.2: reserve_price_cents must be null for FIXED_PRICE"
        )
    assert isinstance(data["photo_urls"], list)
    assert isinstance(data["documents_authentic_flag"], bool)
    assert data["doc_check_status"] in {"NOT_RUN", "PASS", "FAIL"}
    assert data["status"] in {
        "DRAFT",
        "UNDER_REVIEW",
        "ACTIVE",
        "RESERVED",
        "SOLD",
        "DELISTED",
        "REJECTED",
    }


def assert_bid(data: Dict[str, Any]) -> None:
    """PRD §2.4: Bid carries only id + created_at — no updated_at, no version."""
    assert_append_only_fields(data)
    assert isinstance(data["listing_id"], str) and data["listing_id"]
    assert isinstance(data["buyer_id"], str) and data["buyer_id"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["deposit_cents"], int) and data["deposit_cents"] > 0
    assert data["status"] in {"LIVE", "OUTBID", "WON", "LOST", "CANCELLED"}
    assert is_iso8601_timestamp(
        data.get("placed_at", "")
    ), f"placed_at must be ISO 8601: {data.get('placed_at')!r}"


def assert_reservation(data: Dict[str, Any]) -> None:
    """PRD §2.4: Reservation carries only id + created_at — no updated_at, no version."""
    assert_append_only_fields(data)
    assert isinstance(data["listing_id"], str) and data["listing_id"]
    assert isinstance(data["buyer_id"], str) and data["buyer_id"]
    assert isinstance(data["queue_position"], int) and data["queue_position"] >= 1
    assert isinstance(data["deposit_cents"], int) and data["deposit_cents"] > 0
    assert data["status"] in {"QUEUED", "HOLDING", "EXPIRED", "CONVERTED", "CANCELLED"}
    if data.get("hold_expires_at") is not None:
        assert is_iso8601_timestamp(data["hold_expires_at"]), (
            f"hold_expires_at must be ISO 8601: {data['hold_expires_at']!r}"
        )


def assert_purchase_order(data: Dict[str, Any]) -> None:
    assert_common_versioned_fields(data)
    assert isinstance(data["listing_id"], str) and data["listing_id"]
    assert isinstance(data["vehicle_id"], str) and data["vehicle_id"]
    assert isinstance(data["seller_id"], str) and data["seller_id"]
    assert isinstance(data["buyer_id"], str) and data["buyer_id"]
    assert isinstance(data["agreed_price_cents"], int) and data["agreed_price_cents"] > 0
    assert data["payment_method"] in {"FULL_PAYMENT", "LOAN"}
    assert data["status"] in {
        "PENDING_PAYMENT",
        "PAID",
        "AWAITING_TRANSFER",
        "COMPLETED",
        "CANCELLED",
        "REFUNDED",
    }
    if data.get("paid_at") is not None:
        assert is_iso8601_timestamp(data["paid_at"])


def assert_transfer_case(data: Dict[str, Any]) -> None:
    assert_common_versioned_fields(data)
    assert isinstance(data["purchase_order_id"], str) and data["purchase_order_id"]
    assert isinstance(data["required_documents"], list)
    assert data["status"] in {
        "DOCS_PENDING",
        "APPOINTMENT_BOOKED",
        "IN_PROGRESS",
        "SUCCEEDED",
        "FAILED",
        "ROLLED_BACK",
    }
    assert data["license_plate_action"] in {"KEEP_OLD", "REASSIGN", "NEW_NUMBER"}


def assert_loan(data: Dict[str, Any]) -> None:
    assert_common_versioned_fields(data)
    assert isinstance(data["purchase_order_id"], str) and data["purchase_order_id"]
    assert isinstance(data["buyer_id"], str) and data["buyer_id"]
    assert data["lender_code"] in {"LENDER_A", "LENDER_B", "LENDER_C"}
    assert isinstance(data["requested_principal_cents"], int)
    assert data["requested_principal_cents"] > 0
    assert isinstance(data["down_payment_ratio_bp"], int)
    assert data["down_payment_ratio_bp"] >= 0
    assert data["term_months"] in {12, 24, 36, 48, 60, 72}
    assert data["status"] in {
        "APPLIED",
        "CREDIT_CHECKING",
        "APPROVED",
        "REJECTED",
        "DISBURSED",
        "CANCELLED",
    }


def assert_warranty(data: Dict[str, Any]) -> None:
    assert_common_versioned_fields(data)
    assert isinstance(data["purchase_order_id"], str) and data["purchase_order_id"]
    assert data["package_code"] in {"BASIC", "STANDARD", "PREMIUM"}
    assert isinstance(data["coverage_scope"], list)
    assert data["status"] in {"PENDING_ACTIVATION", "ACTIVE", "EXPIRED", "VOIDED"}
    assert isinstance(data["claims_count"], int) and data["claims_count"] >= 0
    assert isinstance(data["total_claim_payout_cents"], int)
    assert data["total_claim_payout_cents"] >= 0


def assert_warranty_claim(data: Dict[str, Any]) -> None:
    assert_common_versioned_fields(data)
    assert isinstance(data["warranty_id"], str) and data["warranty_id"]
    assert isinstance(data["component"], str) and data["component"]
    assert isinstance(data["claimed_amount_cents"], int)
    assert data["claimed_amount_cents"] > 0
    assert data["status"] in {"PENDING", "APPROVED", "REJECTED", "PAID"}


def assert_dispute_case(data: Dict[str, Any]) -> None:
    assert_common_versioned_fields(data)
    assert isinstance(data["purchase_order_id"], str) and data["purchase_order_id"]
    assert data["complainant_role"] in {"BUYER", "SELLER"}
    assert isinstance(data["complaint_text"], str)
    assert data["stage"] in {
        "SUBMITTED",
        "EVIDENCE_REVIEW",
        "THIRD_PARTY_INSPECTION",
        "RESOLUTION_PROPOSED",
        "CLOSED",
    }
    assert isinstance(data["round_count"], int) and data["round_count"] >= 0


def assert_external_event(data: Dict[str, Any]) -> None:
    """PRD §2.4: ExternalEvent carries only id + created_at."""
    assert_append_only_fields(data)
    assert data["source"] in {"DMV", "BANK", "INSURANCE", "PAYMENT"}
    assert isinstance(data["event_type"], str)
    assert isinstance(data["idempotency_key"], str) and data["idempotency_key"]
    assert isinstance(data["payload"], dict)


def assert_audit_log(data: Dict[str, Any]) -> None:
    """PRD §2.4: AuditLog carries only id + created_at."""
    assert_append_only_fields(data)
    assert isinstance(data["actor_role"], str)
    assert isinstance(data["actor_id"], str)
    assert isinstance(data["target_entity"], str)
    assert isinstance(data["target_id"], str)
    assert data["event_type"] in {
        "STATE_TRANSITION",
        "OWNERSHIP_CHANGE",
        "FINANCIAL_HOLD",
        "FINANCIAL_RELEASE",
        "EXTERNAL_SYNC",
    }
    assert is_iso8601_timestamp(data["occurred_at"])


# ──────────────────────────────────────────────────────────
# Domain invariant checkers
# ──────────────────────────────────────────────────────────


def assert_buyer_deposit_invariant(buyer: Dict[str, Any]) -> None:
    """PRD §3.1: deposit_held_cents and deposit_balance_cents remain equal at all times.
    PRD §3.7: this is a recomputation as the sum over LIVE bids and HOLDING reservations.
    """
    assert buyer["deposit_balance_cents"] == buyer["deposit_held_cents"]
    assert buyer["deposit_balance_cents"] >= 0


def assert_listing_in_status(listing: Dict[str, Any], expected_status: str) -> None:
    assert listing["status"] == expected_status, (
        f"Expected listing.status == {expected_status!r}, got {listing.get('status')!r}"
    )


def assert_warranty_coverage_matches_package(
    warranty: Dict[str, Any], expected_scope: List[str]
) -> None:
    """PRD §3.8: coverage_scope is determined by package_code."""
    actual = list(warranty.get("coverage_scope", []))
    assert sorted(actual) == sorted(expected_scope), (
        f"PRD §3.8 coverage_scope for {warranty['package_code']} must be "
        f"{expected_scope}, got {actual}"
    )


def assert_required_documents_seeded(transfer: Dict[str, Any]) -> None:
    """PRD §3.7: required_documents seeded with six entries; every item starts
    with submitted false and doc_url null."""
    docs = transfer.get("required_documents", [])
    types_present = {item.get("doc_type") for item in docs}
    expected_types = {
        "ID_BUYER",
        "ID_SELLER",
        "TITLE",
        "REGISTRATION",
        "RELEASE_OF_LIEN",
        "EMISSIONS_CERT",
    }
    assert expected_types.issubset(types_present), (
        f"PRD §3.7 required_documents must seed all six doc_types; got {types_present}"
    )
