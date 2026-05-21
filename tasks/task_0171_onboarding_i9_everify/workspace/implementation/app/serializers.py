"""Resource-to-view serializers — strip internal keys and present canonical shape."""
from __future__ import annotations

from typing import Any, Dict


_INTERNAL_PREFIX = "_"


def _strip_internal(row: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in row.items() if not k.startswith(_INTERNAL_PREFIX)}


def view_employee(row: Dict[str, Any], onboarding_status: str) -> Dict[str, Any]:
    out = _strip_internal(row)
    out["onboarding_status"] = onboarding_status
    return out


def view_i9_document(row: Dict[str, Any]) -> Dict[str, Any]:
    return _strip_internal(row)


def view_i9_form(row: Dict[str, Any]) -> Dict[str, Any]:
    return _strip_internal(row)


def view_everify_case(row: Dict[str, Any]) -> Dict[str, Any]:
    return _strip_internal(row)


def view_reverification_event(row: Dict[str, Any]) -> Dict[str, Any]:
    return _strip_internal(row)


def view_audit_event(row: Dict[str, Any]) -> Dict[str, Any]:
    return _strip_internal(row)
