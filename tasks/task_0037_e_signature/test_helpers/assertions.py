"""Per-entity assertions and domain invariant checkers.

Field shape and value-range checks are pinned to PRD prose. Each assertion
checks exactly the surface contract the PRD declares -- never more, never
less.
"""
from __future__ import annotations
import re
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Common-fields helpers (PRD §2.4)
# ---------------------------------------------------------------------------
def _assert_versioned(data: Dict[str, Any], label: str) -> None:
    """Standard resources expose id, created_at, updated_at, version
    (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{label}.id must be a UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601 with 3 fractional digits, "
        f"got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be ISO 8601 with 3 fractional digits, "
        f"got {data.get('updated_at')!r}"
    )
    version = data.get("version")
    assert isinstance(version, int) and version >= 1, (
        f"{label}.version must be a positive integer, got {version!r}"
    )


def _assert_append_only(data: Dict[str, Any], label: str) -> None:
    """Append-only entries (IdentityVerification, TimestampToken,
    ReminderEvent, AuditLog) expose only id and created_at per PRD §2.4."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{label}.id must be a UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    )


_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


def is_lower_hex_64(s: Any) -> bool:
    """PRD §3.1: 'exactly 64 lowercase hex characters'."""
    return isinstance(s, str) and bool(_HEX64_RE.match(s))


# ---------------------------------------------------------------------------
# Template (PRD §3.1)
# ---------------------------------------------------------------------------
def assert_template(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "Template")
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert data["category"] in {
        "HR", "SALES", "PROCUREMENT", "LEGAL", "FINANCE", "OTHER",
    }
    assert isinstance(data["owner_org_id"], str) and data["owner_org_id"]
    assert data["permission_scope"] in {"ORG_ONLY", "CROSS_ORG", "PUBLIC"}
    assert isinstance(data["latest_version_number"], int)
    assert data["latest_version_number"] >= 0
    pvn = data.get("published_version_number")
    assert pvn is None or (isinstance(pvn, int) and pvn >= 1)
    assert data["status"] in {"ACTIVE", "ARCHIVED"}


# ---------------------------------------------------------------------------
# TemplateVersion (PRD §3.1)
# ---------------------------------------------------------------------------
def assert_template_version(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "TemplateVersion")
    assert isinstance(data["template_id"], str) and data["template_id"]
    assert isinstance(data["version_number"], int)
    assert data["version_number"] >= 1
    assert is_lower_hex_64(data["document_blob_sha256"]), (
        f"TemplateVersion.document_blob_sha256 must be 64 lowercase hex, "
        f"got {data.get('document_blob_sha256')!r}"
    )
    assert isinstance(data["page_count"], int) and data["page_count"] >= 1
    assert isinstance(data["variable_fields"], list)
    assert isinstance(data["signature_positions"], list)
    assert data["status"] in {"DRAFT", "PUBLISHED", "DEPRECATED"}


# ---------------------------------------------------------------------------
# Contract (PRD §3.2-§3.7)
# ---------------------------------------------------------------------------
def assert_contract(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "Contract")
    assert isinstance(data["template_version_id"], str)
    assert isinstance(data["initiator_user_id"], str)
    assert isinstance(data["initiator_org_id"], str)
    assert isinstance(data["title"], str) and 1 <= len(data["title"]) <= 200
    assert isinstance(data["variable_values"], dict)
    assert data["status"] in {
        "DRAFT", "PENDING_SIGN", "PARTIALLY_SIGNED",
        "COMPLETED", "EXPIRED", "VOIDED",
    }
    assert is_iso8601_timestamp(data["expires_at"])
    # Optional / null-allowed fields per PRD §3.2 prose.
    if data.get("activated_at") is not None:
        assert is_iso8601_timestamp(data["activated_at"])
    if data.get("completed_at") is not None:
        assert is_iso8601_timestamp(data["completed_at"])
    if data.get("voided_at") is not None:
        assert is_iso8601_timestamp(data["voided_at"])
    void_reason = data.get("void_reason")
    assert void_reason in (None, "MANUAL", "EXPIRED_AUTO",
                           "REJECTED_BY_PARTY")
    if data.get("document_fingerprint_sha256") is not None:
        assert is_lower_hex_64(data["document_fingerprint_sha256"]), (
            "Contract.document_fingerprint_sha256 must be 64 lowercase hex"
        )
    # Numeric quantities (PRD §2.5).
    assert isinstance(data["signing_progress_percent"], (int, float))
    assert 0 <= data["signing_progress_percent"] <= 100
    assert isinstance(data["evidence_strength_score"], (int, float))
    assert 0 <= data["evidence_strength_score"] <= 100
    assert data["evidence_tier"] in {"BRONZE", "SILVER", "GOLD", "NOTARIZED"}


# ---------------------------------------------------------------------------
# SigningStep (PRD §3.2, §3.4, §3.6)
# ---------------------------------------------------------------------------
def assert_signing_step(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "SigningStep")
    assert isinstance(data["contract_id"], str)
    assert isinstance(data["step_index"], int)
    assert data["step_index"] >= 1
    assert data["mode"] in {"SEQUENTIAL", "PARALLEL_COUNTERSIGN"}
    bc = data.get("branch_condition")
    assert bc is None or isinstance(bc, dict)
    assert data["status"] in {
        "PENDING", "ACTIVE", "SIGNED", "SKIPPED", "REJECTED",
    }
    if data.get("activated_at") is not None:
        assert is_iso8601_timestamp(data["activated_at"])
    if data.get("completed_at") is not None:
        assert is_iso8601_timestamp(data["completed_at"])


# ---------------------------------------------------------------------------
# SigningParty (PRD §3.2, §3.5, §3.6)
# ---------------------------------------------------------------------------
def assert_signing_party(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "SigningParty")
    assert isinstance(data["signing_step_id"], str)
    assert isinstance(data["contract_id"], str)
    assert isinstance(data["role_key"], str) and data["role_key"]
    assert data["signer_type"] in {
        "INDIVIDUAL", "ORG_LEGAL_REP", "ORG_DELEGATE",
    }
    assert isinstance(data["signer_user_id"], str)
    if data.get("signer_org_id") is not None:
        assert isinstance(data["signer_org_id"], str)
    if data.get("delegation_authorization_id") is not None:
        assert isinstance(data["delegation_authorization_id"], str)
    factors = data["required_auth_factors"]
    assert isinstance(factors, list) and 1 <= len(factors) <= 4
    assert len(set(factors)) == len(factors), (
        "required_auth_factors must have unique values"
    )
    valid_factors = {"SMS", "FACE", "CA_CERT", "BANK_CARD"}
    assert set(factors).issubset(valid_factors)
    assert data["status"] in {
        "WAITING", "AUTHENTICATING", "SIGNED", "DECLINED", "SKIPPED",
    }
    if data.get("signed_at") is not None:
        assert is_iso8601_timestamp(data["signed_at"])


# ---------------------------------------------------------------------------
# IdentityVerification (PRD §3.5) -- append-only
# ---------------------------------------------------------------------------
def assert_identity_verification(data: Dict[str, Any]) -> None:
    _assert_append_only(data, "IdentityVerification")
    assert "updated_at" not in data, (
        "PRD §2.4: IdentityVerification is append-only and must NOT carry "
        "updated_at"
    )
    assert "version" not in data, (
        "PRD §2.4: IdentityVerification is append-only and must NOT carry "
        "version"
    )
    assert isinstance(data["subject_user_id"], str)
    if data.get("contract_id") is not None:
        assert isinstance(data["contract_id"], str)
    assert isinstance(data["factors_attempted"], list)
    assert isinstance(data["factors_passed"], list)
    assert isinstance(data["real_name_match"], bool)
    assert isinstance(data["org_binding_verified"], bool)
    assert data["identity_strength"] in {"WEAK", "STRONG", "EXTRA_STRONG"}
    assert data["result"] in {"VERIFIED", "FAILED"}
    assert is_iso8601_timestamp(data["archived_at"])


# ---------------------------------------------------------------------------
# TimestampToken (PRD §3.5) -- append-only
# ---------------------------------------------------------------------------
def assert_timestamp_token(data: Dict[str, Any]) -> None:
    _assert_append_only(data, "TimestampToken")
    assert "updated_at" not in data
    assert "version" not in data
    assert isinstance(data["contract_id"], str)
    assert isinstance(data["signing_party_id"], str)
    assert is_iso8601_timestamp(data["server_anchor_at"])
    assert is_iso8601_timestamp(data["tsa_anchor_at"])
    assert isinstance(data["tsa_provider"], str)
    assert isinstance(data["tsa_token_value"], str)
    assert is_lower_hex_64(data["hash_signed"])
    assert isinstance(data["drift_seconds"], (int, float))
    assert data["drift_seconds"] >= 0
    assert data["verification_status"] in {"VALID", "INVALID"}


# ---------------------------------------------------------------------------
# EvidencePackage (PRD §3.11)
# ---------------------------------------------------------------------------
def assert_evidence_package(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "EvidencePackage")
    assert isinstance(data["contract_id"], str)
    assert data["status"] in {"PENDING", "GENERATING", "SEALED", "EXPORTED"}
    if data.get("package_sha256") is not None:
        assert is_lower_hex_64(data["package_sha256"]), (
            "EvidencePackage.package_sha256 must be 64 lowercase hex"
        )
    assert data["notary_provider"] in {"NONE", "NOTARY_PUBLIC", "BLOCKCHAIN"}
    if data.get("sealed_at") is not None:
        assert is_iso8601_timestamp(data["sealed_at"])
    if data.get("exported_at") is not None:
        assert is_iso8601_timestamp(data["exported_at"])


# ---------------------------------------------------------------------------
# ReminderRule (PRD §3.8)
# ---------------------------------------------------------------------------
def assert_reminder_rule(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "ReminderRule")
    assert isinstance(data["contract_id"], str)
    assert isinstance(data["interval_hours"], int)
    assert 1 <= data["interval_hours"] <= 168
    assert isinstance(data["channels"], list) and data["channels"]
    assert set(data["channels"]).issubset({"SMS", "EMAIL", "IM"})
    assert len(set(data["channels"])) == len(data["channels"])
    assert isinstance(data["escalation_after_misses"], int)
    assert 0 <= data["escalation_after_misses"] <= 10
    assert isinstance(data["enabled"], bool)
    if data.get("last_fired_at") is not None:
        assert is_iso8601_timestamp(data["last_fired_at"])
    assert isinstance(data["misses_count"], int)
    assert data["misses_count"] >= 0


# ---------------------------------------------------------------------------
# ReminderEvent (PRD §3.8) -- append-only
# ---------------------------------------------------------------------------
def assert_reminder_event(data: Dict[str, Any]) -> None:
    _assert_append_only(data, "ReminderEvent")
    assert "updated_at" not in data
    assert "version" not in data
    assert isinstance(data["reminder_rule_id"], str)
    assert isinstance(data["contract_id"], str)
    assert is_iso8601_timestamp(data["fired_at"])
    assert isinstance(data["channels_used"], list)
    # PRD §3.8: channels_used = rule.channels (+ INITIATOR_IM on escalation).
    valid_channel_set = {"SMS", "EMAIL", "IM", "INITIATOR_IM"}
    for ch in data["channels_used"]:
        assert ch in valid_channel_set, f"unexpected channel {ch!r}"
    assert isinstance(data["escalated"], bool)
    assert isinstance(data["idempotency_key"], str)


# ---------------------------------------------------------------------------
# AuditLog (PRD §2.8) -- append-only, hash-chained
# ---------------------------------------------------------------------------
_AUDIT_ACTIONS = {
    "TEMPLATE_PUBLISHED", "TEMPLATE_DEPRECATED",
    "CONTRACT_INITIATED", "CONTRACT_ACTIVATED",
    "PARTY_SIGNED", "PARTY_REJECTED",
    "CONTRACT_VOIDED", "CONTRACT_EXPIRED_AUTO",
    "CONTRACT_REINITIATED",
    "EVIDENCE_SEALED", "EVIDENCE_EXPORTED",
    "REMINDER_FIRED",
}


def assert_audit_log_entry(data: Dict[str, Any]) -> None:
    _assert_append_only(data, "AuditLog")
    assert "updated_at" not in data
    assert "version" not in data
    # PRD §2.8: contract_id OR template_id may be null (template-scoped vs
    # contract-scoped events).
    contract_id = data.get("contract_id")
    template_id = data.get("template_id")
    if contract_id is not None:
        assert isinstance(contract_id, str)
    if template_id is not None:
        assert isinstance(template_id, str)
    assert isinstance(data["actor_user_id"], str)
    assert isinstance(data["actor_role"], str)
    assert data["action"] in _AUDIT_ACTIONS, (
        f"AuditLog.action must be one of {_AUDIT_ACTIONS}, "
        f"got {data['action']!r}"
    )
    assert is_lower_hex_64(data["payload_sha256"]), (
        "AuditLog.payload_sha256 must be 64 lowercase hex"
    )
    if data.get("prev_log_sha256") is not None:
        assert is_lower_hex_64(data["prev_log_sha256"]), (
            "AuditLog.prev_log_sha256 must be 64 lowercase hex when set"
        )
    assert is_iso8601_timestamp(data["occurred_at"])


# ---------------------------------------------------------------------------
# Audit-log chain integrity (PRD §2.8)
# ---------------------------------------------------------------------------
def assert_audit_log_chain(logs: List[Dict[str, Any]]) -> None:
    """PRD §2.8: 'the first entry in each chain has prev_log_sha256 set to
    null'; for every L_i (i >= 2), L_i.prev_log_sha256 == L_{i-1}.payload_sha256.
    The list MUST be in occurred_at-ascending order (PRD §4 says
    /audit-logs is ordered by occurred_at ASC)."""
    if not logs:
        return
    assert logs[0].get("prev_log_sha256") in (None, ""), (
        "PRD §2.8: first AuditLog entry must have prev_log_sha256 = null"
    )
    for i in range(1, len(logs)):
        prev_payload = logs[i - 1].get("payload_sha256")
        cur_prev = logs[i].get("prev_log_sha256")
        assert cur_prev == prev_payload, (
            f"AuditLog chain broken at position {i}: "
            f"prev_log_sha256={cur_prev!r}, expected {prev_payload!r}"
        )


# ---------------------------------------------------------------------------
# Domain invariant helpers
# ---------------------------------------------------------------------------
def assert_evidence_score_precision(score: float) -> None:
    """PRD §2.5: evidence_strength_score is stored to two decimal places,
    half-up."""
    quantized = round(float(score) * 100) / 100.0
    assert abs(float(score) - quantized) < 1e-9, (
        f"evidence_strength_score must be 2 decimals, got {score!r}"
    )


def assert_progress_precision(progress: float) -> None:
    """PRD §2.5: signing_progress_percent stored to two decimal places."""
    quantized = round(float(progress) * 100) / 100.0
    assert abs(float(progress) - quantized) < 1e-9, (
        f"signing_progress_percent must be 2 decimals, got {progress!r}"
    )


def find_audit_entries(logs: Iterable[Dict[str, Any]],
                       action: str) -> List[Dict[str, Any]]:
    return [log for log in logs if log.get("action") == action]


__all__ = [
    "is_lower_hex_64",
    "assert_template",
    "assert_template_version",
    "assert_contract",
    "assert_signing_step",
    "assert_signing_party",
    "assert_identity_verification",
    "assert_timestamp_token",
    "assert_evidence_package",
    "assert_reminder_rule",
    "assert_reminder_event",
    "assert_audit_log_entry",
    "assert_audit_log_chain",
    "assert_evidence_score_precision",
    "assert_progress_precision",
    "find_audit_entries",
]
