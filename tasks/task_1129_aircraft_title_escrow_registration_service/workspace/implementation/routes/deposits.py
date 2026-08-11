"""Deposit endpoints."""

from flask import Blueprint, request

import db
from db import (
    escrow_file_store, deposit_store, party_store, make_common_fields, touch, now_iso,
)
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_TRANSITION,
    ERR_FILE_ON_HOLD, ERR_ALREADY_TERMINAL, ERR_STALE_VERSION,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from services.escrow import recompute_totals, try_bubble_funded, try_revert_funded
from validators import get_body, require_fields, require_string, require_positive_int, require_enum

bp = Blueprint("deposits", __name__)

VALID_PURPOSES = ["EARNEST_MONEY", "BUYER_FUNDS", "LENDER_FUNDS"]
DEPOSIT_ALLOWED_STATUSES = {"OPENED", "SEARCH_ORDERED", "SEARCH_COMPLETE", "CLEARED", "FUNDED"}
TERMINAL_STATUSES = {"CANCELLED", "VERIFIED"}
RETURN_BLOCKED_STATUSES = {"CLOSED", "RECORDED", "VERIFIED", "CANCELLED"}


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


@bp.route("/api/escrow-files/<id>/deposits", methods=["POST"])
def create_deposit(id):
    user_id, role = require_roles(["EscrowOfficer"])
    ef = escrow_file_store.get(id)
    if not ef:
        raise ApiError(ERR_NOT_FOUND, "EscrowFile not found.", 404)

    if ef["status"] == "ON_HOLD":
        raise ApiError(ERR_FILE_ON_HOLD, "EscrowFile is ON_HOLD.", 409)
    if ef["status"] in TERMINAL_STATUSES:
        raise ApiError(ERR_ALREADY_TERMINAL, f"EscrowFile is {ef['status']}.", 409)
    if ef["status"] not in DEPOSIT_ALLOWED_STATUSES:
        raise ApiError(ERR_INVALID_TRANSITION, f"Cannot create deposit in status {ef['status']}.", 409)

    body = get_body()
    require_fields(body, ["payer_party_id", "amount_cents", "purpose", "expected_escrow_file_version"])

    payer_party_id = require_string(body["payer_party_id"], "payer_party_id")
    amount_cents = require_positive_int(body["amount_cents"], "amount_cents")
    purpose = require_enum(body["purpose"], "purpose", VALID_PURPOSES)
    expected_version = body["expected_escrow_file_version"]
    if not isinstance(expected_version, int) or isinstance(expected_version, bool):
        raise ApiError(ERR_INVALID_REQUEST, "expected_escrow_file_version must be an integer.", 400)

    # Existence: payer party
    if not party_store.get(payer_party_id):
        raise ApiError(ERR_NOT_FOUND, "Payer party not found.", 404)

    # OCC check
    if expected_version != ef["version"]:
        raise ApiError(ERR_STALE_VERSION, "EscrowFile version mismatch.", 412)

    fields = make_common_fields()
    deposit = {
        **fields,
        "escrow_file_id": id,
        "payer_party_id": payer_party_id,
        "amount_cents": amount_cents,
        "purpose": purpose,
        "status": "RECEIVED",
        "returned_at": None,
    }
    deposit_store[deposit["id"]] = deposit

    # Recompute totals
    recompute_totals(ef)

    # Auto CLEARED -> FUNDED
    try_bubble_funded(ef)

    # Increment file version
    touch(ef)

    return success_object(deposit, 201)


@bp.route("/api/deposits/<id>/return", methods=["POST"])
def return_deposit(id):
    user_id, role = require_roles(["EscrowOfficer"])
    dep = deposit_store.get(id)
    if not dep:
        raise ApiError(ERR_NOT_FOUND, "Deposit not found.", 404)

    ef = escrow_file_store.get(dep["escrow_file_id"])
    if ef:
        if ef["status"] == "ON_HOLD":
            raise ApiError(ERR_FILE_ON_HOLD, "EscrowFile is ON_HOLD.", 409)
        if ef["status"] in RETURN_BLOCKED_STATUSES:
            if ef["status"] in TERMINAL_STATUSES:
                raise ApiError(ERR_ALREADY_TERMINAL, f"EscrowFile is {ef['status']}.", 409)
            raise ApiError(ERR_INVALID_TRANSITION, f"Cannot return deposit when file is {ef['status']}.", 409)

    if dep["status"] != "RECEIVED":
        raise ApiError(ERR_INVALID_TRANSITION, f"Cannot return deposit in status {dep['status']}.", 409)

    dep["status"] = "RETURNED"
    dep["returned_at"] = now_iso()
    touch(dep)

    if ef:
        recompute_totals(ef)
        try_revert_funded(ef)
        touch(ef)

    return success_object(dep)


@bp.route("/api/deposits", methods=["GET"])
def list_deposits():
    user_id, role = require_roles(ALL_ROLES)
    items = list(deposit_store.values())

    escrow_file_id = request.args.get("escrow_file_id")
    payer_party_id = request.args.get("payer_party_id")
    status = request.args.get("status")

    if escrow_file_id:
        items = [d for d in items if d["escrow_file_id"] == escrow_file_id]
    if payer_party_id:
        items = [d for d in items if d["payer_party_id"] == payer_party_id]
    if status:
        items = [d for d in items if d["status"] == status]

    items.sort(key=lambda x: x["created_at"])
    limit = _parse_limit()
    offset = _parse_offset()
    total = len(items)
    items = items[offset:offset + limit]
    return success_list(items, limit, offset, total)


@bp.route("/api/deposits/<id>", methods=["GET"])
def get_deposit(id):
    user_id, role = require_roles(ALL_ROLES)
    dep = deposit_store.get(id)
    if not dep:
        raise ApiError(ERR_NOT_FOUND, "Deposit not found.", 404)
    return success_object(dep)
