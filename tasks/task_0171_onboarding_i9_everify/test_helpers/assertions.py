"""Entity assertions and domain invariant checkers.

Each `assert_{entity}(data)` walks the field set declared in PRD §3 for
that entity. Common-fields entities (PRD §2.4) carry id + created_at +
updated_at + version. The four entities that carry only id + created_at
per PRD §2.4 — `I9Document`, `ReverificationEvent`, `AuditEvent`, and
`SystemClock` — are checked with `assert_append_only_fields`.
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
    """PRD §2.4: "Resources whose lifecycle requires update tracking —
    `Employee`, `I9Form`, and `EVerifyCase` — additionally carry
    `created_at`, `updated_at`, and `version`. ... `version` is an
    integer that begins at 1 on creation and increments by 1 on every
    mutation."
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
    """PRD §2.4: "`I9Document`, `ReverificationEvent`, `AuditEvent`, and
    `SystemClock` are leaf or system records that expose only `id` and
    `created_at` — they have neither `updated_at` nor `version`."
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
                  field: str = "status") -> None:
    actual = data.get(field)
    assert actual == expected, (
        f"Expected {field}={expected!r}, got {actual!r}"
    )


def assert_version_incremented_by(prior: Dict[str, Any],
                                  current: Dict[str, Any],
                                  delta: int = 1) -> None:
    """PRD §2.5: "Every successful mutation increments `version` by 1"."""
    assert "version" in prior and "version" in current, (
        "both prior and current must carry version"
    )
    assert current["version"] == prior["version"] + delta, (
        f"Expected version {prior['version']} + {delta} = "
        f"{prior['version'] + delta}, got {current['version']}"
    )


# ---------------------------------------------------------------------------
# Employee — PRD §3.1, §3.7
# ---------------------------------------------------------------------------
ONBOARDING_STATUSES = {
    "PENDING_SECTION_1", "PENDING_SECTION_2", "EVERIFY_PENDING",
    "TNC_OPEN", "AUTHORIZED", "NOT_AUTHORIZED", "TERMINATED",
}

CITIZENSHIP_STATUSES = {
    "US_CITIZEN", "NON_CITIZEN_NATIONAL",
    "LAWFUL_PERMANENT_RESIDENT", "ALIEN_AUTHORIZED",
}

VISA_CLASSES = {
    "F1_OPT", "F1_OPT_STEM", "H1B", "L1", "TN", "OTHER",
}


def assert_employee(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("legal_name"), str) and data["legal_name"], (
        f"legal_name must be non-empty string, got {data.get('legal_name')!r}"
    )
    dob = data.get("date_of_birth")
    assert isinstance(dob, str) and len(dob) == 10 and dob[4] == "-", (
        f"date_of_birth must be ISO 8601 date YYYY-MM-DD, got {dob!r}"
    )
    ssn = data.get("ssn")
    assert isinstance(ssn, str) and len(ssn) == 9 and ssn.isdigit(), (
        f"ssn must be exactly 9 digits, got {ssn!r}"
    )
    assert data.get("citizenship_status") in CITIZENSHIP_STATUSES, (
        f"citizenship_status invalid: {data.get('citizenship_status')!r}"
    )
    # work_authorization_expiry: optional ISO date or null.
    wae = data.get("work_authorization_expiry", None)
    assert wae is None or (isinstance(wae, str) and len(wae) >= 10), (
        f"work_authorization_expiry must be ISO date or null, got {wae!r}"
    )
    # visa_class: optional enum or null.
    vc = data.get("visa_class", None)
    assert vc is None or vc in VISA_CLASSES, (
        f"visa_class invalid: {vc!r}"
    )
    sd = data.get("start_date")
    assert isinstance(sd, str) and len(sd) == 10 and sd[4] == "-", (
        f"start_date must be ISO date YYYY-MM-DD, got {sd!r}"
    )
    # section2_deadline: ISO 8601 datetime (computed)
    s2d = data.get("section2_deadline", None)
    assert s2d is None or is_iso8601_timestamp(str(s2d)), (
        f"section2_deadline must be ISO 8601 datetime or null, got {s2d!r}"
    )
    assert data.get("onboarding_status") in ONBOARDING_STATUSES, (
        f"onboarding_status invalid: {data.get('onboarding_status')!r}"
    )
    assert isinstance(data.get("is_terminated"), bool), (
        f"is_terminated must be bool, got {data.get('is_terminated')!r}"
    )


# ---------------------------------------------------------------------------
# I9Form — PRD §3.3
# ---------------------------------------------------------------------------
FORM_KINDS = {"INITIAL", "REVERIFICATION", "REHIRE"}
FORM_STATUSES = {
    "DRAFT", "SECTION_1_DONE", "SECTION_2_DONE", "SUPERSEDED", "VOIDED",
}


def assert_i9_form(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("employee_id"), str), (
        f"employee_id must be a string, got {data.get('employee_id')!r}"
    )
    assert data.get("form_kind") in FORM_KINDS, (
        f"form_kind invalid: {data.get('form_kind')!r}"
    )
    sfid = data.get("supersedes_form_id", None)
    assert sfid is None or isinstance(sfid, str), (
        f"supersedes_form_id must be string or null, got {sfid!r}"
    )
    s1c = data.get("section1_completed_at", None)
    assert s1c is None or is_iso8601_timestamp(str(s1c)), (
        f"section1_completed_at must be ISO 8601 or null, got {s1c!r}"
    )
    s2c = data.get("section2_completed_at", None)
    assert s2c is None or is_iso8601_timestamp(str(s2c)), (
        f"section2_completed_at must be ISO 8601 or null, got {s2c!r}"
    )
    for fld in (
        "list_a_document_id", "list_b_document_id", "list_c_document_id",
        "section1_attested_by_user_id", "section2_completed_by_user_id",
    ):
        val = data.get(fld, None)
        assert val is None or isinstance(val, str), (
            f"{fld} must be string or null, got {val!r}"
        )
    assert data.get("form_status") in FORM_STATUSES, (
        f"form_status invalid: {data.get('form_status')!r}"
    )
    rvd = data.get("reverification_due", None)
    # PRD §3.4: "The result is at day granularity"; null when no candidates.
    assert rvd is None or isinstance(rvd, str), (
        f"reverification_due must be date string or null, got {rvd!r}"
    )


# ---------------------------------------------------------------------------
# I9Document — PRD §3.2 (leaf — only id + created_at per PRD §2.4)
# ---------------------------------------------------------------------------
DOCUMENT_CATEGORIES = {"LIST_A", "LIST_B", "LIST_C"}


def assert_i9_document(data: Dict[str, Any]) -> None:
    assert_append_only_fields(data)
    assert isinstance(data.get("employee_id"), str)
    assert data.get("category") in DOCUMENT_CATEGORIES, (
        f"category invalid: {data.get('category')!r}"
    )
    assert isinstance(data.get("document_title"), str) and data["document_title"]
    assert isinstance(data.get("document_number"), str) and data["document_number"]
    assert isinstance(data.get("issuing_authority"), str) and data["issuing_authority"]
    exp = data.get("expiration_date", None)
    assert exp is None or isinstance(exp, str), (
        f"expiration_date must be date string or null, got {exp!r}"
    )
    rec = data.get("receipt", False)
    assert isinstance(rec, bool), (
        f"receipt must be bool, got {rec!r}"
    )
    rrd = data.get("receipt_resolution_due", None)
    assert rrd is None or isinstance(rrd, str), (
        f"receipt_resolution_due must be date string or null, got {rrd!r}"
    )


# ---------------------------------------------------------------------------
# EVerifyCase — PRD §3.5, §3.6
# ---------------------------------------------------------------------------
CASE_STATUSES = {
    "DRAFT", "PENDING", "EMPLOYMENT_AUTHORIZED",
    "TNC", "FNC", "CLOSED_AUTHORIZED", "CLOSED_NOT_AUTHORIZED",
}

TNC_KINDS = {"SSA", "DHS"}

TNC_DECISIONS = {"CONTEST", "NO_CONTEST"}

FINAL_DISPOSITIONS = {"AUTHORIZED", "NOT_AUTHORIZED"}


def assert_everify_case(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("employee_id"), str)
    assert isinstance(data.get("i9_form_id"), str)
    sub = data.get("submitted_at", None)
    assert sub is None or is_iso8601_timestamp(str(sub)), (
        f"submitted_at must be ISO 8601 or null, got {sub!r}"
    )
    assert isinstance(data.get("idempotency_key"), str), (
        f"idempotency_key must be string, got {data.get('idempotency_key')!r}"
    )
    assert data.get("case_status") in CASE_STATUSES, (
        f"case_status invalid: {data.get('case_status')!r}"
    )
    tk = data.get("tnc_kind", None)
    assert tk is None or tk in TNC_KINDS, (
        f"tnc_kind invalid: {tk!r}"
    )
    to = data.get("tnc_opened_at", None)
    assert to is None or is_iso8601_timestamp(str(to))
    td = data.get("tnc_contest_deadline", None)
    assert td is None or is_iso8601_timestamp(str(td))
    ed = data.get("tnc_employee_decision", None)
    assert ed is None or ed in TNC_DECISIONS, (
        f"tnc_employee_decision invalid: {ed!r}"
    )
    fd = data.get("final_disposition", None)
    assert fd is None or fd in FINAL_DISPOSITIONS, (
        f"final_disposition invalid: {fd!r}"
    )


# ---------------------------------------------------------------------------
# ReverificationEvent — PRD §3.4 (leaf — only id + created_at)
# ---------------------------------------------------------------------------
REVERIFICATION_REASONS = {
    "WORK_AUTH_EXPIRY",
    "OPT_TO_OPT_STEM_EXTENSION",
    "REHIRE_WITHIN_3_YEARS",
}


def assert_reverification_event(data: Dict[str, Any]) -> None:
    assert_append_only_fields(data)
    assert isinstance(data.get("employee_id"), str)
    assert isinstance(data.get("triggering_form_id"), str)
    assert data.get("reason") in REVERIFICATION_REASONS, (
        f"reverification reason invalid: {data.get('reason')!r}"
    )
    nfi = data.get("new_form_id", None)
    assert nfi is None or isinstance(nfi, str), (
        f"new_form_id must be string or null, got {nfi!r}"
    )
    rd = data.get("resolution_deadline", None)
    assert rd is None or isinstance(rd, str), (
        f"resolution_deadline must be string or null, got {rd!r}"
    )
    ra = data.get("resolved_at", None)
    assert ra is None or is_iso8601_timestamp(str(ra)), (
        f"resolved_at must be ISO 8601 or null, got {ra!r}"
    )


# ---------------------------------------------------------------------------
# AuditEvent — PRD §2.8 (append-only)
# ---------------------------------------------------------------------------
AUDIT_SUBJECT_ENTITIES = {
    "EMPLOYEE", "I9_FORM", "I9_DOCUMENT",
    "EVERIFY_CASE", "REVERIFICATION_EVENT",
}

AUDIT_ACTOR_ROLES = {"Employee", "HRStaff", "EmployerRep", "System"}


def assert_audit_event(data: Dict[str, Any]) -> None:
    assert_append_only_fields(data)
    assert isinstance(data.get("subject_employee_id"), str)
    assert data.get("subject_entity") in AUDIT_SUBJECT_ENTITIES, (
        f"subject_entity invalid: {data.get('subject_entity')!r}"
    )
    assert isinstance(data.get("subject_entity_id"), str)
    assert isinstance(data.get("action"), str) and data["action"], (
        f"action must be non-empty string, got {data.get('action')!r}"
    )
    assert data.get("actor_role") in AUDIT_ACTOR_ROLES, (
        f"actor_role invalid: {data.get('actor_role')!r}"
    )
    aui = data.get("actor_user_id", None)
    assert aui is None or isinstance(aui, str), (
        f"actor_user_id must be string or null, got {aui!r}"
    )
    oc = data.get("occurred_at")
    assert is_iso8601_timestamp(str(oc)), (
        f"occurred_at must be ISO 8601, got {oc!r}"
    )


# ---------------------------------------------------------------------------
# Audit-event search helpers.
# ---------------------------------------------------------------------------
def find_audit_actions(
    events: Iterable[Dict[str, Any]], action: str,
) -> List[Dict[str, Any]]:
    """Return all events whose `action` matches."""
    return [e for e in events if e.get("action") == action]


def assert_audit_action_present(
    events: Iterable[Dict[str, Any]], action: str,
    *, count: Optional[int] = None,
) -> None:
    found = find_audit_actions(events, action)
    if count is None:
        assert len(found) >= 1, (
            f"Expected AuditEvent action={action!r} present, "
            f"none found in {len(list(events))} events"
        )
    else:
        assert len(found) == count, (
            f"Expected AuditEvent action={action!r} count={count}, "
            f"got {len(found)}"
        )


def assert_audit_action_absent(
    events: Iterable[Dict[str, Any]], action: str,
) -> None:
    found = find_audit_actions(events, action)
    assert not found, (
        f"Expected NO AuditEvent action={action!r}, got {len(found)}"
    )


def assert_audit_order(
    events: List[Dict[str, Any]], earlier_action: str,
    later_action: str,
) -> None:
    """Assert at least one earlier_action AuditEvent occurred_at <=
    a later_action AuditEvent.occurred_at."""
    earliers = find_audit_actions(events, earlier_action)
    laters = find_audit_actions(events, later_action)
    assert earliers, (
        f"Cannot test ordering: no AuditEvent action={earlier_action!r}"
    )
    assert laters, (
        f"Cannot test ordering: no AuditEvent action={later_action!r}"
    )
    min_earlier = min(e["occurred_at"] for e in earliers)
    max_later = max(e["occurred_at"] for e in laters)
    assert min_earlier <= max_later, (
        f"Expected {earlier_action!r} (min {min_earlier}) "
        f"<= {later_action!r} (max {max_later})"
    )


__all__ = [
    # Envelope / common-fields
    "assert_common_fields", "assert_append_only_fields",
    "assert_status", "assert_version_incremented_by",
    # Entities
    "assert_employee", "assert_i9_form", "assert_i9_document",
    "assert_everify_case", "assert_reverification_event",
    "assert_audit_event",
    # Audit search helpers
    "find_audit_actions",
    "assert_audit_action_present",
    "assert_audit_action_absent",
    "assert_audit_order",
    # Status sets exported for parametrization
    "ONBOARDING_STATUSES",
    "CITIZENSHIP_STATUSES",
    "VISA_CLASSES",
    "FORM_KINDS",
    "FORM_STATUSES",
    "DOCUMENT_CATEGORIES",
    "CASE_STATUSES",
    "TNC_KINDS",
    "TNC_DECISIONS",
    "FINAL_DISPOSITIONS",
    "REVERIFICATION_REASONS",
    "AUDIT_SUBJECT_ENTITIES",
    "AUDIT_ACTOR_ROLES",
]
