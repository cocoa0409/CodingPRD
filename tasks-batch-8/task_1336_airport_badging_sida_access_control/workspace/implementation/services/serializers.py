"""Serializers: strip internal fields; inject computed fields."""

from __future__ import annotations

import db
from services import logic


def serialize(rec: dict) -> dict:
    return db.public(rec)


def serialize_list(items: list) -> list:
    return [serialize(it) for it in items]


def serialize_sponsor(sponsor: dict) -> dict:
    out = db.public(sponsor)
    out["active_badge_count"] = logic.sponsor_active_badge_count(sponsor["id"])
    return out


def serialize_audit_cycle(cycle: dict) -> dict:
    out = db.public(cycle)
    if cycle["status"] == "OPEN":
        due_scoped, due_accounted, rate = logic.audit_provisional(cycle, db.clock_now())
        out["due_scoped_count"] = due_scoped
        out["due_accounted_count"] = due_accounted
        out["recovery_rate_provisional_pct"] = rate
    return out
