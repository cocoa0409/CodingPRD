"""Output-shaping helpers. Tournament reads expose computed fields."""
from __future__ import annotations

from typing import Any

from ..store import get_store


def serialize_tournament(t: dict[str, Any]) -> dict[str, Any]:
    out = dict(t)
    store = get_store()
    crowdfunded = sum(
        int(c["amount_cents"])
        for c in store.crowdfund_contributions.values()
        if c["tournament_id"] == t["id"] and c["status"] == "COLLECTED"
    )
    base = int(t.get("base_prize_pool_cents", 0))
    out["crowdfunded_prize_pool_cents"] = crowdfunded
    out["total_prize_pool_cents"] = base + crowdfunded
    return out


def serialize_team_registration(r: dict[str, Any]) -> dict[str, Any]:
    """Compute roster_locked on read."""
    from ..clock import CLOCK, parse_iso

    out = dict(r)
    store = get_store()
    t = store.tournaments.get(r["tournament_id"])
    locked = False
    if t is not None:
        # Tournament.status >= ROSTER_LOCKED or roster_lock_deadline has passed
        status_order = ["DRAFT", "REGISTRATION_OPEN", "ROSTER_LOCKED", "BRACKET_PUBLISHED",
                        "IN_PROGRESS", "COMPLETED", "PRIZES_DISTRIBUTED", "CANCELLED"]
        try:
            tstatus_idx = status_order.index(t["status"])
            roster_idx = status_order.index("ROSTER_LOCKED")
            if tstatus_idx >= roster_idx and t["status"] != "CANCELLED":
                locked = True
        except ValueError:
            pass
        if not locked and t.get("roster_lock_deadline"):
            try:
                deadline = parse_iso(t["roster_lock_deadline"])
                if CLOCK.now >= deadline:
                    locked = True
            except Exception:
                pass
    out["roster_locked"] = locked
    return out


def serialize_match(m: dict[str, Any]) -> dict[str, Any]:
    out = dict(m)
    # is_bye derived: exactly one of team_a_id / team_b_id is null
    a = out.get("team_a_id")
    b = out.get("team_b_id")
    out["is_bye"] = bool((a is None) ^ (b is None))
    return out


def serialize_contract(c: dict[str, Any]) -> dict[str, Any]:
    return dict(c)


def serialize_payout(p: dict[str, Any]) -> dict[str, Any]:
    return dict(p)


def serialize_referee(r: dict[str, Any]) -> dict[str, Any]:
    return dict(r)


def serialize_incident(i: dict[str, Any]) -> dict[str, Any]:
    return dict(i)


def serialize_transfer_offer(o: dict[str, Any]) -> dict[str, Any]:
    return dict(o)


def serialize_transfer_window(w: dict[str, Any]) -> dict[str, Any]:
    return dict(w)


def serialize_draft_event(d: dict[str, Any]) -> dict[str, Any]:
    return dict(d)


def serialize_identity_verification(v: dict[str, Any]) -> dict[str, Any]:
    return dict(v)


def serialize_audit_log(a: dict[str, Any]) -> dict[str, Any]:
    return dict(a)


def serialize_contribution(c: dict[str, Any]) -> dict[str, Any]:
    return dict(c)
