"""Client endpoints: register, list, read, transition."""
from flask import Blueprint

import db
import errors as E
import middleware as mw
from middleware import (get_auth, require_roles, require_family_scope, get_body,
                        require_fields, get_entity, touch, new_common, client_pub,
                        list_response, parse_date)
from response import success_object
from services import billing

bp = Blueprint("clients", __name__)


@bp.post("/families/<fid>/clients")
def create_client(fid):
    auth = get_auth()
    require_roles(auth, ["PracticeAdmin", "FamilyMember"])
    require_family_scope(auth, fid)
    fam = get_entity("family", fid)
    body = get_body()
    require_fields(body, ["full_name", "date_of_birth", "track"])
    mw.enum_check(body["track"], ["INDIVIDUAL", "GROUP", "HYBRID"], "track")
    parse_date(body["date_of_birth"], "date_of_birth")
    c = new_common()
    c.update({
        "family_id": fid,
        "full_name": body["full_name"],
        "date_of_birth": body["date_of_birth"],
        "track": body["track"],
        "status": "INTAKE",
        "active_plan_id": None,
        "checkin_streak": 0,
        "rolling_progress_index": None,
        "cumulative_progress_index": None,
    })
    db.clients[c["id"]] = c
    return success_object(client_pub(c), 201)


@bp.get("/families/<fid>/clients")
def list_clients(fid):
    auth = get_auth()
    require_roles(auth, ["PracticeAdmin", "FamilyMember"])
    require_family_scope(auth, fid)
    get_entity("family", fid)
    rows = [c for c in db.clients.values() if c["family_id"] == fid]
    return list_response(rows, client_pub, paginate=False)


@bp.get("/clients/<cid>")
def get_client(cid):
    auth = get_auth()
    require_roles(auth, ["PracticeAdmin", "Coach", "FamilyMember"])
    c = get_entity("client", cid)
    require_family_scope(auth, c["family_id"])
    return success_object(client_pub(c), 200)


@bp.post("/clients/<cid>/transition")
def client_transition(cid):
    auth = get_auth()
    require_roles(auth, ["PracticeAdmin"])
    c = get_entity("client", cid)
    body = get_body()
    require_fields(body, ["to_state"])
    to = body["to_state"]
    mw.enum_check(to, ["PAUSED", "ACTIVE", "DISCHARGED"], "to_state")

    if to == "PAUSED":
        if c["status"] != "ACTIVE":
            E.raise_error(E.ERR_INVALID_STATE,
                          "Cannot transition client from %s to PAUSED" % c["status"])
        c["status"] = "PAUSED"
        touch(c)
        _recompute_active_plan_posture(c)

    elif to == "ACTIVE":
        if c["status"] != "PAUSED":
            E.raise_error(E.ERR_INVALID_STATE,
                          "Cannot transition client from %s to ACTIVE" % c["status"])
        fam = db.families[c["family_id"]]
        if fam["status"] != "ACTIVE":
            E.raise_error(E.ERR_FAMILY_NOT_ACTIVE, "Family is not ACTIVE")
        c["status"] = "ACTIVE"
        touch(c)
        _recompute_active_plan_posture(c)

    else:  # DISCHARGED
        if c["status"] not in ("ACTIVE", "PAUSED"):
            E.raise_error(E.ERR_INVALID_STATE,
                          "Cannot transition client from %s to DISCHARGED" % c["status"])
        if any(p["client_id"] == cid and p["status"] == "ACTIVE" for p in db.plans.values()):
            E.raise_error(E.ERR_CLIENT_HAS_ACTIVE_PLAN,
                          "Client has an ACTIVE coaching plan")
        # Session-release cascade over all of the client's plans.
        billing.cancel_sessions_early(billing.scheduled_sessions_of_client(cid))
        c["status"] = "DISCHARGED"
        c["active_plan_id"] = None
        touch(c)

    return success_object(client_pub(c), 200)


def _recompute_active_plan_posture(client):
    if client["active_plan_id"] and client["active_plan_id"] in db.plans:
        billing.recompute_plan_posture(db.plans[client["active_plan_id"]])
