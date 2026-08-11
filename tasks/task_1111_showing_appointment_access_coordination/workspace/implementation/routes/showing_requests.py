"""ShowingRequest endpoints: intake, approval workflow, confirm, cancel,
reschedule, no-show declaration, credentials, strikes, feedback lookup,
activity events."""

import random

from flask import Blueprint, request as flask_request

import clock
import db
import errors
import middleware as mw
import response
from services import calc, core

bp = Blueprint("showing_requests", __name__)


def get_request_or_404(request_id):
    req = db.showing_requests.get(request_id)
    if req is None:
        raise errors.err(errors.ERR_SHOWING_REQUEST_NOT_FOUND,
                         "Showing request not found.", 404)
    return req


def _get_listing_for_request(req):
    listing = db.listings.get(req["listing_id"])
    if listing is None:
        # Should not happen — requests are only created against existing listings
        raise errors.err(errors.ERR_LISTING_NOT_FOUND, "Listing not found.", 404)
    return listing


def _require_buyer_owner(caller, req):
    if caller.user_id != req["buyer_agent_id"]:
        raise errors.err(errors.ERR_NOT_RESOURCE_OWNER,
                         "Caller is not the buyer agent of this request.", 403)


def _require_seller_owner(caller, listing):
    if caller.user_id != listing["seller_id"]:
        raise errors.err(errors.ERR_NOT_RESOURCE_OWNER,
                         "Caller is not the seller who owns this listing.", 403)


def _require_listing_agent_owner(caller, listing):
    if caller.user_id != listing["listing_agent_id"]:
        raise errors.err(errors.ERR_NOT_RESOURCE_OWNER,
                         "Caller is not the listing agent of this listing.", 403)


def _check_agent_eligibility(agent):
    """Stage 8: verified + not suspended."""
    if agent["verification_status"] != "VERIFIED":
        raise errors.err(errors.ERR_AGENT_NOT_VERIFIED,
                         "Buyer agent is not VERIFIED.", 403)
    if agent["standing"] == "SUSPENDED":
        raise errors.err(errors.ERR_AGENT_SUSPENDED,
                         "Buyer agent is SUSPENDED.", 403)


# ---------------------------------------------------------------------------
# Intake
# ---------------------------------------------------------------------------

@bp.post("/showing-desk/showing-requests")
def create_showing_request():
    caller = mw.authenticate()
    body = mw.get_json_body()
    fields = mw.validate_fields(body, {
        "listing_id": ("string", True),
        "start_at": ("datetime", True),
        "end_at": ("datetime", True),
        "buyer_name": ("string", False),
        "note": ("string", False),
    })
    mw.require_roles(caller, ["BuyerAgent"])
    # Body FK existence
    listing = db.listings.get(fields["listing_id"])
    if listing is None:
        raise errors.err(errors.ERR_LISTING_NOT_FOUND, "Listing not found.", 404)
    agent = db.agents.get(caller.user_id)
    if agent is None:
        raise errors.err(errors.ERR_AGENT_NOT_FOUND, "Agent not found.", 404)
    # Stage 7: listing must be ACTIVE
    if listing["status"] != "ACTIVE":
        raise errors.err(errors.ERR_LISTING_NOT_ACTIVE,
                         "Listing is not ACTIVE.", 409)
    # Stage 8: agent eligibility
    _check_agent_eligibility(agent)
    # Stages 9-12, 14: window validation
    start_at, end_at = fields["start_at"], fields["end_at"]
    calc.validate_new_window(listing, start_at, end_at)

    seller = db.sellers.get(listing["seller_id"])
    created_at = clock.now()
    approval_deadline, confirm_by, born_approved = calc.compute_deadlines(
        listing, seller, start_at, created_at)
    req = core.stamp_new({
        "listing_id": listing["id"],
        "buyer_agent_id": agent["id"],
        "start_at": start_at,
        "end_at": end_at,
        "buyer_name": fields.get("buyer_name"),
        "note": fields.get("note"),
        "status": "APPROVED" if born_approved else "PENDING_APPROVAL",
        "approval_deadline": approval_deadline,
        "confirm_by_deadline": confirm_by,
        "decline_reason": None,
        "cancel_actor": None,
        "cancelled_at": None,
        "completed_at": None,
        "reschedule_count": 0,
    })
    db.showing_requests[req["id"]] = req
    core.add_activity(listing["id"], req["id"], "REQUEST_CREATED", "BuyerAgent",
                      "Showing request created.")
    return response.success_object(core.showing_request_view(req), status=201)


@bp.get("/showing-desk/showing-requests/<request_id>")
def get_showing_request(request_id):
    caller = mw.authenticate()
    mw.require_roles(caller, ["PlatformAdmin", "Seller", "ListingAgent", "BuyerAgent"])
    req = get_request_or_404(request_id)
    return response.success_object(core.showing_request_view(req))


@bp.get("/showing-desk/showing-requests")
def list_showing_requests():
    caller = mw.authenticate()
    mw.require_roles(caller, ["PlatformAdmin", "Seller", "ListingAgent", "BuyerAgent"])
    limit, offset = mw.parse_pagination()
    q = flask_request.args
    unknown = set(q.keys()) - {"listing_id", "buyer_agent_id", "status", "limit", "offset"}
    if unknown:
        raise errors.err(errors.ERR_INVALID_REQUEST,
                         f"Unknown query parameter(s): {', '.join(sorted(unknown))}.", 400)
    status = q.get("status")
    allowed_status = {"PENDING_APPROVAL", "APPROVED", "CONFIRMED", "DECLINED",
                      "COMPLETED", "NO_SHOW", "CANCELLED", "EXPIRED"}
    if status is not None and status not in allowed_status:
        raise errors.err(errors.ERR_INVALID_REQUEST,
                         "status filter is not a recognized showing-request status.", 400)
    items = sorted(db.showing_requests.values(), key=lambda r: r["created_at"])
    if q.get("listing_id") is not None:
        items = [r for r in items if r["listing_id"] == q["listing_id"]]
    if q.get("buyer_agent_id") is not None:
        items = [r for r in items if r["buyer_agent_id"] == q["buyer_agent_id"]]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, total = mw.paginate(items, limit, offset)
    return response.success_list([core.showing_request_view(r) for r in page],
                                 limit, offset, total)


# ---------------------------------------------------------------------------
# Approval workflow
# ---------------------------------------------------------------------------

def _terminal_check(req):
    if req["status"] in calc.TERMINAL_STATES:
        raise errors.err(errors.ERR_SHOWING_ALREADY_TERMINAL,
                         f"Request is already in terminal state {req['status']}.", 409)


@bp.post("/showing-desk/showing-requests/<request_id>/approve")
def approve_request(request_id):
    caller = mw.authenticate()
    mw.require_roles(caller, ["Seller"])
    req = get_request_or_404(request_id)
    listing = _get_listing_for_request(req)
    _require_seller_owner(caller, listing)
    _terminal_check(req)
    if req["status"] != "PENDING_APPROVAL":
        raise errors.err(errors.ERR_SHOWING_NOT_PENDING_APPROVAL,
                         "Only a PENDING_APPROVAL request can be approved.", 409)
    if clock.now() >= req["approval_deadline"]:
        raise errors.err(errors.ERR_APPROVAL_DEADLINE_PASSED,
                         "The approval deadline has passed.", 422)
    req["status"] = "APPROVED"
    core.touch(req)
    core.add_activity(listing["id"], req["id"], "APPROVED", "Seller",
                      "Showing request approved by occupant.")
    return response.success_object(core.showing_request_view(req))


@bp.post("/showing-desk/showing-requests/<request_id>/decline")
def decline_request(request_id):
    caller = mw.authenticate()
    body = mw.get_json_body(required=False)
    fields = mw.validate_fields(body, {"reason": ("string", False)},
                                allow_empty_body=True)
    mw.require_roles(caller, ["Seller"])
    req = get_request_or_404(request_id)
    listing = _get_listing_for_request(req)
    _require_seller_owner(caller, listing)
    _terminal_check(req)
    if req["status"] != "PENDING_APPROVAL":
        raise errors.err(errors.ERR_SHOWING_NOT_PENDING_APPROVAL,
                         "Only a PENDING_APPROVAL request can be declined.", 409)
    req["status"] = "DECLINED"
    req["decline_reason"] = fields.get("reason")
    core.touch(req)
    core.add_activity(listing["id"], req["id"], "DECLINED", "Seller",
                      "Showing request declined by occupant.")
    return response.success_object(core.showing_request_view(req))


@bp.post("/showing-desk/showing-requests/<request_id>/reschedule")
def reschedule_request(request_id):
    caller = mw.authenticate()
    body = mw.get_json_body()
    fields = mw.validate_fields(body, {
        "start_at": ("datetime", True),
        "end_at": ("datetime", True),
    })
    mw.require_roles(caller, ["BuyerAgent"])
    req = get_request_or_404(request_id)
    listing = _get_listing_for_request(req)
    _require_buyer_owner(caller, req)
    _terminal_check(req)
    if req["status"] != "DECLINED":
        raise errors.err(errors.ERR_SHOWING_NOT_DECLINED,
                         "Only a DECLINED request can be rescheduled.", 409)
    if listing["status"] != "ACTIVE":
        raise errors.err(errors.ERR_LISTING_NOT_ACTIVE,
                         "Listing is not ACTIVE.", 409)
    start_at, end_at = fields["start_at"], fields["end_at"]
    calc.validate_new_window(listing, start_at, end_at, exclude_id=req["id"])

    seller = db.sellers.get(listing["seller_id"])
    created_at = clock.now()
    approval_deadline, confirm_by, born_approved = calc.compute_deadlines(
        listing, seller, start_at, created_at)
    req["start_at"] = start_at
    req["end_at"] = end_at
    req["approval_deadline"] = approval_deadline
    req["confirm_by_deadline"] = confirm_by
    req["status"] = "APPROVED" if born_approved else "PENDING_APPROVAL"
    req["reschedule_count"] += 1
    core.touch(req)
    core.add_activity(listing["id"], req["id"], "RESCHEDULED", "BuyerAgent",
                      "Showing request rescheduled.")
    return response.success_object(core.showing_request_view(req))


# ---------------------------------------------------------------------------
# Confirm / cancel / no-show
# ---------------------------------------------------------------------------

@bp.post("/showing-desk/showing-requests/<request_id>/confirm")
def confirm_request(request_id):
    caller = mw.authenticate()
    mw.require_roles(caller, ["BuyerAgent"])
    req = get_request_or_404(request_id)
    listing = _get_listing_for_request(req)
    _require_buyer_owner(caller, req)
    _terminal_check(req)
    if req["status"] != "APPROVED":
        raise errors.err(errors.ERR_SHOWING_NOT_APPROVED,
                         "Only an APPROVED request can be confirmed.", 409)
    agent = db.agents.get(caller.user_id)
    if agent is None:
        raise errors.err(errors.ERR_AGENT_NOT_FOUND, "Agent not found.", 404)
    _check_agent_eligibility(agent)
    if clock.now() >= req["confirm_by_deadline"]:
        raise errors.err(errors.ERR_CONFIRM_DEADLINE_PASSED,
                         "The confirm-by deadline has passed.", 422)
    req["status"] = "CONFIRMED"
    core.touch(req)
    listing["confirmed_showing_count"] += 1
    core.touch(listing)
    # Feedback automation: born SCHEDULED on confirmation
    fb = core.stamp_new({
        "showing_request_id": req["id"],
        "status": "SCHEDULED",
        "sent_at": None,
        "due_at": None,
        "q1": None, "q2": None, "q3": None, "q4": None, "q5": None,
        "comment": None,
        "overall_score": None,
        "submitted_at": None,
    })
    db.feedback_requests[fb["id"]] = fb
    core.add_activity(listing["id"], req["id"], "CONFIRMED", "BuyerAgent",
                      "Showing request confirmed by buyer agent.")
    return response.success_object(core.showing_request_view(req))


@bp.post("/showing-desk/showing-requests/<request_id>/cancel")
def cancel_request(request_id):
    caller = mw.authenticate()
    body = mw.get_json_body(required=False)
    if body:
        mw.validate_fields(body, {"reason": ("string", False)})
    mw.require_roles(caller, ["BuyerAgent"])
    req = get_request_or_404(request_id)
    _get_listing_for_request(req)
    _require_buyer_owner(caller, req)
    _terminal_check(req)
    if req["status"] not in calc.OCCUPANCY_STATES:
        # Only remaining non-terminal state is DECLINED
        raise errors.err(errors.ERR_SHOWING_NOT_PENDING_APPROVAL,
                         "Request cannot be cancelled from its current state.", 409)
    calc.buyer_cancel_request(req, "BuyerAgent")
    return response.success_object(core.showing_request_view(req))


@bp.post("/showing-desk/showing-requests/<request_id>/declare-no-show")
def declare_no_show(request_id):
    caller = mw.authenticate()
    mw.require_roles(caller, ["ListingAgent"])
    req = get_request_or_404(request_id)
    listing = _get_listing_for_request(req)
    _require_listing_agent_owner(caller, listing)
    _terminal_check(req)
    if req["status"] != "CONFIRMED":
        raise errors.err(errors.ERR_SHOWING_NOT_CONFIRMED,
                         "Only a CONFIRMED request can be declared a no-show.", 409)
    now = clock.now()
    if now <= req["end_at"]:
        raise errors.err(errors.ERR_NO_SHOW_TOO_EARLY,
                         "No-show may only be declared after the window has ended.", 422)
    if any(c["status"] == "USED" for c in core.credentials_of_request(req["id"])):
        raise errors.err(errors.ERR_NO_SHOW_NOT_DECLARABLE,
                         "A credential of this request is already USED.", 409)
    # CASCADE B
    req["status"] = "NO_SHOW"
    core.touch(req)
    listing["confirmed_showing_count"] -= 1
    core.touch(listing)
    calc.create_strike(req["buyer_agent_id"], req["id"], "NO_SHOW", listing["id"])
    core.add_activity(listing["id"], req["id"], "NO_SHOW", "ListingAgent",
                      "Buyer agent declared no-show.")
    return response.success_object(core.showing_request_view(req))


# ---------------------------------------------------------------------------
# Access credentials
# ---------------------------------------------------------------------------

@bp.post("/showing-desk/showing-requests/<request_id>/access-credentials")
def issue_credential(request_id):
    caller = mw.authenticate()
    body = mw.get_json_body()
    fields = mw.validate_fields(body, {
        "credential_type": (("enum", ["LOCKBOX_CODE", "DOOR_CODE", "SMART_LOCK"]), True),
    })
    mw.require_roles(caller, ["ListingAgent"])
    req = get_request_or_404(request_id)
    listing = _get_listing_for_request(req)
    _require_listing_agent_owner(caller, listing)
    _terminal_check(req)
    if req["status"] != "CONFIRMED":
        raise errors.err(errors.ERR_SHOWING_NOT_CONFIRMED,
                         "Only a CONFIRMED request can receive a credential.", 409)
    # Stage 15: uniqueness among ISSUED/USED credentials
    if any(c["status"] in ("ISSUED", "USED")
           for c in core.credentials_of_request(req["id"])):
        raise errors.err(errors.ERR_CREDENTIAL_ALREADY_ISSUED,
                         "A credential in ISSUED or USED already exists for this request.",
                         409)
    active_from, expires_at, instructions = calc.access_window(listing, req)
    cred = core.stamp_new({
        "showing_request_id": req["id"],
        "credential_type": fields["credential_type"],
        "access_code": f"{random.SystemRandom().randrange(0, 1000000):06d}",
        "instructions_text": instructions,
        "active_from": active_from,
        "expires_at": expires_at,
        "status": "ISSUED",
        "redeemed_at": None,
    })
    db.access_credentials[cred["id"]] = cred
    core.add_activity(listing["id"], req["id"], "CREDENTIAL_ISSUED", "ListingAgent",
                      "Access credential issued.")
    return response.success_object(core.credential_view(cred), status=201)


@bp.get("/showing-desk/showing-requests/<request_id>/access-credentials")
def list_credentials(request_id):
    caller = mw.authenticate()
    mw.require_roles(caller, ["ListingAgent", "BuyerAgent"])
    req = get_request_or_404(request_id)
    limit, offset = mw.parse_pagination()
    items = sorted(core.credentials_of_request(req["id"]),
                   key=lambda c: c["created_at"])
    page, total = mw.paginate(items, limit, offset)
    return response.success_list([core.credential_view(c) for c in page],
                                 limit, offset, total)


@bp.get("/showing-desk/showing-requests/<request_id>/strikes")
def list_request_strikes(request_id):
    caller = mw.authenticate()
    mw.require_roles(caller, ["PlatformAdmin", "Seller", "ListingAgent"])
    req = get_request_or_404(request_id)
    limit, offset = mw.parse_pagination()
    items = sorted((s for s in db.strike_records.values()
                    if s["showing_request_id"] == req["id"]),
                   key=lambda s: s["created_at"])
    page, total = mw.paginate(items, limit, offset)
    return response.success_list([core.strike_view(s) for s in page],
                                 limit, offset, total)


@bp.get("/showing-desk/showing-requests/<request_id>/feedback-request")
def get_feedback_of_request(request_id):
    caller = mw.authenticate()
    mw.require_roles(caller, ["Seller", "ListingAgent", "BuyerAgent"])
    req = get_request_or_404(request_id)
    items = sorted(core.feedback_of_request(req["id"]),
                   key=lambda f: f["created_at"])
    limit, offset = mw.parse_pagination()
    page, total = mw.paginate(items, limit, offset)
    return response.success_list([core.feedback_view(f) for f in page],
                                 limit, offset, total)


@bp.get("/showing-desk/showing-requests/<request_id>/activity-events")
def list_request_activity(request_id):
    caller = mw.authenticate()
    mw.require_roles(caller, ["Seller", "ListingAgent"])
    req = get_request_or_404(request_id)
    limit, offset = mw.parse_pagination()
    items = sorted((e for e in db.activity_events.values()
                    if e["showing_request_id"] == req["id"]),
                   key=lambda e: e["created_at"])
    event_type = flask_request.args.get("event_type")
    if event_type is not None:
        items = [e for e in items if e["event_type"] == event_type]
    page, total = mw.paginate(items, limit, offset)
    return response.success_list([core.activity_event_view(e) for e in page],
                                 limit, offset, total)
