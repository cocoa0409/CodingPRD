"""Order capture, line pricing, payment, cancellation, and returns."""
from flask import Blueprint, request

import db
import services as svc
from authz import (
    require_roles, owner_or_forbid, owner_of_order, owner_of_order_line,
    owner_of_return_record, scoped_account_filter,
)
from calc import price_line, tax_of
from envelope import ok_object, ok_list
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_REFERENCE_NOT_FOUND, ERR_VALIDATION,
    ERR_STALE_VERSION, ERR_ACCOUNT_SUSPENDED, ERR_JOB_NOT_OPEN,
    ERR_ORDER_NOT_PAYABLE, ERR_ORDER_NOT_CANCELLABLE, ERR_ORDER_NOT_REFUNDABLE,
    ERR_VOC_LIMIT_EXCEEDED, ERR_PRODUCT_NOT_TINTABLE, ERR_CUSTOM_TINT_NO_RETURN,
    ERR_RETURN_QUANTITY_EXCEEDED, ERR_PRODUCT_DISCONTINUED, ERR_FORMULA_RETIRED,
    ERR_FORMULA_PRODUCT_MISMATCH, ERR_SPEC_LINE_PRODUCT_MISMATCH,
    ERR_JOB_ACCOUNT_MISMATCH, ERR_CREDIT_LIMIT_EXCEEDED, ERR_BUDGET_CAP_EXCEEDED,
)
from serializers import ser_order, ser_order_line, ser_return_record, sorted_rows
from validate import body_json, req_int, pagination_params, query_enum_filter

bp = Blueprint("orders", __name__)

ORDER_ACTORS = ["StoreAssociate", "Contractor"]
READERS = ["CorporateAdmin", "StoreManager", "StoreAssociate", "Contractor"]
PAYMENT_STATUS = {"UNPAID", "PAID", "PARTIALLY_REFUNDED", "REFUNDED"}
FULFILLMENT_STATUS = {"PENDING", "OUT_FOR_DELIVERY", "DELIVERED", "CANCELLED"}


def _get_order(order_id):
    o = db.orders.get(order_id)
    if o is None:
        raise_err(ERR_NOT_FOUND, "order %s not found" % order_id)
    return o


def _get_order_line(line_id):
    l = db.order_lines.get(line_id)
    if l is None:
        raise_err(ERR_NOT_FOUND, "order line %s not found" % line_id)
    return l


@bp.post("/orders")
def create_order():
    uid, role = require_roles(ORDER_ACTORS)
    data = body_json()

    # Ownership (stage 3) precedes body references (stage 5).
    if role == "Contractor":
        requested = data.get("contractor_account_id")
        if isinstance(requested, str):
            owner_or_forbid(uid, role, requested)

    # Body references (stage 5): every supplied FK must resolve.
    contractor_account_id = data.get("contractor_account_id")
    job_account_id = data.get("job_account_id")
    if isinstance(contractor_account_id, str) and contractor_account_id not in db.contractor_accounts:
        raise_err(ERR_REFERENCE_NOT_FOUND,
                  "contractor_account_id %s not found" % contractor_account_id)
    if isinstance(job_account_id, str) and job_account_id not in db.job_accounts:
        raise_err(ERR_REFERENCE_NOT_FOUND, "job_account_id %s not found" % job_account_id)
    raw_lines = data.get("lines")
    if isinstance(raw_lines, list):
        for li in raw_lines:
            if not isinstance(li, dict):
                continue
            pid = li.get("product_id")
            if isinstance(pid, str) and pid not in db.products:
                raise_err(ERR_REFERENCE_NOT_FOUND, "product_id %s not found" % pid)
            fid = li.get("formula_id")
            if fid is not None and isinstance(fid, str) and fid not in db.tint_formulas:
                raise_err(ERR_REFERENCE_NOT_FOUND, "formula_id %s not found" % fid)
            sid = li.get("spec_line_id")
            if sid is not None and isinstance(sid, str) and sid not in db.spec_lines:
                raise_err(ERR_REFERENCE_NOT_FOUND, "spec_line_id %s not found" % sid)

    # Shape (stage 6).
    if not isinstance(contractor_account_id, str):
        raise_err(ERR_VALIDATION, "field 'contractor_account_id' is required and must be a string")
    if not isinstance(job_account_id, str):
        raise_err(ERR_VALIDATION, "field 'job_account_id' is required and must be a string")
    expected_version = req_int(data, "expected_contractor_account_version")
    if not isinstance(raw_lines, list):
        raise_err(ERR_VALIDATION, "field 'lines' is required and must be an array")
    parsed_lines = []
    for i, li in enumerate(raw_lines):
        if not isinstance(li, dict):
            raise_err(ERR_VALIDATION, "field 'lines[%d]' must be an object" % i)
        pid = li.get("product_id")
        if not isinstance(pid, str):
            raise_err(ERR_VALIDATION, "field 'lines[%d].product_id' is required" % i)
        qty = li.get("quantity")
        if not isinstance(qty, int) or isinstance(qty, bool):
            raise_err(ERR_VALIDATION, "field 'lines[%d].quantity' must be an integer" % i)
        if qty <= 0:
            raise_err(ERR_VALIDATION, "field 'lines[%d].quantity' must be > 0" % i)
        fid = li.get("formula_id")
        if fid is not None and not isinstance(fid, str):
            raise_err(ERR_VALIDATION, "field 'lines[%d].formula_id' must be a string or null" % i)
        sid = li.get("spec_line_id")
        if sid is not None and not isinstance(sid, str):
            raise_err(ERR_VALIDATION, "field 'lines[%d].spec_line_id' must be a string or null" % i)
        parsed_lines.append({"product_id": pid, "quantity": qty, "formula_id": fid,
                             "spec_line_id": sid})

    account = db.contractor_accounts[contractor_account_id]
    job = db.job_accounts[job_account_id]

    # OCC (stage 7).
    if expected_version != account["version"]:
        raise_err(ERR_STALE_VERSION,
                  "expected_contractor_account_version does not match the account's current version")

    # State (stage 8).
    if account["status"] != "ACTIVE":
        raise_err(ERR_ACCOUNT_SUSPENDED, "contractor account is SUSPENDED")
    if job["status"] != "OPEN":
        raise_err(ERR_JOB_NOT_OPEN, "job account is not OPEN")

    now = db.now()

    # Business: safety first -- VOC compliance per line at the creation instant.
    for li in parsed_lines:
        product = db.products[li["product_id"]]
        rule = svc.voc_rule_at(job["jurisdiction_id"], product["category"], now)
        if rule is not None and product["voc_gpl"] > rule["max_voc_gpl"]:
            raise_err(ERR_VOC_LIMIT_EXCEEDED,
                      "product voc_gpl %d exceeds the effective limit %d"
                      % (product["voc_gpl"], rule["max_voc_gpl"]))

    # Constraints: a line carrying formula_id requires a tintable product.
    for li in parsed_lines:
        if li["formula_id"] is not None:
            if not db.products[li["product_id"]]["tintable"]:
                raise_err(ERR_PRODUCT_NOT_TINTABLE,
                          "product %s does not accept custom tint formulas" % li["product_id"])

    # Referential checks.
    for li in parsed_lines:
        if db.products[li["product_id"]]["status"] != "ACTIVE":
            raise_err(ERR_PRODUCT_DISCONTINUED, "product %s is DISCONTINUED" % li["product_id"])
    for li in parsed_lines:
        if li["formula_id"] is not None:
            if db.tint_formulas[li["formula_id"]]["status"] != "ACTIVE":
                raise_err(ERR_FORMULA_RETIRED, "formula %s is RETIRED" % li["formula_id"])
    for li in parsed_lines:
        if li["formula_id"] is not None:
            if db.tint_formulas[li["formula_id"]]["product_id"] != li["product_id"]:
                raise_err(ERR_FORMULA_PRODUCT_MISMATCH,
                          "formula %s tints a different product" % li["formula_id"])
    for li in parsed_lines:
        if li["spec_line_id"] is not None:
            spec_line = db.spec_lines[li["spec_line_id"]]
            sheet = db.spec_sheets.get(spec_line["spec_sheet_id"])
            if spec_line["product_id"] != li["product_id"] or sheet is None \
                    or sheet["status"] != "APPROVED":
                raise_err(ERR_SPEC_LINE_PRODUCT_MISMATCH,
                          "spec line product mismatch or sheet not APPROVED")
    if job["contractor_account_id"] != contractor_account_id:
        raise_err(ERR_JOB_ACCOUNT_MISMATCH, "job does not belong to the order's contractor")

    # Pricing per line_pricing / order_totals (pinned rounding order).
    tier = account["tier"]
    priced = []
    subtotal = 0
    list_sum = 0
    for li in parsed_lines:
        product = db.products[li["product_id"]]
        unit_list = product["list_price_cents"]
        unit_price, line_total = price_line(tier, unit_list, li["quantity"])
        priced.append({**li, "unit_list_price_cents": unit_list,
                       "unit_price_cents": unit_price, "line_total_cents": line_total})
        subtotal += line_total
        list_sum += unit_list * li["quantity"]
    tax = tax_of(subtotal)
    total = subtotal + tax

    # Fiscal caps: credit limit, then budget cap.
    if svc.outstanding_balance(contractor_account_id) + total > account["credit_limit_cents"]:
        raise_err(ERR_CREDIT_LIMIT_EXCEEDED,
                  "outstanding balance plus new order total exceeds the credit limit")
    if job["budget_cap_cents"] is not None \
            and svc.job_spent(job_account_id) + total > job["budget_cap_cents"]:
        raise_err(ERR_BUDGET_CAP_EXCEEDED,
                  "job spend plus new order total exceeds the budget cap")

    order = svc.stamp_new({
        "contractor_account_id": contractor_account_id,
        "job_account_id": job_account_id,
        "payment_status": "UNPAID",
        "fulfillment_status": "PENDING",
        "tier_snapshot": tier,
        "subtotal_cents": subtotal,
        "discount_cents": list_sum - subtotal,
        "tax_cents": tax,
        "total_cents": total,
        "paid_at": None,
    })
    db.orders[order["id"]] = order
    for pl in priced:
        line = svc.stamp_new({
            "order_id": order["id"],
            "product_id": pl["product_id"],
            "formula_id": pl["formula_id"],
            "spec_line_id": pl["spec_line_id"],
            "quantity": pl["quantity"],
            "returned_quantity": 0,
            "unit_list_price_cents": pl["unit_list_price_cents"],
            "unit_price_cents": pl["unit_price_cents"],
            "line_total_cents": pl["line_total_cents"],
            "is_custom_tint": pl["formula_id"] is not None,
        })
        db.order_lines[line["id"]] = line
    svc.bump(account)
    return ok_object(ser_order(order), 201)


@bp.get("/orders/<order_id>")
def get_order(order_id):
    uid, role = require_roles(READERS)
    order = _get_order(order_id)
    owner_of_order(uid, role, order)
    return ok_object(ser_order(order))


@bp.get("/orders")
def list_orders():
    uid, role = require_roles(READERS)
    limit, offset = pagination_params()
    contractor_filter = scoped_account_filter(uid, role, request.args.get("contractor_account_id"))
    job_filter = request.args.get("job_account_id")
    payment_filter = query_enum_filter("payment_status", PAYMENT_STATUS)
    fulfillment_filter = query_enum_filter("fulfillment_status", FULFILLMENT_STATUS)
    rows = list(db.orders.values())
    if contractor_filter is not None:
        rows = [o for o in rows if o["contractor_account_id"] == contractor_filter]
    if job_filter is not None:
        rows = [o for o in rows if o["job_account_id"] == job_filter]
        job = db.job_accounts.get(job_filter)
        if role == "Contractor" and job is not None:
            owner_or_forbid(uid, role, job["contractor_account_id"])
    if payment_filter is not None:
        rows = [o for o in rows if o["payment_status"] == payment_filter]
    if fulfillment_filter is not None:
        rows = [o for o in rows if o["fulfillment_status"] == fulfillment_filter]
    rows = sorted_rows(rows)
    total = len(rows)
    return ok_list([ser_order(o) for o in rows[offset:offset + limit]], total, limit, offset)


@bp.post("/orders/<order_id>/pay")
def pay_order(order_id):
    uid, role = require_roles(ORDER_ACTORS)
    order = _get_order(order_id)
    owner_of_order(uid, role, order)
    account = db.contractor_accounts.get(order["contractor_account_id"])
    if account is not None and account["status"] != "ACTIVE":
        raise_err(ERR_ACCOUNT_SUSPENDED, "contractor account is SUSPENDED")
    if order["payment_status"] != "UNPAID":
        raise_err(ERR_ORDER_NOT_PAYABLE, "order payment_status is not UNPAID")
    order["payment_status"] = "PAID"
    order["paid_at"] = db.now()
    svc.bump(order)
    svc.post_earn(order)
    if account is not None:
        svc.bump(account)
    return ok_object(ser_order(order))


@bp.post("/orders/<order_id>/cancel")
def cancel_order(order_id):
    uid, role = require_roles(ORDER_ACTORS)
    order = _get_order(order_id)
    owner_of_order(uid, role, order)
    if order["fulfillment_status"] != "PENDING" or order["payment_status"] != "UNPAID":
        raise_err(ERR_ORDER_NOT_CANCELLABLE,
                  "order is not in (PENDING, UNPAID) and cannot be cancelled")
    order["fulfillment_status"] = "CANCELLED"
    svc.bump(order)
    account = db.contractor_accounts.get(order["contractor_account_id"])
    if account is not None:
        svc.bump(account)
    return ok_object(ser_order(order))


# --- order lines ---------------------------------------------------------------------
@bp.get("/order-lines")
def list_order_lines():
    uid, role = require_roles(READERS)
    limit, offset = pagination_params()
    order_filter = request.args.get("order_id")
    product_filter = request.args.get("product_id")
    formula_filter = request.args.get("formula_id")
    spec_line_filter = request.args.get("spec_line_id")
    rows = list(db.order_lines.values())
    if order_filter is not None:
        rows = [l for l in rows if l["order_id"] == order_filter]
        order = db.orders.get(order_filter)
        if role == "Contractor" and order is not None:
            owner_or_forbid(uid, role, order["contractor_account_id"])
    if role == "Contractor" and order_filter is None:
        rows = [l for l in rows
                if db.orders.get(l["order_id"]) is not None
                and db.orders[l["order_id"]]["contractor_account_id"] == uid]
    if product_filter is not None:
        rows = [l for l in rows if l["product_id"] == product_filter]
    if formula_filter is not None:
        rows = [l for l in rows if l["formula_id"] == formula_filter]
    if spec_line_filter is not None:
        rows = [l for l in rows if l["spec_line_id"] == spec_line_filter]
    rows = sorted_rows(rows)
    total = len(rows)
    return ok_list([ser_order_line(l) for l in rows[offset:offset + limit]], total, limit, offset)


@bp.get("/order-lines/<line_id>")
def get_order_line(line_id):
    uid, role = require_roles(READERS)
    line = _get_order_line(line_id)
    owner_of_order_line(uid, role, line)
    return ok_object(ser_order_line(line))


@bp.post("/order-lines/<line_id>/return")
def return_line(line_id):
    require_roles(["StoreAssociate"])
    line = _get_order_line(line_id)
    data = body_json()
    quantity = req_int(data, "quantity", minimum=1)
    order = db.orders.get(line["order_id"])
    if order is None or order["payment_status"] not in {"PAID", "PARTIALLY_REFUNDED"}:
        raise_err(ERR_ORDER_NOT_REFUNDABLE,
                  "order payment_status is not PAID or PARTIALLY_REFUNDED")
    if line["is_custom_tint"]:
        raise_err(ERR_CUSTOM_TINT_NO_RETURN, "custom-tint lines are never returnable")
    if quantity > line["quantity"] - line["returned_quantity"]:
        raise_err(ERR_RETURN_QUANTITY_EXCEEDED,
                  "return quantity exceeds quantity - returned_quantity")
    rr = svc.process_return(line, quantity)
    return ok_object(ser_return_record(rr), 201)


# --- return records ---------------------------------------------------------------------
@bp.get("/return-records")
def list_return_records():
    uid, role = require_roles(READERS)
    limit, offset = pagination_params()
    line_filter = request.args.get("order_line_id")
    rows = list(db.return_records.values())
    if line_filter is not None:
        rows = [r for r in rows if r["order_line_id"] == line_filter]
        line = db.order_lines.get(line_filter)
        if role == "Contractor" and line is not None:
            owner_of_order_line(uid, role, line)
    if role == "Contractor" and line_filter is None:
        def owned(rr):
            line = db.order_lines.get(rr["order_line_id"])
            order = db.orders.get(line["order_id"]) if line else None
            return order is not None and order["contractor_account_id"] == uid
        rows = [r for r in rows if owned(r)]
    rows = sorted_rows(rows)
    total = len(rows)
    return ok_list([ser_return_record(r) for r in rows[offset:offset + limit]], total, limit, offset)


@bp.get("/return-records/<record_id>")
def get_return_record(record_id):
    uid, role = require_roles(READERS)
    rr = db.return_records.get(record_id)
    if rr is None:
        raise_err(ERR_NOT_FOUND, "return record %s not found" % record_id)
    owner_of_return_record(uid, role, rr)
    return ok_object(ser_return_record(rr))
