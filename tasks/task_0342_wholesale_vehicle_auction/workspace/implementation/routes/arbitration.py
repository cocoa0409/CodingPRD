"""ArbitrationClaim endpoints (PRD §3.10)."""
from flask import Blueprint, request

import db
from errors import ApiError
from middleware import get_auth, require_role
from response import success_object, success_list
from services.common import (
    base_record, touch, get_body, require_str, require_int, require_enum,
    public, list_collection,
)
from services import lookup, cascade, calc

bp = Blueprint("arbitration", __name__)


@bp.route("/auction/arbitration-claims", methods=["POST"])
def create_claim():
    user_id, role = get_auth()
    require_role(role, {"Buyer"})
    body = get_body()
    lot_id = require_str(body, "lot_id")
    buyer_id = require_str(body, "buyer_id")
    reason_code = require_enum(body, "reason_code",
                              ("UNDISCLOSED_DAMAGE", "TITLE_DISCREPANCY", "MECHANICAL"))
    claimed = require_int(body, "claimed_cents", positive=True)

    with db.lock:
        # ownership (priority 3): buyer may only claim under own buyer_id
        if buyer_id != user_id:
            raise ApiError("ERR_NOT_RESOURCE_OWNER", "Buyer may only claim under own id.")
        # existence (priority 4)
        lookup.get_lot(lot_id)
        lookup.get_buyer(buyer_id)
        rec = base_record()
        rec.update({
            "lot_id": lot_id,
            "buyer_id": buyer_id,
            "reason_code": reason_code,
            "claimed_cents": claimed,
            "approved_cents": 0,
            "resolution": "PENDING",
            "status": "OPEN",
        })
        db.arbitration_claims[rec["id"]] = rec
        return success_object(public(rec), 201)


@bp.route("/auction/arbitration-claims", methods=["GET"])
def list_claims():
    _, role = get_auth()
    require_role(role, {"AuctionAdmin", "Buyer", "Arbitrator"})
    filters = {
        "lot_id": request.args.get("lot_id"),
        "buyer_id": request.args.get("buyer_id"),
        "status": request.args.get("status"),
    }
    items, limit, offset, total = list_collection(db.arbitration_claims, filters)
    return success_list(items, limit, offset, total)


@bp.route("/auction/arbitration-claims/<claim_id>", methods=["GET"])
def get_claim(claim_id):
    _, role = get_auth()
    require_role(role, {"AuctionAdmin", "Buyer", "Arbitrator"})
    with db.lock:
        claim = lookup.get_claim(claim_id)
        return success_object(public(claim))


@bp.route("/auction/arbitration-claims/<claim_id>/rule", methods=["POST"])
def rule_claim(claim_id):
    _, role = get_auth()
    require_role(role, {"Arbitrator"})
    with db.lock:
        claim = lookup.get_claim(claim_id)
        if claim["status"] != "OPEN":
            raise ApiError("ERR_CLAIM_NOT_OPEN", "Claim not OPEN.")
        lot = db.lots.get(claim["lot_id"])
        settlement = cascade.settlement_for_lot(claim["lot_id"]) if lot else None
        if settlement is None or settlement["payment_status"] != "PAID":
            raise ApiError("ERR_SETTLEMENT_NOT_PAID", "Settlement not PAID.")

        consignment = db.consignments.get(lot["consignment_id"])
        cr = cascade.condition_report_for(consignment["id"]) if consignment else None
        as_is = bool(cr["as_is"]) if cr else False
        grade = cr["grade"] if cr else None

        approved, resolution = calc.arbitration_credit(
            claim["claimed_cents"], settlement["sale_price_cents"],
            claim["reason_code"], as_is, grade)

        claim["approved_cents"] = approved
        claim["resolution"] = resolution
        claim["status"] = "RESOLVED"
        touch(claim)

        if resolution == "APPROVED_PARTIAL":
            seller = db.sellers.get(settlement["seller_id"])
            schedule = db.sales.get(lot["sale_id"])["buyer_fee_schedule_code"]
            from routes.lots import _winning_channel
            channel = _winning_channel(lot)

            old_total = settlement["total_due_cents"]
            new_sale_price = settlement["sale_price_cents"] - approved
            settlement["sale_price_cents"] = new_sale_price
            new_fee = calc.buyer_fee(new_sale_price, schedule, channel)
            new_total = calc.buyer_total_due(new_sale_price, new_fee)
            settlement["buyer_fee_cents"] = new_fee
            settlement["total_due_cents"] = new_total
            settlement["seller_proceeds_cents"] = calc.seller_net_proceeds(
                new_sale_price, seller["seller_fee_pct"] if seller else 0, as_is)
            touch(settlement)

            # mirror seller proceeds onto consignment
            if consignment is not None:
                consignment["expected_proceeds_cents"] = settlement["seller_proceeds_cents"]
                touch(consignment)

            # re-credit buyer by (old_total - new_total) via recompute
            buyer = db.buyers.get(settlement["buyer_id"])
            if buyer is not None:
                cascade.recompute_buyer_credit(buyer)

        elif resolution == "APPROVED_FULL":
            settlement["sale_price_cents"] = settlement["sale_price_cents"]  # unchanged
            cascade.unwind_settlement(settlement)

        # DENIED: no economic change
        return success_object(public(claim))
