"""Firmware campaign / rollout side effects shared across endpoints (PRD 3.9).

These are the cascade hops 4 and 5 of the depth-five escalation cascade, the
decommission cascade, the halt and the completion rule.
"""

from counters import recompute_ring_counters, ring_rollouts
from ladder import touch
from money import as_decimal
from store import db


def _campaign_of(rollout):
    return db.firmware_campaigns.get(rollout.get("campaign_id"))


def block_pending_rollouts(device):
    """Cascade hop 4 (and the decommission cascade): every PENDING rollout
    targeting the device moves to BLOCKED_BY_SERVICE and the device's firmware
    axis moves to BLOCKED where it stood at UPDATE_PENDING.  Hop 5 then
    recomputes the ring counters of each affected campaign and completes a
    RING_ACTIVE campaign whose current ring is left with no PENDING rollout
    while its failure rate is below the halt threshold."""
    affected = set()
    moved = False
    for rollout in db.firmware_rollouts.values():
        if rollout.get("device_id") != device["id"] or rollout.get("status") != "PENDING":
            continue
        rollout["status"] = "BLOCKED_BY_SERVICE"
        touch(rollout)
        moved = True
        campaign = _campaign_of(rollout)
        if campaign is not None:
            affected.add(campaign["id"])
    if moved and device.get("firmware_status") == "UPDATE_PENDING":
        device["firmware_status"] = "BLOCKED"
    for cid in affected:
        campaign = db.firmware_campaigns.get(cid)
        recompute_ring_counters(campaign)
        maybe_complete_campaign(campaign)
        touch(campaign)


def release_service_hold_rollouts(device):
    """PRD 3.8: every rollout of the device sitting in BLOCKED_BY_SERVICE whose
    owning campaign is RING_ACTIVE returns to PENDING, with the device's
    firmware_status returning to UPDATE_PENDING."""
    affected = set()
    moved = False
    for rollout in db.firmware_rollouts.values():
        if rollout.get("device_id") != device["id"]:
            continue
        if rollout.get("status") != "BLOCKED_BY_SERVICE":
            continue
        campaign = _campaign_of(rollout)
        if campaign is None or campaign.get("status") != "RING_ACTIVE":
            continue
        rollout["status"] = "PENDING"
        touch(rollout)
        moved = True
        affected.add(campaign["id"])
    if moved and device.get("firmware_status") == "BLOCKED":
        device["firmware_status"] = "UPDATE_PENDING"
    for cid in affected:
        campaign = db.firmware_campaigns.get(cid)
        recompute_ring_counters(campaign)
        touch(campaign)


def halt_campaign(campaign):
    """PRD 3.9: halting sets every rollout of the current ring still in PENDING
    to BLOCKED_BY_HALT and moves each of those devices' firmware_status to
    BLOCKED; the campaign's status becomes HALTED."""
    for rollout in ring_rollouts(campaign):
        if rollout.get("status") != "PENDING":
            continue
        rollout["status"] = "BLOCKED_BY_HALT"
        touch(rollout)
        device = db.devices.get(rollout.get("device_id"))
        if device is not None and device.get("firmware_status") == "UPDATE_PENDING":
            device["firmware_status"] = "BLOCKED"
            touch(device)
    campaign["status"] = "HALTED"


def maybe_halt_campaign(campaign):
    """The campaign halts when the rounded ring failure rate is greater than or
    equal to its halt_failure_rate_pct."""
    if campaign.get("status") != "RING_ACTIVE":
        return False
    rate = as_decimal(campaign.get("ring_failure_rate") or 0)
    threshold = as_decimal(campaign.get("halt_failure_rate_pct"))
    if rate >= threshold:
        halt_campaign(campaign)
        return True
    return False


def maybe_complete_campaign(campaign):
    """PRD 3.9: whenever an operation leaves a RING_ACTIVE campaign's current
    ring with no rollout in PENDING while ring_failure_rate is STRICTLY below
    halt_failure_rate_pct, the campaign becomes COMPLETED, which is terminal.

    Implemented exactly as written and NOT softened.  The determinate
    consequence -- that the RING_ACTIVE -> RING_ACTIVE multi-ring self-loop is
    only reachable when the ring is emptied while the rate is at or above the
    halt threshold, at which point the campaign has halted instead -- is left
    standing.
    """
    if campaign is None or campaign.get("status") != "RING_ACTIVE":
        return False
    for rollout in ring_rollouts(campaign):
        if rollout.get("status") == "PENDING":
            return False
    rate = as_decimal(campaign.get("ring_failure_rate") or 0)
    threshold = as_decimal(campaign.get("halt_failure_rate_pct"))
    if rate < threshold:
        campaign["status"] = "COMPLETED"
        return True
    return False
