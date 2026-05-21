"""Upgrade waitlist helpers — recompute priority_score and held_points."""

from __future__ import annotations

from ..store import store
from . import calc


def recompute_priority(upgrade: dict, member_tier: str) -> None:
    upgrade["priority_score"] = calc.priority_score(
        member_tier, upgrade["points_offered"], upgrade["waitlist_join_seq"]
    )


def recompute_member_waitlist(member_id: str, member_tier: str, bump_fn) -> None:
    """Recompute priority_score for every WAITLISTED upgrade of *member_id*.
    Each updated row gets its own version/updated_at bump via bump_fn(resource).
    """
    for u in store.upgrade_requests.values():
        if u["member_id"] != member_id or u["status"] != "WAITLISTED":
            continue
        new_score = calc.priority_score(
            member_tier, u["points_offered"], u["waitlist_join_seq"]
        )
        if new_score != u["priority_score"]:
            u["priority_score"] = new_score
            bump_fn(u)


def update_held_points(upgrade: dict) -> None:
    if upgrade["status"] in ("WAITLISTED", "CONFIRMED"):
        upgrade["held_points"] = upgrade["points_offered"]
    else:
        upgrade["held_points"] = 0
