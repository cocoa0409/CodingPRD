"""Permits: the two status axes, renewal, revocation and reinstatement (3.5, 3.8)."""
from flask import Blueprint, request

import db
from body import Body
from errors import invalid_request, invalid_state, raise_err
from gates import (P_BODY, P_OUTSTANDING_INVOICE, P_OWNER, P_PATH,
                   P_PERFORMER_BARRED, P_PERMIT_SUSPENDED, P_RENEWAL_CONDUCT,
                   P_RENEWAL_WINDOW, P_STATE, resolve, run_gates)
from listing import listing, paged
from middleware import PERFORMER, PERMIT_OFFICER, require_owner, require_roles
from response import ok_object
from services import calc, domain
from services.serializers import serialize
from utils import renewal_window_open_at, season_end_utc, touch

bp = Blueprint("permits", __name__, url_prefix="/busking")

REFUND_MODES = {"PRORATED_REFUND", "FULL_REFUND"}


@bp.get("/permits/<permit_id>")
def read_permit(permit_id):
    user_id, role = require_roles([PERMIT_OFFICER, PERFORMER])
    ctx = {}
    run_gates([
        (P_PATH, lambda: ctx.update(permit=resolve("permits", permit_id))),
        (P_OWNER, lambda: require_owner(role, user_id, ctx["permit"]["performer_id"])),
    ])
    return ok_object(serialize(ctx["permit"]))


@bp.get("/permits")
def list_permits():
    require_roles([PERMIT_OFFICER, PERFORMER])
    return listing("permits",
                   ["performer_id", "application_id", "lifecycle_status",
                    "compliance_status", "season_year"],
                   request.args)


@bp.get("/permits/<permit_id>/fee-invoices")
def list_invoices(permit_id):
    user_id, role = require_roles([PERMIT_OFFICER, PERFORMER])
    ctx = {}
    run_gates([
        (P_PATH, lambda: ctx.update(permit=resolve("permits", permit_id))),
        (P_OWNER, lambda: require_owner(role, user_id, ctx["permit"]["performer_id"])),
    ])
    rows = domain.permit_invoices(ctx["permit"])
    for param in ("status", "invoice_kind"):
        value = request.args.get(param)
        if value is not None:
            rows = [row for row in rows if row[param] == value]
    return paged(rows, request.args)


@bp.post("/permits/<permit_id>/renew")
def renew_permit(permit_id):
    user_id, role = require_roles([PERFORMER])
    body = Body(request.get_json(silent=True))
    ctx = {}

    def check_body():
        season_year = body.req_int("season_year")
        if season_year != ctx["permit"]["season_year"] + 1:
            invalid_request("season_year must be exactly one greater than the permit's season")
        ctx["season_year"] = season_year

    def check_state():
        permit = ctx["permit"]
        if permit["lifecycle_status"] != "ACTIVE":
            invalid_state("Only an ACTIVE permit can open a renewal")
        if permit["compliance_status"] == "WARNED":
            invalid_state("The permit's compliance axis must be CLEAR to renew")

    def check_suspended():
        if ctx["permit"]["compliance_status"] == "SUSPENDED":
            raise_err("ERR_PERMIT_SUSPENDED", "A suspended permit cannot be renewed")

    def check_window():
        permit = ctx["permit"]
        clock = db.now()
        opens = renewal_window_open_at(permit["season_year"])
        closes = season_end_utc(permit["season_year"])
        if not (opens <= clock <= closes):
            raise_err("ERR_RENEWAL_WINDOW_CLOSED",
                      "The renewal window for this season is not open")

    def check_outstanding():
        if domain.has_outstanding_invoice(ctx["permit"]):
            raise_err("ERR_OUTSTANDING_INVOICE", "The permit carries an unsettled invoice")

    def check_conduct():
        performer = domain.performer_of(ctx["permit"])
        if performer["renewal_conduct_score"] < calc.RENEWAL_MIN_CONDUCT:
            raise_err("ERR_RENEWAL_CONDUCT_INSUFFICIENT",
                      "The career-weighted conduct score is below the renewal gate")

    run_gates([
        (P_PATH, lambda: ctx.update(permit=resolve("permits", permit_id))),
        (P_OWNER, lambda: require_owner(role, user_id, ctx["permit"]["performer_id"])),
        (P_BODY, check_body),
        (P_STATE, check_state),
        (P_PERMIT_SUSPENDED, check_suspended),
        (P_RENEWAL_WINDOW, check_window),
        (P_OUTSTANDING_INVOICE, check_outstanding),
        (P_RENEWAL_CONDUCT, check_conduct),
    ])

    permit = ctx["permit"]
    application = db.get("applications", permit["application_id"])
    permit["lifecycle_status"] = "RENEWAL_PENDING"
    permit["next_season_year"] = ctx["season_year"]
    domain.mint_invoice(permit, "RENEWAL",
                        application["requested_act_type"], permit["amplification_endorsed"])
    touch(permit)
    return ok_object(serialize(permit))


@bp.post("/permits/<permit_id>/revoke")
def revoke_permit(permit_id):
    require_roles([PERMIT_OFFICER])
    body = Body(request.get_json(silent=True))
    ctx = {}

    def check_body():
        ctx["reason"] = body.req_str("reason")
        ctx["refund_mode"] = body.opt_enum("refund_mode", REFUND_MODES, "PRORATED_REFUND")

    def check_state():
        if ctx["permit"]["lifecycle_status"] not in ("PENDING_FEE", "ACTIVE", "RENEWAL_PENDING"):
            invalid_state("This permit can no longer be revoked")

    run_gates([
        (P_PATH, lambda: ctx.update(permit=resolve("permits", permit_id))),
        (P_BODY, check_body),
        (P_STATE, check_state),
    ])

    domain.revoke_permit(ctx["permit"], ctx["refund_mode"])
    return ok_object(serialize(ctx["permit"]))


@bp.post("/permits/<permit_id>/reinstate")
def reinstate_permit(permit_id):
    require_roles([PERMIT_OFFICER])
    body = Body(request.get_json(silent=True))
    ctx = {}

    def check_body():
        ctx["note"] = body.opt_str("note")

    def check_state():
        if ctx["permit"]["compliance_status"] not in ("WARNED", "SUSPENDED"):
            invalid_state("Only a WARNED or SUSPENDED permit can be reinstated")

    def check_barred():
        performer = domain.performer_of(ctx["permit"])
        if performer["standing"] == "BARRED":
            raise_err("ERR_PERFORMER_BARRED",
                      "The holder is barred and the permit cannot be reinstated")

    run_gates([
        (P_PATH, lambda: ctx.update(permit=resolve("permits", permit_id))),
        (P_BODY, check_body),
        (P_STATE, check_state),
        (P_PERFORMER_BARRED, check_barred),
    ])

    permit = ctx["permit"]
    was_suspended = permit["compliance_status"] == "SUSPENDED"
    permit["compliance_status"] = "CLEAR"
    permit["noise_violation_count"] = 0
    if was_suspended:
        permit["suspended_at"] = None
    touch(permit)
    return ok_object(serialize(permit))
