"""Entity assertions and domain invariant checkers.

Each `assert_{entity}(data)` walks the field set declared in PRD §3 for
that entity. Common-fields entities (PRD §2.4) carry id + created_at +
updated_at + version. The append-only / leaf entities — `LeaveInstance`,
`MedicalCertification`, `BenefitInvoice`, and `AuditEvent` — carry only
id + created_at per PRD §2.4 and are checked with
`assert_append_only_fields`.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Envelope checks — common-fields vs append-only / leaf records.
# ---------------------------------------------------------------------------
def assert_common_fields(data: Dict[str, Any]) -> None:
    """PRD §2.4: "Resources of the types `Employer`, `Worksite`,
    `Employee`, `LeaveCase`, and `PfLClaim` carry the common envelope
    fields: a server-minted `id` (a UUID string with no type prefix),
    a `created_at` timestamp (ISO 8601 UTC with three fractional
    digits), an `updated_at` timestamp updated on every successful
    mutation ..., and an integer `version` that starts at 1 and
    increments by 1 on every successful mutation."
    """
    assert "id" in data, "common-fields row missing 'id'"
    assert is_valid_uuid(str(data["id"])), (
        f"id must be a UUID without prefix, got {data['id']!r}"
    )
    assert "created_at" in data, "missing 'created_at'"
    assert is_iso8601_timestamp(str(data["created_at"])), (
        f"created_at must be ISO 8601, got {data['created_at']!r}"
    )
    assert "updated_at" in data, "missing 'updated_at'"
    assert is_iso8601_timestamp(str(data["updated_at"])), (
        f"updated_at must be ISO 8601, got {data['updated_at']!r}"
    )
    assert "version" in data, "missing 'version'"
    assert isinstance(data["version"], int), (
        f"version must be int, got {type(data['version'])}"
    )
    assert data["version"] >= 1, (
        f"version must be >= 1, got {data['version']}"
    )


def assert_append_only_fields(data: Dict[str, Any]) -> None:
    """PRD §2.4: "Resources of the types `LeaveInstance`,
    `MedicalCertification`, `BenefitInvoice`, and `AuditEvent` are
    append-only or are mutated only through their parent's lifecycle;
    they carry only an `id` (UUID, no type prefix) and a `created_at`
    timestamp. They do not expose `updated_at` and they do not expose
    `version`."
    """
    assert "id" in data, "append-only row missing 'id'"
    assert is_valid_uuid(str(data["id"])), (
        f"id must be a UUID, got {data['id']!r}"
    )
    assert "created_at" in data, "missing 'created_at'"
    assert is_iso8601_timestamp(str(data["created_at"])), (
        f"created_at must be ISO 8601, got {data['created_at']!r}"
    )
    assert "updated_at" not in data, (
        "append-only / leaf entity must not expose 'updated_at' "
        f"(found: {data.get('updated_at')!r})"
    )
    assert "version" not in data, (
        "append-only / leaf entity must not expose 'version' "
        f"(found: {data.get('version')!r})"
    )


def assert_status(data: Dict[str, Any], expected: str,
                  field: str = "case_status") -> None:
    actual = data.get(field)
    assert actual == expected, (
        f"Expected {field}={expected!r}, got {actual!r}"
    )


def assert_version_incremented_by(prior: Dict[str, Any],
                                  current: Dict[str, Any],
                                  delta: int = 1) -> None:
    """PRD §2.4: "Every successful mutation increments `version` by 1"."""
    assert "version" in prior and "version" in current, (
        "both prior and current must carry version"
    )
    assert current["version"] == prior["version"] + delta, (
        f"Expected version {prior['version']} + {delta} = "
        f"{prior['version'] + delta}, got {current['version']}"
    )


# ---------------------------------------------------------------------------
# Status enum sets — PRD §3
# ---------------------------------------------------------------------------
LEAVE_YEAR_BASES = {"CALENDAR", "ROLLING_BACKWARD"}

STATE_PFL_PROGRAMS = {"NONE", "STATE_PFL_8WEEK"}

EMPLOYMENT_STATUSES = {"ACTIVE", "ON_LEAVE", "TERMINATED", "RESTORED"}

LEAVE_REASONS = {
    "OWN_SERIOUS_HEALTH", "FAMILY_SERIOUS_HEALTH",
    "BABY_BONDING", "MILITARY_EXIGENCY",
}

LEAVE_PATTERNS = {"CONTINUOUS", "INTERMITTENT", "REDUCED_SCHEDULE"}

CASE_STATUSES = {
    "DRAFT", "PENDING_CERTIFICATION", "APPROVED", "DENIED",
    "ACTIVE", "COMPLETED", "JOB_RESTORED", "CANCELLED",
}

CERTIFICATION_STATUSES = {
    "NOT_REQUIRED", "AWAITING_DOC", "RECEIVED", "INSUFFICIENT",
    "COMPLETE", "RECERTIFICATION_DUE",
}

JOB_RESTORATION_STATUSES = {"PROTECTED", "FORFEITED", "NOT_APPLICABLE"}

INSTANCE_STATUSES = {"PROPOSED", "APPROVED", "VOIDED"}

REVIEW_OUTCOMES = {"PENDING", "ACCEPTED", "INSUFFICIENT", "REJECTED"}

PFL_CLAIM_TYPES = {"FAMILY_CARE", "BABY_BONDING"}

PFL_CLAIM_STATUSES = {
    "SUBMITTED", "APPROVED", "PAYING", "EXHAUSTED", "DENIED",
}

INVOICE_STATUSES = {"ISSUED", "PAID", "GRACE", "FORFEITED"}

AUDIT_EVENT_KINDS = {
    "ELIGIBILITY_CHECKED", "CASE_CREATED", "CERTIFICATION_SUBMITTED",
    "CERTIFICATION_REVIEWED", "INSTANCE_LOGGED", "INSTANCE_VOIDED",
    "QUOTA_RECOMPUTED", "PFL_LINKED",
    "JOB_RESTORATION_REQUESTED", "JOB_RESTORATION_FORFEITED",
    "BENEFIT_INVOICE_ISSUED", "BENEFIT_INVOICE_FORFEITED",
}


# ---------------------------------------------------------------------------
# Employer — PRD §3.1
# ---------------------------------------------------------------------------
def assert_employer(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("legal_name"), str) and data["legal_name"], (
        f"legal_name must be non-empty string, got {data.get('legal_name')!r}"
    )
    assert data.get("leave_year_basis") in LEAVE_YEAR_BASES, (
        f"leave_year_basis invalid: {data.get('leave_year_basis')!r}"
    )
    assert data.get("state_pfl_program") in STATE_PFL_PROGRAMS, (
        f"state_pfl_program invalid: {data.get('state_pfl_program')!r}"
    )
    bpc = data.get("benefit_premium_share_cents")
    assert isinstance(bpc, int) and bpc >= 0, (
        f"benefit_premium_share_cents must be int >= 0, got {bpc!r}"
    )


# ---------------------------------------------------------------------------
# Worksite — PRD §3.1
# ---------------------------------------------------------------------------
def assert_worksite(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("employer_id"), str)
    assert isinstance(data.get("address_line"), str) and data["address_line"]
    hc = data.get("employee_count_within_75_miles")
    assert isinstance(hc, int) and hc >= 0, (
        f"employee_count_within_75_miles must be int >= 0, got {hc!r}"
    )


# ---------------------------------------------------------------------------
# Employee — PRD §3.1
# ---------------------------------------------------------------------------
def assert_employee(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("employer_id"), str)
    assert isinstance(data.get("worksite_id"), str)
    assert isinstance(data.get("full_name"), str) and data["full_name"], (
        f"full_name must be non-empty string, got {data.get('full_name')!r}"
    )
    hd = data.get("hire_date")
    assert isinstance(hd, str) and len(hd) >= 10, (
        f"hire_date must be ISO date string, got {hd!r}"
    )
    hw = data.get("hours_worked_trailing_12mo")
    assert isinstance(hw, int) and hw >= 0, (
        f"hours_worked_trailing_12mo must be int >= 0, got {hw!r}"
    )
    mw = data.get("monthly_wage_cents")
    assert isinstance(mw, int) and mw >= 0, (
        f"monthly_wage_cents must be int >= 0, got {mw!r}"
    )
    assert data.get("employment_status") in EMPLOYMENT_STATUSES, (
        f"employment_status invalid: {data.get('employment_status')!r}"
    )


# ---------------------------------------------------------------------------
# LeaveCase — PRD §3.3, §3.6, §3.10
# ---------------------------------------------------------------------------
def assert_leave_case(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("employee_id"), str)
    assert data.get("reason") in LEAVE_REASONS, (
        f"reason invalid: {data.get('reason')!r}"
    )
    assert data.get("leave_pattern") in LEAVE_PATTERNS, (
        f"leave_pattern invalid: {data.get('leave_pattern')!r}"
    )
    assert data.get("case_status") in CASE_STATUSES, (
        f"case_status invalid: {data.get('case_status')!r}"
    )
    assert data.get("certification_status") in CERTIFICATION_STATUSES, (
        f"certification_status invalid: {data.get('certification_status')!r}"
    )
    rsd = data.get("requested_start_date")
    assert isinstance(rsd, str) and len(rsd) >= 10, (
        f"requested_start_date must be ISO date, got {rsd!r}"
    )
    eed = data.get("expected_end_date")
    assert isinstance(eed, str) and len(eed) >= 10, (
        f"expected_end_date must be ISO date, got {eed!r}"
    )
    lya = data.get("leave_year_anchor")
    assert isinstance(lya, str) and len(lya) >= 10, (
        f"leave_year_anchor must be ISO date, got {lya!r}"
    )
    pci = data.get("pfl_claim_id", None)
    assert pci is None or isinstance(pci, str), (
        f"pfl_claim_id must be string or null, got {pci!r}"
    )
    cd = data.get("cert_deadline")
    # PRD §3.3: cert_deadline is "case creation timestamp + 15 days" —
    # a server-pinned timestamp.
    assert isinstance(cd, str) and len(cd) >= 10, (
        f"cert_deadline must be ISO timestamp, got {cd!r}"
    )
    hc = data.get("hours_charged")
    assert isinstance(hc, int) and hc >= 0, (
        f"hours_charged must be int >= 0, got {hc!r}"
    )
    assert data.get("job_restoration_status") in JOB_RESTORATION_STATUSES, (
        f"job_restoration_status invalid: "
        f"{data.get('job_restoration_status')!r}"
    )


# ---------------------------------------------------------------------------
# LeaveInstance — PRD §3.4 (append-only / leaf)
# ---------------------------------------------------------------------------
def assert_leave_instance(data: Dict[str, Any]) -> None:
    assert_append_only_fields(data)
    assert isinstance(data.get("leave_case_id"), str)
    idate = data.get("instance_date")
    assert isinstance(idate, str) and len(idate) >= 10, (
        f"instance_date must be ISO date, got {idate!r}"
    )
    hu = data.get("hours_used")
    assert isinstance(hu, int) and 1 <= hu <= 24, (
        f"hours_used must be int in [1,24], got {hu!r}"
    )
    assert data.get("instance_status") in INSTANCE_STATUSES, (
        f"instance_status invalid: {data.get('instance_status')!r}"
    )


# ---------------------------------------------------------------------------
# MedicalCertification — PRD §3.5 (append-only / leaf)
# ---------------------------------------------------------------------------
def assert_medical_certification(data: Dict[str, Any]) -> None:
    assert_append_only_fields(data)
    assert isinstance(data.get("leave_case_id"), str)
    sa = data.get("submitted_at")
    assert isinstance(sa, str) and is_iso8601_timestamp(sa), (
        f"submitted_at must be ISO 8601 timestamp, got {sa!r}"
    )
    shc = data.get("serious_health_condition")
    assert isinstance(shc, bool), (
        f"serious_health_condition must be bool, got {shc!r}"
    )
    efm = data.get("estimated_frequency_per_month")
    assert isinstance(efm, int) and efm >= 0, (
        f"estimated_frequency_per_month must be int >= 0, got {efm!r}"
    )
    edh = data.get("estimated_duration_hours")
    assert isinstance(edh, int) and edh >= 0, (
        f"estimated_duration_hours must be int >= 0, got {edh!r}"
    )
    assert data.get("review_outcome") in REVIEW_OUTCOMES, (
        f"review_outcome invalid: {data.get('review_outcome')!r}"
    )


# ---------------------------------------------------------------------------
# PfLClaim — PRD §3.8
# ---------------------------------------------------------------------------
def assert_pfl_claim(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("employee_id"), str)
    assert data.get("claim_type") in PFL_CLAIM_TYPES, (
        f"claim_type invalid: {data.get('claim_type')!r}"
    )
    assert data.get("claim_status") in PFL_CLAIM_STATUSES, (
        f"claim_status invalid: {data.get('claim_status')!r}"
    )
    wa = data.get("weeks_authorized")
    assert isinstance(wa, int) and 1 <= wa <= 8, (
        f"weeks_authorized must be int in [1,8], got {wa!r}"
    )
    wp = data.get("weeks_paid")
    assert isinstance(wp, int) and wp >= 0, (
        f"weeks_paid must be int >= 0, got {wp!r}"
    )
    wbc = data.get("weekly_benefit_cents")
    assert isinstance(wbc, int) and wbc >= 0, (
        f"weekly_benefit_cents must be int >= 0, got {wbc!r}"
    )


# ---------------------------------------------------------------------------
# BenefitInvoice — PRD §3.9 (append-only / leaf)
# ---------------------------------------------------------------------------
def assert_benefit_invoice(data: Dict[str, Any]) -> None:
    assert_append_only_fields(data)
    assert isinstance(data.get("leave_case_id"), str)
    pm = data.get("period_month")
    assert isinstance(pm, str) and len(pm) == 7 and pm[4] == "-", (
        f"period_month must be YYYY-MM, got {pm!r}"
    )
    adc = data.get("amount_due_cents")
    assert isinstance(adc, int) and adc >= 0, (
        f"amount_due_cents must be int >= 0, got {adc!r}"
    )
    assert data.get("invoice_status") in INVOICE_STATUSES, (
        f"invoice_status invalid: {data.get('invoice_status')!r}"
    )


# ---------------------------------------------------------------------------
# AuditEvent — PRD §2.9 (append-only)
# ---------------------------------------------------------------------------
def assert_audit_event(data: Dict[str, Any]) -> None:
    assert_append_only_fields(data)
    assert isinstance(data.get("leave_case_id"), str)
    assert data.get("event_kind") in AUDIT_EVENT_KINDS, (
        f"event_kind invalid: {data.get('event_kind')!r}"
    )
    # PRD §2.9: "Each row captures the `actor_role` (the role header
    # value of the acting caller, or the literal string `system` for
    # clock-driven auto-events)".
    actor_role = data.get("actor_role")
    assert isinstance(actor_role, str) and actor_role, (
        f"actor_role must be non-empty string, got {actor_role!r}"
    )
    dj = data.get("detail_json", None)
    # PRD §2.9: "a free-form `detail_json` payload" — must be present.
    assert isinstance(dj, (dict, list)) or dj is None, (
        f"detail_json must be a JSON object or null, got {type(dj)}"
    )


# ---------------------------------------------------------------------------
# Audit-event search helpers.
# ---------------------------------------------------------------------------
def find_audit_events(
    events: Iterable[Dict[str, Any]], event_kind: str,
) -> List[Dict[str, Any]]:
    """Return all events whose `event_kind` matches."""
    return [e for e in events if e.get("event_kind") == event_kind]


def assert_audit_event_present(
    events: Iterable[Dict[str, Any]], event_kind: str,
    *, count: Optional[int] = None,
) -> None:
    found = find_audit_events(events, event_kind)
    if count is None:
        assert len(found) >= 1, (
            f"Expected AuditEvent event_kind={event_kind!r} present, "
            f"none found in {len(list(events))} events"
        )
    else:
        assert len(found) == count, (
            f"Expected AuditEvent event_kind={event_kind!r} count={count}, "
            f"got {len(found)}"
        )


def assert_audit_event_absent(
    events: Iterable[Dict[str, Any]], event_kind: str,
) -> None:
    found = find_audit_events(events, event_kind)
    assert not found, (
        f"Expected NO AuditEvent event_kind={event_kind!r}, got {len(found)}"
    )


def assert_audit_event_order(
    events: List[Dict[str, Any]], earlier_kind: str,
    later_kind: str,
) -> None:
    """Assert at least one earlier_kind AuditEvent created_at <= a
    later_kind AuditEvent.created_at.

    PRD §2.3: list endpoints sort by created_at ascending, so the audit
    log is already in chronological order.
    """
    earliers = find_audit_events(events, earlier_kind)
    laters = find_audit_events(events, later_kind)
    assert earliers, (
        f"Cannot test ordering: no AuditEvent event_kind={earlier_kind!r}"
    )
    assert laters, (
        f"Cannot test ordering: no AuditEvent event_kind={later_kind!r}"
    )
    min_earlier = min(e["created_at"] for e in earliers)
    max_later = max(e["created_at"] for e in laters)
    assert min_earlier <= max_later, (
        f"Expected {earlier_kind!r} (min {min_earlier}) "
        f"<= {later_kind!r} (max {max_later})"
    )


# ---------------------------------------------------------------------------
# Quota-balance / eligibility-snapshot shape checkers.
# ---------------------------------------------------------------------------
def assert_quota_balance(data: Dict[str, Any]) -> None:
    """PRD §3.7: read returns basis, window_start, window_end,
    consumed_hours, remaining_hours."""
    assert data.get("basis") in LEAVE_YEAR_BASES, (
        f"basis invalid: {data.get('basis')!r}"
    )
    ws = data.get("window_start")
    we = data.get("window_end")
    assert isinstance(ws, str) and len(ws) >= 10, (
        f"window_start must be ISO date, got {ws!r}"
    )
    assert isinstance(we, str) and len(we) >= 10, (
        f"window_end must be ISO date, got {we!r}"
    )
    ch = data.get("consumed_hours")
    rh = data.get("remaining_hours")
    assert isinstance(ch, int) and ch >= 0, (
        f"consumed_hours must be int >= 0, got {ch!r}"
    )
    assert isinstance(rh, int) and rh >= 0, (
        f"remaining_hours must be int >= 0, got {rh!r}"
    )


def assert_eligibility_snapshot(data: Dict[str, Any]) -> None:
    """PRD §3.2: snapshot returns eligible, reason_code, months_of_service,
    hours_trailing, worksite_headcount."""
    assert isinstance(data.get("eligible"), bool), (
        f"eligible must be bool, got {data.get('eligible')!r}"
    )
    rc = data.get("reason_code", None)
    assert rc is None or isinstance(rc, str), (
        f"reason_code must be string or null, got {rc!r}"
    )
    mos = data.get("months_of_service")
    assert isinstance(mos, int) and mos >= 0, (
        f"months_of_service must be int >= 0, got {mos!r}"
    )
    ht = data.get("hours_trailing")
    assert isinstance(ht, int) and ht >= 0, (
        f"hours_trailing must be int >= 0, got {ht!r}"
    )
    wh = data.get("worksite_headcount")
    assert isinstance(wh, int) and wh >= 0, (
        f"worksite_headcount must be int >= 0, got {wh!r}"
    )


__all__ = [
    # Envelope / common-fields
    "assert_common_fields", "assert_append_only_fields",
    "assert_status", "assert_version_incremented_by",
    # Entities
    "assert_employer", "assert_worksite", "assert_employee",
    "assert_leave_case", "assert_leave_instance",
    "assert_medical_certification", "assert_pfl_claim",
    "assert_benefit_invoice", "assert_audit_event",
    # Shape checkers for non-entity responses
    "assert_quota_balance", "assert_eligibility_snapshot",
    # Audit search helpers
    "find_audit_events",
    "assert_audit_event_present",
    "assert_audit_event_absent",
    "assert_audit_event_order",
    # Status enum sets
    "LEAVE_YEAR_BASES", "STATE_PFL_PROGRAMS",
    "EMPLOYMENT_STATUSES", "LEAVE_REASONS", "LEAVE_PATTERNS",
    "CASE_STATUSES", "CERTIFICATION_STATUSES",
    "JOB_RESTORATION_STATUSES", "INSTANCE_STATUSES",
    "REVIEW_OUTCOMES", "PFL_CLAIM_TYPES", "PFL_CLAIM_STATUSES",
    "INVOICE_STATUSES", "AUDIT_EVENT_KINDS",
]
