"""Rotation provider selection + offer dispatch / re-offer cascade
(scaffold rotation_selection / PRD §3.2)."""
from datetime import timedelta

import db
from clock import iso, now
from errors import ApiError
from services import providers as provider_svc


def active_providers_ranked():
    """ACTIVE providers ordered by rotation_rank ASC, created_at (_seq) ASC tiebreak."""
    actives = [p for p in db.tow_providers.values() if p["status"] == "ACTIVE"]
    actives.sort(key=lambda p: (p["rotation_rank"], p["_seq"]))
    return actives


def offered_count(provider_id):
    return sum(1 for a in db.rotation_assignments.values()
               if a["provider_id"] == provider_id and a["status"] == "OFFERED")


def select_provider(lot):
    """Deterministic selector. Candidate set: ACTIVE providers under the lot's
    concurrent-offer cap. Scan rank-ordered list cyclically starting at the lot's
    rotation_cursor; first eligible at/after the cursor wins. None -> no eligible."""
    ranked = active_providers_ranked()
    if not ranked:
        return None
    cap = lot["max_provider_concurrent_offers"]
    n = len(ranked)
    cursor = lot.get("rotation_cursor", 0) % n if n else 0
    for i in range(n):
        idx = (cursor + i) % n
        prov = ranked[idx]
        if offered_count(prov["id"]) < cap:
            return prov
    return None


def dispatch(lot, offer_ttl_minutes):
    """Select a provider and mint an OFFERED RotationAssignment. Advances the
    lot's rotation_cursor and bumps the selected provider's offers_received_count.
    Does NOT bump the lot version (callers do that). Raises ERR_NO_ELIGIBLE_PROVIDER."""
    prov = select_provider(lot)
    if prov is None:
        raise ApiError("ERR_NO_ELIGIBLE_PROVIDER", "No eligible ACTIVE provider under capacity")
    offered_dt = now()
    expires_dt = offered_dt + timedelta(minutes=offer_ttl_minutes)
    assignment = {
        "lot_id": lot["id"],
        "provider_id": prov["id"],
        "offered_at": iso(offered_dt),
        "expires_at": iso(expires_dt),
        "offer_ttl_minutes": offer_ttl_minutes,
        "superseded_by_id": None,
        "status": "OFFERED",
        "_offered_dt": offered_dt,
        "_expires_dt": expires_dt,
    }
    db.stamp_create(assignment)
    db.rotation_assignments[assignment["id"]] = assignment

    # selected provider counter + standing
    prov["offers_received_count"] += 1
    provider_svc.recompute_standing(prov)
    db.touch(prov)

    # advance cursor (mod list length over ACTIVE providers)
    ranked = active_providers_ranked()
    if ranked:
        lot["rotation_cursor"] = (lot.get("rotation_cursor", 0) + 1) % len(ranked)
    return assignment


def reoffer_cascade(declined_assignment):
    """Decline/expire re-offer cascade. Advance cursor, mint next OFFERED offer to
    the next eligible provider, bump that provider's counter, and set
    superseded_by_id on the declined/expired row. If no eligible provider, no
    re-offer is dispatched and superseded_by_id stays null (graceful, per selector
    'deferred, no offer')."""
    lot = db.impound_lots.get(declined_assignment["lot_id"])
    if lot is None:
        return None
    prov = select_provider(lot)
    if prov is None:
        return None
    offered_dt = now()
    ttl = declined_assignment["offer_ttl_minutes"]
    expires_dt = offered_dt + timedelta(minutes=ttl)
    new_assignment = {
        "lot_id": lot["id"],
        "provider_id": prov["id"],
        "offered_at": iso(offered_dt),
        "expires_at": iso(expires_dt),
        "offer_ttl_minutes": ttl,
        "superseded_by_id": None,
        "status": "OFFERED",
        "_offered_dt": offered_dt,
        "_expires_dt": expires_dt,
    }
    db.stamp_create(new_assignment)
    db.rotation_assignments[new_assignment["id"]] = new_assignment

    prov["offers_received_count"] += 1
    provider_svc.recompute_standing(prov)
    db.touch(prov)

    ranked = active_providers_ranked()
    if ranked:
        lot["rotation_cursor"] = (lot.get("rotation_cursor", 0) + 1) % len(ranked)
    db.touch(lot)

    declined_assignment["superseded_by_id"] = new_assignment["id"]
    return new_assignment
