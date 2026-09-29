"""Disease traceback: scope, response and scoring (PRD 3.7)."""
from flask import Blueprint

import calc
import tracescope as trace_engine
import shape
from authz import PROGRAM_ADMIN, STATE_OFFICIAL, TRACE_ANALYST, require_roles
from db import base_record, store, touch
from errors import conflict, invalid_state, not_found, segregation_of_duties
from respond import success
from routes._common import animal_or_404, page, trace_or_404
from serialize import public
from timeutil import hours_between

bp = Blueprint("traces", __name__)

PATHOGEN_CLASSES = ("DIRECT_CONTACT", "ENVIRONMENTAL")
DIRECTIONS = ("BACKWARD", "FORWARD", "BOTH")


@bp.post("/trace-requests")
def open_trace():
    uid, role = require_roles(TRACE_ANALYST)
    body = shape.body()
    index_animal_id = shape.s_str(body, "index_animal_id")
    pathogen_class = shape.s_enum(body, "pathogen_class", PATHOGEN_CLASSES)
    direction = shape.s_enum(body, "direction", DIRECTIONS)
    lookback_days = shape.s_int(body, "lookback_days", minimum=1, maximum=365)
    max_hops = shape.s_int(body, "max_hops", minimum=1, maximum=5)
    animal = animal_or_404(index_animal_id)

    rec = base_record()
    rec.update({
        "index_animal_id": animal["id"],
        "pathogen_class": pathogen_class,
        "direction": direction,
        "lookback_days": lookback_days,
        "max_hops": max_hops,
        "status": "SUBMITTED",
        "opened_by_user_id": uid,
        "closed_by_user_id": None,
        "opened_at": store.now(),
        "closed_at": None,
        "variant_applied": None,
        "hits": [],
        "hit_count": 0,
        "premises_touched_count": 0,
        "hops_total": 0,
        "hops_unreachable": 0,
        "elapsed_hours": None,
        "completeness_score": None,
        "trace_goal_met": None,
        "_traversed_movement_ids": [],
    })
    store.trace_requests[rec["id"]] = rec
    return success(public(rec), status=201)


@bp.get("/trace-requests/<trace_id>")
def read_trace(trace_id):
    require_roles(TRACE_ANALYST, STATE_OFFICIAL, PROGRAM_ADMIN)
    return success(public(trace_or_404(trace_id)))


@bp.get("/trace-requests")
def list_traces():
    require_roles(TRACE_ANALYST, STATE_OFFICIAL, PROGRAM_ADMIN)
    limit, offset = shape.pagination_params()
    rows = list(store.trace_requests.values())
    for field in ("index_animal_id", "status"):
        value = shape.q(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    goal = shape.q_bool("trace_goal_met")
    if goal is not None:
        rows = [r for r in rows if r["trace_goal_met"] is goal]
    return page(rows, limit, offset)


@bp.post("/trace-requests/<trace_id>/run")
def run_trace(trace_id):
    require_roles(TRACE_ANALYST)
    trace_request = trace_or_404(trace_id)
    # Band 10 - own-state gates.
    if trace_request["status"] != "SUBMITTED":
        raise invalid_state("Only a SUBMITTED trace request may be run")
    index_animal = store.animals.get(trace_request["index_animal_id"])
    if index_animal is None or index_animal["lifecycle_status"] == "VOIDED":
        raise invalid_state("The index animal is VOIDED")

    result = trace_engine.run_projection(trace_request, index_animal)
    trace_request["status"] = "RUNNING"
    trace_request["variant_applied"] = result["variant_applied"]
    trace_request["hits"] = result["hits"]
    trace_request["hit_count"] = result["hit_count"]
    trace_request["premises_touched_count"] = result["premises_touched_count"]
    trace_request["hops_total"] = result["hops_total"]
    trace_request["_traversed_movement_ids"] = result["traversed_movement_ids"]
    touch(trace_request)
    for hit in result["hits"]:
        animal = store.animals.get(hit["animal_id"])
        if animal is not None and animal["trace_status"] == "NORMAL":
            animal["trace_status"] = "TRACE_HIT"
            touch(animal)
    return success(public(trace_request))


@bp.post("/trace-requests/<trace_id>/hits/<animal_id>/respond")
def respond_to_hit(trace_id, animal_id):
    require_roles(STATE_OFFICIAL)
    body = shape.body()
    resolved = shape.s_bool(body, "resolved")
    # Band 4 - path identifiers resolve left to right.
    trace_request = trace_or_404(trace_id)
    animal_or_404(animal_id)
    # Band 5 - the animal must sit in this request's frozen hit set.
    hit = next((h for h in trace_request["hits"] if h["animal_id"] == animal_id), None)
    if hit is None:
        raise not_found("ERR_TRACE_HIT_NOT_FOUND",
                        "The animal is not present in this trace request's hits")
    hit["responded"] = True
    hit["resolved"] = resolved
    touch(trace_request)
    return success(public(trace_request))


@bp.post("/trace-requests/<trace_id>/close")
def close_trace(trace_id):
    uid, role = require_roles(TRACE_ANALYST)
    trace_request = trace_or_404(trace_id)
    # Band 8 - segregation of duties precedes the own-state gate.
    if uid == trace_request["opened_by_user_id"]:
        raise segregation_of_duties(
            "The closing analyst must differ from the opening analyst")
    # Band 10 - own-state gate.
    if trace_request["status"] != "RUNNING":
        raise invalid_state("Only a RUNNING trace request may be closed")
    # Band 11 - a linked hold may not still be pending.
    for hold in store.hold_orders.values():
        if (hold["trace_request_id"] == trace_request["id"]
                and hold["status"] in ("PROPOSED", "UNDER_APPEAL")):
            raise conflict("ERR_HOLD_PENDING",
                           "A hold order linked to this trace is still pending")

    closed_at = store.now()
    traversed = trace_request.get("_traversed_movement_ids") or []
    statuses = [store.movements[mid]["status"] for mid in traversed
                if mid in store.movements]
    hops_unreachable = sum(1 for s in statuses if s in ("DISPUTED", "VOIDED"))
    disputed_hops = sum(1 for s in statuses if s == "DISPUTED")
    hits = trace_request["hits"]
    responded = sum(1 for h in hits if h["responded"])
    resolved = sum(1 for h in hits if h["resolved"])
    stale_premises = any(
        (store.premises.get(h["premises_id"]) or {}).get("registration_status") != "ACTIVE"
        for h in hits)
    score = calc.completeness(trace_request["hit_count"], responded, resolved,
                              hops_unreachable, trace_request["hops_total"],
                              stale_premises, disputed_hops)
    elapsed = calc.to_dec(calc.rhu(hours_between(closed_at, trace_request["opened_at"]), 2), 2)
    trace_request.update({
        "status": "COMPLETED",
        "closed_at": closed_at,
        "closed_by_user_id": uid,
        "hops_unreachable": hops_unreachable,
        "completeness_score": score,
        "elapsed_hours": elapsed,
        "trace_goal_met": calc.trace_goal(elapsed, score),
    })
    touch(trace_request)
    return success(public(trace_request))


@bp.post("/trace-requests/<trace_id>/cancel")
def cancel_trace(trace_id):
    require_roles(TRACE_ANALYST)
    trace_request = trace_or_404(trace_id)
    # Band 10 - own-state gate.
    if trace_request["status"] not in ("SUBMITTED", "RUNNING"):
        raise invalid_state("Only a SUBMITTED or RUNNING trace request may be cancelled")
    # Band 11 - cancelling out of RUNNING is blocked by a live hold.
    if trace_request["status"] == "RUNNING":
        for hold in store.hold_orders.values():
            if (hold["trace_request_id"] == trace_request["id"]
                    and hold["status"] in ("ACTIVE", "UNDER_APPEAL")):
                raise conflict("ERR_TRACE_STILL_OPEN",
                               "A hold order linked to this trace is still open")
    trace_request["status"] = "CANCELLED"
    touch(trace_request)
    return success(public(trace_request))
