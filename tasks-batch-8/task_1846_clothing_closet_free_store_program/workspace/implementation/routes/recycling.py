"""Textile recycling: batches, sweep, seal, pickup (PRD 3.9)."""
from decimal import Decimal

from flask import Blueprint, g

import services as svc
from db import stamp_new, store, touch
from errors import ApiError, invalid_state, not_found
from middleware import require_roles
from response import ok
from util import get_body, v_num, v_str

bp = Blueprint("recycling", __name__)


def get_batch_or_404(batch_id):
    b = store.recycling.get(batch_id)
    if b is None:
        raise not_found("Recycling batch not found")
    return b


@bp.post("/closet/recycling-batches")
@require_roles("ProgramAdmin")
def create_batch():
    data = get_body()
    recycler_name = v_str(data, "recycler_name")
    capacity_kg = v_num(data, "capacity_kg", gt=Decimal("0"))
    b = stamp_new({
        "recycler_name": recycler_name,
        "capacity_kg": capacity_kg,
        "status": "ACCUMULATING",
        "provisional_credit_cents": None,
        "actual_weight_kg": None,
        "final_credit_cents": None,
        "sealed_by_user_id": None,
        "picked_up_by_user_id": None,
    })
    store.recycling[b["id"]] = b
    return ok(svc.serialize_recycling(b), 201)


@bp.get("/closet/recycling-batches/<bid>")
@require_roles("ProgramAdmin", "VolunteerLead", "Volunteer")
def get_batch(bid):
    return ok(svc.serialize_recycling(get_batch_or_404(bid)))


@bp.post("/closet/recycling-batches/<bid>/sweep")
@require_roles("ProgramAdmin")
def sweep(bid):
    b = get_batch_or_404(bid)
    if b["status"] != "ACCUMULATING":
        raise invalid_state("Only an ACCUMULATING batch can sweep items")
    running = svc.est_weight_total(svc.recycling_items(bid))
    candidates = sorted(
        (
            i for i in store.items.values()
            if i["status"] == "REJECTED" and i["recycling_batch_id"] is None
        ),
        key=lambda i: (i["created_at"], i["_seq"]),
    )
    for item in candidates:
        w = svc.est_weight_of(item)
        # Stop at the first candidate that would exceed capacity; never skip
        # ahead to a lighter item.
        if running + w > b["capacity_kg"]:
            break
        item["recycling_batch_id"] = b["id"]
        touch(item)
        running += w
    return ok(svc.serialize_recycling(b))


@bp.post("/closet/recycling-batches/<bid>/seal")
@require_roles("ProgramAdmin")
def seal(bid):
    b = get_batch_or_404(bid)
    if b["status"] != "ACCUMULATING":
        raise invalid_state("Only an ACCUMULATING batch can be sealed")
    items = sorted(
        svc.recycling_items(bid), key=lambda i: (i["created_at"], i["_seq"])
    )
    if len(items) < 1:
        raise ApiError(
            "ERR_RECYCLING_EMPTY", 409, "Seal requires at least one assigned item"
        )
    b["provisional_credit_cents"] = svc.provisional_credit_cents(items)
    for item in items:
        if item["status"] == "REJECTED":
            item["status"] = "RECYCLED"
            touch(item)
    b["sealed_by_user_id"] = g.user_id
    b["status"] = "SEALED"
    touch(b)
    return ok(svc.serialize_recycling(b))


@bp.post("/closet/recycling-batches/<bid>/pickup")
@require_roles("ProgramAdmin")
def pickup(bid):
    b = get_batch_or_404(bid)
    data = get_body()
    # PRD 3.9 pins this order: weight validation, then state, then SoD.
    actual = v_num(data, "actual_weight_kg", gt=Decimal("0"))
    if b["status"] != "SEALED":
        raise invalid_state("Only a SEALED batch can be picked up")
    if b["sealed_by_user_id"] == g.user_id:
        raise ApiError(
            "ERR_SOD_SEALER_CANNOT_PICKUP", 409,
            "The operator who sealed the batch cannot record its pickup",
        )
    b["actual_weight_kg"] = actual
    b["final_credit_cents"] = svc.final_credit_cents(actual)
    b["picked_up_by_user_id"] = g.user_id
    b["status"] = "PICKED_UP"
    touch(b)
    return ok(svc.serialize_recycling(b))
