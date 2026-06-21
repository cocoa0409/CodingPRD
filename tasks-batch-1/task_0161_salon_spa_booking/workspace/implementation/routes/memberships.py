"""Membership routes: enroll, fetch, list, lapse/reinstate/cancel (PRD §3.2)."""
from flask import Blueprint, request

import db
from errors import err
from lookups import get_or_404
from response import success
from util import stamp_create, touch, public
import validate as v
from routes.common import auth, json_body, list_response

bp = Blueprint("memberships", __name__)


@bp.post("/memberships")
def enroll():
    auth(("SalonOwner", "FrontDesk"))
    body = json_body()
    v.require_object(body)

    client_id = v.req_str(body, "client_id")
    plan_id = v.req_str(body, "plan_id")
    client = get_or_404(db.clients, client_id)
    plan = get_or_404(db.membership_plans, plan_id)

    membership = {
        "client_id": client["id"],
        "plan_id": plan["id"],
        "status": "ACTIVE",
    }
    stamp_create(membership)
    db.memberships[membership["id"]] = membership
    return success(public(membership), status=201)


@bp.get("/memberships/<membership_id>")
def get_membership(membership_id):
    auth(("SalonOwner", "FrontDesk", "Client"))
    membership = get_or_404(db.memberships, membership_id)
    return success(public(membership), status=200)


@bp.get("/memberships")
def list_memberships():
    auth(("SalonOwner", "FrontDesk", "Client"))
    client_id = request.args.get("client_id")
    plan_id = request.args.get("plan_id")
    status = request.args.get("status")

    def pred(m):
        if client_id is not None and m["client_id"] != client_id:
            return False
        if plan_id is not None and m["plan_id"] != plan_id:
            return False
        if status is not None and m["status"] != status:
            return False
        return True

    page, meta = list_response(db.memberships, pred)
    return success(page, status=200, response_type="array", pagination=meta)


@bp.post("/memberships/<membership_id>/lapse")
def lapse(membership_id):
    auth(("SalonOwner",))
    membership = get_or_404(db.memberships, membership_id)
    if membership["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "only an ACTIVE membership may lapse")
    membership["status"] = "PAST_DUE"
    touch(membership)
    return success(public(membership), status=200)


@bp.post("/memberships/<membership_id>/reinstate")
def reinstate(membership_id):
    auth(("SalonOwner",))
    membership = get_or_404(db.memberships, membership_id)
    if membership["status"] != "PAST_DUE":
        raise err("ERR_INVALID_STATE", "only a PAST_DUE membership may be reinstated")
    membership["status"] = "ACTIVE"
    touch(membership)
    return success(public(membership), status=200)


@bp.post("/memberships/<membership_id>/cancel")
def cancel(membership_id):
    auth(("SalonOwner",))
    membership = get_or_404(db.memberships, membership_id)
    if membership["status"] not in ("ACTIVE", "PAST_DUE"):
        raise err("ERR_INVALID_STATE", "membership cannot be cancelled from its current state")
    membership["status"] = "CANCELLED"
    touch(membership)
    return success(public(membership), status=200)
