"""Offer letters list, offer events, delegation grants, logical clock."""

from datetime import datetime, timezone

from flask import Blueprint, request

import db
from errors import (
    raise_err, ERR_OFFER_NOT_FOUND, ERR_NOT_RESOURCE_OWNER,
    ERR_DELEGATION_GRANT_NOT_FOUND, ERR_INVALID_REQUEST, ERR_GRANT_OVERLAP,
    ERR_GRANT_SELF_DELEGATION,
)
from middleware import (
    get_actor, require_role, get_json_body, validate_fields, req_string,
    req_enum, get_pagination, paginate,
)
from response import success
from services import calc

bp = Blueprint("misc", __name__)

LETTER_READ_ROLES = ["Recruiter", "HiringManager", "CompAnalyst",
                     "DepartmentDirector", "VPPeople", "HRAdmin", "Candidate"]
EVENT_READ_ROLES = ["Recruiter", "HiringManager", "CompAnalyst",
                    "DepartmentDirector", "VPPeople", "HRAdmin", "BackgroundScreener"]
GRANT_SCOPE_ROLES = ["CompAnalyst", "DepartmentDirector", "VPPeople"]


def _parse_iso(s):
    if not isinstance(s, str):
        raise_err(ERR_INVALID_REQUEST, "timestamp must be an ISO 8601 string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, "invalid ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@bp.route("/api/_clock/set_current_utc", methods=["POST"])
def set_clock():
    uid, role = get_actor()
    body = get_json_body()
    validate_fields(body, ["to_iso8601"], [])
    dt = _parse_iso(body.get("to_iso8601"))
    require_role(role, ["HRAdmin"])
    db.clock_set(dt)
    return success({"current_utc": db.clock_now_iso()})


@bp.route("/api/offers/<offer_id>/letters", methods=["GET"])
def list_letters(offer_id):
    uid, role = get_actor()
    require_role(role, LETTER_READ_ROLES)
    offer = db.offers.get(offer_id)
    if offer is None:
        raise_err(ERR_OFFER_NOT_FOUND, "Offer not found")
    if role == "Candidate" and offer["candidate_id"] != uid:
        raise_err(ERR_NOT_RESOURCE_OWNER, "Candidates may only view their own letters")
    items = sorted(
        [l for l in db.offer_letters.values() if l["offer_id"] == offer_id],
        key=lambda l: l["sequence"],
    )
    return success(items, response_type="array")


@bp.route("/api/offers/<offer_id>/events", methods=["GET"])
def list_events(offer_id):
    uid, role = get_actor()
    require_role(role, EVENT_READ_ROLES)
    limit, offset = get_pagination()
    offer = db.offers.get(offer_id)
    if offer is None:
        raise_err(ERR_OFFER_NOT_FOUND, "Offer not found")
    items = sorted(
        [e for e in db.offer_events.values() if e["offer_id"] == offer_id],
        key=lambda e: e["sequence"],
    )
    et = request.args.get("event_type")
    if et is not None:
        items = [e for e in items if e["event_type"] == et]
    page, pg = paginate(items, limit, offset)
    return success(list(page), response_type="array", pagination=pg)


@bp.route("/api/delegation-grants", methods=["POST"])
def create_grant():
    uid, role = get_actor()
    body = get_json_body()
    validate_fields(body,
                    ["grantor_user_id", "delegate_user_id", "scope_role",
                     "valid_from", "valid_until"],
                    [])
    grantor = req_string(body, "grantor_user_id")
    delegate = req_string(body, "delegate_user_id")
    scope = req_enum(body, "scope_role", GRANT_SCOPE_ROLES)
    vf = _parse_iso(body.get("valid_from"))
    vu = _parse_iso(body.get("valid_until"))
    require_role(role, ["HRAdmin"])
    if grantor == delegate or vu <= vf:
        raise_err(ERR_GRANT_SELF_DELEGATION,
                  "grantor must differ from delegate and valid_until must follow valid_from")
    for g in db.delegation_grants.values():
        if (g["delegate_user_id"] == delegate and g["scope_role"] == scope
                and g["status"] == "ACTIVE"):
            # half-open window overlap; adjacency allowed
            if vf < g["valid_until"] and g["valid_from"] < vu:
                raise_err(ERR_GRANT_OVERLAP, "Delegation window overlaps an existing ACTIVE grant")
    ts = db.now_ms()
    grant = {
        "id": db.new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "grantor_user_id": grantor,
        "delegate_user_id": delegate,
        "scope_role": scope,
        "valid_from": vf,
        "valid_until": vu,
        "status": "ACTIVE",
    }
    db.delegation_grants[grant["id"]] = grant
    return success(_grant_json(grant), status=201)


def _grant_json(g):
    out = dict(g)
    out["valid_from"] = g["valid_from"].strftime("%Y-%m-%dT%H:%M:%SZ")
    out["valid_until"] = g["valid_until"].strftime("%Y-%m-%dT%H:%M:%SZ")
    return out


@bp.route("/api/delegation-grants", methods=["GET"])
def list_grants():
    uid, role = get_actor()
    require_role(role, ["HRAdmin", "VPPeople"])
    limit, offset = get_pagination()
    items = sorted(db.delegation_grants.values(), key=lambda g: g["created_at"])
    d = request.args.get("delegate_user_id")
    s = request.args.get("scope_role")
    st = request.args.get("status")
    if d is not None:
        items = [g for g in items if g["delegate_user_id"] == d]
    if s is not None:
        items = [g for g in items if g["scope_role"] == s]
    if st is not None:
        items = [g for g in items if g["status"] == st]
    page, pg = paginate(items, limit, offset)
    return success([_grant_json(g) for g in page], response_type="array", pagination=pg)


@bp.route("/api/delegation-grants/<grant_id>", methods=["GET"])
def get_grant(grant_id):
    uid, role = get_actor()
    require_role(role, ["HRAdmin"])
    g = db.delegation_grants.get(grant_id)
    if g is None:
        raise_err(ERR_DELEGATION_GRANT_NOT_FOUND, "Delegation grant not found")
    return success(_grant_json(g))


@bp.route("/api/delegation-grants/<grant_id>/revoke", methods=["POST"])
def revoke_grant(grant_id):
    uid, role = get_actor()
    if db.request_has_body():
        get_json_body()
    require_role(role, ["HRAdmin"])
    g = db.delegation_grants.get(grant_id)
    if g is None:
        raise_err(ERR_DELEGATION_GRANT_NOT_FOUND, "Delegation grant not found")
    g["status"] = "REVOKED"
    calc.touch(g)
    return success(_grant_json(g))
