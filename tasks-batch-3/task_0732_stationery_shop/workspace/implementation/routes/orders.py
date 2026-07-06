"""Order endpoints."""

from flask import Blueprint, request

import db
import errors
import middleware
import models
import response as resp
import services
import util

bp = Blueprint("orders", __name__)


TERMINAL_STATES = {"DELIVERED", "CANCELLED"}


# ----- POST /orders --------------------------------------------------------

@bp.route("/orders", methods=["POST"])
def create_order():
    user_id, role = middleware.get_auth()
    middleware.require_roles(role, ["Customer"])
    body = util.get_body()
    customer_id = util.get_str(body, "customer_id")
    design_id = util.get_str(body, "design_id")
    prior_order_id = body.get("prior_order_id")
    if prior_order_id is not None and not isinstance(prior_order_id, str):
        errors.raise_error(errors.ERR_INVALID_REQUEST, "prior_order_id must be a string")
    rush_deadline_raw = body.get("rush_deadline")
    rush_deadline_dt = None
    if rush_deadline_raw is not None:
        if not isinstance(rush_deadline_raw, str):
            errors.raise_error(errors.ERR_INVALID_REQUEST, "rush_deadline must be an ISO 8601 string")
        try:
            rush_deadline_dt = db.parse_iso(rush_deadline_raw)
        except Exception:
            errors.raise_error(errors.ERR_INVALID_REQUEST, "rush_deadline invalid")

    # AuthZ
    middleware.require_owner(user_id, customer_id)
    # Existence
    models.get_customer(customer_id)
    d = models.get_design(design_id)
    # Design must belong to acting customer for this operation
    if d["customer_id"] != customer_id:
        errors.raise_error(errors.ERR_UNAUTHORIZED, "design does not belong to customer")

    # Reorder eligibility check
    if prior_order_id:
        prior = db.orders.get(prior_order_id)
        if not prior:
            errors.raise_error(errors.ERR_ORDER_NOT_FOUND, "prior order not found")
        if prior["customer_id"] != customer_id:
            errors.raise_error(
                errors.ERR_REORDER_WINDOW_EXPIRED,
                "prior order belongs to a different customer",
            )
        if prior["status"] != "DELIVERED":
            errors.raise_error(
                errors.ERR_REORDER_WINDOW_EXPIRED,
                "prior order is not in DELIVERED status",
            )
        # We'll check the calendar-day diff after order created_at is set
        try:
            prev = db.parse_iso(prior["created_at"])
            now = db.get_now()
            days = (now.date() - prev.date()).days
            if days > services.REORDER_WINDOW_DAYS:
                errors.raise_error(
                    errors.ERR_REORDER_WINDOW_EXPIRED,
                    "prior order is outside the reorder window",
                )
        except errors.ApiError:
            raise
        except Exception:
            errors.raise_error(errors.ERR_REORDER_WINDOW_EXPIRED, "reorder date check failed")

    o = models.make_common({
        "customer_id": customer_id,
        "design_id": design_id,
        "proof_id": None,
        "event_package_id": d["event_package_id"],
        "prior_order_id": prior_order_id,
        "rush_requested": False,
        "rush_deadline": db.format_iso(rush_deadline_dt) if rush_deadline_dt else None,
        "subtotal_cents": 0,
        "reorder_discount_cents": 0,
        "rush_surcharge_cents": 0,
        "total_cents": 0,
        "deposit_due_cents": 0,
        "deposit_paid_cents": 0,
        "deposit_paid_at": None,
        "balance_due_cents": 0,
        "expected_lead_days": 0,
        "status": "CART",
    })
    db.orders[o["id"]] = o
    return resp.created(o)


# ----- POST /orders/{id}/line-items ---------------------------------------

@bp.route("/orders/<oid>/line-items", methods=["POST"])
def add_line_item(oid):
    user_id, role = middleware.get_auth()
    middleware.require_roles(role, ["Customer"])
    o = models.get_order(oid)
    middleware.require_owner(user_id, o["customer_id"])
    body = util.get_body()
    paper_stock_id = util.get_str(body, "paper_stock_id")
    finish_option_id = util.get_str(body, "finish_option_id")
    # quantity: must be integer > 0
    if "quantity" not in body or body["quantity"] is None:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "missing required field: quantity")
    qraw = body["quantity"]
    if isinstance(qraw, bool) or not isinstance(qraw, int):
        errors.raise_error(errors.ERR_QUANTITY_INVALID, "quantity must be an integer")
    quantity = qraw
    expected_order_version = util.get_int(body, "expected_order_version")

    # Existence
    ps = models.get_paper_stock(paper_stock_id)
    fo = models.get_finish_option(finish_option_id)

    # OCC check (state band)
    if expected_order_version != o.get("version"):
        errors.raise_error(errors.ERR_STALE_VERSION, "expected_order_version does not match")
    # State: order must be CART
    if o["status"] in TERMINAL_STATES:
        errors.raise_error(errors.ERR_ALREADY_TERMINAL, "order is terminal")
    if o["status"] != "CART":
        errors.raise_error(errors.ERR_INVALID_STATE, "order is not in CART")

    # Reorder exception for catalog integrity
    reorder_ok_for_paper = False
    reorder_ok_for_finish = False
    prior_matching_line = None
    if o.get("prior_order_id"):
        prior = db.orders.get(o["prior_order_id"])
        if prior:
            # Only within window
            try:
                prev = db.parse_iso(prior["created_at"])
                cur = db.parse_iso(o["created_at"])
                within = (cur.date() - prev.date()).days <= services.REORDER_WINDOW_DAYS
            except Exception:
                within = False
            if within:
                for pli in models.order_line_items(prior["id"]):
                    if pli["paper_stock_id"] == paper_stock_id and pli["finish_option_id"] == finish_option_id:
                        prior_matching_line = pli
                        reorder_ok_for_paper = True
                        reorder_ok_for_finish = True
                        break

    # Business safety: paper/finish must be ACTIVE unless reorder exception
    if ps["status"] != "ACTIVE" and not reorder_ok_for_paper:
        errors.raise_error(errors.ERR_PAPER_DISCONTINUED, "paper stock is discontinued")
    if fo["status"] != "ACTIVE" and not reorder_ok_for_finish:
        errors.raise_error(errors.ERR_FINISH_DISCONTINUED, "finish option is discontinued")

    # Business constraint: quantity valid + at least min_qty
    if quantity <= 0:
        errors.raise_error(errors.ERR_QUANTITY_INVALID, "quantity must be positive")
    pkg = db.event_packages.get(o["event_package_id"])
    if quantity < int(pkg["min_qty"]):
        errors.raise_error(errors.ERR_QUANTITY_BELOW_MIN, "quantity below package minimum")

    # Capture prices — reorder-locked if matching prior line exists
    if prior_matching_line:
        captured_base = int(prior_matching_line["captured_base_price_cents"])
        captured_finish = int(prior_matching_line["captured_finish_surcharge_cents"])
    else:
        captured_base = int(ps["base_price_cents"])
        captured_finish = int(fo["surcharge_cents"])

    line_price = services.compute_line_item_price(quantity, captured_base, captured_finish)

    li = models.make_common({
        "order_id": o["id"],
        "paper_stock_id": paper_stock_id,
        "finish_option_id": finish_option_id,
        "quantity": quantity,
        "captured_base_price_cents": captured_base,
        "captured_finish_surcharge_cents": captured_finish,
        "line_price_cents": line_price,
    })
    db.line_items[li["id"]] = li

    services.recompute_order_subtotal(o)
    services.recompute_order_total(o)
    services.recompute_expected_lead_days(o)
    models.bump(o)
    return resp.created(li)


# ----- DELETE /orders/{id}/line-items/{lid} -------------------------------

@bp.route("/orders/<oid>/line-items/<lid>", methods=["DELETE"])
def delete_line_item(oid, lid):
    user_id, role = middleware.get_auth()
    middleware.require_roles(role, ["Customer"])
    o = models.get_order(oid)
    middleware.require_owner(user_id, o["customer_id"])
    li = db.line_items.get(lid)
    if not li or li["order_id"] != oid:
        errors.raise_error(errors.ERR_LINE_ITEM_NOT_FOUND, "line item not on this order")
    if o["status"] in TERMINAL_STATES:
        errors.raise_error(errors.ERR_ALREADY_TERMINAL, "order is terminal")
    if o["status"] != "CART":
        errors.raise_error(errors.ERR_INVALID_STATE, "order is not in CART")

    del db.line_items[lid]
    services.recompute_order_subtotal(o)
    services.recompute_order_total(o)
    services.recompute_expected_lead_days(o)
    models.bump(o)
    return resp.no_content()


# ----- POST /orders/{id}/apply-rush ---------------------------------------

@bp.route("/orders/<oid>/apply-rush", methods=["POST"])
def apply_rush_endpoint(oid):
    user_id, role = middleware.get_auth()
    middleware.require_roles(role, ["Customer", "ShopAdmin"])
    o = models.get_order(oid)
    if role == "Customer":
        middleware.require_owner(user_id, o["customer_id"])
    body = util.get_body()
    rush_deadline_dt = util.get_iso_datetime(body, "rush_deadline")

    # State
    if o["status"] in TERMINAL_STATES:
        errors.raise_error(errors.ERR_ALREADY_TERMINAL, "order is terminal")
    # Rush must be before proof approval
    proof = models.order_active_proof(o["id"])
    if proof and proof["status"] == "APPROVED":
        errors.raise_error(errors.ERR_RUSH_TOO_LATE, "proof already approved")
    # Rush infeasibility check comes next (business fiscal)
    services.apply_rush(o, rush_deadline_dt)

    services.recompute_order_total(o)
    services.recompute_expected_lead_days(o)
    # If proof exists in DRAFT/SUBMITTED/CHANGES_REQUESTED, recompute expires_at using rush variant
    if proof and proof["status"] in ("DRAFT", "SUBMITTED", "CHANGES_REQUESTED"):
        # per PRD: recompute expires_at using rush variant (only meaningful when a submitted proof exists)
        # Standard reading: compute from current UTC (i.e., "now").
        proof["expires_at"] = services.compute_proof_expires_at(proof, o)
        models.bump(proof)
    models.bump(o)
    return resp.ok(o)


# ----- POST /orders/{id}/confirm ------------------------------------------

@bp.route("/orders/<oid>/confirm", methods=["POST"])
def confirm_order(oid):
    user_id, role = middleware.get_auth()
    middleware.require_roles(role, ["Customer"])
    o = models.get_order(oid)
    middleware.require_owner(user_id, o["customer_id"])

    # State: order must be CART
    if o["status"] in TERMINAL_STATES:
        errors.raise_error(errors.ERR_ALREADY_TERMINAL, "order is terminal")
    if o["status"] != "CART":
        errors.raise_error(errors.ERR_INVALID_STATE, "order is not in CART")

    lines = models.order_line_items(o["id"])
    if not lines:
        errors.raise_error(errors.ERR_INVALID_STATE, "order has no line items")

    # Recheck catalog integrity and quantity
    pkg = db.event_packages.get(o["event_package_id"])
    reorder = o.get("prior_order_id")
    prior_lines_by_key = {}
    if reorder:
        prior = db.orders.get(reorder)
        if prior:
            for pli in models.order_line_items(prior["id"]):
                prior_lines_by_key.setdefault((pli["paper_stock_id"], pli["finish_option_id"]), pli)

    for li in lines:
        ps = db.paper_stocks.get(li["paper_stock_id"])
        fo = db.finish_options.get(li["finish_option_id"])
        matching_prior = prior_lines_by_key.get((li["paper_stock_id"], li["finish_option_id"]))
        # Business safety
        if ps and ps["status"] != "ACTIVE" and not matching_prior:
            errors.raise_error(errors.ERR_PAPER_DISCONTINUED, "paper stock is discontinued")
        if fo and fo["status"] != "ACTIVE" and not matching_prior:
            errors.raise_error(errors.ERR_FINISH_DISCONTINUED, "finish option is discontinued")
        # Quantity min
        if int(li["quantity"]) < int(pkg["min_qty"]):
            errors.raise_error(errors.ERR_QUANTITY_BELOW_MIN, "line quantity below min_qty")

    # Advance
    o["status"] = "DEPOSIT_PENDING"
    services.recompute_order_subtotal(o)
    services.recompute_reorder_discount(o)
    o["deposit_due_cents"] = services.compute_deposit_due(o)
    services.recompute_expected_lead_days(o)
    services.recompute_order_total(o)

    # Create Proof DRAFT (no designer)
    proof = models.make_common({
        "design_id": o["design_id"],
        "designer_id": None,
        "current_revision_number": 0,
        "revision_fee_cents": 0,
        "submitted_at": None,
        "expires_at": None,
        "approved_at": None,
        "status": "DRAFT",
    })
    db.proofs[proof["id"]] = proof
    o["proof_id"] = proof["id"]
    models.bump(o)

    # Update Design.status -> PROOFING
    d = db.designs.get(o["design_id"])
    if d:
        d["status"] = "PROOFING"
        models.bump(d)

    # Reserve paper
    services.add_reservations(o)

    return resp.ok(o)


# ----- POST /orders/{id}/pay-deposit --------------------------------------

@bp.route("/orders/<oid>/pay-deposit", methods=["POST"])
def pay_deposit(oid):
    user_id, role = middleware.get_auth()
    middleware.require_roles(role, ["Customer"])
    o = models.get_order(oid)
    middleware.require_owner(user_id, o["customer_id"])
    body = util.get_body()
    amount = util.get_int(body, "amount_cents")

    # State: must be DEPOSIT_PENDING
    if o["status"] in TERMINAL_STATES:
        errors.raise_error(errors.ERR_ALREADY_TERMINAL, "order is terminal")
    if o["status"] != "DEPOSIT_PENDING":
        errors.raise_error(errors.ERR_INVALID_STATE, "order is not in DEPOSIT_PENDING")

    # Fiscal: amount must equal deposit_due_cents
    if amount != int(o["deposit_due_cents"]):
        errors.raise_error(errors.ERR_DEPOSIT_NOT_PAID, "amount must equal deposit_due_cents")

    # Cannot double-pay
    if o.get("deposit_paid_at") is not None:
        errors.raise_error(errors.ERR_INVALID_STATE, "deposit already fully paid")

    o["deposit_paid_cents"] = int(o["deposit_paid_cents"]) + amount
    if o["deposit_paid_cents"] == int(o["deposit_due_cents"]):
        o["deposit_paid_at"] = db.iso_now()
        c = db.customers.get(o["customer_id"])
        if c:
            c["cumulative_deposits_paid_cents"] = int(c.get("cumulative_deposits_paid_cents", 0)) + amount
            models.bump(c)
    services.recompute_order_total(o)
    models.bump(o)
    # Cascade
    services.try_cascade_deposit_and_approval(o)
    return resp.ok(o)


# ----- POST /orders/{id}/cancel -------------------------------------------

@bp.route("/orders/<oid>/cancel", methods=["POST"])
def cancel_order(oid):
    user_id, role = middleware.get_auth()
    middleware.require_roles(role, ["Customer", "ShopAdmin"])
    o = models.get_order(oid)
    if role == "Customer":
        middleware.require_owner(user_id, o["customer_id"])

    if o["status"] in TERMINAL_STATES or o["status"] == "SHIPPED":
        if o["status"] in TERMINAL_STATES:
            errors.raise_error(errors.ERR_ALREADY_TERMINAL, "order is terminal")
        errors.raise_error(errors.ERR_INVALID_STATE, "order cannot be cancelled from SHIPPED")

    if o["status"] == "READY_TO_SHIP":
        # Not covered by state machine in scaffold; treat as not cancellable via this endpoint.
        errors.raise_error(errors.ERR_INVALID_STATE, "order cannot be cancelled from READY_TO_SHIP")

    if o["status"] == "IN_PRODUCTION":
        if role != "ShopAdmin":
            errors.raise_error(errors.ERR_ORDER_NOT_CANCELLABLE, "Customer cannot cancel IN_PRODUCTION order")

    prev_status = o["status"]

    # Cascade proof (if any, not terminal)
    proof = models.order_active_proof(o["id"])
    if proof and proof["status"] not in ("APPROVED", "EXPIRED", "CANCELLED"):
        proof["status"] = "CANCELLED"
        models.bump(proof)

    # Cascade WorkOrder if exists
    for wo in models.order_work_orders(o["id"]):
        # We simply mark by leaving as-is; but for consistency treat production_status/addressing_status as final via cancellation
        # PRD: 'WorkOrder cancelled' — we bump version and record it via a synthetic 'cancelled' by setting statuses to their current values.
        # For now, we don't have a CANCELLED enum on WorkOrder; leave state but bump version to indicate the cascade.
        models.bump(wo)

    # Cascade shipment (PREPARING -> CANCELLED)
    for s in models.order_shipments(o["id"]):
        if s["status"] == "PREPARING":
            s["status"] = "CANCELLED"
            models.bump(s)

    # Cascade addressing jobs
    for a in models.order_addressing_jobs(o["id"]):
        if a["status"] not in ("COMPLETED", "CANCELLED"):
            a["status"] = "CANCELLED"
            models.bump(a)

    # Refund handling
    if prev_status == "DEPOSIT_PENDING" and int(o.get("deposit_paid_cents", 0)) > 0:
        c = db.customers.get(o["customer_id"])
        if c:
            c["credit_balance_cents"] = int(c.get("credit_balance_cents", 0)) + int(o["deposit_paid_cents"])
            models.bump(c)
        o["deposit_paid_cents"] = 0

    # Release reservations (in DEPOSIT_PENDING or IN_PRODUCTION)
    if prev_status in ("DEPOSIT_PENDING", "IN_PRODUCTION"):
        services.remove_reservations(o)

    # If IN_PRODUCTION: also archive design (forfeit path)
    if prev_status == "IN_PRODUCTION":
        d = db.designs.get(o["design_id"])
        if d:
            d["status"] = "ARCHIVED"
            models.bump(d)

    o["status"] = "CANCELLED"
    services.recompute_order_total(o)
    models.bump(o)
    return resp.ok(o)


# ----- GET /orders/{id} ---------------------------------------------------

@bp.route("/orders/<oid>", methods=["GET"])
def get_order(oid):
    user_id, role = middleware.get_auth()
    middleware.require_roles(role, ["ShopAdmin", "Customer"])
    o = models.get_order(oid)
    if role == "Customer":
        middleware.require_owner(user_id, o["customer_id"])
    # Update balance_due read-only field
    services.recompute_order_total(o)
    return resp.ok(o)


@bp.route("/orders", methods=["GET"])
def list_orders():
    user_id, role = middleware.get_auth()
    middleware.require_roles(role, ["ShopAdmin", "Customer"])
    limit, offset = util.get_pagination()

    def match(o):
        cid = request.args.get("customer_id")
        did = request.args.get("design_id")
        pid = request.args.get("proof_id")
        eid = request.args.get("event_package_id")
        pri = request.args.get("prior_order_id")
        st = request.args.get("status")
        if cid and o.get("customer_id") != cid:
            return False
        if did and o.get("design_id") != did:
            return False
        if pid and o.get("proof_id") != pid:
            return False
        if eid and o.get("event_package_id") != eid:
            return False
        if pri and o.get("prior_order_id") != pri:
            return False
        if st and o.get("status") != st:
            return False
        return True

    items = [o for o in db.orders.values() if match(o)]
    if role == "Customer":
        items = [o for o in items if o["customer_id"] == user_id]
    items = util.sort_by_created_at(items)
    page, total = util.apply_pagination(items, limit, offset)
    return resp.list_ok(page, limit, offset, total)
