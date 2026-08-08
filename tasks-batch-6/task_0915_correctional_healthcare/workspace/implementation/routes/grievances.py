"""Grievances: the ladder, the remand loop and the fiscal remedy (Cascade E)."""

from datetime import timedelta

from flask import Blueprint, request

import calc
import money
import serializers
import store
from constants import (
    GRIEVANCE_FILING_WINDOW_DAYS, GRIEVANCE_MAX_REMANDS, GRIEVANCE_NEXT_STAGE,
    GRIEVANCE_OUTCOME_INPUT,
)
from envelope import created, listing, ok, page_params
from errors import ApiError
from ladder import Ctx

bp = Blueprint("grievances", __name__)


@bp.post("/inmates/<inmate_id>/grievances")
def file_grievance(inmate_id):
    # Grievance operations are deliberately exempt from the records freeze.
    ctx = Ctx(roles=("Inmate",))
    ctx.path_inmate(inmate_id)
    ctx.need_body_ref("charge", store.copay_charges, "subject_copay_charge_id",
                      "ERR_RECORD_NOT_FOUND")
    ctx.require("grievance_text", "grieved_event_at")
    ctx.check_type("grievance_text", "string")
    ctx.check_type("grieved_event_at", "datetime")
    ctx.check_type("subject_copay_charge_id", "string")

    def filing_window():
        grieved = ctx.dt_field("grieved_event_at")
        limit = grieved.dt + timedelta(days=GRIEVANCE_FILING_WINDOW_DAYS["INFORMAL"])
        if store.clock_dt() > limit:
            raise ApiError("ERR_GRIEVANCE_FILING_WINDOW_EXPIRED",
                           "the grievance filing window has closed")
    ctx.temporal(filing_window)
    ctx.run()

    row = store.base_row()
    row.update({
        "inmate_id": inmate_id,
        "subject_copay_charge_id": ctx.body.get("subject_copay_charge_id"),
        "grievance_text": ctx.body["grievance_text"],
        "grieved_event_at": ctx.dt_field("grieved_event_at"),
        "stage": "INFORMAL",
        "stage_entered_at": store.now(),
        "remand_count": 0,
        "outcome": None,
        "status": "FILED",
        "_decided_at": None,
    })
    row["response_due_at"] = calc.grievance_response_due(row)
    store.grievances[row["id"]] = row
    return created(serializers.grievance(row))


@bp.get("/grievances")
def list_grievances():
    ctx = Ctx(roles=("GrievanceCoordinator", "HealthServicesAdmin", "Inmate"))
    ctx.run()

    limit, offset = page_params(request.args)
    rows = list(store.grievances.values())
    if ctx.is_inmate_actor:
        rows = [g for g in rows if g["inmate_id"] == ctx.user_id]
    for field in ("inmate_id", "subject_copay_charge_id", "stage", "status"):
        wanted = request.args.get(field)
        if wanted:
            rows = [g for g in rows if g.get(field) == wanted]
    rows = store.sort_rows(rows)
    return listing(serializers.many(serializers.grievance, rows), limit, offset)


def _bind(ctx, grievance_id):
    ctx.own_id(lambda: (store.grievances[grievance_id]["inmate_id"]
                        if grievance_id in store.grievances else None))

    def bind(row):
        ctx.inmate = store.inmates.get(row["inmate_id"])
    ctx.need("grievance", store.grievances, grievance_id, "ERR_RECORD_NOT_FOUND", on_found=bind)


@bp.get("/grievances/<grievance_id>")
def read_grievance(grievance_id):
    ctx = Ctx(roles=("GrievanceCoordinator", "HealthServicesAdmin", "Inmate"))
    _bind(ctx, grievance_id)
    ctx.run()
    return ok(serializers.grievance(ctx.row("grievance")))


@bp.post("/grievances/<grievance_id>/accept")
def accept(grievance_id):
    ctx = Ctx(roles=("GrievanceCoordinator",))
    _bind(ctx, grievance_id)
    ctx.status_in(lambda: ctx.row("grievance"), ("FILED", "REMANDED"))
    ctx.run()

    row = ctx.row("grievance")
    row["status"] = "UNDER_REVIEW"
    row["stage_entered_at"] = store.now()
    row["response_due_at"] = calc.grievance_response_due(row)
    store.touch(row)
    return ok(serializers.grievance(row))


@bp.post("/grievances/<grievance_id>/decide")
def decide(grievance_id):
    ctx = Ctx(roles=("GrievanceCoordinator",))
    _bind(ctx, grievance_id)
    ctx.require("outcome")
    ctx.enum("outcome", GRIEVANCE_OUTCOME_INPUT)
    ctx.status_in(lambda: ctx.row("grievance"), ("UNDER_REVIEW",))

    def reversible():
        row = ctx.row("grievance")
        if ctx.body.get("outcome") != "GRANTED":
            return
        charge_id = row.get("subject_copay_charge_id")
        if not charge_id:
            return
        charge = store.copay_charges.get(charge_id)
        if charge is None:
            return
        if charge["status"] not in ("POSTED", "DEBT_LIEN"):
            raise ApiError("ERR_CHARGE_NOT_REVERSIBLE", "the subject charge is not reversible")
    ctx.caps(reversible)
    ctx.run()

    row = ctx.row("grievance")
    row["status"] = "DECIDED"                       # Cascade E, L1
    row["outcome"] = ctx.body["outcome"]
    row["_decided_at"] = store.now()

    charge_id = row.get("subject_copay_charge_id")
    charge = store.copay_charges.get(charge_id) if charge_id else None
    if (row["outcome"] == "GRANTED" and charge is not None
            and charge["status"] in ("POSTED", "DEBT_LIEN")):
        money.reverse_charge(ctx.inmate, charge, row)   # L2..L4
        store.touch(ctx.inmate)                         # L5: indigent_flag re-derived at read
    store.touch(row)
    return ok(serializers.grievance(row))


@bp.post("/grievances/<grievance_id>/escalate")
def escalate(grievance_id):
    ctx = Ctx(roles=("Inmate",))
    _bind(ctx, grievance_id)

    def escalatable():
        row = ctx.row("grievance")
        if row["status"] != "DECIDED" or row.get("outcome") != "DENIED" \
                or row["stage"] not in GRIEVANCE_NEXT_STAGE:
            raise ApiError("ERR_INVALID_STATE", "this grievance cannot be escalated")
    ctx.state(escalatable)

    def window():
        row = ctx.row("grievance")
        decided = row.get("_decided_at")
        if decided is None:
            return
        next_stage = GRIEVANCE_NEXT_STAGE[row["stage"]]
        limit = decided.dt + timedelta(days=GRIEVANCE_FILING_WINDOW_DAYS[next_stage])
        if store.clock_dt() > limit:
            raise ApiError("ERR_GRIEVANCE_FILING_WINDOW_EXPIRED",
                           "the escalation window has closed")
    ctx.temporal(window)
    ctx.run()

    row = ctx.row("grievance")
    row["stage"] = GRIEVANCE_NEXT_STAGE[row["stage"]]
    row["status"] = "FILED"
    row["outcome"] = None
    row["stage_entered_at"] = store.now()
    row["response_due_at"] = calc.grievance_response_due(row)
    store.touch(row)
    return ok(serializers.grievance(row))


@bp.post("/grievances/<grievance_id>/remand")
def remand(grievance_id):
    ctx = Ctx(roles=("GrievanceCoordinator",))
    _bind(ctx, grievance_id)

    def remandable():
        row = ctx.row("grievance")
        if row["status"] != "UNDER_REVIEW" or row["stage"] != "APPEAL":
            raise ApiError("ERR_INVALID_STATE", "only an APPEAL under review may be remanded")
    ctx.state(remandable)

    def remand_cap():
        if ctx.row("grievance")["remand_count"] >= GRIEVANCE_MAX_REMANDS:
            raise ApiError("ERR_MAX_REMANDS_EXCEEDED", "remand limit reached")
    ctx.caps(remand_cap)
    ctx.run()

    row = ctx.row("grievance")
    row["status"] = "REMANDED"
    row["remand_count"] += 1
    row["stage"] = "FORMAL"
    row["response_due_at"] = calc.grievance_response_due(row)
    store.touch(row)
    return ok(serializers.grievance(row))


@bp.post("/grievances/<grievance_id>/close")
def close(grievance_id):
    ctx = Ctx(roles=("GrievanceCoordinator",))
    _bind(ctx, grievance_id)
    ctx.status_in(lambda: ctx.row("grievance"), ("DECIDED",))
    ctx.run()

    row = ctx.row("grievance")
    row["status"] = "CLOSED"
    store.touch(row)
    return ok(serializers.grievance(row))


@bp.post("/grievances/<grievance_id>/withdraw")
def withdraw(grievance_id):
    ctx = Ctx(roles=("Inmate",))
    _bind(ctx, grievance_id)
    ctx.status_in(lambda: ctx.row("grievance"), ("FILED", "UNDER_REVIEW", "REMANDED"))
    ctx.run()

    row = ctx.row("grievance")
    row["status"] = "WITHDRAWN"
    row["outcome"] = "WITHDRAWN"
    store.touch(row)
    return ok(serializers.grievance(row))
