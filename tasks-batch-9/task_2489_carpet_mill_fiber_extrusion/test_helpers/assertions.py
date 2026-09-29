"""Entity assertions and domain invariant checkers for the carpet mill API."""

from typing import Optional

import pytest

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Common system fields
# ---------------------------------------------------------------------------


def assert_common_fields(data: dict) -> None:
    """Every entity except the append-only lab record carries id, created_at,
    updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version starts at 1, got {data['version']}"


def assert_append_only_fields(data: dict) -> None:
    """The append-only lab record carries only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')}"
    assert "updated_at" not in data, "append-only record must not carry updated_at"
    assert "version" not in data, "append-only record must not carry version"


def assert_cents(value, field: str = "cents field") -> None:
    assert isinstance(value, int) and not isinstance(
        value, bool
    ), f"{field} must be an integer number of cents, got {value!r}"


def assert_rounded(value, places: int, field: str = "value") -> None:
    """The PRD rounds each published figure to a fixed number of decimals."""
    assert isinstance(value, (int, float)), f"{field} must be numeric, got {value!r}"
    assert round(float(value), places) == pytest.approx(
        float(value), abs=1e-9
    ), f"{field} must be rounded to {places} decimals, got {value}"


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------


def assert_account(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["account_code"], str) and data["account_code"]
    assert data["account_type"] in ("DEALER", "BUILDER", "COMMERCIAL")
    assert_cents(data["credit_limit_cents"], "credit_limit_cents")
    assert_cents(data["credit_used_cents"], "credit_used_cents")
    assert data["credit_used_cents"] >= 0, "credit_used_cents must never go negative"
    assert data["status"] in ("ACTIVE", "CREDIT_HOLD", "CLOSED")


def assert_polymer_lot(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["lot_code"], str) and data["lot_code"]
    assert data["polymer_type"] in ("NYLON_6", "NYLON_66", "PET", "POLYPROPYLENE")
    assert data["reclaim_source"] in ("VIRGIN", "POST_CONSUMER", "POST_INDUSTRIAL")
    assert isinstance(data["segregated"], bool)
    assert data["status"] in ("AVAILABLE", "DEPLETED")
    for field in (
        "received_kg",
        "available_kg",
        "reserved_kg",
        "consumed_kg",
        "scrapped_kg",
        "recycled_content_pct",
        "melt_flow_index",
    ):
        assert isinstance(data[field], (int, float)), f"{field} must be numeric"
        assert data[field] >= 0, f"{field} must be non-negative, got {data[field]}"
    assert_polymer_mass_conservation(data)


def assert_polymer_mass_conservation(data: dict) -> None:
    """received_kg equals available_kg + reserved_kg + consumed_kg + scrapped_kg."""
    total = (
        data["available_kg"]
        + data["reserved_kg"]
        + data["consumed_kg"]
        + data["scrapped_kg"]
    )
    assert total == pytest.approx(data["received_kg"], abs=0.001), (
        "polymer mass must be conserved: received_kg "
        f"{data['received_kg']} != available {data['available_kg']} + reserved "
        f"{data['reserved_kg']} + consumed {data['consumed_kg']} + scrapped "
        f"{data['scrapped_kg']} (sum {total})"
    )
    expected_status = "DEPLETED" if data["available_kg"] == 0 else "AVAILABLE"
    assert data["status"] == expected_status, (
        f"status must be {expected_status} when available_kg is "
        f"{data['available_kg']}, got {data['status']}"
    )


def assert_reclamation_batch(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["batch_code"], str) and data["batch_code"]
    assert data["face_fiber_type"] in ("NYLON_6", "NYLON_66", "PET", "POLYPROPYLENE")
    assert data["status"] in ("RECEIVED", "DEPOLYMERIZED")
    assert data["intake_lbs"] > 0
    assert data["contamination_pct"] >= 0
    assert data["depolymerized_kg"] >= 0


def assert_fiber_batch(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["batch_code"], str) and data["batch_code"]
    assert is_valid_uuid(data["polymer_lot_id"])
    assert data["dye_method"] in ("SOLUTION_DYED", "PIECE_DYED_READY")
    assert data["status"] in (
        "QUEUED",
        "SPUN",
        "RELEASED",
        "ALLOCATED",
        "CONSUMED",
        "SCRAPPED",
    )
    assert data["input_kg"] > 0
    assert data["denier_target"] > 0
    assert isinstance(data["filament_count"], int) and data["filament_count"] > 0
    if data.get("denier_actual") is not None:
        assert_rounded(data["denier_actual"], 1, "denier_actual")


def assert_style(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["style_code"], str) and data["style_code"]
    assert data["line_type"] in ("RUNNING_LINE", "CUSTOM")
    assert data["gauge_code"] in ("G_1_8", "G_1_10", "G_5_64")
    assert data["pile_construction"] in ("CUT", "LOOP")
    assert data["dye_method"] in ("SOLUTION_DYED", "PIECE_DYED")
    assert data["replenishment_flag"] in ("NONE", "REPLENISH_REQUIRED")
    assert data["status"] in (
        "DRAFT",
        "ACTIVE",
        "SUSPENDED",
        "RUNOUT",
        "DISCONTINUED",
    )
    assert_cents(data["list_price_cents_per_yard"], "list_price_cents_per_yard")
    assert isinstance(data["plies"], int) and data["plies"] > 0
    assert data["open_backorder_yards"] >= 0


def assert_tufting_machine(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["machine_code"], str) and data["machine_code"]
    assert data["native_gauge_code"] in ("G_1_8", "G_1_10", "G_5_64")
    assert data["status"] in ("IDLE", "MAINTENANCE")
    assert data["min_pile_height_mm"] <= data["max_pile_height_mm"]
    assert isinstance(data["changeover_minutes"], int)
    assert data["changeover_minutes"] >= 0


def assert_dye_vessel(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["vessel_code"], str) and data["vessel_code"]
    assert data["vessel_type"] in ("BECK", "JET")
    assert data["status"] in ("AVAILABLE", "MAINTENANCE")
    assert data["capacity_kg"] > 0


def assert_production_run(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["run_code"], str) and data["run_code"]
    assert is_valid_uuid(data["style_id"])
    assert is_valid_uuid(data["machine_id"])
    assert is_valid_uuid(data["fiber_batch_id"])
    assert is_iso8601_timestamp(data["scheduled_start_utc"])
    assert is_iso8601_timestamp(data["scheduled_end_utc"])
    assert data["status"] in (
        "SCHEDULED",
        "HELD",
        "TUFTING",
        "GREIGE",
        "BACKED",
        "BACKING_FAILED",
        "RELEASED",
        "ABORTED",
    )
    assert isinstance(data["recoat_count"], int) and data["recoat_count"] >= 0
    if data.get("gauge_loaded_code") is not None:
        assert data["gauge_loaded_code"] in ("G_1_8", "G_1_10", "G_5_64")
    if data.get("secondary_backing_type") is not None:
        assert data["secondary_backing_type"] in (
            "ACTION_BAC",
            "WOVEN_POLYPROPYLENE",
            "CUSHION",
        )
    if data.get("face_weight_oz_per_sy") is not None:
        assert_rounded(data["face_weight_oz_per_sy"], 2, "face_weight_oz_per_sy")
    if data.get("delamination_strength_lbf") is not None:
        assert_rounded(
            data["delamination_strength_lbf"], 2, "delamination_strength_lbf"
        )


def assert_dye_lot(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["lot_code"], str) and data["lot_code"]
    assert is_valid_uuid(data["production_run_id"])
    assert is_valid_uuid(data["vessel_id"])
    assert data["status"] in (
        "FORMULATED",
        "DYEING",
        "MEASURED",
        "APPROVED",
        "REDYE_QUEUED",
        "EXHAUSTED",
        "REJECTED",
    )
    if data.get("shade_band") is not None:
        assert data["shade_band"] in ("A", "B", "C", "OUT")
    if data.get("delta_e") is not None:
        assert_rounded(data["delta_e"], 2, "delta_e")
        assert data["delta_e"] >= 0
    assert isinstance(data["redye_count"], int) and data["redye_count"] >= 0
    assert data["lot_kg"] > 0
    assert data["dyed_yards"] >= 0
    assert data["scrapped_yards"] >= 0
    assert data["uncommitted_yards"] >= 0
    assert data["shipped_basis_uncommitted_yards"] >= 0


def assert_roll_good(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["roll_number"], str) and data["roll_number"]
    assert is_valid_uuid(data["production_run_id"])
    assert data["shade_band"] in ("A", "B", "C", "SOLUTION")
    assert isinstance(data["is_remnant"], bool)
    assert data["qa_status"] in ("PENDING", "PASSED", "HELD", "FAILED")
    assert data["inventory_status"] in (
        "IN_PROCESS",
        "AVAILABLE",
        "COMMITTED",
        "DEPLETED",
        "SCRAPPED",
    )
    assert data["initial_yards"] > 0
    assert (
        0 <= data["available_yards"] <= data["initial_yards"]
    ), f"available_yards {data['available_yards']} must lie within initial_yards {data['initial_yards']}"


def assert_product_test(data: dict) -> None:
    assert_append_only_fields(data)
    assert is_valid_uuid(data["style_id"])
    assert is_valid_uuid(data["roll_good_id"])
    assert data["test_type"] in ("WEAR_TARR", "STAIN_AATCC175", "FLAMMABILITY_PILL")
    assert data["verdict"] in ("PASS", "FAIL")
    assert isinstance(data["tested_by_user_id"], str) and data["tested_by_user_id"]
    assert is_iso8601_timestamp(data["tested_at_utc"])


def assert_certification(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["style_id"])
    assert data["cert_type"] in ("DOC_FF_1_70", "NSF_140", "GREEN_LABEL_PLUS")
    assert data["accounting_basis"] in (
        "MASS_BALANCE",
        "PHYSICAL_SEGREGATION",
        "NOT_APPLICABLE",
    )
    assert isinstance(data["source_test_ids"], list) and data["source_test_ids"]
    assert isinstance(data["certified_by_user_id"], str) and data["certified_by_user_id"]
    assert is_iso8601_timestamp(data["issued_at_utc"])
    assert is_iso8601_timestamp(data["expires_at_utc"])
    assert data["status"] in ("ACTIVE", "LAPSED", "REVOKED", "SUPERSEDED")


def assert_cut_order(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["order_code"], str) and data["order_code"]
    assert is_valid_uuid(data["account_id"])
    assert is_valid_uuid(data["style_id"])
    assert data["order_type"] in ("RUNNING_LINE", "CUSTOM")
    assert data["shade_tolerance"] in ("SINGLE_LOT", "BAND_MATCH", "ANY")
    assert data["status"] in (
        "SUBMITTED",
        "ALLOCATED",
        "BACKORDERED",
        "CUT",
        "SHIPPED",
        "CANCELLED",
    )
    for field in (
        "reserved_credit_cents",
        "gross_cents",
        "freight_cents",
        "remnant_credit_cents",
        "net_invoice_cents",
    ):
        assert_cents(data[field], field)
        assert data[field] >= 0, f"{field} must be non-negative, got {data[field]}"
    assert data["requested_yards"] > 0
    assert data["allocated_yards"] >= 0


def assert_cut_allocation(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["cut_order_id"])
    assert is_valid_uuid(data["roll_good_id"])
    assert data["shade_band"] in ("A", "B", "C", "SOLUTION")
    assert isinstance(data["from_remnant"], bool)
    assert_cents(data["line_cents"], "line_cents")
    assert data["status"] in ("RESERVED", "CUT", "SHIPPED", "RELEASED", "VOIDED")
    assert data["yards"] > 0


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------


def assert_roll_good_yardage_conservation(roll: dict, allocations) -> None:
    """A roll's available_yards is its initial_yards less every yard reserved,
    cut or shipped against it."""
    committed = sum(
        a["yards"] for a in allocations if a["status"] in ("RESERVED", "CUT", "SHIPPED")
    )
    assert roll["available_yards"] == pytest.approx(
        roll["initial_yards"] - committed, abs=0.01
    ), (
        f"roll {roll.get('roll_number')} available_yards {roll['available_yards']} "
        f"should equal initial_yards {roll['initial_yards']} minus committed "
        f"{committed}"
    )


def assert_account_credit_conservation(account: dict, orders) -> None:
    """credit_used_cents equals the reserved credit of the account's orders that
    are still working, plus the invoiced amount of its shipped orders."""
    exposure = sum(
        o["reserved_credit_cents"]
        for o in orders
        if o["status"] in ("SUBMITTED", "ALLOCATED", "BACKORDERED", "CUT")
    ) + sum(o["net_invoice_cents"] for o in orders if o["status"] == "SHIPPED")
    assert account["credit_used_cents"] == exposure, (
        f"credit_used_cents {account['credit_used_cents']} should equal the "
        f"ledger total {exposure} over the account's orders"
    )


def assert_credit_hold_posture(account: dict) -> None:
    """An open account sits on CREDIT_HOLD exactly while its used credit has
    reached its limit."""
    if account["status"] == "CLOSED":
        return
    expected = (
        "CREDIT_HOLD"
        if account["credit_used_cents"] >= account["credit_limit_cents"]
        else "ACTIVE"
    )
    assert account["status"] == expected, (
        f"status should be {expected} with credit_used_cents "
        f"{account['credit_used_cents']} against limit "
        f"{account['credit_limit_cents']}, got {account['status']}"
    )


def assert_shade_band_for_delta_e(dye_lot: dict) -> None:
    """The band follows from the rounded delta_e at 0.80 / 1.50 / 2.50."""
    delta_e = dye_lot["delta_e"]
    if delta_e <= 0.80:
        expected = "A"
    elif delta_e <= 1.50:
        expected = "B"
    elif delta_e <= 2.50:
        expected = "C"
    else:
        expected = "OUT"
    assert dye_lot["shade_band"] == expected, (
        f"delta_e {delta_e} must map to shade_band {expected}, got "
        f"{dye_lot['shade_band']}"
    )


def assert_remnant_posture(roll: dict) -> None:
    """is_remnant is derived, not supplied: it is true exactly when
    parent_roll_id is not null."""
    expected = roll.get("parent_roll_id") is not None
    assert roll["is_remnant"] == expected, (
        f"is_remnant should be {expected} with parent_roll_id "
        f"{roll.get('parent_roll_id')!r}, got {roll['is_remnant']}"
    )


def assert_net_invoice(order: dict) -> None:
    """net_invoice_cents is gross plus freight less the remnant credit."""
    expected = (
        order["gross_cents"] + order["freight_cents"] - order["remnant_credit_cents"]
    )
    assert order["net_invoice_cents"] == expected, (
        f"net_invoice_cents {order['net_invoice_cents']} should equal gross "
        f"{order['gross_cents']} + freight {order['freight_cents']} - remnant "
        f"credit {order['remnant_credit_cents']} = {expected}"
    )


def assert_version_unchanged(before: dict, after: dict, label: str = "entity") -> None:
    assert before["version"] == after["version"], (
        f"{label} version must not move on a rejected write: was "
        f"{before['version']}, now {after['version']}"
    )


def assert_field_unchanged(
    before: dict, after: dict, field: str, label: Optional[str] = None
) -> None:
    assert before[field] == after[field], (
        f"{label or 'entity'}.{field} must be unchanged: was {before[field]}, "
        f"now {after[field]}"
    )
