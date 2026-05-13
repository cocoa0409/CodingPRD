"""Payload factories — one per input-bearing endpoint.

Each factory emits ONLY the fields PRD declares as input (source: input).
Tests override via kwargs. Field names mirror PRD prose exactly — no
abbreviation, no guessing.
"""
from __future__ import annotations
import uuid
from typing import Any, Dict, List, Optional


_OMIT = "__OMIT__"


# ---------------------------------------------------------------------------
# Unique-suffix helpers
# ---------------------------------------------------------------------------
def unique_suffix(n: int = 8) -> str:
    return uuid.uuid4().hex[:n]


def unique_department_code(prefix: str = "dept") -> str:
    """PRD §3.1: code 'matching the pattern of a leading lowercase letter
    followed by lowercase letters, digits, and hyphens, total length 2 to
    40 characters'."""
    return f"{prefix}-{unique_suffix(6).lower()}"


def unique_category_code(prefix: str = "C") -> str:
    """PRD §3.1: category_code 'uppercase identifiers matching a leading
    uppercase letter followed by uppercase letters, digits, and
    underscores, total length 2 to 30 characters'."""
    suffix = unique_suffix(6).upper().replace("-", "")
    # Ensure all chars are A-Z or 0-9.
    suffix = "".join(c if c.isalnum() else "X" for c in suffix)
    return f"{prefix}_{suffix}"


def unique_sub_category_code(prefix: str = "S") -> str:
    return unique_category_code(prefix)


def unique_jurisdiction_code() -> str:
    """PRD §3.1: 'each matching the pattern of a literal J followed by
    exactly four digits'."""
    # 4-digit numeric suffix.
    n = uuid.uuid4().int % 10000
    return f"J{n:04d}"


def unique_phone() -> str:
    """PRD §3.2: caller_phone 'pattern of digits, the plus sign, and
    hyphens, of total length 6 to 20'."""
    return f"+1-555-{uuid.uuid4().int % 10000:04d}"


def unique_full_name(prefix: str = "Handler") -> str:
    return f"{prefix} {unique_suffix(5)}"


def unique_department_name(prefix: str = "Department") -> str:
    return f"{prefix} {unique_suffix(5)}"


# ---------------------------------------------------------------------------
# Department  POST /departments  (PRD §3.1)
# ---------------------------------------------------------------------------
def create_department_payload(
    *,
    name: Optional[str] = None,
    code: Optional[str] = None,
    jurisdiction_codes: Optional[List[str]] = None,
    category_codes: Optional[List[str]] = None,
    status: Any = _OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: 'A Department is created with a name, a stable
    kebab-case code... a list of jurisdiction_codes... and a list of
    category_codes it is responsible for.'"""
    payload: Dict[str, Any] = {
        "name": name or unique_department_name(),
        "code": code or unique_department_code(),
        "jurisdiction_codes": (
            list(jurisdiction_codes) if jurisdiction_codes is not None else []
        ),
        "category_codes": (
            list(category_codes) if category_codes is not None else []
        ),
    }
    if status != _OMIT:
        payload["status"] = status
    payload.update(overrides)
    return payload


def update_department_payload(
    *,
    name: Any = _OMIT,
    jurisdiction_codes: Any = _OMIT,
    category_codes: Any = _OMIT,
    status: Any = _OMIT,
    version: Any = _OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §4: 'PATCH /departments/{id} — Update department metadata or
    status.'"""
    payload: Dict[str, Any] = {}
    for k, v in (("name", name), ("jurisdiction_codes", jurisdiction_codes),
                 ("category_codes", category_codes), ("status", status),
                 ("version", version)):
        if v != _OMIT:
            payload[k] = v
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Handler  POST /handlers  (PRD §3.1)
# ---------------------------------------------------------------------------
def create_handler_payload(
    *,
    full_name: Optional[str] = None,
    department_id: str,
    status: Any = _OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: 'A Handler is bound to a department at creation time
    through the department_id field... The handler's full_name is
    non-empty.'"""
    payload: Dict[str, Any] = {
        "full_name": full_name or unique_full_name(),
        "department_id": department_id,
    }
    if status != _OMIT:
        payload["status"] = status
    payload.update(overrides)
    return payload


def update_handler_payload(
    *,
    status: Any = _OMIT,
    version: Any = _OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §4: 'PATCH /handlers/{id} — Update handler status.'"""
    payload: Dict[str, Any] = {}
    if status != _OMIT:
        payload["status"] = status
    if version != _OMIT:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# CategoryRule  POST /category-rules  (PRD §3.1)
# ---------------------------------------------------------------------------
def create_category_rule_payload(
    *,
    category_code: Optional[str] = None,
    sub_category_code: Optional[str] = None,
    lead_department_code: str,
    supporting_department_codes: Optional[List[str]] = None,
    statutory_time_limit_hours: int = 72,
    committed_time_limit_hours: int = 48,
    difficulty_base: Any = _OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: 'A CategoryRule ties a (category_code, sub_category_code)
    pair... to a lead_department_code and a list of
    supporting_department_codes.'"""
    payload: Dict[str, Any] = {
        "category_code": category_code or unique_category_code(),
        "sub_category_code": sub_category_code or unique_sub_category_code(),
        "lead_department_code": lead_department_code,
        "supporting_department_codes": (
            list(supporting_department_codes)
            if supporting_department_codes is not None else []
        ),
        "statutory_time_limit_hours": statutory_time_limit_hours,
        "committed_time_limit_hours": committed_time_limit_hours,
    }
    if difficulty_base != _OMIT:
        payload["difficulty_base"] = difficulty_base
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# WorkOrder  POST /work-orders, PATCH /work-orders/{id}  (PRD §3.2)
# ---------------------------------------------------------------------------
def create_work_order_payload(
    *,
    caller_name: Any = _OMIT,
    caller_phone: Any = _OMIT,
    anonymous: bool = False,
    jurisdiction_code: str,
    category_code: str,
    sub_category_code: str,
    content_text: Optional[str] = None,
    audio_url: Any = _OMIT,
    urgency: Any = _OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.2: 'A hotline operator registers an incoming call by
    submitting caller_name, caller_phone, anonymous, jurisdiction_code,
    category_code, sub_category_code, content_text, optionally audio_url,
    and optionally urgency.'

    Defaults: anonymous=False with a generated caller_phone so payloads
    satisfy the PRD §3.2 anonymous PII rule out of the box. Anonymous
    callers pass anonymous=True and omit caller_phone/caller_name.
    """
    payload: Dict[str, Any] = {
        "anonymous": anonymous,
        "jurisdiction_code": jurisdiction_code,
        "category_code": category_code,
        "sub_category_code": sub_category_code,
        "content_text": content_text or f"call content {unique_suffix(6)}",
    }
    if anonymous:
        # Anonymous calls must omit caller_name and caller_phone unless
        # explicitly overridden (used by negative tests).
        if caller_name != _OMIT:
            payload["caller_name"] = caller_name
        if caller_phone != _OMIT:
            payload["caller_phone"] = caller_phone
    else:
        # Non-anonymous: caller_phone required; supply a default.
        payload["caller_phone"] = (
            caller_phone if caller_phone != _OMIT else unique_phone()
        )
        if caller_name != _OMIT:
            payload["caller_name"] = caller_name
    if audio_url != _OMIT:
        payload["audio_url"] = audio_url
    if urgency != _OMIT:
        payload["urgency"] = urgency
    payload.update(overrides)
    return payload


def update_work_order_payload(
    *,
    content_text: Any = _OMIT,
    category_code: Any = _OMIT,
    sub_category_code: Any = _OMIT,
    urgency: Any = _OMIT,
    audio_url: Any = _OMIT,
    version: Any = _OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.2: 'A registered case still in REGISTERED may be amended
    by the operator with PATCH against content_text, category_code,
    sub_category_code, urgency, or audio_url.'"""
    payload: Dict[str, Any] = {}
    for k, v in (("content_text", content_text),
                 ("category_code", category_code),
                 ("sub_category_code", sub_category_code),
                 ("urgency", urgency), ("audio_url", audio_url),
                 ("version", version)):
        if v != _OMIT:
            payload[k] = v
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Classify / reject  (PRD §3.3)
# ---------------------------------------------------------------------------
def classify_work_order_payload(*, mode: str = "RULE_BASED",
                                **overrides: Any) -> Dict[str, Any]:
    """PRD §3.3: 'The request body carries a mode value indicating
    whether the operator believes the (category, sub-category) pair has
    an exact match in CategoryRule (in which case classification_mode is
    set to RULE_BASED) or whether AI assistance is needed (in which case
    classification_mode is set to AI_ASSISTED).'"""
    payload: Dict[str, Any] = {"mode": mode}
    payload.update(overrides)
    return payload


def reject_work_order_payload(*, rejection_reason: str = "no department",
                              **overrides: Any) -> Dict[str, Any]:
    """PRD §3.3: 'the dispatcher may instead take the explicit
    CLASSIFIED → REJECTED branch by submitting a rejection_reason
    (between 1 and 500 characters).'"""
    payload: Dict[str, Any] = {"rejection_reason": rejection_reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Pause / resolve  (PRD §3.6, §3.7)
# ---------------------------------------------------------------------------
def pause_work_order_payload(*, reason: str = "need clarification",
                             **overrides: Any) -> Dict[str, Any]:
    """PRD §3.6: 'The pause endpoint expects a reason (between 1 and 500
    characters)'."""
    payload: Dict[str, Any] = {"reason": reason}
    payload.update(overrides)
    return payload


def resolve_work_order_payload(*, resolution_summary: str = "case resolved",
                               **overrides: Any) -> Dict[str, Any]:
    """PRD §3.7: 'The request body carries a resolution_summary of length
    between 1 and 4000 characters.'"""
    payload: Dict[str, Any] = {"resolution_summary": resolution_summary}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# DepartmentAssignment actions (PRD §3.5, §3.7)
# ---------------------------------------------------------------------------
def reject_assignment_payload(*, rejection_reason: str = "wrong department",
                              **overrides: Any) -> Dict[str, Any]:
    """PRD §3.5: 'A handler may also reject an assignment back to the
    dispatcher when the assignment is still DISPATCHED and a
    rejection_reason (between 1 and 500 characters) is provided.'"""
    payload: Dict[str, Any] = {"rejection_reason": rejection_reason}
    payload.update(overrides)
    return payload


def reassign_assignment_payload(*, target_department_id: str,
                                **overrides: Any) -> Dict[str, Any]:
    """PRD §3.5: 'The request supplies target_department_id.'"""
    payload: Dict[str, Any] = {"target_department_id": target_department_id}
    payload.update(overrides)
    return payload


def submit_opinion_payload(*, opinion_text: str = "ok",
                           opinion_decision: str = "AGREE",
                           **overrides: Any) -> Dict[str, Any]:
    """PRD §3.7: 'providing an opinion_text (between 1 and 2000 characters)
    and an opinion_decision of AGREE, DISAGREE, or ABSTAIN.'"""
    payload: Dict[str, Any] = {
        "opinion_text": opinion_text,
        "opinion_decision": opinion_decision,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Survey factories (PRD §3.9)
# ---------------------------------------------------------------------------
def create_survey_payload(*, channel: str = "CALL",
                          **overrides: Any) -> Dict[str, Any]:
    """PRD §3.9: 'The manual dispatch endpoint accepts a channel of
    CALL, SMS, or IM.'"""
    payload: Dict[str, Any] = {"channel": channel}
    payload.update(overrides)
    return payload


def respond_survey_payload(*, score: int = 5,
                           comment: Any = _OMIT,
                           **overrides: Any) -> Dict[str, Any]:
    """PRD §3.9: 'A SurveyAgent records the caller's response by
    supplying a score (an integer between 1 and 5 inclusive) and an
    optional comment.'"""
    payload: Dict[str, Any] = {"score": score}
    if comment != _OMIT:
        payload["comment"] = comment
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Test-harness payloads (PRD §2.10)
# ---------------------------------------------------------------------------
def clock_advance_payload(*, seconds: int,
                          **overrides: Any) -> Dict[str, Any]:
    """PRD §2.10: 'A clock-advance capability accepts a seconds body
    field and walks the server's logical clock forward by that many
    seconds.'"""
    payload: Dict[str, Any] = {"seconds": seconds}
    payload.update(overrides)
    return payload


__all__ = [
    "unique_suffix", "unique_department_code", "unique_category_code",
    "unique_sub_category_code", "unique_jurisdiction_code",
    "unique_phone", "unique_full_name", "unique_department_name",
    "create_department_payload", "update_department_payload",
    "create_handler_payload", "update_handler_payload",
    "create_category_rule_payload",
    "create_work_order_payload", "update_work_order_payload",
    "classify_work_order_payload", "reject_work_order_payload",
    "pause_work_order_payload", "resolve_work_order_payload",
    "reject_assignment_payload", "reassign_assignment_payload",
    "submit_opinion_payload",
    "create_survey_payload", "respond_survey_payload",
    "clock_advance_payload",
]
