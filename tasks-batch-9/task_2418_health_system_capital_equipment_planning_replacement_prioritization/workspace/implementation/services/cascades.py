"""Shared multi-hop cascades (PRD sections 2.10, 3.2, 3.5, 3.9, 3.11)."""

from db import db, ordered, touch
from services import allocation as allocation_service
from services import scoring


def rescore_asset_requests(asset):
    """Re-score every SCORED request of an asset (ASSET_CONDITION_CHANGE)."""
    affected_cycles = {}
    for request in ordered(db.requests.values()):
        if request["asset_id"] != asset["id"] or request["status"] != "SCORED":
            continue
        scoring.score_request(request, "ASSET_CONDITION_CHANGE")
        touch(request)
        affected_cycles[request["cycle_id"]] = True
    for cycle_id in affected_cycles:
        cycle = db.cycles.get(cycle_id)
        if cycle is not None:
            scoring.refresh_cycle_counts(cycle)


def rescore_department_requests(department):
    """Re-score a department's SCORED requests (DEPARTMENT_PENALTY_CHANGE)."""
    affected_cycles = {}
    for request in ordered(db.requests.values()):
        if request["department_id"] != department["id"]:
            continue
        if request["status"] != "SCORED":
            continue
        cycle = db.cycles.get(request["cycle_id"])
        if cycle is None or cycle["status"] not in ("SCORING", "ALLOCATED"):
            continue
        scoring.score_request(request, "DEPARTMENT_PENALTY_CHANGE")
        touch(request)
        affected_cycles[cycle["id"]] = cycle
    for cycle in affected_cycles.values():
        scoring.refresh_cycle_counts(cycle)


def apply_committed_delta(allocation, cycle, delta):
    """Move committed_cents by delta, recomputing the identity and posture."""
    allocation["committed_cents"] += delta
    allocation_service.refresh_available(allocation)
    cycle_changed = allocation_service.refresh_posture(allocation, cycle)
    touch(allocation)
    if cycle_changed:
        touch(cycle)
    return cycle_changed


def auto_commit_if_exhausted(cycle):
    """PRD 3.9 hop 4: the cycle auto-commits once every row is exhausted."""
    if cycle["status"] != "ALLOCATED":
        return False
    if cycle["allocation_count"] <= 0:
        return False
    if cycle["exhausted_allocation_count"] != cycle["allocation_count"]:
        return False
    cycle["status"] = "COMMITTED"
    return True


def defer_open_requests(cycle):
    """Every request still SCORED or IN_COMMITTEE moves to DEFERRED."""
    for request in ordered(db.requests.values()):
        if request["cycle_id"] != cycle["id"]:
            continue
        if request["status"] not in ("SCORED", "IN_COMMITTEE"):
            continue
        request["status"] = "DEFERRED"
        touch(request)


def release_trade_in_claim(quote):
    """Undo an accepted quote's hold on its trade-in asset."""
    asset_id = quote.get("trade_in_asset_id")
    if not asset_id:
        return
    asset = db.assets.get(asset_id)
    if asset is None:
        return
    asset["trade_in_credit_applied_cents"] = 0
    if asset["disposition_status"] == "HELD_FOR_TRADE_IN":
        asset["disposition_status"] = "NONE"
    touch(asset)


def claim_trade_in(quote):
    asset_id = quote.get("trade_in_asset_id")
    if not asset_id:
        return
    asset = db.assets.get(asset_id)
    if asset is None:
        return
    asset["trade_in_credit_applied_cents"] = quote["trade_in_credit_cents"]
    asset["disposition_status"] = "HELD_FOR_TRADE_IN"
    touch(asset)
