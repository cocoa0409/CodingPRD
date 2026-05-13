"""Per-entity assertions for the EV Charging API.

PRD §2.4 splits entities into two field-shapes:

- Versioned (carry id + created_at + updated_at + version):
  Operator, Station, Pile, Member, Reservation, QueueEntry,
  ChargingSession, FaultReport, RepairTicket, Payout.

- Append-only (carry id + created_at ONLY; no updated_at, no version):
  PricingVersion, PromoActivity, ChargingCurvePoint,
  SettlementLedgerEntry, AuditLog, ExternalEventInbox.
"""
from __future__ import annotations
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Shape checkers
# ---------------------------------------------------------------------------
def _check_versioned_fields(data: Dict[str, Any], entity: str) -> None:
    """PRD §2.4 versioned shape: id, created_at, updated_at, version."""
    assert "id" in data, f"{entity} missing id"
    assert is_valid_uuid(data["id"]), (
        f"{entity}.id must be UUID, got {data['id']!r}"
    )
    assert "created_at" in data and is_iso8601_timestamp(
        data["created_at"]
    ), f"{entity}.created_at must be ISO 8601 UTC"
    assert "updated_at" in data and is_iso8601_timestamp(
        data["updated_at"]
    ), f"{entity}.updated_at must be ISO 8601 UTC"
    assert "version" in data, f"{entity} missing version"
    assert isinstance(data["version"], int) and data["version"] >= 1, (
        f"{entity}.version must be >= 1, got {data.get('version')!r}"
    )


def _check_append_only_fields(data: Dict[str, Any], entity: str) -> None:
    """PRD §2.4 append-only shape: id + created_at ONLY."""
    assert "id" in data, f"{entity} missing id"
    assert is_valid_uuid(data["id"]), (
        f"{entity}.id must be UUID, got {data['id']!r}"
    )
    assert "created_at" in data and is_iso8601_timestamp(
        data["created_at"]
    ), f"{entity}.created_at must be ISO 8601 UTC"


# ---------------------------------------------------------------------------
# Constants / allowed enum sets
# ---------------------------------------------------------------------------
OPERATOR_ROLE_KINDS = {"PLATFORM", "STATION_OWNER", "ROAMING_PARTNER"}
STATION_STATES = {"ACTIVE", "SUSPENDED"}
PILE_LIFECYCLE_STATES = {"OFF_SHELF", "ON_SHELF", "DECOMMISSIONED"}
PILE_OPERATIONAL_STATES = {"IDLE", "IN_USE", "FAULT", "OFFLINE"}
CONNECTOR_TYPES = {"GBT_DC", "GBT_AC", "CCS2", "CHADEMO"}
MEMBER_TIERS = {"BASIC", "SILVER", "GOLD", "PLATINUM"}
RESERVATION_STATES = {"HELD", "ACTIVATED", "EXPIRED", "CANCELLED"}
QUEUE_STATES = {"WAITING", "PROMOTED", "ABANDONED"}
SESSION_STATES = {"PENDING_AUTH", "CHARGING", "SETTLING", "SETTLED",
                  "ABORTED"}
AUTH_METHODS = {"APP", "RFID", "PLUG_AND_CHARGE"}
WINDOW_TAGS = {"PEAK", "FLAT", "VALLEY"}
ABNORMAL_EVENT_TYPES = {"OVER_TEMPERATURE", "COMMUNICATION_LOSS"}
FAULT_REPORTER_KINDS = {"USER", "AUTO_DETECT"}
FAULT_SEVERITIES = {"MINOR", "MAJOR", "CRITICAL"}
FAULT_STATES = {"OPEN", "ISOLATED", "RESOLVED"}
REPAIR_TICKET_STATES = {
    "OPEN", "DISPATCHED", "IN_REPAIR", "AWAITING_ACCEPTANCE", "CLOSED",
    "REJECTED",
}
COUNTERPARTY_KINDS = {
    "STATION_OWNER_SHARE", "PLATFORM_SERVICE_FEE",
    "ROAMING_PARTNER", "TAX_AUTHORITY",
}
LEDGER_REASONS = {
    "SESSION_SETTLE", "REFUND_REVERSAL", "PAYOUT", "NO_SHOW_PENALTY",
}
PAYOUT_STATES = {"PENDING", "ISSUED", "REVERSED"}
AUDIT_EVENT_KINDS = {"BILLING_ADJUSTMENT", "FAULT_EVENT"}
SOURCE_SYSTEMS = {"PAYMENT", "MAPPING", "GRID"}


# ---------------------------------------------------------------------------
# Operator
# ---------------------------------------------------------------------------
def assert_operator(data: Dict[str, Any]) -> None:
    _check_versioned_fields(data, "Operator")
    assert isinstance(data.get("name"), str) and data["name"]
    assert data.get("role_kind") in OPERATOR_ROLE_KINDS, (
        f"Operator.role_kind must be in {OPERATOR_ROLE_KINDS}, "
        f"got {data.get('role_kind')!r}"
    )
    assert isinstance(data.get("tax_id"), str) and data["tax_id"]


# ---------------------------------------------------------------------------
# Station
# ---------------------------------------------------------------------------
def assert_station(data: Dict[str, Any]) -> None:
    _check_versioned_fields(data, "Station")
    assert isinstance(data.get("name"), str) and data["name"]
    assert is_valid_uuid(data.get("operator_id", "")), (
        f"Station.operator_id must be UUID, got {data.get('operator_id')!r}"
    )
    assert is_valid_uuid(data.get("station_owner_id", "")), (
        f"Station.station_owner_id must be UUID, "
        f"got {data.get('station_owner_id')!r}"
    )
    lat = data.get("latitude")
    lon = data.get("longitude")
    assert isinstance(lat, (int, float)) and -90.0 <= float(lat) <= 90.0
    assert isinstance(lon, (int, float)) and -180.0 <= float(lon) <= 180.0
    assert isinstance(data.get("revenue_share_bps"), int)
    assert 0 <= data["revenue_share_bps"] <= 10000, (
        f"Station.revenue_share_bps must be 0..10000, "
        f"got {data['revenue_share_bps']}"
    )
    assert data.get("status") in STATION_STATES


# ---------------------------------------------------------------------------
# Pile
# ---------------------------------------------------------------------------
def assert_pile(data: Dict[str, Any]) -> None:
    """PRD §3.1: pile carries the orthogonal lifecycle_state and
    operational_state pair; operational_state is null when lifecycle is
    OFF_SHELF or DECOMMISSIONED."""
    _check_versioned_fields(data, "Pile")
    assert is_valid_uuid(data.get("station_id", "")), (
        f"Pile.station_id must be UUID, got {data.get('station_id')!r}"
    )
    assert isinstance(data.get("model_code"), str) and data["model_code"]
    rpw = data.get("rated_power_kw")
    assert isinstance(rpw, (int, float))
    assert float(rpw) > 0.0 and float(rpw) <= 360.0, (
        f"Pile.rated_power_kw must be in (0, 360], got {rpw!r}"
    )
    assert data.get("connector_type") in CONNECTOR_TYPES
    assert isinstance(data.get("firmware_version"), str)
    lifecycle = data.get("lifecycle_state")
    assert lifecycle in PILE_LIFECYCLE_STATES, (
        f"Pile.lifecycle_state must be in {PILE_LIFECYCLE_STATES}, "
        f"got {lifecycle!r}"
    )
    op = data.get("operational_state")
    if lifecycle == "ON_SHELF":
        assert op in PILE_OPERATIONAL_STATES, (
            f"Pile.operational_state must be in {PILE_OPERATIONAL_STATES} "
            f"when lifecycle_state == ON_SHELF, got {op!r}"
        )
    else:
        # PRD §3.1: 'The operational_state is meaningful only while
        # lifecycle_state is ON_SHELF and is otherwise null.'
        assert op is None, (
            f"Pile.operational_state must be null when "
            f"lifecycle_state == {lifecycle}, got {op!r}"
        )


# ---------------------------------------------------------------------------
# Member
# ---------------------------------------------------------------------------
def assert_member(data: Dict[str, Any]) -> None:
    _check_versioned_fields(data, "Member")
    assert isinstance(data.get("display_name"), str) and data["display_name"]
    assert is_valid_uuid(data.get("home_operator_id", "")), (
        f"Member.home_operator_id must be UUID, "
        f"got {data.get('home_operator_id')!r}"
    )
    assert data.get("tier") in MEMBER_TIERS, (
        f"Member.tier must be in {MEMBER_TIERS}, got {data.get('tier')!r}"
    )
    strikes = data.get("no_show_strikes")
    assert isinstance(strikes, int) and strikes >= 0, (
        f"Member.no_show_strikes must be int >= 0, got {strikes!r}"
    )
    wallet = data.get("wallet_balance_cents")
    assert isinstance(wallet, int) and wallet >= 0, (
        f"Member.wallet_balance_cents must be int >= 0, got {wallet!r}"
    )


# ---------------------------------------------------------------------------
# Reservation
# ---------------------------------------------------------------------------
def assert_reservation(data: Dict[str, Any]) -> None:
    _check_versioned_fields(data, "Reservation")
    assert is_valid_uuid(data.get("pile_id", ""))
    assert is_valid_uuid(data.get("member_id", ""))
    assert is_iso8601_timestamp(data.get("hold_expires_at", "")), (
        f"Reservation.hold_expires_at must be ISO 8601, "
        f"got {data.get('hold_expires_at')!r}"
    )
    assert data.get("status") in RESERVATION_STATES
    penalty = data.get("no_show_penalty_cents", 0)
    assert isinstance(penalty, int) and penalty >= 0


# ---------------------------------------------------------------------------
# Queue entry
# ---------------------------------------------------------------------------
def assert_queue_entry(data: Dict[str, Any]) -> None:
    _check_versioned_fields(data, "QueueEntry")
    assert is_valid_uuid(data.get("station_id", ""))
    assert is_valid_uuid(data.get("member_id", ""))
    pos = data.get("position")
    assert isinstance(pos, int) and pos >= 1, (
        f"QueueEntry.position must be int >= 1, got {pos!r}"
    )
    assert data.get("status") in QUEUE_STATES
    assert is_iso8601_timestamp(data.get("enqueued_at", "")), (
        f"QueueEntry.enqueued_at must be ISO 8601"
    )


# ---------------------------------------------------------------------------
# Charging session
# ---------------------------------------------------------------------------
def assert_charging_session(data: Dict[str, Any]) -> None:
    _check_versioned_fields(data, "ChargingSession")
    assert is_valid_uuid(data.get("pile_id", ""))
    assert is_valid_uuid(data.get("member_id", ""))
    res_id = data.get("reservation_id")
    if res_id is not None:
        assert is_valid_uuid(res_id), (
            f"ChargingSession.reservation_id must be UUID or null, "
            f"got {res_id!r}"
        )
    assert data.get("auth_method") in AUTH_METHODS
    assert data.get("status") in SESSION_STATES
    for f in ("peak_kwh_milli", "flat_kwh_milli", "valley_kwh_milli",
              "electricity_fee_cents", "service_fee_cents",
              "tax_cents", "total_cents"):
        v = data.get(f, 0)
        assert isinstance(v, int) and v >= 0, (
            f"ChargingSession.{f} must be int >= 0, got {v!r}"
        )
    events = data.get("abnormal_events", [])
    assert isinstance(events, list)
    for ev in events:
        assert isinstance(ev, dict)
        assert ev.get("type") in ABNORMAL_EVENT_TYPES


def assert_session_terminal_zero_fees(data: Dict[str, Any]) -> None:
    """PRD §3.4: 'no electricity_fee / service_fee charged; total_cents = 0'
    on the ABORTED branch."""
    assert data["status"] == "ABORTED", (
        f"expected ABORTED, got {data['status']}"
    )
    assert data["electricity_fee_cents"] == 0
    assert data["service_fee_cents"] == 0
    assert data["tax_cents"] == 0
    assert data["total_cents"] == 0


def assert_session_settlement_consistent(data: Dict[str, Any]) -> None:
    """PRD §3.4 step D: 'total_cents is the sum of electricity_fee_cents,
    service_fee_cents, and tax_cents.'"""
    expected_total = (
        data["electricity_fee_cents"]
        + data["service_fee_cents"]
        + data["tax_cents"]
    )
    assert data["total_cents"] == expected_total, (
        f"total_cents must equal electricity+service+tax "
        f"({expected_total}), got {data['total_cents']}"
    )


# ---------------------------------------------------------------------------
# Pricing version (append-only)
# ---------------------------------------------------------------------------
def assert_pricing_version(data: Dict[str, Any]) -> None:
    _check_append_only_fields(data, "PricingVersion")
    # PRD §2.4: append-only entities carry no updated_at or version.
    assert "updated_at" not in data or data.get("updated_at") is None, (
        "PricingVersion must not carry updated_at"
    )
    assert "version" not in data or data.get("version") is None, (
        "PricingVersion must not carry a version field"
    )
    assert is_valid_uuid(data.get("operator_id", ""))
    assert isinstance(data.get("version_label"), str)
    assert is_iso8601_timestamp(data.get("effective_from", ""))
    assert is_iso8601_timestamp(data.get("effective_to", ""))
    assert isinstance(data.get("peak_rate_per_kwh_cents"), int)
    assert isinstance(data.get("flat_rate_per_kwh_cents"), int)
    assert isinstance(data.get("valley_rate_per_kwh_cents"), int)
    assert isinstance(data.get("service_fee_per_kwh_cents"), int)
    assert isinstance(data.get("tax_bps"), int)
    assert isinstance(data.get("peak_windows"), list)
    assert isinstance(data.get("valley_windows"), list)
    assert isinstance(data.get("tier_service_fee_discount_bps"), dict)


# ---------------------------------------------------------------------------
# Promo activity (append-only)
# ---------------------------------------------------------------------------
def assert_promo_activity(data: Dict[str, Any]) -> None:
    _check_append_only_fields(data, "PromoActivity")
    assert "updated_at" not in data or data.get("updated_at") is None
    assert "version" not in data or data.get("version") is None
    assert is_valid_uuid(data.get("operator_id", ""))
    assert isinstance(data.get("name"), str) and data["name"]
    assert is_iso8601_timestamp(data.get("starts_at", ""))
    assert is_iso8601_timestamp(data.get("ends_at", ""))
    assert isinstance(data.get("service_fee_discount_bps"), int)
    assert isinstance(data.get("applies_to_tiers"), list)


# ---------------------------------------------------------------------------
# Curve point (append-only)
# ---------------------------------------------------------------------------
def assert_curve_point(data: Dict[str, Any]) -> None:
    _check_append_only_fields(data, "ChargingCurvePoint")
    assert is_valid_uuid(data.get("session_id", ""))
    assert is_iso8601_timestamp(data.get("sampled_at", ""))
    assert data.get("window_tag") in WINDOW_TAGS
    p = data.get("instant_power_kw")
    assert isinstance(p, (int, float)) and float(p) >= 0.0
    e = data.get("cumulative_energy_milli")
    assert isinstance(e, int) and e >= 0


# ---------------------------------------------------------------------------
# Fault report
# ---------------------------------------------------------------------------
def assert_fault_report(data: Dict[str, Any]) -> None:
    _check_versioned_fields(data, "FaultReport")
    assert is_valid_uuid(data.get("pile_id", ""))
    assert data.get("reporter_kind") in FAULT_REPORTER_KINDS
    rm = data.get("reporter_member_id")
    if rm is not None:
        assert is_valid_uuid(rm), (
            f"FaultReport.reporter_member_id must be UUID or null, "
            f"got {rm!r}"
        )
    assert isinstance(data.get("symptom_code"), str)
    assert data.get("severity") in FAULT_SEVERITIES
    assert data.get("status") in FAULT_STATES


# ---------------------------------------------------------------------------
# Repair ticket
# ---------------------------------------------------------------------------
def assert_repair_ticket(data: Dict[str, Any]) -> None:
    _check_versioned_fields(data, "RepairTicket")
    assert is_valid_uuid(data.get("fault_report_id", ""))
    assert isinstance(data.get("assigned_technician_id"), str) and (
        data["assigned_technician_id"]
    )
    assert data.get("status") in REPAIR_TICKET_STATES


# ---------------------------------------------------------------------------
# Settlement ledger entry (append-only)
# ---------------------------------------------------------------------------
def assert_settlement_ledger_entry(data: Dict[str, Any]) -> None:
    _check_append_only_fields(data, "SettlementLedgerEntry")
    assert "updated_at" not in data or data.get("updated_at") is None
    assert "version" not in data or data.get("version") is None
    assert is_valid_uuid(data.get("session_id", ""))
    assert is_valid_uuid(data.get("operator_id", ""))
    assert data.get("counterparty_kind") in COUNTERPARTY_KINDS
    assert isinstance(data.get("amount_cents"), int)
    assert isinstance(data.get("tax_cents", 0), int)
    assert data.get("reason") in LEDGER_REASONS


# ---------------------------------------------------------------------------
# Payout
# ---------------------------------------------------------------------------
def assert_payout(data: Dict[str, Any]) -> None:
    _check_versioned_fields(data, "Payout")
    assert is_valid_uuid(data.get("operator_id", ""))
    assert is_iso8601_timestamp(data.get("period_start", ""))
    assert is_iso8601_timestamp(data.get("period_end", ""))
    for f in ("gross_cents", "reversal_cents", "net_cents"):
        assert isinstance(data.get(f), int), (
            f"Payout.{f} must be int, got {data.get(f)!r}"
        )
    assert data.get("status") in PAYOUT_STATES


# ---------------------------------------------------------------------------
# Audit log (append-only)
# ---------------------------------------------------------------------------
def assert_audit_log(data: Dict[str, Any]) -> None:
    _check_append_only_fields(data, "AuditLog")
    assert "updated_at" not in data or data.get("updated_at") is None
    assert "version" not in data or data.get("version") is None
    assert isinstance(data.get("actor_role"), str)
    assert isinstance(data.get("actor_id"), str)
    assert isinstance(data.get("entity_kind"), str)
    assert isinstance(data.get("entity_id"), str)
    assert data.get("event_kind") in AUDIT_EVENT_KINDS
    assert isinstance(data.get("payload"), dict)
    assert is_iso8601_timestamp(data.get("occurred_at", ""))


def find_audit_logs(rows: Iterable[Dict[str, Any]],
                    *,
                    event_kind: Optional[str] = None,
                    entity_kind: Optional[str] = None,
                    entity_id: Optional[str] = None,
                    ) -> List[Dict[str, Any]]:
    """Filter audit-log rows by event_kind / entity_kind / entity_id."""
    out: List[Dict[str, Any]] = []
    for r in rows:
        if event_kind is not None and r.get("event_kind") != event_kind:
            continue
        if entity_kind is not None and r.get("entity_kind") != entity_kind:
            continue
        if entity_id is not None and r.get("entity_id") != entity_id:
            continue
        out.append(r)
    return out


# ---------------------------------------------------------------------------
# External event inbox (append-only)
# ---------------------------------------------------------------------------
def assert_external_event(data: Dict[str, Any]) -> None:
    _check_append_only_fields(data, "ExternalEventInbox")
    assert "updated_at" not in data or data.get("updated_at") is None
    assert "version" not in data or data.get("version") is None
    assert data.get("source_system") in SOURCE_SYSTEMS
    assert isinstance(data.get("event_type"), str)
    assert isinstance(data.get("payload"), dict)
    assert isinstance(data.get("processed"), bool)
    assert is_iso8601_timestamp(data.get("received_at", ""))


# ---------------------------------------------------------------------------
# Ledger sum invariants (PRD §3.6)
# ---------------------------------------------------------------------------
def sum_amounts_by_counterparty(
    rows: Iterable[Dict[str, Any]],
) -> Dict[str, int]:
    """Compute per-counterparty sum of amount_cents."""
    totals: Dict[str, int] = {}
    for r in rows:
        kind = r.get("counterparty_kind")
        if kind is None:
            continue
        totals[kind] = totals.get(kind, 0) + int(r.get("amount_cents", 0))
    return totals


__all__ = [
    "OPERATOR_ROLE_KINDS",
    "STATION_STATES",
    "PILE_LIFECYCLE_STATES",
    "PILE_OPERATIONAL_STATES",
    "CONNECTOR_TYPES",
    "MEMBER_TIERS",
    "RESERVATION_STATES",
    "QUEUE_STATES",
    "SESSION_STATES",
    "AUTH_METHODS",
    "WINDOW_TAGS",
    "ABNORMAL_EVENT_TYPES",
    "FAULT_REPORTER_KINDS",
    "FAULT_SEVERITIES",
    "FAULT_STATES",
    "REPAIR_TICKET_STATES",
    "COUNTERPARTY_KINDS",
    "LEDGER_REASONS",
    "PAYOUT_STATES",
    "AUDIT_EVENT_KINDS",
    "SOURCE_SYSTEMS",
    "assert_operator",
    "assert_station",
    "assert_pile",
    "assert_member",
    "assert_reservation",
    "assert_queue_entry",
    "assert_charging_session",
    "assert_session_terminal_zero_fees",
    "assert_session_settlement_consistent",
    "assert_pricing_version",
    "assert_promo_activity",
    "assert_curve_point",
    "assert_fault_report",
    "assert_repair_ticket",
    "assert_settlement_ledger_entry",
    "assert_payout",
    "assert_audit_log",
    "assert_external_event",
    "find_audit_logs",
    "sum_amounts_by_counterparty",
]
