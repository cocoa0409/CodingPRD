"""Payload factories -- one per endpoint payload defined in the PRD.

Only `source: input` fields appear here. Fields the server mints (ids,
serial_numbers, timestamps, computed derivations) are intentionally
absent so factories never invite implementations to skip server-side
derivations.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional


# ===========================================================================
# Unique id / value generators
# ===========================================================================
def unique_id() -> str:
    """Short unique suffix used inside factory defaults."""
    return uuid.uuid4().hex[:8]


def _unique_letters(n: int = 8) -> str:
    """Return n uppercase ASCII letters drawn from a uuid hex source.

    Used by unique_department_code so the result conforms to PRD §3.1's
    'uppercase letters and underscores' constraint (digits are not
    allowed). The mapping converts each hex digit to a letter via
    `int + ord('A')` arithmetic so the suffix stays unique while remaining
    inside [A..P].
    """
    src = uuid.uuid4().hex
    return "".join(chr(ord("A") + int(c, 16)) for c in src[:n])


def unique_department_code(prefix: str = "DEPT") -> str:
    # PRD §3.1: code is uppercase letters/underscores, 3..32 chars.
    raw = f"{prefix}_{_unique_letters(8)}"
    return raw[:32]


def unique_matter_code(prefix: str = "MATTER") -> str:
    # PRD §3.1: 4..64 chars; alphanumeric + underscore is broadly accepted.
    raw = f"{prefix}_{unique_id()}"
    return raw[:64]


def unique_version_label(prefix: str = "V") -> str:
    # PRD §3.1: 1..32 chars, unique within parent matter.
    raw = f"{prefix}-{unique_id()}"
    return raw[:32]


def unique_material_template_code(prefix: str = "MTPL") -> str:
    # PRD §3.3: 4..64 chars, unique.
    raw = f"{prefix}_{unique_id()}"
    return raw[:64]


def unique_certificate_template_code(prefix: str = "CTPL") -> str:
    # PRD §3.3: 4..64 chars, unique.
    raw = f"{prefix}_{unique_id()}"
    return raw[:64]


def unique_idempotency_key(prefix: str = "evt") -> str:
    return f"{prefix}-{unique_id()}"


def unique_applicant_id(prefix: str = "applicant") -> str:
    return f"{prefix}-{unique_id()}"


def unique_admin_id(prefix: str = "admin") -> str:
    return f"{prefix}-{unique_id()}"


def unique_certificate_officer_id(prefix: str = "cert-officer") -> str:
    return f"{prefix}-{unique_id()}"


# ===========================================================================
# Department (PRD §3.1)
# ===========================================================================
def create_department_payload(
    code: Optional[str] = None,
    name: Optional[str] = None,
    parent_department_id: Optional[str] = None,
    include_parent: bool = False,
    **overrides: Any,
) -> Dict[str, Any]:
    """Payload for POST /departments.

    PRD §3.1: 'Each carries a stable code (uppercase letters and
    underscores, 3-32 characters, unique across the platform), a
    human-readable name, an optional parent_department_id ...'
    """
    payload: Dict[str, Any] = {
        "code": code or unique_department_code(),
        "name": name or f"Department {unique_id()}",
    }
    if include_parent or parent_department_id is not None:
        payload["parent_department_id"] = parent_department_id
    payload.update(overrides)
    return payload


# ===========================================================================
# Matter (PRD §3.1)
# ===========================================================================
def create_matter_payload(
    owning_department_id: str,
    code: Optional[str] = None,
    theme: str = "OTHER",
    **overrides: Any,
) -> Dict[str, Any]:
    """Payload for POST /matters.

    PRD §3.1: 'A CatalogManager opens a new matter by minting a Matter
    shell with a stable code (4-64 characters, unique across the
    catalog), a theme drawn from BIRTH, EDUCATION, BUSINESS, HOUSING,
    TRANSPORT, SOCIAL_SECURITY, or OTHER, and an owning_department_id
    that points at the department responsible for the matter.'
    """
    payload: Dict[str, Any] = {
        "code": code or unique_matter_code(),
        "theme": theme,
        "owning_department_id": owning_department_id,
    }
    payload.update(overrides)
    return payload


# ===========================================================================
# MatterVersion (PRD §3.1, §3.2)
# ===========================================================================
def make_routing(
    *,
    mode: str = "SERIAL",
    lead_department_id: Optional[str] = None,
    stages: Optional[List[Dict[str, Any]]] = None,
    aggregation_rule: Optional[Any] = "__OMIT__",
) -> Dict[str, Any]:
    """Build a review_routing object.

    PRD §3.2: 'mode is either SERIAL or PARALLEL ... aggregation_rule
    is required when mode is PARALLEL ... when mode is SERIAL,
    aggregation_rule must be null.' Default builds a single-stage SERIAL
    routing whose lead department is the one stage. When no
    aggregation_rule override is supplied, SERIAL gets null and PARALLEL
    must be supplied explicitly.
    """
    if stages is None:
        if lead_department_id is None:
            raise ValueError(
                "make_routing: must pass lead_department_id when stages is omitted"
            )
        stages = [{"department_id": lead_department_id, "sla_days": 5}]
    if lead_department_id is None:
        lead_department_id = stages[0]["department_id"]
    routing: Dict[str, Any] = {
        "mode": mode,
        "lead_department_id": lead_department_id,
        "stages": stages,
    }
    if aggregation_rule == "__OMIT__":
        routing["aggregation_rule"] = None if mode == "SERIAL" else "ALL_AGREE"
    else:
        routing["aggregation_rule"] = aggregation_rule
    return routing


def create_matter_version_payload(
    required_material_template_ids: List[str],
    certificate_template_id: str,
    review_routing: Dict[str, Any],
    *,
    version_label: Optional[str] = None,
    legal_basis: str = "Reg. 2025-1",
    conditions: str = "Eligibility: any individual.",
    statutory_time_limit_days: int = 15,
    committed_time_limit_days: int = 10,
    warning_threshold_pct: Optional[int] = None,
    fee_amount_cents: Optional[int] = None,
    channels: Optional[List[str]] = None,
    max_correction_rounds: Optional[int] = None,
    correction_window_days: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Payload for POST /matters/{matter_id}/versions.

    PRD §3.1 enumerates the version content. Optional fields with
    defaults are omitted unless the caller passes a value, so factories
    do not assert any particular default.
    """
    payload: Dict[str, Any] = {
        "version_label": version_label or unique_version_label(),
        "legal_basis": legal_basis,
        "conditions": conditions,
        "required_material_template_ids": list(required_material_template_ids),
        "statutory_time_limit_days": statutory_time_limit_days,
        "committed_time_limit_days": committed_time_limit_days,
        "channels": channels if channels is not None else ["ONLINE", "OFFLINE"],
        "review_routing": review_routing,
        "certificate_template_id": certificate_template_id,
    }
    if warning_threshold_pct is not None:
        payload["warning_threshold_pct"] = warning_threshold_pct
    if fee_amount_cents is not None:
        payload["fee_amount_cents"] = fee_amount_cents
    if max_correction_rounds is not None:
        payload["max_correction_rounds"] = max_correction_rounds
    if correction_window_days is not None:
        payload["correction_window_days"] = correction_window_days
    payload.update(overrides)
    return payload


# ===========================================================================
# MaterialTemplate (PRD §3.3)
# ===========================================================================
def create_material_template_payload(
    *,
    code: Optional[str] = None,
    title: Optional[str] = None,
    material_type: str = "ORIGINAL",
    form_url: Optional[str] = None,
    example_url: Optional[str] = None,
    e_form_schema: Optional[Dict[str, Any]] = None,
    include_form_url: bool = False,
    include_example_url: bool = False,
    include_e_form_schema: bool = False,
    **overrides: Any,
) -> Dict[str, Any]:
    """Payload for POST /material-templates.

    PRD §3.3: 'A MaterialTemplate carries a stable code (4-64 characters,
    unique), a display title, a material_type of ORIGINAL, COPY, or
    NOTARIZED, an optional form_url ... an optional example_url ... and
    an optional e_form_schema ...'
    """
    payload: Dict[str, Any] = {
        "code": code or unique_material_template_code(),
        "title": title or f"Material {unique_id()}",
        "material_type": material_type,
    }
    if include_form_url or form_url is not None:
        payload["form_url"] = form_url
    if include_example_url or example_url is not None:
        payload["example_url"] = example_url
    if include_e_form_schema or e_form_schema is not None:
        payload["e_form_schema"] = e_form_schema
    payload.update(overrides)
    return payload


# ===========================================================================
# CertificateTemplate (PRD §3.3, §3.10)
# ===========================================================================
def create_certificate_template_payload(
    *,
    code: Optional[str] = None,
    body_template: Optional[str] = None,
    required_variables: Optional[List[str]] = None,
    validity_days: Optional[int] = None,
    official_seal_id: str = "SEAL-DEFAULT",
    **overrides: Any,
) -> Dict[str, Any]:
    """Payload for POST /certificate-templates.

    PRD §3.3: 'A CertificateTemplate carries a stable code, a
    Mustache-style body_template whose placeholders are listed in
    required_variables (every entry of required_variables must appear in
    body_template), a validity_days integer ... and an official_seal_id
    identifying the seal asset embedded on issuance.'
    """
    if required_variables is None:
        required_variables = ["applicant_name"]
    if body_template is None:
        # Render every required variable so the schema-level "every
        # required_variables entry must appear in body_template" rule is
        # satisfied by default.
        placeholders = " ".join("{{" + v + "}}" for v in required_variables)
        body_template = f"Approved certificate for {placeholders}."
    payload: Dict[str, Any] = {
        "code": code or unique_certificate_template_code(),
        "body_template": body_template,
        "required_variables": required_variables,
        "official_seal_id": official_seal_id,
    }
    if validity_days is not None:
        payload["validity_days"] = validity_days
    payload.update(overrides)
    return payload


# ===========================================================================
# Application (PRD §3.4)
# ===========================================================================
def submitted_material_entry(
    material_template_id: str,
    *,
    attachment_ref: Optional[str] = None,
    e_form_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build one entry of an Application's submitted_materials array.

    PRD §3.4: 'Each submitted-material entry is a small object with a
    material_template_id, an attachment_ref, and an optional
    e_form_payload.'
    """
    entry: Dict[str, Any] = {
        "material_template_id": material_template_id,
        "attachment_ref": attachment_ref or f"attachment://{unique_id()}",
    }
    if e_form_payload is not None:
        entry["e_form_payload"] = e_form_payload
    return entry


def submit_application_payload(
    matter_version_id: str,
    submitted_materials: List[Dict[str, Any]],
    *,
    channel: str = "ONLINE",
    **overrides: Any,
) -> Dict[str, Any]:
    """Payload for POST /applications.

    PRD §3.4: 'An applicant initiates an application by referencing a
    matter_version_id (which is pinned at submission and will not change
    for the life of the application), choosing a channel of ONLINE or
    OFFLINE, and providing submitted_materials.'
    """
    payload: Dict[str, Any] = {
        "matter_version_id": matter_version_id,
        "channel": channel,
        "submitted_materials": submitted_materials,
    }
    payload.update(overrides)
    return payload


# ===========================================================================
# CorrectionNotice (PRD §3.6)
# ===========================================================================
def deficiency_entry(material_template_id: str,
                     reason: str = "missing") -> Dict[str, Any]:
    """One {material_template_id, reason} entry inside deficiencies."""
    return {"material_template_id": material_template_id, "reason": reason}


def issue_correction_notice_payload(
    deficiencies: List[Dict[str, Any]],
    issued_by_review_task_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """Payload for POST /applications/{id}/correction-notices.

    PRD §3.6: 'The issuance request takes a non-empty deficiencies array
    -- each entry naming a material_template_id and a reason -- and an
    issued_by_review_task_id identifying the reviewer's own task.'
    """
    payload: Dict[str, Any] = {
        "deficiencies": deficiencies,
        "issued_by_review_task_id": issued_by_review_task_id,
    }
    payload.update(overrides)
    return payload


def resubmit_correction_payload(
    submitted_materials: List[Dict[str, Any]],
    **overrides: Any,
) -> Dict[str, Any]:
    """Payload for POST /applications/{id}/correction-notices/{cid}/resubmit.

    PRD §3.6: 'The resubmit request addresses the notice through the URL
    slot cid and takes an updated submitted_materials array.'
    """
    payload: Dict[str, Any] = {"submitted_materials": submitted_materials}
    payload.update(overrides)
    return payload


# ===========================================================================
# ReviewTask decision (PRD §3.6)
# ===========================================================================
def decide_review_task_payload(
    decision: str,
    opinion_text: Optional[str] = None,
    include_opinion: bool = False,
    **overrides: Any,
) -> Dict[str, Any]:
    """Payload for POST /review-tasks/{id}/decide.

    PRD §3.6: 'A reviewer ... decides by submitting a decision of AGREED
    or DISAGREED and an optional opinion_text.'
    """
    payload: Dict[str, Any] = {"decision": decision}
    if include_opinion or opinion_text is not None:
        payload["opinion_text"] = opinion_text or "ok"
    payload.update(overrides)
    return payload


# ===========================================================================
# Escalation (PRD §3.9)
# ===========================================================================
def resolve_escalation_payload(decision: str,
                               **overrides: Any) -> Dict[str, Any]:
    """Payload for POST /applications/{id}/escalation-resolve.

    PRD §3.9: 'A PlatformAdmin resolves the escalation by submitting a
    decision of either AGREED or DISAGREED.'
    """
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


# ===========================================================================
# Certificate (PRD §3.10)
# ===========================================================================
def revoke_certificate_payload(reason: Optional[str] = None) -> Dict[str, Any]:
    """Payload for POST /certificates/{id}/revoke.

    PRD §3.10: 'A PlatformAdmin may also revoke an ACTIVE certificate
    explicitly by submitting an optional reason.'
    """
    payload: Dict[str, Any] = {}
    if reason is not None:
        payload["reason"] = reason
    return payload


# ===========================================================================
# ExternalEvent (PRD §2.12, §3.5)
# ===========================================================================
def emit_event_payload(
    event_type: str,
    subject_application_id: str,
    *,
    idempotency_key: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Payload for POST /_events/emit.

    PRD §2.12: 'Each event carries an event_type, an idempotency_key
    that the source platform guarantees unique within event_type, a
    subject_application_id, and a free-form payload.'
    """
    return {
        "event_type": event_type,
        "idempotency_key": idempotency_key or unique_idempotency_key(),
        "subject_application_id": subject_application_id,
        "payload": payload if payload is not None else {},
    }


# ===========================================================================
# Test-driving (PRD §2.14)
# ===========================================================================
def clock_advance_payload(seconds: int) -> Dict[str, Any]:
    """Payload for POST /_clock/advance."""
    return {"seconds": seconds}


__all__ = [
    "unique_id",
    "unique_department_code",
    "unique_matter_code",
    "unique_version_label",
    "unique_material_template_code",
    "unique_certificate_template_code",
    "unique_idempotency_key",
    "unique_applicant_id",
    "unique_admin_id",
    "unique_certificate_officer_id",
    "create_department_payload",
    "create_matter_payload",
    "make_routing",
    "create_matter_version_payload",
    "create_material_template_payload",
    "create_certificate_template_payload",
    "submitted_material_entry",
    "submit_application_payload",
    "deficiency_entry",
    "issue_correction_notice_payload",
    "resubmit_correction_payload",
    "decide_review_task_payload",
    "resolve_escalation_payload",
    "revoke_certificate_payload",
    "emit_event_payload",
    "clock_advance_payload",
]
