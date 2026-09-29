"""Retailer accounts, the order book, invoicing and shipping (PRD 3.5, 3.6)."""

from flask import Blueprint

from core import (
    DISCOUNT_TIERS,
    ORDER_STATUSES,
    RETAILER_STATUSES,
    ApiError,
    apply_fields,
    auth,
    bad,
    created_row,
    date_of,
    db,
    get_body,
    ok_list,
    ok_row,
    ordered,
    page,
    q_bool,
    q_enum,
    q_str,
    v_bool,
    v_int,
    v_str,
)
from calc import retailer_discount_tier, retailer_invoice_total
import services as svc

retailers_bp = Blueprint("retailers", __name__, url_prefix="/comics/retailers")
orders_bp = Blueprint("orders", __name__, url_prefix="/comics/retailer-orders")


# ---------------------------------------------------------------------------
# Retailer accounts
# ---------------------------------------------------------------------------


@retailers_bp.post("")
def create_retailer():
    auth(("SalesDirector",))
    body = get_body()
    account_no = v_str(body, "account_no", required=True, min_len=1, max_len=32)
    name = v_str(body, "name", required=True, min_len=1, max_len=160)
    credit_limit_cents = v_int(body, "credit_limit_cents", required=True, minimum=0)
    non_returnable_ack = v_bool(body, "non_returnable_ack", required=True)
    opening_units_ytd = v_int(body, "opening_units_ytd", minimum=0, default=0)
    if any(r["account_no"] == account_no for r in db.retailers.values()):
        bad("A retailer account numbered '%s' already exists." % account_no)

    row = db.new_row(
        account_no=account_no,
        name=name,
        credit_limit_cents=credit_limit_cents,
        non_returnable_ack=non_returnable_ack,
        opening_units_ytd=opening_units_ytd,
        cumulative_units_ytd=opening_units_ytd,
        open_balance_cents=0,
        discount_tier=retailer_discount_tier(opening_units_ytd),
        status="ACTIVE",
        suspension_reason=None,
    )
    db.retailers[row["id"]] = row
    return created_row(svc.retailer_json, row)


@retailers_bp.get("")
def list_retailers():
    auth(("EditorInChief", "SalesDirector", "RoyaltyAccountant"))
    discount_tier = q_enum("discount_tier", DISCOUNT_TIERS)
    status = q_enum("status", RETAILER_STATUSES)
    rows = ordered(db.retailers)
    if discount_tier is not None:
        rows = [r for r in rows if r["discount_tier"] == discount_tier]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    window, meta = page(rows)
    return ok_list(svc.retailer_json, window, meta)


@retailers_bp.get("/<retailer_id>")
def read_retailer(retailer_id):
    auth(("EditorInChief", "SalesDirector", "RoyaltyAccountant", "Retailer"))
    return ok_row(svc.retailer_json, svc.get_retailer(retailer_id))


@retailers_bp.post("/<retailer_id>/suspend")
def suspend_retailer(retailer_id):
    auth(("SalesDirector",))
    body = get_body()
    reason = v_str(body, "reason", required=True, min_len=1, max_len=500)
    retailer = svc.get_retailer(retailer_id)
    if retailer["status"] != "ACTIVE":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only an ACTIVE account can be suspended, not %s." % retailer["status"],
        )
    apply_fields(retailer, status="SUSPENDED", suspension_reason=reason)
    return ok_row(svc.retailer_json, retailer)


@retailers_bp.post("/<retailer_id>/reinstate")
def reinstate_retailer(retailer_id):
    auth(("SalesDirector",))
    retailer = svc.get_retailer(retailer_id)
    if retailer["status"] != "SUSPENDED":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only a SUSPENDED account can be reinstated, not %s." % retailer["status"],
        )
    apply_fields(retailer, status="ACTIVE", suspension_reason=None)
    return ok_row(svc.retailer_json, retailer)


# ---------------------------------------------------------------------------
# Retailer orders
# ---------------------------------------------------------------------------


def _own_order(order, user_id, role):
    if role == "Retailer" and order["retailer_id"] != user_id:
        raise ApiError(
            "ERR_FORBIDDEN_RESOURCE", "This order belongs to another retailer account."
        )


def _invoice_lines(order, issue):
    """The pinned invoice line sequence: the standard line first, then one line
    per frozen incentive allocation in stored order."""
    standard = svc.standard_cover(issue["id"])
    unit_price = standard["cover_price_cents"] if standard else issue["cover_price_cents"]
    lines = [(order["standard_qty"], unit_price)]
    for allocation in order["earned_variant_allocations"]:
        cover = db.variant_covers.get(allocation["variant_cover_id"])
        if cover is None:
            continue
        lines.append((allocation["qty"], cover["cover_price_cents"]))
    return lines


@orders_bp.post("")
def draft_order():
    user_id, role = auth(("Retailer",))
    body = get_body()
    retailer_id = v_str(body, "retailer_id", required=True, min_len=1)
    issue_id = v_str(body, "issue_id", required=True, min_len=1)
    standard_qty = v_int(body, "standard_qty", required=True, minimum=1)
    exclusive_variant_qty = v_int(body, "exclusive_variant_qty", minimum=0, default=0)

    retailer = svc.get_retailer(retailer_id)
    issue = svc.get_issue(issue_id)
    if retailer["id"] != user_id:
        raise ApiError(
            "ERR_FORBIDDEN_RESOURCE",
            "A retailer may only draft orders for its own account.",
        )
    if exclusive_variant_qty > 0 and not svc.has_exclusive_cover(issue["id"]):
        raise ApiError(
            "ERR_VARIANT_NOT_AVAILABLE",
            "The issue carries no RETAILER_EXCLUSIVE cover to request.",
        )

    row = db.new_row(
        retailer_id=retailer["id"],
        issue_id=issue["id"],
        standard_qty=standard_qty,
        exclusive_variant_qty=exclusive_variant_qty,
        earned_variant_allocations=[],
        total_units=0,
        is_reorder=issue["commercial_status"] == "ON_SALE",
        discount_tier_applied=None,
        merchandise_net_cents=0,
        handling_fee_cents=0,
        invoice_total_cents=0,
        status="DRAFT",
        cancel_reason=None,
    )
    db.orders[row["id"]] = row
    return created_row(svc.order_json, row)


@orders_bp.get("")
def list_orders():
    auth(("EditorInChief", "SalesDirector", "RoyaltyAccountant", "Retailer"))
    retailer_id = q_str("retailer_id")
    issue_id = q_str("issue_id")
    status = q_enum("status", ORDER_STATUSES)
    is_reorder = q_bool("is_reorder")
    rows = ordered(db.orders)
    if retailer_id is not None:
        rows = [r for r in rows if r["retailer_id"] == retailer_id]
    if issue_id is not None:
        rows = [r for r in rows if r["issue_id"] == issue_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if is_reorder is not None:
        rows = [r for r in rows if r["is_reorder"] == is_reorder]
    window, meta = page(rows)
    return ok_list(svc.order_json, window, meta)


@orders_bp.get("/<order_id>")
def read_order(order_id):
    auth(("EditorInChief", "SalesDirector", "RoyaltyAccountant", "Retailer"))
    return ok_row(svc.order_json, svc.get_order(order_id))


@orders_bp.post("/<order_id>/submit")
def submit_order(order_id):
    user_id, role = auth(("Retailer",))
    order = svc.get_order(order_id)
    _own_order(order, user_id, role)
    if order["status"] != "DRAFT":
        raise ApiError(
            "ERR_INVALID_STATE",
            "An order submits from DRAFT, not %s." % order["status"],
        )
    issue = svc.get_issue(order["issue_id"])
    retailer = svc.get_retailer(order["retailer_id"])
    required_status = "ON_SALE" if order["is_reorder"] else "SOLICITED"
    if issue["commercial_status"] != required_status:
        raise ApiError(
            "ERR_ISSUE_NOT_SOLICITED",
            "The issue is %s; %s is required for this order."
            % (issue["commercial_status"], required_status),
        )
    if retailer["status"] != "ACTIVE":
        raise ApiError(
            "ERR_RETAILER_NOT_ACTIVE", "A suspended account may not submit orders."
        )
    if not retailer["non_returnable_ack"]:
        raise ApiError(
            "ERR_NON_RETURNABLE_ACK_REQUIRED",
            "The account has not acknowledged non-returnable terms.",
        )
    if retailer["open_balance_cents"] >= retailer["credit_limit_cents"]:
        raise ApiError(
            "ERR_CREDIT_LIMIT_EXCEEDED",
            "The account has no credit headroom for new business.",
        )
    apply_fields(order, status="SUBMITTED")
    return ok_row(svc.order_json, order)


@orders_bp.post("/<order_id>/adjust")
def adjust_order(order_id):
    user_id, role = auth(("Retailer",))
    body = get_body()
    standard_qty = v_int(body, "standard_qty", required=True, minimum=1)
    exclusive_variant_qty = v_int(body, "exclusive_variant_qty", minimum=0)
    order = svc.get_order(order_id)
    _own_order(order, user_id, role)
    if order["status"] != "SUBMITTED":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only a SUBMITTED order may be adjusted, not %s." % order["status"],
        )
    issue = svc.get_issue(order["issue_id"])
    if date_of(db.now()) >= date_of(issue["foc_date"]):
        raise ApiError(
            "ERR_FOC_ALREADY_PASSED",
            "Quantities are frozen from the final order cut-off onwards.",
        )
    if exclusive_variant_qty is not None and exclusive_variant_qty > 0:
        if not svc.has_exclusive_cover(issue["id"]):
            raise ApiError(
                "ERR_VARIANT_NOT_AVAILABLE",
                "The issue carries no RETAILER_EXCLUSIVE cover to request.",
            )
    updates = {"standard_qty": standard_qty}
    if exclusive_variant_qty is not None:
        updates["exclusive_variant_qty"] = exclusive_variant_qty
    apply_fields(order, **updates)
    return ok_row(svc.order_json, order)


@orders_bp.post("/<order_id>/invoice")
def invoice_order(order_id):
    auth(("SalesDirector",))
    order = svc.get_order(order_id)
    if order["status"] != "FOC_LOCKED":
        raise ApiError(
            "ERR_INVALID_STATE",
            "An order invoices from FOC_LOCKED, not %s." % order["status"],
        )
    retailer = svc.get_retailer(order["retailer_id"])
    issue = svc.get_issue(order["issue_id"])
    if retailer["status"] != "ACTIVE":
        raise ApiError(
            "ERR_RETAILER_NOT_ACTIVE", "A suspended account may not be invoiced."
        )
    if not retailer["non_returnable_ack"]:
        raise ApiError(
            "ERR_NON_RETURNABLE_ACK_REQUIRED",
            "The account has not acknowledged non-returnable terms.",
        )

    tier = retailer["discount_tier"]
    figures = retailer_invoice_total(tier, _invoice_lines(order, issue))
    if retailer["open_balance_cents"] + figures["invoice_total_cents"] > retailer[
        "credit_limit_cents"
    ]:
        raise ApiError(
            "ERR_CREDIT_LIMIT_EXCEEDED",
            "This invoice would carry the account past its credit limit.",
        )

    apply_fields(
        order,
        discount_tier_applied=tier,
        merchandise_net_cents=figures["merchandise_net_cents"],
        handling_fee_cents=figures["handling_fee_cents"],
        invoice_total_cents=figures["invoice_total_cents"],
        status="INVOICED",
    )
    svc.recompute_retailer_balance(retailer)
    return ok_row(svc.order_json, order)


@orders_bp.post("/<order_id>/ship")
def ship_order(order_id):
    auth(("SalesDirector",))
    order = svc.get_order(order_id)
    if order["status"] != "INVOICED":
        raise ApiError(
            "ERR_INVALID_STATE",
            "An order ships from INVOICED, not %s." % order["status"],
        )
    issue = svc.get_issue(order["issue_id"])
    if issue["printed_units"] < issue["total_ordered_units"]:
        raise ApiError(
            "ERR_PRINT_NOT_COMPLETE",
            "The issue has printed %d of %d ordered copies."
            % (issue["printed_units"], issue["total_ordered_units"]),
        )

    gross = sum(qty * unit for qty, unit in _invoice_lines(order, issue))
    apply_fields(order, status="SHIPPED")
    event = db.new_row(
        versioned=False,
        issue_id=issue["id"],
        channel="PRINT_DM",
        basis_status="ACTUAL",
        gross_receipts_cents=gross,
        net_receipts_cents=order["merchandise_net_cents"],
        units=order["total_units"],
        period=db.now()[:7],
        source="SHIPMENT",
    )
    db.revenue_events[event["id"]] = event
    svc.recompute_issue_order_units(issue)
    return ok_row(svc.order_json, order)


@orders_bp.post("/<order_id>/cancel")
def cancel_order(order_id):
    user_id, role = auth(("SalesDirector", "Retailer"))
    body = get_body()
    reason = v_str(body, "reason", required=True, min_len=1, max_len=500)
    order = svc.get_order(order_id)
    _own_order(order, user_id, role)

    if order["status"] == "SHIPPED":
        raise ApiError(
            "ERR_RETURNS_NOT_PERMITTED",
            "A shipped order is final under non-returnable terms.",
        )
    if order["status"] == "CANCELLED":
        raise ApiError("ERR_INVALID_STATE", "The order is already cancelled.")
    if role == "Retailer" and order["status"] not in ("DRAFT", "SUBMITTED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "A %s order can only be cancelled by the sales director." % order["status"],
        )

    apply_fields(order, status="CANCELLED", cancel_reason=reason)
    retailer = db.retailers.get(order["retailer_id"])
    if retailer is not None:
        svc.recompute_retailer_units(retailer)
        svc.recompute_retailer_balance(retailer)
    issue = db.issues.get(order["issue_id"])
    if issue is not None:
        svc.recompute_issue_order_units(issue)
    return ok_row(svc.order_json, order)
