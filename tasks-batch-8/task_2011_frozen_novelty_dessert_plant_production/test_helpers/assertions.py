"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from datetime import datetime

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, mutable: bool = True):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    if mutable:
        assert is_iso8601_timestamp(data.get("updated_at", "")), \
            "updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int) and data["version"] >= 1, \
            "version must be an integer >= 1"


def assert_product(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["sku_code"], str) and data["sku_code"]
    assert data["format"] in ("NOVELTY", "BULK")
    assert data["flavor_family"] in (
        "VANILLA", "CHOCOLATE", "FRUIT", "CARAMEL", "NUT_BAKERY", "COFFEE")
    assert isinstance(data["allergens"], list)
    assert data["status"] in ("ACTIVE", "DISCONTINUED")


def assert_customer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["customer_code"], str) and data["customer_code"]
    assert data["kind"] in ("PRIVATE_LABEL", "DISTRIBUTOR")


def assert_contract(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["contract_code"], str) and data["contract_code"]
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "APPROVED", "ACTIVE", "FULFILLED", "CANCELED")


def assert_mix_batch(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["batch_code"], str) and data["batch_code"]
    assert data["status"] in (
        "PLANNED", "PASTEURIZED", "RELEASED", "CONSUMED", "REJECTED", "EXPIRED")


def assert_line(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["line_code"], str) and data["line_code"]
    assert data["format"] in ("NOVELTY", "BULK")
    assert data["status"] in ("IDLE", "CLEANING", "RUNNING")


def assert_changeover(data: dict):
    _assert_common_fields(data)
    assert data["required_clean_level"] in ("RINSE", "WASH", "ALLERGEN_CIP")
    assert data["status"] in (
        "REQUIRED", "AWAITING_VERIFICATION", "VERIFIED", "CONSUMED")


def assert_production_run(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["run_code"], str) and data["run_code"]
    assert data["status"] in (
        "SCHEDULED", "MIX_ASSIGNED", "IN_PRODUCTION", "ON_HOLD",
        "COMPLETED", "CANCELED")


def assert_tunnel(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["tunnel_code"], str) and data["tunnel_code"]


def assert_tunnel_booking(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("BOOKED", "COMPLETED", "CANCELED", "EXPIRED")


def assert_freezer_zone(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["zone_code"], str) and data["zone_code"]
    assert isinstance(data["pallet_capacity"], int)


def assert_inventory_lot(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["lot_code"], str) and data["lot_code"]
    assert data["status"] in ("AVAILABLE", "QUARANTINED", "DESTROYED", "EXPIRED")


def assert_shipment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["shipment_code"], str) and data["shipment_code"]
    assert data["status"] in (
        "PLANNED", "LOADED", "IN_TRANSIT", "DELIVERED", "REJECTED")


def assert_allocation(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "RELEASED", "FULFILLED")


def assert_temp_reading(data: dict):
    # Append-only entity: only id and created_at are system fields (PRD §2.4).
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert "updated_at" not in data, "TempReading must not carry updated_at"
    assert "version" not in data, "TempReading must not carry version"
    assert "temp_c" in data and "recorded_at" in data


def assert_claim(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["claim_code"], str) and data["claim_code"]
    assert data["status"] in (
        "SUBMITTED", "EVIDENCE_REVIEW", "APPROVED", "PAID", "DENIED",
        "APPEALED", "WITHDRAWN")


def assert_complaint(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["complaint_code"], str) and data["complaint_code"]
    assert data["status"] in (
        "UNDER_REVIEW", "LAB_TEST", "DISPOSITIONED_SUBSTANTIATED",
        "CLOSED_UNFOUNDED", "WITHDRAWN")


def assert_build_plan(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["plan_code"], str) and data["plan_code"]
    assert data["status"] in ("DRAFT", "APPROVED", "CANCELED")


def assert_lot_units_conservation(lot: dict):
    """PRD §3.7: the four unit buckets always sum to units_produced."""
    total = (lot["units_available"] + lot["units_reserved"]
             + lot["units_shipped"] + lot["units_destroyed"])
    assert total == lot["units_produced"], (
        f"lot units not conserved: "
        f"{lot['units_available']}+{lot['units_reserved']}+"
        f"{lot['units_shipped']}+{lot['units_destroyed']} != "
        f"{lot['units_produced']}")


def assert_mix_litres_conservation(batch: dict):
    """PRD §3.3: consumed + wasted + remaining always equals litres_produced."""
    total = (batch["litres_consumed"] + batch["litres_wasted"]
             + batch["litres_remaining"])
    assert abs(total - batch["litres_produced"]) < 0.005, (
        f"mix litres not conserved: {batch['litres_consumed']}+"
        f"{batch['litres_wasted']}+{batch['litres_remaining']} != "
        f"{batch['litres_produced']}")


def parse_iso8601(value: str) -> datetime:
    """Parse an ISO 8601 timestamp ending in Z into a datetime."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
