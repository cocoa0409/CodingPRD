"""Renewal run + box-revert cascades (PRD §3.12, §3.3, §3.5)."""
from db import db
from common import touch
from services.ledger import cadence_delta, create_invoice, create_billing_cycle
from services.inventory import release_allocation


def _plan_for(subscription):
    return db.plans[subscription["plan_id"]]


def revert_finalized_box_for_period(subscription, period_index, revert_to="SKIPPED"):
    """Revert a FINALIZED box for `period_index` into an OPEN/LOCKED wave.

    Used by immediate-cancel cascade (revert_to SKIPPED, PRD §3.3) and by the
    charge-failed cascade (revert_to SKIPPED, PRD §3.12). Releasing the
    allocation runs the restock + reserved_count decrement cascade.
    """
    sub_id = subscription["id"]
    for box in list(db.box_selections.values()):
        if box["subscription_id"] != sub_id:
            continue
        if box["period_index"] != period_index:
            continue
        if box["decision"] != "FINALIZED" or not box.get("allocation_id"):
            continue
        alloc = db.allocations.get(box["allocation_id"])
        if alloc is None or alloc["status"] != "RESERVED":
            continue
        wave = db.shipping_waves.get(alloc["wave_id"])
        if wave is None or wave["status"] not in ("OPEN", "LOCKED"):
            continue
        # release returns units, decrements reserved_count, reverts box
        release_allocation(alloc, revert_decision=revert_to)


def revert_all_upcoming_finalized(subscription, revert_to="SKIPPED"):
    """Cancel cascade: revert every upcoming FINALIZED box in OPEN/LOCKED waves."""
    sub_id = subscription["id"]
    current = subscription["current_period_index"]
    for box in list(db.box_selections.values()):
        if box["subscription_id"] != sub_id:
            continue
        if box["period_index"] <= current:
            continue
        if box["decision"] != "FINALIZED" or not box.get("allocation_id"):
            continue
        alloc = db.allocations.get(box["allocation_id"])
        if alloc is None or alloc["status"] != "RESERVED":
            continue
        wave = db.shipping_waves.get(alloc["wave_id"])
        if wave is None or wave["status"] not in ("OPEN", "LOCKED"):
            continue
        release_allocation(alloc, revert_decision=revert_to)


def run_renewal(target_subscription_id=None, charge_outcome=None):
    """Run the renewal/wave epoch at the current clock (PRD §3.12)."""
    clock = db.now()
    subs = list(db.subscriptions.values())
    if target_subscription_id is not None:
        subs = [s for s in subs if s["id"] == target_subscription_id]

    for sub in subs:
        _process_subscription(sub, clock, charge_outcome)


def _process_subscription(sub, clock, charge_outcome):
    plan = _plan_for(sub)

    # 1. Auto-resume a paused subscription whose paused_until the clock reached.
    if sub["lifecycle_status"] == "PAUSED":
        if sub["paused_until"] is not None and clock >= sub["paused_until"]:
            _auto_resume(sub, plan, clock)
        else:
            return  # still paused; nothing else fires

    # 2. Fire a CANCEL_SCHEDULED subscription whose scheduled date is due.
    if sub["lifecycle_status"] == "CANCEL_SCHEDULED":
        if sub["next_renewal_at"] is not None and clock >= sub["next_renewal_at"]:
            sub["lifecycle_status"] = "CANCELLED"
            sub["next_renewal_at"] = None
            sub["prepaid_periods_remaining"] = 0
            sub["prepaid_unit_value_cents"] = 0
            sub["billing_status"] = "CURRENT"
            touch(sub)
        return

    if sub["lifecycle_status"] != "ACTIVE":
        return

    # Renewal due?
    nra = sub["next_renewal_at"]
    if nra is None or clock < nra:
        return

    # 3. Drive the renewal by billing posture.
    if sub["billing_status"] == "PREPAID":
        _renew_prepaid(sub, plan, clock)
    elif sub["billing_status"] == "CURRENT":
        _renew_charge(sub, plan, clock, charge_outcome)
    elif sub["billing_status"] == "PAST_DUE":
        # Past-due subscriptions are resolved via retry-charge, not the run.
        return


def _auto_resume(sub, plan, clock):
    """PAUSED -> ACTIVE on clock>=paused_until (PRD §3.3)."""
    pause_start = sub.get("_pause_start")
    delta = cadence_delta(plan["cadence"])
    if sub["next_renewal_at"] is not None and pause_start is not None:
        elapsed = clock - pause_start
        periods = 0
        if delta.total_seconds() > 0:
            # round elapsed up to whole cadence periods forward
            import math
            periods = math.ceil(elapsed.total_seconds() / delta.total_seconds())
        sub["next_renewal_at"] = sub["next_renewal_at"] + periods * delta
    sub["lifecycle_status"] = "ACTIVE"
    sub["paused_until"] = None
    sub["_pause_start"] = None
    touch(sub)


def _advance_period(sub, plan):
    sub["current_period_index"] += 1
    delta = cadence_delta(plan["cadence"])
    if sub["next_renewal_at"] is not None:
        sub["next_renewal_at"] = sub["next_renewal_at"] + delta


def _renew_prepaid(sub, plan, clock):
    new_period = sub["current_period_index"] + 1
    last_draw = sub["prepaid_periods_remaining"] == 1
    if sub["is_gift"]:
        create_billing_cycle(sub["id"], new_period, 0, "GIFT",
                             status="PAID", charged_at=clock)
    else:
        create_billing_cycle(sub["id"], new_period, 0, "PREPAID_DRAW",
                             status="PAID", charged_at=clock)
    sub["prepaid_periods_remaining"] -= 1
    _advance_period(sub, plan)

    if last_draw:
        if sub["is_gift"]:
            # gift exhausted -> EXPIRED (PRD §3.12)
            sub["lifecycle_status"] = "EXPIRED"
            sub["next_renewal_at"] = None
            sub["prepaid_unit_value_cents"] = 0
        else:
            # prepaid drained -> billing CURRENT (PRD §3.4)
            sub["billing_status"] = "CURRENT"
            sub["prepaid_unit_value_cents"] = 0
    touch(sub)


def _renew_charge(sub, plan, clock, charge_outcome):
    new_period = sub["current_period_index"] + 1
    outcome = charge_outcome if charge_outcome in ("PAID", "FAILED") else "PAID"
    amount = plan["period_price_cents"]
    if outcome == "PAID":
        cycle = create_billing_cycle(sub["id"], new_period, amount, "CHARGE",
                                     status="PAID", charged_at=clock)
        create_invoice(sub["subscriber_id"], sub["id"], amount, "PERIOD_CHARGE")
        _advance_period(sub, plan)
        touch(sub)
    else:
        create_billing_cycle(sub["id"], new_period, amount, "CHARGE",
                             status="FAILED", charged_at=clock)
        # CURRENT -> PAST_DUE; box revert for the failed period (PRD §3.12)
        sub["billing_status"] = "PAST_DUE"
        _advance_period(sub, plan)
        revert_finalized_box_for_period(sub, new_period, revert_to="SKIPPED")
        touch(sub)
