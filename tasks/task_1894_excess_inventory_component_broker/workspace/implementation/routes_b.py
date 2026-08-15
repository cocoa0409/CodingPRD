"""Routes: buy offers pipeline, lots, market price snapshots."""

from flask import g

from calc import active_listings_for, bin_occupied_units, recompute_lot_posture
from core import (
    ApiError,
    DB,
    ERR_BIN_CAPACITY_EXCEEDED,
    ERR_BUY_OFFER_NOT_FOUND,
    ERR_INVALID_AMOUNT,
    ERR_INVALID_STATE,
    ERR_LOT_NOT_FOUND,
    ERR_PROVENANCE_DOCUMENT_REQUIRED,
    ERR_SELLER_NOT_FOUND,
    ERR_STORAGE_BIN_NOT_FOUND,
    body,
    forbid_ownership,
    list_response,
    new_entity,
    next_seq,
    new_id,
    now_dt,
    ok_object,
    opt_str,
    req_enum,
    req_int,
    req_str,
    require_roles,
    touch,
)
from serialize import ser_lot, ser_offer, ser_snapshot

INSPECTION_OUTCOMES = ("PASS", "FAIL_COUNTERFEIT", "FAIL_DAMAGED", "FAIL_DOCUMENTATION")
ACQUISITION_MODES = ("BROKER_OWNED", "CONSIGNMENT")


def _get_offer(oid):
    o = DB.offers.get(oid)
    if o is None:
        raise ApiError(ERR_BUY_OFFER_NOT_FOUND, 404, "Buy offer not found")
    return o


def _get_lot(lid):
    lot = DB.lots.get(lid)
    if lot is None:
        raise ApiError(ERR_LOT_NOT_FOUND, 404, "Lot not found")
    return lot


def register(app):
    # ---------------------------- buy offers --------------------------------
    @app.route("/buy-offers", methods=["POST"])
    def create_offer():
        require_roles("Seller")
        data = body()
        seller_id = req_str(data, "seller_id")
        mpn = req_str(data, "mpn")
        quantity = req_int(data, "quantity")
        ask = req_int(data, "ask_price_per_unit_cents")
        prov = opt_str(data, "provenance_doc_url", None)
        if seller_id != g.uid:
            forbid_ownership("Seller may only submit offers for own seller id")
        if seller_id not in DB.sellers:
            raise ApiError(ERR_SELLER_NOT_FOUND, 404, "Seller not found")
        if quantity <= 0:
            raise ApiError(ERR_INVALID_AMOUNT, 422, "quantity must be strictly positive")
        if ask <= 0:
            raise ApiError(
                ERR_INVALID_AMOUNT, 422, "ask_price_per_unit_cents must be strictly positive"
            )
        o = new_entity()
        o.update(
            {
                "seller_id": seller_id,
                "mpn": mpn,
                "quantity": quantity,
                "ask_price_per_unit_cents": ask,
                "provenance_doc_url": prov,
                "status": "PENDING_REVIEW",
                "agreed_unit_price_cents": None,
                "acquisition_mode": None,
                "inspection_result": "NONE",
                "failure_note": None,
            }
        )
        DB.offers[o["id"]] = o
        return ok_object(ser_offer(o), 201)

    @app.route("/buy-offers/<oid>", methods=["GET"])
    def get_offer(oid):
        require_roles("BrokerOps", "Inspector", "Seller")
        o = _get_offer(oid)
        if g.role == "Seller" and o["seller_id"] != g.uid:
            forbid_ownership("Seller may only read own buy offers")
        return ok_object(ser_offer(o))

    @app.route("/buy-offers/<oid>/accept", methods=["POST"])
    def accept_offer(oid):
        require_roles("BrokerOps")
        data = body()
        agreed = req_int(data, "agreed_unit_price_cents")
        mode = req_enum(data, "acquisition_mode", ACQUISITION_MODES)
        o = _get_offer(oid)
        if o["status"] != "PENDING_REVIEW":
            raise ApiError(ERR_INVALID_STATE, 409, "Offer is not PENDING_REVIEW")
        if agreed <= 0:
            raise ApiError(
                ERR_INVALID_AMOUNT,
                422,
                "agreed_unit_price_cents must be strictly positive",
            )
        o["agreed_unit_price_cents"] = agreed
        o["acquisition_mode"] = mode
        o["status"] = "ACCEPTED"
        touch(o)
        return ok_object(ser_offer(o))

    @app.route("/buy-offers/<oid>/reject", methods=["POST"])
    def reject_offer(oid):
        require_roles("BrokerOps")
        o = _get_offer(oid)
        if o["status"] != "PENDING_REVIEW":
            raise ApiError(ERR_INVALID_STATE, 409, "Offer is not PENDING_REVIEW")
        o["status"] = "REJECTED"
        touch(o)
        return ok_object(ser_offer(o))

    @app.route("/buy-offers/<oid>/cancel", methods=["POST"])
    def cancel_offer(oid):
        require_roles("Seller")
        o = _get_offer(oid)
        if o["seller_id"] != g.uid:
            forbid_ownership("Seller may only cancel own buy offers")
        if o["status"] != "PENDING_REVIEW":
            raise ApiError(ERR_INVALID_STATE, 409, "Offer is not PENDING_REVIEW")
        o["status"] = "CANCELLED"
        touch(o)
        return ok_object(ser_offer(o))

    @app.route("/buy-offers/<oid>/receive", methods=["POST"])
    def receive_offer(oid):
        require_roles("BrokerOps")
        o = _get_offer(oid)
        if o["status"] != "ACCEPTED":
            raise ApiError(ERR_INVALID_STATE, 409, "Offer is not ACCEPTED")
        o["status"] = "UNDER_INSPECTION"
        touch(o)
        return ok_object(ser_offer(o))

    @app.route("/buy-offers/<oid>/inspect", methods=["POST"])
    def inspect_offer(oid):
        require_roles("Inspector")
        data = body()
        outcome = req_enum(data, "outcome", INSPECTION_OUTCOMES)
        prov = opt_str(data, "provenance_doc_url", None)
        note = opt_str(data, "failure_note", None)
        o = _get_offer(oid)
        if o["status"] != "UNDER_INSPECTION":
            raise ApiError(ERR_INVALID_STATE, 409, "Offer is not UNDER_INSPECTION")
        if outcome == "PASS":
            if not o["provenance_doc_url"] and not prov:
                raise ApiError(
                    ERR_PROVENANCE_DOCUMENT_REQUIRED,
                    422,
                    "PASS requires a provenance document on the offer or in the payload",
                )
            if prov:
                o["provenance_doc_url"] = prov
            o["inspection_result"] = "PASS"
            o["status"] = "INSPECTION_PASSED"
        else:
            o["inspection_result"] = outcome
            o["failure_note"] = note
            o["status"] = "INSPECTION_FAILED"
        touch(o)
        return ok_object(ser_offer(o))

    @app.route("/buy-offers/<oid>/convert-to-lot", methods=["POST"])
    def convert_to_lot(oid):
        require_roles("BrokerOps")
        data = body()
        bin_id = req_str(data, "storage_bin_id")
        o = _get_offer(oid)
        b = DB.bins.get(bin_id)
        if b is None:
            raise ApiError(ERR_STORAGE_BIN_NOT_FOUND, 404, "Storage bin not found")
        if o["status"] != "INSPECTION_PASSED":
            raise ApiError(ERR_INVALID_STATE, 409, "Offer is not INSPECTION_PASSED")
        available = b["capacity_units"] - bin_occupied_units(b["id"])
        if o["quantity"] > available:
            raise ApiError(
                ERR_BIN_CAPACITY_EXCEEDED, 422, "Offer quantity exceeds bin capacity"
            )
        lot = new_entity()
        lot.update(
            {
                "buy_offer_id": o["id"],
                "mpn": o["mpn"],
                "storage_bin_id": b["id"],
                "storage_mode": o["acquisition_mode"],
                "quantity_received": o["quantity"],
                "qty_available": o["quantity"],
                "qty_reserved": 0,
                "qty_sold": 0,
                "qty_returned": 0,
                "cost_basis_per_unit_cents": o["agreed_unit_price_cents"],
                "received_at": now_dt(),
                "is_counterfeit_suspect": False,
                "status": "IN_STOCK",
                "_quarantined": False,
            }
        )
        DB.lots[lot["id"]] = lot
        o["status"] = "CONVERTED"
        touch(o)
        return ok_object(ser_lot(lot), 201)

    @app.route("/buy-offers/<oid>/initiate-return", methods=["POST"])
    def initiate_return(oid):
        require_roles("BrokerOps")
        o = _get_offer(oid)
        if o["status"] != "INSPECTION_FAILED":
            raise ApiError(ERR_INVALID_STATE, 409, "Offer is not INSPECTION_FAILED")
        o["status"] = "RETURN_PENDING"
        touch(o)
        return ok_object(ser_offer(o))

    @app.route("/buy-offers/<oid>/mark-returned", methods=["POST"])
    def mark_returned(oid):
        require_roles("BrokerOps")
        o = _get_offer(oid)
        if o["status"] != "RETURN_PENDING":
            raise ApiError(ERR_INVALID_STATE, 409, "Offer is not RETURN_PENDING")
        o["status"] = "RETURNED"
        touch(o)
        return ok_object(ser_offer(o))

    # -------------------------------- lots ----------------------------------
    @app.route("/lots", methods=["GET"])
    def list_lots():
        require_roles("BrokerOps", "Inspector", "FinanceAdmin")
        from flask import request

        f_offer = request.args.get("buy_offer_id")
        f_bin = request.args.get("storage_bin_id")
        items = [
            lot
            for lot in DB.lots.values()
            if (f_offer is None or lot["buy_offer_id"] == f_offer)
            and (f_bin is None or lot["storage_bin_id"] == f_bin)
        ]
        items.sort(key=lambda e: (e["created_at"], e["_seq"]))
        return list_response(items, ser_lot)

    @app.route("/lots/<lid>", methods=["GET"])
    def get_lot(lid):
        require_roles("BrokerOps", "Inspector", "FinanceAdmin")
        return ok_object(ser_lot(_get_lot(lid)))

    @app.route("/lots/<lid>/flag-counterfeit-suspect", methods=["POST"])
    def flag_counterfeit(lid):
        require_roles("Inspector")
        lot = _get_lot(lid)
        lot["is_counterfeit_suspect"] = True
        touch(lot)
        return ok_object(ser_lot(lot))

    @app.route("/lots/<lid>/quarantine", methods=["POST"])
    def quarantine_lot(lid):
        require_roles("Inspector")
        body()  # optional quarantine_note accepted and ignored
        lot = _get_lot(lid)
        if not lot["is_counterfeit_suspect"] or lot["status"] == "DEPLETED":
            raise ApiError(
                ERR_INVALID_STATE,
                409,
                "Quarantine requires suspect flag set and lot not DEPLETED",
            )
        lot["_quarantined"] = True
        for lst in active_listings_for(lot["id"]):
            lst["status"] = "WITHDRAWN"
            touch(lst)
        recompute_lot_posture(lot)
        return ok_object(ser_lot(lot))

    @app.route("/lots/<lid>/release-quarantine", methods=["POST"])
    def release_quarantine(lid):
        require_roles("Inspector")
        lot = _get_lot(lid)
        if lot["status"] != "QUARANTINED":
            raise ApiError(ERR_INVALID_STATE, 409, "Lot is not QUARANTINED")
        lot["_quarantined"] = False
        lot["is_counterfeit_suspect"] = False
        recompute_lot_posture(lot)
        return ok_object(ser_lot(lot))

    # ------------------------ market price snapshots ------------------------
    @app.route("/market-price-snapshots", methods=["POST"])
    def create_snapshot():
        require_roles("BrokerOps")
        data = body()
        mpn = req_str(data, "mpn")
        spot = req_int(data, "spot_price_cents")
        source = req_str(data, "source")
        if spot <= 0:
            raise ApiError(
                ERR_INVALID_AMOUNT, 422, "spot_price_cents must be strictly positive"
            )
        s = {
            "id": new_id(),
            "created_at": now_dt(),
            "_seq": next_seq(),
            "mpn": mpn,
            "spot_price_cents": spot,
            "source": source,
            "observed_at": now_dt(),
        }
        DB.snapshots[s["id"]] = s
        return ok_object(ser_snapshot(s), 201)

    @app.route("/market-price-snapshots", methods=["GET"])
    def list_snapshots():
        require_roles("BrokerOps", "Inspector", "FinanceAdmin")
        from flask import request

        f_mpn = request.args.get("mpn")
        items = [
            s for s in DB.snapshots.values() if f_mpn is None or s["mpn"] == f_mpn
        ]
        items.sort(key=lambda e: (e["observed_at"], e["created_at"], e["_seq"]), reverse=True)
        return list_response(items, ser_snapshot)
