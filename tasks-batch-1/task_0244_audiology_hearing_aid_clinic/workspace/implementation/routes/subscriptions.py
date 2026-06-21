"""Supply subscription + supply cycle endpoints."""

from flask import Blueprint, request

from db import db
import serialize
import validate
import errors
from clock import clock
from timeutil import now_iso, parse_iso, add_days
from middleware import require_auth, require_role, require_ownership, get_json_body
from response import object_response, array_response
from services.domain import get_or_404, append_ledger
from services.listing import list_page
from services import calculations as calc

bp = Blueprint("subscriptions", __name__)

CADENCES = {30, 60, 90}


# ===========================================================================
# Subscription creation + reads
# ===========================================================================
@bp.post("/clinic/subscriptions")
def create_subscription():
    auth = require_auth()
    require_role(auth, {"BillingClerk", "Patient"})
    body = get_json_body()
    patient_id = validate.require_str(body, "patient_id")
    fitting_order_id = validate.require_str(body, "fitting_order_id")
    cadence_days = validate.require_in_set(body, "cadence_days", CADENCES)
    unit_price = validate.require_int(body, "unit_price_cents", minimum=1)

    # A Patient may only create a subscription for their own patient_id.
    require_ownership(auth, patient_id)

    # Body FK existence.
    get_or_404(db.patients, patient_id)
    order = get_or_404(db.orders, fitting_order_id)

    with db.lock:
        # The supplied device's order must be PURCHASED or WARRANTY_ACTIVE.
        if order["status"] not in ("PURCHASED", "WARRANTY_ACTIVE"):
            raise errors.invalid_state("Order is not PURCHASED or WARRANTY_ACTIVE.")

        now = clock.now()
        sub = {
            "patient_id": patient_id,
            "fitting_order_id": fitting_order_id,
            "cadence_days": cadence_days,
            "unit_price_cents": unit_price,
            "started_at": now_iso(now),
            "cycles_fulfilled": 0,
            "lifetime_billed_cents": 0,
            "status": "ACTIVE",
        }
        db.stamp_create(sub)
        db.subscriptions[sub["id"]] = sub

        # Schedule the first cycle (cycle_index 1).
        _create_cycle(sub, 1)
    return object_response(serialize.subscription(sub), 201)


@bp.get("/clinic/subscriptions/<sid>")
def get_subscription(sid):
    auth = require_auth()
    require_role(auth, {"BillingClerk", "ClinicAdmin", "Patient"})
    sub = get_or_404(db.subscriptions, sid)
    require_ownership(auth, sub["patient_id"])
    return object_response(serialize.subscription(sub))


@bp.get("/clinic/subscriptions")
def list_subscriptions():
    auth = require_auth()
    require_role(auth, {"BillingClerk", "ClinicAdmin"})
    a = request.args
    fitting_order_id = a.get("fitting_order_id")
    patient_id = a.get("patient_id")
    status = a.get("status")
    items = [s for s in db.subscriptions.values()
             if (fitting_order_id is None or s["fitting_order_id"] == fitting_order_id)
             and (patient_id is None or s["patient_id"] == patient_id)
             and (status is None or s["status"] == status)]
    page, limit, offset, total = list_page(a, items, serialize.subscription)
    return array_response(page, limit, offset, total)


# ===========================================================================
# Subscription lifecycle (Patient-owned)
# ===========================================================================
@bp.post("/clinic/subscriptions/<sid>/pause")
def pause_subscription(sid):
    auth = require_auth()
    require_role(auth, {"Patient"})
    with db.lock:
        sub = get_or_404(db.subscriptions, sid)
        require_ownership(auth, sub["patient_id"])
        if sub["status"] != "ACTIVE":
            raise errors.invalid_state("Only an ACTIVE subscription may be paused.")
        sub["status"] = "PAUSED"
        db.touch(sub)
    return object_response(serialize.subscription(sub))


@bp.post("/clinic/subscriptions/<sid>/resume")
def resume_subscription(sid):
    auth = require_auth()
    require_role(auth, {"Patient"})
    with db.lock:
        sub = get_or_404(db.subscriptions, sid)
        require_ownership(auth, sub["patient_id"])
        if sub["status"] != "PAUSED":
            raise errors.invalid_state("Only a PAUSED subscription may be resumed.")
        sub["status"] = "ACTIVE"
        db.touch(sub)
    return object_response(serialize.subscription(sub))


@bp.post("/clinic/subscriptions/<sid>/cancel")
def cancel_subscription(sid):
    auth = require_auth()
    require_role(auth, {"Patient"})
    with db.lock:
        sub = get_or_404(db.subscriptions, sid)
        require_ownership(auth, sub["patient_id"])
        if sub["status"] not in ("ACTIVE", "PAUSED"):
            raise errors.invalid_state("Subscription cannot be cancelled from its current state.")
        sub["status"] = "CANCELLED"
        db.touch(sub)
        # Conditional cascade: roll SCHEDULED cycles -> SKIPPED.
        for cyc in db.supply_cycles.values():
            if cyc["subscription_id"] == sub["id"] and cyc["status"] == "SCHEDULED":
                cyc["status"] = "SKIPPED"
                db.touch(cyc)
    return object_response(serialize.subscription(sub))


# ===========================================================================
# Supply cycle scheduling + listing
# ===========================================================================
@bp.post("/clinic/subscriptions/<sid>/cycles")
def schedule_cycle(sid):
    auth = require_auth()
    require_role(auth, {"BillingClerk", "ClinicAdmin"})
    with db.lock:
        sub = get_or_404(db.subscriptions, sid)
        next_index = 1 + max(
            [c["cycle_index"] for c in db.supply_cycles.values() if c["subscription_id"] == sid],
            default=0,
        )
        cyc = _create_cycle(sub, next_index)
    return object_response(serialize.supply_cycle(cyc), 201)


@bp.get("/clinic/subscriptions/<sid>/cycles")
def list_cycles(sid):
    auth = require_auth()
    require_role(auth, {"BillingClerk", "ClinicAdmin", "Patient"})
    sub = get_or_404(db.subscriptions, sid)
    require_ownership(auth, sub["patient_id"])
    status = request.args.get("status")
    items = [c for c in db.supply_cycles.values()
             if c["subscription_id"] == sid and (status is None or c["status"] == status)]
    page, limit, offset, total = list_page(request.args, items, serialize.supply_cycle)
    return array_response(page, limit, offset, total)


@bp.get("/clinic/supply-cycles/<cid>")
def get_cycle(cid):
    auth = require_auth()
    require_role(auth, {"BillingClerk", "ClinicAdmin", "Patient"})
    cyc = get_or_404(db.supply_cycles, cid)
    sub = db.subscriptions.get(cyc["subscription_id"])
    require_ownership(auth, sub["patient_id"] if sub else None)
    return object_response(serialize.supply_cycle(cyc))


@bp.post("/clinic/supply-cycles/<cid>/ship")
def ship_cycle(cid):
    auth = require_auth()
    require_role(auth, {"ClinicAdmin"})
    with db.lock:
        cyc = get_or_404(db.supply_cycles, cid)
        if cyc["status"] != "SCHEDULED":
            raise errors.invalid_state("Only a SCHEDULED cycle may be shipped.")
        sub = db.subscriptions.get(cyc["subscription_id"])
        if sub is None:
            raise errors.not_found()
        if sub["status"] != "ACTIVE":
            raise errors.invalid_state("Parent subscription is not ACTIVE.")

        now = clock.now()
        due = parse_iso(cyc["due_at"])
        if due is not None and now < due:
            raise errors.ApiError(errors.ERR_CYCLE_NOT_DUE, 422, "Cycle is not yet due.")

        billed = calc.supply_cycle_billing(cyc["cycle_index"], sub["unit_price_cents"])
        cyc["billed_cents"] = billed
        cyc["status"] = "SHIPPED"
        db.touch(cyc)

        # Ledger: SUPPLY_BILLING amount = +billed.
        append_ledger(sub["patient_id"], "SUPPLY_BILLING", cyc["id"], billed,
                      "Supply cycle billing")

        # Cascade: recompute subscription cycles_fulfilled + lifetime_billed_cents.
        _recompute_subscription_totals(sub)
    return object_response(serialize.supply_cycle(cyc))


@bp.post("/clinic/supply-cycles/<cid>/skip")
def skip_cycle(cid):
    auth = require_auth()
    require_role(auth, {"ClinicAdmin", "Patient"})
    with db.lock:
        cyc = get_or_404(db.supply_cycles, cid)
        sub = db.subscriptions.get(cyc["subscription_id"])
        # Patient may only skip a cycle under their own subscription.
        require_ownership(auth, sub["patient_id"] if sub else None)
        if cyc["status"] != "SCHEDULED":
            raise errors.invalid_state("Only a SCHEDULED cycle may be skipped.")
        cyc["status"] = "SKIPPED"
        db.touch(cyc)
    return object_response(serialize.supply_cycle(cyc))


# --- helpers ----------------------------------------------------------------
def _create_cycle(sub, cycle_index):
    """Create a SCHEDULED cycle with due_at = started_at + index*cadence days."""
    started = parse_iso(sub["started_at"])
    due = add_days(started, cycle_index * sub["cadence_days"])
    cyc = {
        "subscription_id": sub["id"],
        "cycle_index": cycle_index,
        "due_at": now_iso(due),
        "billed_cents": None,
        "status": "SCHEDULED",
    }
    db.stamp_create(cyc)
    db.supply_cycles[cyc["id"]] = cyc
    return cyc


def _recompute_subscription_totals(sub):
    """Recompute cycles_fulfilled (# SHIPPED) and lifetime_billed_cents (sum of
    SHIPPED billed_cents) then bump the subscription (cascade hop)."""
    shipped = [c for c in db.supply_cycles.values()
               if c["subscription_id"] == sub["id"] and c["status"] == "SHIPPED"]
    sub["cycles_fulfilled"] = len(shipped)
    sub["lifetime_billed_cents"] = sum(c.get("billed_cents") or 0 for c in shipped)
    db.touch(sub)
