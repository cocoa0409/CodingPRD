"""Subscription lifecycle service: cycle opening, cancel cascade, renew, etc."""
from datetime import timedelta
from decimal import Decimal

from util import iso_now, parse_iso, gen_id
from common import new_common, new_common_appendonly, touch
import db
from services import calculations as calc


def open_cycle(sub, start_dt, cycle_index):
    """Create the PENDING RENEWAL charge and cadence-count shipments for this cycle.

    Returns (charge, shipments).
    """
    plan = db.plans[sub["plan_id"]]

    # 1) Compute renewal price at cycle open using current subscription config
    price = calc.renewal_price_cents(
        plan=plan,
        size=sub["size"],
        vase_addon=sub.get("vase_addon", False),
        discount_pct=sub.get("discount_pct", 0),
    )

    # 2) Create the RENEWAL charge
    charge = {
        **new_common(),
        "subscription_id": sub["id"],
        "cycle_index": cycle_index,
        "kind": "RENEWAL",
        "amount_cents": price,
        "status": "PENDING",
        "refunded_cents": 0,
    }
    db.charges[charge["id"]] = charge

    # 3) Create shipments
    cadence = plan["cadence"]
    n = calc.DELIVERIES_PER_CYCLE[cadence]
    spacing = calc.CADENCE_SPACING_DAYS[cadence]
    shipments = []
    for k in range(n):
        sd = start_dt + timedelta(days=calc.FIRST_LEAD_DAYS + spacing * k)
        sh = {
            **new_common(),
            "subscription_id": sub["id"],
            "cycle_index": cycle_index,
            "scheduled_delivery_date": iso_now(sd),
            "status": "SCHEDULED",
            "occasion": sub.get("occasion"),
            "gift_message": sub.get("gift_message"),
            "substitution_applied": False,
            "route_id": None,
            "delivery_window_start": None,
            "delivery_window_end": None,
            "stem_cost_cents": None,
        }
        db.shipments[sh["id"]] = sh
        shipments.append(sh)

    return charge, shipments


def release_allocation(alloc):
    """Move an allocation to RELEASED and restore lot quantity_available.

    Restoration is implicit — quantity_available is computed from RESERVED/COMMITTED
    allocations only, so a RELEASED status is enough.
    """
    if alloc["status"] not in ("RESERVED", "COMMITTED"):
        return
    alloc["status"] = "RELEASED"
    touch(alloc)


def cancel_shipment_cascade(shipment):
    """Cancel a non-terminal shipment and release its RESERVED/COMMITTED allocations."""
    prev_status = shipment["status"]
    if prev_status in ("DELIVERED", "CANCELLED", "SKIPPED"):
        return
    shipment["status"] = "CANCELLED"
    touch(shipment)
    for a in list(db.allocations.values()):
        if a["shipment_id"] == shipment["id"] and a["status"] in ("RESERVED", "COMMITTED"):
            release_allocation(a)


def find_current_cycle_charge(sub):
    """Return the RENEWAL charge for the subscription's current cycle_index, or None."""
    cyc = sub["current_cycle_index"]
    for c in db.charges.values():
        if c["subscription_id"] == sub["id"] and c["cycle_index"] == cyc and c["kind"] == "RENEWAL":
            return c
    return None


def cancellation_refund_estimate(sub):
    """Estimate variant: per_shipment_value * count(current-cycle shipments where status NOT IN {DELIVERED, CANCELLED})."""
    plan = db.plans[sub["plan_id"]]
    psv = calc.per_shipment_value_cents(_effective_renewal_price(sub), plan["cadence"])
    cyc = sub["current_cycle_index"]
    n = 0
    for sh in db.shipments.values():
        if sh["subscription_id"] != sub["id"]:
            continue
        if sh["cycle_index"] != cyc:
            continue
        if sh["status"] in ("DELIVERED", "CANCELLED"):
            continue
        n += 1
    return psv * n, n


def cancellation_refund_actual(sub):
    """Actual variant: per_shipment_value * count(current-cycle shipments where status IN {SCHEDULED, SKIPPED})."""
    plan = db.plans[sub["plan_id"]]
    psv = calc.per_shipment_value_cents(_effective_renewal_price(sub), plan["cadence"])
    cyc = sub["current_cycle_index"]
    n = 0
    for sh in db.shipments.values():
        if sh["subscription_id"] != sub["id"]:
            continue
        if sh["cycle_index"] != cyc:
            continue
        if sh["status"] in ("SCHEDULED", "SKIPPED"):
            n += 1
    return psv * n, n


def _effective_renewal_price(sub):
    """Compute renewal price from current config; used by refund/skip calculations
    so any concurrent config change is reflected."""
    plan = db.plans.get(sub["plan_id"])
    if plan is None:
        return sub.get("renewal_price_cents", 0)
    return calc.renewal_price_cents(
        plan=plan,
        size=sub["size"],
        vase_addon=sub.get("vase_addon", False),
        discount_pct=sub.get("discount_pct", 0),
    )


def create_wallet_entry(customer_id, amount_cents, reason, related_charge_id=None):
    w = {
        **new_common_appendonly(),
        "customer_id": customer_id,
        "amount_cents": int(amount_cents),
        "reason": reason,
        "related_charge_id": related_charge_id,
    }
    db.wallet_entries[w["id"]] = w
    return w


def apply_billing_past_due(sub):
    """billing_status -> PAST_DUE and cancel every current-cycle SCHEDULED shipment.

    A separate side_effect on the SAME transition per SCAFFOLD state_machines.
    """
    sub["billing_status"] = "PAST_DUE"
    cyc = sub["current_cycle_index"]
    for sh in list(db.shipments.values()):
        if sh["subscription_id"] != sub["id"]:
            continue
        if sh["cycle_index"] != cyc:
            continue
        if sh["status"] == "SCHEDULED":
            cancel_shipment_cascade(sh)
