"""Serializers that flatten internal entity dicts into API payloads.

We keep stored entities as plain dicts already in API shape; these serializers
exist mostly to provide a single place to add formatting tweaks (e.g. removing
internal fields).
"""
from __future__ import annotations

from typing import Any, Dict

# Internal fields we do not surface in API payloads.
_INTERNAL_FIELDS = set()


def _strip(d: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in d.items() if k not in _INTERNAL_FIELDS}


def plan_view(plan: dict) -> dict:
    return _strip(plan)


def offering_period_view(op: dict) -> dict:
    return _strip(op)


def enrollment_view(enr: dict) -> dict:
    return _strip(enr)


def contribution_view(c: dict) -> dict:
    return _strip(c)


def purchase_view(p: dict) -> dict:
    return _strip(p)


def form_3922_view(f: dict) -> dict:
    return _strip(f)


def disposition_view(d: dict) -> dict:
    return _strip(d)


def clock_view(clock: dict) -> dict:
    return dict(clock)
