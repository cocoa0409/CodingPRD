"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


# ---------------------------------------------------------------------------
# Common-field helpers
# ---------------------------------------------------------------------------

def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an int >= 1, got {data.get('version')!r}"
    )


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------

def assert_zone(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["zone_code"], str)
    assert isinstance(data["bond_coverage_cents"], int) and data["bond_coverage_cents"] >= 0
    assert data["status"] in ("ACTIVE", "SUSPENDED", "DEACTIVATED")
    assert data["compliance_posture"] in ("NORMAL", "AUDIT_HOLD")
    assert isinstance(data["deferred_duty_exposure_cents"], int)
    assert isinstance(data["active_lot_count"], int) and data["active_lot_count"] >= 0


def assert_admission(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("zone_id", "")), "zone_id must be a valid UUID"
    assert isinstance(data["importer_ref"], str) and len(data["importer_ref"]) > 0
    assert isinstance(data["description"], str)
    assert isinstance(data["hts_code"], str)
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["unit_value_cents"], int) and data["unit_value_cents"] >= 0
    assert data["zone_status"] in (
        "PRIVILEGED_FOREIGN", "NON_PRIVILEGED_FOREIGN", "DOMESTIC", "ZONE_RESTRICTED",
    )
    if data.get("admission_date") is not None:
        assert is_iso8601_timestamp(data["admission_date"]), "admission_date must be ISO 8601"
    assert data["status"] in ("DRAFT", "SUBMITTED", "ADMITTED", "CANCELLED")


def assert_inventory_lot(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("zone_id", "")), "zone_id must be a valid UUID"
    assert data.get("admission_id") is None or is_valid_uuid(data["admission_id"])
    assert data.get("source_manipulation_id") is None or is_valid_uuid(data["source_manipulation_id"])
    assert isinstance(data["importer_ref"], str) and len(data["importer_ref"]) > 0
    assert isinstance(data["hts_code"], str)
    assert data["zone_status"] in (
        "PRIVILEGED_FOREIGN", "NON_PRIVILEGED_FOREIGN", "DOMESTIC", "ZONE_RESTRICTED",
    )
    assert isinstance(data["admitted_quantity"], int) and data["admitted_quantity"] >= 1
    assert isinstance(data["quantity_on_hand"], int) and data["quantity_on_hand"] >= 0
    assert isinstance(data["reserved_quantity"], int) and data["reserved_quantity"] >= 0
    assert isinstance(data["cumulative_withdrawn"], int) and data["cumulative_withdrawn"] >= 0
    assert isinstance(data["cumulative_consumed"], int) and data["cumulative_consumed"] >= 0
    assert isinstance(data["unit_value_cents"], int) and data["unit_value_cents"] >= 0
    assert isinstance(data["duty_rate"], (int, float)) and data["duty_rate"] >= 0
    assert data["status"] in ("IN_ZONE", "DEPLETED")


def assert_manipulation_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("zone_id", "")), "zone_id must be a valid UUID"
    assert isinstance(data["importer_ref"], str) and len(data["importer_ref"]) > 0
    assert is_valid_uuid(data.get("source_lot_id", "")), "source_lot_id must be a valid UUID"
    assert isinstance(data["input_quantity"], int) and data["input_quantity"] >= 1
    assert isinstance(data["output_hts_code"], str)
    assert isinstance(data["output_quantity"], int) and data["output_quantity"] >= 1
    assert isinstance(data["value_added_cents"], int) and data["value_added_cents"] >= 0
    assert isinstance(data["output_description"], str)
    assert data.get("output_lot_id") is None or is_valid_uuid(data["output_lot_id"])
    assert data["status"] in ("REQUESTED", "APPROVED", "COMPLETED", "REJECTED", "CANCELLED")


def assert_withdrawal(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("zone_id", "")), "zone_id must be a valid UUID"
    assert isinstance(data["importer_ref"], str) and len(data["importer_ref"]) > 0
    assert is_valid_uuid(data.get("lot_id", "")), "lot_id must be a valid UUID"
    assert data.get("weekly_entry_id") is None or is_valid_uuid(data["weekly_entry_id"])
    assert data["withdrawal_type"] in ("CONSUMPTION", "EXPORT")
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["estimated_duty_cents"], int) and data["estimated_duty_cents"] >= 0
    assert data.get("assessed_duty_cents") is None or isinstance(data["assessed_duty_cents"], int)
    if data.get("withdrawal_date") is not None:
        assert is_iso8601_timestamp(data["withdrawal_date"]), "withdrawal_date must be ISO 8601"
    assert data["duty_outcome"] in ("PENDING", "COLLECTED", "EXTINGUISHED", "NONE")
    assert data["status"] in ("DRAFT", "FILED", "DUTY_PAID", "EXPORTED", "CANCELLED")


def assert_weekly_entry(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("zone_id", "")), "zone_id must be a valid UUID"
    assert isinstance(data["importer_ref"], str) and len(data["importer_ref"]) > 0
    assert is_iso8601_timestamp(data["week_start_date"]), "week_start_date must be ISO 8601"
    assert is_iso8601_timestamp(data["week_end_date"]), "week_end_date must be ISO 8601"
    for field in (
        "entered_value_cents", "duty_total_cents", "mpf_uncapped_cents",
        "mpf_cents", "per_shipment_mpf_cents", "mpf_savings_cents",
    ):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"{field} must be a non-negative int, got {data.get(field)!r}"
        )
    assert data["status"] in ("OPEN", "FILED", "ACCEPTED", "FROZEN")


def assert_annual_reconciliation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("zone_id", "")), "zone_id must be a valid UUID"
    assert isinstance(data["zone_year"], int)
    assert isinstance(data["beginning_value_cents"], int) and data["beginning_value_cents"] >= 0
    assert isinstance(data["physical_ending_value_cents"], int) and data["physical_ending_value_cents"] >= 0
    # Computed figures are null until SUBMITTED.
    for field in (
        "book_receipts_value_cents", "book_withdrawals_value_cents",
        "book_ending_value_cents", "discrepancy_cents",
    ):
        assert data.get(field) is None or isinstance(data[field], int), (
            f"{field} must be null or int, got {data.get(field)!r}"
        )
    assert data.get("discrepancy_pct") is None or isinstance(data["discrepancy_pct"], (int, float))
    assert data.get("audit_flagged") is None or isinstance(data["audit_flagged"], bool)
    assert data["status"] in ("DRAFT", "SUBMITTED", "ACCEPTED", "SUPERSEDED")


def assert_access_badge(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("zone_id", "")), "zone_id must be a valid UUID"
    assert isinstance(data["holder_name"], str) and len(data["holder_name"]) > 0
    assert is_iso8601_timestamp(data["valid_from"]), "valid_from must be ISO 8601"
    assert is_iso8601_timestamp(data["valid_until"]), "valid_until must be ISO 8601"
    assert data["status"] in ("ACTIVE", "SUSPENDED", "REVOKED")


def assert_zone_access_event(data: dict):
    # Append-only audit record: id + created_at only — updated_at / version absent.
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only event must not carry updated_at"
    assert "version" not in data, "append-only event must not carry version"
    assert is_valid_uuid(data.get("zone_id", "")), "zone_id must be a valid UUID"
    assert is_valid_uuid(data.get("badge_id", "")), "badge_id must be a valid UUID"
    assert data["direction"] in ("IN", "OUT")
    assert is_iso8601_timestamp(data["occurred_at"]), "occurred_at must be ISO 8601"


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------

def assert_lot_quantity_invariant(lot: dict):
    """admitted_quantity == quantity_on_hand + cumulative_withdrawn + cumulative_consumed."""
    assert (
        lot["admitted_quantity"]
        == lot["quantity_on_hand"] + lot["cumulative_withdrawn"] + lot["cumulative_consumed"]
    ), (
        f"lot unit conservation violated: admitted {lot['admitted_quantity']} != "
        f"on_hand {lot['quantity_on_hand']} + withdrawn {lot['cumulative_withdrawn']} + "
        f"consumed {lot['cumulative_consumed']}"
    )
