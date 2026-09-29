"""Part orders, order lines and their two independent lifecycles."""

from db import db, base_row, fmt, now, touch
from errors import ApiError
from flask import Blueprint
from middleware import (authenticate, check_account_scope, check_branch_open,
                        check_branch_scope, require_acting_branch)
from response import created, ok, ok_list
from services import calc, flows, serialize
from validation import parse_body, pagination, q_str

bp = Blueprint("orders", __name__)

ALL_ROLES = ("PlatformAdmin", "CreditManager", "BranchCounterRep", "PricingAdmin",
             "WarrantyAdmin", "Servicer")
ORDER_WRITERS = ("Servicer", "BranchCounterRep", "PlatformAdmin")
CREDIT_WRITERS = ("CreditManager", "PlatformAdmin")
BRANCH_WRITERS = ("BranchCounterRep", "PlatformAdmin")

FULFILLMENT_MODES = {"WILL_CALL", "OVERNIGHT_DROP_SHIP"}
DECISIONS = {"APPROVE", "DECLINE"}


def _account_of(order):
    return db.servicer_accounts.get(order["servicer_account_id"])


def _require_active_account(account):
    """Rule 8."""
    if account is None or account["account_status"] != "ACTIVE":
        raise ApiError("ERR_SERVICER_NOT_ACTIVE",
                       "The servicer account is not ACTIVE")


def _require_draft(order):
    """Rule 10: DRAFT on the physical dimension AND PENDING_CREDIT on the money one."""
    if order["fulfillment_status"] != "DRAFT" \
            or order["settlement_status"] != "PENDING_CREDIT":
        raise ApiError("ERR_ORDER_NOT_DRAFT",
                       "The order is not an undecided DRAFT")


# --------------------------------------------------------------------------
# order intake
# --------------------------------------------------------------------------

@bp.post("/part-orders")
def create_order():
    user_id, role = authenticate(ORDER_WRITERS)
    body = parse_body([
        ("servicer_account_id", "str", True),
        ("fulfillment_mode", "enum", True, FULFILLMENT_MODES),
        ("pickup_branch_id", "str", False),
        ("ship_to_zip", "str", False),
        ("purchase_order_ref", "str", False),
    ])
    pickup_branch = None
    if "pickup_branch_id" in body:
        pickup_branch = flows.branch_or_404(body["pickup_branch_id"])
    account = flows.account_or_404(body["servicer_account_id"])
    check_account_scope(user_id, role, account["id"])
    _require_active_account(account)

    mode = body["fulfillment_mode"]
    has_pickup = "pickup_branch_id" in body
    has_zip = "ship_to_zip" in body
    if mode == "WILL_CALL":
        if not has_pickup or has_zip:
            raise ApiError("ERR_FULFILLMENT_MODE_MISMATCH",
                           "A WILL_CALL order carries pickup_branch_id and no "
                           "ship_to_zip")
    else:
        if not has_zip or has_pickup:
            raise ApiError("ERR_FULFILLMENT_MODE_MISMATCH",
                           "An OVERNIGHT_DROP_SHIP order carries ship_to_zip and "
                           "no pickup_branch_id")
    if pickup_branch is not None and not pickup_branch["will_call_enabled"]:
        raise ApiError("ERR_WILL_CALL_NOT_ENABLED",
                       "Branch %s does not accept will-call" % pickup_branch["id"])

    row = base_row()
    row.update({
        "servicer_account_id": account["id"],
        "fulfillment_mode": mode,
        "pickup_branch_id": body.get("pickup_branch_id"),
        "ship_to_zip": body.get("ship_to_zip"),
        "purchase_order_ref": body.get("purchase_order_ref"),
        "fulfillment_status": "DRAFT",
        "hold_reason": None,
        "settlement_status": "PENDING_CREDIT",
        "pricing_basis": "ORDER_DATE",
        "credit_decided_by_user_id": None,
        "subtotal_cents": 0,
        "core_deposit_total_cents": 0,
        "freight_cents": 0,
        "total_cents": 0,
        "invoiced_total_cents": None,
        "fulfilled_at": None,
        "tracking_ref": None,
    })
    db.part_orders[row["id"]] = row
    return created(serialize.part_order(row))


@bp.post("/part-orders/<order_id>/lines")
def add_order_line(order_id):
    user_id, role = authenticate(ORDER_WRITERS)
    body = parse_body([
        ("requested_part_id", "str", True),
        ("quantity", "qty", True),
        ("expected_part_order_version", "signed", True),
    ])
    order = flows.order_or_404(order_id)
    requested_part = flows.part_or_404(body["requested_part_id"])
    check_account_scope(user_id, role, order["servicer_account_id"])
    account = _account_of(order)
    _require_active_account(account)
    _require_draft(order)
    if order["version"] != body["expected_part_order_version"]:
        raise ApiError("ERR_STALE_ORDER_VERSION",
                       "Order version is %d, not %d"
                       % (order["version"], body["expected_part_order_version"]))

    resolved, hops, substitute_required = flows.resolve_chain(requested_part)
    flows.check_oem_authorization(account, resolved)
    flows.check_technician_cert(account, resolved)

    tier = db.pricing_tiers.get(account["pricing_tier_id"])
    if tier is None:
        raise ApiError("ERR_PRICING_TIER_NOT_FOUND",
                       "The account's pricing tier no longer exists")
    quantity = body["quantity"]
    unit_price = calc.unit_price_cents(resolved, tier, quantity)
    extended = unit_price * quantity

    # credit exposure recomputed WITH this line folded into the order's own total
    contribution = 0 if substitute_required else extended
    projected_subtotal = flows.compute_subtotal(order) + contribution
    projected_total = (projected_subtotal
                       + flows.compute_core_total(order)
                       + order["freight_cents"])
    flows.check_credit_limit(
        account, flows.projected_credit_used(account, order, projected_total))

    line = base_row()
    line.update({
        "part_order_id": order["id"],
        "requested_part_id": requested_part["id"],
        "resolved_part_id": resolved["id"],
        "quantity": quantity,
        "supersession_hops": hops,
        "unit_price_cents": unit_price,
        "extended_price_cents": extended,
        "invoiced_unit_price_cents": None,
        "core_deposit_cents": 0,
        "returned_units": 0,
        "line_status": "SUBSTITUTE_PENDING" if substitute_required else "RESOLVED",
        "allocation_branch_id": None,
    })
    db.order_lines[line["id"]] = line

    if substitute_required:
        request = base_row()
        request.update({
            "order_line_id": line["id"],
            "obsolete_part_id": resolved["id"],
            "proposed_substitute_part_id": None,
            "request_status": "PENDING",
            "price_variance_pct": None,
            "source": "CHAIN_TERMINAL_OBSOLETE",
            "created_by_price_file_id": None,
            "decided_by_user_id": None,
        })
        db.substitute_requests[request["id"]] = request

    flows.recompute_totals(order, reassess_freight=False)
    touch(order)
    flows.sync_account(account)
    return created(serialize.order_line(line))


@bp.post("/order-lines/<line_id>/cancel")
def cancel_order_line(line_id):
    user_id, role = authenticate(ORDER_WRITERS)
    parse_body([("cancellation_reason", "str", True)])
    line = flows.line_or_404(line_id)
    order = db.part_orders.get(line["part_order_id"])
    check_account_scope(user_id, role, order["servicer_account_id"])
    if line["line_status"] not in ("RESOLVED", "ALLOCATED", "BACKORDERED") \
            or order["fulfillment_status"] not in ("DRAFT", "ALLOCATED", "HELD"):
        raise ApiError("ERR_LINE_STATE_INVALID",
                       "This line can no longer be cancelled")
    flows.release_reservation(line)
    for request in flows.pending_substitutes_for_line(line):
        request["request_status"] = "WITHDRAWN"
        touch(request)
    line["line_status"] = "CANCELLED"
    touch(line)
    flows.recompute_totals(order)
    touch(order)
    account = _account_of(order)
    if account is not None:
        flows.sync_account(account)
    return ok(serialize.order_line(line))


# --------------------------------------------------------------------------
# credit decisioning and payment
# --------------------------------------------------------------------------

@bp.post("/part-orders/<order_id>/credit-decision")
def credit_decision(order_id):
    user_id, role = authenticate(CREDIT_WRITERS)
    body = parse_body([
        ("decision", "enum", True, DECISIONS),
        ("decision_note", "str", False),
    ])
    order = flows.order_or_404(order_id)
    _require_draft(order)
    account = _account_of(order)
    if body["decision"] == "APPROVE":
        _require_active_account(account)
        flows.check_credit_limit(account, flows.credit_used_cents(account["id"]))

    order["credit_decided_by_user_id"] = user_id
    if body["decision"] == "APPROVE":
        order["settlement_status"] = "CREDIT_APPROVED"
    else:
        order["settlement_status"] = "CREDIT_DECLINED"
    touch(order)

    account["delinquency_score"] = flows.delinquency_score(account, "rolling")
    touch(account)
    flows.sync_account(account)
    if body["decision"] == "DECLINE" \
            and account["delinquency_score"] < calc.DELINQUENCY_HOLD_THRESHOLD:
        flows.apply_credit_hold(account)
    return ok(serialize.part_order(order))


@bp.post("/part-orders/<order_id>/payments")
def post_payment(order_id):
    authenticate(CREDIT_WRITERS)
    body = parse_body([
        ("amount_cents", "money", True),
        ("payment_reference", "str", False),
    ])
    order = flows.order_or_404(order_id)
    if order["settlement_status"] not in ("CREDIT_APPROVED", "INVOICED"):
        raise ApiError("ERR_SETTLEMENT_STATE_INVALID",
                       "A payment requires settlement_status CREDIT_APPROVED or "
                       "INVOICED")
    if order["settlement_status"] == "CREDIT_APPROVED":
        expected = order["total_cents"]
    else:
        expected = order["invoiced_total_cents"] or 0
    if body["amount_cents"] != expected:
        raise ApiError("ERR_PAYMENT_AMOUNT_MISMATCH",
                       "Payment must be exactly %d cents" % expected)
    order["settlement_status"] = "PAID"
    touch(order)
    account = _account_of(order)
    if account is not None:
        flows.sync_account(account)
        flows.maybe_release_credit_hold(account)
    return ok(serialize.part_order(order))


# --------------------------------------------------------------------------
# allocation and hand-over
# --------------------------------------------------------------------------

@bp.post("/part-orders/<order_id>/allocate")
def allocate_order(order_id):
    user_id, role = authenticate(BRANCH_WRITERS)
    parse_body([])
    order = flows.order_or_404(order_id)

    # rule 7 then rule 9, both before any target-state rule
    pickup_branch = None
    if order["fulfillment_mode"] == "WILL_CALL":
        check_branch_scope(user_id, role, order.get("pickup_branch_id"))
        pickup_branch = db.branches.get(order.get("pickup_branch_id"))
        acting_branch = pickup_branch
    else:
        acting_branch = require_acting_branch(user_id, role)

    account = _account_of(order)
    _require_active_account(account)
    check_branch_open(acting_branch)
    if order["fulfillment_status"] != "DRAFT" \
            or order["settlement_status"] not in ("CREDIT_APPROVED", "PAID"):
        raise ApiError("ERR_ORDER_STATE_INVALID",
                       "Allocation requires a DRAFT order that is credit-cleared")
    live_lines = [l for l in flows.order_lines_of(order)
                  if l["line_status"] != "CANCELLED"]
    if not live_lines:
        raise ApiError("ERR_ORDER_HAS_NO_LINES",
                       "The order has no lines left to allocate")
    if order["fulfillment_mode"] == "WILL_CALL" \
            and pickup_branch is not None \
            and not pickup_branch["will_call_enabled"]:
        raise ApiError("ERR_WILL_CALL_NOT_ENABLED",
                       "Branch %s does not accept will-call" % pickup_branch["id"])

    allocated = flows.allocation_sweep(order, ("RESOLVED",))
    if allocated > 0:
        order["fulfillment_status"] = "ALLOCATED"
        order["hold_reason"] = None
    else:
        order["fulfillment_status"] = "HELD"
        order["hold_reason"] = "BACKORDER"
    flows.recompute_totals(order)
    touch(order)
    if account is not None:
        flows.sync_account(account)
    return ok(serialize.part_order(order))


@bp.post("/part-orders/<order_id>/fulfill")
def fulfill_order(order_id):
    user_id, role = authenticate(BRANCH_WRITERS)
    body = parse_body([("tracking_ref", "str", False)])
    order = flows.order_or_404(order_id)

    # rule 7: the acting branch must match the order's shape
    acting_branch = None
    if order["fulfillment_mode"] == "WILL_CALL":
        check_branch_scope(user_id, role, order.get("pickup_branch_id"))
        acting_branch = db.branches.get(order.get("pickup_branch_id"))
    else:
        if role == "BranchCounterRep":
            allocated_branches = set(
                l.get("allocation_branch_id") for l in flows.order_lines_of(order)
                if l["line_status"] == "ALLOCATED")
            if user_id not in allocated_branches:
                raise ApiError("ERR_BRANCH_SCOPE_VIOLATION",
                               "Only a branch holding an allocated line may ship "
                               "this order")
            acting_branch = db.branches.get(user_id)

    account = _account_of(order)
    _require_active_account(account)
    check_branch_open(acting_branch)
    if order["fulfillment_status"] != "ALLOCATED":
        raise ApiError("ERR_ORDER_STATE_INVALID",
                       "Hand-over requires an ALLOCATED order")
    if account["credit_terms"] == "PREPAY":
        if order["settlement_status"] != "PAID":
            raise ApiError("ERR_PREPAY_REQUIRED",
                           "A PREPAY account must pay before hand-over")
    elif order["settlement_status"] not in ("CREDIT_APPROVED", "PAID"):
        raise ApiError("ERR_ORDER_STATE_INVALID",
                       "Hand-over requires an approved settlement")

    allocated_lines = [l for l in flows.order_lines_of(order)
                       if l["line_status"] == "ALLOCATED"]
    core_addition = 0
    for line in allocated_lines:
        part = db.parts.get(line["resolved_part_id"])
        if part is not None and part["core_required"]:
            core_addition += part["core_deposit_cents"] * line["quantity"]
    if account["core_liability_cents"] + core_addition \
            > account["core_liability_limit_cents"]:
        raise ApiError("ERR_CORE_LIABILITY_LIMIT_EXCEEDED",
                       "Hand-over would exceed the account's core liability limit")

    tier = db.pricing_tiers.get(account["pricing_tier_id"])
    order["pricing_basis"] = "SHIP_DATE"
    for line in allocated_lines:
        part = db.parts.get(line["resolved_part_id"])
        if part is not None and tier is not None:
            line["invoiced_unit_price_cents"] = calc.unit_price_cents(
                part, tier, line["quantity"])
        if part is not None and part["core_required"]:
            line["core_deposit_cents"] = part["core_deposit_cents"]
        else:
            line["core_deposit_cents"] = 0
        record = flows.inventory_for(line["allocation_branch_id"],
                                    line["resolved_part_id"])
        if record is not None:
            record["on_hand_units"] = record["on_hand_units"] - line["quantity"]
            record["reserved_units"] = max(0, record["reserved_units"]
                                           - line["quantity"])
            touch(record)
        line["line_status"] = "SHIPPED"
        touch(line)

    flows.recompute_totals(order)
    order["invoiced_total_cents"] = (flows.ship_date_subtotal(order)
                                     + order["core_deposit_total_cents"]
                                     + order["freight_cents"])
    order["fulfilled_at"] = fmt(now())
    order["tracking_ref"] = body.get("tracking_ref")
    order["fulfillment_status"] = "FULFILLED"
    if account["credit_terms"] != "PREPAY" \
            and order["settlement_status"] == "CREDIT_APPROVED":
        order["settlement_status"] = "INVOICED"
    touch(order)
    flows.sync_account(account)
    return ok(serialize.part_order(order))


@bp.post("/part-orders/<order_id>/cancel")
def cancel_order(order_id):
    user_id, role = authenticate(("Servicer", "CreditManager", "PlatformAdmin"))
    parse_body([("cancellation_reason", "str", True)])
    order = flows.order_or_404(order_id)
    check_account_scope(user_id, role, order["servicer_account_id"])
    if order["fulfillment_status"] not in ("DRAFT", "ALLOCATED", "HELD") \
            or order["settlement_status"] == "INVOICED":
        raise ApiError("ERR_ORDER_STATE_INVALID",
                       "This order can no longer be cancelled")
    flows.cancel_order(order)
    account = _account_of(order)
    if account is not None:
        flows.sync_account(account)
    return ok(serialize.part_order(order))


# --------------------------------------------------------------------------
# reads
# --------------------------------------------------------------------------

@bp.get("/part-orders")
def list_orders():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    rows = flows.rows_sorted(db.part_orders)
    for field in ("servicer_account_id", "pickup_branch_id", "fulfillment_status",
                  "settlement_status", "fulfillment_mode", "hold_reason"):
        value = q_str(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    page, total = serialize.paginate(rows, limit, offset)
    return ok_list([serialize.part_order(r) for r in page], limit, offset, total)


@bp.get("/part-orders/<order_id>")
def get_order(order_id):
    user_id, role = authenticate(ALL_ROLES)
    order = flows.order_or_404(order_id)
    check_account_scope(user_id, role, order["servicer_account_id"])
    return ok(serialize.part_order(order))


@bp.get("/order-lines")
def list_order_lines():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    rows = flows.rows_sorted(db.order_lines)
    for field in ("part_order_id", "requested_part_id", "resolved_part_id",
                  "allocation_branch_id", "line_status"):
        value = q_str(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    page, total = serialize.paginate(rows, limit, offset)
    return ok_list([serialize.order_line(r) for r in page], limit, offset, total)


@bp.get("/order-lines/<line_id>")
def get_order_line(line_id):
    authenticate(ALL_ROLES)
    return ok(serialize.order_line(flows.line_or_404(line_id)))
