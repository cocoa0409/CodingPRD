"""Sourcing events and bidder invitations (PRD 3.7)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_AWARD_ABOVE_LIMIT,
    ERR_DUPLICATE_INVITATION,
    ERR_FORBIDDEN_FOR_ROLE,
    ERR_INCLUSION_SHORTFALL,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_SUPPLIER_NOT_ELIGIBLE,
)
from middleware import authorized
from response import success_object
from routes.helpers import list_response
from services.core import (
    make_record,
    touch,
    pub_sourcing_event,
    pub_invitation,
    recompute_event_bid_count,
)
from validate import get_body, req_str, req_int, opt_int, opt_str, get_resource

bp = Blueprint("sourcing", __name__)

EVENT_WRITERS = ["BusinessUnitLead", "DiversityAdmin"]
READERS = ["DiversityAdmin", "DiversityAnalyst", "BusinessUnitLead", "Auditor"]


def _check_bu_scope(caller, event):
    """BusinessUnitLead callers act only on events of their own BU."""
    if caller.role == "BusinessUnitLead":
        bu = db["business_units"].get(event["business_unit_id"])
        if bu is None or bu["lead_user_id"] != caller.user_id:
            raise_error(
                ERR_FORBIDDEN_FOR_ROLE,
                "BusinessUnitLead may act only on events of its own business unit",
            )


def _find_invitation(event_id, supplier_id):
    for inv in db["invitations"].values():
        if inv["sourcing_event_id"] == event_id and inv["supplier_id"] == supplier_id:
            return inv
    return None


@bp.route("/api/v1/sourcing-events", methods=["POST"])
def create_sourcing_event():
    caller = authorized(EVENT_WRITERS)
    body = get_body()
    business_unit_id = req_str(body, "business_unit_id")
    bu = get_resource("business_units", business_unit_id)
    if caller.role == "BusinessUnitLead" and caller.user_id != bu["lead_user_id"]:
        raise_error(
            ERR_FORBIDDEN_FOR_ROLE,
            "BusinessUnitLead may create events only for its own business unit",
        )
    title = req_str(body, "title")
    estimated_value_cents = req_int(body, "estimated_value_cents", minimum=1)
    required = opt_int(
        body, "required_diverse_bidders",
        default=bu["inclusion_min_diverse_bidders"], minimum=0, maximum=10,
    )
    rec = make_record({
        "business_unit_id": bu["id"],
        "title": title,
        "estimated_value_cents": estimated_value_cents,
        "required_diverse_bidders": required,
        "award_supplier_id": None,
        "award_amount_cents": None,
        "inclusion_waiver_reason": None,
        "diverse_bid_count": 0,
        "status": "DRAFT",
    })
    db["sourcing_events"][rec["id"]] = rec
    return success_object(pub_sourcing_event(rec), status=201)


@bp.route("/api/v1/sourcing-events", methods=["GET"])
def list_sourcing_events():
    authorized(READERS)
    filters = {
        "business_unit_id": request.args.get("business_unit_id"),
        "status": request.args.get("status"),
    }
    return list_response(list(db["sourcing_events"].values()), filters, pub_sourcing_event)


@bp.route("/api/v1/sourcing-events/<rid>", methods=["GET"])
def get_sourcing_event(rid):
    authorized(READERS)
    rec = get_resource("sourcing_events", rid)
    return success_object(pub_sourcing_event(rec))


@bp.route("/api/v1/sourcing-events/<rid>/open", methods=["POST"])
def open_sourcing_event(rid):
    caller = authorized(EVENT_WRITERS)
    event = get_resource("sourcing_events", rid)
    _check_bu_scope(caller, event)
    if event["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, "open requires status DRAFT")
    event["status"] = "OPEN"
    touch(event)
    return success_object(pub_sourcing_event(event))


@bp.route("/api/v1/sourcing-events/<rid>/award", methods=["POST"])
def award_sourcing_event(rid):
    caller = authorized(EVENT_WRITERS)
    event = get_resource("sourcing_events", rid)
    body = get_body()
    waiver = opt_str(body, "inclusion_waiver_reason")
    if isinstance(waiver, str) and waiver.strip() == "":
        waiver = None
    # Role/scope rung: BU ownership; waivers are DiversityAdmin-only.
    if caller.role == "BusinessUnitLead":
        _check_bu_scope(caller, event)
        if waiver is not None:
            raise_error(
                ERR_FORBIDDEN_FOR_ROLE,
                "inclusion waivers may be supplied only by DiversityAdmin",
            )
    award_supplier_id = req_str(body, "award_supplier_id")
    supplier = get_resource("suppliers", award_supplier_id)
    # State rung.
    if event["status"] != "OPEN":
        raise_error(ERR_INVALID_STATE, "award requires status OPEN")
    # Eligibility rung: winner must hold a BID_SUBMITTED invitation and be ACTIVE.
    invitation = _find_invitation(event["id"], award_supplier_id)
    if (invitation is None
            or invitation["status"] != "BID_SUBMITTED"
            or supplier["status"] != "ACTIVE"):
        raise_error(
            ERR_SUPPLIER_NOT_ELIGIBLE,
            "award winner must hold a BID_SUBMITTED invitation and be ACTIVE",
        )
    # Quota rung: inclusion check unless waived (exactly equal passes).
    if waiver is None and event["diverse_bid_count"] < event["required_diverse_bidders"]:
        raise_error(ERR_INCLUSION_SHORTFALL, "diverse_bid_count below required threshold")
    # Fiscal rung: award cap.
    award_amount_cents = req_int(body, "award_amount_cents", minimum=1)
    if award_amount_cents > event["estimated_value_cents"]:
        raise_error(ERR_AWARD_ABOVE_LIMIT, "award_amount_cents exceeds estimated_value_cents")
    event["status"] = "AWARDED"
    event["award_supplier_id"] = award_supplier_id
    event["award_amount_cents"] = award_amount_cents
    event["inclusion_waiver_reason"] = waiver
    touch(event)
    # Invitation cascade: winner WON, other BID_SUBMITTED LOST, INVITED
    # NO_RESPONSE; DECLINED/WITHDRAWN unchanged.
    for inv in list(db["invitations"].values()):
        if inv["sourcing_event_id"] != event["id"]:
            continue
        if inv["id"] == invitation["id"]:
            inv["status"] = "WON"
            touch(inv)
        elif inv["status"] == "BID_SUBMITTED":
            inv["status"] = "LOST"
            touch(inv)
        elif inv["status"] == "INVITED":
            inv["status"] = "NO_RESPONSE"
            touch(inv)
    return success_object(pub_sourcing_event(event))


@bp.route("/api/v1/sourcing-events/<rid>/cancel", methods=["POST"])
def cancel_sourcing_event(rid):
    caller = authorized(EVENT_WRITERS)
    event = get_resource("sourcing_events", rid)
    _check_bu_scope(caller, event)
    if event["status"] not in ("DRAFT", "OPEN"):
        raise_error(ERR_INVALID_STATE, "cancel requires status DRAFT or OPEN")
    if event["status"] == "OPEN":
        # INVITED invitations withdraw; BID_SUBMITTED/DECLINED unchanged.
        for inv in list(db["invitations"].values()):
            if inv["sourcing_event_id"] == event["id"] and inv["status"] == "INVITED":
                inv["status"] = "WITHDRAWN"
                touch(inv)
    event["status"] = "CANCELLED"
    touch(event)
    return success_object(pub_sourcing_event(event))


# ---------------------------------------------------------------------------
# Invitations
# ---------------------------------------------------------------------------

@bp.route("/api/v1/sourcing-events/<rid>/invitations", methods=["POST"])
def create_invitation(rid):
    caller = authorized(EVENT_WRITERS)
    event = get_resource("sourcing_events", rid)
    _check_bu_scope(caller, event)
    body = get_body()
    supplier_id = req_str(body, "supplier_id")
    supplier = get_resource("suppliers", supplier_id)
    if event["status"] != "OPEN":
        raise_error(ERR_INVALID_STATE, "invitations require an OPEN event")
    if supplier["status"] == "SUSPENDED":
        raise_error(ERR_SUPPLIER_NOT_ELIGIBLE, "SUSPENDED suppliers may not be invited")
    if _find_invitation(event["id"], supplier_id) is not None:
        raise_error(
            ERR_DUPLICATE_INVITATION,
            "an invitation for this (sourcing_event, supplier) already exists",
        )
    rec = make_record({
        "sourcing_event_id": event["id"],
        "supplier_id": supplier_id,
        "status": "INVITED",
    })
    db["invitations"][rec["id"]] = rec
    return success_object(pub_invitation(rec), status=201)


@bp.route("/api/v1/sourcing-events/<rid>/invitations", methods=["GET"])
def list_event_invitations(rid):
    authorized(READERS)
    event = get_resource("sourcing_events", rid)
    filters = {"status": request.args.get("status")}
    records = [i for i in db["invitations"].values() if i["sourcing_event_id"] == event["id"]]
    return list_response(records, filters, pub_invitation)


@bp.route("/api/v1/suppliers/<rid>/invitations", methods=["GET"])
def list_supplier_invitations(rid):
    authorized(READERS)
    supplier = get_resource("suppliers", rid)
    filters = {"status": request.args.get("status")}
    records = [i for i in db["invitations"].values() if i["supplier_id"] == supplier["id"]]
    return list_response(records, filters, pub_invitation)


@bp.route("/api/v1/invitations/<rid>/respond", methods=["POST"])
def respond_invitation(rid):
    caller = authorized(EVENT_WRITERS)
    invitation = get_resource("invitations", rid)
    event = db["sourcing_events"].get(invitation["sourcing_event_id"])
    if event is not None:
        _check_bu_scope(caller, event)
    # State rung: defined only for an INVITED invitation on an OPEN event.
    if invitation["status"] != "INVITED":
        raise_error(ERR_INVALID_STATE, "respond requires an INVITED invitation")
    if event is None or event["status"] != "OPEN":
        raise_error(ERR_INVALID_STATE, "respond requires an OPEN sourcing event")
    body = get_body()
    response = body.get("response")
    if response not in ("BID_SUBMITTED", "DECLINED"):
        raise_error(ERR_INVALID_REQUEST, "response must be BID_SUBMITTED or DECLINED")
    invitation["status"] = response
    touch(invitation)
    if response == "BID_SUBMITTED":
        recompute_event_bid_count(event)
    return success_object(pub_invitation(invitation))
