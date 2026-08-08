"""Closed-loop referrals: holding, responding, re-routing and closing (PRD §3.4)."""

from flask import Blueprint

import calc
import cascades
import store
import validate as v
from clockutil import clock, shift
from envelope import created, listing, ok
from errors import (
    ApiError, ERR_INSUFFICIENT_UNITS, ERR_INVALID_STATE, ERR_NOT_RESOURCE_OWNER,
    ERR_PATIENT_NOT_ENROLLED, ERR_PATIENT_NOT_FOUND, ERR_REROUTE_LIMIT_EXCEEDED,
    ERR_RESOURCE_NOT_FOUND, ERR_RESOURCE_ORG_SUSPENDED, ERR_STALE_OFFERING_VERSION,
)
from ladder import ALL_ROLES, CHW, Endpoint, PARTNER, SUPERVISOR, run
from serial import dump, dump_all

bp = Blueprint("referrals", __name__)

EP_REFERRAL_CREATE = Endpoint("referral.create", [CHW], gated=True)
EP_REFERRAL_READ = Endpoint("referral.read", ALL_ROLES, path=[("referral_id", "referral")])
EP_REFERRAL_LIST = Endpoint("referral.list", ALL_ROLES)
EP_REFERRAL_RESPOND = Endpoint("referral.respond", [PARTNER],
                               path=[("referral_id", "referral")])
EP_REFERRAL_DELIVER = Endpoint("referral.deliver", [PARTNER],
                               path=[("referral_id", "referral")])
EP_REFERRAL_CLOSE = Endpoint("referral.close", [CHW, SUPERVISOR],
                             path=[("referral_id", "referral")])
EP_REFERRAL_REROUTE = Endpoint("referral.reroute", [CHW],
                               path=[("referral_id", "referral")], gated=True)

URGENCIES = tuple(calc.ACK_SLA_HOURS.keys())
DECISIONS = ("ACCEPTED", "DECLINED")


def _eligibility_step(ctx):
    patient = ctx.state["patient"]
    offering = ctx.state["offering"]
    _order, failing, error_id = calc.run_gauntlet(patient, offering["id"])
    if failing is not None:
        raise ApiError(error_id, "Patient fails eligibility criterion %s" % failing["id"])


def _capacity_step(ctx):
    offering = ctx.state["offering"]
    if offering["available_units"] < ctx.state["units_requested"]:
        raise ApiError(ERR_INSUFFICIENT_UNITS, "Not enough available units")


def _org_and_enrollment(ctx):
    offering = ctx.state["offering"]
    org = store.get("org", offering.get("resource_org_id"))
    if org is not None and org.get("status") != "ACTIVE":
        raise ApiError(ERR_RESOURCE_ORG_SUSPENDED, "The resource organization is SUSPENDED")
    if ctx.state["patient"]["enrollment_status"] != "ENROLLED":
        raise ApiError(ERR_PATIENT_NOT_ENROLLED, "Patient is not ENROLLED")


def _new_referral(patient, offering, opened_by_chw_id, urgency, units, parent=None):
    now = clock.now_raw()
    sla_hours = calc.ACK_SLA_HOURS[urgency]
    if parent is None:
        ack_source = now
        parent_id = None
        root_id = None
        reroute_count = 0
    else:
        root = store.get("referral", parent.get("root_referral_id")) or parent
        ack_source = root["sent_at"]
        parent_id = parent["id"]
        root_id = parent.get("root_referral_id")
        reroute_count = parent.get("reroute_count", 0) + 1
    row = store.insert("referral", {
        "patient_id": patient["id"],
        "offering_id": offering["id"],
        "opened_by_chw_id": opened_by_chw_id,
        "parent_referral_id": parent_id,
        "root_referral_id": root_id,
        "urgency": urgency,
        "units_requested": units,
        "status": "SENT",
        "sent_at": now,
        "ack_deadline_at": shift(ack_source, hours=sla_hours),
        "hold_expires_at": shift(now, hours=calc.REFERRAL_HOLD_EXPIRY_HOURS),
        "reroute_count": reroute_count,
        "decline_reason": None,
        "lapse_reason": None,
        "delivered_at": None,
        "closed_at": None,
        "outcome_note": None,
    })
    if row["root_referral_id"] is None:
        row["root_referral_id"] = row["id"]
    cascades.place_hold(offering, units, patient["id"])
    return row


@bp.post("/chw/referrals")
def create_referral():
    def payload(ctx):
        s = ctx.state
        s["patient_id"] = v.req_str(ctx.body, "patient_id")
        s["offering_id"] = v.req_str(ctx.body, "offering_id")
        s["opened_by_chw_id"] = v.req_str(ctx.body, "opened_by_chw_id")
        s["urgency"] = v.req_enum(ctx.body, "urgency", URGENCIES)
        s["units_requested"] = v.req_int(ctx.body, "units_requested", minimum=1)
        s["expected_offering_version"] = v.req_int(ctx.body, "expected_offering_version")

    def body_refs(ctx):
        s = ctx.state
        patient = store.get("patient", s["patient_id"])
        if patient is None:
            raise ApiError(ERR_PATIENT_NOT_FOUND, "patient_id does not resolve")
        offering = store.get("offering", s["offering_id"])
        if offering is None:
            raise ApiError(ERR_RESOURCE_NOT_FOUND, "offering_id does not resolve")
        if store.get("worker", s["opened_by_chw_id"]) is None:
            raise ApiError(ERR_RESOURCE_NOT_FOUND, "opened_by_chw_id does not resolve")
        s["patient"] = patient
        s["offering"] = offering

    def occ(ctx):
        if ctx.state["expected_offering_version"] != ctx.state["offering"]["version"]:
            raise ApiError(ERR_STALE_OFFERING_VERSION, "expected_offering_version is stale")

    ctx = run(EP_REFERRAL_CREATE, steps={
        5: [payload], 6: [body_refs], 7: [occ], 9: [_org_and_enrollment],
        12: [_eligibility_step], 16: [_capacity_step],
    })
    s = ctx.state
    row = _new_referral(s["patient"], s["offering"], s["opened_by_chw_id"],
                        s["urgency"], s["units_requested"])
    return created(dump(row))


@bp.get("/chw/referrals/<referral_id>")
def read_referral(referral_id):
    ctx = run(EP_REFERRAL_READ, {"referral_id": referral_id})
    return ok(dump(ctx.row("referral_id")))


@bp.get("/chw/referrals")
def list_referrals():
    def pagination(ctx):
        ctx.state["page"] = v.pagination(ctx.args)

    ctx = run(EP_REFERRAL_LIST, steps={5: [pagination]})
    limit, offset = ctx.state["page"]
    rows = store.all_rows("referral")
    for key in ("patient_id", "offering_id", "opened_by_chw_id", "parent_referral_id",
                "root_referral_id", "status"):
        wanted = ctx.args.get(key)
        if wanted is not None:
            rows = [r for r in rows if r.get(key) == wanted]
    page, total = v.paginate(rows, limit, offset)
    return listing(dump_all(page), limit, offset, total)


def _partner_owns(ctx):
    referral = ctx.row("referral_id")
    offering = store.get("offering", referral.get("offering_id"))
    if offering is None or ctx.user_id != offering.get("resource_org_id"):
        raise ApiError(ERR_NOT_RESOURCE_OWNER, "Referral belongs to another organization")


@bp.post("/chw/referrals/<referral_id>/respond")
def respond_referral(referral_id):
    def payload(ctx):
        ctx.state["decision"] = v.req_enum(ctx.body, "decision", DECISIONS)
        ctx.state["decline_reason"] = v.opt_str(ctx.body, "decline_reason")

    def target_state(ctx):
        if ctx.row("referral_id")["status"] != "SENT":
            raise ApiError(ERR_INVALID_STATE, "Only a SENT referral may be responded to")

    ctx = run(EP_REFERRAL_RESPOND, {"referral_id": referral_id},
              steps={5: [payload], 8: [target_state], 10: [_partner_owns]})
    referral = ctx.row("referral_id")
    if ctx.state["decision"] == "ACCEPTED":
        referral["status"] = "ACCEPTED"
        store.touch(referral)
    else:
        referral["status"] = "DECLINED"
        referral["decline_reason"] = ctx.state["decline_reason"]
        store.touch(referral)
        offering = store.get("offering", referral.get("offering_id"))
        if offering is not None:
            cascades.release_hold(referral, offering, "released_units")
        cascades.bump_unfulfilled(store.get("patient", referral["patient_id"]), referral)
    return ok(dump(referral))


@bp.post("/chw/referrals/<referral_id>/deliver")
def deliver_referral(referral_id):
    def target_state(ctx):
        if ctx.row("referral_id")["status"] != "ACCEPTED":
            raise ApiError(ERR_INVALID_STATE, "Only an ACCEPTED referral may be delivered")

    ctx = run(EP_REFERRAL_DELIVER, {"referral_id": referral_id},
              steps={8: [target_state], 10: [_partner_owns]})
    referral = ctx.row("referral_id")
    referral["status"] = "SERVICE_DELIVERED"
    referral["delivered_at"] = clock.now_raw()
    store.touch(referral)
    offering = store.get("offering", referral.get("offering_id"))
    if offering is not None:
        cascades.consume_hold(referral, offering)
    return ok(dump(referral))


@bp.post("/chw/referrals/<referral_id>/close")
def close_referral(referral_id):
    def payload(ctx):
        ctx.state["outcome_note"] = v.req_str(ctx.body, "outcome_note")

    def target_state(ctx):
        if ctx.row("referral_id")["status"] not in ("SERVICE_DELIVERED", "DECLINED"):
            raise ApiError(ERR_INVALID_STATE,
                           "Only a SERVICE_DELIVERED or DECLINED referral may be closed")

    ctx = run(EP_REFERRAL_CLOSE, {"referral_id": referral_id},
              steps={5: [payload], 8: [target_state]})
    referral = ctx.row("referral_id")
    referral["status"] = "CLOSED"
    referral["closed_at"] = clock.now_raw()
    referral["outcome_note"] = ctx.state["outcome_note"]
    store.touch(referral)
    return ok(dump(referral))


@bp.post("/chw/referrals/<referral_id>/reroute")
def reroute_referral(referral_id):
    def payload(ctx):
        s = ctx.state
        s["offering_id"] = v.req_str(ctx.body, "offering_id")
        s["urgency"] = v.req_enum(ctx.body, "urgency", URGENCIES)
        s["units_requested"] = v.req_int(ctx.body, "units_requested", minimum=1)
        s["expected_offering_version"] = v.req_int(ctx.body, "expected_offering_version")

    def body_refs(ctx):
        offering = store.get("offering", ctx.state["offering_id"])
        if offering is None:
            raise ApiError(ERR_RESOURCE_NOT_FOUND, "offering_id does not resolve")
        ctx.state["offering"] = offering
        ctx.state["patient"] = store.get("patient", ctx.row("referral_id")["patient_id"])

    def occ(ctx):
        if ctx.state["expected_offering_version"] != ctx.state["offering"]["version"]:
            raise ApiError(ERR_STALE_OFFERING_VERSION, "expected_offering_version is stale")

    def target_state(ctx):
        if ctx.row("referral_id")["status"] != "DECLINED":
            raise ApiError(ERR_INVALID_STATE, "Only a DECLINED referral may be re-routed")

    def reroute_limit(ctx):
        if ctx.row("referral_id").get("reroute_count", 0) >= calc.MAX_REROUTE_COUNT:
            raise ApiError(ERR_REROUTE_LIMIT_EXCEEDED, "The chain's re-route budget is exhausted")

    ctx = run(EP_REFERRAL_REROUTE, {"referral_id": referral_id}, steps={
        5: [payload], 6: [body_refs], 7: [occ], 8: [target_state],
        9: [_org_and_enrollment], 12: [_eligibility_step], 14: [reroute_limit],
        16: [_capacity_step],
    })
    s = ctx.state
    parent = ctx.row("referral_id")
    child = _new_referral(s["patient"], s["offering"], parent["opened_by_chw_id"],
                          s["urgency"], s["units_requested"], parent=parent)
    root_id = child["root_referral_id"]
    for row in store.all_rows("referral"):
        if row["id"] == child["id"]:
            continue
        if row.get("root_referral_id") == root_id:
            row["reroute_count"] = child["reroute_count"]
            store.touch(row)
    return created(dump(child))
