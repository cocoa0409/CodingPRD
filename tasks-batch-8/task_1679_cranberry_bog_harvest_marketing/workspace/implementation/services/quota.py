"""MemberQuota dual-variant computation and recomputation cascades.

quota_base_barrels (scaffold §1.3):
  baseline_quota_barrels = sum over the member's ACTIVE bogs of
                           round2(acres * season.baseline_barrels_per_acre)
  approved_estimate total = sum over ACTIVE bogs of (APPROVED estimate's
                           estimated_barrels if one exists else the rounded
                           acreage product)
  base_quota_barrels = base_quota_override if set else round2(approved total)
Recomputation is skipped while quota_locked is true.
"""
from decimal import Decimal

from db import store, touch
from validation import round2, to_decimal


def find_quota(member_id, season_id):
    for q in store.quotas.values():
        if q["member_id"] == member_id and q["season_id"] == season_id:
            return q
    return None


def approved_estimate_for(bog_id, season_id):
    for e in store.estimates.values():
        if e["bog_id"] == bog_id and e["season_id"] == season_id and e["status"] == "APPROVED":
            return e
    return None


def compute_quota_values(member_id, season):
    """Returns (baseline_quota_barrels, approved_estimate_total) both round2."""
    baseline = Decimal("0")
    approved_total = Decimal("0")
    per_acre = to_decimal(season["baseline_barrels_per_acre"])
    for bog in store.bogs.values():
        if bog["member_id"] != member_id or bog["status"] != "ACTIVE":
            continue
        per_bog = round2(to_decimal(bog["acres"]) * per_acre)
        baseline += per_bog
        est = approved_estimate_for(bog["id"], season["id"])
        if est is not None:
            approved_total += to_decimal(est["estimated_barrels"])
        else:
            approved_total += per_bog
    return round2(baseline), round2(approved_total)


def posture_of(quota):
    if to_decimal(quota["delivered_barrels"]) <= to_decimal(quota["base_quota_barrels"]):
        return "WITHIN_QUOTA"
    return "OVER_QUOTA"


def recompute_quota(quota):
    """Recompute both variants and posture. Skipped when locked.

    Every triggered recomputation is a mutation: version and updated_at
    advance (PRD §2.6 — recomputes increment the quota's version).
    """
    if quota["quota_locked"]:
        return
    season = store.seasons.get(quota["season_id"])
    if season is None:
        return
    baseline, approved_total = compute_quota_values(quota["member_id"], season)
    if quota["base_quota_override"] is not None:
        base = round2(to_decimal(quota["base_quota_override"]))
    else:
        base = approved_total
    quota["baseline_quota_barrels"] = baseline
    quota["base_quota_barrels"] = base
    quota["posture"] = posture_of(quota)
    touch(quota)


def recompute_member_quotas(member_id):
    """Recompute every non-locked quota row of the member (all seasons)."""
    for q in store.quotas.values():
        if q["member_id"] == member_id:
            recompute_quota(q)


def lock_season_quotas(season_id):
    for q in store.quotas.values():
        if q["season_id"] == season_id:
            q["quota_locked"] = True
            touch(q)


def unlock_season_quotas(season_id):
    for q in store.quotas.values():
        if q["season_id"] == season_id:
            q["quota_locked"] = False
            touch(q)
