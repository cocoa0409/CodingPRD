"""Subscription plans (PRD 3.1)."""

from flask import Blueprint

import auth
import constants as K
import envelope
import listing
import lookup
import serialize
import shape
import store

bp = Blueprint("plans", __name__)

ALL_ROLES = tuple(K.ROLES)


@bp.post("/kidswear/plans")
def create_plan():
    auth.gate("PlatformAdmin")
    body = shape.body_json()
    tier = shape.enum_in(body, "tier", K.PLAN_TIERS)
    slots_per_box = shape.integer(body, "slots_per_box", minimum=1, maximum=8)
    swaps_per_cycle = shape.integer(body, "swaps_per_cycle", minimum=0, maximum=6)
    monthly_fee_cents = shape.integer(body, "monthly_fee_cents", minimum=0)
    protection_available = shape.boolean(body, "protection_available", required=False, default=True)
    proration_basis = shape.enum_in(body, "proration_basis", K.PRORATION_BASES,
                                    required=False, default="THIRTY_DAY")
    late_fee_mode = shape.enum_in(body, "late_fee_mode", K.LATE_FEE_MODES,
                                  required=False, default="PER_DAY")
    capsule_quota = shape.integer(body, "capsule_quota_per_wave", required=False, default=2,
                                  minimum=0, maximum=6)
    discount_pct = shape.number(body, "discount_pct", required=False, default=0,
                                minimum=0, maximum=0.50)
    row = store.insert("plans", {
        "tier": tier,
        "slots_per_box": slots_per_box,
        "swaps_per_cycle": swaps_per_cycle,
        "monthly_fee_cents": monthly_fee_cents,
        "protection_available": protection_available,
        "proration_basis": proration_basis,
        "late_fee_mode": late_fee_mode,
        "capsule_quota_per_wave": capsule_quota,
        "discount_pct": discount_pct,
        "status": "ACTIVE",
    })
    return envelope.created(serialize.plan(row))


@bp.get("/kidswear/plans")
def list_plans():
    auth.gate(*ALL_ROLES)
    rows = store.all_rows("plans")
    rows = listing.eq(rows, "tier", shape.query_member("tier", K.PLAN_TIERS))
    rows = listing.eq(rows, "status", shape.query_member("status", K.PLAN_STATUSES))
    return envelope.listing(rows, serialize.plan)


@bp.get("/kidswear/plans/<plan_id>")
def read_plan(plan_id):
    auth.gate("PlatformAdmin", "Member", "BillingAgent", "MerchandisePlanner")
    row = lookup.plan(plan_id)
    return envelope.ok(serialize.plan(row))


@bp.patch("/kidswear/plans/<plan_id>")
def update_plan(plan_id):
    auth.gate("PlatformAdmin")
    body = shape.body_json()
    discount_pct = shape.number(body, "discount_pct", required=False, default=None,
                                minimum=0, maximum=0.50)
    status = shape.member_in(body, "status", K.PLAN_STATUSES, required=False, default=None)
    row = lookup.plan(plan_id)
    if discount_pct is not None:
        row["discount_pct"] = discount_pct
    if status is not None:
        row["status"] = status
    store.touch(row)
    return envelope.ok(serialize.plan(row))
