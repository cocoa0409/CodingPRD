"""Entity assertions and domain invariant checkers (PRD §2.4, §2.6).

Timestamp comparisons parse to instants instead of comparing strings: the PRD
pins the three-fractional-digit rendering only for created_at/updated_at, so
computed instants (cure_eligible_at, delivered_at, ...) are compared by value.
"""
from datetime import datetime, timezone

import pytest
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp, tolerating optional fractional digits."""
    assert isinstance(value, str), f"Expected timestamp string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def assert_instant_equal(actual: str, expected_iso: str, label: str = "instant"):
    """Two ISO 8601 timestamps denote the same instant, regardless of rendering."""
    actual_dt = parse_instant(actual)
    expected_dt = parse_instant(expected_iso)
    assert actual_dt == expected_dt, (
        f"{label}: expected instant {expected_iso}, got {actual}"
    )


def assert_common_fields(data: dict):
    """Fields every versioned resource carries (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_retailer(data: dict):
    assert_common_fields(data)
    assert isinstance(data["retailer_name"], str) and data["retailer_name"]
    assert isinstance(data["drop_ship_enabled"], bool)
    assert isinstance(data["recycling_enrolled"], bool)
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["credit_balance_cents"], int)


def assert_credit_adjustment(data: dict):
    # Append-only ledger entry: id + created_at only (PRD §2.4)
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert "version" not in data, "ledger entries must not carry a version"
    assert "updated_at" not in data, "ledger entries must not carry updated_at"
    assert isinstance(data["retailer_id"], str)
    assert isinstance(data["amount_cents"], int)
    assert data["source"] in [
        "MANUAL", "WARRANTY_PAYOUT", "RECYCLING_PROVISIONAL",
        "RECYCLING_FINAL_DELTA", "EXCHANGE_RECOVERY",
    ]


def assert_model(data: dict):
    assert_common_fields(data)
    assert isinstance(data["model_code"], str) and data["model_code"]
    assert isinstance(data["quilt_pattern"], str) and data["quilt_pattern"]
    assert isinstance(data["bom_cost_cents"], int)
    assert data["status"] in [
        "DRAFT", "CERT_REVIEW", "CERTIFIED", "ACTIVE", "DISCONTINUED",
    ]


def assert_bom_line(data: dict):
    assert_common_fields(data)
    assert data["component_type"] in [
        "FOAM_CORE", "MEMORY_LAYER", "FIRE_BARRIER", "TICKING",
        "QUILT_PANEL", "FOUNDATION", "THREAD",
    ]
    assert isinstance(data["material_code"], str)
    assert data["quantity_per_unit"] > 0
    assert isinstance(data["unit_cost_cents"], int) and data["unit_cost_cents"] >= 0
    assert isinstance(data["line_cost_cents"], int)


def assert_certificate(data: dict):
    assert_common_fields(data)
    assert data["cert_type"] in ["FLAMMABILITY_16CFR1633", "PROP65_CA", "TB117"]
    assert isinstance(data["jurisdiction_state_code"], str)
    assert data["status"] in ["SUBMITTED", "APPROVED", "REVOKED", "EXPIRED"]


def assert_spec(data: dict):
    assert_common_fields(data)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["filling_content_codes"], list)
    assert isinstance(data["required_phrases"], list)
    assert isinstance(data["prop65_warning_required"], bool)
    assert data["status"] in ["DRAFT", "PUBLISHED", "SUPERSEDED"]


def assert_law_label(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("model_id", ""))
    assert is_valid_uuid(data.get("spec_id", ""))
    assert isinstance(data["spec_version"], int)
    assert isinstance(data["state_code"], str)
    assert isinstance(data["content_text"], str)
    assert data["status"] in ["GENERATED", "APPROVED", "ACTIVE", "SUPERSEDED", "REJECTED"]


def assert_foam_batch(data: dict):
    assert_common_fields(data)
    assert data["foam_density_class"] in ["STANDARD", "HIGH_DENSITY", "MEMORY"]
    assert data["poured_mass_kg"] > 0
    for field in ("available_mass_kg", "reserved_mass_kg",
                  "consumed_mass_kg", "scrapped_mass_kg"):
        assert isinstance(data[field], (int, float)), f"{field} must be numeric"
    assert isinstance(data["cure_cycles"], int)
    assert data["status"] in [
        "POURED", "CURING", "CURED", "QUARANTINED", "CONSUMED", "SCRAPPED",
    ]


def assert_quilt_run(data: dict):
    assert_common_fields(data)
    assert data["size"] in ["TWIN", "FULL", "QUEEN", "KING", "CAL_KING"]
    assert isinstance(data["machine_id"], str)
    assert data["status"] in ["SCHEDULED", "RUNNING", "COMPLETE", "CANCELLED"]


def assert_production_order(data: dict):
    assert_common_fields(data)
    assert data["production_status"] in [
        "PLANNED", "MATERIAL_ALLOCATED", "IN_PRODUCTION",
        "QC_PENDING", "QC_HOLD", "COMPLETE", "CANCELLED",
    ]
    assert data["fulfillment_status"] in [
        "UNFULFILLED", "PARTIALLY_SHIPPED", "FULLY_SHIPPED", "DELIVERED",
    ]
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["compliance_fee_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert data["ship_method"] in ["WAREHOUSE", "DROP_SHIP"]


def assert_unit(data: dict):
    assert_common_fields(data)
    assert data["status"] in [
        "MANUFACTURED", "SHIPPED", "DELIVERED", "RETURNED", "RECOVERED", "SCRAPPED",
    ]
    assert isinstance(data["purchase_price_cents"], int)


def assert_shipment(data: dict):
    assert_common_fields(data)
    assert isinstance(data["unit_ids"], list)
    assert data["status"] in ["CREATED", "DISPATCHED", "DELIVERED"]


def assert_return_request(data: dict):
    assert_common_fields(data)
    assert data["reason"] in ["COMFORT_EXCHANGE", "DEFECT"]
    assert data["status"] in [
        "REQUESTED", "RECEIVED", "INSPECTED",
        "RESOLVED_EXCHANGE", "RESOLVED_RECYCLED", "REJECTED",
    ]


def assert_warranty_claim(data: dict):
    assert_common_fields(data)
    assert data["claim_type"] in ["SAG_DEFECT", "WORKMANSHIP"]
    assert data["status"] in ["FILED", "APPROVED", "PAID", "DENIED"]


def assert_recycling_intake(data: dict):
    assert_common_fields(data)
    assert data["declared_weight_kg"] > 0
    assert isinstance(data["provisional_credit_cents"], int)
    assert data["status"] in ["RECEIVED", "FINALIZED"]


def assert_foam_mass_conservation(batch: dict):
    """PRD §2.6 mass invariant: poured == available + reserved + consumed + scrapped."""
    total = (
        batch["available_mass_kg"]
        + batch["reserved_mass_kg"]
        + batch["consumed_mass_kg"]
        + batch["scrapped_mass_kg"]
    )
    assert total == pytest.approx(batch["poured_mass_kg"]), (
        f"Mass conservation violated: {batch['poured_mass_kg']} poured vs "
        f"{batch['available_mass_kg']} available + {batch['reserved_mass_kg']} reserved "
        f"+ {batch['consumed_mass_kg']} consumed + {batch['scrapped_mass_kg']} scrapped"
    )
