"""Entity assertions, money helpers and semantic instant comparison."""

from datetime import datetime, timezone

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import INVOICE_LINE_COMPONENTS

MONEY_TOLERANCE = 0.005


def parse_instant(value):
    """Parse an ISO 8601 UTC instant into an aware datetime.

    Accepts a trailing Z, an explicit offset, and any number of fractional
    digits, so a value rendered as '...T00:00:00Z' and one rendered as
    '...T00:00:00.000Z' parse to the same instant.
    """
    assert isinstance(value, str) and value, f"expected an ISO 8601 string, got {value!r}"
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_same_instant(actual, expected, label="timestamp"):
    """Compare two instants semantically, never as strings."""
    assert actual is not None, f"{label} must not be null (expected {expected})"
    got = parse_instant(actual)
    want = parse_instant(expected)
    assert got == want, f"{label}: expected instant {expected}, got {actual}"


def assert_money(actual, expected, label="amount"):
    assert actual is not None, f"{label} must not be null (expected {expected})"
    assert abs(float(actual) - float(expected)) < MONEY_TOLERANCE, (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_two_decimal_places(value, label="amount"):
    """Monetary values are carried to a precision of exactly 2 decimal places."""
    assert value is not None, f"{label} must not be null"
    rounded = round(float(value) + 1e-9, 2)
    assert abs(float(value) - rounded) < 1e-6, (
        f"{label} must carry at most 2 decimal places, got {value}"
    )


def assert_four_decimal_places(value, label="fill_rate"):
    assert value is not None, f"{label} must not be null"
    rounded = round(float(value) + 1e-11, 4)
    assert abs(float(value) - rounded) < 1e-8, (
        f"{label} must carry at most 4 decimal places, got {value}"
    )


def assert_common_fields(data, label="record"):
    """Twenty-one of the twenty-two entity types carry id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a bare UUID string"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be an ISO 8601 UTC timestamp"
    )
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer"
    assert data["version"] >= 1, f"{label}.version begins at 1"


def assert_bare_uuid_id(data, label="record"):
    """The id is a UUID string with no type prefix of any kind."""
    raw = data.get("id", "")
    assert is_valid_uuid(raw), f"{label}.id must be a bare UUID, got {raw!r}"
    assert ":" not in raw and "_" not in raw, f"{label}.id must carry no type prefix, got {raw!r}"


# ------------------------------------------------------------------ entities

def assert_brokerage(data):
    assert_common_fields(data, "brokerage")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["license_code"], str) and data["license_code"]
    assert_two_decimal_places(data["authorization_cap"], "brokerage.authorization_cap")
    assert isinstance(data["tax_exempt"], bool)
    assert isinstance(data["open_project_count"], int)


def assert_client(data):
    assert_common_fields(data, "client")
    assert data["client_type"] in ("LISTING_AGENT", "SELLER", "BROKERAGE_ADMIN")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert_two_decimal_places(
        data["effective_authorization_cap"], "client.effective_authorization_cap"
    )
    assert isinstance(data["consent_on_file"], bool)


def assert_property(data):
    assert_common_fields(data, "property")
    assert data["occupancy"] in ("OCCUPIED", "VACANT")
    assert data["prep_state"] in (
        "NEW", "CONSULT_BOOKED", "SCOPED", "IN_PREP", "STAGED", "DESTAGED", "CLOSED",
    )
    assert 1 <= data["room_count"] <= 40
    assert 0 <= float(data["distance_miles"]) <= 500


def assert_listing(data):
    assert_common_fields(data, "listing")
    assert data["listing_state"] in (
        "ACTIVE", "UNDER_CONTRACT", "BACK_ON_MARKET", "CLOSED_SOLD", "TERMINATED",
    )
    assert isinstance(data["fallout_count"], int) and data["fallout_count"] >= 0
    assert float(data["list_price"]) > 0


def assert_package_tier(data):
    """PackageTier is configuration: id and created_at only, no version, no updated_at."""
    assert is_valid_uuid(data.get("id", "")), "package tier id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "package tier created_at required"
    assert "version" not in data, "a package tier row carries no version field"
    assert "updated_at" not in data, "a package tier row carries no updated_at field"
    assert data["tier_code"] in ("ESSENTIAL", "SIGNATURE", "LUXE")
    assert 1 <= data["tier_rank"] <= 3


def assert_vendor(data):
    assert_common_fields(data, "vendor")
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["lead_time_days"], int)
    assert isinstance(data["min_lease_cycles"], int)
    assert isinstance(data["cancel_cutoff_days"], int)


def assert_inventory_item(data):
    assert_common_fields(data, "inventory item")
    assert data["category"] in (
        "SOFA", "BED", "TABLE", "CHAIR", "ART", "RUG", "LAMP", "ACCESSORY_SET",
    )
    assert data["status"] in ("AVAILABLE", "RESERVED", "DEPLOYED", "IN_REPAIR", "WRITTEN_OFF")
    assert data["condition_grade"] in ("A", "B", "C")
    assert isinstance(data["times_deployed"], int) and data["times_deployed"] >= 0


def assert_consultation(data):
    assert_common_fields(data, "consultation")
    assert data["state"] in (
        "SCHEDULED", "HELD", "SCOPE_DRAFTED", "SCOPE_SUBMITTED",
        "SCOPE_APPROVED", "SCOPE_REJECTED", "CANCELLED",
    )
    assert data.get("pipeline") in (None, "OCCUPIED_PREP", "VACANT_STAGING")
    assert isinstance(data["revision_count"], int)
    assert isinstance(data["scoped_room_count"], int)
    assert isinstance(data["rental_line_count"], int)


def assert_scope_item(data):
    assert_common_fields(data, "scope item")
    assert data["action"] in ("EDIT", "DECLUTTER", "REFRESH", "PACKAGE_ROOM", "ACCESSORY_ONLY")
    assert isinstance(data["sequence_index"], int) and data["sequence_index"] >= 1
    assert isinstance(data["requires_rental"], bool)


def assert_project(data):
    assert_common_fields(data, "project")
    assert data["pipeline"] in ("OCCUPIED_PREP", "VACANT_STAGING")
    assert data["payer_type"] in ("AGENT", "SELLER", "SPLIT", "BROKERAGE", "PAY_AT_CLOSING")
    assert data["workflow_state"] in (
        "DRAFT", "AUTHORIZED", "PULL_OPEN", "INSTALL_SCHEDULED", "VISITS_OPEN",
        "STAGED", "RESTAGE_REQUIRED", "DESTAGE_PENDING", "PICKED_UP", "CLOSEOUT", "CLOSED",
    )
    assert data["payment_state"] in (
        "UNBILLED", "DEPOSIT_HELD", "INVOICED", "DEFERRED",
        "ESCALATED", "SETTLED", "WRITTEN_OFF",
    )
    assert_two_decimal_places(data["contract_value"], "project.contract_value")
    assert isinstance(data["fiscal_hold"], bool)
    assert isinstance(data["reshoot_credits_remaining"], int)


def assert_pull(data):
    assert_common_fields(data, "pull")
    assert data["state"] in ("DRAFT", "SUBMITTED", "PARTIAL", "COMMITTED", "RELEASED", "CANCELLED")
    assert isinstance(data["requested_unit_count"], int)
    assert isinstance(data["filled_unit_count"], int)
    assert_four_decimal_places(data["fill_rate"], "pull.fill_rate")
    assert isinstance(data["resubmit_count"], int)


def assert_pull_line(data):
    assert_common_fields(data, "pull line")
    assert data["source"] in ("OWNED", "VENDOR")
    assert data["state"] in (
        "REQUESTED", "ALLOCATED", "UNFILLED", "DEPLOYED", "RETURNED", "SWAPPED", "DROPPED",
    )
    assert_two_decimal_places(data["monthly_rate"], "pull line.monthly_rate")


def assert_rental_order(data):
    assert_common_fields(data, "rental order")
    assert data["state"] in (
        "DRAFT", "PLACED", "CONFIRMED", "DELIVERED", "RETURNED", "CANCELLED", "CANCELLED_LATE",
    )
    assert 1 <= data["unit_count"] <= 60


def assert_install(data):
    assert_common_fields(data, "install")
    assert data["state"] in ("SCHEDULED", "IN_PROGRESS", "COMPLETE", "NO_ACCESS", "CANCELLED")
    assert 1 <= data["crew_size"] <= 8
    assert isinstance(data["attempt_count"], int)


def assert_visit(data):
    assert_common_fields(data, "visit")
    assert data["state"] in ("SCHEDULED", "COMPLETED", "NO_ACCESS", "CANCELLED")
    assert isinstance(data["visit_index"], int) and data["visit_index"] >= 1
    assert isinstance(data["attempt_count"], int)


def assert_lease(data):
    assert_common_fields(data, "lease")
    assert data["state"] in (
        "PENDING", "ACTIVE", "EXTENDED", "ENDING", "HOLDOVER", "ENDED", "CANCELLED",
    )
    assert 3 <= data["initial_cycles"] <= 24
    assert isinstance(data["extension_cycles"], int)
    assert isinstance(data["billed_cycles"], int)
    assert_two_decimal_places(data["monthly_rent"], "lease.monthly_rent")


def assert_extension(data):
    assert_common_fields(data, "extension")
    assert data["state"] in (
        "REQUESTED", "APPROVED_FULL", "APPROVED_PARTIAL", "DENIED", "APPLIED",
    )
    assert isinstance(data["granted_cycles"], int)
    assert isinstance(data["extended_line_count"], int)
    assert isinstance(data["returned_line_count"], int)


def assert_pickup(data):
    assert_common_fields(data, "pickup")
    assert data["state"] in (
        "SCHEDULED", "IN_PROGRESS", "COMPLETED", "NO_ACCESS", "REFUSED", "CANCELLED",
    )
    assert isinstance(data["attempt_count"], int)
    assert isinstance(data["assessed_line_count"], int)
    assert_two_decimal_places(data["damage_total"], "pickup.damage_total")


def assert_damage_assessment(data):
    assert_common_fields(data, "damage assessment")
    assert data["state"] in ("DRAFT", "ASSESSED", "DISPUTED", "UPHELD", "REVISED", "FINAL")
    assert data["condition_at_pickup"] in ("INTACT", "MINOR", "MAJOR", "MISSING")
    assert data["disposition"] in ("NO_CHARGE", "REPAIR", "REPLACE")
    assert_two_decimal_places(data["charge_amount"], "assessment.charge_amount")
    assert_two_decimal_places(
        data["depreciated_replacement_value"], "assessment.depreciated_replacement_value"
    )


def assert_photo_shoot(data):
    assert_common_fields(data, "photo shoot")
    assert data["state"] in (
        "SCHEDULED", "COMPLETED", "DELIVERED", "RESHOOT_REQUESTED", "CANCELLED",
    )
    assert isinstance(data["is_reshoot"], bool)
    assert isinstance(data["mls_delivery_gated"], bool)
    assert_two_decimal_places(data["overage_fee"], "shoot.overage_fee")


def assert_invoice(data):
    assert_common_fields(data, "invoice")
    assert data["state"] in (
        "DRAFT", "ISSUED", "DEFERRED_CLOSING", "ESCALATED", "PAID", "VOID",
    )
    for field in ("subtotal", "tax_amount", "deposit_applied", "interest_accrued", "total_due"):
        assert_two_decimal_places(data[field], f"invoice.{field}")
    assert float(data["total_due"]) >= 0.0, "invoice.total_due is floored at 0.00"


def assert_deposit(data):
    assert_common_fields(data, "deposit")
    assert data["state"] in (
        "REQUIRED", "HELD", "PARTIALLY_APPLIED", "APPLIED", "REFUNDED", "FORFEITED",
    )
    for field in (
        "amount", "applied_to_damage", "applied_to_holdover", "applied_to_balance",
        "refunded_amount", "forfeited_amount", "held_remaining",
    ):
        assert_two_decimal_places(data[field], f"deposit.{field}")


# ---------------------------------------------------------------- invariants

def assert_deposit_conservation(deposit):
    """A deposit's amount equals the sum of its five allocations plus the residue."""
    total = (
        float(deposit["applied_to_damage"])
        + float(deposit["applied_to_holdover"])
        + float(deposit["applied_to_balance"])
        + float(deposit["refunded_amount"])
        + float(deposit["forfeited_amount"])
        + float(deposit["held_remaining"])
    )
    assert abs(total - float(deposit["amount"])) < MONEY_TOLERANCE, (
        "deposit amount must equal damage + holdover + balance + refunded + "
        f"forfeited + held_remaining; amount={deposit['amount']} sum={total}"
    )


def assert_warehouse_conservation(summary):
    """on_hand_total equals available + reserved + deployed + in_repair + written_off."""
    buckets = (
        int(summary["available"])
        + int(summary["reserved"])
        + int(summary["deployed"])
        + int(summary["in_repair"])
        + int(summary["written_off"])
    )
    assert buckets == int(summary["on_hand_total"]), (
        f"on_hand_total {summary['on_hand_total']} must equal the five buckets summing to {buckets}"
    )


def assert_lease_cycle_conservation(lease, applied_granted_cycles):
    """billed_cycles equals initial_cycles plus the granted cycles of APPLIED extensions."""
    assert int(lease["billed_cycles"]) == int(lease["initial_cycles"]) + applied_granted_cycles, (
        f"billed_cycles {lease['billed_cycles']} must equal initial_cycles "
        f"{lease['initial_cycles']} plus applied extension cycles {applied_granted_cycles}"
    )


def assert_line_summary_shape(line_summary):
    """The line_summary carries the twelve named components."""
    assert isinstance(line_summary, dict), "line_summary must be an object"
    for component in INVOICE_LINE_COMPONENTS:
        assert component in line_summary, f"line_summary is missing the '{component}' component"
        assert_two_decimal_places(line_summary[component], f"line_summary.{component}")


def approx_money(value):
    return pytest.approx(value, abs=0.005)
