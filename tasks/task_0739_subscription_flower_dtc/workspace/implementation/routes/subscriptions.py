"""Subscription routes: create, list, get, shipments/charges lists, pause/resume/change/cancel/cancel-preview/renew.

Validation order per PRD §2.9 (fixed priority list):
  auth (10) -> role (20) -> path existence (30) -> body well-formedness (35)
  -> state (40) -> OCC (45) -> ownership (50) -> temporal (55)
  -> resource constraints (60) -> fiscal (65)
"""
from datetime import timedelta
from decimal import Decimal
from flask import Blueprint, request, g

from common import new_common, touch
from errors import (
    ApiError, bad_request, stale_version, invalid_state,
    ERR_CUSTOMER_NOT_FOUND, ERR_PLAN_NOT_FOUND, ERR_SUBSCRIPTION_NOT_FOUND,
    ERR_NOT_OWNER, ERR_BILLING_PAST_DUE, ERR_STALE_VERSION,
)
from middleware import auth_required
import db
from response import created, ok, list_ok
from pagination import parse_pagination, apply_page
from util import iso_now, parse_iso
from services import validators as v
from services import calculations as calc
from services import subscription as svc
from services.views import subscription_view, shipment_view, charge_view

bp = Blueprint("subscriptions", __name__)


def _get_or_404(sid):
    s = db.subscriptions.get(sid)
    if s is None:
        raise ApiError(ERR_SUBSCRIPTION_NOT_FOUND, "subscription not found", 404)
    return s


def _customer_ownership_check(sub):
    """Enforce customer ownership when acting role is Customer."""
    if g.user_role == "Customer" and sub["customer_id"] != g.user_id:
        raise ApiError(ERR_NOT_OWNER, "not owner", 403)


# -------------------- Create --------------------
@bp.route("/subscriptions", methods=["POST"])
@auth_required("Customer", "PlatformAdmin")
def create_subscription():
    body = request.get_json(silent=True) or {}
    v.require_dict(body)
    customer_id = v.require_str(body, "customer_id")
    plan_id = v.require_str(body, "plan_id")
    size = v.require_enum(body, "size", v.SIZE_ENUM)
    style = v.optional_enum(body, "style", v.STYLE_ENUM, default="ROUND")
    vase_addon = v.optional_bool(body, "vase_addon", default=False)
    is_gift = v.optional_bool(body, "is_gift", default=False)
    occasion = v.optional_str(body, "occasion")
    gift_message = v.optional_str(body, "gift_message")
    start_dt, start_str = v.optional_datetime(body, "start_date")

    # Existence
    customer = db.customers.get(customer_id)
    if customer is None:
        raise ApiError(ERR_CUSTOMER_NOT_FOUND, "customer not found", 404)
    plan = db.plans.get(plan_id)
    if plan is None:
        raise ApiError(ERR_PLAN_NOT_FOUND, "plan not found", 404)

    # Customer creating for themselves: ownership check
    if g.user_role == "Customer" and customer_id != g.user_id:
        raise ApiError(ERR_NOT_OWNER, "not owner", 403)

    if start_dt is None:
        start_dt = db.now()
        start_str = iso_now(start_dt)

    sub = {
        **new_common(),
        "customer_id": customer_id,
        "plan_id": plan_id,
        "size": size,
        "style": style,
        "vase_addon": vase_addon,
        "is_gift": is_gift,
        "occasion": occasion,
        "gift_message": gift_message,
        "lifecycle_status": "ACTIVE",
        "billing_status": "CURRENT",
        "current_cycle_index": 1,
        "next_renewal_date": iso_now(start_dt + timedelta(days=calc.CYCLE_DAYS)),
        "discount_pct": 0,
        "renewal_price_cents": 0,  # will be recomputed on read
        "cancel_reason": None,
        "start_date": start_str,
        "paused_until": None,
    }
    db.subscriptions[sub["id"]] = sub

    # Open cycle 1
    svc.open_cycle(sub, start_dt, 1)

    return created(subscription_view(sub))


# -------------------- List --------------------
@bp.route("/subscriptions", methods=["GET"])
@auth_required("Customer", "PlatformAdmin", "BillingAdmin")
def list_subscriptions():
    limit, offset = parse_pagination()
    customer_id = request.args.get("customer_id")
    plan_id = request.args.get("plan_id")
    status_filter = request.args.get("status")

    items = list(db.subscriptions.values())
    if customer_id is not None:
        items = [s for s in items if s["customer_id"] == customer_id]
    if plan_id is not None:
        items = [s for s in items if s["plan_id"] == plan_id]
    if status_filter is not None:
        items = [s for s in items
                 if s.get("lifecycle_status") == status_filter
                 or s.get("billing_status") == status_filter]
    # Customer scope: implicitly restrict to own subscriptions.
    if g.user_role == "Customer":
        items = [s for s in items if s["customer_id"] == g.user_id]
    items.sort(key=lambda s: s["created_at"])
    page, total = apply_page(items, limit, offset)
    return list_ok([subscription_view(s) for s in page], limit, offset, total)


# -------------------- Get --------------------
@bp.route("/subscriptions/<sid>", methods=["GET"])
@auth_required("Customer", "PlatformAdmin", "BillingAdmin")
def get_subscription(sid):
    sub = _get_or_404(sid)
    _customer_ownership_check(sub)
    return ok(subscription_view(sub))


# -------------------- Nested lists --------------------
@bp.route("/subscriptions/<sid>/shipments", methods=["GET"])
@auth_required("Customer", "FulfillmentOps", "PlatformAdmin")
def list_sub_shipments(sid):
    limit, offset = parse_pagination()
    sub = _get_or_404(sid)
    _customer_ownership_check(sub)

    status_filter = request.args.get("status")
    cycle_filter = request.args.get("cycle_index")
    if cycle_filter is not None:
        try:
            cycle_filter = int(cycle_filter)
        except ValueError:
            raise bad_request("cycle_index must be an integer")

    items = [sh for sh in db.shipments.values() if sh["subscription_id"] == sid]
    if status_filter is not None:
        items = [sh for sh in items if sh["status"] == status_filter]
    if cycle_filter is not None:
        items = [sh for sh in items if sh["cycle_index"] == cycle_filter]
    # (cycle_index, scheduled_delivery_date, created_at) asc — per §1.5.
    items.sort(key=lambda sh: (sh["cycle_index"], sh["scheduled_delivery_date"], sh["created_at"]))
    page, total = apply_page(items, limit, offset)
    return list_ok([shipment_view(sh) for sh in page], limit, offset, total)


@bp.route("/subscriptions/<sid>/charges", methods=["GET"])
@auth_required("Customer", "BillingAdmin")
def list_sub_charges(sid):
    limit, offset = parse_pagination()
    sub = _get_or_404(sid)
    _customer_ownership_check(sub)

    status_filter = request.args.get("status")
    items = [c for c in db.charges.values() if c["subscription_id"] == sid]
    if status_filter is not None:
        items = [c for c in items if c["status"] == status_filter]
    items.sort(key=lambda c: (c["cycle_index"], c["created_at"]))
    page, total = apply_page(items, limit, offset)
    return list_ok([charge_view(c) for c in page], limit, offset, total)


# -------------------- Pause / Resume --------------------
@bp.route("/subscriptions/<sid>/pause", methods=["POST"])
@auth_required("Customer")
def pause_subscription(sid):
    sub = _get_or_404(sid)
    body = request.get_json(silent=True) or {}
    v.require_dict(body)
    resume_dt, resume_str = v.optional_datetime(body, "resume_date")

    # State (40)
    if sub["lifecycle_status"] != "ACTIVE":
        raise invalid_state("subscription is not ACTIVE")
    # Ownership (50)
    _customer_ownership_check(sub)

    sub["lifecycle_status"] = "PAUSED"
    if resume_str is not None:
        sub["paused_until"] = resume_str
    touch(sub)
    return ok(subscription_view(sub))


@bp.route("/subscriptions/<sid>/resume", methods=["POST"])
@auth_required("Customer")
def resume_subscription(sid):
    sub = _get_or_404(sid)

    if sub["lifecycle_status"] != "PAUSED":
        raise invalid_state("subscription is not PAUSED")
    _customer_ownership_check(sub)

    sub["lifecycle_status"] = "ACTIVE"
    sub["paused_until"] = None
    touch(sub)
    return ok(subscription_view(sub))


# -------------------- Change (OCC) --------------------
@bp.route("/subscriptions/<sid>/change", methods=["POST"])
@auth_required("Customer")
def change_subscription(sid):
    sub = _get_or_404(sid)
    body = request.get_json(silent=True) or {}
    v.require_dict(body)

    # Well-formedness (35): expected_subscription_version required.
    if "expected_subscription_version" not in body or body["expected_subscription_version"] is None:
        raise bad_request("missing required field 'expected_subscription_version'")
    ev = body["expected_subscription_version"]
    if isinstance(ev, bool) or not isinstance(ev, int):
        raise bad_request("'expected_subscription_version' must be an integer")

    # Validate optional fields at well-formedness level.
    new_size = v.optional_enum(body, "size", v.SIZE_ENUM)
    new_style = v.optional_enum(body, "style", v.STYLE_ENUM)
    new_vase = None
    if "vase_addon" in body and body["vase_addon"] is not None:
        new_vase = v.optional_bool(body, "vase_addon")
    new_plan_id = v.optional_str(body, "plan_id")
    if new_plan_id is not None and db.plans.get(new_plan_id) is None:
        raise ApiError(ERR_PLAN_NOT_FOUND, "plan not found", 404)

    # State (40): lifecycle must be ACTIVE or PAUSED (not CANCELLED/EXPIRED).
    if sub["lifecycle_status"] not in ("ACTIVE", "PAUSED"):
        raise invalid_state("subscription is not modifiable")

    # OCC (45) — before ownership per PRD §2.9.
    if ev != sub["version"]:
        raise stale_version()

    # Ownership (50)
    _customer_ownership_check(sub)

    # Fiscal (65)
    if sub.get("billing_status") == "PAST_DUE":
        raise ApiError(ERR_BILLING_PAST_DUE, "subscription is past due", 402)

    # Apply.
    if new_size is not None:
        sub["size"] = new_size
    if new_style is not None:
        sub["style"] = new_style
    if new_vase is not None:
        sub["vase_addon"] = new_vase
    if new_plan_id is not None:
        sub["plan_id"] = new_plan_id

    # Recompute renewal_price_cents (persisted for symmetry with next_renewal snapshot).
    plan = db.plans[sub["plan_id"]]
    sub["renewal_price_cents"] = calc.renewal_price_cents(
        plan=plan, size=sub["size"], vase_addon=sub.get("vase_addon", False),
        discount_pct=sub.get("discount_pct", 0),
    )
    touch(sub)
    return ok(subscription_view(sub))


# -------------------- Cancel --------------------
@bp.route("/subscriptions/<sid>/cancel", methods=["POST"])
@auth_required("Customer")
def cancel_subscription(sid):
    sub = _get_or_404(sid)
    body = request.get_json(silent=True) or {}
    v.require_dict(body)

    reason = v.optional_str(body, "reason")
    refund_destination = v.optional_enum(body, "refund_destination",
                                         v.REFUND_DESTINATION_ENUM)

    # State (40)
    if sub["lifecycle_status"] not in ("ACTIVE", "PAUSED"):
        raise invalid_state("subscription not cancellable")

    # Ownership (50)
    _customer_ownership_check(sub)

    # Compute actual refund BEFORE cascading (actual variant uses statuses as they
    # stood immediately before cancellation, i.e. counts SCHEDULED and SKIPPED).
    refund_cents, _ = svc.cancellation_refund_actual(sub)

    # Cascade: cancel non-terminal shipments and release their allocations/lots.
    for sh in list(db.shipments.values()):
        if sh["subscription_id"] != sid:
            continue
        if sh["status"] in ("SCHEDULED", "SOURCING", "SOURCED", "SUBSTITUTED"):
            svc.cancel_shipment_cascade(sh)

    # Refund via wallet + bump matching CAPTURED charge.
    if refund_destination == "WALLET" and refund_cents > 0:
        renewal_charge = svc.find_current_cycle_charge(sub)
        related_charge_id = None
        if renewal_charge is not None and renewal_charge["status"] == "CAPTURED":
            cap_room = int(renewal_charge["amount_cents"]) - int(renewal_charge.get("refunded_cents", 0))
            applied = min(refund_cents, cap_room) if cap_room > 0 else 0
            if applied > 0:
                renewal_charge["refunded_cents"] = int(renewal_charge.get("refunded_cents", 0)) + applied
                if renewal_charge["refunded_cents"] >= renewal_charge["amount_cents"]:
                    renewal_charge["status"] = "REFUNDED"
                touch(renewal_charge)
                related_charge_id = renewal_charge["id"]
        # Always credit the full computed refund to the wallet (money conservation
        # applies to the wallet ledger; the Charge cap is a separate check).
        svc.create_wallet_entry(
            customer_id=sub["customer_id"],
            amount_cents=refund_cents,
            reason="REFUND",
            related_charge_id=related_charge_id,
        )

    # Create win-back offer.
    from services.calculations import WINBACK_DISCOUNT_PCT, WINBACK_WINDOW_DAYS
    expires_dt = db.now() + timedelta(days=WINBACK_WINDOW_DAYS)
    offer = {
        **new_common(),
        "customer_id": sub["customer_id"],
        "discount_pct": float(WINBACK_DISCOUNT_PCT),
        "expires_at": iso_now(expires_dt),
        "status": "OFFERED",
    }
    db.win_back_offers[offer["id"]] = offer

    # Finalize subscription state.
    sub["lifecycle_status"] = "CANCELLED"
    if reason is not None:
        sub["cancel_reason"] = reason
    touch(sub)
    return ok(subscription_view(sub))


# -------------------- Cancel-preview --------------------
@bp.route("/subscriptions/<sid>/cancel-preview", methods=["GET"])
@auth_required("Customer")
def cancel_preview(sid):
    sub = _get_or_404(sid)
    _customer_ownership_check(sub)
    est, n = svc.cancellation_refund_estimate(sub)
    return ok({
        "estimated_refund_cents": est,
        "refundable_shipment_count": n,
    })


# -------------------- Renew --------------------
@bp.route("/subscriptions/<sid>/renew", methods=["POST"])
@auth_required("BillingAdmin")
def renew_subscription(sid):
    sub = _get_or_404(sid)

    # State (40): renewal only meaningful while lifecycle ACTIVE or PAUSED.
    if sub["lifecycle_status"] not in ("ACTIVE", "PAUSED"):
        raise invalid_state("subscription not renewable")

    plan = db.plans[sub["plan_id"]]

    # PRD §3.7: increment cycle_index, advance next_renewal_date by CYCLE_DAYS,
    # recompute renewal_price_cents (using current discount_pct), then reset
    # discount_pct to 0 — in that order, so the discount lands on exactly this
    # renewal charge and is cleared for future cycles.
    sub["current_cycle_index"] = int(sub["current_cycle_index"]) + 1
    cycle_start = parse_iso(sub["next_renewal_date"])
    sub["next_renewal_date"] = iso_now(cycle_start + timedelta(days=calc.CYCLE_DAYS))

    # 3) recompute price at current (still-discounted) config -> stamped on the charge.
    sub["renewal_price_cents"] = calc.renewal_price_cents(
        plan=plan, size=sub["size"], vase_addon=sub.get("vase_addon", False),
        discount_pct=sub.get("discount_pct", 0),
    )

    # open_cycle will use this configuration (calls calc.renewal_price_cents
    # with the same inputs) to stamp Charge.amount_cents. Do this BEFORE resetting
    # discount_pct so the discount is applied to the new charge.
    svc.open_cycle(sub, cycle_start, sub["current_cycle_index"])

    # 4) reset discount for subsequent cycles.
    sub["discount_pct"] = 0
    touch(sub)
    return created(subscription_view(sub))
