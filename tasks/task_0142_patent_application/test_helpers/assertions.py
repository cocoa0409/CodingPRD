"""Entity assertions and domain invariant checkers.

Field names are PRD-exact. Primary persisted entities (Applicant,
Application, OfficeAction, Response, MaintenanceFee, PCTPhase) carry
id, created_at, updated_at, version per PRD §2.4. The two append-only
ledger entities (FeeTransaction, AuditEvent) carry only id and
created_at — assertions on those entities MUST NOT demand updated_at
or version. SystemClock has only `now`.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# ---------------------------------------------------------------------------
# Generic utilities
# ---------------------------------------------------------------------------
def _assert_uuid(value: Any, label: str) -> None:
    assert isinstance(value, str), f"{label} must be a string, got {type(value).__name__}"
    assert is_valid_uuid(value), f"{label} must be a valid UUID, got {value!r}"


def _assert_timestamp(value: Any, label: str) -> None:
    assert isinstance(value, str), f"{label} must be a string, got {type(value).__name__}"
    assert is_iso8601_timestamp(value), f"{label} must be ISO 8601 UTC, got {value!r}"


def _assert_common_versioned(entity: Dict[str, Any], name: str) -> None:
    """PRD §2.4: primary persisted entities carry
    id / created_at / updated_at / version."""
    _assert_uuid(entity.get("id"), f"{name}.id")
    _assert_timestamp(entity.get("created_at"), f"{name}.created_at")
    _assert_timestamp(entity.get("updated_at"), f"{name}.updated_at")
    assert isinstance(entity.get("version"), int), (
        f"{name}.version must be int, got {type(entity.get('version')).__name__}"
    )
    assert entity["version"] >= 1, f"{name}.version must be >= 1"


def _assert_append_only(entity: Dict[str, Any], name: str) -> None:
    """PRD §2.4: append-only ledger entities carry only id and
    created_at — must NOT carry updated_at or version."""
    _assert_uuid(entity.get("id"), f"{name}.id")
    _assert_timestamp(entity.get("created_at"), f"{name}.created_at")
    assert "updated_at" not in entity or entity.get("updated_at") is None, (
        f"{name} must not carry updated_at (PRD §2.4 append-only ledger)"
    )
    assert "version" not in entity or entity.get("version") is None, (
        f"{name} must not carry version (PRD §2.4 append-only ledger)"
    )


# ---------------------------------------------------------------------------
# Applicant (PRD §3.1)
# ---------------------------------------------------------------------------
def assert_applicant(data: Dict[str, Any]) -> None:
    _assert_common_versioned(data, "Applicant")
    name = data.get("name")
    assert isinstance(name, str) and len(name) >= 1, (
        f"Applicant.name must be non-empty string, got {name!r}"
    )
    assert data.get("entity_size") in ("LARGE", "SMALL", "MICRO"), (
        f"Applicant.entity_size unexpected: {data.get('entity_size')!r}"
    )
    assert data.get("status") in ("ACTIVE", "SUSPENDED"), (
        f"Applicant.status unexpected: {data.get('status')!r}"
    )
    gi = data.get("gross_income_cents")
    if gi is not None:
        assert isinstance(gi, int) and gi >= 0, (
            f"Applicant.gross_income_cents must be non-negative int, got {gi!r}"
        )
    pf = data.get("prior_filings_count")
    if pf is not None:
        assert isinstance(pf, int) and pf >= 0, (
            f"Applicant.prior_filings_count must be non-negative int, got {pf!r}"
        )


# ---------------------------------------------------------------------------
# Application (PRD §3.2)
# ---------------------------------------------------------------------------
def assert_application(data: Dict[str, Any]) -> None:
    _assert_common_versioned(data, "Application")
    _assert_uuid(data.get("applicant_id"), "Application.applicant_id")
    assert data.get("application_type") in ("UTILITY", "DESIGN", "PROVISIONAL"), (
        f"Application.application_type unexpected: {data.get('application_type')!r}"
    )
    title = data.get("title")
    assert isinstance(title, str) and len(title) >= 1, (
        f"Application.title must be a non-empty string, got {title!r}"
    )
    cc = data.get("claim_count")
    ic = data.get("independent_claim_count")
    assert isinstance(cc, int) and cc >= 0, (
        f"Application.claim_count must be a non-negative int, got {cc!r}"
    )
    assert isinstance(ic, int) and ic >= 0, (
        f"Application.independent_claim_count must be a non-negative int, got {ic!r}"
    )
    # PRD §3.2 cross-field: independent_claim_count <= claim_count.
    assert ic <= cc, (
        f"Application invariant: independent_claim_count ({ic}) must be <= "
        f"claim_count ({cc}) (PRD §3.2)"
    )
    assert data.get("status") in (
        "DRAFT", "FILED", "UNDER_EXAMINATION", "OFFICE_ACTION_PENDING",
        "ALLOWED", "GRANTED", "ABANDONED", "EXPIRED",
    ), f"Application.status unexpected: {data.get('status')!r}"
    fa = data.get("filed_at")
    if fa is not None:
        _assert_timestamp(fa, "Application.filed_at")
    ga = data.get("granted_at")
    if ga is not None:
        _assert_timestamp(ga, "Application.granted_at")
    ea = data.get("expires_at")
    if ea is not None:
        _assert_timestamp(ea, "Application.expires_at")
    pa = data.get("parent_application_id")
    if pa is not None:
        _assert_uuid(pa, "Application.parent_application_id")
    ct = data.get("continuation_type")
    if ct is not None:
        assert ct in ("NONE", "CONTINUATION", "CIP"), (
            f"Application.continuation_type unexpected: {ct!r}"
        )
    # PRD §3.2: continuation_type must be NONE iff parent_application_id
    # is null.
    if pa is None:
        assert ct in (None, "NONE"), (
            f"PRD §3.2 invariant violated: parent_application_id is null but "
            f"continuation_type is {ct!r}"
        )
    else:
        assert ct in ("CONTINUATION", "CIP"), (
            f"PRD §3.2 invariant violated: parent_application_id is set but "
            f"continuation_type is {ct!r}"
        )
    tfp = data.get("total_fees_paid_cents")
    assert isinstance(tfp, int) and tfp >= 0, (
        f"Application.total_fees_paid_cents must be non-negative int, got {tfp!r}"
    )


# ---------------------------------------------------------------------------
# OfficeAction (PRD §3.3)
# ---------------------------------------------------------------------------
def assert_office_action(data: Dict[str, Any]) -> None:
    _assert_common_versioned(data, "OfficeAction")
    _assert_uuid(data.get("application_id"), "OfficeAction.application_id")
    an = data.get("action_number")
    assert isinstance(an, int) and an >= 1, (
        f"OfficeAction.action_number must be a positive int, got {an!r}"
    )
    assert data.get("action_type") in ("NON_FINAL", "FINAL"), (
        f"OfficeAction.action_type unexpected: {data.get('action_type')!r}"
    )
    _assert_timestamp(data.get("issued_at"), "OfficeAction.issued_at")
    _assert_timestamp(data.get("response_deadline_at"), "OfficeAction.response_deadline_at")
    _assert_timestamp(data.get("extended_deadline_at"), "OfficeAction.extended_deadline_at")
    assert data["response_deadline_at"] < data["extended_deadline_at"], (
        "OfficeAction.response_deadline_at must precede extended_deadline_at "
        "(PRD §3.3: 90d shortened period within 180d extended period)"
    )
    assert data.get("status") in ("PENDING", "RESPONDED", "ABANDONED_BY_DEFAULT"), (
        f"OfficeAction.status unexpected: {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# Response (PRD §3.3)
# ---------------------------------------------------------------------------
def assert_response(data: Dict[str, Any]) -> None:
    _assert_common_versioned(data, "Response")
    _assert_uuid(data.get("office_action_id"), "Response.office_action_id")
    _assert_uuid(data.get("application_id"), "Response.application_id")
    _assert_timestamp(data.get("filed_at"), "Response.filed_at")
    me = data.get("months_extension")
    assert isinstance(me, int) and 0 <= me <= 3, (
        f"Response.months_extension must be in [0, 3] inclusive, got {me!r}"
    )
    ef = data.get("extension_fee_cents")
    assert isinstance(ef, int) and ef >= 0, (
        f"Response.extension_fee_cents must be non-negative int, got {ef!r}"
    )


# ---------------------------------------------------------------------------
# MaintenanceFee (PRD §3.4 / §3.5)
# ---------------------------------------------------------------------------
def assert_maintenance_fee(data: Dict[str, Any]) -> None:
    _assert_common_versioned(data, "MaintenanceFee")
    _assert_uuid(data.get("application_id"), "MaintenanceFee.application_id")
    assert data.get("stage") in ("STAGE_3_5", "STAGE_7_5", "STAGE_11_5"), (
        f"MaintenanceFee.stage unexpected: {data.get('stage')!r}"
    )
    _assert_timestamp(data.get("window_open_at"), "MaintenanceFee.window_open_at")
    _assert_timestamp(data.get("due_at"), "MaintenanceFee.due_at")
    _assert_timestamp(data.get("grace_period_end_at"), "MaintenanceFee.grace_period_end_at")
    assert data["window_open_at"] < data["due_at"] < data["grace_period_end_at"], (
        "MaintenanceFee timestamps must satisfy window_open_at < due_at < "
        "grace_period_end_at (PRD §3.4)"
    )
    assert data.get("status") in ("SCHEDULED", "PAID", "LAPSED"), (
        f"MaintenanceFee.status unexpected: {data.get('status')!r}"
    )
    rf = data.get("required_fee_cents")
    if rf is not None:
        assert isinstance(rf, int) and rf >= 0, (
            f"MaintenanceFee.required_fee_cents must be non-negative int, got {rf!r}"
        )


# ---------------------------------------------------------------------------
# PCTPhase (PRD §3.6)
# ---------------------------------------------------------------------------
def assert_pct_phase(data: Dict[str, Any]) -> None:
    _assert_common_versioned(data, "PCTPhase")
    _assert_uuid(data.get("application_id"), "PCTPhase.application_id")
    _assert_timestamp(data.get("pct_filed_at"), "PCTPhase.pct_filed_at")
    _assert_timestamp(data.get("priority_date"), "PCTPhase.priority_date")
    _assert_timestamp(data.get("national_phase_deadline_at"),
                      "PCTPhase.national_phase_deadline_at")
    assert data.get("status") in ("INTERNATIONAL", "NATIONAL_ENTERED", "LAPSED"), (
        f"PCTPhase.status unexpected: {data.get('status')!r}"
    )
    ne = data.get("national_entered_at")
    if ne is not None:
        _assert_timestamp(ne, "PCTPhase.national_entered_at")


# ---------------------------------------------------------------------------
# FeeTransaction (PRD §2.4 append-only)
# ---------------------------------------------------------------------------
def assert_fee_transaction(data: Dict[str, Any]) -> None:
    _assert_append_only(data, "FeeTransaction")
    _assert_uuid(data.get("application_id"), "FeeTransaction.application_id")
    assert data.get("fee_category") in (
        "FILING", "EXCESS_CLAIM", "EXAMINATION", "ISSUE",
        "MAINTENANCE", "EXTENSION", "PCT_TRANSMITTAL", "PCT_NATIONAL",
    ), f"FeeTransaction.fee_category unexpected: {data.get('fee_category')!r}"
    ac = data.get("amount_cents")
    assert isinstance(ac, int) and ac >= 0, (
        f"FeeTransaction.amount_cents must be non-negative int, got {ac!r}"
    )
    _assert_timestamp(data.get("paid_at"), "FeeTransaction.paid_at")


# ---------------------------------------------------------------------------
# AuditEvent (PRD §2.4 append-only)
# ---------------------------------------------------------------------------
def assert_audit_event(data: Dict[str, Any]) -> None:
    _assert_append_only(data, "AuditEvent")
    _assert_uuid(data.get("application_id"), "AuditEvent.application_id")
    assert isinstance(data.get("actor_role"), str) and data["actor_role"]
    assert isinstance(data.get("actor_id"), str) and data["actor_id"]
    assert isinstance(data.get("action"), str) and data["action"]
    assert isinstance(data.get("details"), dict)


# ---------------------------------------------------------------------------
# SystemClock (PRD §2.4 singleton)
# ---------------------------------------------------------------------------
def assert_system_clock(data: Dict[str, Any]) -> None:
    _assert_timestamp(data.get("now"), "SystemClock.now")
    assert "updated_at" not in data or data.get("updated_at") is None, (
        "SystemClock must not carry updated_at (PRD §2.4 singleton)"
    )
    assert "version" not in data or data.get("version") is None, (
        "SystemClock must not carry version (PRD §2.4 singleton)"
    )


# ---------------------------------------------------------------------------
# Convenience: find a row by id within a list
# ---------------------------------------------------------------------------
def find_by_id(rows: Iterable[Dict[str, Any]], _id: str) -> Optional[Dict[str, Any]]:
    for r in rows:
        if r.get("id") == _id:
            return r
    return None


def find_audit_actions(events: Iterable[Dict[str, Any]], action: str) -> List[Dict[str, Any]]:
    return [e for e in events if e.get("action") == action]


__all__ = [
    "assert_applicant",
    "assert_application",
    "assert_office_action",
    "assert_response",
    "assert_maintenance_fee",
    "assert_pct_phase",
    "assert_fee_transaction",
    "assert_audit_event",
    "assert_system_clock",
    "find_by_id",
    "find_audit_actions",
]
