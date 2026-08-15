"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §2.8)."""
import pytest
from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)


def assert_money_equal(actual, expected, label="amount"):
    """Money is expressed to exactly two decimal places (PRD §2.8)."""
    assert actual == pytest.approx(expected, abs=0.001), (
        f"{label}: expected {expected}, got {actual}"
    )
    assert_cost_precision(actual)


def assert_weight_equal(actual, expected, label="weight"):
    """Chargeable weight moves in exact 0.5 kg steps (PRD §3.5)."""
    assert actual == pytest.approx(expected, abs=1e-6), (
        f"{label}: expected {expected}, got {actual}"
    )


def _assert_common_fields(data, entity_label):
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_label}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int), f"{entity_label}.version must be an integer"


def assert_shipper(data: dict):
    _assert_common_fields(data, "shipper")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["account_code"], str) and data["account_code"]
    assert data["known_shipper_status"] in ("UNVERIFIED", "KNOWN", "SUSPENDED")
    assert isinstance(data["screening_rejection_count"], int)
    assert data["screening_rejection_count"] >= 0


def assert_flight_booking(data: dict):
    _assert_common_fields(data, "flight_booking")
    assert data["status"] in ("OPEN", "CUTOFF_CLOSED", "DEPARTED", "CANCELLED")
    assert_cost_precision(data["booked_weight_kg"])
    assert data["booked_weight_kg"] > 0
    assert data["booked_volume_m3"] > 0
    assert data["consumed_weight_kg"] >= 0
    assert data["consumed_volume_m3"] >= 0
    assert data["utilization_pct"] >= 0


def assert_master_waybill(data: dict):
    _assert_common_fields(data, "master_waybill")
    assert isinstance(data["mawb_number"], str) and data["mawb_number"]
    assert data["status"] in (
        "DRAFT", "OPEN_FOR_CONSOLIDATION", "TENDERED", "IN_TRANSIT",
        "ARRIVED", "DELIVERED", "CLOSED", "VOID",
    )
    assert data["total_chargeable_weight_kg"] >= 0
    assert data["total_volume_m3"] >= 0
    assert_cost_precision(data["total_freight_amount"])


def assert_house_waybill(data: dict):
    _assert_common_fields(data, "house_waybill")
    assert isinstance(data["hwb_number"], str) and data["hwb_number"]
    assert data["status"] in (
        "DRAFT", "SCREENING", "SCREENING_REJECTED", "CLEARED", "CONSOLIDATED",
        "TENDERED", "IN_TRANSIT", "DELIVERED", "CANCELLED",
    )
    assert data["weight_basis"] in ("UNRATED", "QUOTED", "FINAL")
    assert data["pieces"] > 0
    assert data["gross_weight_kg"] > 0
    assert data["declared_volume_m3"] > 0
    assert data["chargeable_weight_kg"] >= 0
    for field in (
        "freight_amount", "fuel_surcharge_amount", "security_fee_amount",
        "spot_surcharge_amount", "total_charge_amount",
    ):
        assert_cost_precision(data[field])


def assert_screening_record(data: dict):
    _assert_common_fields(data, "screening_record")
    assert data["screening_type"] in ("SECURITY", "DANGEROUS_GOODS")
    assert data["result"] in ("PENDING", "CLEARED", "REJECTED")


def assert_customs_entry(data: dict):
    _assert_common_fields(data, "customs_entry")
    assert data["entry_type"] in ("INFORMAL", "CONSUMPTION", "TRANSIT")
    assert data["status"] in ("PREPARING", "HANDED_OFF", "FILED", "REJECTED", "RELEASED")


def assert_rate_agreement(data: dict):
    _assert_common_fields(data, "rate_agreement")
    assert isinstance(data["weight_breaks"], list) and len(data["weight_breaks"]) >= 1
    assert data["min_charge_amount"] >= 0
    assert data["fuel_surcharge_pct"] >= 0


def assert_milestone_event(data: dict):
    """Append-only audit entry (PRD §2.4): id + created_at, never version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "milestone_event.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "milestone_event.created_at must be ISO 8601"
    )
    assert "version" not in data, "milestone events carry no version field"
    assert "updated_at" not in data, "milestone events carry no updated_at field"
    assert data["event_code"] in ("DEPARTED", "ARRIVED", "DELIVERED", "EXCEPTION")
    assert data["exception_code"] in ("NONE", "DAMAGE", "SHORTAGE", "DELAY", "CUSTOMS_HOLD")
    assert isinstance(data["out_of_order"], bool)


def assert_claim(data: dict):
    _assert_common_fields(data, "claim")
    assert data["claim_type"] in ("DAMAGE", "SHORTAGE", "DELAY", "LOSS")
    assert data["status"] in (
        "FILED", "UNDER_REVIEW", "COUNTERED", "APPROVED", "DENIED", "SETTLED"
    )
    assert data["liability_basis"] in ("STANDARD", "DECLARED_VALUE")
    assert data["claimed_amount"] > 0
    assert_cost_precision(data["liability_limit_amount"])
    assert isinstance(data["review_round_count"], int)
    assert data["review_round_count"] >= 0
