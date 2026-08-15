"""Routes: consignment agreements, listings."""

from calc import (
    asking_price_floor,
    current_agreement,
    recompute_lot_posture,
)
from core import (
    ApiError,
    DB,
    ERR_AGREEMENT_NOT_ACTIVE,
    ERR_ASKING_BELOW_COST_FLOOR,
    ERR_CONSIGNMENT_AGREEMENT_NOT_FOUND,
    ERR_CONSIGNMENT_SELLER_MISMATCH,
    ERR_CONSIGNMENT_WINDOW_INVALID,
    ERR_CONSIGNMENT_WINDOW_OVERLAP,
    ERR_COUNTERFEIT_SUSPECTED,
    ERR_INVALID_AMOUNT,
    ERR_INVALID_STATE,
    ERR_INVALID_FEE_BPS,
    ERR_LISTING_NOT_FOUND,
    ERR_LOT_NOT_CONSIGNMENT,
    ERR_LOT_NOT_FOUND,
    ERR_LOT_NOT_IN_STOCK,
    ERR_NO_CURRENT_CONSIGNMENT_AGREEMENT,
    ERR_SELLER_NOT_FOUND,
    ERR_STALE_VERSION,
    body,
    list_response,
    new_entity,
    now_dt,
    ok_object,
    req_dt,
    req_int,
    req_str,
    require_roles,
    touch,
)
from serialize import ser_agreement, ser_listing


def _get_agreement(aid):
    a = DB.agreements.get(aid)
    if a is None:
        raise ApiError(
            ERR_CONSIGNMENT_AGREEMENT_NOT_FOUND, 404, "Consignment agreement not found"
        )
    return a


def _get_listing(lid):
    lst = DB.listings.get(lid)
    if lst is None:
        raise ApiError(ERR_LISTING_NOT_FOUND, 404, "Listing not found")
    return lst


def _check_floor(listing_asking, lot):
    if listing_asking < asking_price_floor(lot["cost_basis_per_unit_cents"]):
        raise ApiError(
            ERR_ASKING_BELOW_COST_FLOOR,
            422,
            "Asking price is below 80% of the lot cost basis",
        )


def _pause_active_listings_on_lot(lot_id):
    from calc import active_listings_for

    for lst in active_listings_for(lot_id):
        lst["status"] = "PAUSED"
        touch(lst)


def register(app):
    # ------------------------ consignment agreements ------------------------
    @app.route("/consignment-agreements", methods=["POST"])
    def create_agreement():
        require_roles("BrokerOps")
        data = body()
        seller_id = req_str(data, "seller_id")
        lot_id = req_str(data, "lot_id")
        eff_from = req_dt(data, "effective_from")
        eff_to = req_dt(data, "effective_to")
        fee_bps = req_int(data, "broker_fee_bps")
        if seller_id not in DB.sellers:
            raise ApiError(ERR_SELLER_NOT_FOUND, 404, "Seller not found")
        lot = DB.lots.get(lot_id)
        if lot is None:
            raise ApiError(ERR_LOT_NOT_FOUND, 404, "Lot not found")
        if lot["storage_mode"] != "CONSIGNMENT":
            raise ApiError(
                ERR_LOT_NOT_CONSIGNMENT, 409, "Lot storage_mode is not CONSIGNMENT"
            )
        if not eff_from < eff_to:
            raise ApiError(
                ERR_CONSIGNMENT_WINDOW_INVALID,
                422,
                "effective_from must be strictly earlier than effective_to",
            )
        for other in DB.agreements.values():
            if (
                other["lot_id"] == lot_id
                and other["status"] == "ACTIVE"
                and eff_from < other["effective_to"]
                and other["effective_from"] < eff_to
            ):
                raise ApiError(
                    ERR_CONSIGNMENT_WINDOW_OVERLAP,
                    409,
                    "Window overlaps an existing ACTIVE agreement on this lot",
                )
        origin = DB.offers.get(lot["buy_offer_id"])
        if origin is None or origin["seller_id"] != seller_id:
            raise ApiError(
                ERR_CONSIGNMENT_SELLER_MISMATCH,
                422,
                "Agreement seller differs from the lot's originating seller",
            )
        if not 1 <= fee_bps <= 5000:
            raise ApiError(
                ERR_INVALID_FEE_BPS, 422, "broker_fee_bps must be within 1..5000"
            )
        a = new_entity()
        a.update(
            {
                "seller_id": seller_id,
                "lot_id": lot_id,
                "effective_from": eff_from,
                "effective_to": eff_to,
                "broker_fee_bps": fee_bps,
                "status": "ACTIVE",
            }
        )
        DB.agreements[a["id"]] = a
        return ok_object(ser_agreement(a), 201)

    @app.route("/consignment-agreements", methods=["GET"])
    def list_agreements():
        require_roles("BrokerOps", "FinanceAdmin")
        from flask import request

        f_seller = request.args.get("seller_id")
        f_lot = request.args.get("lot_id")
        items = [
            a
            for a in DB.agreements.values()
            if (f_seller is None or a["seller_id"] == f_seller)
            and (f_lot is None or a["lot_id"] == f_lot)
        ]
        items.sort(key=lambda e: (e["created_at"], e["_seq"]))
        return list_response(items, ser_agreement)

    @app.route("/consignment-agreements/<aid>", methods=["GET"])
    def get_agreement(aid):
        require_roles("BrokerOps", "FinanceAdmin")
        return ok_object(ser_agreement(_get_agreement(aid)))

    @app.route("/consignment-agreements/<aid>/terminate", methods=["POST"])
    def terminate_agreement(aid):
        require_roles("BrokerOps")
        a = _get_agreement(aid)
        if a["status"] != "ACTIVE":
            raise ApiError(ERR_AGREEMENT_NOT_ACTIVE, 409, "Agreement is not ACTIVE")
        a["status"] = "TERMINATED"
        touch(a)
        lot = DB.lots.get(a["lot_id"])
        if lot is not None:
            _pause_active_listings_on_lot(lot["id"])
            recompute_lot_posture(lot)
        return ok_object(ser_agreement(a))

    # ------------------------------- listings -------------------------------
    @app.route("/listings", methods=["POST"])
    def create_listing():
        require_roles("BrokerOps")
        data = body()
        lot_id = req_str(data, "lot_id")
        asking = req_int(data, "asking_price_per_unit_cents")
        lot = DB.lots.get(lot_id)
        if lot is None:
            raise ApiError(ERR_LOT_NOT_FOUND, 404, "Lot not found")
        _check_floor(asking, lot)
        if asking <= 0:
            raise ApiError(
                ERR_INVALID_AMOUNT,
                422,
                "asking_price_per_unit_cents must be strictly positive",
            )
        lst = new_entity()
        lst.update(
            {
                "lot_id": lot_id,
                "asking_price_per_unit_cents": asking,
                "status": "DRAFT",
            }
        )
        DB.listings[lst["id"]] = lst
        return ok_object(ser_listing(lst), 201)

    @app.route("/listings", methods=["GET"])
    def list_listings():
        require_roles("BrokerOps", "Inspector", "FinanceAdmin", "Customer")
        from flask import request

        f_lot = request.args.get("lot_id")
        items = [
            lst
            for lst in DB.listings.values()
            if f_lot is None or lst["lot_id"] == f_lot
        ]
        items.sort(key=lambda e: (e["created_at"], e["_seq"]))
        return list_response(items, ser_listing)

    @app.route("/listings/<lid>", methods=["GET"])
    def get_listing(lid):
        require_roles("BrokerOps", "Inspector", "FinanceAdmin", "Customer")
        return ok_object(ser_listing(_get_listing(lid)))

    @app.route("/listings/<lid>", methods=["PATCH"])
    def reprice_listing(lid):
        require_roles("BrokerOps")
        data = body()
        asking = req_int(data, "asking_price_per_unit_cents")
        expected = req_int(data, "expected_listing_version")
        lst = _get_listing(lid)
        if expected != lst["version"]:
            raise ApiError(
                ERR_STALE_VERSION,
                412,
                "expected_listing_version does not match the listing version",
            )
        if lst["status"] not in ("DRAFT", "PAUSED"):
            raise ApiError(
                ERR_INVALID_STATE, 409, "Only DRAFT or PAUSED listings may be repriced"
            )
        lot = DB.lots.get(lst["lot_id"])
        _check_floor(asking, lot)
        if asking <= 0:
            raise ApiError(
                ERR_INVALID_AMOUNT,
                422,
                "asking_price_per_unit_cents must be strictly positive",
            )
        lst["asking_price_per_unit_cents"] = asking
        touch(lst)
        return ok_object(ser_listing(lst))

    @app.route("/listings/<lid>/activate", methods=["POST"])
    def activate_listing(lid):
        require_roles("BrokerOps")
        lst = _get_listing(lid)
        if lst["status"] not in ("DRAFT", "PAUSED"):
            raise ApiError(
                ERR_INVALID_STATE, 409, "Only DRAFT or PAUSED listings may be activated"
            )
        lot = DB.lots.get(lst["lot_id"])
        if lot["status"] != "IN_STOCK":
            raise ApiError(ERR_LOT_NOT_IN_STOCK, 409, "Lot posture is not IN_STOCK")
        if lot["is_counterfeit_suspect"]:
            raise ApiError(
                ERR_COUNTERFEIT_SUSPECTED, 422, "Lot is flagged counterfeit suspect"
            )
        if lot["storage_mode"] == "CONSIGNMENT" and current_agreement(lot["id"]) is None:
            raise ApiError(
                ERR_NO_CURRENT_CONSIGNMENT_AGREEMENT,
                409,
                "No current ACTIVE consignment agreement covers this lot",
            )
        _check_floor(lst["asking_price_per_unit_cents"], lot)
        lst["status"] = "ACTIVE"
        touch(lst)
        recompute_lot_posture(lot)
        return ok_object(ser_listing(lst))

    @app.route("/listings/<lid>/pause", methods=["POST"])
    def pause_listing(lid):
        require_roles("BrokerOps")
        lst = _get_listing(lid)
        if lst["status"] != "ACTIVE":
            raise ApiError(ERR_INVALID_STATE, 409, "Listing is not ACTIVE")
        lst["status"] = "PAUSED"
        touch(lst)
        lot = DB.lots.get(lst["lot_id"])
        if lot is not None:
            recompute_lot_posture(lot)
        return ok_object(ser_listing(lst))

    @app.route("/listings/<lid>/withdraw", methods=["POST"])
    def withdraw_listing(lid):
        require_roles("BrokerOps")
        lst = _get_listing(lid)
        if lst["status"] not in ("DRAFT", "ACTIVE", "PAUSED"):
            raise ApiError(
                ERR_INVALID_STATE,
                409,
                "Only DRAFT, ACTIVE or PAUSED listings may be withdrawn",
            )
        lst["status"] = "WITHDRAWN"
        touch(lst)
        lot = DB.lots.get(lst["lot_id"])
        if lot is not None:
            recompute_lot_posture(lot)
        return ok_object(ser_listing(lst))
