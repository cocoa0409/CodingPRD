from decimal import Decimal

from flask import Blueprint

import db
import response
import serializers
import services.cascade as cascade
from errors import raise_err
from middleware import require_roles
from routes._common import as_decimal, as_dt, as_enum, body, opt_field, req_field
from services.calc import (
    D,
    LOSS_DECLARED_PCT,
    allocate_loss,
    resurvey_loss,
    table_rate_loss,
)

bp = Blueprint("loss_events", __name__)

METHODS = {"TABLE_RATE", "RESURVEY"}


@bp.post("/api/loss-events")
def create_loss_event():
    require_roles(["STATION_OPERATOR"])
    data = body()
    pile_id = req_field(data, "pile_id")
    method = as_enum(req_field(data, "method"), "method", METHODS)
    survey_at = as_dt(req_field(data, "survey_at"), "survey_at")
    ws = as_dt(req_field(data, "window_start"), "window_start")
    we = as_dt(req_field(data, "window_end"), "window_end")
    measured = opt_field(data, "measured_remaining_lbs", None)
    if measured is not None:
        measured = as_decimal(measured, "measured_remaining_lbs")

    pile = db.piles.get(pile_id)
    if not pile:
        raise_err("ERR_NOT_FOUND", "Pile not found")
    if pile["fill_status"] != "SEALED":
        raise_err("ERR_INVALID_STATE", "Pile must be SEALED to create a loss event")
    if method == "RESURVEY" and measured is None:
        raise_err("ERR_INVALID_REQUEST", "measured_remaining_lbs is required for RESURVEY")

    e = db.stamp_new({
        "pile_id": pile_id,
        "method": method,
        "survey_at": survey_at,
        "window_start": ws,
        "window_end": we,
        "measured_remaining_lbs": measured,
        "loss_lbs": None,
        "unallocated_lbs": None,
        "status": "DRAFT",
    })
    db.loss_events[e["id"]] = e
    return response.success(serializers.loss_event(e), 201)


def _prior_confirmed_loss(pile_id, exclude_id):
    total = Decimal("0")
    for x in db.loss_events.values():
        if x["pile_id"] == pile_id and x["id"] != exclude_id and x["status"] in ("CONFIRMED", "ALLOCATED"):
            total += D(x["loss_lbs"] or 0)
    return total


def _recompute_pile_condition(pile):
    """Apply condition transitions per SCAFFOLD StoragePile.condition_status."""
    if pile["sealed_stored_lbs"] is None:
        return
    sealed = D(pile["sealed_stored_lbs"])
    if sealed <= 0:
        return
    cumulative = Decimal("0")
    for x in db.loss_events.values():
        if x["pile_id"] == pile["id"] and x["status"] in ("CONFIRMED", "ALLOCATED"):
            cumulative += D(x["loss_lbs"] or 0)
    threshold = sealed * LOSS_DECLARED_PCT / Decimal("100")
    if cumulative > threshold:
        new_status = "LOSS_DECLARED"
    elif cumulative > 0:
        new_status = "DETERIORATING"
    else:
        new_status = "SOUND"
    if new_status != pile["condition_status"]:
        pile["condition_status"] = new_status
        db.touch(pile)


@bp.post("/api/loss-events/<loss_event_id>/confirm")
def confirm_loss_event(loss_event_id):
    require_roles(["STATION_OPERATOR"])
    e = db.loss_events.get(loss_event_id)
    if not e:
        raise_err("ERR_NOT_FOUND", "Loss event not found")
    if e["status"] != "DRAFT":
        raise_err("ERR_INVALID_STATE", "Loss event is not DRAFT")
    pile = db.piles.get(e["pile_id"])
    if pile["fill_status"] != "SEALED":
        raise_err("ERR_INVALID_STATE", "Pile must be SEALED at confirm")

    if e["method"] == "TABLE_RATE":
        loss = table_rate_loss(pile["sealed_stored_lbs"], pile["sealed_at"], e["survey_at"])
    else:  # RESURVEY
        if e["measured_remaining_lbs"] is None:
            raise_err("ERR_MEASURED_WEIGHT_INVALID", "measured_remaining_lbs is required for RESURVEY")
        if D(e["measured_remaining_lbs"]) < 0:
            raise_err("ERR_MEASURED_WEIGHT_INVALID", "measured_remaining_lbs must be >= 0")
        prior = _prior_confirmed_loss(e["pile_id"], e["id"])
        loss = resurvey_loss(pile["sealed_stored_lbs"], prior, e["measured_remaining_lbs"])
        if loss < 0:
            raise_err("ERR_MEASURED_WEIGHT_INVALID", "Computed loss would be negative")

    e["loss_lbs"] = loss
    e["status"] = "CONFIRMED"
    db.touch(e)
    _recompute_pile_condition(pile)
    return response.success(serializers.loss_event(e), 200)


@bp.post("/api/loss-events/<loss_event_id>/allocate")
def allocate_loss_event(loss_event_id):
    require_roles(["POOL_ACCOUNTANT"])
    e = db.loss_events.get(loss_event_id)
    if not e:
        raise_err("ERR_NOT_FOUND", "Loss event not found")
    if e["status"] != "CONFIRMED":
        raise_err("ERR_INVALID_STATE", "Loss event is not CONFIRMED")
    pile = db.piles.get(e["pile_id"])

    allocations = [a for a in db.pile_allocations.values() if a["pile_id"] == pile["id"]]
    distributed, shares = allocate_loss(e["loss_lbs"], allocations)

    member_loss = {}
    for a in allocations:
        share = shares.get(a["id"])
        if share is None:
            continue
        a["remaining_lbs"] = D(a["remaining_lbs"]) - share
        db.touch(a)
        member_loss[a["member_id"]] = member_loss.get(a["member_id"], Decimal("0")) + share

    for mid, amt in member_loss.items():
        m = db.members.get(mid)
        if m:
            m["deterioration_loss_lbs"] = D(m["deterioration_loss_lbs"] or 0) + amt
            db.touch(m)

    e["unallocated_lbs"] = D(e["loss_lbs"]) - distributed
    e["status"] = "ALLOCATED"
    db.touch(e)

    cascade.recompute_pile_stored(pile["id"])
    db.touch(pile)
    cascade.recompute_station(pile["station_id"])

    return response.success(serializers.loss_event(e), 200)
