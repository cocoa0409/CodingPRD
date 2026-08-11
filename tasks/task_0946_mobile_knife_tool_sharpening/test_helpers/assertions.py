"""Entity assertions, timestamp helpers and domain invariant checkers."""
from datetime import datetime, timezone
from typing import Optional

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


# --------------------------------------------------------------------------
# Timestamps are compared as instants, never as strings: an implementation may
# legitimately render the same instant as "...Z" or "....000Z".
# --------------------------------------------------------------------------

def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant into a timezone-aware datetime."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_same_instant(actual: Optional[str], expected: Optional[str], label: str = "timestamp"):
    """Compare two ISO 8601 timestamps semantically (instant equality)."""
    if expected is None:
        assert actual is None, f"{label}: expected null, got {actual!r}"
        return
    assert actual is not None, f"{label}: expected {expected!r}, got null"
    assert parse_instant(actual) == parse_instant(expected), (
        f"{label}: expected instant {expected!r}, got {actual!r}"
    )


def assert_instant_before(earlier: str, later: str, label: str = "ordering"):
    assert parse_instant(earlier) < parse_instant(later), (
        f"{label}: expected {earlier!r} to precede {later!r}"
    )


# --------------------------------------------------------------------------
# Common-field assertions
# --------------------------------------------------------------------------

def assert_common_fields(data: dict, entity_name: str = "entity"):
    """id + created_at + updated_at + version for a versioned row."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a UUID string"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity_name}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity_name}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_name}.version must be an integer starting at 1"
    )


def assert_append_only_fields(data: dict, entity_name: str = "record"):
    """id + created_at only -- no updated_at and no version at all."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a UUID string"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity_name}.created_at must be ISO 8601"
    assert "version" not in data, f"{entity_name} must not carry a version field"
    assert "updated_at" not in data, f"{entity_name} must not carry an updated_at field"


# --------------------------------------------------------------------------
# Per-entity assertions
# --------------------------------------------------------------------------

def assert_account(data: dict):
    assert_common_fields(data, "Account")
    assert data["account_type"] in ["RESIDENTIAL", "RESTAURANT", "SALON", "COMMERCIAL"]
    assert data["zone_code"] in ["ZONE_N", "ZONE_S", "ZONE_E", "ZONE_W"]
    assert data["billing_mode"] in ["PER_VISIT", "MONTHLY_ROLLUP"]
    assert data["status"] in ["ACTIVE", "SUSPENDED"]
    assert isinstance(data["tax_exempt"], bool)
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["outstanding_balance_cents"], int)


def assert_subscription(data: dict):
    assert_common_fields(data, "Subscription")
    assert data["status"] in ["ACTIVE", "PAUSED", "CANCELLED"]
    assert data["cadence"] in ["WEEKLY", "BIWEEKLY", "MONTHLY"]
    assert isinstance(data["allowance_remaining"], int)
    assert isinstance(data["included_items_this_cycle"], int)
    assert isinstance(data["effective_monthly_fee_cents"], int)
    assert isinstance(data["cycle_index"], int) and data["cycle_index"] >= 1


def assert_service_request(data: dict):
    assert_common_fields(data, "ServiceRequest")
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "SCHEDULED", "IN_SERVICE", "COMPLETED", "CANCELLED"]
    assert data["billing_status"] in ["UNBILLED", "INVOICED", "SETTLED", "CREDITED"]
    assert data["channel"] in ["VAN_ROUTE", "LOCKER", "REWORK"]
    assert data["priority"] in ["STANDARD", "RUSH"]
    assert isinstance(data["item_count"], int) and data["item_count"] >= 0


def assert_request_item(data: dict):
    assert_common_fields(data, "RequestItem")
    assert data["service_status"] in [
        "INTAKE_PENDING", "ASSESSED", "IN_WORK", "DONE", "DELIVERED",
        "REWORK_QUEUED", "RETURNED_UNSERVICED", "ABANDONED"]
    assert data["custody_location"] in [
        "CUSTOMER", "VAN", "BENCH", "LOCKER", "DELIVERED", "ABANDONED"]
    assert data["authorization_status"] in [
        "NOT_REQUIRED", "PENDING", "AUTHORIZED", "DECLINED"]
    assert isinstance(data["quoted_gross_cents"], int)
    assert isinstance(data["final_gross_cents"], int)


def assert_route_run(data: dict):
    assert_common_fields(data, "RouteRun")
    assert data["status"] in ["PLANNED", "DISPATCHED", "IN_PROGRESS", "COMPLETED", "CANCELLED"]
    assert isinstance(data["scheduled_stop_count"], int) and data["scheduled_stop_count"] >= 0
    assert isinstance(data["booked_service_minutes"], int) and data["booked_service_minutes"] >= 0
    assert isinstance(data["committed_minutes_provisional"], int)


def assert_route_stop(data: dict):
    assert_common_fields(data, "RouteStop")
    assert data["status"] in ["SCHEDULED", "ARRIVED", "SERVICED", "SKIPPED", "SPILLED", "CANCELLED"]
    assert isinstance(data["sequence"], int) and data["sequence"] >= 1
    assert isinstance(data["spill_hop_count"], int) and data["spill_hop_count"] >= 0


def assert_locker_compartment(data: dict):
    assert_common_fields(data, "LockerCompartment")
    assert data["status"] in ["AVAILABLE", "ASSIGNED", "OCCUPIED", "HOLD_EXPIRED"]
    assert data["size"] in ["SMALL", "MEDIUM", "LARGE"]
    assert isinstance(data["stored_item_count"], int)
    assert isinstance(data["stored_value_cents"], int)


def assert_bench_day(data: dict):
    assert_common_fields(data, "BenchDay")
    assert isinstance(data["bench_minute_budget"], int) and data["bench_minute_budget"] >= 1
    assert isinstance(data["booked_minutes"], int) and data["booked_minutes"] >= 0


def assert_loaner_unit(data: dict):
    assert_common_fields(data, "LoanerUnit")
    assert data["status"] in ["IN_STOCK", "ISSUED", "INSPECTION", "RETIRED"]
    assert data["grade"] in ["STANDARD", "PREMIUM"]
    assert isinstance(data["cycle_count"], int) and data["cycle_count"] >= 0


def assert_loaner_issue(data: dict):
    assert_common_fields(data, "LoanerIssue")
    assert data["status"] in ["OPEN", "RETURNED"]
    assert data["requested_grade"] in ["STANDARD", "PREMIUM"]
    assert isinstance(data["late_fee_cents"], int)


def assert_warranty_claim(data: dict):
    assert_common_fields(data, "WarrantyClaim")
    assert data["status"] in ["SUBMITTED", "APPROVED", "DENIED"]
    assert isinstance(data["resubmit_count"], int) and data["resubmit_count"] >= 0
    assert isinstance(data["credit_basis_cents"], int)


def assert_invoice(data: dict):
    assert_common_fields(data, "Invoice")
    assert data["status"] in ["DRAFT", "ISSUED", "PARTIALLY_PAID", "PAID", "VOID"]
    assert data["billing_mode"] in ["PER_VISIT", "MONTHLY_ROLLUP"]
    for field in ("taxable_subtotal_cents", "nontaxable_subtotal_cents", "tax_cents",
                  "total_cents", "amount_paid_cents", "amount_due_cents"):
        assert isinstance(data[field], int), f"Invoice.{field} must be integer cents"


def assert_invoice_line(data: dict):
    assert_append_only_fields(data, "InvoiceLine")
    assert data["source"] in [
        "SERVICE", "PART", "SUBSCRIPTION_FEE", "LATE_FEE", "WARRANTY_CREDIT", "PRORATION_CREDIT"]
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["taxable"], bool)
    assert isinstance(data["sequence_index"], int) and data["sequence_index"] >= 1


def assert_payment(data: dict):
    assert_append_only_fields(data, "Payment")
    assert data["method"] in ["CARD", "ACH", "CHECK", "CASH"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert data["resulting_invoice_status"] in ["PARTIALLY_PAID", "PAID"]


def assert_allowance_entry(data: dict):
    assert_append_only_fields(data, "AllowanceLedgerEntry")
    assert data["kind"] in ["GRANTED", "CONSUMED", "EXPIRED", "RESTORED"]
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1


# --------------------------------------------------------------------------
# Domain invariant checkers (PRD 2.10)
# --------------------------------------------------------------------------

def assert_money_conservation(invoice: dict):
    """amount_due_cents == total_cents - amount_paid_cents."""
    assert invoice["amount_due_cents"] == invoice["total_cents"] - invoice["amount_paid_cents"], (
        "amount_due_cents must equal total_cents minus amount_paid_cents, got "
        f"{invoice['amount_due_cents']} vs {invoice['total_cents']} - {invoice['amount_paid_cents']}"
    )


def assert_invoice_totals_consistent(invoice: dict):
    """total_cents == taxable_subtotal + nontaxable_subtotal + tax."""
    expected = (invoice["taxable_subtotal_cents"] + invoice["nontaxable_subtotal_cents"]
                + invoice["tax_cents"])
    assert invoice["total_cents"] == expected, (
        f"total_cents must equal the two subtotals plus tax; expected {expected}, "
        f"got {invoice['total_cents']}"
    )


def assert_route_minute_conservation(run: dict, stops: list):
    """booked_service_minutes and scheduled_stop_count over the active stops."""
    active = [s for s in stops if s["status"] in ("SCHEDULED", "ARRIVED", "SERVICED")]
    expected_minutes = sum(s["stop_service_minutes"] for s in active)
    assert run["booked_service_minutes"] == expected_minutes, (
        f"booked_service_minutes {run['booked_service_minutes']} != sum over active stops "
        f"{expected_minutes}")
    assert run["scheduled_stop_count"] == len(active), (
        f"scheduled_stop_count {run['scheduled_stop_count']} != active stop count {len(active)}")


def assert_bench_minute_conservation(bench_day: dict, items: list):
    """booked_minutes over items on this bench day currently in BENCH custody."""
    expected = 0
    for item in items:
        if item.get("bench_day_id") == bench_day["id"] and item["custody_location"] == "BENCH":
            assessed = item.get("service_minutes_assessed")
            expected += assessed if assessed is not None else item["service_minutes_declared"]
    assert bench_day["booked_minutes"] == expected, (
        f"booked_minutes {bench_day['booked_minutes']} != sum over bench items {expected}")


def assert_allowance_ledger_balances(entries: list, allowance_remaining: int, cycle_index: int):
    """GRANTED - CONSUMED - EXPIRED + RESTORED == allowance_remaining for the cycle."""
    total = 0
    for entry in entries:
        if entry["cycle_index"] != cycle_index:
            continue
        if entry["kind"] in ("GRANTED", "RESTORED"):
            total += entry["quantity"]
        else:
            total -= entry["quantity"]
    assert total == allowance_remaining, (
        f"ledger balance {total} != allowance_remaining {allowance_remaining} "
        f"for cycle {cycle_index}")


def assert_loaner_unit_conservation(units: list, expected_total: int):
    """Every unit sits in exactly one of the four statuses and the total is conserved."""
    counted = [u for u in units if u["status"] in ("IN_STOCK", "ISSUED", "INSPECTION", "RETIRED")]
    assert len(counted) == expected_total, (
        f"expected {expected_total} loaner units across the four statuses, got {len(counted)}")
    assert not any(u["status"] == "INSPECTION" for u in units), (
        "a unit must never be left sitting in INSPECTION between calls")
