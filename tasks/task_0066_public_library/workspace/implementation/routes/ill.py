"""Inter-Library Loan request routes."""
from datetime import timedelta
from flask import Blueprint, request, g

import db
from errors import err
from response import success
from middleware import require_auth
from services import validation as V
from services.common import (
    get_ill_request, get_card, get_copy, check_version, assert_reader_ownership,
)
from services.serialize import serialize_ill_request
from services.money import (
    ILL_HANDLING_FEE_CENTS, ILL_REQUESTER_MAX_DAYS, ill_settlement_total,
)
from services import reservations as reservations_svc
from services.aggregates import recompute_title_aggregates
from clock import parse_iso, iso, now


bp = Blueprint("ill", __name__)


@bp.route("/library/ill-requests", methods=["POST"])
@require_auth(roles={"Reader", "Librarian", "ILLCoordinator"})
def submit_ill():
    body = V.require_dict(request.get_json(silent=True) or {})
    card_id = V.require_str(body, "card_id")
    card = get_card(card_id)
    # PRD §3.7: partner_library_code outside the approved set returns
    # ERR_UNKNOWN_PARTNER. An empty string is also "any other value" per PRD —
    # it is not a special input-validation case.
    partner = V.require_str(body, "partner_library_code", allow_empty=True)
    if partner not in V.ILL_PARTNER_CODES:
        raise err("ERR_UNKNOWN_PARTNER",
                  f"Unknown partner_library_code: {partner}")
    marc = V.require_str(body, "target_marc_control_number")
    shipping = V.require_int(body, "shipping_cost_cents")
    if shipping < 0:
        raise err("ERR_INVALID_INPUT", "shipping_cost_cents must be >= 0")

    if g.user_role == "Reader":
        if g.user_id != card["reader_id"]:
            raise err("ERR_FORBIDDEN", "Reader can submit ILL only with their own card")

    entity = {
        "reader_id": card["reader_id"],
        "card_id": card["id"],
        "partner_library_code": partner,
        "target_marc_control_number": marc,
        "agreed_loan_days": 0,
        "shipping_cost_cents": shipping,
        "handling_fee_cents": ILL_HANDLING_FEE_CENTS,
        "settlement_total_cents": 0,
        "in_transit_from": None,
        "in_transit_to": None,
        "status": "SUBMITTED",
    }
    db.stamp_create(entity)
    db.ill_requests[entity["id"]] = entity
    return success(serialize_ill_request(entity), status=201)


@bp.route("/library/ill-requests/<iid>/approve", methods=["POST"])
@require_auth(roles={"ILLCoordinator"})
def approve_ill(iid):
    ill = get_ill_request(iid)
    body = V.require_dict(request.get_json(silent=True) or {})
    check_version(ill, body)
    if ill["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE",
                  f"ILLRequest is {ill['status']}, not SUBMITTED")
    avail = db.ill_availability.get(ill["id"])
    if avail is None or not avail.get("available"):
        raise err("ERR_INVALID_STATE",
                  "No availability event indicating available=true received")
    partner_max = int(avail.get("partner_max_days") or 0)
    ill["agreed_loan_days"] = min(partner_max, ILL_REQUESTER_MAX_DAYS) if partner_max > 0 else 0
    ill["status"] = "APPROVED"
    db.stamp_update(ill)
    return success(serialize_ill_request(ill))


@bp.route("/library/ill-requests/<iid>/reject", methods=["POST"])
@require_auth(roles={"ILLCoordinator"})
def reject_ill(iid):
    ill = get_ill_request(iid)
    body = V.require_dict(request.get_json(silent=True) or {})
    check_version(ill, body)
    V.require_str(body, "reason")
    if ill["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE",
                  f"ILLRequest is {ill['status']}, not SUBMITTED")
    ill["status"] = "REJECTED"
    db.stamp_update(ill)
    return success(serialize_ill_request(ill))


@bp.route("/library/ill-requests/<iid>/dispatch", methods=["POST"])
@require_auth(roles={"ILLCoordinator"})
def dispatch_ill(iid):
    ill = get_ill_request(iid)
    body = V.require_dict(request.get_json(silent=True) or {})
    check_version(ill, body)
    copy_id = V.require_str(body, "copy_id")
    copy = get_copy(copy_id)

    if ill["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE",
                  f"ILLRequest is {ill['status']}, not APPROVED")

    # Copy's BookTitle must carry the same marc_control_number
    bt = db.book_titles.get(copy["book_title_id"])
    if bt is None or bt["marc_control_number"] != ill["target_marc_control_number"]:
        raise err("ERR_INVALID_INPUT",
                  "Copy's BookTitle does not match target_marc_control_number")
    if copy["status"] != "AVAILABLE":
        raise err("ERR_COPY_NOT_AVAILABLE",
                  f"Copy is {copy['status']}, not AVAILABLE")

    copy["status"] = "IN_TRANSIT_ILL"
    db.stamp_update(copy)
    ill["status"] = "IN_TRANSIT"
    ill["in_transit_from"] = iso(now())
    db.stamp_update(ill)
    recompute_title_aggregates(copy["book_title_id"])
    # Track the dispatched copy so receive-return can release the correct one
    ill["_dispatched_copy_id"] = copy["id"]
    return success(serialize_ill_request(ill))


@bp.route("/library/ill-requests/<iid>/return-received", methods=["POST"])
@require_auth(roles={"ILLCoordinator"})
def return_received_ill(iid):
    ill = get_ill_request(iid)
    body = V.require_dict(request.get_json(silent=True) or {})
    check_version(ill, body)
    if ill["status"] != "RETURNED_TRANSIT":
        raise err("ERR_INVALID_STATE",
                  f"ILLRequest is {ill['status']}, not RETURNED_TRANSIT")

    # Loan period gate
    if ill.get("in_transit_from"):
        start = parse_iso(ill["in_transit_from"])
        if now() < start + timedelta(days=ill.get("agreed_loan_days", 0)):
            raise err("ERR_ILL_LOAN_PERIOD_NOT_MET",
                      "Return-received before loan period has elapsed")

    # Release the dispatched copy
    copy_id = ill.get("_dispatched_copy_id")
    copy = db.copies.get(copy_id) if copy_id else None
    if copy is not None and copy["status"] == "IN_TRANSIT_ILL":
        copy["status"] = "AVAILABLE"
        db.stamp_update(copy)
        reservations_svc.promote_next_head_for_copy(copy)
        recompute_title_aggregates(copy["book_title_id"])

    ill["in_transit_to"] = iso(now())
    ill["settlement_total_cents"] = ill_settlement_total(
        ill["shipping_cost_cents"], ill["handling_fee_cents"])
    ill["status"] = "SETTLED"
    db.stamp_update(ill)
    return success(serialize_ill_request(ill))
