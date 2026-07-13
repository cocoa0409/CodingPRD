"""Warranty: filing, liability, and the remake that begets a lab order (PRD 3.9)."""
from flask import Blueprint, request

import calc
import schema
import store
from auth import authenticate, require_owner
from envelope import array_response, object_response, paginate
from errors import err
from serializers import dump, dump_all

bp = Blueprint("warranty", __name__)

REASONS = ("MANUFACTURER_DEFECT", "CUSTOMER_DAMAGE", "RX_CHANGE")


@bp.post("/warranty-claims")
def create_warranty_claim():
    actor = authenticate("Customer")
    b = schema.body()
    lab_order_id = schema.string_field(b, "lab_order_id")
    customer_id = schema.string_field(b, "customer_id")
    reason = schema.enum_field(b, "reason", REASONS)
    expected_version = schema.int_field(b, "expected_lab_order_version")

    lab = schema.get_lab_order(lab_order_id)
    schema.get_customer(customer_id)
    require_owner(actor, customer_id)

    # Priority 8 -- OCC on the parent lab order's version.
    if expected_version != lab["version"]:
        raise err("ERR_STALE_LAB_ORDER_VERSION")

    # Priority 11 -- the glasses must actually be in the customer's hands.
    if lab["status"] != "DELIVERED" or not lab.get("delivered_at"):
        raise err("ERR_LAB_ORDER_NOT_DELIVERED")

    # Priority 19 -- the warranty window; exactly 365 days is INSIDE it.
    days_since_delivery = store.days_between_floor(
        store.clock_now(), lab["_delivered_at_dt"]
    )
    if days_since_delivery > calc.WARRANTY_WINDOW_DAYS:
        raise err("ERR_WARRANTY_EXPIRED")

    order = store.orders.get(lab["order_id"])
    lens_upcharge = order["lens_upcharge_cents"] if order else 0
    charge = calc.remake_liability(reason, days_since_delivery, lens_upcharge)

    # A new filing supersedes the lab order's existing OPEN claim.
    existing_id = lab["active_warranty_claim_id"]
    if existing_id:
        existing = store.warranty_claims.get(existing_id)
        if existing is not None and existing["status"] == "OPEN":
            existing["status"] = "SUPERSEDED"
            store.touch(existing)

    claim = store.new_record(
        lab_order_id=lab_order_id,
        customer_id=customer_id,
        remake_lab_order_id=None,
        reason=reason,
        status="OPEN",
        customer_charge_cents=charge,
        denial_reason=None,
    )
    store.warranty_claims[claim["id"]] = claim

    lab["active_warranty_claim_id"] = claim["id"]
    store.touch(lab)

    return object_response(dump("warranty_claim", claim), 201)


@bp.get("/warranty-claims/<claim_id>")
def read_warranty_claim(claim_id):
    actor = authenticate("Customer", "StoreAssociate", "PlatformAdmin")
    rec = schema.get_warranty_claim(claim_id)
    require_owner(actor, rec["customer_id"])
    return object_response(dump("warranty_claim", rec))


@bp.get("/warranty-claims")
def list_warranty_claims():
    authenticate("StoreAssociate", "PlatformAdmin")
    items = store.ordered(store.warranty_claims)
    for field in ("lab_order_id", "customer_id", "remake_lab_order_id", "status"):
        value = request.args.get(field)
        if value:
            items = [w for w in items if w[field] == value]
    window, meta = paginate(items)
    return array_response(dump_all("warranty_claim", window), meta)


@bp.post("/warranty-claims/<claim_id>/decide")
def decide_warranty_claim(claim_id):
    authenticate("StoreAssociate")
    b = schema.body()
    decision = schema.enum_field(b, "decision", ("APPROVED", "DENIED"))
    denial_reason = schema.string_field(
        b, "denial_reason", required=(decision == "DENIED"), default=None
    )

    claim = schema.get_warranty_claim(claim_id)
    if claim["status"] != "OPEN":
        raise err("ERR_INVALID_STATE")

    if decision == "DENIED":
        claim["status"] = "DENIED"
        claim["denial_reason"] = denial_reason
        store.touch(claim)
        return object_response(dump("warranty_claim", claim))

    lab = store.lab_orders.get(claim["lab_order_id"])
    remake = store.new_record(
        order_id=lab["order_id"] if lab else None,
        shipped_to_store_id=None,
        active_warranty_claim_id=None,
        status="QUEUED",
        remake_count=0,
        qc_failure_reason=None,
        is_remake=True,
        delivered_at=None,
    )
    store.lab_orders[remake["id"]] = remake

    claim["status"] = "APPROVED"
    claim["remake_lab_order_id"] = remake["id"]
    store.touch(claim)

    return object_response(dump("warranty_claim", claim))
