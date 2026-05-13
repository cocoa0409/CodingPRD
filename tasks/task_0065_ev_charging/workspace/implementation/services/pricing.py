"""Pricing-version and promo selection helpers."""

from __future__ import annotations

import db
from clock import parse_iso


def find_active_pricing(operator_id: str, instant_iso: str) -> dict | None:
    """Return the PricingVersion of operator_id whose half-open interval
    [effective_from, effective_to) covers `instant_iso`, or None."""
    instant = parse_iso(instant_iso)
    for pv in db.pricing_versions.values():
        if pv["operator_id"] != operator_id:
            continue
        try:
            ef = parse_iso(pv["effective_from"])
            et = parse_iso(pv["effective_to"])
        except Exception:
            continue
        if ef <= instant < et:
            return pv
    return None


def find_active_promo(operator_id: str, tier: str, instant_iso: str) -> dict | None:
    instant = parse_iso(instant_iso)
    candidates = []
    for promo in db.promo_activities.values():
        if promo["operator_id"] != operator_id:
            continue
        if tier not in promo.get("applies_to_tiers", []):
            continue
        try:
            starts = parse_iso(promo["starts_at"])
            ends = parse_iso(promo["ends_at"])
        except Exception:
            continue
        if starts <= instant < ends:
            candidates.append(promo)
    if not candidates:
        return None
    # Prefer most-recently created (largest _seq)
    candidates.sort(key=lambda p: p.get("_seq", 0), reverse=True)
    return candidates[0]
