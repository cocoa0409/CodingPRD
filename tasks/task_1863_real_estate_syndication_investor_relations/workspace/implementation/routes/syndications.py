"""Syndication lifecycle (PRD 3.1)."""
from flask import Blueprint

import resolve
from db import db
from errors import raise_error
from middleware import SPONSOR, ALL_ROLES, endpoint
from response import success_list, success_object
from serializers import ser_syndication
from services.domain import stamp_new, touch, sorted_items
from validate import get_body, req_number, req_str, opt_version, pagination

bp = Blueprint("syndications", __name__)

RS = {"strict_slashes": False}


@bp.route("/syndications", methods=["POST"], **RS)
@endpoint(SPONSOR)
def create_syndication(caller):
    body = get_body()
    o = {
        "syndication_name": req_str(body, "syndication_name"),
        "sponsor_legal_entity": req_str(body, "sponsor_legal_entity"),
        "preferred_return_pct_annual": req_number(body, "preferred_return_pct_annual", minimum=0),
        "carried_interest_pct": req_number(body, "carried_interest_pct", minimum=0),
        "status": "DRAFT",
    }
    stamp_new(o)
    db["syndications"][o["id"]] = o
    return success_object(ser_syndication(o), 201)


@bp.route("/syndications", methods=["GET"], **RS)
@endpoint(*ALL_ROLES)
def list_syndications(caller):
    limit, offset = pagination()
    items = sorted_items(db["syndications"].values())
    page = items[offset:offset + limit]
    return success_list([ser_syndication(o) for o in page], len(items), limit, offset)


@bp.route("/syndications/<syndicationId>", methods=["GET"], **RS)
@endpoint(*ALL_ROLES)
def get_syndication(caller, syndicationId):
    return success_object(ser_syndication(resolve.syndication(syndicationId)))


def _check_version(body, syn):
    opt_version(body, "expected_syndication_version", syn["version"],
                "ERR_STALE_SYNDICATION_VERSION")


@bp.route("/syndications/<syndicationId>/activate", methods=["POST"], **RS)
@endpoint(SPONSOR)
def activate_syndication(caller, syndicationId):
    syn = resolve.syndication(syndicationId)
    body = get_body()
    _check_version(body, syn)
    if syn["status"] not in ("DRAFT", "SUSPENDED"):
        raise_error("ERR_INVALID_STATE",
                    f"cannot activate a syndication in status {syn['status']}")
    syn["status"] = "ACTIVE"
    touch(syn)
    return success_object(ser_syndication(syn))


@bp.route("/syndications/<syndicationId>/suspend", methods=["POST"], **RS)
@endpoint(SPONSOR)
def suspend_syndication(caller, syndicationId):
    syn = resolve.syndication(syndicationId)
    body = get_body()
    _check_version(body, syn)
    if syn["status"] != "ACTIVE":
        raise_error("ERR_INVALID_STATE",
                    f"cannot suspend a syndication in status {syn['status']}")
    syn["status"] = "SUSPENDED"
    touch(syn)
    # Cascade: every OPEN offering under this syndication closes to new subscriptions.
    for off in db["offerings"].values():
        if off["syndication_id"] == syn["id"] and off["status"] == "OPEN":
            off["status"] = "CLOSED_TO_NEW_SUBSCRIPTIONS"
            touch(off)
    return success_object(ser_syndication(syn))


@bp.route("/syndications/<syndicationId>/close", methods=["POST"], **RS)
@endpoint(SPONSOR)
def close_syndication(caller, syndicationId):
    syn = resolve.syndication(syndicationId)
    body = get_body()
    _check_version(body, syn)
    if syn["status"] != "ACTIVE":
        raise_error("ERR_INVALID_STATE",
                    f"cannot close a syndication in status {syn['status']}")
    offs = [o for o in db["offerings"].values() if o["syndication_id"] == syn["id"]]
    if any(o["status"] not in ("FINAL_CLOSE", "DISSOLVED") for o in offs):
        raise_error("ERR_SYNDICATION_HAS_OPEN_OFFERINGS",
                    "all offerings must be FINAL_CLOSE or DISSOLVED before close")
    syn["status"] = "CLOSED"
    touch(syn)
    # Cascade: every non-terminal subscription beneath this syndication withdraws.
    off_ids = {o["id"] for o in offs}
    for s in db["subscriptions"].values():
        if s["offering_id"] in off_ids and s["status"] not in ("FUNDED", "WITHDRAWN"):
            s["status"] = "WITHDRAWN"
            touch(s)
    return success_object(ser_syndication(syn))
