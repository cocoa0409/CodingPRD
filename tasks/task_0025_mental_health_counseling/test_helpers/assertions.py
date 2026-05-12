"""Per-entity response assertions and domain invariant checkers.

These functions validate that an entity dict returned from the API matches
the schema specified by the PRD (field names verbatim, value enums, common
fields where applicable). They use the framework's generic helpers
(is_valid_uuid, is_iso8601_timestamp) internally.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


# ---------------------------------------------------------------------------
# Common-field assertions (PRD §2.4)
# ---------------------------------------------------------------------------
def _assert_common_fields_versioned(data: Dict[str, Any]):
    """Versioned entity per PRD §2.4: id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601 with three fractional digits: {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601: {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be integer >= 1: {data.get('version')!r}"


def _assert_immutable_common_fields(data: Dict[str, Any]):
    """Append-only/immutable entity per PRD §2.4: only id + created_at;
    NEVER updated_at, NEVER version."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert "updated_at" not in data, \
        "PRD §2.4: append-only entity MUST NOT carry updated_at"
    assert "version" not in data, \
        "PRD §2.4: append-only entity MUST NOT carry version"


# ---------------------------------------------------------------------------
# Counselor (PRD §3.1)
# ---------------------------------------------------------------------------
def assert_counselor(data: Dict[str, Any]):
    _assert_common_fields_versioned(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"] == data["email"].lower()
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert is_iso8601_timestamp(data["license_expires_at"])
    assert isinstance(data["specialty_tags"], list) and len(data["specialty_tags"]) >= 1
    for tag in data["specialty_tags"]:
        assert tag in {
            "ANXIETY", "DEPRESSION", "TRAUMA", "FAMILY",
            "ADDICTION", "ADOLESCENT", "EATING_DISORDER", "GRIEF",
        }, f"unexpected specialty tag: {tag}"
    assert isinstance(data["supported_channels"], list) and len(data["supported_channels"]) >= 1
    for ch in data["supported_channels"]:
        assert ch in {"TEXT", "AUDIO", "VIDEO"}, f"unexpected channel: {ch}"
    assert isinstance(data["timezone"], str) and data["timezone"]
    assert data["status"] in {"PENDING_CERT", "ACTIVE", "SUSPENDED", "DISQUALIFIED"}
    assert isinstance(data["revenue_share_bps"], int)
    assert 0 <= data["revenue_share_bps"] <= 10000


# ---------------------------------------------------------------------------
# Client (PRD §3.3)
# ---------------------------------------------------------------------------
def assert_client(data: Dict[str, Any]):
    _assert_common_fields_versioned(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"] == data["email"].lower()
    assert isinstance(data["timezone"], str) and data["timezone"]
    assert isinstance(data["emergency_contact_name"], str)
    assert isinstance(data["emergency_contact_phone"], str)
    assert data["assessment_status"] in {"PENDING", "IN_PROGRESS", "COMPLETED"}
    assert isinstance(data["package_balance_sessions"], int)
    assert data["package_balance_sessions"] >= 0
    assert data["risk_flag"] in {"NONE", "ELEVATED", "ACUTE"}


# ---------------------------------------------------------------------------
# Certification cycle (PRD §3.2)
# ---------------------------------------------------------------------------
def assert_certification_cycle(data: Dict[str, Any]):
    _assert_common_fields_versioned(data)
    assert is_valid_uuid(data["counselor_id"])
    assert isinstance(data["cycle_index"], int) and data["cycle_index"] >= 1
    assert isinstance(data["required_supervision_hours"], (int, float))
    assert isinstance(data["required_ce_hours"], (int, float))
    assert is_iso8601_timestamp(data["window_start_at"])
    assert is_iso8601_timestamp(data["window_end_at"])
    assert data["status"] in {"OPEN", "UNDER_REVIEW", "APPROVED", "EXPIRED", "REJECTED"}


# ---------------------------------------------------------------------------
# Availability slot (PRD §3.4)
# ---------------------------------------------------------------------------
def assert_availability_slot(data: Dict[str, Any]):
    _assert_common_fields_versioned(data)
    assert is_valid_uuid(data["counselor_id"])
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])
    assert data["channel"] in {"TEXT", "AUDIO", "VIDEO"}
    assert data["status"] in {"OPEN", "HELD", "BOOKED", "BLOCKED", "RELEASED"}


# ---------------------------------------------------------------------------
# Appointment (PRD §3.4–§3.5)
# ---------------------------------------------------------------------------
def assert_appointment(data: Dict[str, Any]):
    _assert_common_fields_versioned(data)
    assert is_valid_uuid(data["counselor_id"])
    assert is_valid_uuid(data["client_id"])
    assert is_valid_uuid(data["slot_id"])
    assert data["appointment_type"] in {"INTAKE", "STANDARD", "FOLLOW_UP"}
    assert data["channel"] in {"TEXT", "AUDIO", "VIDEO"}
    assert data["status"] in {
        "HOLD", "CONFIRMED", "IN_SESSION", "COMPLETED",
        "CANCELLED", "NO_SHOW", "RESCHEDULED",
    }
    assert data["payment_mode"] in {"PAY_PER_SESSION", "PACKAGE"}
    assert isinstance(data["list_price_cents"], int) and data["list_price_cents"] >= 0
    assert data["refund_state"] in {
        "NONE", "FULL_REFUNDED", "PARTIAL_REFUNDED", "NON_REFUNDABLE",
    }


# ---------------------------------------------------------------------------
# Counseling record (PRD §3.6) — append-only per PRD §2.4
# ---------------------------------------------------------------------------
def assert_counseling_record(data: Dict[str, Any]):
    _assert_immutable_common_fields(data)
    assert is_valid_uuid(data["appointment_id"])
    assert is_valid_uuid(data["counselor_id"])
    assert is_valid_uuid(data["client_id"])
    assert data["redaction_status"] in {"ACTIVE", "PURGED"}
    assert is_iso8601_timestamp(data["retention_expires_at"])


# ---------------------------------------------------------------------------
# Settlement ledger (PRD §3.8) — append-only per PRD §2.4
# ---------------------------------------------------------------------------
def assert_settlement_ledger_row(data: Dict[str, Any]):
    _assert_immutable_common_fields(data)
    assert is_valid_uuid(data["appointment_id"])
    assert data["direction"] in {"CHARGE", "REFUND"}
    assert isinstance(data["gross_amount_cents"], int)
    assert isinstance(data["tax_cents"], int)
    assert isinstance(data["counselor_share_cents"], int)
    assert isinstance(data["platform_share_cents"], int)


# ---------------------------------------------------------------------------
# Crisis incident (PRD §3.7)
# ---------------------------------------------------------------------------
def assert_crisis_incident(data: Dict[str, Any]):
    _assert_common_fields_versioned(data)
    assert is_valid_uuid(data["appointment_id"])
    assert is_valid_uuid(data["client_id"])
    assert data["detection_source"] in {"KEYWORD_DETECTOR", "COUNSELOR_TRIGGERED"}
    assert data["severity"] in {"LOW", "MEDIUM", "HIGH"}
    assert data["status"] in {
        "DETECTED", "HANDED_OVER", "EMERGENCY_NOTIFIED",
        "FOLLOW_UP_SCHEDULED", "RESOLVED",
    }


# ---------------------------------------------------------------------------
# Payout (PRD §3.9)
# ---------------------------------------------------------------------------
def assert_payout(data: Dict[str, Any]):
    _assert_common_fields_versioned(data)
    assert is_valid_uuid(data["counselor_id"])
    assert is_iso8601_timestamp(data["period_start_at"])
    assert is_iso8601_timestamp(data["period_end_at"])
    assert isinstance(data["total_counselor_share_cents"], int)
    assert isinstance(data["total_tax_cents"], int)
    assert data["status"] in {"PENDING", "PAID", "REVERSED"}


# ---------------------------------------------------------------------------
# Supervision session (PRD §3.10)
# ---------------------------------------------------------------------------
def assert_supervision_session(data: Dict[str, Any]):
    _assert_common_fields_versioned(data)
    assert is_valid_uuid(data["counselor_id"])
    assert is_valid_uuid(data["supervisor_id"])
    assert is_valid_uuid(data["case_appointment_id"])
    assert is_iso8601_timestamp(data["scheduled_at"])
    assert isinstance(data["duration_hours"], (int, float))
    assert 0.5 <= float(data["duration_hours"]) <= 4.0
    assert data["status"] in {"PENDING_REVIEW", "APPROVED", "REJECTED"}


# ---------------------------------------------------------------------------
# CE record (PRD §3.10)
# ---------------------------------------------------------------------------
def assert_ce_record(data: Dict[str, Any]):
    _assert_common_fields_versioned(data)
    assert is_valid_uuid(data["counselor_id"])
    assert isinstance(data["course_title"], str) and data["course_title"]
    assert is_iso8601_timestamp(data["completed_at"])
    assert isinstance(data["hours_claimed"], (int, float))
    assert float(data["hours_claimed"]) > 0
    assert isinstance(data["hours_credited"], (int, float))
    assert data["status"] in {"PENDING_REVIEW", "APPROVED", "REJECTED"}


# ---------------------------------------------------------------------------
# Audit-log entry (PRD §2.9 / §3.11) — append-only per PRD §2.4
# ---------------------------------------------------------------------------
def assert_audit_log_entry(data: Dict[str, Any]):
    _assert_immutable_common_fields(data)
    assert data["actor_role"] in {
        "Client", "Counselor", "Supervisor", "CrisisResponder",
        "PlatformAdmin", "system",
    }, f"unexpected actor_role {data.get('actor_role')!r}"
    assert isinstance(data["actor_user_id"], str)
    assert data["action"] in {
        "RECORD_READ", "RECORD_EXPORT", "RECORD_PURGE",
        "CRISIS_DETECTED", "CRISIS_HANDOVER", "CRISIS_NOTIFY",
        "COUNSELOR_DISQUALIFIED", "RECERT_DECISION",
    }, f"unexpected action {data.get('action')!r}"
    assert isinstance(data["target_entity"], str) and data["target_entity"]
    assert isinstance(data["target_id"], str) and data["target_id"]


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------
def assert_charge_breakdown_pay_per_session(
    row: Dict[str, Any], *,
    list_price_cents: int = 12000,
    revenue_share_bps: int = 7000,
    tax_bps: int = 875,
):
    """PAY_PER_SESSION CHARGE breakdown invariants (PRD §3.8 / §2.8).

    For PAY_PER_SESSION, gross_amount_cents == list_price_cents,
    tax_cents == round_half_up(gross * tax_bps / 10000),
    counselor_share_cents == round_half_up(gross * revenue_share_bps / 10000),
    platform_share_cents == gross - counselor_share (per PRD §2.8 pin).
    """
    assert row["direction"] == "CHARGE"
    assert row["gross_amount_cents"] == list_price_cents
    expected_tax = _round_half_up_int(list_price_cents * tax_bps / 10000)
    assert row["tax_cents"] == expected_tax, \
        f"tax_cents expected {expected_tax}, got {row['tax_cents']}"
    expected_counselor = _round_half_up_int(list_price_cents * revenue_share_bps / 10000)
    assert row["counselor_share_cents"] == expected_counselor, \
        f"counselor_share_cents expected {expected_counselor}, got {row['counselor_share_cents']}"
    expected_platform = list_price_cents - expected_counselor
    assert row["platform_share_cents"] == expected_platform, \
        f"platform_share_cents expected {expected_platform}, got {row['platform_share_cents']}"


def assert_charge_breakdown_package(
    row: Dict[str, Any], *,
    revenue_share_bps: int = 7000,
    shadow_rate_cents: int = 9000,
):
    """PACKAGE CHARGE breakdown invariants (PRD §3.8).

    For PACKAGE, gross_amount_cents == 0, tax_cents == 0,
    counselor_share_cents == round_half_up(SHADOW_PACKAGE_RATE * revenue_share_bps / 10000),
    platform_share_cents == -counselor_share_cents.
    """
    assert row["direction"] == "CHARGE"
    assert row["gross_amount_cents"] == 0
    assert row["tax_cents"] == 0
    expected_counselor = _round_half_up_int(shadow_rate_cents * revenue_share_bps / 10000)
    assert row["counselor_share_cents"] == expected_counselor
    assert row["platform_share_cents"] == -expected_counselor


def assert_refund_breakdown_full_pps(
    row: Dict[str, Any], *,
    list_price_cents: int = 12000,
    revenue_share_bps: int = 7000,
    tax_bps: int = 875,
):
    """FULL_REFUNDED breakdown for PAY_PER_SESSION (PRD §3.5).

    Each component is recorded with negative sign.
    """
    assert row["direction"] == "REFUND"
    assert row["gross_amount_cents"] == -list_price_cents
    expected_tax = _round_half_up_int(list_price_cents * tax_bps / 10000)
    assert row["tax_cents"] == -expected_tax
    expected_counselor = _round_half_up_int(list_price_cents * revenue_share_bps / 10000)
    assert row["counselor_share_cents"] == -expected_counselor
    expected_platform = list_price_cents - expected_counselor
    assert row["platform_share_cents"] == -expected_platform


def assert_refund_breakdown_full_package(
    row: Dict[str, Any], *,
    revenue_share_bps: int = 7000,
    shadow_rate_cents: int = 9000,
):
    """FULL_REFUNDED breakdown for PACKAGE (PRD §3.5)."""
    assert row["direction"] == "REFUND"
    assert row["gross_amount_cents"] == 0
    assert row["tax_cents"] == 0
    expected_counselor = _round_half_up_int(shadow_rate_cents * revenue_share_bps / 10000)
    assert row["counselor_share_cents"] == -expected_counselor
    assert row["platform_share_cents"] == expected_counselor


def assert_refund_breakdown_partial_pps(
    row: Dict[str, Any], *,
    list_price_cents: int = 12000,
    revenue_share_bps: int = 7000,
    tax_bps: int = 875,
):
    """PARTIAL_REFUNDED breakdown for PAY_PER_SESSION (PRD §3.5).

    Refund gross = round_half_up(list_price_cents * 0.50). Each component is
    rounded against THAT refund gross, then platform_share = gross - counselor.
    """
    refund_gross = _round_half_up_int(list_price_cents * 0.50)
    assert row["direction"] == "REFUND"
    assert row["gross_amount_cents"] == -refund_gross
    expected_tax = _round_half_up_int(refund_gross * tax_bps / 10000)
    assert row["tax_cents"] == -expected_tax
    expected_counselor = _round_half_up_int(refund_gross * revenue_share_bps / 10000)
    assert row["counselor_share_cents"] == -expected_counselor
    expected_platform = refund_gross - expected_counselor
    assert row["platform_share_cents"] == -expected_platform


def _round_half_up_int(x: float) -> int:
    """PRD §2.8: round half up to the nearest cent."""
    # Use a string-based approach to avoid IEEE 754 ambiguity
    import decimal
    d = decimal.Decimal(repr(x))
    return int(d.quantize(decimal.Decimal("1"), rounding=decimal.ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Search helpers (for crawling list endpoints)
# ---------------------------------------------------------------------------
def find_ledger_rows_for_appointment(
    rows: List[Dict[str, Any]], appointment_id: str,
) -> List[Dict[str, Any]]:
    return [r for r in rows if r.get("appointment_id") == appointment_id]


def find_ledger_row(
    rows: List[Dict[str, Any]], appointment_id: str, direction: str,
) -> Optional[Dict[str, Any]]:
    for r in rows:
        if r.get("appointment_id") == appointment_id and r.get("direction") == direction:
            return r
    return None


def find_audit_entries(
    entries: List[Dict[str, Any]], *, action: Optional[str] = None,
    target_entity: Optional[str] = None, target_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    out = []
    for e in entries:
        if action is not None and e.get("action") != action:
            continue
        if target_entity is not None and e.get("target_entity") != target_entity:
            continue
        if target_id is not None and e.get("target_id") != target_id:
            continue
        out.append(e)
    return out
