"""Served-agency agreements, emergency activations, and roster endpoints
(PRD §3.4), including the supersede OCC rule and segregation of duties."""
from flask import Blueprint, request

import db
import services as svc
from errors import (
    ERR_ACTIVATION_IN_PROGRESS, ERR_ACTIVATION_NOT_OPEN, ERR_AGREEMENT_NOT_ACTIVE,
    ERR_ALREADY_ON_ROSTER, ERR_FORBIDDEN, ERR_INVALID_STATE,
    ERR_MEMBERSHIP_NOT_ACTIVE, ERR_REQUIRED_OPERATORS_EXCEED_AGREEMENT,
    ERR_ROSTER_ENTRY_INELIGIBLE, ERR_ROSTER_FULL, ERR_SOD_DEMOBILIZE,
    ERR_STALE_VERSION, ApiError,
)
from middleware import auth_context, require_role
from response import paginate, success
from util import (
    as_dt, as_enum, as_int, as_str, bad_request, body_json, need,
    reject_unknown_fields,
)

bp = Blueprint("emergency", __name__)

AGENCY_STATUSES = {"DRAFT", "ACTIVE", "EXPIRED", "TERMINATED"}
ACTIVATION_STATUSES = {"STANDBY", "ACTIVATED", "DEMOBILIZED", "CANCELLED"}
ROSTER_STATUSES = {"VOLUNTEERED", "CONFIRMED", "RELEASED", "WITHDRAWN", "NO_SHOW"}
ADMIN = {"ClubAdmin"}
EC = {"EmergencyCoordinator"}
AGENCY_READ = {"ClubAdmin", "EmergencyCoordinator"}
ACTIVATION_READ = {"ClubAdmin", "EmergencyCoordinator", "Member"}
ROSTER_RW = {"EmergencyCoordinator", "Member"}


def _auth(allowed):
    user_id, role = auth_context()
    require_role(role, allowed)
    return user_id, role


# ---------------------------------------------------------------------------
# Served-agency agreements
# ---------------------------------------------------------------------------

@bp.post("/served-agency-agreements")
def create_agency():
    _auth(ADMIN)
    body = body_json(request)
    reject_unknown_fields(body, {"agency_name", "max_operators",
                                 "effective_start", "effective_end"})
    agency_name = as_str(need(body, "agency_name"), "agency_name")
    max_operators = as_int(need(body, "max_operators"), "max_operators")
    if max_operators <= 0:
        bad_request("max_operators must be > 0")
    effective_start = as_dt(need(body, "effective_start"), "effective_start")
    effective_end = as_dt(need(body, "effective_end"), "effective_end")
    ag = {
        "agency_name": agency_name,
        "max_operators": max_operators,
        "effective_start": effective_start,
        "effective_end": effective_end,
        "status": "DRAFT",
    }
    svc.stamp_new(ag)
    db.STORE["agency_agreements"][ag["id"]] = ag
    return success(svc.ser_agency(ag), "object", 201)


@bp.get("/served-agency-agreements")
def list_agencies():
    _auth(AGENCY_READ)
    status = request.args.get("status")
    items = [svc.ser_agency(a) for a in svc.sorted_records("agency_agreements")
             if status is None or a["status"] == status]
    page, meta = paginate(items, request.args)
    return success(page, "array", 200, meta)


@bp.get("/served-agency-agreements/<aid>")
def get_agency(aid):
    _auth(AGENCY_READ)
    return success(svc.ser_agency(svc.get_agency(aid)), "object", 200)


@bp.post("/served-agency-agreements/<aid>/set-status")
def set_agency_status(aid):
    _auth(ADMIN)
    ag = svc.get_agency(aid)
    body = body_json(request)
    reject_unknown_fields(body, {"to"})
    to = as_enum(need(body, "to"), "to", AGENCY_STATUSES)
    current = ag["status"]
    if to == "ACTIVE":
        if current != "DRAFT":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "cannot activate agreement from %s" % current)
        if ag["effective_end"] <= db.now():
            raise ApiError(ERR_INVALID_STATE, 409,
                           "effective_end must be in the future to activate")
        ag["status"] = "ACTIVE"
        svc.touch(ag)
    elif to == "TERMINATED":
        if current not in ("DRAFT", "ACTIVE"):
            raise ApiError(ERR_INVALID_STATE, 409,
                           "cannot terminate agreement from %s" % current)
        if current == "ACTIVE":
            # Blocked while any activation under it is ACTIVATED.
            for act in db.STORE["activations"].values():
                if (act["agreement_id"] == ag["id"]
                        and act["status"] == "ACTIVATED"):
                    raise ApiError(ERR_ACTIVATION_IN_PROGRESS, 409,
                                   "an ACTIVATED activation exists for this agreement")
            ag["status"] = "TERMINATED"
            svc.touch(ag)
            for act in svc.sorted_records("activations"):
                if (act["agreement_id"] == ag["id"]
                        and act["status"] == "STANDBY"):
                    svc.cancel_activation_cascade(act)
        else:
            ag["status"] = "TERMINATED"
            svc.touch(ag)
    else:  # EXPIRED is system-only
        raise ApiError(ERR_INVALID_STATE, 409,
                       "cannot move agreement from %s to %s" % (current, to))
    return success(svc.ser_agency(ag), "object", 200)


# ---------------------------------------------------------------------------
# Emergency activations
# ---------------------------------------------------------------------------

@bp.post("/emergency-activations")
def create_activation():
    user_id, role = _auth(EC)
    body = body_json(request)
    reject_unknown_fields(body, {"agreement_id", "title", "required_operators",
                                 "expected_served_agency_agreement_version"})
    agreement_id = as_str(need(body, "agreement_id"), "agreement_id")
    agreement = svc.get_agency(agreement_id)  # body FK existence
    title = as_str(need(body, "title"), "title")
    required_operators = as_int(need(body, "required_operators"),
                                "required_operators")
    expected = as_int(need(body, "expected_served_agency_agreement_version"),
                      "expected_served_agency_agreement_version")
    # OCC (PRD §2.9): refuse to supersede on a stale view of the agreement.
    if expected != agreement["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_served_agency_agreement_version does not match "
                       "current version")
    if required_operators <= 0 or required_operators > agreement["max_operators"]:
        raise ApiError(ERR_REQUIRED_OPERATORS_EXCEED_AGREEMENT, 422,
                       "required_operators must be > 0 and <= agreement.max_operators")
    if agreement["status"] not in ("DRAFT", "ACTIVE"):
        raise ApiError(ERR_AGREEMENT_NOT_ACTIVE, 409,
                       "agreement must be DRAFT or ACTIVE at activation create")
    # Supersede: the prior STANDBY activation for this agreement is cancelled.
    for act in svc.sorted_records("activations"):
        if (act["agreement_id"] == agreement["id"]
                and act["status"] == "STANDBY"):
            svc.cancel_activation_cascade(act)
    svc.touch(agreement)
    act = {
        "agreement_id": agreement["id"],
        "title": title,
        "required_operators": required_operators,
        "status": "STANDBY",
        "activated_by_member_id": None,
        "activated_at": None,
        "demobilized_at": None,
    }
    svc.stamp_new(act)
    db.STORE["activations"][act["id"]] = act
    return success(svc.ser_activation(act), "object", 201)


@bp.get("/emergency-activations")
def list_activations():
    _auth(ACTIVATION_READ)
    agreement_id = request.args.get("agreement_id")
    activated_by = request.args.get("activated_by_member_id")
    status = request.args.get("status")
    items = []
    for a in svc.sorted_records("activations"):
        if agreement_id is not None and a["agreement_id"] != agreement_id:
            continue
        if activated_by is not None and a["activated_by_member_id"] != activated_by:
            continue
        if status is not None and a["status"] != status:
            continue
        items.append(svc.ser_activation(a))
    page, meta = paginate(items, request.args)
    return success(page, "array", 200, meta)


@bp.get("/emergency-activations/<aid>")
def get_activation(aid):
    _auth(ACTIVATION_READ)
    return success(svc.ser_activation(svc.get_activation(aid)), "object", 200)


@bp.post("/emergency-activations/<aid>/set-status")
def set_activation_status(aid):
    user_id, role = _auth(EC)
    act = svc.get_activation(aid)
    body = body_json(request)
    reject_unknown_fields(body, {"to"})
    to = as_enum(need(body, "to"), "to", ACTIVATION_STATUSES)
    current = act["status"]
    if to == "ACTIVATED":
        if current != "STANDBY":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "cannot activate from %s" % current)
        agreement = svc.get_agency(act["agreement_id"])
        if agreement["status"] != "ACTIVE":
            raise ApiError(ERR_AGREEMENT_NOT_ACTIVE, 409,
                           "agreement is not ACTIVE")
        act["status"] = "ACTIVATED"
        act["activated_by_member_id"] = user_id
        act["activated_at"] = db.now()
        svc.touch(act)
    elif to == "DEMOBILIZED":
        if current != "ACTIVATED":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "cannot demobilize from %s" % current)
        # Segregation of duties: demobilizer != activator (p5).
        if user_id == act["activated_by_member_id"]:
            raise ApiError(ERR_SOD_DEMOBILIZE, 403,
                           "demobilizer must differ from the activator")
        act["status"] = "DEMOBILIZED"
        act["demobilized_at"] = db.now()
        svc.touch(act)
        svc.resolve_roster_on_activation_close(act)
    elif to == "CANCELLED":
        if current != "STANDBY":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "cannot cancel an activation in status %s" % current)
        svc.cancel_activation_cascade(act)
    else:  # STANDBY is never a manual target
        raise ApiError(ERR_INVALID_STATE, 409,
                       "cannot move an activation from %s to %s" % (current, to))
    return success(svc.ser_activation(act), "object", 200)


# ---------------------------------------------------------------------------
# Roster entries
# ---------------------------------------------------------------------------

@bp.post("/roster-entries")
def create_roster_entry():
    user_id, role = _auth({"Member"})
    body = body_json(request)
    reject_unknown_fields(body, {"activation_id"})
    activation_id = as_str(need(body, "activation_id"), "activation_id")
    act = svc.get_activation(activation_id)  # body FK existence
    member = svc.get_member(user_id)
    if act["status"] not in ("STANDBY", "ACTIVATED"):
        raise ApiError(ERR_ACTIVATION_NOT_OPEN, 409,
                       "activation is not open for volunteers")
    for r in db.STORE["roster_entries"].values():
        if (r["activation_id"] == act["id"]
                and r["member_id"] == member["id"]):
            raise ApiError(ERR_ALREADY_ON_ROSTER, 409,
                           "member already has a roster entry on this activation")
    if member["membership_status"] != "ACTIVE":
        raise ApiError(ERR_MEMBERSHIP_NOT_ACTIVE, 409,
                       "membership_status is not ACTIVE")
    if svc.member_readiness(member)["readiness_tier"] == "INELIGIBLE":
        raise ApiError(ERR_ROSTER_ENTRY_INELIGIBLE, 409,
                       "member readiness_tier is INELIGIBLE")
    entry = {
        "activation_id": act["id"],
        "member_id": member["id"],
        "status": "VOLUNTEERED",
        "confirmed_at": None,
    }
    svc.stamp_new(entry)
    db.STORE["roster_entries"][entry["id"]] = entry
    return success(svc.ser_roster(entry), "object", 201)


@bp.get("/roster-entries")
def list_roster_entries():
    _auth(ACTIVATION_READ)
    activation_id = request.args.get("activation_id")
    member_id = request.args.get("member_id")
    status = request.args.get("status")
    items = []
    for r in svc.sorted_records("roster_entries"):
        if activation_id is not None and r["activation_id"] != activation_id:
            continue
        if member_id is not None and r["member_id"] != member_id:
            continue
        if status is not None and r["status"] != status:
            continue
        items.append(svc.ser_roster(r))
    page, meta = paginate(items, request.args)
    return success(page, "array", 200, meta)


@bp.get("/roster-entries/<rid>")
def get_roster_entry(rid):
    _auth(ACTIVATION_READ)
    return success(svc.ser_roster(svc.get_roster(rid)), "object", 200)


@bp.post("/roster-entries/<rid>/set-status")
def set_roster_status(rid):
    user_id, role = _auth(ROSTER_RW)
    entry = svc.get_roster(rid)
    body = body_json(request)
    reject_unknown_fields(body, {"to"})
    to = as_enum(need(body, "to"), "to", ROSTER_STATUSES)
    # Role/ownership gate: EC runs confirmations; members only withdraw their own.
    if role == "Member":
        if to != "WITHDRAWN" or entry["member_id"] != user_id:
            raise ApiError(ERR_FORBIDDEN, 403,
                           "members may only withdraw their own roster entry")
    else:  # EmergencyCoordinator
        if to == "WITHDRAWN":
            raise ApiError(ERR_FORBIDDEN, 403,
                           "withdrawal is performed by the owning member")
    act = svc.get_activation(entry["activation_id"])
    current = entry["status"]
    if to == "CONFIRMED":
        if current != "VOLUNTEERED":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "cannot confirm an entry in status %s" % current)
        if act["status"] not in ("STANDBY", "ACTIVATED"):
            raise ApiError(ERR_INVALID_STATE, 409,
                           "activation is not open for confirmation")
        member = svc.get_member(entry["member_id"])
        if member["membership_status"] != "ACTIVE":
            raise ApiError(ERR_MEMBERSHIP_NOT_ACTIVE, 409,
                           "membership_status is not ACTIVE")
        if svc.member_readiness(member)["readiness_tier"] == "INELIGIBLE":
            raise ApiError(ERR_ROSTER_ENTRY_INELIGIBLE, 409,
                           "member readiness_tier is INELIGIBLE")
        confirmed, _posture = svc.activation_staffing(act)
        if confirmed >= act["required_operators"]:
            raise ApiError(ERR_ROSTER_FULL, 409,
                           "activation roster is at required_operators")
        entry["status"] = "CONFIRMED"
        entry["confirmed_at"] = db.now()
        svc.touch(entry)
    elif to == "VOLUNTEERED":
        if current != "CONFIRMED":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "cannot revert an entry in status %s" % current)
        if act["status"] not in ("STANDBY", "ACTIVATED"):
            raise ApiError(ERR_INVALID_STATE, 409,
                           "activation is not open for revert")
        entry["status"] = "VOLUNTEERED"
        entry["confirmed_at"] = None
        svc.touch(entry)
    elif to == "RELEASED":
        if current != "CONFIRMED":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "cannot release an entry in status %s" % current)
        if act["status"] not in ("STANDBY", "ACTIVATED"):
            raise ApiError(ERR_INVALID_STATE, 409,
                           "activation is not open for release")
        entry["status"] = "RELEASED"
        svc.touch(entry)
    elif to == "NO_SHOW":
        if current != "CONFIRMED":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "cannot no-show an entry in status %s" % current)
        if act["status"] != "ACTIVATED":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "NO_SHOW requires the activation to be ACTIVATED")
        entry["status"] = "NO_SHOW"
        svc.touch(entry)
    else:  # WITHDRAWN (member self, from VOLUNTEERED)
        if current != "VOLUNTEERED":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "cannot withdraw an entry in status %s" % current)
        entry["status"] = "WITHDRAWN"
        svc.touch(entry)
    return success(svc.ser_roster(entry), "object", 200)
