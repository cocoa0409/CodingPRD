"""Entity assertions and domain invariant checkers.

Each `assert_{entity}(data)` walks the field set declared in PRD §3 for
that entity. Common-fields entities carry id + created_at + updated_at
+ version (PRD §2.4); the two append-only entities (ExemptionClaim and
AuditEntry) carry ONLY id + created_at — PRD §2.4: "The two entities
`ExemptionClaim` and `AuditEntry` are immutable: once written they are
never updated, and consequently they carry only `id` and `created_at`
- both `updated_at` and `version` are absent on those two entities."
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Envelope checks
# ---------------------------------------------------------------------------
def assert_common_fields(data: Dict[str, Any]) -> None:
    """PRD §2.4: every common-fields resource carries id, created_at,
    updated_at, and version (monotonically increasing integer starting
    at 1)."""
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
    """PRD §2.4: "The two entities `ExemptionClaim` and `AuditEntry`
    are immutable: once written they are never updated, and
    consequently they carry only `id` and `created_at` - both
    `updated_at` and `version` are absent on those two entities."
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
        "append-only entity must not expose 'updated_at' "
        f"(found: {data.get('updated_at')!r})"
    )
    assert "version" not in data, (
        "append-only entity must not expose 'version' "
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
    """PRD §2.4: "version, a monotonically increasing integer starting
    at 1 that is incremented by exactly one each time the resource is
    mutated."""
    assert "version" in prior and "version" in current, (
        "both prior and current must carry version"
    )
    assert current["version"] == prior["version"] + delta, (
        f"Expected version {prior['version']} + {delta} = "
        f"{prior['version'] + delta}, got {current['version']}"
    )


# ---------------------------------------------------------------------------
# Requester — PRD §3.1
# ---------------------------------------------------------------------------
def assert_requester(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("full_name"), str) and data["full_name"], (
        "full_name must be non-empty string"
    )
    assert isinstance(data.get("contact_email"), str), (
        "contact_email must be a string"
    )
    assert data.get("requester_tier") in {
        "COMMERCIAL", "EDUCATIONAL_NONCOMMERCIAL", "PUBLIC_INTEREST",
    }, f"requester_tier invalid: {data.get('requester_tier')!r}"
    assert data.get("status") in {"ACTIVE", "SUSPENDED"}, (
        f"status invalid: {data.get('status')!r}"
    )
    # tier_justification is nullable only on COMMERCIAL.
    if data["requester_tier"] != "COMMERCIAL":
        tj = data.get("tier_justification")
        assert isinstance(tj, str) and tj, (
            "Non-commercial requester must carry non-empty "
            f"tier_justification, got {tj!r}"
        )


# ---------------------------------------------------------------------------
# Request — PRD §3.2 — §3.5, §3.8, §3.9
# ---------------------------------------------------------------------------
REQUEST_STATUS_SET = {
    "INTAKE", "ACKNOWLEDGED", "SEARCH", "DETERMINATION_PENDING",
    "RELEASED", "PARTIAL_RELEASE", "DENIED", "GLOMAR_ISSUED",
    "WITHDRAWN", "REOPENED_BY_APPEAL",
}


def assert_request(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("requester_id"), str), (
        "requester_id must be a string"
    )
    assert isinstance(data.get("subject_summary"), str), (
        "subject_summary must be a string"
    )
    assert data.get("status") in REQUEST_STATUS_SET, (
        f"Request.status invalid: {data.get('status')!r}"
    )
    assert isinstance(data.get("fee_estimate_accepted"), bool), (
        f"fee_estimate_accepted must be bool, got "
        f"{type(data.get('fee_estimate_accepted'))}"
    )
    assert isinstance(data.get("fee_waiver_requested"), bool), (
        "fee_waiver_requested must be bool"
    )
    # fee_waiver_granted is nullable until adjudicated.
    fwg = data.get("fee_waiver_granted", None)
    assert fwg is None or isinstance(fwg, bool), (
        f"fee_waiver_granted must be bool or null, got {fwg!r}"
    )
    assert isinstance(data.get("glomar_invoked"), bool), (
        "glomar_invoked must be bool"
    )
    basis = data.get("glomar_exemption_basis", [])
    assert isinstance(basis, list), (
        f"glomar_exemption_basis must be array, got {type(basis)}"
    )
    tdc = data.get("tolling_days_consumed")
    assert isinstance(tdc, int) and tdc >= 0, (
        f"tolling_days_consumed must be non-negative int, got {tdc!r}"
    )


# ---------------------------------------------------------------------------
# ResponsiveRecord — PRD §3.6
# ---------------------------------------------------------------------------
def assert_responsive_record(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("request_id"), str)
    assert isinstance(data.get("title"), str) and data["title"]
    assert isinstance(data.get("page_count"), int)
    assert data["page_count"] >= 1, (
        f"page_count must be >= 1, got {data['page_count']}"
    )
    assert isinstance(data.get("contains_third_party_info"), bool)
    if data["contains_third_party_info"]:
        tpid = data.get("third_party_id")
        assert isinstance(tpid, str) and tpid, (
            "contains_third_party_info=true implies non-null third_party_id, "
            f"got {tpid!r}"
        )
    assert data.get("disposition") in {
        "PENDING_REVIEW", "RELEASED_FULL",
        "RELEASED_REDACTED", "WITHHELD_FULL",
    }, f"disposition invalid: {data.get('disposition')!r}"


# ---------------------------------------------------------------------------
# ExemptionClaim — PRD §3.6 (append-only)
# ---------------------------------------------------------------------------
def assert_exemption_claim(data: Dict[str, Any]) -> None:
    assert_append_only_fields(data)
    assert isinstance(data.get("record_id"), str)
    assert data.get("exemption_code") in {
        "B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B9",
    }, f"exemption_code invalid: {data.get('exemption_code')!r}"
    assert data.get("redaction_scope") in {"FULL", "PARTIAL"}
    assert isinstance(data.get("rationale"), str) and data["rationale"]


# ---------------------------------------------------------------------------
# ThirdPartyNotice — PRD §3.7
# ---------------------------------------------------------------------------
def assert_third_party_notice(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("request_id"), str)
    assert isinstance(data.get("record_id"), str)
    assert isinstance(data.get("third_party_id"), str) and data["third_party_id"]
    assert data.get("status") in {
        "PENDING_RESPONSE", "CONSENTED", "OBJECTED",
        "EXPIRED", "OVERRIDDEN",
    }, f"ThirdPartyNotice.status invalid: {data.get('status')!r}"


# ---------------------------------------------------------------------------
# Appeal — PRD §3.9
# ---------------------------------------------------------------------------
def assert_appeal(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("request_id"), str)
    assert data.get("appellant_role") in {"REQUESTER", "THIRD_PARTY"}
    assert isinstance(data.get("grounds"), str) and data["grounds"]
    assert data.get("status") in {
        "SUBMITTED", "UNDER_REVIEW", "UPHELD",
        "REVERSED", "REMANDED", "DISMISSED",
    }, f"Appeal.status invalid: {data.get('status')!r}"


# ---------------------------------------------------------------------------
# FeeAssessment — PRD §3.3, §3.8
# ---------------------------------------------------------------------------
def assert_fee_assessment(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("request_id"), str)
    assert data.get("status") in {
        "DRAFT", "ESTIMATED", "ACCEPTED", "FINALIZED", "WAIVED",
    }, f"FeeAssessment.status invalid: {data.get('status')!r}"
    assert isinstance(data.get("estimated_pages"), int)
    # estimated_search_hours and estimated_review_hours may be int or float.
    esh = data.get("estimated_search_hours")
    assert isinstance(esh, (int, float)), (
        f"estimated_search_hours must be numeric, got {type(esh)}"
    )
    erh = data.get("estimated_review_hours")
    assert isinstance(erh, (int, float)), (
        f"estimated_review_hours must be numeric, got {type(erh)}"
    )
    # estimate_total_cents and final_total_cents are integer cents.
    etc = data.get("estimate_total_cents")
    assert isinstance(etc, int) and etc >= 0, (
        f"estimate_total_cents must be non-negative int, got {etc!r}"
    )
    ftc = data.get("final_total_cents")
    assert isinstance(ftc, int) and ftc >= 0, (
        f"final_total_cents must be non-negative int, got {ftc!r}"
    )


# ---------------------------------------------------------------------------
# AuditEntry — PRD §2.6 (append-only)
# ---------------------------------------------------------------------------
def assert_audit_entry(data: Dict[str, Any]) -> None:
    assert_append_only_fields(data)
    assert data.get("subject_type") in {
        "REQUEST", "APPEAL", "THIRD_PARTY_NOTICE", "FEE_ASSESSMENT",
    }, f"subject_type invalid: {data.get('subject_type')!r}"
    assert isinstance(data.get("subject_id"), str)
    assert isinstance(data.get("event_code"), str) and data["event_code"]
    assert isinstance(data.get("actor_role"), str)
    assert isinstance(data.get("actor_id"), str)


# ---------------------------------------------------------------------------
# Multi-entry helpers — audit filtering / chronology
# ---------------------------------------------------------------------------
def find_audit_entries_with(entries: Iterable[Dict[str, Any]],
                            *,
                            subject_type: Optional[str] = None,
                            subject_id: Optional[str] = None,
                            event_code: Optional[str] = None,
                            ) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for e in entries:
        if subject_type is not None and e.get("subject_type") != subject_type:
            continue
        if subject_id is not None and e.get("subject_id") != subject_id:
            continue
        if event_code is not None and e.get("event_code") != event_code:
            continue
        out.append(e)
    return out


__all__ = [
    "assert_common_fields",
    "assert_append_only_fields",
    "assert_status",
    "assert_version_incremented_by",
    "assert_requester",
    "assert_request",
    "assert_responsive_record",
    "assert_exemption_claim",
    "assert_third_party_notice",
    "assert_appeal",
    "assert_fee_assessment",
    "assert_audit_entry",
    "find_audit_entries_with",
]
