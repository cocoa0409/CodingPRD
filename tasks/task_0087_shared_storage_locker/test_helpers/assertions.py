"""Entity assertions and domain invariant checkers.

Per PRD §2.4: Cabinet, Compartment, Rental, InsuranceClaim, RepairTicket
carry id/created_at/updated_at/version. PricingProfile, RevenueRecord,
AuditEvent are immutable and carry only id + created_at.
"""
from __future__ import annotations

from typing import Iterable, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Common-field assertion helpers
# ---------------------------------------------------------------------------
def _assert_mutable_common(data: dict, entity_label: str) -> None:
    """Assert id/created_at/updated_at/version present and well-formed."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_label}.id must be valid UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_label}.updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), (
        f"{entity_label}.version must be integer, got {type(data.get('version'))}"
    )
    assert data["version"] >= 0, (
        f"{entity_label}.version must be non-negative, got {data['version']}"
    )


def _assert_immutable_common(data: dict, entity_label: str) -> None:
    """Assert id + created_at present and well-formed for immutable rows."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_label}.id must be valid UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    )


# ---------------------------------------------------------------------------
# Cabinet
# ---------------------------------------------------------------------------
def assert_cabinet(data: dict) -> None:
    _assert_mutable_common(data, "Cabinet")
    assert isinstance(data["location_code"], str) and data["location_code"]
    assert isinstance(data["latitude"], (int, float))
    assert isinstance(data["longitude"], (int, float))
    assert isinstance(data["partner_id"], str) and data["partner_id"]
    assert isinstance(data["partner_share_pct"], (int, float))
    assert 0 <= data["partner_share_pct"] <= 100
    assert isinstance(data["firmware_version"], str)
    assert data["online_status"] in ("ONLINE", "DEGRADED", "OFFLINE")
    assert data["capacity_alert_level"] in ("NONE", "WARNING", "CRITICAL")
    # last_heartbeat_at may be null until the first heartbeat.
    lhb = data.get("last_heartbeat_at")
    if lhb is not None:
        assert is_iso8601_timestamp(lhb)
    # Capacity counters
    for f in (
        "total_compartments",
        "small_capacity_total",
        "medium_capacity_total",
        "large_capacity_total",
    ):
        assert isinstance(data[f], int) and data[f] >= 0, (
            f"Cabinet.{f} must be non-negative integer, got {data[f]!r}"
        )
    # Occupancy percentages 2dp
    for f in (
        "small_occupancy_pct",
        "medium_occupancy_pct",
        "large_occupancy_pct",
    ):
        v = data[f]
        assert isinstance(v, (int, float)) and v >= 0
        # 2dp precision check.
        rounded = round(v, 2)
        assert abs(rounded - v) < 1e-9, (
            f"Cabinet.{f} must be 2dp, got {v}"
        )


def assert_cabinet_capacity_alert_invariant(data: dict) -> None:
    """PRD §3.7: tier each size-class pct via WARNING_PCT=80 / CRITICAL_PCT=95
    (>= semantics); overall = max severity."""
    def level_for(pct: float) -> str:
        if pct >= 95.0:
            return "CRITICAL"
        if pct >= 80.0:
            return "WARNING"
        return "NONE"

    sev_rank = {"NONE": 0, "WARNING": 1, "CRITICAL": 2}
    derived = max(
        (
            level_for(data["small_occupancy_pct"]),
            level_for(data["medium_occupancy_pct"]),
            level_for(data["large_occupancy_pct"]),
        ),
        key=lambda x: sev_rank[x],
    )
    assert data["capacity_alert_level"] == derived, (
        f"capacity_alert_level={data['capacity_alert_level']!r} but the "
        f"three occupancy_pct values "
        f"({data['small_occupancy_pct']}, {data['medium_occupancy_pct']}, "
        f"{data['large_occupancy_pct']}) imply {derived!r}"
    )


# ---------------------------------------------------------------------------
# Compartment
# ---------------------------------------------------------------------------
def assert_compartment(data: dict) -> None:
    _assert_mutable_common(data, "Compartment")
    assert isinstance(data["cabinet_id"], str)
    assert isinstance(data["slot_number"], int) and data["slot_number"] >= 1
    assert data["size_class"] in ("SMALL", "MEDIUM", "LARGE")
    assert data["operational_status"] in ("OK", "FAULT")
    assert data["occupancy_status"] in ("IDLE", "RENTED", "OVERDUE", "HOLDING")
    fc = data.get("fault_category")
    if fc is not None:
        assert fc in (
            "DOOR_NOT_CLOSED", "SENSOR_FAULT",
            "COMMUNICATION_LOSS", "USER_REPORTED",
        )
    # PRD §3.2: when IDLE / HOLDING, active_rental_id must be null.
    if data["occupancy_status"] in ("IDLE", "HOLDING"):
        assert data.get("active_rental_id") in (None, ""), (
            f"Compartment.active_rental_id must be null when "
            f"occupancy_status={data['occupancy_status']}, got "
            f"{data.get('active_rental_id')!r}"
        )


# ---------------------------------------------------------------------------
# PricingProfile (immutable)
# ---------------------------------------------------------------------------
def assert_pricing_profile(data: dict) -> None:
    _assert_immutable_common(data, "PricingProfile")
    # PRD §2.4: no updated_at, no version.
    assert "updated_at" not in data or data.get("updated_at") is None, (
        "PricingProfile must NOT carry updated_at (PRD §2.4)"
    )
    assert "version" not in data or data.get("version") is None, (
        "PricingProfile must NOT carry version (PRD §2.4)"
    )
    assert data["size_class"] in ("SMALL", "MEDIUM", "LARGE")
    assert data["rental_mode"] in ("HOURLY", "DAILY", "MONTHLY")
    assert isinstance(data["unit_price_cents"], int)
    assert data["unit_price_cents"] > 0
    assert isinstance(data["deposit_cents"], int) and data["deposit_cents"] >= 0
    assert isinstance(data["grace_minutes"], int) and data["grace_minutes"] >= 0
    assert isinstance(data["overdue_rate_cents_per_hour"], int)
    assert data["overdue_rate_cents_per_hour"] >= 0
    assert isinstance(data["forced_clearance_hours"], int)


# ---------------------------------------------------------------------------
# Rental
# ---------------------------------------------------------------------------
def assert_rental(data: dict) -> None:
    _assert_mutable_common(data, "Rental")
    assert isinstance(data["renter_id"], str) and data["renter_id"]
    assert isinstance(data["compartment_id"], str)
    assert isinstance(data["cabinet_id"], str)
    assert data["size_class"] in ("SMALL", "MEDIUM", "LARGE")
    assert data["rental_mode"] in ("HOURLY", "DAILY", "MONTHLY")
    assert data["status"] in (
        "ACTIVE", "EXPIRING_SOON", "OVERDUE",
        "RETURNED", "FORCE_CLEARED", "REFUNDED",
    )
    assert data["insurance_tier"] in ("NONE", "BASIC", "PREMIUM")
    assert isinstance(data["billing_units"], int) and data["billing_units"] >= 1

    # Snapshot fields are integer cents.
    for f in (
        "unit_price_cents_snapshot",
        "deposit_cents_snapshot",
        "grace_minutes_snapshot",
        "overdue_rate_snapshot",
        "forced_clearance_hours_snapshot",
        "declared_value_cents",
        "insurance_premium_cents",
        "rental_fee_cents",
        "total_charged_cents",
        "overdue_fee_cents",
        "deposit_forfeited_cents",
        "deposit_refunded_cents",
        "renewal_count",
    ):
        assert isinstance(data[f], int), (
            f"Rental.{f} must be integer, got {data[f]!r}"
        )
        assert data[f] >= 0, f"Rental.{f} must be non-negative, got {data[f]}"

    # PRD §3.4: total_charged_cents = rental_fee + insurance_premium + deposit
    # at creation (renewals add to rental_fee; total_charged not redefined for
    # renewal — assert this only on the freshly-created rental).
    assert is_iso8601_timestamp(data["started_at"])
    assert is_iso8601_timestamp(data["original_expires_at"])
    assert is_iso8601_timestamp(data["current_expires_at"])
    ea = data.get("ended_at")
    if ea is not None:
        assert is_iso8601_timestamp(ea)
    rsa = data.get("reminder_sent_at")
    if rsa is not None:
        assert is_iso8601_timestamp(rsa)


def assert_rental_total_charged_on_create(rental: dict) -> None:
    """PRD §3.4: 'The total charged at creation is the rental fee plus the
    insurance premium plus the deposit snapshot, stored as total_charged_cents.'

    Use only immediately after creation (before any renewal)."""
    expected = (
        rental["rental_fee_cents"]
        + rental["insurance_premium_cents"]
        + rental["deposit_cents_snapshot"]
    )
    assert rental["total_charged_cents"] == expected, (
        f"total_charged_cents={rental['total_charged_cents']} but "
        f"rental_fee_cents + insurance_premium_cents + deposit_cents_snapshot"
        f" = {expected}"
    )


# ---------------------------------------------------------------------------
# InsuranceClaim
# ---------------------------------------------------------------------------
def assert_insurance_claim(data: dict) -> None:
    _assert_mutable_common(data, "InsuranceClaim")
    assert isinstance(data["rental_id"], str)
    assert isinstance(data["renter_id"], str)
    assert data["claim_type"] in ("DAMAGE", "LOSS", "THEFT")
    assert isinstance(data["claimed_amount_cents"], int)
    assert data["claimed_amount_cents"] > 0
    assert isinstance(data["evidence_count"], int) and data["evidence_count"] >= 0
    assert data["status"] in (
        "REPORTED", "EVIDENCE_PENDING", "UNDER_REVIEW",
        "EVIDENCE_REJECTED", "APPROVED", "DENIED", "PAID",
    )
    p = data.get("payout_cents")
    if p is not None:
        assert isinstance(p, int) and p >= 0


# ---------------------------------------------------------------------------
# RepairTicket
# ---------------------------------------------------------------------------
def assert_repair_ticket(data: dict) -> None:
    _assert_mutable_common(data, "RepairTicket")
    assert isinstance(data["compartment_id"], str)
    assert data["fault_category"] in (
        "DOOR_NOT_CLOSED", "SENSOR_FAULT",
        "COMMUNICATION_LOSS", "USER_REPORTED",
    )
    assert data["status"] in (
        "OPEN", "DISPATCHED", "REPAIRED", "ACCEPTED", "REJECTED",
    )
    assert data["reporter_role"] in ("RENTER", "SYSTEM", "OPERATOR")
    at = data.get("accepted_at")
    if at is not None:
        assert is_iso8601_timestamp(at)


# ---------------------------------------------------------------------------
# RevenueRecord (immutable)
# ---------------------------------------------------------------------------
def assert_revenue_record(data: dict) -> None:
    _assert_immutable_common(data, "RevenueRecord")
    assert "updated_at" not in data or data.get("updated_at") is None
    assert "version" not in data or data.get("version") is None
    assert data["revenue_kind"] in (
        "RENTAL_FEE", "OVERDUE_FEE", "DEPOSIT_FORFEIT", "REFUND_REVERSAL",
    )
    assert isinstance(data["gross_cents"], int)
    assert isinstance(data["partner_share_cents"], int)
    assert isinstance(data["platform_share_cents"], int)
    # PRD §2.12: row-level invariant: partner + platform == gross,
    # including for negative-gross refund-reversal rows.
    assert (data["partner_share_cents"] + data["platform_share_cents"]
            == data["gross_cents"]), (
        f"RevenueRecord row invariant violated: partner={data['partner_share_cents']} "
        f"+ platform={data['platform_share_cents']} != gross={data['gross_cents']}"
    )
    assert is_iso8601_timestamp(data["occurred_at"])


# ---------------------------------------------------------------------------
# AuditEvent (immutable)
# ---------------------------------------------------------------------------
def assert_audit_event(data: dict) -> None:
    _assert_immutable_common(data, "AuditEvent")
    assert "updated_at" not in data or data.get("updated_at") is None
    assert "version" not in data or data.get("version") is None
    assert data["event_kind"] in ("COMPARTMENT_OPENED", "FORCE_CLEARANCE")
    assert data["subject_type"] in ("Compartment", "Rental")
    assert isinstance(data["subject_id"], str)
    assert isinstance(data["actor_id"], str)
    uc = data.get("unlock_channel")
    if uc is not None:
        assert uc in ("QR", "BLUETOOTH", "PASSWORD", "OPERATOR_OVERRIDE")
    assert is_iso8601_timestamp(data["occurred_at"])


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------
def assert_version_increases(new_data: dict, old_data: dict) -> None:
    """OCC version monotonicity across one mutation."""
    assert new_data["version"] > old_data["version"], (
        f"Version did not increase: {old_data['version']} → {new_data['version']}"
    )


def assert_updated_at_advanced(new_data: dict, old_data: dict) -> None:
    """updated_at must refresh on any mutation."""
    assert new_data["updated_at"] >= old_data["updated_at"], (
        f"updated_at did not refresh: {old_data['updated_at']} → "
        f"{new_data['updated_at']}"
    )


def select_rows(rows: Iterable[dict], **filters) -> list:
    out = []
    for r in rows:
        if all(r.get(k) == v for k, v in filters.items()):
            out.append(r)
    return out


def find_row(rows: Iterable[dict], **filters) -> Optional[dict]:
    matches = select_rows(rows, **filters)
    return matches[0] if matches else None


__all__ = [
    "assert_cabinet",
    "assert_cabinet_capacity_alert_invariant",
    "assert_compartment",
    "assert_pricing_profile",
    "assert_rental",
    "assert_rental_total_charged_on_create",
    "assert_insurance_claim",
    "assert_repair_ticket",
    "assert_revenue_record",
    "assert_audit_event",
    "assert_version_increases",
    "assert_updated_at_advanced",
    "select_rows",
    "find_row",
]
