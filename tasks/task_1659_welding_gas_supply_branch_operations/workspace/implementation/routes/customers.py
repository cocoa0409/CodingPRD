"""Customer accounts: CRUD, manual credit-hold actions, payment waterfall."""
from flask import Blueprint

import db
from db import store, new_common, new_id, touch, is_int
from errors import ApiError
from middleware import require_roles, body
from response import ok, created, list_response, filter_param
from services import exposure

bp = Blueprint("customers", __name__)

ALL_ROLES = ("CounterRep", "BranchManager", "RouteDriver", "Trainer", "ServiceTech")


def get_customer(cid):
    cust = store.customers.get(cid)
    if cust is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Customer not found")
    return cust


@bp.route("/customers", methods=["POST"])
@require_roles("CounterRep", "BranchManager")
def create_customer():
    b = body()
    # Priority 3: body-referenced ids must exist.
    pb_id = b.get("price_book_id")
    if pb_id is not None and pb_id not in store.price_books:
        raise ApiError("ERR_NOT_FOUND", 404, "PriceBook not found")
    # Priority 4: shape.
    account_no = b.get("account_no")
    name = b.get("name")
    terms = b.get("terms", "CASH")
    credit_limit = b.get("credit_limit_cents", 0)
    if not isinstance(account_no, str) or not account_no:
        raise ApiError("ERR_VALIDATION", 400, "account_no is required")
    if not isinstance(name, str) or not name:
        raise ApiError("ERR_VALIDATION", 400, "name is required")
    if terms not in ("CASH", "NET30"):
        raise ApiError("ERR_VALIDATION", 400, "terms must be CASH or NET30")
    if not is_int(credit_limit) or credit_limit < 0:
        raise ApiError("ERR_VALIDATION", 400, "credit_limit_cents must be an integer >= 0")
    if pb_id is not None and not isinstance(pb_id, str):
        raise ApiError("ERR_VALIDATION", 400, "price_book_id must be a string or null")
    # Priority 10: uniqueness.
    if any(c["account_no"] == account_no for c in store.customers.values()):
        raise ApiError("ERR_DUPLICATE_ACCOUNT", 409, "account_no already exists")
    cust = {
        "id": new_id(),
        "account_no": account_no,
        "name": name,
        "terms": terms,
        "status": "ACTIVE",
        "credit_limit_cents": credit_limit,
        "price_book_id": pb_id,
        "credit_balance_cents": 0,
    }
    new_common(cust)
    store.customers[cust["id"]] = cust
    return created(exposure.customer_view(cust))


@bp.route("/customers", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_customers():
    rows = list(store.customers.values())
    rows = filter_param(rows, "status")
    rows = filter_param(rows, "terms")
    rows = filter_param(rows, "price_book_id")
    return list_response([exposure.customer_view(c) for c in rows])


@bp.route("/customers/<cid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_one_customer(cid):
    return ok(exposure.customer_view(get_customer(cid)))


@bp.route("/customers/<cid>", methods=["PATCH"])
@require_roles("CounterRep", "BranchManager")
def update_customer(cid):
    cust = get_customer(cid)
    b = body()
    # Priority 3: referenced price book must exist when attaching/replacing.
    if "price_book_id" in b and b["price_book_id"] is not None \
            and b["price_book_id"] not in store.price_books:
        raise ApiError("ERR_NOT_FOUND", 404, "PriceBook not found")
    # Priority 4: shape of the supplied fields.
    if "name" in b and (not isinstance(b["name"], str) or not b["name"]):
        raise ApiError("ERR_VALIDATION", 400, "name must be a non-empty string")
    if "terms" in b and b["terms"] not in ("CASH", "NET30"):
        raise ApiError("ERR_VALIDATION", 400, "terms must be CASH or NET30")
    if "credit_limit_cents" in b and (not is_int(b["credit_limit_cents"])
                                    or b["credit_limit_cents"] < 0):
        raise ApiError("ERR_VALIDATION", 400, "credit_limit_cents must be an integer >= 0")
    if "price_book_id" in b and b["price_book_id"] is not None \
            and not isinstance(b["price_book_id"], str):
        raise ApiError("ERR_VALIDATION", 400, "price_book_id must be a string or null")
    for field in ("name", "terms", "credit_limit_cents", "price_book_id"):
        if field in b:
            cust[field] = b[field]
    touch(cust)
    return ok(exposure.customer_view(cust))


_CREDIT_HOLD_ACTIONS = {
    # action: (allowed from-states, target state)
    "PLACE_HOLD": (("ACTIVE",), "CREDIT_HOLD"),
    "RELEASE_HOLD": (("CREDIT_HOLD",), "ACTIVE"),
    "SUSPEND": (("ACTIVE", "CREDIT_HOLD"), "SUSPENDED"),
    "REINSTATE": (("SUSPENDED",), "ACTIVE"),
}


@bp.route("/customers/<cid>/credit-hold", methods=["POST"])
@require_roles("BranchManager")
def credit_hold(cid):
    cust = get_customer(cid)
    b = body()
    action = b.get("action")
    if action not in _CREDIT_HOLD_ACTIONS:
        raise ApiError("ERR_VALIDATION", 400,
                       "action must be PLACE_HOLD, RELEASE_HOLD, SUSPEND or REINSTATE")
    from_states, target = _CREDIT_HOLD_ACTIONS[action]
    if cust["status"] not in from_states:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Cannot %s a customer in status %s" % (action, cust["status"]))
    cust["status"] = target
    touch(cust)
    return ok(exposure.customer_view(cust))


@bp.route("/customers/<cid>/payments", methods=["POST"])
@require_roles("CounterRep", "BranchManager")
def apply_payment(cid):
    cust = get_customer(cid)
    b = body()
    # Priority 4: shape — both fields are non-optional.
    amount = b.get("amount_cents")
    expected = b.get("expected_customer_version")
    if not is_int(amount) or amount <= 0:
        raise ApiError("ERR_VALIDATION", 400, "amount_cents must be a positive integer")
    if not is_int(expected):
        raise ApiError("ERR_VALIDATION", 400, "expected_customer_version is required")
    # Priority 5: optimistic concurrency on Customer.version.
    if expected != cust["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_customer_version does not match the customer's current version")
    # Payment waterfall: OPEN invoices only, due_at ASC, then issued_at ASC,
    # then created_at ASC (never id). Allocation is exact min() arithmetic.
    open_invoices = [i for i in store.invoices.values()
                     if i["customer_id"] == cid and i["status"] == "OPEN"]
    open_invoices.sort(key=lambda i: (i["due_at"], i["issued_at"], i["created_at"],
                                      i.get("_seq", 0)))
    remaining = amount
    allocations = []
    for inv in open_invoices:
        if remaining <= 0:
            break
        applied = min(remaining, inv["amount_cents"] - inv["paid_cents"])
        if applied <= 0:
            continue
        inv["paid_cents"] += applied
        remaining -= applied
        if inv["paid_cents"] >= inv["amount_cents"]:
            inv["status"] = "PAID"
        touch(inv)
        allocations.append({
            "invoice_id": inv["id"],
            "applied_cents": applied,
            "paid_cents": inv["paid_cents"],
            "status": inv["status"],
        })
        # Invoice -> PAID cascade: linked ORDER payment_status INVOICED -> SETTLED.
        if inv["status"] == "PAID" and inv["source"] == "ORDER" and inv["order_id"]:
            order = store.orders.get(inv["order_id"])
            if order is not None and order["payment_status"] == "INVOICED":
                order["payment_status"] = "SETTLED"
                touch(order)
    credit_added = remaining
    cust["credit_balance_cents"] += credit_added
    touch(cust)
    # Auto-release CREDIT_HOLD when posted exposure falls to <= limit.
    exposure.release_if_cleared(cust)
    return ok({
        "allocations": allocations,
        "credit_added_cents": credit_added,
        "outstanding_balance_cents": exposure.outstanding_balance(cid),
        "posted_exposure_cents": exposure.posted_exposure(cust),
    })
