"""Entity assertions and domain invariant checkers."""

import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

CONTRACT_STATUSES = ["DRAFT", "ACTIVE", "SUSPENDED", "TERMINATING", "CLOSED"]
SECURE_RELEASE_STATES = ["UNCONFIGURED", "PENDING_VALIDATION", "CONFIGURED", "FAILED"]
RELEASE_METHODS = ["NONE", "BADGE", "PIN"]
DEVICE_LIFECYCLE_STATES = [
    "ASSESSED",
    "PLACED",
    "NETWORKED",
    "ACTIVE",
    "SERVICE_HOLD",
    "RETRIEVED",
    "REMOVED",
]
DEVICE_SUPPLY_STATES = ["SUPPLY_OK", "SUPPLY_LOW", "SUPPLY_ORDERED", "SUPPLY_BLOCKED"]
READ_STATUSES = ["PENDING_VALIDATION", "ACCEPTED", "EXCEPTION", "VOID"]
READ_SOURCES = ["AUTOMATED", "MANUAL", "SWEEP_ESTIMATE"]
EXCEPTION_REASONS = ["NONE", "DEVICE_OFFLINE", "ROLLBACK", "IMPLAUSIBLE_SPIKE"]
PERIOD_STATUSES = ["OPEN", "SWEPT", "PROVISIONAL", "CLOSED"]
ORDER_STATUSES = ["ORDERED", "DELIVERED", "CANCELLED"]
TICKET_STATUSES = ["OPEN", "DISPATCHED", "PARTS_HOLD", "ONSITE", "RESOLVED", "CANCELLED"]
REVIEW_STATUSES = ["DRAFT", "APPROVED"]
REMOVAL_STATUSES = ["REQUESTED", "SCHEDULED", "COLLECTED", "SANITIZED", "SETTLED"]


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------
_ISO_INSTANT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,9})?(Z|[+-]\d{2}:\d{2})$"
)


def _as_instant(value: Any) -> Optional[datetime]:
    """Parse an ISO 8601 UTC timestamp into an aware datetime, else return None.

    The PRD pins the *instant* a business timestamp carries — "`last_read_at`
    takes the reading's `coverage_end`", "the window must not intersect another
    period" — and pins a three-fractional-digit rendering only for the
    server-minted `created_at` / `updated_at` pair.  It never states how an
    echoed client-supplied instant is re-serialised, so `2026-09-01T00:00:00Z`
    and `2026-09-01T00:00:00.000Z` are the same asserted value.
    """
    if not isinstance(value, str) or not _ISO_INSTANT_RE.match(value):
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        return datetime.fromisoformat(text).astimezone(timezone.utc)
    except ValueError:
        return None


def assert_fields(data: Dict[str, Any], **expected) -> None:
    """Assert every named field equals its expected value, with a clear message.

    Timestamp-valued fields compare by instant rather than by byte-identical
    string, because the PRD fixes the instant and not its fractional-digit form.
    """
    for field, want in expected.items():
        assert field in data, f"response is missing field '{field}': {data}"
        got = data[field]
        if got == want:
            continue
        want_instant = _as_instant(want)
        if want_instant is not None and _as_instant(got) == want_instant:
            continue
        raise AssertionError(f"expected {field} == {want!r}, got {got!r}")


def assert_identity_fields(data: Dict[str, Any]) -> None:
    """Every record exposes a prefix-free UUID id and an ISO 8601 created_at."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID with no prefix: {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601: {data.get('created_at')!r}"


def assert_versioned_record(data: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """Records that carry the full quartet: id, created_at, updated_at, version."""
    assert_identity_fields(data)
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601: {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"
    if expected_version is not None:
        assert data["version"] == expected_version, (
            f"expected version {expected_version}, got {data['version']}"
        )


def assert_append_only_record(data: Dict[str, Any]) -> None:
    """Records that carry only id and created_at — never updated_at or version."""
    assert_identity_fields(data)
    assert "updated_at" not in data, "this record must not carry updated_at"
    assert "version" not in data, "this record must not carry version"


def assert_whole_cents(value: Any, label: str = "amount") -> None:
    """All money is expressed as a whole number of cents."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be a whole number of cents, got {value!r}"
    )


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------
def assert_service_contract(data: Dict[str, Any]) -> None:
    assert_versioned_record(data)
    assert isinstance(data["customer_name"], str) and data["customer_name"], "customer_name non-empty"
    assert 12 <= data["term_months"] <= 60, "term_months lies between 12 and 60"
    assert data["status"] in CONTRACT_STATUSES, f"unknown contract status {data['status']!r}"
    assert data["included_service_scope"] in ["BASIC", "FULL"]
    for field in (
        "minimum_mono_pages_per_period",
        "minimum_color_pages_per_period",
        "monthly_service_fee_cents",
        "labor_rate_cents_per_hour",
        "early_termination_fee_cents",
        "active_device_count",
        "consumables_committed_cents",
        "lifetime_billed_cents",
        "suspension_count",
    ):
        assert data[field] >= 0, f"{field} must be non-negative"
    assert 1 <= data["response_sla_hours_critical"] <= 72
    assert 1 <= data["response_sla_hours_standard"] <= 168
    assert data["suspension_reason"] in ["NONE", "NONPAYMENT", "DISPUTE", "CUSTOMER_REQUEST"]
    assert_whole_cents(data["true_up_balance_cents"], "true_up_balance_cents")


def assert_cost_tier(data: Dict[str, Any]) -> None:
    assert_append_only_record(data)
    assert data["page_class"] in ["MONO", "COLOR"]
    assert data["tier_index"] >= 1, "tier_index starts at 1"
    assert data["from_page"] >= 1, "from_page is at least 1"
    if data.get("to_page") is not None:
        assert data["to_page"] >= data["from_page"], "to_page is not below from_page"
    assert data["rate_micro_dollars_per_page"] >= 1


def assert_site(data: Dict[str, Any]) -> None:
    assert_versioned_record(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["address_region"], str) and data["address_region"]
    assert data["address_region"] == data["address_region"].upper(), "address_region is upper-case"
    assert data["secure_release_state"] in SECURE_RELEASE_STATES
    assert data["release_method"] in RELEASE_METHODS
    if data.get("network_vlan_tag") is not None:
        assert 1 <= data["network_vlan_tag"] <= 4094
    assert data["toner_unit_cap"] >= 1
    assert data["open_toner_units"] >= 0


def assert_spare_part_stock(data: Dict[str, Any]) -> None:
    assert_versioned_record(data)
    assert isinstance(data["part_sku"], str) and data["part_sku"]
    assert data["on_hand_qty"] >= 0, "on_hand_qty never falls below zero"
    assert data["reserved_qty"] >= 0


def assert_device(data: Dict[str, Any]) -> None:
    assert_versioned_record(data)
    assert isinstance(data["asset_tag"], str) and data["asset_tag"]
    assert isinstance(data["model_code"], str) and data["model_code"]
    assert data["lifecycle_state"] in DEVICE_LIFECYCLE_STATES
    assert data["supply_state"] in DEVICE_SUPPLY_STATES
    assert 0 <= data["toner_level_pct"] <= 100
    assert data["rated_monthly_duty_cycle"] >= 1
    for field in (
        "last_accepted_mono_meter",
        "last_accepted_color_meter",
        "lifetime_mono_pages",
        "lifetime_color_pages",
        "pages_since_last_cartridge",
        "assessed_monthly_mono_pages",
        "assessed_monthly_color_pages",
        "baseline_overhead_cents_per_month",
    ):
        assert data[field] >= 0, f"{field} must be non-negative"
    assert data["baseline_cost_micro_dollars_per_page"] >= 1
    assert isinstance(data["color_capable"], bool)
    assert isinstance(data["secure_release_enrolled"], bool)
    assert isinstance(data["refresh_due"], bool)
    assert data["right_sizing_action"] in [
        "NONE",
        "RETAIN",
        "DOWNGRADE",
        "UPGRADE",
        "CONSOLIDATE",
    ]
    if data.get("last_read_at") is not None:
        assert is_iso8601_timestamp(data["last_read_at"])


def assert_technician(data: Dict[str, Any]) -> None:
    assert_versioned_record(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["home_region"] == data["home_region"].upper(), "home_region is upper-case"
    assert data["skill_level"] in ["L1", "L2", "L3"]
    assert 0 <= data["travel_buffer_minutes"] <= 120
    assert data["open_dispatch_count"] >= 0


def assert_meter_read(data: Dict[str, Any]) -> None:
    assert_versioned_record(data)
    assert data["source"] in READ_SOURCES
    assert data["status"] in READ_STATUSES
    assert data["exception_reason"] in EXCEPTION_REASONS
    assert data["mono_meter"] >= 0 and data["color_meter"] >= 0
    assert 0 <= data["toner_level_pct"] <= 100
    assert is_iso8601_timestamp(data["coverage_start"])
    assert is_iso8601_timestamp(data["coverage_end"])
    assert data["coverage_start"] < data["coverage_end"], "coverage_start precedes coverage_end"
    assert data["mono_delta"] >= 0 and data["color_delta"] >= 0
    assert isinstance(data["submitted_by_user_id"], str) and data["submitted_by_user_id"]
    assert data["voided_reason"] in [
        "NONE",
        "WRONG_DEVICE",
        "DUPLICATE_CAPTURE",
        "CUSTOMER_DISPUTE",
    ]
    if data["status"] != "ACCEPTED":
        assert data["mono_delta"] == 0 and data["color_delta"] == 0, (
            "a reading that is not accepted carries deltas of exactly zero"
        )


def assert_billing_period(data: Dict[str, Any]) -> None:
    assert_versioned_record(data)
    assert data["status"] in PERIOD_STATUSES
    assert is_iso8601_timestamp(data["period_start"])
    assert is_iso8601_timestamp(data["period_end"])
    assert data["period_start"] < data["period_end"], "period_start precedes period_end"
    assert data["sweep_run_count"] >= 0
    assert data["exception_open_count"] >= 0


def assert_billing_statement(data: Dict[str, Any]) -> None:
    assert_versioned_record(data)
    assert data["variant"] in ["PROVISIONAL", "FINAL"]
    assert data["projection_basis"] in ["PROJECTED", "ACTUAL"]
    assert is_iso8601_timestamp(data["generated_at"])
    for field in (
        "usage_subtotal_cents",
        "shortfall_cents",
        "service_labor_cents",
        "sla_credit_cents",
        "waste_penalty_cents",
        "total_cents",
    ):
        assert_whole_cents(data[field], field)
    for field in ("mono_pages_billed", "color_pages_billed", "shortfall_pages"):
        assert data[field] >= 0, f"{field} must be non-negative"


def assert_statement_line(data: Dict[str, Any]) -> None:
    assert_append_only_record(data)
    assert data["page_class"] in ["MONO", "COLOR"]
    assert data["pages"] > 0, "a line is only emitted when pages are greater than zero"
    assert data["rate_micro_dollars_per_page"] >= 0
    assert_whole_cents(data["amount_cents"], "amount_cents")


def assert_consumable_order(data: Dict[str, Any]) -> None:
    assert_versioned_record(data)
    assert data["part_type"] in ["TONER_BLACK", "TONER_COLOR"]
    assert 1 <= data["quantity"] <= 3
    assert data["unit_price_cents"] >= 1
    assert data["status"] in ORDER_STATUSES
    assert data["trigger_source"] in ["AUTO_THRESHOLD", "MANUAL"]
    assert data["committed_cents"] == data["quantity"] * data["unit_price_cents"], (
        "committed_cents is quantity multiplied by unit_price_cents"
    )
    assert isinstance(data["waste_flagged"], bool)
    assert data["pages_since_last_cartridge_at_order"] >= 0
    assert data["cancel_reason"] in [
        "NONE",
        "HOARDING_CONTROL",
        "WRONG_PART",
        "DEVICE_REMOVED",
        "READ_VOIDED",
    ]


def assert_service_ticket(data: Dict[str, Any]) -> None:
    assert_versioned_record(data)
    assert data["severity"] in ["CRITICAL", "STANDARD"]
    assert data["status"] in TICKET_STATUSES
    assert isinstance(data["symptom_code"], str) and data["symptom_code"]
    assert is_iso8601_timestamp(data["opened_at"])
    assert is_iso8601_timestamp(data["respond_by"])
    assert data["parts_hold_hours"] >= 0
    assert data["hours_late"] >= 0, "hours_late is floored at zero"
    assert data["labor_hours"] >= 0
    assert_whole_cents(data["labor_cents"], "labor_cents")
    assert_whole_cents(data["sla_credit_cents"], "sla_credit_cents")


def assert_quarterly_review(data: Dict[str, Any]) -> None:
    assert_versioned_record(data)
    assert data["status"] in REVIEW_STATUSES
    assert isinstance(data["authored_by_user_id"], str) and data["authored_by_user_id"]
    assert_whole_cents(data["baseline_savings_cents"], "baseline_savings_cents")
    assert_whole_cents(data["realized_savings_cents"], "realized_savings_cents")
    for field in (
        "retain_count",
        "downgrade_count",
        "upgrade_count",
        "consolidate_count",
        "refresh_due_device_count",
    ):
        assert data[field] >= 0, f"{field} must be non-negative"
    assert data["refresh_due_device_count"] == data["upgrade_count"] + data["consolidate_count"], (
        "refresh_due_device_count is the sum of the upgrade and consolidate counts"
    )


def assert_removal_order(data: Dict[str, Any]) -> None:
    assert_versioned_record(data)
    assert data["status"] in REMOVAL_STATUSES
    assert data["sanitization_method"] in [
        "NONE",
        "CRYPTO_ERASE",
        "OVERWRITE_3PASS",
        "PHYSICAL_DESTRUCTION",
    ]
    assert data["device_count"] >= 0
    for field in (
        "unbilled_pages_charge_cents",
        "early_termination_fee_applied_cents",
        "device_residual_credit_cents",
        "gross_settlement_cents",
        "sanitization_fee_cents",
        "net_settlement_cents",
    ):
        assert_whole_cents(data[field], field)


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------
def assert_device_dimensions(data: Dict[str, Any], lifecycle_state: str, supply_state: str) -> None:
    """The two device dimensions move independently; assert both at once."""
    assert data["lifecycle_state"] == lifecycle_state, (
        f"expected lifecycle_state {lifecycle_state}, got {data['lifecycle_state']}"
    )
    assert data["supply_state"] == supply_state, (
        f"expected supply_state {supply_state}, got {data['supply_state']}"
    )


def assert_statement_total_is_consistent(statement: Dict[str, Any]) -> None:
    """total_cents is usage plus shortfall plus labour plus waste, less the SLA credit."""
    expected = (
        statement["usage_subtotal_cents"]
        + statement["shortfall_cents"]
        + statement["service_labor_cents"]
        + statement["waste_penalty_cents"]
        - statement["sla_credit_cents"]
    )
    assert statement["total_cents"] == expected, (
        f"total_cents should be {expected}, got {statement['total_cents']}"
    )


def assert_lines_sum_to_usage_subtotal(lines, statement: Dict[str, Any]) -> None:
    """Every line amount is rounded first; the subtotal is their sum."""
    total = sum(line["amount_cents"] for line in lines)
    assert statement["usage_subtotal_cents"] == total, (
        f"usage_subtotal_cents should equal the sum of line amounts ({total}), "
        f"got {statement['usage_subtotal_cents']}"
    )


def assert_settlement_waterfall(order: Dict[str, Any]) -> None:
    """The settlement waterfall is pinned: gross excludes the sanitization fee."""
    expected_gross = (
        order["unbilled_pages_charge_cents"]
        + order["early_termination_fee_applied_cents"]
        - order["device_residual_credit_cents"]
    )
    assert order["gross_settlement_cents"] == expected_gross, (
        f"gross_settlement_cents should be {expected_gross}, got {order['gross_settlement_cents']}"
    )
    expected_net = order["gross_settlement_cents"] + order["sanitization_fee_cents"]
    assert order["net_settlement_cents"] == expected_net, (
        f"net_settlement_cents should be {expected_net}, got {order['net_settlement_cents']}"
    )
