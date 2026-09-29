"""Ledger bookkeeping, cascades, lazy lapse, promotion and sector selection."""
from decimal import Decimal

import calc
import db
import domain
from util import add_days, dec, q1


# ===========================================================================
# sector version bookkeeping
# ===========================================================================
class SectorTracker:
    """Bumps a sector's version once per request when its derived state moved.

    PRD 2.5: a recomputation of a derived field counts as a mutation.  A
    sector is therefore versioned when any of its ledger roll-ups or its
    posture changed during the request, or when the request wrote one of its
    stored fields directly.
    """

    def __init__(self):
        self.snapshots = {}
        self.dirty = set()

    def watch(self, sector):
        if sector is None:
            return
        if sector["id"] not in self.snapshots:
            self.snapshots[sector["id"]] = domain.sector_snapshot(sector)

    def watch_tower(self, tower_id):
        for sector in domain.tower_sectors(tower_id):
            self.watch(sector)

    def mark(self, sector):
        if sector is None:
            return
        self.watch(sector)
        self.dirty.add(sector["id"])

    def settle(self):
        for sector_id, snapshot in self.snapshots.items():
            sector = db.sectors.get(sector_id)
            if sector is None:
                continue
            if sector_id in self.dirty or domain.sector_snapshot(sector) != snapshot:
                db.touch(sector)


# ===========================================================================
# reservation unwinding
# ===========================================================================
def expire_reserved_request(hold):
    request = db.serviceability_requests.get(hold["serviceability_request_id"])
    if request is None:
        return
    # Chain X hop 4: only a QUALIFIED reservation expires.  A CAPACITY_DEFERRED
    # enquiry has no EXPIRED transition -- it simply stops being promotable.
    if request["status"] == "QUALIFIED":
        request["status"] = "EXPIRED"
        request["qualified_sector_id"] = None
        db.touch(request)


def release_hold(hold, reason, tracker):
    """Move a HELD reservation out of HELD without consuming it."""
    sector = db.sectors.get(hold["sector_id"])
    tracker.watch(sector)
    if reason == "LAPSED":
        hold["status"] = "EXPIRED"
    else:
        hold["status"] = "RELEASED"
    hold["release_reason"] = reason
    db.touch(hold)
    expire_reserved_request(hold)


def release_holds_on_sector(sector, reason, tracker):
    for hold in db.ordered(list(db.capacity_holds.values())):
        if hold["sector_id"] == sector["id"] and hold["status"] == "HELD":
            release_hold(hold, reason, tracker)


# ===========================================================================
# deferred-qualification promotion (PRD 3.5)
# ===========================================================================
def promote_deferred(sector, tracker):
    """Promote at most one CAPACITY_DEFERRED enquiry onto this sector."""
    if sector is None:
        return None
    ledger = domain.sector_ledger(sector)
    if ledger["capacity_posture"] not in (calc.POSTURE_OPEN, calc.POSTURE_WATCH):
        return None
    candidates = [r for r in db.serviceability_requests.values()
                  if r["candidate_tower_id"] == sector["tower_id"]
                  and r["status"] == "CAPACITY_DEFERRED"
                  and r.get("qualification_expires_at") is not None
                  and db.now() < r["qualification_expires_at"]]
    candidates.sort(key=lambda r: (r["created_at"], r["intake_sequence"]))
    for request in candidates:
        plan = db.service_plans.get(request["requested_plan_id"])
        if plan is None:
            continue
        if int(plan["downstream_mbps"]) <= ledger["remaining_allowance_mbps"]:
            request["status"] = "QUALIFIED"
            request["qualified_sector_id"] = sector["id"]
            db.touch(request)
            tracker.watch(sector)
            mint_hold(request, sector, plan, calc.AUTO_PROMOTION_HOLD_DAYS, "AUTO_PROMOTION")
            return request
    return None


def mint_hold(request, sector, plan, hold_days, origin):
    hold = db.base_record(
        serviceability_request_id=request["id"],
        sector_id=sector["id"],
        held_mbps=int(plan["downstream_mbps"]),
        hold_days=int(hold_days),
        expires_at=add_days(db.now(), int(hold_days)),
        status="HELD",
        release_reason=None,
        origin=origin,
    )
    db.capacity_holds[hold["id"]] = hold
    return hold


# ===========================================================================
# lazy lapse of reservations (PRD 2.4 / 3.6)
# ===========================================================================
def lapse_expired_holds():
    """Settle every reservation the logical clock has reached.

    Run at the start of every request: the outcome depends only on where the
    logical clock sits when the request arrives, and there is no sweeper.
    """
    expired = [h for h in db.ordered(list(db.capacity_holds.values()))
               if h["status"] == "HELD" and h.get("expires_at") is not None
               and db.now() >= h["expires_at"]]
    if not expired:
        return
    tracker = SectorTracker()
    for hold in expired:
        release_hold(hold, "LAPSED", tracker)
    for sector_id in list(tracker.snapshots.keys()):
        promote_deferred(db.sectors.get(sector_id), tracker)
    tracker.settle()


# ===========================================================================
# sector selection (PRD 3.5)
# ===========================================================================
def select_sector(tower, plan):
    """Return (chosen_sector, outcome) where outcome is QUALIFIED /
    CAPACITY_DEFERRED / NO_ACTIVE_SECTOR."""
    active = [s for s in domain.tower_sectors(tower["id"]) if s["status"] == "ACTIVE"]
    if not active:
        return None, "NO_ACTIVE_SECTOR"
    needed = int(plan["downstream_mbps"])
    eligible = []
    capacity_excluded = False
    licensed_any = False
    for sector in active:
        license_record = db.spectrum_licenses.get(sector["spectrum_license_id"])
        if license_record is None or domain.license_status(license_record) != "ACTIVE":
            continue
        licensed_any = True
        ledger = domain.sector_ledger(sector)
        if ledger["capacity_posture"] not in (calc.POSTURE_OPEN, calc.POSTURE_WATCH):
            capacity_excluded = True
            continue
        if ledger["remaining_allowance_mbps"] < needed:
            capacity_excluded = True
            continue
        eligible.append((ledger["oversubscription_ratio"], dec(sector["azimuth_deg"]),
                         sector["created_at"], sector["_seq"], sector))
    if eligible:
        eligible.sort(key=lambda row: (row[0], row[1], row[2], row[3]))
        return eligible[0][4], "QUALIFIED"
    if licensed_any and capacity_excluded:
        return None, "CAPACITY_DEFERRED"
    return None, "NO_ACTIVE_SECTOR"


# ===========================================================================
# the transport cascade (PRD 2.10 / 3.1)
# ===========================================================================
def cascade_circuit_degraded(tower, tracker):
    for sector in domain.tower_sectors(tower["id"]):
        tracker.watch(sector)
        ledger = domain.sector_ledger(sector)
        if ledger["capacity_posture"] == calc.POSTURE_FROZEN:
            release_holds_on_sector(sector, "BACKHAUL_DEGRADED", tracker)
    for sector in domain.tower_sectors(tower["id"]):
        promote_deferred(sector, tracker)


# ===========================================================================
# the decommission cascade (PRD 3.1 / 3.2)
# ===========================================================================
def cascade_tower_decommissioned(tower, tracker):
    for sector in domain.tower_sectors(tower["id"]):
        tracker.watch(sector)
        if sector["status"] not in ("PLANNED", "ACTIVE"):
            continue
        was_active = sector["status"] == "ACTIVE"
        sector["status"] = "DISABLED"
        tracker.mark(sector)
        if was_active:
            sector["capacity_policy_note"] = (
                "Sector disabled with the decommissioning of its tower.")
            release_holds_on_sector(sector, "SECTOR_DISABLED", tracker)


# ===========================================================================
# usage posture (PRD 3.8)
# ===========================================================================
def refresh_usage_posture(subscriber, plan):
    """Re-derive usage_priority and the shaped rate over the current window."""
    usage = domain.subscriber_cycle_usage_gb(subscriber)
    breached = usage > dec(plan["soft_cap_gb"])
    target = "DEPRIORITIZED" if (breached or subscriber["sticky_deprioritization_active"]) \
        else "STANDARD"
    current = subscriber["usage_priority"]
    if target == current:
        return breached
    if target == "DEPRIORITIZED":
        # Moving STANDARD -> DEPRIORITIZED needs an open cycle to breach.
        if subscriber["service_status"] not in ("ACTIVE", "SUSPENDED"):
            return breached
        subscriber["usage_priority"] = "DEPRIORITIZED"
        subscriber["deprioritized_at"] = db.now()
    else:
        subscriber["usage_priority"] = "STANDARD"
        subscriber["deprioritized_at"] = None
    return breached


# ===========================================================================
# cancellation cascade (PRD 3.8)
# ===========================================================================
def cascade_subscriber_cancelled(subscriber, previous_status, tracker):
    sector = db.sectors.get(subscriber["sector_id"])
    tracker.watch(sector)
    subscriber["cancelled_at"] = db.now()
    for assignment in domain.subscriber_assignments(subscriber["id"]):
        if previous_status in ("ACTIVE", "SUSPENDED"):
            if assignment["status"] == "DEPLOYED":
                assignment["status"] = "RETURN_PENDING"
                assignment["return_due_at"] = add_days(db.now(), calc.RETURN_WINDOW_DAYS)
                db.touch(assignment)
        else:
            if assignment["status"] == "ASSIGNED":
                assignment["status"] = "VOIDED"
                assignment["settlement_cents"] = 0
                assignment["settlement_basis"] = "NONE"
                db.touch(assignment)
    if previous_status == "PENDING_INSTALL":
        for order in domain.subscriber_work_orders(subscriber["id"]):
            if order["status"] in ("SCHEDULED", "EXCEPTION_PENDING", "RESURVEY_REQUIRED"):
                order["status"] = "CANCELLED"
                db.touch(order)
    promote_deferred(sector, tracker)
