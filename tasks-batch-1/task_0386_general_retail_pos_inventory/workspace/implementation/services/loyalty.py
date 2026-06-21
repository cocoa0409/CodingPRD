"""Loyalty tier recompute (calc D, PRD §3.8)."""
from common import touch

SILVER_AT = 1000
GOLD_AT = 5000


def recompute_tier(account):
    """PRD §3.8: inclusive thresholds. >=5000 GOLD; >=1000 SILVER; else STANDARD."""
    lp = account["lifetime_points"]
    if lp >= GOLD_AT:
        account["tier"] = "GOLD"
    elif lp >= SILVER_AT:
        account["tier"] = "SILVER"
    else:
        account["tier"] = "STANDARD"


def apply_tier_multiplier(base_points, tier):
    """PRD §3.8: SILVER x1.25, GOLD x1.50, floored after multiply; STANDARD unchanged."""
    if tier == "SILVER":
        return (base_points * 125) // 100
    if tier == "GOLD":
        return (base_points * 150) // 100
    return base_points
