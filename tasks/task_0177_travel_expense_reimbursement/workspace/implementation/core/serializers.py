"""Serialize internal entity dicts into API-facing JSON shapes."""
from __future__ import annotations

from typing import Any, Dict


def _copy(d: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in d.items()}


def serialize_employee(e: Dict[str, Any]) -> Dict[str, Any]:
    return _copy(e)


def serialize_per_diem_rate(r: Dict[str, Any]) -> Dict[str, Any]:
    return _copy(r)


def serialize_trip(t: Dict[str, Any]) -> Dict[str, Any]:
    return _copy(t)


def serialize_virtual_card(c: Dict[str, Any]) -> Dict[str, Any]:
    return _copy(c)


def serialize_expense_report(r: Dict[str, Any]) -> Dict[str, Any]:
    return _copy(r)


def serialize_expense_line(line: Dict[str, Any]) -> Dict[str, Any]:
    return _copy(line)


def serialize_receipt(r: Dict[str, Any]) -> Dict[str, Any]:
    return _copy(r)


def serialize_oop_approval(a: Dict[str, Any]) -> Dict[str, Any]:
    return _copy(a)
