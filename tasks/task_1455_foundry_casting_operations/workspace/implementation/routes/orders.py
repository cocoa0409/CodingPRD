"""Casting order intake, cancellation, production counters (PRD 3.3)."""

from flask import request

from db import all_of, get, new_record, touch
from errors import fail
from middleware import auth, paged, require_role
from response import ok_list, ok_object
from util import (as_nonneg_int, as_nonneg_num, as_pos_int, as_str, body_dict,
                  opt, req)

ORDER_ROLES = {"FoundryAdmin", "LineOperator", "WarrantyManager", "Customer"}


def register(app):
    @app.route("/api/orders", methods=["POST"])
    def create_order():
        auth_user, role = auth()
        require_role(role, {"Customer", "FoundryAdmin"})
        body = body_dict(request.get_json(silent=True))
        foundry_id = as_str(req(body, "foundry_id"), "foundry_id")
        customer_id = as_str(req(body, "customer_id"), "customer_id")
        pattern_id = as_str(req(body, "pattern_id"), "pattern_id")
        quantity = as_pos_int(req(body, "quantity"), "quantity")
        overage = as_nonneg_num(opt(body, "overage_pct", 0.10), "overage_pct")
        unit_price = as_nonneg_int(req(body, "unit_price_cents"), "unit_price_cents")
        ma_pct = as_nonneg_num(req(body, "machining_allowance_pct"), "machining_allowance_pct")
        warranty_months = as_nonneg_int(req(body, "warranty_months"), "warranty_months")
        budget = as_nonneg_int(req(body, "warranty_budget_cents"), "warranty_budget_cents")

        # ownership (priority 2): a Customer places only its own orders
        if role == "Customer" and customer_id != auth_user:
            fail("ERR_FORBIDDEN_OWNER", "customer may only place its own orders")

        # existence + same-foundry references (priority 3, PRD 2.11)
        if get("foundries", foundry_id) is None:
            fail("ERR_NOT_FOUND", "foundry not found")
        customer = get("customers", customer_id)
        if customer is None or customer["foundry_id"] != foundry_id:
            fail("ERR_NOT_FOUND", "customer not found")
        pattern = get("patterns", pattern_id)
        if pattern is None or pattern["foundry_id"] != foundry_id:
            fail("ERR_NOT_FOUND", "pattern not found")

        rec = new_record("orders", {
            "foundry_id": foundry_id,
            "customer_id": customer_id,
            "pattern_id": pattern_id,
            "quantity": quantity,
            "overage_pct": overage,
            "unit_price_cents": unit_price,
            "machining_allowance_pct": ma_pct,
            "warranty_months": warranty_months,
            "warranty_budget_cents": budget,
            "accepted_count": 0,
            "scrapped_count": 0,
            "pipeline_count": 0,
            "settled_total_cents": 0,
            "fulfilled_at": None,
            "status": "RECEIVED",
        })
        return ok_object(rec, 201)

    @app.route("/api/orders/<oid>", methods=["GET"])
    def get_order(oid):
        auth_user, role = auth()
        require_role(role, ORDER_ROLES)
        rec = get("orders", oid)
        if rec is None:
            fail("ERR_NOT_FOUND", "order not found")
        if role == "Customer" and rec["customer_id"] != auth_user:
            fail("ERR_FORBIDDEN_OWNER", "customer may only read its own orders")
        return ok_object(rec, 200)

    @app.route("/api/orders", methods=["GET"])
    def list_orders():
        auth_user, role = auth()
        require_role(role, ORDER_ROLES)
        foundry_id = request.args.get("foundry_id")
        customer_id = request.args.get("customer_id")
        pattern_id = request.args.get("pattern_id")
        status = request.args.get("status")
        recs = list(all_of("orders"))
        if role == "Customer":
            recs = [o for o in recs if o["customer_id"] == auth_user]
        if foundry_id is not None:
            recs = [o for o in recs if o["foundry_id"] == foundry_id]
        if customer_id is not None:
            recs = [o for o in recs if o["customer_id"] == customer_id]
        if pattern_id is not None:
            recs = [o for o in recs if o["pattern_id"] == pattern_id]
        if status is not None:
            recs = [o for o in recs if o["status"] == status]
        page, limit, offset, total = paged(recs)
        return ok_list(page, limit, offset, total)

    @app.route("/api/orders/<oid>/cancel", methods=["POST"])
    def cancel_order(oid):
        auth_user, role = auth()
        require_role(role, {"Customer", "FoundryAdmin"})
        rec = get("orders", oid)
        if rec is None:
            fail("ERR_NOT_FOUND", "order not found")
        if role == "Customer" and rec["customer_id"] != auth_user:
            fail("ERR_FORBIDDEN_OWNER", "customer may only cancel its own orders")
        if rec["status"] in ("CLOSED", "CANCELLED"):
            fail("ERR_ALREADY_TERMINAL", "order is in a terminal state")
        if rec["status"] not in ("RECEIVED", "IN_PRODUCTION"):
            fail("ERR_INVALID_STATE", "order cannot be cancelled from %s" % rec["status"])
        for m in all_of("molds"):
            if m["order_id"] == rec["id"] and m["status"] in ("ASSEMBLED", "POURED", "COOLED"):
                fail("ERR_INVALID_STATE", "order has open molds")
        rec["status"] = "CANCELLED"
        touch(rec)
        return ok_object(rec, 200)
