"""Home visits: two independent lifecycles on one row (PRD §3.5)."""

from decimal import Decimal

from flask import Blueprint

import calc
import cascades
import store
import validate as v
from clockutil import clock, elapsed_days, elapsed_hours, parse_iso
from envelope import created, listing, ok
from errors import (
    ApiError, ERR_AMENDMENT_WINDOW_CLOSED, ERR_ATTESTATION_WINDOW_CLOSED,
    ERR_INVALID_STATE, ERR_NOT_RESOURCE_OWNER, ERR_PATIENT_NOT_ENROLLED,
    ERR_PATIENT_NOT_FOUND, ERR_RESOURCE_NOT_FOUND, ERR_TWO_PERSON_VISIT_REQUIRED,
    ERR_VISIT_SLOT_CONFLICT,
)
from ladder import ALL_ROLES, CHW, Endpoint, SUPERVISOR, run
from serial import dump, dump_all

bp = Blueprint("visits", __name__)

EP_VISIT_CREATE = Endpoint("visit.create", [CHW, SUPERVISOR], gated=True)
EP_VISIT_READ = Endpoint("visit.read", ALL_ROLES, path=[("visit_id", "visit")])
EP_VISIT_LIST = Endpoint("visit.list", ALL_ROLES)
EP_VISIT_EN_ROUTE = Endpoint("visit.en_route", [CHW], path=[("visit_id", "visit")], gated=True)
EP_VISIT_COMPLETE = Endpoint("visit.complete", [CHW], path=[("visit_id", "visit")], gated=True)
EP_VISIT_NO_SHOW = Endpoint("visit.no_show", [CHW, SUPERVISOR],
                            path=[("visit_id", "visit")], gated=True)
EP_VISIT_CANCEL = Endpoint("visit.cancel", [CHW, SUPERVISOR], path=[("visit_id", "visit")])
EP_VISIT_ATTEST = Endpoint("visit.attest", [CHW], path=[("visit_id", "visit")], gated=True)
EP_VISIT_DOC_REVISION = Endpoint("visit.documentation_revision", [CHW, SUPERVISOR],
                                 path=[("visit_id", "visit")], gated=True)

OCCUPYING_STATUSES = ("SCHEDULED", "EN_ROUTE", "COMPLETED")
REVISION_ACTIONS = ("AMEND", "VOID")


def _assigned_owner(ctx):
    if ctx.user_id != ctx.row("visit_id").get("assigned_chw_id"):
        raise ApiError(ERR_NOT_RESOURCE_OWNER, "Caller is not the visit's assigned worker")


@bp.post("/chw/home-visits")
def create_visit():
    def payload(ctx):
        s = ctx.state
        s["patient_id"] = v.req_str(ctx.body, "patient_id")
        s["assigned_chw_id"] = v.req_str(ctx.body, "assigned_chw_id")
        s["second_chw_id"] = v.opt_str(ctx.body, "second_chw_id")
        s["scheduled_start"] = v.req_instant(ctx.body, "scheduled_start")
        s["scheduled_end"] = v.req_instant(ctx.body, "scheduled_end")
        start = parse_iso(s["scheduled_start"])
        end = parse_iso(s["scheduled_end"])
        if end <= start:
            v.bad("scheduled_end must be strictly after scheduled_start")
        minutes = Decimal((end - start).total_seconds()) / Decimal(60)
        if minutes < calc.VISIT_MIN_DURATION_MINUTES or minutes > calc.VISIT_MAX_DURATION_MINUTES:
            v.bad("visit duration must be between 15 and 240 minutes")
        if s["second_chw_id"] is not None and s["second_chw_id"] == s["assigned_chw_id"]:
            v.bad("second_chw_id must differ from assigned_chw_id")

    def body_refs(ctx):
        s = ctx.state
        patient = store.get("patient", s["patient_id"])
        if patient is None:
            raise ApiError(ERR_PATIENT_NOT_FOUND, "patient_id does not resolve")
        if store.get("worker", s["assigned_chw_id"]) is None:
            raise ApiError(ERR_RESOURCE_NOT_FOUND, "assigned_chw_id does not resolve")
        if s["second_chw_id"] is not None and store.get("worker", s["second_chw_id"]) is None:
            raise ApiError(ERR_RESOURCE_NOT_FOUND, "second_chw_id does not resolve")
        s["patient"] = patient

    def enrollment(ctx):
        if ctx.state["patient"]["enrollment_status"] != "ENROLLED":
            raise ApiError(ERR_PATIENT_NOT_ENROLLED, "Patient is not ENROLLED")

    def safety(ctx):
        if ctx.state["patient"].get("address_safety_flag") and not ctx.state["second_chw_id"]:
            raise ApiError(ERR_TWO_PERSON_VISIT_REQUIRED,
                           "A second worker is required for this address")

    def overlap(ctx):
        s = ctx.state
        new_start = parse_iso(s["scheduled_start"])
        new_end = parse_iso(s["scheduled_end"])
        workers = [w for w in (s["assigned_chw_id"], s["second_chw_id"]) if w]
        for existing in store.all_rows("visit"):
            if existing.get("scheduling_status") not in OCCUPYING_STATUSES:
                continue
            occupants = [existing.get("assigned_chw_id"), existing.get("second_chw_id")]
            if not any(worker in occupants for worker in workers):
                continue
            other_start = parse_iso(existing.get("scheduled_start"))
            other_end = parse_iso(existing.get("scheduled_end"))
            if other_start is None or other_end is None:
                continue
            if new_start < other_end and other_start < new_end:
                raise ApiError(ERR_VISIT_SLOT_CONFLICT, "The worker's slot is already taken")

    ctx = run(EP_VISIT_CREATE, steps={
        5: [payload], 6: [body_refs], 9: [enrollment], 11: [safety], 13: [overlap],
    })
    s = ctx.state
    row = store.insert("visit", {
        "patient_id": s["patient"]["id"],
        "assigned_chw_id": s["assigned_chw_id"],
        "second_chw_id": s["second_chw_id"],
        "scheduled_start": s["scheduled_start"],
        "scheduled_end": s["scheduled_end"],
        "two_person_required": bool(s["patient"].get("address_safety_flag")),
        "scheduling_status": "SCHEDULED",
        "documentation_status": "DRAFT",
        "completed_at": None,
        "attested_at": None,
        "amendment_count": 0,
        "visit_note": None,
    })
    return created(dump(row))


@bp.get("/chw/home-visits/<visit_id>")
def read_visit(visit_id):
    ctx = run(EP_VISIT_READ, {"visit_id": visit_id})
    return ok(dump(ctx.row("visit_id")))


@bp.get("/chw/home-visits")
def list_visits():
    def pagination(ctx):
        ctx.state["page"] = v.pagination(ctx.args)

    ctx = run(EP_VISIT_LIST, steps={5: [pagination]})
    limit, offset = ctx.state["page"]
    rows = store.all_rows("visit")
    for key in ("patient_id", "assigned_chw_id", "second_chw_id",
                "scheduling_status", "documentation_status"):
        wanted = ctx.args.get(key)
        if wanted is not None:
            rows = [r for r in rows if r.get(key) == wanted]
    page, total = v.paginate(rows, limit, offset)
    return listing(dump_all(page), limit, offset, total)


@bp.post("/chw/home-visits/<visit_id>/en-route")
def visit_en_route(visit_id):
    def target_state(ctx):
        if ctx.row("visit_id")["scheduling_status"] != "SCHEDULED":
            raise ApiError(ERR_INVALID_STATE, "Only a SCHEDULED visit may go en route")

    ctx = run(EP_VISIT_EN_ROUTE, {"visit_id": visit_id},
              steps={8: [target_state], 10: [_assigned_owner]})
    visit = ctx.row("visit_id")
    visit["scheduling_status"] = "EN_ROUTE"
    store.touch(visit)
    return ok(dump(visit))


@bp.post("/chw/home-visits/<visit_id>/complete")
def visit_complete(visit_id):
    def target_state(ctx):
        if ctx.row("visit_id")["scheduling_status"] != "EN_ROUTE":
            raise ApiError(ERR_INVALID_STATE, "Only an EN_ROUTE visit may be completed")

    ctx = run(EP_VISIT_COMPLETE, {"visit_id": visit_id},
              steps={8: [target_state], 10: [_assigned_owner]})
    visit = ctx.row("visit_id")
    visit["scheduling_status"] = "COMPLETED"
    visit["completed_at"] = clock.now_raw()
    store.touch(visit)
    return ok(dump(visit))


@bp.post("/chw/home-visits/<visit_id>/no-show")
def visit_no_show(visit_id):
    def target_state(ctx):
        if ctx.row("visit_id")["scheduling_status"] not in ("SCHEDULED", "EN_ROUTE"):
            raise ApiError(ERR_INVALID_STATE,
                           "Only a SCHEDULED or EN_ROUTE visit may be marked no-show")

    ctx = run(EP_VISIT_NO_SHOW, {"visit_id": visit_id}, steps={8: [target_state]})
    visit = ctx.row("visit_id")
    visit["scheduling_status"] = "NO_SHOW"
    store.touch(visit)
    return ok(dump(visit))


@bp.post("/chw/home-visits/<visit_id>/cancel")
def visit_cancel(visit_id):
    def target_state(ctx):
        if ctx.row("visit_id")["scheduling_status"] not in ("SCHEDULED", "EN_ROUTE"):
            raise ApiError(ERR_INVALID_STATE,
                           "Only a SCHEDULED or EN_ROUTE visit may be cancelled")

    ctx = run(EP_VISIT_CANCEL, {"visit_id": visit_id}, steps={8: [target_state]})
    visit = ctx.row("visit_id")
    visit["scheduling_status"] = "CANCELLED"
    store.touch(visit)
    return ok(dump(visit))


@bp.post("/chw/home-visits/<visit_id>/attest")
def visit_attest(visit_id):
    def payload(ctx):
        ctx.state["visit_note"] = v.req_str(ctx.body, "visit_note")

    def target_state(ctx):
        visit = ctx.row("visit_id")
        if visit["documentation_status"] != "DRAFT":
            raise ApiError(ERR_INVALID_STATE, "Documentation is no longer in DRAFT")
        if visit["scheduling_status"] != "COMPLETED":
            raise ApiError(ERR_INVALID_STATE, "Only a COMPLETED visit may be attested")

    def window(ctx):
        visit = ctx.row("visit_id")
        elapsed = elapsed_hours(visit.get("completed_at"), clock.now_raw())
        if elapsed is None or elapsed > Decimal(calc.ATTESTATION_WINDOW_HOURS):
            raise ApiError(ERR_ATTESTATION_WINDOW_CLOSED, "The 72-hour attestation window is closed")

    ctx = run(EP_VISIT_ATTEST, {"visit_id": visit_id},
              steps={5: [payload], 8: [target_state], 10: [_assigned_owner], 14: [window]})
    visit = ctx.row("visit_id")
    visit["documentation_status"] = "ATTESTED"
    visit["attested_at"] = clock.now_raw()
    visit["visit_note"] = ctx.state["visit_note"]
    store.touch(visit)
    return ok(dump(visit))


@bp.post("/chw/home-visits/<visit_id>/documentation-revision")
def visit_documentation_revision(visit_id):
    def payload(ctx):
        ctx.state["action"] = v.req_enum(ctx.body, "action", REVISION_ACTIONS)
        ctx.state["visit_note"] = v.opt_str(ctx.body, "visit_note")

    def target_state(ctx):
        if ctx.row("visit_id")["documentation_status"] not in ("ATTESTED", "AMENDED"):
            raise ApiError(ERR_INVALID_STATE,
                           "Documentation must be ATTESTED or AMENDED to be revised")

    def actor(ctx):
        if ctx.state["action"] == "AMEND":
            if ctx.role != CHW or ctx.user_id != ctx.row("visit_id").get("assigned_chw_id"):
                raise ApiError(ERR_NOT_RESOURCE_OWNER,
                               "AMEND requires the assigned CHW")
        else:
            if ctx.role != SUPERVISOR:
                raise ApiError(ERR_NOT_RESOURCE_OWNER, "VOID requires a Supervisor")

    def window(ctx):
        if ctx.state["action"] != "AMEND":
            return
        visit = ctx.row("visit_id")
        elapsed = elapsed_days(visit.get("attested_at"), clock.now_raw())
        if elapsed is None or elapsed > Decimal(calc.AMENDMENT_WINDOW_DAYS):
            raise ApiError(ERR_AMENDMENT_WINDOW_CLOSED, "The 30-day amendment window is closed")

    ctx = run(EP_VISIT_DOC_REVISION, {"visit_id": visit_id},
              steps={5: [payload], 8: [target_state], 10: [actor], 14: [window]})
    visit = ctx.row("visit_id")
    if ctx.state["action"] == "AMEND":
        visit["documentation_status"] = "AMENDED"
        if "visit_note" in ctx.body:
            visit["visit_note"] = ctx.state["visit_note"]
        visit["amendment_count"] = visit.get("amendment_count", 0) + 1
        store.touch(visit)
    else:
        visit["documentation_status"] = "VOIDED"
        store.touch(visit)
        cascades.void_draft_encounters_for_visit(visit)
    return ok(dump(visit))
