"""Entity assertions and domain invariant checkers (PRD §2.5, §2.8, §3)."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AlertStatus,
    AmountBasis,
    ChargebackStatus,
    ClaimStatus,
    DefectResponsibility,
    DenialReasonCode,
    DeterminedTier,
    DisputeOutcome,
    ItemCategory,
    ReserveEntryKind,
    ServiceRequestStatus,
    Severity,
    Trade,
    WarrantyProgram,
    WorkOrderStatus,
)


# ─── Instant / date comparison helpers ─────────────────
# The PRD pins instants and calendar dates (§2.4, §3.x) but renders common-field
# timestamps with three fractional digits while writing deadline instants at
# second precision; comparisons are therefore done on the parsed instant, never
# on the raw string.

def _parse_instant(value):
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def assert_instant_equal(actual, expected_iso, label="timestamp"):
    """Assert two ISO 8601 values denote the same instant (PRD §2.4)."""
    actual_dt = _parse_instant(actual)
    expected_dt = _parse_instant(expected_iso)
    assert actual_dt is not None, (
        f"{label}: {actual!r} is not a parseable ISO 8601 timestamp"
    )
    assert expected_dt is not None, f"{label}: bad expectation {expected_iso!r}"
    assert actual_dt == expected_dt, (
        f"{label}: expected instant {expected_iso}, got {actual!r}"
    )


def assert_date_equal(actual, expected_date, label="date"):
    """Assert a date- or datetime-valued field carries the expected calendar date."""
    assert isinstance(actual, str), f"{label}: expected a string, got {type(actual)}"
    assert actual[:10] == expected_date, (
        f"{label}: expected date {expected_date}, got {actual!r}"
    )


# ─── Common-field shapes ───────────────────────────────

def _assert_common_fields(data, label):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer >= 1"
    )


def assert_homeowner(data):
    _assert_common_fields(data, "homeowner")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]


def assert_home(data):
    _assert_common_fields(data, "home")
    assert is_valid_uuid(data.get("homeowner_id", "")), "home.homeowner_id UUID"
    assert isinstance(data["lot_number"], str) and data["lot_number"]
    assert isinstance(data["community_name"], str) and data["community_name"]
    assert isinstance(data["sale_price_cents"], int) and data["sale_price_cents"] > 0
    assert data["warranty_program"] in [p.value for p in WarrantyProgram]
    for field in ("workmanship_end_date", "systems_end_date", "structural_end_date"):
        assert isinstance(data.get(field), str) and data[field], (
            f"home.{field} must be present"
        )


def assert_service_request(data):
    _assert_common_fields(data, "service_request")
    assert is_valid_uuid(data.get("home_id", "")), "service_request.home_id UUID"
    assert is_valid_uuid(data.get("homeowner_id", "")), (
        "service_request.homeowner_id UUID"
    )
    assert data["item_category"] in [c.value for c in ItemCategory]
    assert data["severity"] in [s.value for s in Severity]
    assert data["status"] in [s.value for s in ServiceRequestStatus]
    assert _parse_instant(data.get("reported_at")) is not None, (
        "service_request.reported_at must be a timestamp"
    )
    assert _parse_instant(data.get("response_due_at")) is not None, (
        "service_request.response_due_at must be a timestamp"
    )
    assert isinstance(data["response_breached"], bool)
    assert isinstance(data["completion_breached"], bool)
    assert isinstance(data["escalation_level"], int)
    assert isinstance(data["reopened_count"], int)
    if data.get("determined_tier") is not None:
        assert data["determined_tier"] in [t.value for t in DeterminedTier]
    if data.get("denial_reason_code") is not None:
        assert data["denial_reason_code"] in [d.value for d in DenialReasonCode]
    if data.get("dispute_outcome") is not None:
        assert data["dispute_outcome"] in [d.value for d in DisputeOutcome]


def assert_work_order(data):
    _assert_common_fields(data, "work_order")
    assert is_valid_uuid(data.get("service_request_id", "")), "work_order parent UUID"
    assert is_valid_uuid(data.get("trade_partner_id", "")), "work_order partner UUID"
    assert data["status"] in [s.value for s in WorkOrderStatus]
    assert data["defect_responsibility"] in [d.value for d in DefectResponsibility]
    assert isinstance(data["estimated_cost_cents"], int)
    assert data["estimated_cost_cents"] >= 0
    assert isinstance(data["duration_minutes"], int) and data["duration_minutes"] > 0


def assert_trade_partner(data):
    _assert_common_fields(data, "trade_partner")
    assert isinstance(data["company_name"], str) and data["company_name"]
    assert data["trade"] in [t.value for t in Trade]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert isinstance(data["daily_capacity_minutes"], int)
    assert data["daily_capacity_minutes"] > 0
    assert isinstance(data["open_work_order_count"], int)
    assert data["open_work_order_count"] >= 0
    assert isinstance(data["outstanding_chargeback_cents"], int)
    assert data["outstanding_chargeback_cents"] >= 0


def assert_chargeback(data):
    _assert_common_fields(data, "chargeback")
    assert is_valid_uuid(data.get("work_order_id", "")), "chargeback work order UUID"
    assert is_valid_uuid(data.get("trade_partner_id", "")), "chargeback partner UUID"
    assert data["status"] in [s.value for s in ChargebackStatus]
    assert data["amount_basis"] in [b.value for b in AmountBasis]
    assert isinstance(data["provisional_amount_cents"], int)
    assert isinstance(data["payable_amount_cents"], int)
    assert isinstance(data["collected_cents"], int)
    assert isinstance(data["outstanding_cents"], int)


def assert_warranty_reserve(data):
    _assert_common_fields(data, "warranty_reserve")
    assert is_valid_uuid(data.get("home_id", "")), "warranty_reserve.home_id UUID"
    assert data["alert_status"] in [a.value for a in AlertStatus]
    assert isinstance(data["expected_lifetime_accrual_cents"], int)
    assert isinstance(data["accrued_to_date_cents"], int)
    assert isinstance(data["drawn_to_date_cents"], int)
    assert isinstance(data["recovered_to_date_cents"], int)
    assert isinstance(data["balance_cents"], int)
    assert isinstance(data["last_accrual_month_index"], int)


def assert_reserve_entry(data):
    """Ledger lines carry only id + created_at (PRD §2.5): no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "reserve_entry.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "reserve_entry.created_at must be ISO 8601"
    )
    assert "updated_at" not in data, "reserve_entry must NOT carry updated_at"
    assert "version" not in data, "reserve_entry must NOT carry version"
    assert data["kind"] in [k.value for k in ReserveEntryKind]
    assert isinstance(data["amount_cents"], int)


def assert_administrator_claim(data):
    _assert_common_fields(data, "administrator_claim")
    assert is_valid_uuid(data.get("service_request_id", "")), "claim request UUID"
    assert is_valid_uuid(data.get("home_id", "")), "claim home UUID"
    assert data["status"] in [s.value for s in ClaimStatus]
    assert isinstance(data["claimed_amount_cents"], int)
    assert data["claimed_amount_cents"] > 0


# ─── Domain invariants ─────────────────────────────────

def assert_ledger_conservation(reserve, entries):
    """balance_cents equals the signed sum of all entries (PRD §2.8)."""
    signed_sum = sum(e["amount_cents"] for e in entries)
    assert reserve["balance_cents"] == signed_sum, (
        f"Ledger conservation violated: balance {reserve['balance_cents']} "
        f"!= signed entry sum {signed_sum}"
    )
