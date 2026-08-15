"""Routes: sales orders, escrow ledger, return cases."""

from flask import g

from calc import (
    current_agreement,
    customer_exposure,
    escrow_entry,
    escrow_split,
    final_settlement_pricing,
    lot_of_order,
    provisional_pricing,
    recompute_lot_posture,
)
from core import (
    ApiError,
    DB,
    ERR_COUNTERFEIT_SUSPECTED,
    ERR_CUSTOMER_NOT_FOUND,
    ERR_ESCROW_OVERPAYMENT,
    ERR_INSUFFICIENT_CUSTOMER_CREDIT,
    ERR_INVALID_AMOUNT,
    ERR_INVALID_STATE,
    ERR_LISTING_NOT_ACTIVE,
    ERR_LISTING_NOT_FOUND,
    ERR_LOT_QUARANTINED,
    ERR_ORDER_NOT_DELIVERED,
    ERR_QUANTITY_EXCEEDS_AVAILABLE,
    ERR_RETURN_CASE_NOT_FOUND,
    ERR_SALES_ORDER_NOT_FOUND,
    body,
    forbid_ownership,
    list_response,
    new_entity,
    now_dt,
    ok_object,
    opt_str,
    req_enum,
    req_int,
    req_str,
    require_roles,
    touch,
)
from serialize import ser_escrow_entry, ser_order, ser_return_case

RETURN_REASONS = (
    "COUNTERFEIT_SUSPECTED",
    "DAMAGED",
    "WRONG_PART",
    "FAILED_INCOMING_INSPECTION",
)


def _get_order(oid):
    o = DB.orders.get(oid)
    if o is None:
        raise ApiError(ERR_SALES_ORDER_NOT_FOUND, 404, "Sales order not found")
    return o


def _get_case(rid):
    rc = DB.return_cases.get(rid)
    if rc is None:
        raise ApiError(ERR_RETURN_CASE_NOT_FOUND, 404, "Return case not found")
    return rc


def _check_order_ownership(order):
    if g.role == "Customer" and order["customer_id"] != g.uid:
        forbid_ownership("Customer may only act on own orders")


def register(app):
    # ---------------------------- sales orders ------------------------------
    @app.route("/sales-orders", methods=["POST"])
    def create_order():
        require_roles("Customer")
        data = body()
        customer_id = req_str(data, "customer_id")
        listing_id = req_str(data, "listing_id")
        quantity = req_int(data, "quantity")
        if customer_id != g.uid:
            forbid_ownership("customer_id must equal the acting Customer id")
        customer = DB.customers.get(customer_id)
        if customer is None:
            raise ApiError(ERR_CUSTOMER_NOT_FOUND, 404, "Customer not found")
        listing = DB.listings.get(listing_id)
        if listing is None:
            raise ApiError(ERR_LISTING_NOT_FOUND, 404, "Listing not found")
        lot = DB.lots.get(listing["lot_id"])
        if listing["status"] != "ACTIVE":
            raise ApiError(ERR_LISTING_NOT_ACTIVE, 409, "Listing is not ACTIVE")
        if lot["is_counterfeit_suspect"]:
            raise ApiError(
                ERR_COUNTERFEIT_SUSPECTED, 422, "Lot is flagged counterfeit suspect"
            )
        if quantity > lot["qty_available"]:
            raise ApiError(
                ERR_QUANTITY_EXCEEDS_AVAILABLE,
                422,
                "Order quantity exceeds lot availability",
            )
        unit, total, required = provisional_pricing(listing, customer, quantity)
        if customer_exposure(customer_id) + required > customer["credit_limit_cents"]:
            raise ApiError(
                ERR_INSUFFICIENT_CUSTOMER_CREDIT,
                402,
                "Open-order exposure would exceed the customer credit limit",
            )
        if quantity <= 0:
            raise ApiError(ERR_INVALID_AMOUNT, 422, "quantity must be strictly positive")
        fee_bps_snapshot = None
        if lot["storage_mode"] == "CONSIGNMENT":
            agreement = current_agreement(lot["id"])
            fee_bps_snapshot = agreement["broker_fee_bps"] if agreement else None
        lot["qty_available"] -= quantity
        lot["qty_reserved"] += quantity
        recompute_lot_posture(lot)
        o = new_entity()
        o.update(
            {
                "customer_id": customer_id,
                "listing_id": listing_id,
                "quantity": quantity,
                "urgency_tier_snapshot": customer["urgency_tier"],
                "consignment_fee_bps_snapshot": fee_bps_snapshot,
                "provisional_unit_price_cents": unit,
                "provisional_total_cents": total,
                "required_escrow_cents": required,
                "escrow_funded_cents": 0,
                "final_unit_price_cents": None,
                "final_total_cents": None,
                "customer_refund_cents": None,
                "status": "PENDING_ESCROW",
            }
        )
        DB.orders[o["id"]] = o
        return ok_object(ser_order(o), 201)

    @app.route("/sales-orders", methods=["GET"])
    def list_orders():
        require_roles("BrokerOps", "FinanceAdmin")
        from flask import request

        f_customer = request.args.get("customer_id")
        f_listing = request.args.get("listing_id")
        items = [
            o
            for o in DB.orders.values()
            if (f_customer is None or o["customer_id"] == f_customer)
            and (f_listing is None or o["listing_id"] == f_listing)
        ]
        items.sort(key=lambda e: (e["created_at"], e["_seq"]))
        return list_response(items, ser_order)

    @app.route("/sales-orders/<oid>", methods=["GET"])
    def get_order(oid):
        require_roles("BrokerOps", "FinanceAdmin", "Customer")
        o = _get_order(oid)
        _check_order_ownership(o)
        return ok_object(ser_order(o))

    @app.route("/sales-orders/<oid>/escrow/deposit", methods=["POST"])
    def deposit(oid):
        require_roles("Customer")
        data = body()
        amount = req_int(data, "amount_cents")
        o = _get_order(oid)
        _check_order_ownership(o)
        if o["status"] != "PENDING_ESCROW":
            raise ApiError(ERR_INVALID_STATE, 409, "Order is not PENDING_ESCROW")
        if o["escrow_funded_cents"] + amount > o["required_escrow_cents"]:
            raise ApiError(
                ERR_ESCROW_OVERPAYMENT,
                422,
                "Deposit would exceed the required escrow amount",
            )
        if amount <= 0:
            raise ApiError(
                ERR_INVALID_AMOUNT, 422, "amount_cents must be strictly positive"
            )
        escrow_entry(o["id"], "DEPOSIT", amount, "Customer escrow deposit")
        o["escrow_funded_cents"] += amount
        if o["escrow_funded_cents"] == o["required_escrow_cents"]:
            o["status"] = "ESCROW_FUNDED"
        touch(o)
        return ok_object(ser_order(o))

    @app.route("/sales-orders/<oid>/fulfill", methods=["POST"])
    def fulfill(oid):
        require_roles("BrokerOps")
        o = _get_order(oid)
        if o["status"] != "ESCROW_FUNDED":
            raise ApiError(ERR_INVALID_STATE, 409, "Order is not ESCROW_FUNDED")
        lot = lot_of_order(o)
        if lot is not None and lot["status"] == "QUARANTINED":
            raise ApiError(ERR_LOT_QUARANTINED, 409, "Lot is QUARANTINED")
        o["status"] = "FULFILLING"
        touch(o)
        return ok_object(ser_order(o))

    @app.route("/sales-orders/<oid>/ship", methods=["POST"])
    def ship(oid):
        require_roles("BrokerOps")
        o = _get_order(oid)
        if o["status"] != "FULFILLING":
            raise ApiError(ERR_INVALID_STATE, 409, "Order is not FULFILLING")
        o["status"] = "SHIPPED"
        touch(o)
        return ok_object(ser_order(o))

    @app.route("/sales-orders/<oid>/deliver", methods=["POST"])
    def deliver(oid):
        require_roles("BrokerOps")
        o = _get_order(oid)
        if o["status"] != "SHIPPED":
            raise ApiError(ERR_INVALID_STATE, 409, "Order is not SHIPPED")
        o["status"] = "DELIVERED"
        touch(o)
        return ok_object(ser_order(o))

    @app.route("/sales-orders/<oid>/settle", methods=["POST"])
    def settle(oid):
        require_roles("FinanceAdmin")
        o = _get_order(oid)
        if o["status"] != "DELIVERED":
            raise ApiError(ERR_INVALID_STATE, 409, "Order is not DELIVERED")
        lot = lot_of_order(o)
        if lot is not None and lot["status"] == "QUARANTINED":
            raise ApiError(ERR_LOT_QUARANTINED, 409, "Lot is QUARANTINED")
        final_unit, final_total, refund = final_settlement_pricing(o, lot, now_dt())
        if refund > 0:
            escrow_entry(
                o["id"], "CUSTOMER_REFUND", -refund, "Customer escrow refund at settlement"
            )
        if lot["storage_mode"] == "BROKER_OWNED":
            escrow_entry(
                o["id"], "BROKER_REVENUE", -final_total, "Broker revenue at settlement"
            )
        else:
            fee, payout = escrow_split(
                final_total, o["consignment_fee_bps_snapshot"] or 0
            )
            escrow_entry(o["id"], "BROKER_FEE", -fee, "Broker consignment fee")
            escrow_entry(o["id"], "SELLER_PAYOUT", -payout, "Seller consignment payout")
        lot["qty_reserved"] -= o["quantity"]
        lot["qty_sold"] += o["quantity"]
        recompute_lot_posture(lot)
        o["final_unit_price_cents"] = final_unit
        o["final_total_cents"] = final_total
        o["customer_refund_cents"] = refund
        o["status"] = "SETTLED"
        touch(o)
        return ok_object(ser_order(o))

    @app.route("/sales-orders/<oid>/cancel", methods=["POST"])
    def cancel_order(oid):
        require_roles("Customer", "BrokerOps")
        o = _get_order(oid)
        _check_order_ownership(o)
        if o["status"] not in ("PENDING_ESCROW", "ESCROW_FUNDED"):
            raise ApiError(
                ERR_INVALID_STATE,
                409,
                "Only PENDING_ESCROW or ESCROW_FUNDED orders may be cancelled",
            )
        if o["escrow_funded_cents"] > 0:
            escrow_entry(
                o["id"],
                "CUSTOMER_REFUND",
                -o["escrow_funded_cents"],
                "Customer escrow refund at cancellation",
            )
        lot = lot_of_order(o)
        if lot is not None:
            lot["qty_reserved"] -= o["quantity"]
            lot["qty_available"] += o["quantity"]
            recompute_lot_posture(lot)
        o["status"] = "CANCELLED"
        touch(o)
        return ok_object(ser_order(o))

    # ---------------------------- escrow ledger -----------------------------
    @app.route("/sales-orders/<oid>/escrow-entries", methods=["GET"])
    def escrow_entries(oid):
        require_roles("BrokerOps", "FinanceAdmin", "Customer")
        o = _get_order(oid)
        _check_order_ownership(o)
        items = sorted(
            (e for e in DB.escrow.values() if e["sales_order_id"] == o["id"]),
            key=lambda e: (e["created_at"], e["_seq"]),
        )
        return list_response(items, ser_escrow_entry)

    # ---------------------------- return cases ------------------------------
    @app.route("/return-cases", methods=["POST"])
    def create_return_case():
        require_roles("Customer")
        data = body()
        order_id = req_str(data, "sales_order_id")
        reason = req_enum(data, "reason", RETURN_REASONS)
        o = DB.orders.get(order_id)
        if o is None:
            raise ApiError(ERR_SALES_ORDER_NOT_FOUND, 404, "Sales order not found")
        if o["customer_id"] != g.uid:
            forbid_ownership("Customer may only open return cases on own orders")
        if o["status"] != "DELIVERED":
            raise ApiError(ERR_ORDER_NOT_DELIVERED, 409, "Order is not DELIVERED")
        rc = new_entity()
        rc.update(
            {
                "sales_order_id": o["id"],
                "reason": reason,
                "status": "OPENED",
                "refund_amount_cents": None,
                "rejection_note": None,
            }
        )
        DB.return_cases[rc["id"]] = rc
        return ok_object(ser_return_case(rc), 201)

    @app.route("/return-cases/<rid>", methods=["GET"])
    def get_return_case(rid):
        require_roles("BrokerOps", "FinanceAdmin", "Customer")
        rc = _get_case(rid)
        o = DB.orders.get(rc["sales_order_id"])
        if g.role == "Customer" and (o is None or o["customer_id"] != g.uid):
            forbid_ownership("Customer may only read own return cases")
        return ok_object(ser_return_case(rc))

    @app.route("/sales-orders/<oid>/return-cases", methods=["GET"])
    def list_return_cases(oid):
        require_roles("BrokerOps", "FinanceAdmin", "Customer")
        o = _get_order(oid)
        _check_order_ownership(o)
        items = sorted(
            (rc for rc in DB.return_cases.values() if rc["sales_order_id"] == o["id"]),
            key=lambda e: (e["created_at"], e["_seq"]),
        )
        return list_response(items, ser_return_case)

    @app.route("/return-cases/<rid>/start-review", methods=["POST"])
    def start_review(rid):
        require_roles("BrokerOps")
        rc = _get_case(rid)
        if rc["status"] != "OPENED":
            raise ApiError(ERR_INVALID_STATE, 409, "Return case is not OPENED")
        rc["status"] = "UNDER_REVIEW"
        touch(rc)
        return ok_object(ser_return_case(rc))

    @app.route("/return-cases/<rid>/approve", methods=["POST"])
    def approve_return(rid):
        require_roles("BrokerOps")
        rc = _get_case(rid)
        if rc["status"] != "UNDER_REVIEW":
            raise ApiError(ERR_INVALID_STATE, 409, "Return case is not UNDER_REVIEW")
        o = DB.orders.get(rc["sales_order_id"])
        if o is None or o["status"] != "DELIVERED":
            raise ApiError(ERR_ORDER_NOT_DELIVERED, 409, "Order is not DELIVERED")
        rc["refund_amount_cents"] = o["escrow_funded_cents"]
        rc["status"] = "APPROVED"
        touch(rc)
        o["status"] = "REFUND_PENDING"
        touch(o)
        return ok_object(ser_return_case(rc))

    @app.route("/return-cases/<rid>/reject", methods=["POST"])
    def reject_return(rid):
        require_roles("BrokerOps")
        data = body()
        note = opt_str(data, "rejection_note", None)
        rc = _get_case(rid)
        if rc["status"] != "UNDER_REVIEW":
            raise ApiError(ERR_INVALID_STATE, 409, "Return case is not UNDER_REVIEW")
        rc["rejection_note"] = note
        rc["status"] = "REJECTED"
        touch(rc)
        return ok_object(ser_return_case(rc))

    @app.route("/return-cases/<rid>/issue-refund", methods=["POST"])
    def issue_refund(rid):
        require_roles("FinanceAdmin")
        rc = _get_case(rid)
        if rc["status"] != "APPROVED":
            raise ApiError(ERR_INVALID_STATE, 409, "Return case is not APPROVED")
        o = DB.orders.get(rc["sales_order_id"])
        escrow_entry(
            o["id"],
            "CUSTOMER_REFUND",
            -rc["refund_amount_cents"],
            "Customer refund for approved return",
        )
        o["status"] = "REFUNDED"
        touch(o)
        lot = lot_of_order(o)
        if lot is not None:
            lot["qty_reserved"] -= o["quantity"]
            lot["qty_returned"] += o["quantity"]
            recompute_lot_posture(lot)
        rc["status"] = "REFUND_ISSUED"
        touch(rc)
        return ok_object(ser_return_case(rc))
