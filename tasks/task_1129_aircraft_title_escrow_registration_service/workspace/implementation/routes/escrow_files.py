"""EscrowFile endpoints."""

from flask import Blueprint, request

import db
from db import (
    aircraft_store, party_store, escrow_file_store, title_search_store,
    deposit_store, disbursement_store, filing_store, closing_document_store,
    lien_store, lien_release_store, make_common_fields, touch, now_iso,
)
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_AIRCRAFT_UNDER_CONTRACT,
    ERR_FILE_ON_HOLD, ERR_ALREADY_TERMINAL, ERR_INVALID_TRANSITION,
    ERR_STALE_VERSION, ERR_POSTURE_NOT_READY, ERR_DOCUMENTS_INCOMPLETE,
    ERR_SEARCH_STALE, ERR_DUPLICATE_FILING,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from services.calculations import compute_proration, compute_escrow_fee
from services.escrow import (
    recompute_posture, recompute_totals, try_bubble_cleared, try_bubble_funded,
    try_revert_funded, try_bubble_recorded, try_bubble_verified, cancel_cascade,
)
from validators import (
    get_body, require_fields, require_string, require_positive_int,
    require_non_negative_int, require_enum, require_date_string,
)

bp = Blueprint("escrow_files", __name__)

VALID_PRORATION_METHODS = ["DAILY", "MONTHLY"]
ACTIVE_STATUSES = {"OPENED", "SEARCH_ORDERED", "SEARCH_COMPLETE", "CLEARED", "FUNDED"}
TERMINAL_STATUSES = {"CANCELLED", "VERIFIED"}


def _parse_limit():
    try:
        v = int(request.args.get("limit", 10))
    except (ValueError, TypeError):
        v = 10
    return max(1, min(100, v))


def _parse_offset():
    try:
        v = int(request.args.get("offset", 0))
    except (ValueError, TypeError):
        v = 0
    return max(0, v)


@bp.route("/api/escrow-files", methods=["POST"])
def create_escrow_file():
    user_id, role = require_roles(["EscrowOfficer"])
    body = get_body()
    require_fields(
        body,
        ["aircraft_id", "buyer_party_id", "seller_party_id", "purchase_price_cents",
         "annual_registration_fee_cents", "proration_method", "expected_close_date"],
        ["lender_party_id", "trustee_party_id", "requires_trust"],
    )

    aircraft_id = require_string(body["aircraft_id"], "aircraft_id")
    buyer_party_id = require_string(body["buyer_party_id"], "buyer_party_id")
    seller_party_id = require_string(body["seller_party_id"], "seller_party_id")
    lender_party_id = body.get("lender_party_id")
    trustee_party_id = body.get("trustee_party_id")
    requires_trust = body.get("requires_trust", False)
    purchase_price_cents = require_positive_int(body["purchase_price_cents"], "purchase_price_cents")
    annual_fee = require_non_negative_int(body["annual_registration_fee_cents"], "annual_registration_fee_cents")
    proration_method = require_enum(body["proration_method"], "proration_method", VALID_PRORATION_METHODS)
    expected_close_date = require_date_string(body["expected_close_date"], "expected_close_date")

    if not isinstance(requires_trust, bool):
        raise ApiError(ERR_INVALID_REQUEST, "requires_trust must be a boolean.", 400)

    # Existence checks
    aircraft = aircraft_store.get(aircraft_id)
    if not aircraft:
        raise ApiError(ERR_NOT_FOUND, "Aircraft not found.", 404)
    buyer = party_store.get(buyer_party_id)
    if not buyer:
        raise ApiError(ERR_NOT_FOUND, "Buyer party not found.", 404)
    seller = party_store.get(seller_party_id)
    if not seller:
        raise ApiError(ERR_NOT_FOUND, "Seller party not found.", 404)
    if lender_party_id is not None:
        if not party_store.get(lender_party_id):
            raise ApiError(ERR_NOT_FOUND, "Lender party not found.", 404)
    if trustee_party_id is not None:
        if not party_store.get(trustee_party_id):
            raise ApiError(ERR_NOT_FOUND, "Trustee party not found.", 404)

    # Aircraft occupation check
    for ef in escrow_file_store.values():
        if ef["aircraft_id"] == aircraft_id and ef["status"] not in TERMINAL_STATUSES:
            raise ApiError(ERR_AIRCRAFT_UNDER_CONTRACT, "Aircraft already has a non-terminal escrow file.", 409)

    # Compute frozen values
    proration = compute_proration(annual_fee, proration_method, expected_close_date)
    fee = compute_escrow_fee(purchase_price_cents, proration, requires_trust)
    due = purchase_price_cents + proration + fee

    fields = make_common_fields()
    ef = {
        **fields,
        "aircraft_id": aircraft_id,
        "buyer_party_id": buyer_party_id,
        "seller_party_id": seller_party_id,
        "lender_party_id": lender_party_id,
        "trustee_party_id": trustee_party_id,
        "requires_trust": requires_trust,
        "purchase_price_cents": purchase_price_cents,
        "annual_registration_fee_cents": annual_fee,
        "proration_method": proration_method,
        "expected_close_date": expected_close_date,
        "status": "OPENED",
        "posture": "READY",
        "hold_return_state": None,
        "escrow_fee_cents": fee,
        "proration_amount_cents": proration,
        "buyer_amount_due_cents": due,
        "total_funded_cents": 0,
        "escrow_balance_cents": 0,
        "seller_net_proceeds_cents": purchase_price_cents + proration - fee,
        "closed_at": None,
    }
    escrow_file_store[ef["id"]] = ef

    # Initialize posture
    recompute_posture(ef)

    return success_object(ef, 201)


@bp.route("/api/escrow-files/<id>", methods=["GET"])
def get_escrow_file(id):
    user_id, role = require_roles(ALL_ROLES)
    ef = escrow_file_store.get(id)
    if not ef:
        raise ApiError(ERR_NOT_FOUND, "EscrowFile not found.", 404)
    return success_object(ef)


@bp.route("/api/escrow-files", methods=["GET"])
def list_escrow_files():
    user_id, role = require_roles(ALL_ROLES)
    items = list(escrow_file_store.values())

    # Apply filters
    aircraft_id = request.args.get("aircraft_id")
    buyer_party_id = request.args.get("buyer_party_id")
    seller_party_id = request.args.get("seller_party_id")
    lender_party_id = request.args.get("lender_party_id")
    trustee_party_id = request.args.get("trustee_party_id")
    status = request.args.get("status")

    if aircraft_id:
        items = [e for e in items if e["aircraft_id"] == aircraft_id]
    if buyer_party_id:
        items = [e for e in items if e["buyer_party_id"] == buyer_party_id]
    if seller_party_id:
        items = [e for e in items if e["seller_party_id"] == seller_party_id]
    if lender_party_id:
        items = [e for e in items if e.get("lender_party_id") == lender_party_id]
    if trustee_party_id:
        items = [e for e in items if e.get("trustee_party_id") == trustee_party_id]
    if status:
        items = [e for e in items if e["status"] == status]

    items.sort(key=lambda x: x["created_at"])
    limit = _parse_limit()
    offset = _parse_offset()
    total = len(items)
    items = items[offset:offset + limit]
    return success_list(items, limit, offset, total)


@bp.route("/api/escrow-files/<id>/hold", methods=["POST"])
def hold_escrow_file(id):
    user_id, role = require_roles(["EscrowOfficer"])
    ef = escrow_file_store.get(id)
    if not ef:
        raise ApiError(ERR_NOT_FOUND, "EscrowFile not found.", 404)
    _check_terminal(ef)
    _check_on_hold(ef)

    if ef["status"] not in ACTIVE_STATUSES:
        raise ApiError(ERR_INVALID_TRANSITION, f"Cannot hold file in status {ef['status']}.", 409)

    ef["hold_return_state"] = ef["status"]
    ef["status"] = "ON_HOLD"
    touch(ef)
    return success_object(ef)


@bp.route("/api/escrow-files/<id>/resume", methods=["POST"])
def resume_escrow_file(id):
    user_id, role = require_roles(["EscrowOfficer"])
    ef = escrow_file_store.get(id)
    if not ef:
        raise ApiError(ERR_NOT_FOUND, "EscrowFile not found.", 404)
    _check_terminal(ef)

    if ef["status"] != "ON_HOLD":
        raise ApiError(ERR_INVALID_TRANSITION, f"Cannot resume file in status {ef['status']}.", 409)

    ef["status"] = ef["hold_return_state"]
    ef["hold_return_state"] = None
    touch(ef)
    return success_object(ef)


@bp.route("/api/escrow-files/<id>/cancel", methods=["POST"])
def cancel_escrow_file(id):
    user_id, role = require_roles(["EscrowOfficer"])
    ef = escrow_file_store.get(id)
    if not ef:
        raise ApiError(ERR_NOT_FOUND, "EscrowFile not found.", 404)
    _check_terminal(ef)

    if ef["status"] not in ACTIVE_STATUSES and ef["status"] != "ON_HOLD":
        raise ApiError(ERR_INVALID_TRANSITION, f"Cannot cancel file in status {ef['status']}.", 409)

    cancel_cascade(ef)
    ef["status"] = "CANCELLED"
    ef["hold_return_state"] = None
    touch(ef)
    return success_object(ef)


@bp.route("/api/escrow-files/<id>/close", methods=["POST"])
def close_escrow_file(id):
    user_id, role = require_roles(["EscrowOfficer"])
    ef = escrow_file_store.get(id)
    if not ef:
        raise ApiError(ERR_NOT_FOUND, "EscrowFile not found.", 404)
    _check_on_hold(ef)
    _check_terminal(ef)

    if ef["status"] != "FUNDED":
        raise ApiError(ERR_INVALID_TRANSITION, f"Cannot close file in status {ef['status']}.", 409)

    body = get_body()
    require_fields(body, ["expected_escrow_file_version"])

    # OCC check
    expected = body["expected_escrow_file_version"]
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError(ERR_INVALID_REQUEST, "expected_escrow_file_version must be an integer.", 400)
    if expected != ef["version"]:
        raise ApiError(ERR_STALE_VERSION, "EscrowFile version mismatch.", 412)

    # Posture check
    if ef["posture"] != "READY":
        raise ApiError(ERR_POSTURE_NOT_READY, "Posture is not READY.", 409)

    # Documents check
    file_docs = [d for d in closing_document_store.values() if d["escrow_file_id"] == id]
    for doc in file_docs:
        if doc["status"] != "FULLY_SIGNED":
            raise ApiError(ERR_DOCUMENTS_INCOMPLETE, "Not all closing documents are fully signed.", 409)

    # Title search freshness check
    file_searches = [ts for ts in title_search_store.values() if ts["escrow_file_id"] == id]
    file_searches.sort(key=lambda x: x["created_at"])
    if not file_searches:
        raise ApiError(ERR_SEARCH_STALE, "No title search exists.", 409)
    latest = file_searches[-1]
    if latest["status"] != "COMPLETED":
        raise ApiError(ERR_SEARCH_STALE, "Latest title search is not COMPLETED.", 409)
    if latest.get("effective_at"):
        from datetime import datetime, timedelta
        eff = datetime.fromisoformat(latest["effective_at"].replace("Z", "+00:00"))
        threshold = eff + timedelta(days=30)
        if db.get_logical_now() > threshold:
            raise ApiError(ERR_SEARCH_STALE, "Latest title search is stale.", 409)
    else:
        raise ApiError(ERR_SEARCH_STALE, "Latest title search has no effective_at.", 409)

    # Freeze live figures
    recompute_totals(ef)

    ef["status"] = "CLOSED"
    ef["closed_at"] = now_iso()
    touch(ef)

    return success_object(ef)


@bp.route("/api/escrow-files/<id>/statement", methods=["GET"])
def get_statement(id):
    user_id, role = require_roles(ALL_ROLES)
    ef = escrow_file_store.get(id)
    if not ef:
        raise ApiError(ERR_NOT_FOUND, "EscrowFile not found.", 404)

    # Recompute live figures for read
    recompute_totals(ef)

    return success_object({
        "purchase_price_cents": ef["purchase_price_cents"],
        "proration_amount_cents": ef["proration_amount_cents"],
        "escrow_fee_cents": ef["escrow_fee_cents"],
        "buyer_amount_due_cents": ef["buyer_amount_due_cents"],
        "total_funded_cents": ef["total_funded_cents"],
        "escrow_balance_cents": ef["escrow_balance_cents"],
        "seller_net_proceeds_cents": ef["seller_net_proceeds_cents"],
    })


def _check_on_hold(ef):
    if ef["status"] == "ON_HOLD":
        raise ApiError(ERR_FILE_ON_HOLD, "EscrowFile is ON_HOLD.", 409)


def _check_terminal(ef):
    if ef["status"] in TERMINAL_STATUSES:
        raise ApiError(ERR_ALREADY_TERMINAL, f"EscrowFile is {ef['status']}.", 409)


def _check_file_mutable(ef):
    """Check both ON_HOLD and terminal for child mutations."""
    _check_on_hold(ef)
    _check_terminal(ef)
