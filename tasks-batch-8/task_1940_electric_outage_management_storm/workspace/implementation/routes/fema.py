"""FemaClaim endpoints: open, get, list, submit, certify, withdraw, obligate,
mark_paid. Segregation of duties: certifier must differ from preparer."""
from flask import Blueprint, request

from db import db
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from errors import (
    raise_err, ERR_INVALID_STATE_TRANSITION, ERR_EVENT_NOT_DEMOBILIZING,
    ERR_SEGREGATION_OF_DUTIES, ERR_FEMA_THRESHOLD_NOT_MET,
)
from services.core import (
    get_body, req_string, req_int, paginate, new_common, bump,
    get_event, get_claim, serialize_claim, sort_created_asc,
    fema_eligible_cost, check_event_not_closed,
)

bp = Blueprint("fema_claims", __name__)


@bp.route("/om/fema-claims", methods=["POST"])
def create_claim():
    require_roles(["ClaimsOfficer"])
    body = get_body()
    event_id = req_string(body, "storm_event_id")
    event = get_event(event_id)
    county = req_string(body, "county_code")
    threshold = req_int(body, "threshold_cents", minimum=0)
    check_event_not_closed(event)
    c = new_common()
    c.update({
        "storm_event_id": event_id,
        "county_code": county,
        "threshold_cents": threshold,
        "claim_status": "DRAFT",
        "eligible_snapshot_cents": None,
        "preparer_user_id": None,
        "certifier_user_id": None,
    })
    db.fema_claims[c["id"]] = c
    return success_object(serialize_claim(c), status=201)


@bp.route("/om/fema-claims/<cid>", methods=["GET"])
def get_one(cid):
    require_roles(ALL_ROLES)
    c = get_claim(cid)
    return success_object(serialize_claim(c))


@bp.route("/om/fema-claims", methods=["GET"])
def list_claims():
    require_roles(ALL_ROLES)
    items = list(db.fema_claims.values())
    event_id = request.args.get("storm_event_id")
    status = request.args.get("claim_status")
    if event_id is not None:
        items = [c for c in items if c["storm_event_id"] == event_id]
    if status is not None:
        items = [c for c in items if c["claim_status"] == status]
    items = sort_created_asc(items)
    page, limit, offset, total = paginate(items)
    return success_list([serialize_claim(c) for c in page], limit, offset, total)


@bp.route("/om/fema-claims/<cid>/submit", methods=["POST"])
def submit(cid):
    user_id, _ = require_roles(["ClaimsOfficer"])
    c = get_claim(cid)
    if c["claim_status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  f"Claim in {c['claim_status']} cannot be submitted")
    event = get_event(c["storm_event_id"])
    if event["event_status"] not in ("DEMOBILIZING", "CLOSED"):
        raise_err(ERR_EVENT_NOT_DEMOBILIZING,
                  "FEMA submit requires the event DEMOBILIZING or CLOSED")
    eligible = fema_eligible_cost(c)
    if eligible < c["threshold_cents"]:
        raise_err(ERR_FEMA_THRESHOLD_NOT_MET,
                  "eligible_cost_cents is below threshold_cents")
    c["claim_status"] = "SUBMITTED"
    c["preparer_user_id"] = user_id
    c["eligible_snapshot_cents"] = eligible
    bump(c)
    return success_object(serialize_claim(c))


@bp.route("/om/fema-claims/<cid>/certify", methods=["POST"])
def certify(cid):
    user_id, _ = require_roles(["ClaimsOfficer"])
    c = get_claim(cid)
    if c["claim_status"] != "SUBMITTED":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  f"Claim in {c['claim_status']} cannot be certified")
    if user_id == c["preparer_user_id"]:
        raise_err(ERR_SEGREGATION_OF_DUTIES,
                  "Certifier must differ from the preparer")
    c["claim_status"] = "CERTIFIED"
    c["certifier_user_id"] = user_id
    bump(c)
    return success_object(serialize_claim(c))


@bp.route("/om/fema-claims/<cid>/withdraw", methods=["POST"])
def withdraw(cid):
    require_roles(["ClaimsOfficer"])
    c = get_claim(cid)
    body = get_body()
    permanent = body.get("permanent", False)
    if permanent is None:
        permanent = False
    if not isinstance(permanent, bool):
        from errors import ERR_INVALID_REQUEST
        raise_err(ERR_INVALID_REQUEST, "permanent must be a boolean")
    if permanent:
        if c["claim_status"] not in ("DRAFT", "SUBMITTED"):
            raise_err(ERR_INVALID_STATE_TRANSITION,
                      f"Claim in {c['claim_status']} cannot be withdrawn")
        c["claim_status"] = "WITHDRAWN"
    else:
        if c["claim_status"] != "SUBMITTED":
            raise_err(ERR_INVALID_STATE_TRANSITION,
                      f"Claim in {c['claim_status']} cannot be returned to DRAFT")
        c["claim_status"] = "DRAFT"
        c["preparer_user_id"] = None
        c["eligible_snapshot_cents"] = None
    bump(c)
    return success_object(serialize_claim(c))


@bp.route("/om/fema-claims/<cid>/obligate", methods=["POST"])
def obligate(cid):
    require_roles(["Regulator"])
    c = get_claim(cid)
    if c["claim_status"] != "CERTIFIED":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  f"Claim in {c['claim_status']} cannot be obligated")
    c["claim_status"] = "OBLIGATED"
    bump(c)
    return success_object(serialize_claim(c))


@bp.route("/om/fema-claims/<cid>/mark_paid", methods=["POST"])
def mark_paid(cid):
    require_roles(["Regulator"])
    c = get_claim(cid)
    if c["claim_status"] != "OBLIGATED":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  f"Claim in {c['claim_status']} cannot be marked paid")
    c["claim_status"] = "PAID"
    bump(c)
    return success_object(serialize_claim(c))
