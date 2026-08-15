"""AgencyInquiry endpoints."""

from flask import Blueprint, request

from db import store, new_id, parse_iso
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_RESOURCE_NOT_FOUND, ERR_INVALID_STATE,
    ERR_INQUIRY_DEADLINE_PASSED,
)
from middleware import require_auth, ALL_ROLES
from response import success, paginate
from services.core import (
    stamp_new, touch, get_engagement_or_404, compute_exposure,
    compute_provisional_score, risk_level_for,
)

bp = Blueprint("inquiries", __name__)

AGENCY_TYPES = {"IRS", "DOL", "STATE_EDD", "STATE_UI"}


@bp.route("/api/engagements/<eid>/inquiries", methods=["POST"])
def create_inquiry(eid):
    require_auth(["AgencyLiaison"])
    body = request.get_json(silent=True) or {}
    agency_type = body.get("agency_type")
    received_at = body.get("received_at")
    response_deadline = body.get("response_deadline")
    back_payments_cents = body.get("back_payments_cents")
    quarters_outstanding = body.get("quarters_outstanding")

    if agency_type not in AGENCY_TYPES:
        raise ApiError(ERR_INVALID_REQUEST, 400, "invalid agency_type")
    if parse_iso(received_at) is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "received_at must be a valid ISO8601 instant")
    if parse_iso(response_deadline) is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "response_deadline must be a valid ISO8601 instant")
    if (back_payments_cents is None or not isinstance(back_payments_cents, int)
            or isinstance(back_payments_cents, bool) or back_payments_cents < 0):
        raise ApiError(ERR_INVALID_REQUEST, 400, "back_payments_cents must be an integer >= 0")
    if (quarters_outstanding is None or not isinstance(quarters_outstanding, int)
            or isinstance(quarters_outstanding, bool) or quarters_outstanding < 0):
        raise ApiError(ERR_INVALID_REQUEST, 400, "quarters_outstanding must be an integer >= 0")

    eng = get_engagement_or_404(eid)

    exposure = compute_exposure(back_payments_cents, quarters_outstanding)
    inquiry = {
        "id": new_id(),
        "engagement_id": eid,
        "contractor_id": eng["contractor_id"],
        "agency_type": agency_type,
        "received_at": received_at,
        "response_deadline": response_deadline,
        "back_payments_cents": back_payments_cents,
        "quarters_outstanding": quarters_outstanding,
        "exposure_estimate_cents": exposure,
        "status": "RECEIVED",
    }
    stamp_new(inquiry)
    store.inquiries[inquiry["id"]] = inquiry
    return success(inquiry, status=201)


@bp.route("/api/engagements/<eid>/inquiries", methods=["GET"])
def list_engagement_inquiries(eid):
    require_auth(ALL_ROLES)
    get_engagement_or_404(eid)
    items = [i for i in store.inquiries.values() if i["engagement_id"] == eid]
    items.sort(key=lambda i: i["created_at"])
    page, pg = paginate(items, request.args)
    return success(page, pagination=pg)


@bp.route("/api/inquiries", methods=["GET"])
def list_inquiries():
    require_auth(ALL_ROLES)
    items = list(store.inquiries.values())
    for key in ("engagement_id", "status"):
        v = request.args.get(key)
        if v:
            items = [i for i in items if i.get(key) == v]
    items.sort(key=lambda i: i["created_at"])
    page, pg = paginate(items, request.args)
    return success(page, pagination=pg)


@bp.route("/api/inquiries/<iid>/respond", methods=["POST"])
def respond_inquiry(iid):
    require_auth(["AgencyLiaison"])
    body = request.get_json(silent=True) or {}
    response_summary = body.get("response_summary")
    if not response_summary or not isinstance(response_summary, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "response_summary is required")

    inq = store.inquiries.get(iid)
    if inq is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404, "Inquiry not found")
    if inq["status"] not in ("RECEIVED", "AUDIT_OPENED"):
        raise ApiError(ERR_INVALID_STATE, 409, "respond requires RECEIVED or AUDIT_OPENED")
    deadline = parse_iso(inq["response_deadline"])
    if deadline is not None and store.clock > deadline:
        raise ApiError(ERR_INQUIRY_DEADLINE_PASSED, 422, "Response deadline has passed")
    inq["status"] = "RESPONSE_SUBMITTED"
    touch(inq)
    return success(inq)


@bp.route("/api/inquiries/<iid>/resolve", methods=["POST"])
def resolve_inquiry(iid):
    require_auth(["AgencyLiaison"])
    body = request.get_json(silent=True) or {}
    outcome = body.get("outcome")
    new_deadline = body.get("new_response_deadline")
    if outcome not in ("RESOLVED", "ESCALATE_TO_AUDIT"):
        raise ApiError(ERR_INVALID_REQUEST, 400, "outcome must be RESOLVED or ESCALATE_TO_AUDIT")
    if outcome == "ESCALATE_TO_AUDIT":
        nd = parse_iso(new_deadline)
        if nd is None or nd <= store.clock:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "new_response_deadline must be a future instant")

    inq = store.inquiries.get(iid)
    if inq is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404, "Inquiry not found")
    if inq["status"] != "RESPONSE_SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409, "resolve requires RESPONSE_SUBMITTED")

    if outcome == "RESOLVED":
        inq["status"] = "RESOLVED"
        touch(inq)
        return success(inq)

    # ESCALATE_TO_AUDIT
    inq["status"] = "AUDIT_OPENED"
    inq["response_deadline"] = new_deadline
    touch(inq)

    provisional = compute_provisional_score(inq["contractor_id"], inq["engagement_id"])
    audit = {
        "id": new_id(),
        "contractor_id": inq["contractor_id"],
        "engagement_id": inq["engagement_id"],
        "audit_type": "FIELDWORK",
        "provisional_risk_score": provisional,
        "final_risk_score": None,
        "risk_level": risk_level_for(provisional),
        "open_action_count": 0,
        "findings_summary": None,
        "status": "OPEN",
    }
    stamp_new(audit)
    store.audits[audit["id"]] = audit
    return success(inq)
