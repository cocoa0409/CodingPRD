"""The two scarce ledgers: cell slots and beam megabits (PRD 2.8, 3.2, 3.3).

Every counter here is derived from the stored rows rather than cached, so a
cascade hop only has to `touch()` the record whose figures moved.
"""

from datetime import timedelta

from clock import clock
from constants import (
    CONSTRAINED_FRACTION,
    DEPRIORITIZED_WEIGHT,
    PLAN_TIER_RANK,
    RESERVATION_HOLD_HOURS,
    SLOT_OCCUPYING_STATES,
    SOLD_SET_STATES,
    TIER_WEIGHT,
    WAITLIST_CAP_PER_CELL,
    WAIT_DAY_CAP,
)
from db import db, ordered, touch
from numeric import ZERO, dec, floor_days, q


# ------------------------------------------------------------- navigation ----

def beam_of_cell(cell):
    return db.beams.get(cell["beam_id"])


def cells_of_beam(beam):
    return ordered([c for c in db.cells.values() if c["beam_id"] == beam["id"]])


def cell_of_subscription(subscription):
    return db.cells.get(subscription["service_cell_id"])


def beam_of_subscription(subscription):
    cell = cell_of_subscription(subscription)
    return beam_of_cell(cell) if cell else None


def plan_of_subscription(subscription):
    return db.plans.get(subscription["service_plan_id"])


def license_of_beam(beam):
    return db.licenses.get(beam["spectrum_license_id"]) if beam else None


def subscriptions_of_cell(cell):
    return ordered(
        [s for s in db.subscriptions.values() if s["service_cell_id"] == cell["id"]]
    )


def subscriptions_of_beam(beam):
    cell_ids = {c["id"] for c in db.cells.values() if c["beam_id"] == beam["id"]}
    return ordered(
        [s for s in db.subscriptions.values() if s["service_cell_id"] in cell_ids]
    )


def ordered_subscriptions_on_terminal(terminal_id):
    return ordered(
        [s for s in db.subscriptions.values() if s["terminal_id"] == terminal_id]
    )


def orders_of_cell(cell):
    return ordered(
        [o for o in db.orders.values() if o["service_cell_id"] == cell["id"]]
    )


# ------------------------------------------------------------- cell slots ----

def committed_terminal_count(cell):
    return sum(
        1
        for s in db.subscriptions.values()
        if s["service_cell_id"] == cell["id"]
        and s["service_state"] in SLOT_OCCUPYING_STATES
    )


def reserved_slot_count(cell):
    return sum(
        1
        for o in db.orders.values()
        if o["service_cell_id"] == cell["id"] and o["order_state"] == "RESERVED"
    )


def expired_reserved_count(cell):
    now = clock.now()
    return sum(
        1
        for o in db.orders.values()
        if o["service_cell_id"] == cell["id"]
        and o["order_state"] == "RESERVED"
        and o["reservation_expires_at"] is not None
        and o["reservation_expires_at"] <= now
    )


def waitlist_depth(cell):
    return sum(
        1
        for o in db.orders.values()
        if o["service_cell_id"] == cell["id"] and o["order_state"] == "WAITLISTED"
    )


def free_slot_count(cell):
    """The advertised (strict) free-slot figure: every RESERVED row counts."""
    return max(
        0,
        cell["max_active_terminals"]
        - committed_terminal_count(cell)
        - reserved_slot_count(cell),
    )


def admission_free(cell, self_reservation=0):
    """The write-path figure: expired holds (and the caller's own) do not count."""
    reserved = reserved_slot_count(cell) - expired_reserved_count(cell) - self_reservation
    return max(0, cell["max_active_terminals"] - committed_terminal_count(cell) - reserved)


def availability_state(cell):
    beam = beam_of_cell(cell)
    if beam is not None and beam["beam_state"] == "SUSPENDED":
        return "CLOSED"
    if beam is not None and capacity_state(beam) == "SATURATED":
        return "CLOSED"
    if cell["max_active_terminals"] == 0:
        return "CLOSED"
    if free_slot_count(cell) >= 1:
        return "AVAILABLE"
    if waitlist_depth(cell) < WAITLIST_CAP_PER_CELL:
        return "WAITLIST_ONLY"
    return "CLOSED"


# ----------------------------------------------------------- beam megabits ---

def subscription_weight(subscription):
    if subscription["priority_state"] == "DEPRIORITIZED":
        return DEPRIORITIZED_WEIGHT
    plan = plan_of_subscription(subscription)
    if plan is None:
        return ZERO
    return TIER_WEIGHT[plan["priority_tier"]]


def subscription_contribution(subscription):
    plan = plan_of_subscription(subscription)
    if plan is None:
        return ZERO
    return dec(plan["committed_rate_mbps"]) * subscription_weight(subscription)


def weighted_sold_mbps(beam):
    total = ZERO
    for subscription in subscriptions_of_beam(beam):
        if subscription["service_state"] in SOLD_SET_STATES:
            total += subscription_contribution(subscription)
    return q(total, 3)


def oversubscription_ratio(beam):
    capacity = dec(beam["forward_capacity_mbps"])
    if capacity == 0:
        return q(0, 4)
    return q(weighted_sold_mbps(beam) / capacity, 4)


def capacity_state(beam):
    ratio = oversubscription_ratio(beam)
    limit = dec(beam["oversubscription_limit"])
    if ratio > limit:
        return "SATURATED"
    if ratio > CONSTRAINED_FRACTION * limit:
        return "CONSTRAINED"
    return "NORMAL"


def projected_ratio(beam, delta):
    capacity = dec(beam["forward_capacity_mbps"])
    if capacity == 0:
        return q(0, 4)
    return q((weighted_sold_mbps(beam) + delta) / capacity, 4)


def has_headroom(beam, delta):
    """Exact equality with the limit is admitted; strictly above is refused."""
    return projected_ratio(beam, delta) <= dec(beam["oversubscription_limit"])


def effective_threshold_gb(subscription, plan=None, beam=None):
    plan = plan or plan_of_subscription(subscription)
    beam = beam or beam_of_subscription(subscription)
    allowance = dec(plan["priority_data_gb"]) if plan else ZERO
    grace = dec(beam["deprioritization_grace_gb"]) if beam else ZERO
    return allowance + grace


def effective_rate_mbps(subscription):
    plan = plan_of_subscription(subscription)
    if plan is None:
        return None
    if subscription["priority_state"] == "DEPRIORITIZED":
        return dec(plan["deprioritized_rate_mbps"])
    return dec(plan["committed_rate_mbps"])


def apply_fair_use_threshold(subscription, plan=None, beam=None):
    """Flip PRIORITY -> DEPRIORITIZED when the counter reaches the threshold.

    The boundary is inclusive and the flip is one-directional: raising the grace
    never restores a subscription that has already flipped.
    """
    if subscription["priority_state"] != "PRIORITY":
        return False
    threshold = effective_threshold_gb(subscription, plan, beam)
    if dec(subscription["cycle_priority_gb_used"]) >= threshold:
        subscription["priority_state"] = "DEPRIORITIZED"
        subscription["deprioritized_at"] = clock.now()
        touch(subscription)
        return True
    return False


def overage_gb(subscription, plan=None, beam=None):
    threshold = effective_threshold_gb(subscription, plan, beam)
    raw = q(dec(subscription["cycle_priority_gb_used"]) - threshold, 3)
    return raw if raw > 0 else q(0, 3)


# --------------------------------------------------------------- cascades ----

def recompute_beam(beam):
    """The congestion figures are derived; the recompute is the version bump."""
    if beam is not None:
        touch(beam)


def recompute_cells_of_beam(beam):
    if beam is None:
        return
    for cell in cells_of_beam(beam):
        touch(cell)


def recompute_cell(cell):
    if cell is not None:
        touch(cell)


# ---------------------------------------------------------- waitlist / hold --

def reservation_deadline():
    return clock.now() + timedelta(hours=RESERVATION_HOLD_HOURS)


def waitlist_priority_score(order):
    plan = db.plans.get(order["requested_plan_id"])
    rank = PLAN_TIER_RANK[plan["priority_tier"]] if plan else 0
    waited = floor_days((clock.now() - order["created_at"]).total_seconds())
    if waited < 0:
        waited = 0
    return rank * 1000 + min(waited, WAIT_DAY_CAP)


def run_promotion(cell):
    """The single shared promotion routine (PRD 3.3).

    Waiting time is re-accrued for every waitlisted order on the cell at each
    evaluation, then the top-ranked order takes each free slot in turn.
    """
    promoted = 0
    while True:
        eligible = [
            o
            for o in db.orders.values()
            if o["service_cell_id"] == cell["id"] and o["order_state"] == "WAITLISTED"
        ]
        for order in eligible:
            order["waitlist_priority_score"] = waitlist_priority_score(order)
        if not eligible or free_slot_count(cell) < 1:
            return promoted
        eligible.sort(
            key=lambda o: (-o["waitlist_priority_score"], o["created_at"], o["_seq"])
        )
        winner = eligible[0]
        winner["order_state"] = "RESERVED"
        winner["reservation_expires_at"] = reservation_deadline()
        winner["promoted_at"] = clock.now()
        touch(winner)
        subscriber = db.subscribers.get(winner["subscriber_id"])
        if subscriber is not None and subscriber["account_state"] == "WAITLISTED":
            subscriber["account_state"] = "PROSPECT"
            touch(subscriber)
        promoted += 1


def expire_reservations(cell):
    """Lazy expiry: release dead holds, never promote (PRD 3.3)."""
    now = clock.now()
    expired = 0
    for order in orders_of_cell(cell):
        if (
            order["order_state"] == "RESERVED"
            and order["reservation_expires_at"] is not None
            and order["reservation_expires_at"] <= now
        ):
            order["order_state"] = "EXPIRED"
            touch(order)
            expired += 1
    if expired:
        touch(cell)
    return expired
