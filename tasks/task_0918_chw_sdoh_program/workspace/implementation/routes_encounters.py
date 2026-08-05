"""Community health worker time capture (PRD §3.7)."""

from flask import Blueprint

import calc
import cascades
import store
import validate as v
from clockutil import clock
from envelope import created, listing, ok
from errors import (
    ApiError, ERR_INVALID_STATE, ERR_NOT_RESOURCE_OWNER, ERR_PATIENT_NOT_ENROLLED,
    ERR_PATIENT_NOT_FOUND, ERR_RESOURCE_NOT_FOUND,
)
from ladder import ALL_ROLES, CHW, Endpoint, SUPERVISOR, run
from serial import dump, dump_all

bp = Blueprint("encounters", __name__)

EP_ENCOUNTER_CREATE = Endpoint("encounter.create", [CHW], gated=True)
EP_ENCOUNTER_READ = Endpoint("encounter.read", ALL_ROLES, path=[("encounter_id", "encounter")])
EP_ENCOUNTER_LIST = Endpoint("encounter.list", ALL_ROLES)
EP_ENCOUNTER_SUBMIT = Endpoint("encounter.submit", [CHW],
                               path=[("encounter_id", "encounter")], gated=True)
EP_ENCOUNTER_VOID = Endpoint("encounter.void", [SUPERVISOR],
                             path=[("encounter_id", "encounter")])

MINUTE_FIELDS = ("direct_minutes", "indirect_minutes", "travel_minutes", "documentation_minutes")


@bp.post("/chw/encounters")
def create_encounter():
    def payload(ctx):
        s = ctx.state
        s["patient_id"] = v.req_str(ctx.body, "patient_id")
        s["chw_id"] = v.req_str(ctx.body, "chw_id")
        s["encounter_date"] = v.req_date(ctx.body, "encounter_date")
        total = 0
        for field in MINUTE_FIELDS:
            s[field] = v.req_int(ctx.body, field, minimum=0)
            total += s[field]
        if total > calc.ENCOUNTER_MAX_TOTAL_MINUTES:
            v.bad("total_minutes must not exceed 480")
        s["total_minutes"] = total
        s["travel_miles"] = v.opt_num(ctx.body, "travel_miles", 0, minimum=0)
        s["home_visit_id"] = v.opt_str(ctx.body, "home_visit_id")

    def body_refs(ctx):
        s = ctx.state
        patient = store.get("patient", s["patient_id"])
        if patient is None:
            raise ApiError(ERR_PATIENT_NOT_FOUND, "patient_id does not resolve")
        if store.get("worker", s["chw_id"]) is None:
            raise ApiError(ERR_RESOURCE_NOT_FOUND, "chw_id does not resolve")
        if s["home_visit_id"] is not None and store.get("visit", s["home_visit_id"]) is None:
            raise ApiError(ERR_RESOURCE_NOT_FOUND, "home_visit_id does not resolve")
        s["patient"] = patient

    def enrollment(ctx):
        if ctx.state["patient"]["enrollment_status"] != "ENROLLED":
            raise ApiError(ERR_PATIENT_NOT_ENROLLED, "Patient is not ENROLLED")

    ctx = run(EP_ENCOUNTER_CREATE, steps={5: [payload], 6: [body_refs], 9: [enrollment]})
    s = ctx.state
    raw_billable = s["direct_minutes"] + s["indirect_minutes"] + s["documentation_minutes"]
    row = store.insert("encounter", {
        "patient_id": s["patient"]["id"],
        "chw_id": s["chw_id"],
        "home_visit_id": s["home_visit_id"],
        "funding_claim_id": None,
        "encounter_date": s["encounter_date"],
        "service_month": s["encounter_date"][:7],
        "direct_minutes": s["direct_minutes"],
        "indirect_minutes": s["indirect_minutes"],
        "travel_minutes": s["travel_minutes"],
        "documentation_minutes": s["documentation_minutes"],
        "travel_miles": s["travel_miles"],
        "total_minutes": s["total_minutes"],
        "raw_billable_minutes": raw_billable,
        "billable_minutes": calc.encounter_billable_minutes(raw_billable),
        "travel_reimbursement_cents": calc.marginal_cents(s["travel_miles"]),
        "funding_source": "UNFUNDED",
        "status": "DRAFT",
        "submitted_at": None,
    })
    return created(dump(row))


@bp.get("/chw/encounters/<encounter_id>")
def read_encounter(encounter_id):
    ctx = run(EP_ENCOUNTER_READ, {"encounter_id": encounter_id})
    return ok(dump(ctx.row("encounter_id")))


@bp.get("/chw/encounters")
def list_encounters():
    def pagination(ctx):
        ctx.state["page"] = v.pagination(ctx.args)

    ctx = run(EP_ENCOUNTER_LIST, steps={5: [pagination]})
    limit, offset = ctx.state["page"]
    rows = store.all_rows("encounter")
    for key in ("patient_id", "chw_id", "home_visit_id", "funding_claim_id",
                "service_month", "status", "funding_source"):
        wanted = ctx.args.get(key)
        if wanted is not None:
            rows = [r for r in rows if r.get(key) == wanted]
    page, total = v.paginate(rows, limit, offset)
    return listing(dump_all(page), limit, offset, total)


@bp.post("/chw/encounters/<encounter_id>/submit")
def submit_encounter(encounter_id):
    def target_state(ctx):
        if ctx.row("encounter_id")["status"] != "DRAFT":
            raise ApiError(ERR_INVALID_STATE, "Only a DRAFT encounter may be submitted")

    def cross_entity(ctx):
        encounter = ctx.row("encounter_id")
        visit_id = encounter.get("home_visit_id")
        if not visit_id:
            return
        visit = store.get("visit", visit_id)
        if visit is None or visit.get("documentation_status") not in ("ATTESTED", "AMENDED"):
            raise ApiError(ERR_INVALID_STATE,
                           "The linked home visit's documentation is not ATTESTED or AMENDED")

    def owner(ctx):
        if ctx.user_id != ctx.row("encounter_id").get("chw_id"):
            raise ApiError(ERR_NOT_RESOURCE_OWNER, "Caller is not the encounter's worker")

    ctx = run(EP_ENCOUNTER_SUBMIT, {"encounter_id": encounter_id},
              steps={8: [target_state], 9: [cross_entity], 10: [owner]})
    encounter = ctx.row("encounter_id")
    encounter["status"] = "SUBMITTED"
    encounter["submitted_at"] = clock.now_raw()
    store.touch(encounter)
    return ok(dump(encounter))


@bp.post("/chw/encounters/<encounter_id>/void")
def void_encounter(encounter_id):
    def payload(ctx):
        # `reason` is accepted for the caller's convenience and is not persisted.
        v.opt_str(ctx.body, "reason")

    def target_state(ctx):
        encounter = ctx.row("encounter_id")
        status = encounter["status"]
        if status == "VOIDED":
            raise ApiError(ERR_INVALID_STATE, "The encounter is already VOIDED")
        if status == "LOCKED" and encounter.get("funding_source") != "GRANT":
            raise ApiError(ERR_INVALID_STATE,
                           "A payer-locked encounter cannot be voided; resolve the claim first")

    ctx = run(EP_ENCOUNTER_VOID, {"encounter_id": encounter_id},
              steps={5: [payload], 8: [target_state]})
    encounter = ctx.row("encounter_id")
    was_grant_locked = (encounter["status"] == "LOCKED"
                        and encounter.get("funding_source") == "GRANT")
    encounter["status"] = "VOIDED"
    encounter["funding_source"] = "UNFUNDED"
    encounter["funding_claim_id"] = None
    store.touch(encounter)
    if was_grant_locked:
        for line in store.all_rows("chargeline"):
            if line.get("encounter_id") != encounter["id"]:
                continue
            if line.get("status") != "POSTED":
                continue
            cascades.reverse_charge_line(line, "ENCOUNTER_VOIDED")
    return ok(dump(encounter))
