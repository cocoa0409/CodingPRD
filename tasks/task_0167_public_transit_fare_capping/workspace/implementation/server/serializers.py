"""Output shapers — produce the wire representation per entity."""
from __future__ import annotations

from typing import Any


def _strip_internal(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if not k.startswith("_")}


def rider_view(r: dict[str, Any]) -> dict[str, Any]:
    return _strip_internal(r)


def employer_view(e: dict[str, Any]) -> dict[str, Any]:
    return _strip_internal(e)


def card_view(c: dict[str, Any]) -> dict[str, Any]:
    return _strip_internal(c)


def certificate_view(c: dict[str, Any]) -> dict[str, Any]:
    return _strip_internal(c)


def low_income_view(li: dict[str, Any]) -> dict[str, Any]:
    return _strip_internal(li)


def mobile_token_view(t: dict[str, Any]) -> dict[str, Any]:
    return _strip_internal(t)


def trip_view(t: dict[str, Any]) -> dict[str, Any]:
    return _strip_internal(t)


def cap_period_view(p: dict[str, Any]) -> dict[str, Any]:
    return _strip_internal(p)


def fsa_account_view(a: dict[str, Any]) -> dict[str, Any]:
    return _strip_internal(a)


def fsa_contribution_view(c: dict[str, Any]) -> dict[str, Any]:
    return _strip_internal(c)


def dispute_view(d: dict[str, Any]) -> dict[str, Any]:
    return _strip_internal(d)
