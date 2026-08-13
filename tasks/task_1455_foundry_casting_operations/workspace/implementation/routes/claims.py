"""Warranty claims: filing, review conversation, settlement (PRD 3.9)."""

from flask import request

from db import all_of, get, logical_now, new_record, touch
from errors import fail
from middleware import auth, paged, require_role
from response import ok_list, ok_object
from util import (D, add_months, as_enum, as_nonneg_int, as_pos_int, as_str,
                  body_dict, opt, q0, req)

CLAIM_GET_ROLES = {"FoundryAdmin", "WarrantyManager", "Customer"}
MANAGER_ACTIONS = {"START", "APPROVE", "DENY", "REQUEST_INFO"}
CUSTOMER_ACTIONS = {"RESPOND", "APPEAL"}
ALL_ACTIONS = MANAGER_ACTIONS | CUSTOMER_ACTIONS

# action -> (required current status, next status)
ACTION_TRANSITIONS = {
    "START": ("FILED", "UNDER_REVIEW"),
    "APPROVE": ("UNDER_REVIEW", "APPROVED"),
    "DENY": ("UNDER_REVIEW", "DENIED"),
    "REQUEST_INFO": ("UNDER_REVIEW", "INFO_REQUESTED"),
    "RESPOND": ("INFO_REQUESTED", "UNDER_REVIEW"),
    "APPEAL": ("DENIED", "UNDER_REVIEW"),
}


def register(app):
    @app.route("/api/claims", methods=["POST"])
    def create_claim():
        auth_user, role = auth()
        require_role(role, {"Customer"})
        body = body_dict(request.get_json(silent=True))
        order_id = as_str(req(body, "order_id"), "order_id")
        claim_type = as_enum(req(body, "claim_type"), "claim_type",
                             {"DEFECT", "MACHINING_SHORTFALL"})
        qty = as_pos_int(req(body, "claim_qty"), "claim_qty")
        claimed = as_nonneg_int(req(body, "claimed_amount_cents"), "claimed_amount_cents")
        freight = as_nonneg_int(opt(body, "freight_cents", 0), "freight_cents")

        order = get("orders", order_id)
        if order is None:
            fail("ERR_NOT_FOUND", "order not found")
        # ownership: the filer must own the order
        if order["customer_id"] != auth_user:
            fail("ERR_FORBIDDEN_OWNER", "customer may only claim on its own orders")
        # referential lifecycle: order FULFILLED or CLOSED at filing
        if order["status"] not in ("FULFILLED", "CLOSED"):
            fail("ERR_INVALID_STATE", "order must be FULFILLED or CLOSED at filing")
        # temporal: within warranty_months of fulfilled_at (logical clock)
        if order["fulfilled_at"] is not None:
            window_end = add_months(order["fulfilled_at"], order["warranty_months"])
            if logical_now() > window_end:
                fail("ERR_CLAIM_WINDOW_EXPIRED", "warranty window has expired")

        rec = new_record("claims", {
            "order_id": order_id,
            "customer_id": order["customer_id"],
            "claim_type": claim_type,
            "claim_qty": qty,
            "claimed_amount_cents": claimed,
            "freight_cents": freight,
            "appeal_used": False,
            "reviewed_by_user_id": None,
            "credit_variant_applied": None,
            "settled_credit_cents": None,
            "status": "FILED",
        })
        return ok_object(rec, 201)

    @app.route("/api/claims/<cid>", methods=["GET"])
    def get_claim(cid):
        auth_user, role = auth()
        require_role(role, CLAIM_GET_ROLES)
        rec = get("claims", cid)
        if rec is None:
            fail("ERR_NOT_FOUND", "claim not found")
        if role == "Customer" and rec["customer_id"] != auth_user:
            fail("ERR_FORBIDDEN_OWNER", "customer may only read its own claims")
        return ok_object(rec, 200)

    @app.route("/api/claims", methods=["GET"])
    def list_claims():
        auth_user, role = auth()
        require_role(role, CLAIM_GET_ROLES)
        order_id = request.args.get("order_id")
        customer_id = request.args.get("customer_id")
        status = request.args.get("status")
        recs = list(all_of("claims"))
        if role == "Customer":
            recs = [c for c in recs if c["customer_id"] == auth_user]
        if order_id is not None:
            recs = [c for c in recs if c["order_id"] == order_id]
        if customer_id is not None:
            recs = [c for c in recs if c["customer_id"] == customer_id]
        if status is not None:
            recs = [c for c in recs if c["status"] == status]
        page, limit, offset, total = paged(recs)
        return ok_list(page, limit, offset, total)

    @app.route("/api/claims/<cid>/review", methods=["POST"])
    def review_claim(cid):
        auth_user, role = auth()
        # endpoint role gate, then per-action scoping (both priority 2)
        require_role(role, {"WarrantyManager", "Customer"})
        body = body_dict(request.get_json(silent=True))
        action = as_enum(req(body, "action"), "action", ALL_ACTIONS)
        if role == "WarrantyManager" and action not in MANAGER_ACTIONS:
            fail("ERR_UNAUTHORIZED_ROLE",
                 "action %s is not permitted for WarrantyManager" % action)
        if role == "Customer" and action not in CUSTOMER_ACTIONS:
            fail("ERR_UNAUTHORIZED_ROLE",
                 "action %s is not permitted for Customer" % action)

        rec = get("claims", cid)
        if rec is None:
            fail("ERR_NOT_FOUND", "claim not found")
        if role == "Customer" and rec["customer_id"] != auth_user:
            fail("ERR_FORBIDDEN_OWNER", "customer may only act on its own claims")
        if rec["status"] == "SETTLED":
            fail("ERR_ALREADY_TERMINAL", "claim is SETTLED")
        want_from, next_state = ACTION_TRANSITIONS[action]
        if rec["status"] != want_from:
            fail("ERR_INVALID_STATE",
                 "action %s is not available from %s" % (action, rec["status"]))
        if action == "APPEAL":
            if rec["appeal_used"]:
                fail("ERR_APPEAL_ALREADY_USED", "the single appeal has been consumed")
            rec["appeal_used"] = True
        if action in ("APPROVE", "DENY"):
            rec["reviewed_by_user_id"] = auth_user
        rec["status"] = next_state
        touch(rec)
        return ok_object(rec, 200)

    @app.route("/api/claims/<cid>/settle", methods=["POST"])
    def settle_claim(cid):
        auth_user, role = auth()
        require_role(role, {"WarrantyManager"})
        rec = get("claims", cid)
        if rec is None:
            fail("ERR_NOT_FOUND", "claim not found")
        if rec["status"] == "SETTLED":
            fail("ERR_ALREADY_TERMINAL", "claim is SETTLED")
        if rec["status"] != "APPROVED":
            fail("ERR_INVALID_STATE", "only an APPROVED claim can be settled")
        # segregation of duties: approver may not settle (priority 5)
        if rec["reviewed_by_user_id"] is not None and rec["reviewed_by_user_id"] == auth_user:
            fail("ERR_SEGREGATION_OF_DUTIES",
                 "the approving manager may not settle the claim")
        order = get("orders", rec["order_id"])
        if order is None:
            fail("ERR_NOT_FOUND", "order not found")
        if order["status"] not in ("FULFILLED", "CLOSED"):
            fail("ERR_INVALID_STATE", "order must be FULFILLED or CLOSED at settle")

        # warranty_credit variants, integer cents, rounded before the budget check
        if rec["claim_type"] == "DEFECT":
            variant = "STANDARD"
            credit = min(rec["claimed_amount_cents"],
                         order["unit_price_cents"] * rec["claim_qty"])
        else:
            variant = "MACHINING_ALLOWANCE"
            allowance = q0(D(order["unit_price_cents"])
                           * D(order["machining_allowance_pct"])
                           * D(rec["claim_qty"]))
            credit = min(rec["claimed_amount_cents"],
                         int(allowance) + rec["freight_cents"])
        # budget: credit must fit the order's remaining warranty budget
        if credit > order["warranty_budget_cents"] - order["settled_total_cents"]:
            fail("ERR_WARRANTY_BUDGET_EXCEEDED",
                 "settlement credit exceeds the remaining warranty budget")

        rec["settled_credit_cents"] = credit
        rec["credit_variant_applied"] = variant
        rec["status"] = "SETTLED"
        touch(rec)
        order["settled_total_cents"] += credit
        touch(order)
        return ok_object(rec, 200)
