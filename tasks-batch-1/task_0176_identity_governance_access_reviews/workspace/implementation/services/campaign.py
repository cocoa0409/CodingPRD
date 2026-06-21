"""Certification campaign derived fields: posture, completion_pct, and the
projected/realized revocation-impact pair (SCAFFOLD §1.3 / PRD §3.8).
"""
from decimal import Decimal, ROUND_HALF_UP

import db


def _items_of(campaign_id):
    return [it for it in db.certification_items.values()
            if it["campaign_id"] == campaign_id]


def compute_posture(campaign):
    """OPEN while DRAFT; COMPLETE when every item is CERTIFIED/REVOKED (or zero
    items); otherwise IN_REVIEW (PRD §3.8)."""
    if campaign["status"] == "DRAFT":
        return "OPEN"
    items = _items_of(campaign["id"])
    if not items or all(it["decision_status"] in ("CERTIFIED", "REVOKED") for it in items):
        return "COMPLETE"
    return "IN_REVIEW"


def compute_completion_pct(campaign):
    """divide-then-round: ratio over the frozen item_count, multiplied by 100,
    rounded HALF_UP to 2 dp exactly once (PRD §3.8)."""
    total = campaign.get("item_count") or 0
    if total == 0:
        return 100.00
    decided = sum(1 for it in _items_of(campaign["id"])
                  if it["decision_status"] in ("CERTIFIED", "REVOKED"))
    ratio = (Decimal(decided) / Decimal(total)) * Decimal(100)
    rounded = ratio.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(rounded)


def compute_projected_revocation(campaign):
    """Items still PENDING/UNDER_REVIEW that would auto-revoke at close."""
    return sum(1 for it in _items_of(campaign["id"])
               if it["decision_status"] in ("PENDING", "UNDER_REVIEW"))


def compute_realized_revocation(campaign):
    """Items actually flipped to REVOKED."""
    return sum(1 for it in _items_of(campaign["id"])
               if it["decision_status"] == "REVOKED")


def recompute_campaign_derived(campaign):
    """Refresh posture / completion_pct / projected / realized counts in place.

    These are derived read-fields; recomputing them does not on its own bump
    version (they are reflected at read time and on the transitions that own
    them). We keep them stored so list/get returns the current figures.
    """
    campaign["posture"] = compute_posture(campaign)
    campaign["completion_pct"] = compute_completion_pct(campaign)
    campaign["projected_revocation_count"] = compute_projected_revocation(campaign)
    campaign["realized_revocation_count"] = compute_realized_revocation(campaign)
