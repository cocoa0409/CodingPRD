"""Entity assertions, timestamp helpers and domain invariant checkers."""

from datetime import datetime, timedelta, timezone
from typing import Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AccrualStatus,
    CreditGrantSource,
    CreditGrantStatus,
    CycleStatus,
    DropRunStatus,
    ExceptionState,
    ItemStatus,
    MemberOrderStatus,
    MemberStatus,
    MemberTier,
    OrderLineStatus,
    PalletStatus,
    PaymentKind,
    PaymentMethod,
    PaymentRecordStatus,
    PaymentStatusAxis,
    ReconciliationStatus,
    RemainderPolicy,
    RouteRunStatus,
    SubstitutionOfferStatus,
    SubstitutionPref,
    TempClass,
    VolunteerShiftStatus,
)

# --------------------------------------------------------------------------
# Timestamps.  Server-minted stamps are rendered with three fractional digits
# (PRD §2.4) while caller-supplied instants may be echoed verbatim, so every
# timestamp comparison in this suite is semantic, never a string equality.
# --------------------------------------------------------------------------


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, accepting both `Z` and `+00:00` forms
    and any number of fractional digits."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_same_instant(actual: str, expected: str, label: str = "timestamp") -> None:
    """Compare two ISO 8601 instants by value, not by rendering."""
    assert actual is not None, f"{label}: expected {expected}, got None"
    a = parse_instant(actual)
    b = parse_instant(expected)
    assert a == b, f"{label}: expected instant {expected} ({b}), got {actual} ({a})"


def assert_instant_equals_offset(
    actual: str, base_iso: str, *, days: int = 0, hours: int = 0, label: str = "timestamp"
) -> None:
    """Assert `actual` equals `base_iso` shifted by the given offset."""
    expected = parse_instant(base_iso) + timedelta(days=days, hours=hours)
    a = parse_instant(actual)
    assert a == expected, (
        f"{label}: expected {expected.isoformat()} "
        f"(= {base_iso} + {days}d {hours}h), got {actual}"
    )


def iso_z(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def shift_iso(base_iso: str, *, days: int = 0, hours: int = 0) -> str:
    return iso_z(parse_instant(base_iso) + timedelta(days=days, hours=hours))


# --------------------------------------------------------------------------
# Common-field assertions
# --------------------------------------------------------------------------


def assert_common_fields(data: dict, entity_name: str = "resource") -> None:
    """`id`, `created_at`, `updated_at` and `version` (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity_name}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{entity_name}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_name}.version must be an integer starting at 1"
    )


def assert_append_only_fields(data: dict, entity_name: str = "resource") -> None:
    """`id` and `created_at` only — no `updated_at`, no `version` (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity_name}.created_at must be ISO 8601"
    assert "updated_at" not in data, f"{entity_name} must not carry updated_at"
    assert "version" not in data, f"{entity_name} must not carry version"


def _enum_values(enum_cls) -> list:
    return [member.value for member in enum_cls]


# --------------------------------------------------------------------------
# Per-entity assertions
# --------------------------------------------------------------------------


def assert_route(data: dict) -> None:
    assert_common_fields(data, "Route")
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["name"], str)
    assert isinstance(data["reefer_slots"], int) and data["reefer_slots"] >= 0
    assert isinstance(data["route_minimum_cents"], int)
    assert data["route_minimum_cents"] >= 0
    assert isinstance(data["max_pallets"], int) and data["max_pallets"] >= 1
    assert data["cold_capable"] is (data["reefer_slots"] > 0), (
        "cold_capable must be true exactly when reefer_slots is greater than 0"
    )


def assert_drop_point(data: dict) -> None:
    assert_common_fields(data, "DropPoint")
    assert is_valid_uuid(data["route_id"])
    assert isinstance(data["name"], str)
    assert isinstance(data["drop_minimum_cents"], int)


def assert_item(data: dict) -> None:
    assert_common_fields(data, "Item")
    assert isinstance(data["sku"], str) and data["sku"]
    assert data["temp_class"] in _enum_values(TempClass)
    assert isinstance(data["case_pack_units"], int) and data["case_pack_units"] >= 1
    assert isinstance(data["unit_weight_grams"], int) and data["unit_weight_grams"] >= 1
    assert isinstance(data["unit_cube_cm3"], int) and data["unit_cube_cm3"] >= 1
    assert isinstance(data["split_allowed"], bool)
    assert data["remainder_policy"] in _enum_values(RemainderPolicy)
    assert data["status"] in _enum_values(ItemStatus)


def assert_price_version(data: dict) -> None:
    assert_append_only_fields(data, "PriceVersion")
    assert is_valid_uuid(data["item_id"])
    assert isinstance(data["case_price_cents"], int) and data["case_price_cents"] >= 1
    assert isinstance(data["split_unit_base_cents"], int)
    assert is_iso8601_timestamp(data["effective_from"])


def assert_member(data: dict) -> None:
    assert_common_fields(data, "Member")
    assert isinstance(data["email"], str) and data["email"]
    assert data["tier"] in _enum_values(MemberTier)
    assert data["status"] in _enum_values(MemberStatus)
    assert data["tier_rank"] in (1, 2, 3)
    assert isinstance(data["lifetime_dues_paid_cents"], int)
    assert isinstance(data["credit_balance_cents"], int)
    assert data["credit_balance_cents"] >= 0
    assert isinstance(data["is_coordinator"], bool)


def assert_cycle(data: dict) -> None:
    assert_common_fields(data, "Cycle")
    assert isinstance(data["code"], str) and data["code"]
    assert data["status"] in _enum_values(CycleStatus)
    assert data["exception_state"] in _enum_values(ExceptionState)
    assert is_iso8601_timestamp(data["opens_at"])
    assert is_iso8601_timestamp(data["cutoff_at"])
    assert parse_instant(data["cutoff_at"]) > parse_instant(data["opens_at"]), (
        "cutoff_at must be strictly after opens_at"
    )


def assert_route_run(data: dict) -> None:
    assert_common_fields(data, "RouteRun")
    assert is_valid_uuid(data["cycle_id"])
    assert is_valid_uuid(data["route_id"])
    assert data["status"] in _enum_values(RouteRunStatus)
    for field in (
        "aggregated_subtotal_cents",
        "supplier_invoice_cents",
        "freight_cents",
        "cold_pallet_count",
        "dry_pallet_count",
        "reefer_slots_used",
        "reefer_surcharge_cents",
        "received_subtotal_cents",
    ):
        assert isinstance(data[field], int), f"RouteRun.{field} must be an integer"
    assert data["reefer_slots_used"] == data["cold_pallet_count"], (
        "reefer_slots_used is exactly cold_pallet_count"
    )


def assert_drop_run(data: dict) -> None:
    assert_common_fields(data, "DropRun")
    assert is_valid_uuid(data["cycle_id"])
    assert is_valid_uuid(data["drop_point_id"])
    assert data["status"] in _enum_values(DropRunStatus)
    for field in (
        "subtotal_cents",
        "discounted_subtotal_cents",
        "received_subtotal_cents",
        "freight_alloc_cents",
        "reefer_alloc_cents",
        "rollforward_count",
    ):
        assert isinstance(data[field], int), f"DropRun.{field} must be an integer"
    assert isinstance(data["verified_volunteer_hours"], (int, float))
    assert isinstance(data["volunteer_obligation_met"], bool)
    assert data["volunteer_obligation_met"] is (
        float(data["verified_volunteer_hours"]) >= 4.0
    ), "volunteer_obligation_met is true exactly when verified hours are at least 4.0"


def assert_member_order(data: dict) -> None:
    assert_common_fields(data, "MemberOrder")
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["drop_run_id"])
    assert data["status"] in _enum_values(MemberOrderStatus)
    assert data["payment_status"] in _enum_values(PaymentStatusAxis)
    for field in (
        "gross_cents",
        "split_fee_cents",
        "tier_discount_cents",
        "freight_alloc_cents",
        "reefer_alloc_cents",
        "pre_credit_total_cents",
        "credit_applied_cents",
        "actual_total_cents",
        "estimated_total_cents",
        "authorized_amount_cents",
        "captured_cents",
        "refunded_cents",
    ):
        assert isinstance(data[field], int), f"MemberOrder.{field} must be an integer"


def assert_order_line(data: dict) -> None:
    assert_common_fields(data, "OrderLine")
    assert is_valid_uuid(data["member_order_id"])
    assert is_valid_uuid(data["item_id"])
    assert isinstance(data["qty_units"], int)
    assert data["status"] in _enum_values(OrderLineStatus)
    assert data["substitution_pref"] in _enum_values(SubstitutionPref)
    assert isinstance(data["rollover_opt_in"], bool)
    assert isinstance(data["is_split_unit"], bool)
    for field in (
        "bound_case_price_cents",
        "unit_price_cents",
        "split_fee_per_unit_cents",
        "confirmed_units",
        "allocated_units",
        "short_units",
        "allocation_remainder_rank",
        "line_gross_cents",
    ):
        assert isinstance(data[field], int), f"OrderLine.{field} must be an integer"


def assert_case_aggregate(data: dict) -> None:
    assert_common_fields(data, "CaseAggregate")
    assert is_valid_uuid(data["route_run_id"])
    assert is_valid_uuid(data["item_id"])
    assert data["policy_applied"] in _enum_values(RemainderPolicy)
    for field in (
        "requested_units",
        "cases_ordered",
        "covered_units",
        "remainder_units",
        "overage_units",
        "dropped_units",
        "case_price_cents",
        "units_received",
    ):
        assert isinstance(data[field], int), f"CaseAggregate.{field} must be an integer"


def assert_receipt_line(data: dict) -> None:
    assert_common_fields(data, "ReceiptLine")
    assert is_valid_uuid(data["route_run_id"])
    assert is_valid_uuid(data["case_aggregate_id"])
    assert isinstance(data["cases_received"], int) and data["cases_received"] >= 0
    assert isinstance(data["units_received"], int)


def assert_substitution_offer(data: dict) -> None:
    assert_common_fields(data, "SubstitutionOffer")
    assert is_valid_uuid(data["order_line_id"])
    assert is_valid_uuid(data["substitute_item_id"])
    assert data["status"] in _enum_values(SubstitutionOfferStatus)
    assert isinstance(data["within_tolerance"], bool)
    assert is_iso8601_timestamp(data["respond_by"])
    for field in (
        "offered_units",
        "original_unit_price_cents",
        "offered_unit_price_cents",
    ):
        assert isinstance(data[field], int)


def assert_pallet(data: dict) -> None:
    assert_common_fields(data, "Pallet")
    assert is_valid_uuid(data["route_run_id"])
    assert data["temp_class"] in _enum_values(TempClass)
    assert data["status"] in _enum_values(PalletStatus)
    assert isinstance(data["sequence_index"], int) and data["sequence_index"] >= 1
    for field in ("weight_grams", "cube_cm3", "unit_count"):
        assert isinstance(data[field], int)
    assert data["requires_reefer"] is (
        data["temp_class"] in ("FROZEN", "CHILLED")
    ), "requires_reefer is true exactly when temp_class is FROZEN or CHILLED"


def assert_payment(data: dict) -> None:
    assert_common_fields(data, "Payment")
    assert is_valid_uuid(data["member_order_id"])
    assert data["kind"] in _enum_values(PaymentKind)
    assert data["method"] in _enum_values(PaymentMethod)
    assert data["status"] in _enum_values(PaymentRecordStatus)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0


def assert_drop_reconciliation(data: dict) -> None:
    assert_common_fields(data, "DropReconciliation")
    assert is_valid_uuid(data["drop_run_id"])
    assert data["status"] in _enum_values(ReconciliationStatus)
    for field in (
        "member_charges_cents",
        "supplier_cost_cents",
        "freight_alloc_cents",
        "reefer_alloc_cents",
        "commission_cents",
        "club_margin_cents",
        "variance_cents",
    ):
        assert isinstance(data[field], int), (
            f"DropReconciliation.{field} must be an integer"
        )


def assert_commission_accrual(data: dict) -> None:
    assert_common_fields(data, "CommissionAccrual")
    assert is_valid_uuid(data["drop_run_id"])
    assert is_valid_uuid(data["coordinator_member_id"])
    assert data["status"] in _enum_values(AccrualStatus)
    for field in (
        "base_subtotal_cents",
        "accrued_cents",
        "clawback_cents",
        "net_cents",
        "payout_value_cents",
    ):
        assert isinstance(data[field], int)
    assert data["net_cents"] == data["accrued_cents"] - data["clawback_cents"], (
        "net_cents is accrued_cents less clawback_cents"
    )


def assert_volunteer_shift(data: dict) -> None:
    assert_common_fields(data, "VolunteerShift")
    assert is_valid_uuid(data["drop_run_id"])
    assert is_valid_uuid(data["member_id"])
    assert data["status"] in _enum_values(VolunteerShiftStatus)
    assert isinstance(data["hours"], (int, float)) and data["hours"] > 0


def assert_credit_grant(data: dict) -> None:
    assert_common_fields(data, "CreditGrant")
    assert is_valid_uuid(data["member_id"])
    assert data["source"] in _enum_values(CreditGrantSource)
    assert data["status"] in _enum_values(CreditGrantStatus)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert isinstance(data["remaining_cents"], int)
    assert is_iso8601_timestamp(data["expires_at"])


# --------------------------------------------------------------------------
# Domain invariants (PRD §2.11)
# --------------------------------------------------------------------------


def assert_units_conserved(lines: list, units_received: int) -> None:
    """Invariant 1 — allocated plus short equals confirmed, and allocated
    equals the smaller of supply and total confirmed demand."""
    total_confirmed = sum(line["confirmed_units"] for line in lines)
    total_allocated = sum(line["allocated_units"] for line in lines)
    total_short = sum(line["short_units"] for line in lines)
    assert total_allocated + total_short == total_confirmed, (
        f"allocated {total_allocated} + short {total_short} "
        f"must equal confirmed {total_confirmed}"
    )
    assert total_allocated == min(units_received, total_confirmed), (
        f"allocated {total_allocated} must equal min(units_received "
        f"{units_received}, demand {total_confirmed})"
    )


def assert_reefer_fully_allocated(route_run: dict, orders: list) -> None:
    """Invariant 4 — the reefer surcharge is distributed exactly."""
    total = sum(order["reefer_alloc_cents"] for order in orders)
    assert total == route_run["reefer_surcharge_cents"], (
        f"reefer_alloc_cents across the run's orders sums to {total}, "
        f"expected reefer_surcharge_cents {route_run['reefer_surcharge_cents']}"
    )


def assert_freight_fully_allocated(route_run: dict, drop_runs: list) -> None:
    """Invariant 5, level one."""
    total = sum(drop_run["freight_alloc_cents"] for drop_run in drop_runs)
    assert total == route_run["freight_cents"], (
        f"freight_alloc_cents across the drop runs sums to {total}, "
        f"expected freight_cents {route_run['freight_cents']}"
    )


def assert_freight_fully_allocated_within_drop(drop_run: dict, orders: list) -> None:
    """Invariant 5, level two."""
    total = sum(order["freight_alloc_cents"] for order in orders)
    assert total == drop_run["freight_alloc_cents"], (
        f"freight_alloc_cents across the drop run's orders sums to {total}, "
        f"expected {drop_run['freight_alloc_cents']}"
    )


def assert_ledger_identity_holds(reconciliation: dict) -> None:
    """Invariant 6 — at variance 0 the ledger identity closes exactly."""
    assert reconciliation["variance_cents"] == 0, (
        f"variance_cents must be 0, got {reconciliation['variance_cents']}"
    )
    total = (
        reconciliation["supplier_cost_cents"]
        + reconciliation["freight_alloc_cents"]
        + reconciliation["reefer_alloc_cents"]
        + reconciliation["commission_cents"]
        + reconciliation["club_margin_cents"]
    )
    assert reconciliation["member_charges_cents"] == total, (
        f"member_charges_cents {reconciliation['member_charges_cents']} must equal "
        f"the sum of the five ledger legs {total}"
    )


def find_by_id(rows: list, row_id: str) -> Optional[dict]:
    for row in rows:
        if row.get("id") == row_id:
            return row
    return None
