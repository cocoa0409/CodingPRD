"""Entity assertions and domain invariant checkers for the mill API."""

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import WARRANTY_RESTRICT_FLOOR_CENTS


# ---------------------------------------------------------------------------
# Shared field discipline
# ---------------------------------------------------------------------------


def assert_identity_fields(data: dict) -> None:
    """Every stored resource carries a server-minted UUID ``id`` with no type
    prefix and a ``created_at`` in ISO 8601 UTC with three fractional digits."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a canonical UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"


def assert_versioned_fields(data: dict, expected_version=None) -> None:
    """Most resources also carry ``updated_at`` and an integer ``version``."""
    assert_identity_fields(data)
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    if expected_version is not None:
        assert data["version"] == expected_version, (
            f"Expected version {expected_version}, got {data['version']}"
        )


def assert_no_revision_counter(data: dict) -> None:
    """An immutable tally line has no ``updated_at`` field and no ``version``
    field at all, and neither appears in its representation."""
    assert "updated_at" not in data, "an immutable tally line must not carry updated_at"
    assert "version" not in data, "an immutable tally line must not carry version"


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------


def assert_species_profile(data: dict) -> None:
    assert_versioned_fields(data)
    assert isinstance(data["species_code"], str) and data["species_code"]
    assert isinstance(data["common_name"], str) and data["common_name"]
    assert data["density_class"] in ("DENSE", "MEDIUM", "SOFT")
    assert data["tangential_shrinkage_coefficient"] >= 0
    assert data["target_moisture_pct"] >= 0
    assert data["max_moisture_gradient_pp"] >= 0
    assert data["green_to_dry_shrink_pct"] in (7.5, 6.0, 5.0)


def assert_drying_schedule(data: dict) -> None:
    assert_versioned_fields(data)
    assert isinstance(data["schedule_code"], str) and data["schedule_code"]
    assert is_valid_uuid(data["species_profile_id"])
    assert data["thickness_in"] > 0
    assert 48.0 <= data["planned_dry_hours"] <= 360.0, (
        f"planned_dry_hours must be clamped into 48 to 360, got {data['planned_dry_hours']}"
    )


def assert_kiln_chamber(data: dict) -> None:
    assert_versioned_fields(data)
    assert isinstance(data["chamber_code"], str) and data["chamber_code"]
    assert isinstance(data["capacity_board_feet"], int)
    assert data["status"] in ("AVAILABLE", "OCCUPIED", "MAINTENANCE")


def assert_green_receipt(data: dict) -> None:
    assert_versioned_fields(data)
    assert is_valid_uuid(data["species_profile_id"])
    assert isinstance(data["supplier_name"], str) and data["supplier_name"]
    assert isinstance(data["received_board_feet"], int)
    assert data["receipt_grade"] in ("FAS", "SELECT", "NO1_COMMON", "NO2_COMMON")
    assert isinstance(data["accepted_board_feet"], int)
    assert data["status"] in ("RECEIVED", "ACCEPTED", "ALLOCATED", "CONSUMED", "REJECTED")


def assert_kiln_charge(data: dict) -> None:
    assert_versioned_fields(data)
    assert is_valid_uuid(data["drying_schedule_id"])
    assert is_valid_uuid(data["kiln_chamber_id"])
    assert data["status"] in (
        "SCHEDULED",
        "DISPLACED",
        "LOADED",
        "DRYING",
        "CONDITIONING",
        "REDRY",
        "RELEASED",
        "CLOSED",
    )
    assert isinstance(data["charged_green_bf"], int), "charged green board feet are whole integers"
    assert isinstance(data["redry_count"], int)


def assert_product_line(data: dict) -> None:
    assert_versioned_fields(data)
    assert isinstance(data["line_code"], str) and data["line_code"]
    assert data["construction_type"] in ("SOLID", "ENGINEERED")
    assert data["posture"] in ("OPEN", "RESTRICTED", "FROZEN")
    assert isinstance(data["freeze_override"], bool)
    assert_warranty_ledger_invariants(data)


def assert_core_stock(data: dict) -> None:
    assert_versioned_fields(data)
    assert is_valid_uuid(data["product_line_id"])
    assert data["core_material"] in ("BIRCH_PLY", "HDF", "EUCALYPTUS_PLY")
    assert data["available_square_feet"] >= 0
    assert data["reserved_square_feet"] >= 0


def assert_prefinish_line(data: dict) -> None:
    assert_versioned_fields(data)
    assert isinstance(data["line_code"], str) and data["line_code"]
    assert isinstance(data["daily_capacity_linear_feet"], int)
    assert isinstance(data["coating_passes"], int)


def assert_flooring_lot(data: dict) -> None:
    assert_versioned_fields(data)
    assert is_valid_uuid(data["product_line_id"])
    assert is_valid_uuid(data["kiln_charge_id"])
    assert data["status"] in ("PLANNED", "MILLED", "GRADED", "QUARANTINED", "VOIDED")
    assert data["construction_type"] in ("SOLID", "ENGINEERED")
    assert data["input_dry_bf"] > 0


def assert_grade_run(data: dict) -> None:
    assert_versioned_fields(data)
    assert is_valid_uuid(data["flooring_lot_id"])
    assert data["inspector_ruleset"] in ("NHLA", "MILL_CHARACTER")
    assert data["status"] in ("DRAFT", "FINALIZED", "SUPERSEDED")


def assert_grade_bundle(data: dict) -> None:
    """A graded bundle is an immutable tally line: once written it is never
    edited, so it carries only ``id`` and ``created_at``."""
    assert_identity_fields(data)
    assert_no_revision_counter(data)
    assert data["grade_class"] in (
        "CLEAR",
        "SELECT",
        "NO1_COMMON",
        "NO2_COMMON",
        "CHARACTER",
        "CABIN",
    )
    assert data["bundle_board_feet"] > 0
    assert data["length_factor"] in (0.83, 1.00, 1.07)
    assert data["credit_factor"] in (1.00, 0.95, 0.85, 0.70, 0.60, 0.40)
    assert isinstance(data["tally_value_cents"], int), "monetary amounts are whole cents"


def assert_prefinish_run(data: dict) -> None:
    assert_versioned_fields(data)
    assert is_valid_uuid(data["prefinish_line_id"])
    assert is_valid_uuid(data["flooring_lot_id"])
    assert is_valid_uuid(data["product_line_id"])
    assert data["status"] in ("SCHEDULED", "HELD", "RUNNING", "COMPLETED")
    assert isinstance(data["scheduled_linear_feet"], int), "linear feet are whole integers"


def assert_byproduct_batch(data: dict) -> None:
    assert_versioned_fields(data)
    assert is_valid_uuid(data["flooring_lot_id"])
    assert data["byproduct_type"] in ("SAWDUST", "SHAVINGS", "SHORTS")
    assert data["available_tons"] >= 0
    assert data["sold_tons"] >= 0


def assert_byproduct_sale(data: dict) -> None:
    assert_versioned_fields(data)
    assert is_valid_uuid(data["byproduct_batch_id"])
    for field in ("gross_cents", "discount_cents", "haul_cents", "net_cents"):
        assert isinstance(data[field], int), f"{field} must be a whole number of cents"


def assert_warranty_claim(data: dict) -> None:
    assert_versioned_fields(data)
    assert is_valid_uuid(data["product_line_id"])
    assert data["claim_type"] in ("CUPPING", "GAPPING")
    assert data["adjudication_status"] in (
        "SUBMITTED",
        "INFO_REQUESTED",
        "APPROVED",
        "DENIED",
        "REVERSED",
    )
    assert data["remediation_status"] in (
        "NOT_STARTED",
        "IN_PROGRESS",
        "COMPLETED",
        "CANCELLED",
    )
    assert isinstance(data["estimated_liability_cents"], int)
    assert isinstance(data["submitted_by_user_id"], str) and data["submitted_by_user_id"]


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------


def assert_warranty_ledger_invariants(line: dict) -> None:
    """At all times a line's ``warranty_balance_cents`` plus its
    ``warranty_committed_cents`` equals its ``warranty_funded_total_cents``, and
    the posture follows the reserve."""
    assert (
        line["warranty_balance_cents"] + line["warranty_committed_cents"]
        == line["warranty_funded_total_cents"]
    ), (
        "balance + committed must equal funded total, got "
        f"{line['warranty_balance_cents']} + {line['warranty_committed_cents']} "
        f"!= {line['warranty_funded_total_cents']}"
    )
    if line["freeze_override"]:
        assert line["posture"] == "FROZEN", "a frozen override forces the posture to FROZEN"
    elif line["warranty_balance_cents"] < WARRANTY_RESTRICT_FLOOR_CENTS:
        assert line["posture"] == "RESTRICTED", (
            f"balance {line['warranty_balance_cents']} is below the restriction floor "
            f"so posture must be RESTRICTED, got {line['posture']}"
        )
    else:
        assert line["posture"] == "OPEN", (
            f"balance {line['warranty_balance_cents']} is at or above the floor so "
            f"posture must be OPEN, got {line['posture']}"
        )


def assert_green_ledger_invariant(charge: dict, allocated_receipts: list) -> None:
    """The charge's ``charged_green_bf`` equals the total ``accepted_board_feet``
    of the green receipts pointing at it in ``ALLOCATED`` or ``CONSUMED``."""
    expected = sum(
        receipt["accepted_board_feet"]
        for receipt in allocated_receipts
        if receipt["status"] in ("ALLOCATED", "CONSUMED")
        and receipt.get("kiln_charge_id") == charge["id"]
    )
    assert charge["charged_green_bf"] == expected, (
        f"charged_green_bf {charge['charged_green_bf']} must equal the total accepted "
        f"board feet of its allocated receipts ({expected})"
    )


def assert_decimal_places(value, places: int, field: str = "value") -> None:
    """Assert a serialized decimal carries no more precision than the PRD allows."""
    quantized = round(float(value), places)
    assert abs(float(value) - quantized) < 1e-9, (
        f"{field} must be rounded to {places} decimal places, got {value}"
    )


def assert_cents(value, field: str = "amount") -> None:
    assert isinstance(value, int), f"{field} must be a whole number of cents, got {value!r}"


__all__ = [
    "assert_identity_fields",
    "assert_versioned_fields",
    "assert_no_revision_counter",
    "assert_species_profile",
    "assert_drying_schedule",
    "assert_kiln_chamber",
    "assert_green_receipt",
    "assert_kiln_charge",
    "assert_product_line",
    "assert_core_stock",
    "assert_prefinish_line",
    "assert_flooring_lot",
    "assert_grade_run",
    "assert_grade_bundle",
    "assert_prefinish_run",
    "assert_byproduct_batch",
    "assert_byproduct_sale",
    "assert_warranty_claim",
    "assert_warranty_ledger_invariants",
    "assert_green_ledger_invariant",
    "assert_decimal_places",
    "assert_cents",
]
