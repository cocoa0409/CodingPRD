"""Homeowner derived-field recompute (delinquency_score, standing, booking_privilege)."""

import db
from entities import bump
from services import calc
from services import property as property_svc


def recompute(home, now_iso, now_dt=None):
    """Recompute delinquency_score, standing, booking_privilege. Bumps version/updated_at
    only if any of them changed."""
    if now_dt is None:
        from clock import get_now
        now_dt = get_now()

    # Collect all assessments across every property owned by this homeowner
    # whose status ∈ {OPEN, PARTIALLY_PAID, OVERDUE, DELINQUENT}.
    owned_property_ids = {p["id"] for p in db.properties.values() if p["homeowner_id"] == home["id"]}
    relevant = [
        a for a in db.assessments.values()
        if a["property_id"] in owned_property_ids
        and a["status"] in ("OPEN", "PARTIALLY_PAID", "OVERDUE", "DELINQUENT")
    ]

    grace_policy = db.community_config.get("grace_policy", "STRICT")
    score = calc.delinquency_score(relevant, grace_policy, now_dt)
    standing = calc.standing_from_score(score)
    booking = calc.booking_privilege_from_standing(standing)

    changed = False
    if home.get("delinquency_score") != score:
        home["delinquency_score"] = score
        changed = True
    if home.get("standing") != standing:
        home["standing"] = standing
        changed = True
    if home.get("booking_privilege") != booking:
        home["booking_privilege"] = booking
        changed = True
    if changed:
        bump(home, now_iso)


def recompute_all(now_iso):
    """Full recompute for every homeowner (used by /_config/grace-policy)."""
    from clock import get_now
    now_dt = get_now()
    for h in db.homeowners.values():
        recompute(h, now_iso, now_dt=now_dt)


def recompute_owner_and_property(property_id, now_iso):
    """Convenience: recompute property derived fields, then the owning homeowner's."""
    from clock import get_now
    now_dt = get_now()
    prop = db.properties.get(property_id)
    if not prop:
        return
    property_svc.recompute(prop, now_iso, now_dt=now_dt)
    home = db.homeowners.get(prop["homeowner_id"])
    if home:
        recompute(home, now_iso, now_dt=now_dt)
