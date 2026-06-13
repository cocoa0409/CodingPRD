"""PaddleRegistration routes (PRD §3.4).

Create (assigns sequential paddle_number per sale), read, revoke.
"""
from flask import Blueprint, request

import db
import errors
from errors import err
from middleware import require_role, get_json_body
from response import object_response
from services.common import (
    serialize, require_string, require_enum, optional_int,
    validate_occ_field, match_occ,
)

bp = Blueprint("paddle_registrations", __name__)


@bp.route("/paddle-registrations", methods=["POST"])
def create_paddle():
    require_role({"SaleAdministrator"})
    body = get_json_body()

    with db.LOCK:
        auction_sale_id = require_string(body, "auction_sale_id")
        bidder_id = require_string(body, "bidder_id")
        registration_type = require_enum(
            body, "registration_type", {"FLOOR", "ABSENTEE", "PHONE"}, default="FLOOR")
        max_absentee = optional_int(body, "max_absentee_bid_cents", 0, minimum=0)

        # priority 5: FK resolution
        if auction_sale_id not in db.auction_sales:
            raise err(errors.ERR_FK_NOT_FOUND, "auction_sale_id does not resolve")
        if bidder_id not in db.bidders:
            raise err(errors.ERR_FK_NOT_FOUND, "bidder_id does not resolve")

        bidder = db.bidders[bidder_id]

        # priority 10: eligibility — suspended bidder may not register.
        if bidder["status"] == "SUSPENDED":
            raise err(errors.ERR_PADDLE_INELIGIBLE, "Bidder is suspended")

        # priority 11: absentee rule — ABSENTEE requires max>0, FLOOR/PHONE must be 0.
        if registration_type == "ABSENTEE":
            if max_absentee <= 0:
                raise err(errors.ERR_INVALID_LOT_TERMS,
                          "ABSENTEE requires max_absentee_bid_cents > 0")
        else:
            if max_absentee != 0:
                raise err(errors.ERR_INVALID_LOT_TERMS,
                          "max_absentee_bid_cents must be 0 for FLOOR/PHONE")

        # priority 13: a bidder may hold only one paddle per sale.
        for p in db.paddle_registrations.values():
            if p["auction_sale_id"] == auction_sale_id and p["bidder_id"] == bidder_id:
                raise err(errors.ERR_DUPLICATE, "Bidder already registered for this sale")

        # paddle_number: sequential per sale, starting at 1, in created_at order.
        existing = [p for p in db.paddle_registrations.values()
                    if p["auction_sale_id"] == auction_sale_id]
        paddle_number = len(existing) + 1

        common = db.new_common()
        record = {
            "id": common["id"],
            "created_at": common["created_at"],
            "updated_at": common["updated_at"],
            "version": common["version"],
            "_seq": common["_seq"],
            "auction_sale_id": auction_sale_id,
            "bidder_id": bidder_id,
            "paddle_number": paddle_number,
            "registration_type": registration_type,
            "max_absentee_bid_cents": max_absentee,
            "status": "ACTIVE",
        }
        db.paddle_registrations[record["id"]] = record
        return object_response(serialize(record), 201)


@bp.route("/paddle-registrations/<id>", methods=["GET"])
def get_paddle(id):
    user_id, role = require_role(
        {"SaleAdministrator", "FinanceOfficer", "Auctioneer", "Bidder", "Viewer"})
    with db.LOCK:
        record = db.paddle_registrations.get(id)
        if record is None:
            raise err(errors.ERR_NOT_FOUND, "Paddle registration not found")
        if role == "Bidder" and record["bidder_id"] != user_id:
            raise err(errors.ERR_NOT_RESOURCE_OWNER, "Not the owning bidder's paddle")
        return object_response(serialize(record), 200)


@bp.route("/paddle-registrations/<id>/revoke", methods=["POST"])
def revoke_paddle(id):
    require_role({"SaleAdministrator"})
    body = get_json_body()
    with db.LOCK:
        record = db.paddle_registrations.get(id)
        if record is None:
            raise err(errors.ERR_NOT_FOUND, "Paddle registration not found")
        validate_occ_field(body, "expected_paddle_registration_version", required=True)
        if record["status"] != "ACTIVE":
            raise err(errors.ERR_INVALID_STATE, "Paddle is not ACTIVE")
        match_occ(record, body, "expected_paddle_registration_version")
        record["status"] = "REVOKED"
        db.touch(record)
        return object_response(serialize(record), 200)
