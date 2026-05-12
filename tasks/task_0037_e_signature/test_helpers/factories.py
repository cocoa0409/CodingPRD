"""Payload factories -- one per entity, input fields only.

Field names match PRD §3 verbatim. Each factory accepts **overrides so
individual tests can pin specific values for boundary or precondition
behavior.
"""
from __future__ import annotations
import hashlib
import uuid
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Unique-id helpers
# ---------------------------------------------------------------------------
def unique_id(prefix: str = "u") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def unique_user_id(prefix: str = "user") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def unique_org_id(prefix: str = "org") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def unique_template_name(prefix: str = "Template") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def unique_token_value(prefix: str = "tsa-token") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:16]}"


def unique_blob_sha256() -> str:
    """Return a 64-char lowercase hex string (PRD §3.1)."""
    return hashlib.sha256(uuid.uuid4().bytes).hexdigest()


def unique_idempotency_key(rule_id: str, slot: int) -> str:
    """PRD §3.8: 'idempotency_key of the form {reminder_rule_id}:{slot}'."""
    return f"{rule_id}:{slot}"


# ---------------------------------------------------------------------------
# Template (PRD §3.1)
# ---------------------------------------------------------------------------
def create_template_payload(
    *,
    name: Optional[str] = None,
    category: str = "OTHER",
    owner_org_id: Optional[str] = None,
    permission_scope: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": name or unique_template_name(),
        "category": category,
        "owner_org_id": owner_org_id or unique_org_id(),
    }
    if permission_scope is not None:
        payload["permission_scope"] = permission_scope
    payload.update(overrides)
    return payload


def patch_template_payload(*, version: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"version": version}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# TemplateVersion (PRD §3.1)
# ---------------------------------------------------------------------------
def variable_field(name: str, type_: str = "string",
                   required: bool = True) -> Dict[str, Any]:
    return {"name": name, "type": type_, "required": required}


def signature_position(role_key: str, page: int = 1, x: float = 0.1,
                       y: float = 0.1, w: float = 0.2, h: float = 0.05,
                       kind: str = "NORMAL") -> Dict[str, Any]:
    """PRD §3.1: signature_positions are rectangles
    {role_key, page, x, y, w, h, kind} where kind is NORMAL or SEAM."""
    return {"role_key": role_key, "page": page,
            "x": x, "y": y, "w": w, "h": h, "kind": kind}


def create_template_version_payload(
    *,
    document_blob_sha256: Optional[str] = None,
    page_count: int = 1,
    variable_fields: Optional[List[Dict[str, Any]]] = None,
    signature_positions: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "document_blob_sha256": document_blob_sha256 or unique_blob_sha256(),
        "page_count": page_count,
        "variable_fields": variable_fields if variable_fields is not None
        else [variable_field("subject")],
        "signature_positions": (
            signature_positions if signature_positions is not None
            else [signature_position("PARTY_A", page=1)]
        ),
    }
    payload.update(overrides)
    return payload


def patch_template_version_payload(*, version: int,
                                   **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"version": version}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Contract (PRD §3.2)
# ---------------------------------------------------------------------------
def create_contract_payload(
    *,
    template_version_id: str,
    title: Optional[str] = None,
    variable_values: Optional[Dict[str, Any]] = None,
    expires_at: str,
    reinitiated_from_contract_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "template_version_id": template_version_id,
        "title": title or f"Contract-{uuid.uuid4().hex[:6]}",
        "variable_values": (
            variable_values if variable_values is not None
            else {"subject": "Test"}
        ),
        "expires_at": expires_at,
    }
    if reinitiated_from_contract_id is not None:
        payload["reinitiated_from_contract_id"] = reinitiated_from_contract_id
    payload.update(overrides)
    return payload


def patch_contract_payload(*, version: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"version": version}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# SigningStep (PRD §3.2)
# ---------------------------------------------------------------------------
def create_signing_step_payload(
    *,
    step_index: int,
    mode: str = "PARALLEL_COUNTERSIGN",
    branch_condition: Optional[Dict[str, Any]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "step_index": step_index,
        "mode": mode,
    }
    if branch_condition is not None:
        payload["branch_condition"] = branch_condition
    payload.update(overrides)
    return payload


def branch_condition(*, variable: str, operator: str, value: Any,
                     on_false_skip: bool = True) -> Dict[str, Any]:
    """PRD §3.2: branch_condition is of the form
    {variable, operator, value, on_false_skip}."""
    return {
        "variable": variable,
        "operator": operator,
        "value": value,
        "on_false_skip": on_false_skip,
    }


# ---------------------------------------------------------------------------
# SigningParty (PRD §3.2)
# ---------------------------------------------------------------------------
def create_signing_party_payload(
    *,
    role_key: str = "PARTY_A",
    signer_type: str = "INDIVIDUAL",
    signer_user_id: str,
    signer_org_id: Optional[str] = None,
    delegation_authorization_id: Optional[str] = None,
    required_auth_factors: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "role_key": role_key,
        "signer_type": signer_type,
        "signer_user_id": signer_user_id,
        "required_auth_factors": (
            required_auth_factors if required_auth_factors is not None
            else ["SMS"]
        ),
    }
    if signer_org_id is not None:
        payload["signer_org_id"] = signer_org_id
    if delegation_authorization_id is not None:
        payload["delegation_authorization_id"] = delegation_authorization_id
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# IdentityVerification (PRD §3.5)
# ---------------------------------------------------------------------------
def factor_attempt(factor: str, outcome: str = "PASS") -> Dict[str, Any]:
    """PRD §3.5: factors_attempted is an array of {factor, outcome} where
    outcome is PASS or FAIL."""
    return {"factor": factor, "outcome": outcome}


def create_identity_verification_payload(
    *,
    subject_user_id: str,
    contract_id: Optional[str] = None,
    factors_attempted: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "subject_user_id": subject_user_id,
        "factors_attempted": (
            factors_attempted if factors_attempted is not None
            else [factor_attempt("SMS", "PASS")]
        ),
    }
    if contract_id is not None:
        payload["contract_id"] = contract_id
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Sign-act payload (PRD §3.5)
# ---------------------------------------------------------------------------
def sign_party_payload(
    *,
    tsa_anchor_at: str,
    tsa_provider: str = "tsa-default",
    tsa_token_value: Optional[str] = None,
    identity_verification_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "tsa_anchor_at": tsa_anchor_at,
        "tsa_provider": tsa_provider,
        "tsa_token_value": tsa_token_value or unique_token_value(),
        "identity_verification_id": identity_verification_id,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# ReminderRule (PRD §3.8)
# ---------------------------------------------------------------------------
def create_reminder_rule_payload(
    *,
    interval_hours: int = 24,
    channels: Optional[List[str]] = None,
    escalation_after_misses: int = 2,
    enabled: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "interval_hours": interval_hours,
        "channels": channels if channels is not None else ["SMS"],
        "escalation_after_misses": escalation_after_misses,
    }
    if enabled is not None:
        payload["enabled"] = enabled
    payload.update(overrides)
    return payload


def patch_reminder_rule_payload(*, version: int,
                                **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"version": version}
    payload.update(overrides)
    return payload


def fire_reminder_payload(*, idempotency_key: str,
                          **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"idempotency_key": idempotency_key}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# EvidencePackage seal (PRD §3.11)
# ---------------------------------------------------------------------------
def seal_evidence_payload(
    *,
    notary_provider: Optional[str] = None,
    notary_reference: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if notary_provider is not None:
        payload["notary_provider"] = notary_provider
    if notary_reference is not None:
        payload["notary_reference"] = notary_reference
    payload.update(overrides)
    return payload


__all__ = [
    "unique_id",
    "unique_user_id",
    "unique_org_id",
    "unique_template_name",
    "unique_token_value",
    "unique_blob_sha256",
    "unique_idempotency_key",
    "create_template_payload",
    "patch_template_payload",
    "variable_field",
    "signature_position",
    "create_template_version_payload",
    "patch_template_version_payload",
    "create_contract_payload",
    "patch_contract_payload",
    "create_signing_step_payload",
    "branch_condition",
    "create_signing_party_payload",
    "factor_attempt",
    "create_identity_verification_payload",
    "sign_party_payload",
    "create_reminder_rule_payload",
    "patch_reminder_rule_payload",
    "fire_reminder_payload",
    "seal_evidence_payload",
]
