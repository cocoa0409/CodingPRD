"""Derived counters and the conservation invariants of PRD 2.10."""

from money import round_half_up_4, as_decimal
from store import db, new_row, clock
from ladder import touch, in_force_subscription

# PRD 3.1 -- entitled_device_count counts these lifecycle states.
ENTITLED_STATES = ("CLAIMED", "ACTIVE", "SERVICE_HOLD", "SUSPENDED_RMA", "TRANSFER_PENDING")
# PRD 3.1 -- active_device_count is the narrower count.
ACTIVE_STATES = ("ACTIVE", "SERVICE_HOLD", "SUSPENDED_RMA")
# PRD 3.4 / rung 34 -- an RMA case is "in flight" in these statuses.
RMA_IN_FLIGHT_STATES = ("OPEN", "ROUTED", "ADVANCE_SHIPPED", "AWAITING_RETURN")


def recompute_household_counts(household):
    """Recomputation of the derived counters does not by itself bump
    Household.version (PRD 2.4)."""
    if household is None:
        return
    hid = household["id"]
    entitled = 0
    active = 0
    for dev in db.devices.values():
        if dev.get("household_id") != hid:
            continue
        status = dev.get("lifecycle_status")
        if status in ENTITLED_STATES:
            entitled += 1
        if status in ACTIVE_STATES:
            active += 1
    household["entitled_device_count"] = entitled
    household["active_device_count"] = active


def recompute_overage_device_count(subscription):
    """PRD 3.2: overage_device_count counts the household's devices flagged
    is_overage whose lifecycle_status is one of the entitled states.  Booking
    a counter does not by itself bump Subscription.version."""
    if subscription is None:
        return
    hid = subscription.get("household_id")
    count = 0
    for dev in db.devices.values():
        if dev.get("household_id") != hid:
            continue
        if not dev.get("is_overage"):
            continue
        if dev.get("lifecycle_status") in ENTITLED_STATES:
            count += 1
    subscription["overage_device_count"] = count


def recompute_household_and_subscription(household):
    recompute_household_counts(household)
    if household is not None:
        sub = in_force_subscription(household["id"])
        recompute_overage_device_count(sub)


def recompute_slot_counts(technician):
    """PRD 3.8 slot-capacity conservation: open + booked + blocked == total,
    recomputed from the technician's slot rows with no time-window filter."""
    if technician is None:
        return
    tid = technician["id"]
    total = open_ = booked = blocked = 0
    for slot in db.visit_slots.values():
        if slot.get("technician_id") != tid:
            continue
        total += 1
        status = slot.get("status")
        if status == "OPEN":
            open_ += 1
        elif status == "BOOKED":
            booked += 1
        elif status == "BLOCKED":
            blocked += 1
    technician["total_slot_count"] = total
    technician["open_slot_count"] = open_
    technician["booked_slot_count"] = booked
    technician["blocked_slot_count"] = blocked


def recompute_ring_counters(campaign):
    """PRD 3.9: the counters cover the CURRENT ring only; earlier rings never
    re-enter the calculation.  The rate is rounded half up to four decimal
    places before any threshold comparison."""
    if campaign is None:
        return
    ring = campaign.get("current_ring_index")
    rows = [r for r in db.firmware_rollouts.values()
            if r.get("campaign_id") == campaign["id"] and r.get("ring_index") == ring]
    count = len(rows)
    failed = len([r for r in rows if r.get("status") == "ROLLED_BACK"])
    campaign["ring_device_count"] = count
    campaign["ring_failed_count"] = failed
    if count == 0:
        campaign["ring_failure_rate"] = 0
    else:
        campaign["ring_failure_rate"] = float(round_half_up_4(as_decimal(failed) / as_decimal(count)))


def ring_rollouts(campaign):
    ring = campaign.get("current_ring_index")
    return [r for r in db.firmware_rollouts.values()
            if r.get("campaign_id") == campaign["id"] and r.get("ring_index") == ring]


def device_has_rma_in_flight(device_id):
    for case in db.rma_cases.values():
        if case.get("device_id") == device_id and case.get("status") in RMA_IN_FLIGHT_STATES:
            return True
    return False


def household_of_device(device):
    if device is None:
        return None
    return db.households.get(device.get("household_id"))


def household_of_ticket(ticket):
    if ticket is None:
        return None
    return db.households.get(ticket.get("household_id"))
