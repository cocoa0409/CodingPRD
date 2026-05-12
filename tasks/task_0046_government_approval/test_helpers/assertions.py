"""Entity assertions and domain invariant checkers.

Each assert_{entity}() verifies that a response dict carries the fields
the PRD declares, with the expected types and enum membership. Domain
invariant helpers cover monetary precision (integer cents per PRD §2.8)
and ISO 8601 / UUID format conformance.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    CAP_SURCHARGE_CENTS,
    HANDLING_RATE_BP,
    OVERHEAD_RATE_BP,
    SURCHARGE_PER_ROUND_CENTS,
    SURCHARGE_TIER_BOUNDARY,
    VERIFICATION_CODE_LEN,
)


# ===========================================================================
# Generic field assertions
# ===========================================================================
def _assert_common_id_created(data: Dict[str, Any]) -> None:
    """PRD §2.4: 'id -- a server-minted UUID with no type prefix; immutable.
    created_at -- an ISO 8601 UTC timestamp with three fractional digits,
    set once at creation.'
    """
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )


def _assert_common_fields(data: Dict[str, Any]) -> None:
    """PRD §2.4: 'updated_at -- an ISO 8601 UTC timestamp with three
    fractional digits, refreshed on every mutation. version -- an
    integer that starts at 1 on creation and increments by 1 on every
    mutation, including the cascading mutations described in §2.5.'
    """
    _assert_common_id_created(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), (
        f"version must be int, got {type(data.get('version')).__name__}"
    )
    assert data["version"] >= 1, f"version must start at 1, got {data['version']}"


# ===========================================================================
# Department (PRD §3.1)
# ===========================================================================
def assert_department(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert isinstance(data["code"], str)
    assert 3 <= len(data["code"]) <= 32, f"code length, got {len(data['code'])}"
    assert isinstance(data["name"], str) and len(data["name"]) >= 1
    # PRD §3.1: 'an optional parent_department_id ... (null at the top of
    # the hierarchy)'
    assert "parent_department_id" in data
    parent = data["parent_department_id"]
    assert parent is None or isinstance(parent, str)
    # PRD §3.1: 'a status of either ACTIVE or ARCHIVED defaulting to ACTIVE.'
    assert data["status"] in ("ACTIVE", "ARCHIVED")


# ===========================================================================
# Matter (PRD §3.1)
# ===========================================================================
def assert_matter(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert isinstance(data["code"], str)
    assert 4 <= len(data["code"]) <= 64
    assert data["theme"] in (
        "BIRTH", "EDUCATION", "BUSINESS", "HOUSING",
        "TRANSPORT", "SOCIAL_SECURITY", "OTHER",
    )
    assert is_valid_uuid(data["owning_department_id"])
    # PRD §3.1: 'The new shell's status is DRAFT_ONLY and its
    # current_published_version_id is null until the first version is
    # published.'
    assert data["status"] in ("DRAFT_ONLY", "PUBLISHED", "ARCHIVED")
    assert "current_published_version_id" in data
    if data["current_published_version_id"] is not None:
        assert is_valid_uuid(data["current_published_version_id"])


# ===========================================================================
# MatterVersion (PRD §3.1, §3.2)
# ===========================================================================
def assert_matter_version(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["matter_id"])
    assert isinstance(data["version_label"], str)
    assert 1 <= len(data["version_label"]) <= 32
    assert isinstance(data["legal_basis"], str)
    assert isinstance(data["conditions"], str)
    assert isinstance(data["required_material_template_ids"], list)
    assert all(
        is_valid_uuid(x) for x in data["required_material_template_ids"]
    )
    # PRD §3.1: 'statutory_time_limit_days between 1 and 365 ... and
    # committed_time_limit_days between 1 and the version's
    # statutory_time_limit_days.'
    assert isinstance(data["statutory_time_limit_days"], int)
    assert 1 <= data["statutory_time_limit_days"] <= 365
    assert isinstance(data["committed_time_limit_days"], int)
    assert 1 <= data["committed_time_limit_days"] <= data["statutory_time_limit_days"]
    # PRD §3.1: 'a warning_threshold_pct between 50 and 99 (default 80)'
    assert isinstance(data["warning_threshold_pct"], int)
    assert 50 <= data["warning_threshold_pct"] <= 99
    # PRD §3.1: 'a fee_amount_cents defaulting to 0 with a non-negative constraint'
    assert isinstance(data["fee_amount_cents"], int)
    assert data["fee_amount_cents"] >= 0
    # PRD §3.1: 'a non-empty channels subset of {ONLINE, OFFLINE}'
    assert isinstance(data["channels"], list) and len(data["channels"]) >= 1
    assert all(c in ("ONLINE", "OFFLINE") for c in data["channels"])
    # PRD §3.2: routing keys
    routing = data["review_routing"]
    assert isinstance(routing, dict)
    assert routing["mode"] in ("SERIAL", "PARALLEL")
    assert is_valid_uuid(routing["lead_department_id"])
    assert isinstance(routing["stages"], list) and len(routing["stages"]) >= 1
    if routing["mode"] == "PARALLEL":
        assert routing["aggregation_rule"] in ("ALL_AGREE", "MAJORITY", "LEAD_DECIDES")
    else:
        # PRD §3.2: 'when mode is SERIAL, aggregation_rule must be null'
        assert routing.get("aggregation_rule") is None
    # PRD §3.1 ranges
    assert 1 <= data["max_correction_rounds"] <= 5
    assert 1 <= data["correction_window_days"] <= 30
    assert is_valid_uuid(data["certificate_template_id"])
    assert data["status"] in ("DRAFT", "PUBLISHED", "SUPERSEDED", "RETIRED")
    if data["status"] == "DRAFT":
        assert data.get("published_at") is None
    else:
        assert is_iso8601_timestamp(data["published_at"])


# ===========================================================================
# MaterialTemplate (PRD §3.3)
# ===========================================================================
def assert_material_template(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert isinstance(data["code"], str)
    assert 4 <= len(data["code"]) <= 64
    assert isinstance(data["title"], str)
    assert data["material_type"] in ("ORIGINAL", "COPY", "NOTARIZED")
    assert data["status"] in ("DRAFT", "PUBLISHED", "RETIRED")


# ===========================================================================
# CertificateTemplate (PRD §3.3)
# ===========================================================================
def assert_certificate_template(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert isinstance(data["code"], str)
    assert 4 <= len(data["code"]) <= 64
    assert isinstance(data["body_template"], str)
    assert isinstance(data["required_variables"], list)
    # PRD §3.3: 'every entry of required_variables must appear in body_template.'
    body = data["body_template"]
    for var in data["required_variables"]:
        assert "{{" + var + "}}" in body, (
            f"required_variable {var!r} must appear in body_template"
        )
    assert isinstance(data["validity_days"], int)
    assert data["validity_days"] >= 0
    assert isinstance(data["official_seal_id"], str)
    assert data["status"] in ("DRAFT", "PUBLISHED", "RETIRED")


# ===========================================================================
# Application (PRD §3.4 -- §3.7)
# ===========================================================================
APPLICATION_REVIEW_STATES = {
    "SUBMITTED", "UNDER_REVIEW", "AWAITING_CORRECTION", "ESCALATED",
    "APPROVED", "REJECTED", "WITHDRAWN",
}
APPLICATION_TERMINAL_STATES = {"APPROVED", "REJECTED", "WITHDRAWN"}


def assert_application(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["matter_version_id"])
    assert isinstance(data["applicant_user_id"], str) and data["applicant_user_id"]
    assert data["channel"] in ("ONLINE", "OFFLINE")
    assert isinstance(data["identity_verified"], bool)
    assert data["payment_status"] in ("PENDING", "PAID", "REFUNDED")
    assert data["review_status"] in APPLICATION_REVIEW_STATES
    assert isinstance(data["correction_round"], int)
    assert data["correction_round"] >= 0
    assert isinstance(data["total_paused_seconds"], int)
    assert data["total_paused_seconds"] >= 0
    # PRD §3.4: 'clock_started_at, deadline_at, and pinned_routing_snapshot
    # remain null until the application transitions to UNDER_REVIEW.'
    if data["review_status"] == "SUBMITTED":
        assert data.get("clock_started_at") is None
        assert data.get("pinned_routing_snapshot") is None
    else:
        assert is_iso8601_timestamp(data["clock_started_at"])
        assert isinstance(data["pinned_routing_snapshot"], dict)


# ===========================================================================
# ReviewTask (PRD §3.2, §3.6)
# ===========================================================================
REVIEW_TASK_STATES = {"PENDING", "IN_PROGRESS", "AGREED", "DISAGREED", "SKIPPED"}


def assert_review_task(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["application_id"])
    assert is_valid_uuid(data["department_id"])
    assert isinstance(data["stage_index"], int) and data["stage_index"] >= 0
    assert isinstance(data["is_lead"], bool)
    assert data["status"] in REVIEW_TASK_STATES
    if data["status"] in ("AGREED", "DISAGREED"):
        # PRD §3.6: 'the task records decided_at as the server's current
        # time and stores the opinion_text.'
        assert is_iso8601_timestamp(data["decided_at"])


# ===========================================================================
# CorrectionNotice (PRD §3.6) -- common_fields: false
# ===========================================================================
CORRECTION_NOTICE_STATES = {"OPEN", "RESOLVED", "EXPIRED"}


def assert_correction_notice(data: Dict[str, Any]) -> None:
    """PRD §2.4: 'CorrectionNotice ... omits both updated_at and version.'"""
    _assert_common_id_created(data)
    assert is_valid_uuid(data["application_id"])
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1
    assert isinstance(data["deficiencies"], list) and len(data["deficiencies"]) >= 1
    for entry in data["deficiencies"]:
        assert "material_template_id" in entry
        assert "reason" in entry
    assert is_iso8601_timestamp(data["issued_at"])
    assert is_iso8601_timestamp(data["due_at"])
    assert data["status"] in CORRECTION_NOTICE_STATES
    if data["status"] == "RESOLVED":
        assert is_iso8601_timestamp(data["resolved_at"])


# ===========================================================================
# Certificate (PRD §3.10)
# ===========================================================================
CERTIFICATE_STATES = {"ACTIVE", "EXPIRED", "REVOKED", "REISSUED"}


def assert_certificate(data: Dict[str, Any]) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data["application_id"])
    assert is_valid_uuid(data["certificate_template_id"])
    # PRD §3.10: 'serial_number is generated as
    # GOV-{matter.code}-{YYMMDD}-{6-digit zero-padded sequence}'
    serial = data["serial_number"]
    assert isinstance(serial, str)
    assert serial.startswith("GOV-"), f"serial must start GOV-, got {serial!r}"
    parts = serial.split("-")
    assert len(parts) >= 4, f"serial_number must follow GOV-{{code}}-YYMMDD-NNNNNN, got {serial!r}"
    assert len(parts[-1]) == 6 and parts[-1].isdigit(), (
        f"serial trailing sequence must be 6-digit zero-padded, got {parts[-1]!r}"
    )
    assert len(parts[-2]) == 6 and parts[-2].isdigit(), (
        f"serial date segment must be YYMMDD, got {parts[-2]!r}"
    )
    # PRD §3.10: 'verification_code is generated as a 16-character
    # alphanumeric string ... The leading 16 characters of the encoded
    # result form the value.'
    code = data["verification_code"]
    assert isinstance(code, str) and len(code) == VERIFICATION_CODE_LEN, (
        f"verification_code must be 16 chars, got {code!r}"
    )
    assert code.isalnum(), f"verification_code must be alphanumeric, got {code!r}"
    assert isinstance(data["rendered_body"], str)
    assert is_iso8601_timestamp(data["issued_at"])
    # PRD §3.10: 'expires_at is set to null when the template's
    # validity_days is 0; otherwise it is computed as issued_at plus
    # validity_days multiplied by the day-in-seconds constant of 86,400.'
    assert "expires_at" in data
    if data["expires_at"] is not None:
        assert is_iso8601_timestamp(data["expires_at"])
    assert data["status"] in CERTIFICATE_STATES
    # PRD §3.10: 'a null superseded_by_certificate_id' on issuance.
    assert "superseded_by_certificate_id" in data
    if data["superseded_by_certificate_id"] is not None:
        assert is_valid_uuid(data["superseded_by_certificate_id"])


# ===========================================================================
# ExternalEvent (PRD §2.12) -- common_fields: false
# ===========================================================================
def assert_external_event(data: Dict[str, Any]) -> None:
    """PRD §2.4: 'ExternalEvent ... omits both updated_at and version.'"""
    _assert_common_id_created(data)
    assert data["event_type"] in (
        "IDENTITY_VERIFIED", "SIGNATURE_AFFIXED",
        "PAYMENT_SETTLED", "DATA_SHARED",
    )
    assert isinstance(data["idempotency_key"], str)
    assert isinstance(data["subject_application_id"], str)
    assert isinstance(data["payload"], dict)
    assert isinstance(data["processed"], bool)


# ===========================================================================
# AuditLog (PRD §2.13) -- common_fields: false
# ===========================================================================
AUDIT_ACTIONS = {
    "APPLICATION_SUBMIT", "REVIEW_DECIDE", "CORRECTION_ISSUE",
    "CORRECTION_RESUBMIT", "ESCALATE", "APPROVE", "REJECT",
    "CERT_ISSUE", "CERT_REISSUE", "CERT_REVOKE",
}


def assert_audit_log(data: Dict[str, Any]) -> None:
    """PRD §2.4 / §2.13: 'AuditLog ... append-only ... created_at is
    recorded; updated_at and version are absent.'"""
    _assert_common_id_created(data)
    assert isinstance(data["actor_role"], str)
    assert isinstance(data["actor_id"], str)
    assert data["action"] in AUDIT_ACTIONS
    assert isinstance(data["target_entity"], str)
    assert isinstance(data["target_id"], str)
    assert isinstance(data["payload_snapshot"], dict)


# ===========================================================================
# Fee breakdown formula (PRD §3.11) -- shared between fixtures and tests
# ===========================================================================
def expected_surcharge_subtotal_cents(correction_round: int) -> int:
    """PRD §3.11: 'The per-correction surcharge subtotal in cents is 0
    when the application's correction_round is 0; for correction_round
    between 1 and 2 inclusive it equals the per-round surcharge constant
    of 500 cents ... multiplied by correction_round; and for
    correction_round strictly greater than 2 it is capped at the
    surcharge cap of 1,000 cents.'
    """
    if correction_round <= 0:
        return 0
    if correction_round <= SURCHARGE_TIER_BOUNDARY:
        return SURCHARGE_PER_ROUND_CENTS * correction_round
    return CAP_SURCHARGE_CENTS


def expected_handling_line_cents(base_fee_cents: int) -> int:
    """PRD §3.11: 'The handling line in cents equals the base fee in
    cents multiplied by the handling-rate basis points (200 basis points,
    i.e., 2.00%), divided by 10,000, and ceilinged to the next integer
    cent.'
    """
    return math.ceil(base_fee_cents * HANDLING_RATE_BP / 10000)


def expected_admin_overhead_cents(surcharge_subtotal_cents: int) -> int:
    """PRD §3.11: 'The administrative-overhead line in cents equals the
    surcharge subtotal in cents multiplied by the overhead-rate basis
    points (500 basis points, i.e., 5.00%), divided by 10,000, and
    ceilinged to the next integer cent.'
    """
    return math.ceil(surcharge_subtotal_cents * OVERHEAD_RATE_BP / 10000)


def expected_fee_total_cents(base_fee_cents: int, correction_round: int) -> int:
    """PRD §3.11: 'The total in cents is then the literal sum of four
    integer values: the base fee, the handling line, the surcharge
    subtotal, and the administrative-overhead line -- in that order.'
    """
    surcharge = expected_surcharge_subtotal_cents(correction_round)
    handling = expected_handling_line_cents(base_fee_cents)
    overhead = expected_admin_overhead_cents(surcharge)
    return base_fee_cents + handling + surcharge + overhead


# ===========================================================================
# Search / filter helpers
# ===========================================================================
def find_audit_entries(entries: Iterable[Dict[str, Any]],
                       *,
                       action: Optional[str] = None,
                       target_entity: Optional[str] = None,
                       target_id: Optional[str] = None,
                       ) -> List[Dict[str, Any]]:
    """Filter a flat audit-log list by any combination of fields."""
    out: List[Dict[str, Any]] = []
    for e in entries:
        if action is not None and e.get("action") != action:
            continue
        if target_entity is not None and e.get("target_entity") != target_entity:
            continue
        if target_id is not None and e.get("target_id") != target_id:
            continue
        out.append(e)
    return out


__all__ = [
    "assert_department",
    "assert_matter",
    "assert_matter_version",
    "assert_material_template",
    "assert_certificate_template",
    "assert_application",
    "assert_review_task",
    "assert_correction_notice",
    "assert_certificate",
    "assert_external_event",
    "assert_audit_log",
    "expected_surcharge_subtotal_cents",
    "expected_handling_line_cents",
    "expected_admin_overhead_cents",
    "expected_fee_total_cents",
    "find_audit_entries",
    "APPLICATION_REVIEW_STATES",
    "APPLICATION_TERMINAL_STATES",
    "REVIEW_TASK_STATES",
    "CORRECTION_NOTICE_STATES",
    "CERTIFICATE_STATES",
    "AUDIT_ACTIONS",
]
