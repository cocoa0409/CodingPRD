"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the exact JSON-body schema the PRD declares for the
request body (PRD §3 narrative + §4 endpoint table). Tests pass
overrides for the values they want to control. Only PRD-declared input
fields are produced.

PRD §2.4: timestamps are ISO 8601 UTC with three fractional digits.
"""
from __future__ import annotations

import random
import string
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .constants import TEST_DEFAULTS


# ---------------------------------------------------------------------------
# Timestamp helpers — PRD §2.4 format with three fractional digits.
# ---------------------------------------------------------------------------
def iso_utc(dt: datetime) -> str:
    """Render a datetime as ISO 8601 UTC with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def _server_now_dt_lazy() -> datetime:
    """Return the server's current logical-clock instant.

    Lazy import to avoid a fixtures->factories import cycle. PRD §2.11:
    the runner-managed logical clock advances independently of wall
    time, so tests must construct timestamps against this clock to keep
    declared_at <= clock_now < expires_at invariants holding.
    """
    from .fixtures import server_now_dt
    return server_now_dt()


def iso_now() -> str:
    """ISO 8601 instant aligned with the server's logical clock.

    PRD §2.11: the logical clock is advanced by /_clock/advance. Tests
    that bracket an EmergencyDeclaration around "now" must use the
    server clock, not the wall clock, since prior tests may have
    advanced the server clock far past the wall clock.
    """
    return iso_utc(_server_now_dt_lazy())


def iso_offset(*, days: int = 0, hours: int = 0, minutes: int = 0,
               seconds: int = 0,
               base: Optional[datetime] = None) -> str:
    """As iso_now, plus a delta. When `base` is omitted, anchors on the
    server's logical clock (see iso_now)."""
    base = base if base is not None else _server_now_dt_lazy()
    return iso_utc(base + timedelta(
        days=days, hours=hours, minutes=minutes, seconds=seconds,
    ))


def parse_iso(iso_string: str) -> datetime:
    """Parse an ISO 8601 string returned by the API; tolerates `Z` and
    fractional digits."""
    s = iso_string.replace("Z", "+00:00")
    return datetime.fromisoformat(s)


_ALPHANUM = string.ascii_uppercase + string.digits


def random_suffix(n: int = 8) -> str:
    return "".join(random.choices(_ALPHANUM, k=n))


def random_state_code() -> str:
    """Two-letter all-caps state code suffix; avoid collisions across
    concurrent tests."""
    return "".join(random.choices(string.ascii_uppercase, k=2))


# ---------------------------------------------------------------------------
# StatePolicy — PRD §3.1, §4 (PolicyAdmin-only)
# ---------------------------------------------------------------------------
def create_state_policy_payload(
    *,
    state_code: str,
    fpl_year: int = TEST_DEFAULTS["FPL_YEAR"],
    fpl_base_amount: float = TEST_DEFAULTS["FPL_BASE_AMOUNT"],
    fpl_per_member_amount: float = TEST_DEFAULTS["FPL_PER_MEMBER_AMOUNT"],
    magi_income_limit_pct: float = TEST_DEFAULTS["MAGI_INCOME_LIMIT_PCT"],
    asset_test_applies: Optional[bool] = None,
    asset_limit_per_member: Optional[float] = None,
    state_disregard_amount: Optional[float] = None,
    state_exempt_asset_types: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /state-policies — PolicyAdmin only.

    PRD §3.1: required input fields are state_code, fpl_year,
    fpl_base_amount, fpl_per_member_amount, magi_income_limit_pct.
    PRD §3.1: asset_test_applies defaults to false; state_disregard_amount
    defaults to zero; asset_limit_per_member, state_exempt_asset_types
    are optional.
    """
    payload: Dict[str, Any] = {
        "state_code": state_code,
        "fpl_year": fpl_year,
        "fpl_base_amount": fpl_base_amount,
        "fpl_per_member_amount": fpl_per_member_amount,
        "magi_income_limit_pct": magi_income_limit_pct,
    }
    if asset_test_applies is not None:
        payload["asset_test_applies"] = asset_test_applies
    if asset_limit_per_member is not None:
        payload["asset_limit_per_member"] = asset_limit_per_member
    if state_disregard_amount is not None:
        payload["state_disregard_amount"] = state_disregard_amount
    if state_exempt_asset_types is not None:
        payload["state_exempt_asset_types"] = state_exempt_asset_types
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# EmergencyDeclaration — PRD §3.5
# ---------------------------------------------------------------------------
def create_emergency_declaration_payload(
    *,
    scope: str = "STATE",
    state_code: Optional[str] = None,
    declared_at: Optional[str] = None,
    expires_at: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /emergency-declarations — PolicyAdmin only.

    PRD §3.1: "When the scope is STATE, a state_code is required and
    identifies the affected state; when the scope is FEDERAL,
    state_code must be null." declared_at and expires_at are required.
    """
    payload: Dict[str, Any] = {
        "scope": scope,
        "declared_at": declared_at or iso_now(),
        "expires_at": expires_at or iso_offset(days=30),
    }
    # scope=FEDERAL must have state_code=null; scope=STATE requires
    # state_code. Callers pass state_code explicitly when needed.
    if scope == "STATE":
        payload["state_code"] = state_code
    else:
        payload["state_code"] = None
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Household — PRD §3.1
# ---------------------------------------------------------------------------
def create_household_payload(
    *,
    state_code: str,
    address_line: str = TEST_DEFAULTS["DEFAULT_ADDRESS_LINE"],
    filing_status: str = TEST_DEFAULTS["DEFAULT_FILING_STATUS"],
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /households — IntakeWorker only.

    PRD §3.1: required input fields are state_code (must reference an
    existing StatePolicy), address_line, filing_status (SINGLE,
    MARRIED_JOINT, MARRIED_SEPARATE, HEAD_OF_HOUSEHOLD).
    """
    payload: Dict[str, Any] = {
        "state_code": state_code,
        "address_line": address_line,
        "filing_status": filing_status,
    }
    payload.update(overrides)
    return payload


def patch_household_payload(
    *,
    address_line: Optional[str] = None,
    filing_status: Optional[str] = None,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PATCH /households/{id} — IntakeWorker only.

    PRD §3.1: "A household's address_line and filing_status may be
    modified via patch, with optimistic concurrency on version."
    PRD §2.7: "If version is omitted from the body, the system does not
    perform a stale-write check"; if supplied and mismatched →
    ERR_VERSION_CONFLICT.
    """
    payload: Dict[str, Any] = {}
    if address_line is not None:
        payload["address_line"] = address_line
    if filing_status is not None:
        payload["filing_status"] = filing_status
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Applicant — PRD §3.1
# ---------------------------------------------------------------------------
def create_applicant_payload(
    *,
    full_name: Optional[str] = None,
    date_of_birth: str = TEST_DEFAULTS["DEFAULT_DATE_OF_BIRTH"],
    dependent_status: str = TEST_DEFAULTS["DEFAULT_DEPENDENT_STATUS"],
    is_disabled: Optional[bool] = None,
    is_pregnant: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /households/{id}/applicants — IntakeWorker only.

    PRD §3.1: required input fields are full_name, date_of_birth,
    dependent_status (PRIMARY/SPOUSE/DEPENDENT/EXCLUDED); is_disabled
    and is_pregnant default to false.
    """
    payload: Dict[str, Any] = {
        "full_name": full_name or f"Applicant {random_suffix(4)}",
        "date_of_birth": date_of_birth,
        "dependent_status": dependent_status,
    }
    if is_disabled is not None:
        payload["is_disabled"] = is_disabled
    if is_pregnant is not None:
        payload["is_pregnant"] = is_pregnant
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# IncomeRecord — PRD §3.1
# ---------------------------------------------------------------------------
def create_income_record_payload(
    *,
    source_type: str = "WAGES",
    gross_amount: float = 1000.00,
    frequency: str = "MONTHLY",
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /households/{id}/applicants/{id}/income — IntakeWorker.

    PRD §3.1: required input fields are source_type, gross_amount,
    frequency (ANNUAL/MONTHLY/BIWEEKLY/WEEKLY).
    """
    payload: Dict[str, Any] = {
        "source_type": source_type,
        "gross_amount": gross_amount,
        "frequency": frequency,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# AssetRecord — PRD §3.1
# ---------------------------------------------------------------------------
def create_asset_record_payload(
    *,
    asset_type: str = "CHECKING",
    market_value: float = 1000.00,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /households/{id}/applicants/{id}/assets — IntakeWorker.

    PRD §3.1: required input fields are asset_type and market_value.
    """
    payload: Dict[str, Any] = {
        "asset_type": asset_type,
        "market_value": market_value,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Application — PRD §3.3
# ---------------------------------------------------------------------------
def create_application_payload(
    *,
    program: str = "MAGI_ADULT",
    rule_variant: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /households/{id}/applications — IntakeWorker only.

    PRD §3.3: required input is program; rule_variant defaults to STATE
    when omitted ("optionally the rule_variant, which defaults to
    STATE").
    """
    payload: Dict[str, Any] = {"program": program}
    if rule_variant is not None:
        payload["rule_variant"] = rule_variant
    payload.update(overrides)
    return payload


def patch_application_payload(
    *,
    program: Optional[str] = None,
    rule_variant: Optional[str] = None,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PATCH /households/{id}/applications/{id} — IntakeWorker only.

    PRD §3.3 / §3.1: "An application's program and rule_variant may be
    modified via patch while it is still in DRAFT, also with optimistic
    concurrency on version."
    """
    payload: Dict[str, Any] = {}
    if program is not None:
        payload["program"] = program
    if rule_variant is not None:
        payload["rule_variant"] = rule_variant
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


def decide_application_payload(
    *,
    decision: str,
    ineligibility_reason: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /households/{id}/applications/{id}/decide — EligibilityCaseworker.

    PRD §3.3: required input is decision (APPROVE/DENY); optional
    ineligibility_reason when denying (INCOME_EXCEEDS_LIMIT,
    ASSETS_EXCEED_LIMIT, NOT_RESIDENT, NON_QUALIFYING_PROGRAM).
    """
    payload: Dict[str, Any] = {"decision": decision}
    if ineligibility_reason is not None:
        payload["ineligibility_reason"] = ineligibility_reason
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Redetermination — PRD §3.4
# ---------------------------------------------------------------------------
def submit_redetermination_payload(
    *,
    decision: str,
    new_snapshot_magi: float,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /redeterminations/{id}/submit — EligibilityCaseworker only.

    PRD §3.4: "The submission carries a decision of RENEW or TERMINATE
    and a new_snapshot_magi value capturing the household's updated
    annualized MAGI for the renewal year."
    """
    payload: Dict[str, Any] = {
        "decision": decision,
        "new_snapshot_magi": new_snapshot_magi,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Appeal — PRD §3.6
# ---------------------------------------------------------------------------
def create_appeal_payload(
    *,
    determination_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /appeals — IntakeWorker only.

    PRD §3.6: "An IntakeWorker files an Appeal by submitting an Appeal
    against the determination, supplying determination_id in the body."
    """
    payload: Dict[str, Any] = {"determination_id": determination_id}
    payload.update(overrides)
    return payload


def schedule_hearing_payload(
    *,
    officer_id: str,
    scheduled_start: str,
    scheduled_end: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /appeals/{id}/schedule-hearing — AppealsOfficer only.

    PRD §3.6: "supplies the officer_id who will hear it, and supplies
    scheduled_start and scheduled_end instants."
    """
    payload: Dict[str, Any] = {
        "officer_id": officer_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    payload.update(overrides)
    return payload


def grant_appeal_payload(
    *,
    outcome_reason: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /appeals/{id}/grant — AppealsOfficer only.

    PRD §3.6: "accepts an optional outcome_reason recording a free-text
    rationale."
    """
    payload: Dict[str, Any] = {}
    if outcome_reason is not None:
        payload["outcome_reason"] = outcome_reason
    payload.update(overrides)
    return payload


def uphold_appeal_payload(
    *,
    outcome_reason: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /appeals/{id}/uphold — AppealsOfficer only.

    PRD §3.6: "likewise accepts an optional outcome_reason".
    """
    payload: Dict[str, Any] = {}
    if outcome_reason is not None:
        payload["outcome_reason"] = outcome_reason
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Clock advance — PRD §2.11
# ---------------------------------------------------------------------------
def clock_advance_payload(*, to: str, **overrides: Any) -> Dict[str, Any]:
    """POST /_clock/advance — PolicyAdmin only.

    PRD §2.11: "An admin-only test-driving capability advances the
    logical clock to a supplied target instant carried in the request
    body as `to`."
    """
    payload: Dict[str, Any] = {"to": to}
    payload.update(overrides)
    return payload


__all__ = [
    "iso_utc",
    "utcnow",
    "iso_now",
    "iso_offset",
    "parse_iso",
    "random_suffix",
    "random_state_code",
    "create_state_policy_payload",
    "create_emergency_declaration_payload",
    "create_household_payload",
    "patch_household_payload",
    "create_applicant_payload",
    "create_income_record_payload",
    "create_asset_record_payload",
    "create_application_payload",
    "patch_application_payload",
    "decide_application_payload",
    "submit_redetermination_payload",
    "create_appeal_payload",
    "schedule_hearing_payload",
    "grant_appeal_payload",
    "uphold_appeal_payload",
    "clock_advance_payload",
]
