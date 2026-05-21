"""Entity assertions and domain invariant checkers.

`assert_{entity}(data)` walks the field set the PRD declares for each
entity. Common-fields resources (PRD §2.4) carry id + created_at +
updated_at + version. Append-only / leaf records (JurisdictionPolicy,
AuditEvent) carry only id + created_at.
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Status enum-like sets — used by entity assertions.
# ---------------------------------------------------------------------------
ELIGIBILITY_POSTURES = {"ELIGIBLE", "UNDER_REVIEW", "ADVERSE", "LOCKED"}
CONSENT_STATUSES = {"ACTIVE", "REVOKED", "SUPERSEDED"}
ORDER_STATUSES = {
    "INTAKE", "IN_VERIFICATION", "AWAITING_ADJUDICATION",
    "PRE_ADVERSE_ISSUED", "AWAITING_FINAL", "REWORK",
    "COMPLETED_CLEAR", "TERMINATED_ADVERSE", "CANCELLED",
}
COMPOSITE_DECISIONS = {"PENDING", "CLEAR", "CONSIDER", "INELIGIBLE"}
VERIFICATION_ITEM_STATUSES = {
    "QUEUED", "IN_PROGRESS", "RETURNED", "DISPUTED",
    "REWORK_REQUIRED", "PASSED", "FAILED",
}
VERIFICATION_ITEM_KINDS = {"CRIMINAL", "MVR", "EDUCATION"}
DISPUTE_STATUSES = {"OPEN", "UPHELD", "OVERTURNED"}
ADVERSE_NOTIFICATION_STATUSES = {
    "PENDING_DELIVERY", "PRE_DELIVERED", "FINAL_DELIVERED",
}
ADVERSE_PROCEDURAL_STATUSES = {
    "PRE_AWAITING_DISPUTE_WINDOW", "DISPUTE_PAUSED",
    "READY_FOR_FINAL", "FINALIZED", "ABANDONED",
}
BAN_THE_BOX_STAGES = {"PRE_OFFER", "POST_INTERVIEW", "POST_OFFER"}
AUDIT_EVENT_TYPES = {
    "CONSENT_RECORDED", "CONSENT_REVOKED", "ORDER_OPENED",
    "ITEM_RETURNED", "ITEM_FAILED", "DISPUTE_OPENED",
    "DISPUTE_RESOLVED", "PRE_ADVERSE_SENT", "FINAL_ADVERSE_ISSUED",
    "ORDER_CANCELLED", "REWORK_REQUESTED",
}
AUDIT_SUBJECT_ENTITIES = {
    "Candidate", "BackgroundCheckOrder", "VerificationItem",
    "Dispute", "AdverseActionFlow", "ConsentDisclosure",
}


# ---------------------------------------------------------------------------
# Envelope checks — common-fields vs append-only.
# ---------------------------------------------------------------------------
def assert_common_fields(data: Dict[str, Any]) -> None:
    """PRD §2.4: "Each carries an `id`, which is a server-minted UUID
    with no type prefix. Each carries a `created_at` timestamp ... and
    an `updated_at` timestamp ... and an integer `version` that starts
    at 1 and increments by 1 on every mutation."
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
    """PRD §2.4: "`JurisdictionPolicy` rows carry only an `id` and a
    `created_at`; they have no `updated_at` and no `version`.
    `AuditEvent` rows likewise carry only an `id` and a `created_at`;
    an audit event is an immutable record and never mutates."
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
        f"(found {data.get('updated_at')!r})"
    )
    assert "version" not in data, (
        "append-only entity must not expose 'version' "
        f"(found {data.get('version')!r})"
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
    """PRD §2.8: "the server updates the target row's `updated_at` and
    increments its integer `version` by 1."
    """
    assert "version" in prior and "version" in current, (
        "both prior and current must carry version"
    )
    assert current["version"] == prior["version"] + delta, (
        f"Expected version {prior['version']} + {delta} = "
        f"{prior['version'] + delta}, got {current['version']}"
    )


# ---------------------------------------------------------------------------
# Candidate — PRD §3.1
# ---------------------------------------------------------------------------
def assert_candidate(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("full_name"), str)
    assert len(data["full_name"]) > 0
    assert isinstance(data.get("email"), str) and "@" in data["email"]
    assert data.get("residence_jurisdiction") in (
        "CA", "NY", "IL", "TX", "FL", "MA", "WA"
    ), (
        f"residence_jurisdiction must be one of the seven supported "
        f"codes, got {data.get('residence_jurisdiction')!r}"
    )
    assert isinstance(data.get("date_of_birth"), str)
    # date_of_birth is "YYYY-MM-DD" per PRD §3.1.
    assert len(data["date_of_birth"]) == 10
    assert data.get("eligibility_posture") in ELIGIBILITY_POSTURES, (
        f"eligibility_posture must be one of {ELIGIBILITY_POSTURES}, "
        f"got {data.get('eligibility_posture')!r}"
    )
    assert isinstance(data.get("salary_history_disclosed"), bool)
    # archived_at may be null or an ISO timestamp.
    archived = data.get("archived_at")
    if archived is not None:
        assert is_iso8601_timestamp(str(archived))


# ---------------------------------------------------------------------------
# ConsentDisclosure — PRD §3.2
# ---------------------------------------------------------------------------
def assert_consent_disclosure(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(str(data.get("candidate_id", "")))
    assert isinstance(data.get("disclosure_text_hash"), str)
    assert len(data["disclosure_text_hash"]) > 0
    assert isinstance(data.get("consent_signature"), str)
    assert is_iso8601_timestamp(str(data.get("consent_timestamp", "")))
    assert is_iso8601_timestamp(str(data.get("disclosure_presented_at", "")))
    revoked = data.get("revoked_at")
    if revoked is not None:
        assert is_iso8601_timestamp(str(revoked))
    assert data.get("status") in CONSENT_STATUSES, (
        f"ConsentDisclosure.status must be one of {CONSENT_STATUSES}, "
        f"got {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# BackgroundCheckOrder — PRD §3.3
# ---------------------------------------------------------------------------
def assert_background_check_order(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(str(data.get("candidate_id", "")))
    assert is_valid_uuid(str(data.get("consent_disclosure_id", "")))
    assert data.get("stage_at_order") in BAN_THE_BOX_STAGES, (
        f"stage_at_order must be one of {BAN_THE_BOX_STAGES}, "
        f"got {data.get('stage_at_order')!r}"
    )
    packages = data.get("requested_packages")
    assert isinstance(packages, list)
    assert len(packages) > 0, "requested_packages must be non-empty"
    assert len(set(packages)) == len(packages), (
        f"requested_packages must have no duplicates, got {packages!r}"
    )
    for pkg in packages:
        assert pkg in ("CRIMINAL", "MVR", "EDUCATION"), (
            f"unknown package {pkg!r}"
        )
    assert data.get("status") in ORDER_STATUSES, (
        f"BackgroundCheckOrder.status must be one of {ORDER_STATUSES}, "
        f"got {data.get('status')!r}"
    )
    assert data.get("composite_decision") in COMPOSITE_DECISIONS, (
        f"composite_decision must be one of {COMPOSITE_DECISIONS}, "
        f"got {data.get('composite_decision')!r}"
    )


# ---------------------------------------------------------------------------
# VerificationItem — PRD §3.4
# ---------------------------------------------------------------------------
def assert_verification_item(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(str(data.get("order_id", "")))
    assert data.get("kind") in VERIFICATION_ITEM_KINDS, (
        f"kind must be one of {VERIFICATION_ITEM_KINDS}, "
        f"got {data.get('kind')!r}"
    )
    assert data.get("status") in VERIFICATION_ITEM_STATUSES, (
        f"VerificationItem.status must be one of "
        f"{VERIFICATION_ITEM_STATUSES}, got {data.get('status')!r}"
    )
    score = data.get("severity_score")
    # severity_score may be 0 before return; once set, in 0..100.
    if score is not None:
        assert isinstance(score, int), (
            f"severity_score must be int, got {type(score)}"
        )
        assert 0 <= score <= 100, (
            f"severity_score out of [0,100]: {score}"
        )
    rework = data.get("rework_count")
    if rework is not None:
        assert isinstance(rework, int)
        # PRD §3.4: "The cap is 2".
        assert 0 <= rework <= 2, (
            f"rework_count out of [0,2]: {rework}"
        )


# ---------------------------------------------------------------------------
# Dispute — PRD §3.7
# ---------------------------------------------------------------------------
def assert_dispute(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(str(data.get("verification_item_id", "")))
    # candidate_id is denormalized per PRD §3.7 / scaffold §1.1.
    cid = data.get("candidate_id")
    if cid is not None:
        assert is_valid_uuid(str(cid)) or len(str(cid)) > 0
    assert isinstance(data.get("reason_text"), str)
    assert 1 <= len(data["reason_text"]) <= 1000, (
        f"reason_text length out of [1,1000]: {len(data['reason_text'])}"
    )
    assert data.get("status") in DISPUTE_STATUSES, (
        f"Dispute.status must be one of {DISPUTE_STATUSES}, "
        f"got {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# AdverseActionFlow — PRD §3.6, §3.8
# ---------------------------------------------------------------------------
def assert_adverse_action_flow(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(str(data.get("order_id", "")))
    # pre_adverse_notice_sent_at is server-stamped, present once issued.
    sent = data.get("pre_adverse_notice_sent_at")
    if sent is not None:
        assert is_iso8601_timestamp(str(sent))
    waiting = data.get("waiting_period_business_days")
    if waiting is not None:
        assert isinstance(waiting, int)
        # PRD §3.1: "federal floor is 5".
        assert waiting >= 5, (
            f"waiting_period_business_days must be >= 5, got {waiting}"
        )
    eligible = data.get("earliest_final_eligible_at")
    if eligible is not None:
        assert is_iso8601_timestamp(str(eligible))
    final_at = data.get("final_adverse_action_at")
    if final_at is not None:
        assert is_iso8601_timestamp(str(final_at))
    assert data.get("notification_status") in ADVERSE_NOTIFICATION_STATUSES, (
        f"notification_status must be one of "
        f"{ADVERSE_NOTIFICATION_STATUSES}, "
        f"got {data.get('notification_status')!r}"
    )
    assert data.get("procedural_status") in ADVERSE_PROCEDURAL_STATUSES, (
        f"procedural_status must be one of "
        f"{ADVERSE_PROCEDURAL_STATUSES}, "
        f"got {data.get('procedural_status')!r}"
    )


# ---------------------------------------------------------------------------
# JurisdictionPolicy — PRD §3.1 (append-only per §2.4)
# ---------------------------------------------------------------------------
def assert_jurisdiction_policy(data: Dict[str, Any]) -> None:
    assert_append_only_fields(data)
    assert data.get("jurisdiction_code") in (
        "CA", "NY", "IL", "TX", "FL", "MA", "WA"
    )
    assert isinstance(data.get("criminal_lookback_years"), int)
    assert data["criminal_lookback_years"] > 0
    assert isinstance(data.get("salary_history_ban"), bool)
    assert data.get("ban_the_box_stage") in BAN_THE_BOX_STAGES
    assert isinstance(data.get("adverse_action_waiting_business_days"), int)
    # PRD §3.1: ">= 5".
    assert data["adverse_action_waiting_business_days"] >= 5


# ---------------------------------------------------------------------------
# AuditEvent — PRD §2.11, §3.9 (append-only per §2.4)
# ---------------------------------------------------------------------------
def assert_audit_event(data: Dict[str, Any]) -> None:
    assert_append_only_fields(data)
    assert data.get("event_type") in AUDIT_EVENT_TYPES, (
        f"event_type must be one of {AUDIT_EVENT_TYPES}, "
        f"got {data.get('event_type')!r}"
    )
    assert data.get("subject_entity") in AUDIT_SUBJECT_ENTITIES, (
        f"subject_entity must be one of {AUDIT_SUBJECT_ENTITIES}, "
        f"got {data.get('subject_entity')!r}"
    )
    assert isinstance(data.get("subject_id"), str)
    assert len(data["subject_id"]) > 0
    assert isinstance(data.get("actor_role"), str)
    assert len(data["actor_role"]) > 0
    assert isinstance(data.get("actor_user_id"), str)
    # previous_event_id is null for the first event on a subject; else
    # a UUID-like string.
    prev = data.get("previous_event_id")
    if prev is not None:
        assert isinstance(prev, str)
        assert len(prev) > 0
    assert isinstance(data.get("payload_hash"), str)
    # SHA-256 hex digests are 64 lowercase-hex chars.
    h = data["payload_hash"]
    assert len(h) == 64, (
        f"payload_hash should be 64 hex chars (SHA-256), got len={len(h)}"
    )
    assert all(c in "0123456789abcdef" for c in h.lower()), (
        f"payload_hash should be lowercase hex, got {h!r}"
    )


def assert_audit_chain_links(events: List[Dict[str, Any]]) -> None:
    """PRD §2.8: "Every state-changing endpoint also appends one or more
    `AuditEvent` rows, each carrying a `previous_event_id` that points
    to the immediately prior `AuditEvent` for the same `subject_id`."
    """
    # Group by subject_id, then per-subject the chain must form a linked
    # list ordered by created_at.
    by_subject: Dict[str, List[Dict[str, Any]]] = {}
    for e in events:
        by_subject.setdefault(e["subject_id"], []).append(e)
    for sid, chain in by_subject.items():
        chain.sort(key=lambda x: x.get("created_at", ""))
        prev_id: Optional[str] = None
        for event in chain:
            assert event.get("previous_event_id") == prev_id, (
                f"audit chain broken for subject {sid}: "
                f"expected previous_event_id={prev_id!r}, "
                f"got {event.get('previous_event_id')!r}"
            )
            prev_id = event.get("id")


def expected_payload_hash(
    *,
    subject_id: str,
    event_type: str,
    actor_user_id: str,
    created_at: str,
    previous_event_id: Optional[str],
) -> str:
    """PRD §2.11: "a `payload_hash` that is a SHA-256 over the
    concatenation of `subject_id`, `event_type`, `actor_user_id`,
    `created_at`, and `previous_event_id`."

    The PRD does not prescribe a separator. The string "concatenation"
    is the only constraint; tests that probe payload_hash use this
    helper only as a sanity check on the SHAPE (64 hex chars) — they
    never assert exact equality against any particular concatenation
    convention, because the PRD does not pin one.
    """
    prev = previous_event_id if previous_event_id is not None else ""
    raw = (
        subject_id + event_type + actor_user_id + created_at + prev
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


__all__ = [
    # Enum-like sets
    "ELIGIBILITY_POSTURES",
    "CONSENT_STATUSES",
    "ORDER_STATUSES",
    "COMPOSITE_DECISIONS",
    "VERIFICATION_ITEM_STATUSES",
    "VERIFICATION_ITEM_KINDS",
    "DISPUTE_STATUSES",
    "ADVERSE_NOTIFICATION_STATUSES",
    "ADVERSE_PROCEDURAL_STATUSES",
    "BAN_THE_BOX_STAGES",
    "AUDIT_EVENT_TYPES",
    "AUDIT_SUBJECT_ENTITIES",
    # Envelope checks
    "assert_common_fields",
    "assert_append_only_fields",
    "assert_status",
    "assert_version_incremented_by",
    # Entity assertions
    "assert_candidate",
    "assert_consent_disclosure",
    "assert_background_check_order",
    "assert_verification_item",
    "assert_dispute",
    "assert_adverse_action_flow",
    "assert_jurisdiction_policy",
    "assert_audit_event",
    "assert_audit_chain_links",
    "expected_payload_hash",
]
