"""Sick call: slip, triage, re-triage, scheduling and encounter disposition."""

from flask import Blueprint, request

import calc
import money
import serializers
import store
from constants import ACUITY, MAX_RETRIAGE_COUNT, SICK_CALL_ENCOUNTER_TYPES
from envelope import created, listing, ok, page_params
from errors import ApiError
from ladder import Ctx

bp = Blueprint("sickcall", __name__)


@bp.post("/sick-call-requests")
def submit():
    ctx = Ctx(roles=("Inmate", "Nurse"))
    ctx.body_inmate("inmate_id")
    ctx.freeze_gate()
    ctx.custody_gate()
    ctx.require("inmate_id", "complaint_text")
    ctx.check_type("inmate_id", "string")
    ctx.check_type("complaint_text", "string")
    ctx.enum("encounter_type", SICK_CALL_ENCOUNTER_TYPES)
    ctx.run()

    row = store.base_row()
    row.update({
        "inmate_id": ctx.inmate["id"],
        "complaint_text": ctx.body["complaint_text"],
        "submitted_at": store.now(),
        "acuity": None,
        "triaged_at": None,
        "deadline_anchor_at": None,
        "response_deadline_at": None,
        "seen_at": None,
        "retriage_count": 0,
        "encounter_type": ctx.body.get("encounter_type") or "SICK_CALL",
        "status": "SUBMITTED",
        "copay_charge_id": None,
    })
    store.sick_calls[row["id"]] = row
    return created(serializers.sick_call(row))


@bp.get("/sick-call-requests")
def list_requests():
    ctx = Ctx(roles=("Nurse", "Provider", "HealthServicesAdmin", "Inmate"))
    ctx.run()

    limit, offset = page_params(request.args)
    rows = list(store.sick_calls.values())
    if ctx.is_inmate_actor:
        rows = [s for s in rows if s["inmate_id"] == ctx.user_id]
    if request.args.get("inmate_id"):
        rows = [s for s in rows if s["inmate_id"] == request.args["inmate_id"]]
    if request.args.get("copay_charge_id"):
        rows = [s for s in rows if s.get("copay_charge_id") == request.args["copay_charge_id"]]
    if request.args.get("status"):
        rows = [s for s in rows if s["status"] == request.args["status"]]
    if request.args.get("acuity"):
        rows = [s for s in rows if s.get("acuity") == request.args["acuity"]]
    rows = store.sort_rows(rows)
    return listing(serializers.many(serializers.sick_call, rows), limit, offset)


def _bind_request(ctx, request_id, roles):
    def owner():
        row = store.sick_calls.get(request_id)
        return row["inmate_id"] if row else None
    ctx.own_id(owner)

    def bind(row):
        ctx.inmate = store.inmates.get(row["inmate_id"])
    ctx.need("request", store.sick_calls, request_id, "ERR_RECORD_NOT_FOUND", on_found=bind)


@bp.get("/sick-call-requests/<request_id>")
def read_request(request_id):
    ctx = Ctx(roles=("Nurse", "Provider", "HealthServicesAdmin", "Inmate"))
    _bind_request(ctx, request_id, None)
    ctx.run()
    return ok(serializers.sick_call(ctx.row("request")))


@bp.post("/sick-call-requests/<request_id>/triage")
def triage(request_id):
    ctx = Ctx(roles=("Nurse",))
    _bind_request(ctx, request_id, None)
    ctx.freeze_gate()
    ctx.require("acuity")
    ctx.enum("acuity", ACUITY)
    ctx.status_in(lambda: ctx.row("request"), ("SUBMITTED", "TRIAGED"))

    def distinct_acuity():
        row = ctx.row("request")
        if row["status"] == "TRIAGED" and ctx.body.get("acuity") == row.get("acuity"):
            raise ApiError("ERR_VALIDATION",
                           "a re-triage must supply an acuity different from the stored one")
    ctx.state(distinct_acuity, sub=1)

    def retriage_cap():
        row = ctx.row("request")
        if row["status"] == "TRIAGED" and row["retriage_count"] >= MAX_RETRIAGE_COUNT:
            raise ApiError("ERR_MAX_RETRIAGE_EXCEEDED", "re-triage limit reached")
    ctx.caps(retriage_cap)
    ctx.run()

    row = ctx.row("request")
    acuity = ctx.body["acuity"]
    first = row["status"] == "SUBMITTED"
    anchor, deadline = calc.sick_call_deadline(row, acuity, first)
    if not first:
        row["retriage_count"] += 1
    row["status"] = "TRIAGED"
    row["acuity"] = acuity
    row["triaged_at"] = store.now()
    row["deadline_anchor_at"] = anchor
    row["response_deadline_at"] = deadline
    store.touch(row)
    return ok(serializers.sick_call(row))


@bp.post("/sick-call-requests/<request_id>/schedule")
def schedule(request_id):
    ctx = Ctx(roles=("Nurse",))
    _bind_request(ctx, request_id, None)
    ctx.freeze_gate()
    ctx.status_in(lambda: ctx.row("request"), ("TRIAGED",))
    ctx.run()

    row = ctx.row("request")
    row["status"] = "SCHEDULED"           # response_deadline_at is NOT recomputed
    store.touch(row)
    return ok(serializers.sick_call(row))


@bp.post("/sick-call-requests/<request_id>/see")
def see(request_id):
    ctx = Ctx(roles=("Provider",))
    _bind_request(ctx, request_id, None)
    ctx.freeze_gate()
    ctx.status_in(lambda: ctx.row("request"), ("SCHEDULED",))
    ctx.run()

    row = ctx.row("request")
    row["status"] = "SEEN"
    row["seen_at"] = store.now()
    charge, entry = money.post_copay_charge(ctx.inmate, row["encounter_type"],
                                            source_sick_call_id=row["id"])
    row["copay_charge_id"] = charge["id"]
    store.touch(row)
    if entry is not None:
        store.touch(ctx.inmate)
    return ok(serializers.sick_call(row))


@bp.post("/sick-call-requests/<request_id>/close")
def close(request_id):
    # PRD 3.3: "the freeze gate is not consulted on this final step, whose only
    # precondition is that the request is SEEN."
    ctx = Ctx(roles=("Provider",))
    _bind_request(ctx, request_id, None)
    ctx.status_in(lambda: ctx.row("request"), ("SEEN",))
    ctx.run()

    row = ctx.row("request")
    row["status"] = "CLOSED"
    store.touch(row)
    return ok(serializers.sick_call(row))
