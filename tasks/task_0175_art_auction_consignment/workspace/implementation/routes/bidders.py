"""Bidder routes (PRD §3.1).

Bidder: legal_name, email (unique among bidders), country_code, optional
credit_limit_cents (default 0). status ACTIVE|SUSPENDED, outstanding_balance
computed. Bidder is entity-backed: ownership on own reads.
"""
from flask import Blueprint, request

import db
import errors
from errors import err
from middleware import require_role
from middleware import get_json_body
from response import object_response, array_response
from services.common import (
    serialize, require_string, optional_int, parse_pagination, paginate,
    validate_occ_field, match_occ,
)
from services.domain import recompute_bidder_outstanding

bp = Blueprint("bidders", __name__)


@bp.route("/bidders", methods=["POST"])
def create_bidder():
    require_role({"SaleAdministrator"})
    body = get_json_body()
    legal_name = require_string(body, "legal_name")
    email = require_string(body, "email")
    country_code = require_string(body, "country_code")
    credit_limit = optional_int(body, "credit_limit_cents", 0, minimum=0)

    with db.LOCK:
        for b in db.bidders.values():
            if b["email"] == email:
                raise err(errors.ERR_DUPLICATE, "email already registered for a bidder")
        common = db.new_common()
        record = {
            "id": common["id"],
            "created_at": common["created_at"],
            "updated_at": common["updated_at"],
            "version": common["version"],
            "_seq": common["_seq"],
            "legal_name": legal_name,
            "email": email,
            "country_code": country_code,
            "credit_limit_cents": credit_limit,
            "outstanding_balance_cents": 0,
            "status": "ACTIVE",
        }
        db.bidders[record["id"]] = record
        return object_response(serialize(record), 201)


def _owns_bidder(role, user_id, bidder):
    if role == "Bidder" and user_id != bidder["id"]:
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "Not the owning bidder")


@bp.route("/bidders/<id>", methods=["GET"])
def get_bidder(id):
    user_id, role = require_role(
        {"SaleAdministrator", "FinanceOfficer", "Bidder", "Viewer"})
    with db.LOCK:
        record = db.bidders.get(id)
        if record is None:
            raise err(errors.ERR_NOT_FOUND, "Bidder not found")
        _owns_bidder(role, user_id, record)
        return object_response(serialize(record), 200)


@bp.route("/bidders/<id>", methods=["PATCH"])
def patch_bidder(id):
    require_role({"SaleAdministrator"})
    body = get_json_body()
    with db.LOCK:
        record = db.bidders.get(id)
        if record is None:
            raise err(errors.ERR_NOT_FOUND, "Bidder not found")

        # Validate provided fields before mutating.
        new_credit = None
        if "credit_limit_cents" in body and body["credit_limit_cents"] is not None:
            new_credit = optional_int(body, "credit_limit_cents", None, minimum=0)
        new_status = None
        if "status" in body and body["status"] is not None:
            if body["status"] not in ("ACTIVE", "SUSPENDED"):
                raise err(errors.ERR_INVALID_REQUEST, "status must be ACTIVE or SUSPENDED")
            new_status = body["status"]

        # expected_bidder_version is required for this guarded transition.
        validate_occ_field(body, "expected_bidder_version", required=True)
        match_occ(record, body, "expected_bidder_version")

        if new_credit is not None:
            record["credit_limit_cents"] = new_credit
        if new_status is not None:
            record["status"] = new_status
        db.touch(record)
        return object_response(serialize(record), 200)


@bp.route("/bidders/<id>/invoices", methods=["GET"])
def list_bidder_invoices(id):
    user_id, role = require_role(
        {"SaleAdministrator", "FinanceOfficer", "Bidder", "Viewer"})
    with db.LOCK:
        bidder = db.bidders.get(id)
        if bidder is None:
            raise err(errors.ERR_NOT_FOUND, "Bidder not found")
        _owns_bidder(role, user_id, bidder)
        limit, offset = parse_pagination(request.args)
        rows = [inv for inv in db.invoices.values() if inv["bidder_id"] == id]
        items, total = paginate(rows, limit, offset)
        return array_response(items, limit, offset, total, 200)


@bp.route("/bidders/<id>/paddle-registrations", methods=["GET"])
def list_bidder_paddles(id):
    user_id, role = require_role(
        {"SaleAdministrator", "FinanceOfficer", "Bidder", "Viewer"})
    with db.LOCK:
        bidder = db.bidders.get(id)
        if bidder is None:
            raise err(errors.ERR_NOT_FOUND, "Bidder not found")
        _owns_bidder(role, user_id, bidder)
        limit, offset = parse_pagination(request.args)
        rows = [p for p in db.paddle_registrations.values() if p["bidder_id"] == id]
        items, total = paginate(rows, limit, offset)
        return array_response(items, limit, offset, total, 200)
