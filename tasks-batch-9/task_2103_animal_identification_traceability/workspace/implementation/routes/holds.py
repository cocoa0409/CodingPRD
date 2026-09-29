"""Quarantine holds, appeals and the investigation cascade (PRD 3.6)."""
from datetime import timedelta

from flask import Blueprint

import derive
import shape
from authz import PRODUCER, PROGRAM_ADMIN, STATE_OFFICIAL, require_owner, require_roles
from db import base_record, store, touch
from errors import conflict, invalid_state, stale_version, unprocessable
from respond import success
from routes._common import hold_or_404, page, premises_or_404, trace_or_404
from serialize import public

bp = Blueprint("holds", __name__)

COOLDOWN = timedelta(hours=72)
LIVE_HOLD_STATES = ("PROPOSED", "ACTIVE", "UNDER_APPEAL")


@bp.post("/hold-orders")
def propose_hold():
    uid, role = require_roles(STATE_OFFICIAL)
    body = shape.body()
    premises_id = shape.s_str(body, "premises_id")
    effective_from = shape.s_instant(body, "effective_from")
    effective_until = shape.s_instant(body, "effective_until")
    expected_version = shape.s_int(body, "expected_premises_version")
    trace_request_id = shape.s_str(body, "trace_request_id", required=False)
    premises = premises_or_404(premises_id)
    if trace_request_id is not None:
        trace_or_404(trace_request_id)
    # Band 9 - optimistic concurrency on the parent premises.
    if expected_version != premises["version"]:
        raise stale_version("expected_premises_version does not match the premises version")
    # Band 12 - regulatory interval safety: cooldown, then window overlap.
    last_release = premises["last_hold_released_at"]
    if last_release is not None and effective_from < last_release + COOLDOWN:
        raise conflict("ERR_HOLD_COOLDOWN_ACTIVE",
                       "The premises is inside the 72-hour hold cooldown")
    for hold in store.hold_orders.values():
        if hold["premises_id"] != premises["id"] or hold["status"] not in LIVE_HOLD_STATES:
            continue
        if effective_from < hold["effective_until"] and hold["effective_from"] < effective_until:
            raise conflict("ERR_HOLD_WINDOW_OVERLAP",
                           "The hold window intersects an existing hold on this premises")
    # Band 13 - the window must be non-degenerate.
    if effective_until <= effective_from:
        raise unprocessable("ERR_INVALID_WINDOW",
                            "effective_until must be strictly later than effective_from")

    rec = base_record()
    rec.update({
        "premises_id": premises["id"],
        "trace_request_id": trace_request_id,
        "effective_from": effective_from,
        "effective_until": effective_until,
        "status": "PROPOSED",
        "issued_by_user_id": uid,
        "appeal_count": 0,
        "released_at": None,
    })
    store.hold_orders[rec["id"]] = rec
    derive.recompute_premises_pending_hold_count(premises)
    touch(premises)
    return success(public(rec), status=201)


@bp.get("/hold-orders/<hold_id>")
def read_hold(hold_id):
    require_roles(STATE_OFFICIAL, PRODUCER, PROGRAM_ADMIN)
    return success(public(hold_or_404(hold_id)))


@bp.get("/hold-orders")
def list_holds():
    require_roles(STATE_OFFICIAL, PRODUCER, PROGRAM_ADMIN)
    limit, offset = shape.pagination_params()
    rows = list(store.hold_orders.values())
    for field in ("premises_id", "trace_request_id", "status"):
        value = shape.q(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    return page(rows, limit, offset)


@bp.post("/hold-orders/<hold_id>/activate")
def activate_hold(hold_id):
    require_roles(STATE_OFFICIAL)
    hold = hold_or_404(hold_id)
    # Band 10 - own-state gate.
    if hold["status"] != "PROPOSED":
        raise invalid_state("Only a PROPOSED hold may be activated")
    premises = store.premises.get(hold["premises_id"])
    # Band 11 - the target premises may not still be pending review.
    if premises is None or premises["registration_status"] == "PENDING_REVIEW":
        raise conflict("ERR_PREMISES_NOT_ACTIVE",
                       "The premises registration is still PENDING_REVIEW")

    hold["status"] = "ACTIVE"
    touch(hold)
    # CASCADE-C hop 1: quarantine the premises.
    if premises["health_status"] != "QUARANTINED":
        premises["health_status"] = "QUARANTINED"
        touch(premises)
    # hop 2: dispute the outbound traffic still in REPORTED.
    for movement in list(store.movements.values()):
        if (movement["origin_premises_id"] != premises["id"]
                or movement["status"] != "REPORTED"):
            continue
        movement["status"] = "DISPUTED"
        touch(movement)
        # hop 2b: flag the moved animal.
        animal = store.animals.get(movement["animal_id"])
        if animal is not None and animal["trace_status"] == "NORMAL":
            animal["trace_status"] = "TRACE_HIT"
            touch(animal)
        # hop 3: widen the investigation to the destination.
        destination = store.premises.get(movement["destination_premises_id"])
        if destination is not None and destination["health_status"] == "CLEAR":
            destination["health_status"] = "UNDER_INVESTIGATION"
            touch(destination)
    return success(public(hold))


@bp.post("/hold-orders/<hold_id>/appeal")
def appeal_hold(hold_id):
    uid, role = require_roles(PRODUCER)
    body = shape.body()
    shape.s_str(body, "grounds", required=False)
    hold = hold_or_404(hold_id)
    premises = store.premises.get(hold["premises_id"])
    # Band 6 - only the producer that owns the held premises may appeal.
    require_owner(premises is not None and premises["producer_id"] == uid)
    # Band 10 - own-state gate.
    if hold["status"] != "ACTIVE":
        raise invalid_state("Only an ACTIVE hold may be appealed")
    # Band 15 - the appeal cycle is bounded at two appeals.
    if hold["appeal_count"] >= 2:
        raise conflict("ERR_APPEAL_LIMIT_EXCEEDED",
                       "The hold has already been appealed twice")
    hold["status"] = "UNDER_APPEAL"
    hold["appeal_count"] += 1
    touch(hold)
    return success(public(hold))


@bp.post("/hold-orders/<hold_id>/deny-appeal")
def deny_appeal(hold_id):
    require_roles(STATE_OFFICIAL)
    hold = hold_or_404(hold_id)
    if hold["status"] != "UNDER_APPEAL":
        raise invalid_state("Only a hold UNDER_APPEAL may have its appeal denied")
    hold["status"] = "ACTIVE"
    touch(hold)
    return success(public(hold))


@bp.post("/hold-orders/<hold_id>/release")
def release_hold(hold_id):
    require_roles(STATE_OFFICIAL)
    hold = hold_or_404(hold_id)
    # Band 10 - own-state gate.
    if hold["status"] not in ("ACTIVE", "UNDER_APPEAL"):
        raise invalid_state("Only an ACTIVE or UNDER_APPEAL hold may be released")
    # Band 11 - the linked investigation must not still be running.
    if hold["trace_request_id"]:
        trace_request = store.trace_requests.get(hold["trace_request_id"])
        if trace_request is not None and trace_request["status"] == "RUNNING":
            raise conflict("ERR_TRACE_STILL_OPEN", "The linked trace request is still RUNNING")

    now = store.now()
    hold["status"] = "RELEASED"
    hold["released_at"] = now
    touch(hold)
    premises = store.premises.get(hold["premises_id"])
    if premises is not None:
        derive.recompute_premises_pending_hold_count(premises)
        others_live = any(h["premises_id"] == premises["id"]
                          and h["status"] in ("ACTIVE", "UNDER_APPEAL")
                          for h in store.hold_orders.values())
        if not others_live and premises["health_status"] == "QUARANTINED":
            premises["health_status"] = "CLEAR"
        premises["last_hold_released_at"] = now
        touch(premises)
        for animal in store.animals.values():
            if (animal["current_premises_id"] == premises["id"]
                    and animal["trace_status"] == "TRACE_HIT"):
                animal["trace_status"] = "CLEARED"
                touch(animal)
    return success(public(hold))
