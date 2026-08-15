"""Routes: logical clock, sellers, customers, storage bins."""

from flask import g

from calc import active_listings_for, recompute_lot_posture
from core import (
    ApiError,
    DB,
    ERR_CUSTOMER_NOT_FOUND,
    ERR_DUPLICATE_BIN_CODE,
    ERR_FORBIDDEN_OWNERSHIP,
    ERR_INVALID_AMOUNT,
    ERR_INVALID_REQUEST,
    ERR_SELLER_NOT_FOUND,
    ERR_STORAGE_BIN_NOT_FOUND,
    body,
    forbid_ownership,
    iso,
    list_response,
    new_entity,
    ok_object,
    opt_enum,
    opt_int,
    parse_dt,
    req_int,
    req_str,
    require_roles,
    touch,
)
from serialize import ser_bin, ser_customer, ser_offer, ser_seller

URGENCY_TIERS = ("STANDARD", "PRIORITY", "CRITICAL")


def register(app):
    # ------------------------------ clock -----------------------------------
    @app.route("/_clock/set_current_utc", methods=["POST"])
    def set_current_utc():
        require_roles("BrokerOps")
        data = body()
        if "to_iso8601" not in data or data["to_iso8601"] is None:
            raise ApiError(ERR_INVALID_REQUEST, 400, "to_iso8601 is required")
        target = parse_dt(data["to_iso8601"])
        if target is None:
            raise ApiError(
                ERR_INVALID_REQUEST, 400, "to_iso8601 must be an ISO 8601 timestamp"
            )
        DB.clock = target
        # Consignment expiry sweep with listing pause cascade.
        for a in list(DB.agreements.values()):
            if a["status"] == "ACTIVE" and a["effective_to"] <= target:
                a["status"] = "EXPIRED"
                touch(a)
                lot = DB.lots.get(a["lot_id"])
                if lot is not None:
                    for lst in active_listings_for(lot["id"]):
                        lst["status"] = "PAUSED"
                        touch(lst)
                    recompute_lot_posture(lot)
        return ok_object({"current_utc": iso(DB.clock)})

    # ------------------------------ sellers ---------------------------------
    @app.route("/sellers", methods=["POST"])
    def create_seller():
        require_roles("BrokerOps")
        data = body()
        name = req_str(data, "name")
        email = req_str(data, "contact_email")
        payout = opt_int(data, "payout_terms_days", 30)
        s = new_entity()
        s.update(
            {"name": name, "contact_email": email, "payout_terms_days": payout}
        )
        DB.sellers[s["id"]] = s
        return ok_object(ser_seller(s), 201)

    @app.route("/sellers/<sid>", methods=["GET"])
    def get_seller(sid):
        require_roles("BrokerOps", "FinanceAdmin", "Seller")
        if g.role == "Seller" and sid != g.uid:
            forbid_ownership("Seller may only read own seller record")
        s = DB.sellers.get(sid)
        if s is None:
            raise ApiError(ERR_SELLER_NOT_FOUND, 404, "Seller not found")
        return ok_object(ser_seller(s))

    @app.route("/sellers/<sid>/buy-offers", methods=["GET"])
    def seller_buy_offers(sid):
        require_roles("BrokerOps", "Inspector", "Seller")
        if g.role == "Seller" and sid != g.uid:
            forbid_ownership("Seller may only list own buy offers")
        if sid not in DB.sellers:
            raise ApiError(ERR_SELLER_NOT_FOUND, 404, "Seller not found")
        items = sorted(
            (o for o in DB.offers.values() if o["seller_id"] == sid),
            key=lambda e: (e["created_at"], e["_seq"]),
        )
        return list_response(items, ser_offer)

    # ----------------------------- customers --------------------------------
    @app.route("/customers", methods=["POST"])
    def create_customer():
        require_roles("BrokerOps")
        data = body()
        name = req_str(data, "name")
        email = req_str(data, "contact_email")
        credit = req_int(data, "credit_limit_cents")
        tier = opt_enum(data, "urgency_tier", URGENCY_TIERS, "STANDARD")
        if credit < 0:
            raise ApiError(
                ERR_INVALID_AMOUNT, 422, "credit_limit_cents must not be negative"
            )
        c = new_entity()
        c.update(
            {
                "name": name,
                "contact_email": email,
                "urgency_tier": tier,
                "credit_limit_cents": credit,
            }
        )
        DB.customers[c["id"]] = c
        return ok_object(ser_customer(c), 201)

    @app.route("/customers/<cid>", methods=["GET"])
    def get_customer(cid):
        require_roles("BrokerOps", "FinanceAdmin", "Customer")
        if g.role == "Customer" and cid != g.uid:
            forbid_ownership("Customer may only read own customer record")
        c = DB.customers.get(cid)
        if c is None:
            raise ApiError(ERR_CUSTOMER_NOT_FOUND, 404, "Customer not found")
        return ok_object(ser_customer(c))

    # ---------------------------- storage bins ------------------------------
    @app.route("/storage-bins", methods=["POST"])
    def create_bin():
        require_roles("BrokerOps")
        data = body()
        bin_code = req_str(data, "bin_code")
        capacity = req_int(data, "capacity_units")
        if any(b["bin_code"] == bin_code for b in DB.bins.values()):
            raise ApiError(ERR_DUPLICATE_BIN_CODE, 422, "bin_code already in use")
        if capacity <= 0:
            raise ApiError(
                ERR_INVALID_AMOUNT, 422, "capacity_units must be strictly positive"
            )
        b = new_entity()
        b.update({"bin_code": bin_code, "capacity_units": capacity})
        DB.bins[b["id"]] = b
        return ok_object(ser_bin(b), 201)

    @app.route("/storage-bins/<bid>", methods=["GET"])
    def get_bin(bid):
        require_roles("BrokerOps", "Inspector")
        b = DB.bins.get(bid)
        if b is None:
            raise ApiError(ERR_STORAGE_BIN_NOT_FOUND, 404, "Storage bin not found")
        return ok_object(ser_bin(b))
