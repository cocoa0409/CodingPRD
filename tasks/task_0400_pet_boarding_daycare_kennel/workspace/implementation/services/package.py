"""Package credit recomputation (PRD §3.7).

credits_remaining == credits_total minus the number of active (non-reversed)
redemptions, floored at 0.
"""
from db import db


def recompute_credits_remaining(pkg):
    active = 0
    for rec in db.package_redemptions.values():
        if rec["package_id"] != pkg["id"]:
            continue
        if rec.get("reversed"):
            continue
        active += rec.get("credits_used", 1)
    remaining = pkg["credits_total"] - active
    if remaining < 0:
        remaining = 0
    pkg["credits_remaining"] = remaining
    return remaining
