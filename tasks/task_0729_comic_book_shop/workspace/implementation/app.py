import os
import random
import string
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

from flask import Flask, request, jsonify, g

from errors import ApiError, err
from store import db, new_id, fmt_ts, parse_ts

app = Flask(__name__)

ROLES = {"Customer", "Clerk", "Manager"}
TIER_MAX = {"BRONZE": 1, "SILVER": 2, "GOLD": 3}
TIER_RANK = {"BRONZE": 1, "SILVER": 2, "GOLD": 3}
TIER_MULT = {"BRONZE": "1.0", "SILVER": "1.25", "GOLD": "1.5"}
SILVER_THRESHOLD = 50000
GOLD_THRESHOLD = 150000
DISPUTE_LIMIT = 3
CREDIT_REASONS = {"CONSIGNMENT_PAYOUT", "REFUND", "ADJUSTMENT", "REDEMPTION"}


# --------------------------------------------------------------------------
# Time / envelope helpers
# --------------------------------------------------------------------------
def wall_iso():
    return fmt_ts(datetime.now(timezone.utc))


def request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def meta(extra=None):
    m = {"api_request_id": request_id(), "api_request_timestamp": wall_iso()}
    if extra:
        m.update(extra)
    return m


def serialize(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def ok(data, response_type="object", code=200, extra_meta=None):
    body = {
        "meta": meta(extra_meta),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), code


def touch(entity):
    if "version" in entity:
        entity["version"] += 1
        entity["updated_at"] = wall_iso()


def base_common(common=True):
    now = wall_iso()
    e = {"id": new_id(), "created_at": now, "_seq": db.next_seq()}
    if common:
        e["updated_at"] = now
        e["version"] = 1
    return e


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers")
    g.user_id = uid
    g.role = role
    return uid, role


def require_role(allowed):
    if g.role not in allowed:
        raise err("ERR_UNAUTHORIZED", "Role not permitted for this operation")


def body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


# --------------------------------------------------------------------------
# Validation helpers
# --------------------------------------------------------------------------
def v_error(msg):
    raise err("ERR_VALIDATION", msg)


def req_str(d, key):
    val = d.get(key)
    if not isinstance(val, str) or val == "":
        v_error(f"'{key}' is required and must be a non-empty string")
    return val


def req_int(d, key, minimum=None):
    val = d.get(key)
    if not isinstance(val, int) or isinstance(val, bool):
        v_error(f"'{key}' is required and must be an integer")
    if minimum is not None and val < minimum:
        v_error(f"'{key}' must be >= {minimum}")
    return val


def opt_int(d, key, default, minimum=None):
    if key not in d or d.get(key) is None:
        return default
    val = d.get(key)
    if not isinstance(val, int) or isinstance(val, bool):
        v_error(f"'{key}' must be an integer")
    if minimum is not None and val < minimum:
        v_error(f"'{key}' must be >= {minimum}")
    return val


def req_dt(d, key):
    raw = d.get(key)
    if not isinstance(raw, str):
        v_error(f"'{key}' is required and must be an ISO 8601 datetime")
    dt = parse_ts(raw)
    if dt is None:
        v_error(f"'{key}' must be a valid ISO 8601 datetime")
    return dt


def get_entity(coll, eid):
    e = coll.get(eid)
    if e is None:
        raise err("ERR_NOT_FOUND", "Resource not found")
    return e


def round_half_up(dec):
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------
# Pagination + list helpers
# --------------------------------------------------------------------------
def paginate(items):
    q = request.args
    try:
        limit = int(q.get("limit", 10))
    except (ValueError, TypeError):
        v_error("'limit' must be an integer")
    try:
        offset = int(q.get("offset", 0))
    except (ValueError, TypeError):
        v_error("'offset' must be an integer")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    items = sorted(items, key=lambda e: e["_seq"])
    total = len(items)
    page = items[offset:offset + limit]
    extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return [serialize(e) for e in page], extra


def list_response(coll, owner_field=None, filters=None):
    items = list(coll.values())
    # Customer scoping to own resources
    if g.role == "Customer" and owner_field:
        items = [e for e in items if e.get(owner_field) == g.user_id]
    if filters:
        for fkey, ekey in filters.items():
            fval = request.args.get(fkey)
            if fval is not None:
                items = [e for e in items if str(e.get(ekey)) == fval]
    data, extra = paginate(items)
    return ok(data, "array", 200, extra)


def get_response(coll, eid, owner_field=None, self_id=False):
    e = get_entity(coll, eid)
    if g.role == "Customer":
        if self_id:
            if e["id"] != g.user_id:
                raise err("ERR_UNAUTHORIZED", "Cannot access another customer's resource")
        elif owner_field is not None:
            if e.get(owner_field) != g.user_id:
                raise err("ERR_UNAUTHORIZED", "Cannot access another customer's resource")
    return ok(serialize(e), "object", 200)


# --------------------------------------------------------------------------
# Loyalty helpers
# --------------------------------------------------------------------------
def recompute_tier(customer):
    settled = customer["lifetime_spend_cents"]
    forward = settled + sum(
        po["estimated_total_cents"]
        for po in db.pre_orders.values()
        if po["customer_id"] == customer["id"] and po["status"] == "CONFIRMED"
    )
    if forward >= GOLD_THRESHOLD:
        tier = "GOLD"
    elif forward >= SILVER_THRESHOLD:
        tier = "SILVER"
    else:
        tier = "BRONZE"
    changed = customer["loyalty_tier"] != tier
    customer["loyalty_tier"] = tier
    return changed


def recompute_available(issue):
    issue["copies_available"] = issue["copies_ordered"] - issue["copies_allocated"]


# --------------------------------------------------------------------------
# Error handlers
# --------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(e):
    body_ = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body_), e.http_status


@app.errorhandler(404)
def handle_404(e):
    body_ = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found"},
    }
    return jsonify(body_), 404


@app.errorhandler(405)
def handle_405(e):
    body_ = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Method not allowed"},
    }
    return jsonify(body_), 404


@app.errorhandler(Exception)
def handle_generic(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    body_ = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_VALIDATION", "message": str(e)},
    }
    return jsonify(body_), 400


# ==========================================================================
# CUSTOMERS
# ==========================================================================
@app.route("/api/customers", methods=["POST"])
def create_customer():
    authenticate()
    require_role({"Clerk", "Manager"})
    d = body()
    email = req_str(d, "email")
    full_name = req_str(d, "full_name")
    for c in db.customers.values():
        if c["email"] == email:
            v_error("email must be unique")
    e = base_common()
    e.update({
        "email": email,
        "full_name": full_name,
        "loyalty_tier": "BRONZE",
        "loyalty_points_balance": 0,
        "store_credit_cents": 0,
        "lifetime_spend_cents": 0,
        "status": "ACTIVE",
    })
    db.customers[e["id"]] = e
    return ok(serialize(e), "object", 201)


@app.route("/api/customers/<cid>", methods=["GET"])
def get_customer(cid):
    authenticate()
    require_role(ROLES)
    return get_response(db.customers, cid, self_id=True)


@app.route("/api/customers", methods=["GET"])
def list_customers():
    authenticate()
    require_role({"Clerk", "Manager"})
    return list_response(db.customers, filters={"status": "status"})


@app.route("/api/customers/<cid>/credit-adjustments", methods=["POST"])
def credit_adjustment(cid):
    authenticate()
    require_role({"Manager"})
    c = get_entity(db.customers, cid)
    d = body()
    amount = req_int(d, "amount_cents")
    reason = req_str(d, "reason")
    if reason not in CREDIT_REASONS:
        v_error("invalid reason")
    c["store_credit_cents"] += amount
    txn = base_common(common=False)
    txn.update({
        "customer_id": c["id"],
        "amount_cents": amount,
        "reason": reason,
        "balance_after_cents": c["store_credit_cents"],
    })
    db.credit_transactions[txn["id"]] = txn
    recompute_tier(c)
    touch(c)
    return ok(serialize(txn), "object", 201)


@app.route("/api/customers/<cid>/ban", methods=["POST"])
def ban_customer(cid):
    authenticate()
    require_role({"Manager"})
    c = get_entity(db.customers, cid)
    c["status"] = "BANNED"
    touch(c)
    return ok(serialize(c), "object", 200)


# ==========================================================================
# CREDIT TRANSACTIONS (read)
# ==========================================================================
@app.route("/api/credit-transactions/<tid>", methods=["GET"])
def get_credit_txn(tid):
    authenticate()
    require_role(ROLES)
    return get_response(db.credit_transactions, tid, owner_field="customer_id")


@app.route("/api/credit-transactions", methods=["GET"])
def list_credit_txns():
    authenticate()
    require_role(ROLES)
    return list_response(
        db.credit_transactions,
        owner_field="customer_id",
        filters={"customer_id": "customer_id", "reason": "reason"},
    )


# ==========================================================================
# COMIC SERIES
# ==========================================================================
@app.route("/api/comic-series", methods=["POST"])
def create_series():
    authenticate()
    require_role({"Clerk", "Manager"})
    d = body()
    title = req_str(d, "title")
    publisher = req_str(d, "publisher")
    e = base_common()
    e.update({"title": title, "publisher": publisher, "status": "ACTIVE"})
    db.comic_series[e["id"]] = e
    return ok(serialize(e), "object", 201)


@app.route("/api/comic-series/<sid>", methods=["GET"])
def get_series(sid):
    authenticate()
    require_role(ROLES)
    return get_response(db.comic_series, sid)


@app.route("/api/comic-series", methods=["GET"])
def list_series():
    authenticate()
    require_role(ROLES)
    return list_response(db.comic_series, filters={"status": "status"})


@app.route("/api/comic-series/<sid>/discontinue", methods=["POST"])
def discontinue_series(sid):
    authenticate()
    require_role({"Clerk", "Manager"})
    s = get_entity(db.comic_series, sid)
    s["status"] = "DISCONTINUED"
    touch(s)
    return ok(serialize(s), "object", 200)


# ==========================================================================
# COMIC ISSUES
# ==========================================================================
@app.route("/api/comic-issues", methods=["POST"])
def create_issue():
    authenticate()
    require_role({"Clerk", "Manager"})
    d = body()
    series_id = req_str(d, "series_id")
    get_entity(db.comic_series, series_id)
    issue_number = req_str(d, "issue_number")
    cover_price = req_int(d, "cover_price_cents", minimum=0)
    on_sale = req_dt(d, "on_sale_date")
    cutoff = req_dt(d, "order_cutoff_date")
    copies_ordered = opt_int(d, "copies_ordered", 0, minimum=0)
    e = base_common()
    e.update({
        "series_id": series_id,
        "issue_number": issue_number,
        "cover_price_cents": cover_price,
        "on_sale_date": fmt_ts(on_sale),
        "order_cutoff_date": fmt_ts(cutoff),
        "copies_ordered": copies_ordered,
        "copies_reserved": 0,
        "copies_allocated": 0,
        "copies_available": copies_ordered,
        "status": "SOLICITED",
        "_allocation_ran": False,
    })
    db.comic_issues[e["id"]] = e
    return ok(serialize(e), "object", 201)


@app.route("/api/comic-issues/<iid>", methods=["GET"])
def get_issue(iid):
    authenticate()
    require_role(ROLES)
    return get_response(db.comic_issues, iid)


@app.route("/api/comic-issues", methods=["GET"])
def list_issues():
    authenticate()
    require_role(ROLES)
    return list_response(db.comic_issues, filters={"series_id": "series_id", "status": "status"})


def candidates_for_issue(issue_id, statuses):
    return [r for r in db.reservations.values()
            if r["issue_id"] == issue_id and r["status"] in statuses]


def promote_earliest_waitlisted(issue):
    """Promote the earliest-created WAITLISTED reservation on this issue if copies available."""
    if issue["copies_available"] < 1:
        return
    waitlisted = candidates_for_issue(issue["id"], {"WAITLISTED"})
    if not waitlisted:
        return
    waitlisted.sort(key=lambda r: r["_seq"])
    r = waitlisted[0]
    cust = db.customers.get(r["customer_id"])
    cap = TIER_MAX[cust["loyalty_tier"]] if cust else 1
    grant = min(r["requested_qty"], issue["copies_available"], cap)
    if grant >= 1:
        r["allocated_qty"] = grant
        r["status"] = "ALLOCATED"
        issue["copies_allocated"] += grant
        recompute_available(issue)
        touch(r)


@app.route("/api/comic-issues/<iid>/transition", methods=["POST"])
def transition_issue(iid):
    authenticate()
    require_role({"Clerk", "Manager"})
    issue = get_entity(db.comic_issues, iid)
    d = body()
    to_status = req_str(d, "to_status")
    cur = issue["status"]
    if cur == "SOLICITED" and to_status == "ORDERED":
        series = db.comic_series.get(issue["series_id"])
        if series and series["status"] != "ACTIVE":
            raise err("ERR_SERIES_DISCONTINUED", "Series is discontinued")
        issue["status"] = "ORDERED"
    elif cur == "ORDERED" and to_status == "ON_SALE":
        issue["status"] = "ON_SALE"
    elif cur == "ON_SALE" and to_status == "CLOSED":
        issue["status"] = "CLOSED"
        for r in candidates_for_issue(iid, {"RESERVED", "WAITLISTED", "ALLOCATED"}):
            r["status"] = "EXPIRED"
            issue["copies_reserved"] -= r["requested_qty"]
            if r["allocated_qty"] > 0:
                issue["copies_allocated"] -= r["allocated_qty"]
            touch(r)
        recompute_available(issue)
    else:
        raise err("ERR_INVALID_STATE", f"Cannot transition issue from {cur} to {to_status}")
    touch(issue)
    return ok(serialize(issue), "object", 200)


@app.route("/api/comic-issues/<iid>/run-allocation", methods=["POST"])
def run_allocation(iid):
    authenticate()
    require_role({"Clerk", "Manager"})
    issue = get_entity(db.comic_issues, iid)
    if issue["status"] != "ON_SALE":
        raise err("ERR_ISSUE_NOT_ON_SALE", "Allocation requires issue to be ON_SALE")
    reserved = candidates_for_issue(iid, {"RESERVED"})
    if not reserved and issue["_allocation_ran"]:
        raise err("ERR_ALLOCATION_ALREADY_RUN", "Allocation already run and no reservations remain")

    def sort_key(r):
        cust = db.customers.get(r["customer_id"])
        rank = TIER_RANK[cust["loyalty_tier"]] if cust else 1
        return (-rank, r["_seq"])

    reserved.sort(key=sort_key)
    remaining = issue["copies_available"]
    for r in reserved:
        cust = db.customers.get(r["customer_id"])
        cap = TIER_MAX[cust["loyalty_tier"]] if cust else 1
        grant = min(r["requested_qty"], remaining, cap)
        if grant >= 1:
            r["allocated_qty"] = grant
            r["status"] = "ALLOCATED"
            issue["copies_allocated"] += grant
            remaining -= grant
        else:
            r["status"] = "WAITLISTED"
        touch(r)
    recompute_available(issue)
    issue["_allocation_ran"] = True
    touch(issue)
    return ok(serialize(issue), "object", 200)


# ==========================================================================
# PULL SUBSCRIPTIONS
# ==========================================================================
@app.route("/api/pull-subscriptions", methods=["POST"])
def create_subscription():
    authenticate()
    require_role(ROLES)
    d = body()
    customer_id = d.get("customer_id")
    if g.role == "Customer" and customer_id is not None and customer_id != g.user_id:
        raise err("ERR_UNAUTHORIZED", "Customer may only act on own resources")
    customer_id = req_str(d, "customer_id")
    get_entity(db.customers, customer_id)
    series_id = req_str(d, "series_id")
    get_entity(db.comic_series, series_id)
    e = base_common()
    e.update({"customer_id": customer_id, "series_id": series_id, "status": "ACTIVE"})
    db.pull_subscriptions[e["id"]] = e
    return ok(serialize(e), "object", 201)


@app.route("/api/pull-subscriptions/<sid>", methods=["GET"])
def get_subscription(sid):
    authenticate()
    require_role(ROLES)
    return get_response(db.pull_subscriptions, sid, owner_field="customer_id")


@app.route("/api/pull-subscriptions", methods=["GET"])
def list_subscriptions():
    authenticate()
    require_role(ROLES)
    return list_response(
        db.pull_subscriptions,
        owner_field="customer_id",
        filters={"customer_id": "customer_id", "series_id": "series_id", "status": "status"},
    )


def cascade_subscription_cancel(sub):
    affected_issues = {}
    linked = [r for r in db.reservations.values()
              if r["subscription_id"] == sub["id"] and r["status"] in {"RESERVED", "WAITLISTED", "ALLOCATED"}]
    for r in linked:
        r["status"] = "RELEASED"
        issue = db.comic_issues.get(r["issue_id"])
        if issue:
            issue["copies_reserved"] -= r["requested_qty"]
            if r["allocated_qty"] > 0:
                issue["copies_allocated"] -= r["allocated_qty"]
            recompute_available(issue)
            affected_issues[issue["id"]] = issue
        touch(r)
    for issue in affected_issues.values():
        if issue["copies_available"] > 0:
            promote_earliest_waitlisted(issue)
        touch(issue)


@app.route("/api/pull-subscriptions/<sid>/transition", methods=["POST"])
def transition_subscription(sid):
    authenticate()
    require_role(ROLES)
    sub = get_entity(db.pull_subscriptions, sid)
    d = body()
    to_status = req_str(d, "to_status")
    if g.role == "Customer" and sub["customer_id"] != g.user_id:
        raise err("ERR_UNAUTHORIZED", "Customer may only act on own resources")
    cur = sub["status"]
    valid = (
        (cur == "ACTIVE" and to_status == "PAUSED")
        or (cur == "PAUSED" and to_status == "ACTIVE")
        or (cur in {"ACTIVE", "PAUSED"} and to_status == "CANCELLED")
    )
    if not valid:
        raise err("ERR_INVALID_STATE", f"Cannot transition subscription from {cur} to {to_status}")
    sub["status"] = to_status
    if to_status == "CANCELLED":
        cascade_subscription_cancel(sub)
    touch(sub)
    return ok(serialize(sub), "object", 200)


# ==========================================================================
# RESERVATIONS
# ==========================================================================
@app.route("/api/reservations", methods=["POST"])
def create_reservation():
    authenticate()
    require_role(ROLES)
    d = body()
    customer_id = d.get("customer_id")
    if g.role == "Customer" and customer_id is not None and customer_id != g.user_id:
        raise err("ERR_UNAUTHORIZED", "Customer may only act on own resources")
    # Existence (left to right): customer_id, issue_id, subscription_id
    customer_id = req_str(d, "customer_id")
    get_entity(db.customers, customer_id)
    issue_id = req_str(d, "issue_id")
    issue = get_entity(db.comic_issues, issue_id)
    subscription_id = d.get("subscription_id")
    if subscription_id is not None:
        get_entity(db.pull_subscriptions, subscription_id)
    # Well-formedness
    requested_qty = opt_int(d, "requested_qty", 1, minimum=1)
    if "expected_comic_issue_version" not in d or d.get("expected_comic_issue_version") is None:
        v_error("'expected_comic_issue_version' is required")
    expected = d.get("expected_comic_issue_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        v_error("'expected_comic_issue_version' must be an integer")
    # OCC (last)
    if expected != issue["version"]:
        raise err("ERR_STALE_VERSION", "ComicIssue version mismatch")
    e = base_common()
    e.update({
        "customer_id": customer_id,
        "issue_id": issue_id,
        "subscription_id": subscription_id,
        "requested_qty": requested_qty,
        "allocated_qty": 0,
        "unit_price_cents": 0,
        "status": "RESERVED",
    })
    db.reservations[e["id"]] = e
    issue["copies_reserved"] += requested_qty
    touch(issue)
    return ok(serialize(e), "object", 201)


@app.route("/api/reservations/<rid>", methods=["GET"])
def get_reservation(rid):
    authenticate()
    require_role(ROLES)
    return get_response(db.reservations, rid, owner_field="customer_id")


@app.route("/api/reservations", methods=["GET"])
def list_reservations():
    authenticate()
    require_role(ROLES)
    return list_response(
        db.reservations,
        owner_field="customer_id",
        filters={"customer_id": "customer_id", "issue_id": "issue_id",
                 "subscription_id": "subscription_id", "status": "status"},
    )


@app.route("/api/reservations/<rid>/transition", methods=["POST"])
def transition_reservation(rid):
    authenticate()
    require_role(ROLES)
    r = get_entity(db.reservations, rid)
    d = body()
    to_status = req_str(d, "to_status")
    # Actor RBAC: RELEASED is a Customer action; PULLED/SOLD are Clerk actions.
    if g.role == "Customer":
        if to_status != "RELEASED":
            raise err("ERR_UNAUTHORIZED", "Customers may only release reservations")
        if r["customer_id"] != g.user_id:
            raise err("ERR_UNAUTHORIZED", "Customer may only act on own resources")
    issue = db.comic_issues.get(r["issue_id"])
    cur = r["status"]
    if to_status == "RELEASED" and cur in {"RESERVED", "WAITLISTED"}:
        r["status"] = "RELEASED"
        if issue:
            issue["copies_reserved"] -= r["requested_qty"]
            recompute_available(issue)
            touch(issue)
    elif to_status == "RELEASED" and cur == "ALLOCATED":
        if issue:
            if issue["copies_allocated"] - r["allocated_qty"] < 0:
                raise err("ERR_NEGATIVE_INVENTORY", "Release would drive inventory negative")
            r["status"] = "RELEASED"
            issue["copies_reserved"] -= r["requested_qty"]
            issue["copies_allocated"] -= r["allocated_qty"]
            recompute_available(issue)
            promote_earliest_waitlisted(issue)
            touch(issue)
        else:
            r["status"] = "RELEASED"
    elif to_status == "PULLED" and cur == "ALLOCATED":
        if not issue or issue["status"] != "ON_SALE":
            raise err("ERR_ISSUE_NOT_ON_SALE", "Pull requires issue to be ON_SALE")
        r["status"] = "PULLED"
    elif to_status == "SOLD" and cur == "PULLED":
        r["status"] = "SOLD"
        if issue:
            r["unit_price_cents"] = issue["cover_price_cents"]
    else:
        raise err("ERR_INVALID_STATE", f"Cannot transition reservation from {cur} to {to_status}")
    touch(r)
    return ok(serialize(r), "object", 200)


# ==========================================================================
# PRE-ORDERS
# ==========================================================================
@app.route("/api/pre-orders", methods=["POST"])
def create_preorder():
    authenticate()
    require_role(ROLES)
    d = body()
    customer_id = d.get("customer_id")
    if g.role == "Customer" and customer_id is not None and customer_id != g.user_id:
        raise err("ERR_UNAUTHORIZED", "Customer may only act on own resources")
    customer_id = req_str(d, "customer_id")
    get_entity(db.customers, customer_id)
    issue_id = req_str(d, "issue_id")
    issue = get_entity(db.comic_issues, issue_id)
    quantity = opt_int(d, "quantity", 1, minimum=1)
    e = base_common()
    e.update({
        "customer_id": customer_id,
        "issue_id": issue_id,
        "quantity": quantity,
        "estimated_total_cents": quantity * issue["cover_price_cents"],
        "status": "PENDING",
    })
    db.pre_orders[e["id"]] = e
    return ok(serialize(e), "object", 201)


@app.route("/api/pre-orders/<pid>", methods=["GET"])
def get_preorder(pid):
    authenticate()
    require_role(ROLES)
    return get_response(db.pre_orders, pid, owner_field="customer_id")


@app.route("/api/pre-orders", methods=["GET"])
def list_preorders():
    authenticate()
    require_role(ROLES)
    return list_response(
        db.pre_orders,
        owner_field="customer_id",
        filters={"customer_id": "customer_id", "issue_id": "issue_id", "status": "status"},
    )


@app.route("/api/pre-orders/<pid>/transition", methods=["POST"])
def transition_preorder(pid):
    authenticate()
    require_role(ROLES)
    po = get_entity(db.pre_orders, pid)
    d = body()
    to_status = req_str(d, "to_status")
    # Actor RBAC: CANCELLED is Customer; CONFIRMED/FULFILLED are Clerk.
    if g.role == "Customer":
        if to_status != "CANCELLED":
            raise err("ERR_UNAUTHORIZED", "Customers may only cancel pre-orders")
        if po["customer_id"] != g.user_id:
            raise err("ERR_UNAUTHORIZED", "Customer may only act on own resources")
    issue = db.comic_issues.get(po["issue_id"])
    cur = po["status"]
    customer = db.customers.get(po["customer_id"])
    if cur == "PENDING" and to_status == "CONFIRMED":
        # temporal (before cutoff) then referential (issue state)
        cutoff = parse_ts(issue["order_cutoff_date"]) if issue else None
        if cutoff is not None and not (db.clock < cutoff):
            raise err("ERR_PAST_CUTOFF", "Order cutoff has passed")
        if issue and issue["status"] not in {"SOLICITED", "ORDERED"}:
            raise err("ERR_ISSUE_ALREADY_ON_SALE", "Issue already on sale or closed")
        po["status"] = "CONFIRMED"
        touch(po)
        if customer and recompute_tier(customer):
            touch(customer)
    elif cur == "CONFIRMED" and to_status == "FULFILLED":
        if not issue or issue["status"] != "ON_SALE":
            raise err("ERR_ISSUE_NOT_ON_SALE", "Fulfillment requires issue ON_SALE")
        po["status"] = "FULFILLED"
        touch(po)
    elif cur in {"PENDING", "CONFIRMED"} and to_status == "CANCELLED":
        po["status"] = "CANCELLED"
        touch(po)
        if customer and recompute_tier(customer):
            touch(customer)
    else:
        raise err("ERR_INVALID_STATE", f"Cannot transition pre-order from {cur} to {to_status}")
    return ok(serialize(po), "object", 200)


# ==========================================================================
# BACK-ISSUES
# ==========================================================================
@app.route("/api/back-issues", methods=["POST"])
def create_backissue():
    authenticate()
    require_role({"Clerk", "Manager"})
    d = body()
    series_id = req_str(d, "series_id")
    get_entity(db.comic_series, series_id)
    issue_number = req_str(d, "issue_number")
    condition = req_str(d, "condition")
    if condition not in {"RAW", "GRADED"}:
        v_error("condition must be RAW or GRADED")
    grade_value = d.get("grade_value")
    if grade_value is not None and not isinstance(grade_value, (int, float)) or isinstance(grade_value, bool):
        if grade_value is not None:
            v_error("grade_value must be a number")
    price_cents = req_int(d, "price_cents", minimum=0)
    e = base_common()
    e.update({
        "series_id": series_id,
        "issue_number": issue_number,
        "condition": condition,
        "grade_value": grade_value,
        "price_cents": price_cents,
        "status": "IN_STOCK",
    })
    db.back_issues[e["id"]] = e
    return ok(serialize(e), "object", 201)


@app.route("/api/back-issues/<bid>", methods=["GET"])
def get_backissue(bid):
    authenticate()
    require_role(ROLES)
    return get_response(db.back_issues, bid)


@app.route("/api/back-issues", methods=["GET"])
def list_backissues():
    authenticate()
    require_role(ROLES)
    return list_response(
        db.back_issues,
        filters={"series_id": "series_id", "status": "status", "condition": "condition"},
    )


@app.route("/api/back-issues/<bid>/transition", methods=["POST"])
def transition_backissue(bid):
    authenticate()
    require_role({"Clerk", "Manager"})
    b = get_entity(db.back_issues, bid)
    d = body()
    to_status = req_str(d, "to_status")
    cur = b["status"]
    valid = (
        (cur == "IN_STOCK" and to_status == "RESERVED")
        or (cur == "RESERVED" and to_status == "IN_STOCK")
        or (cur in {"IN_STOCK", "RESERVED"} and to_status == "SOLD")
    )
    if not valid:
        raise err("ERR_INVALID_STATE", f"Cannot transition back-issue from {cur} to {to_status}")
    b["status"] = to_status
    touch(b)
    return ok(serialize(b), "object", 200)


# ==========================================================================
# GRADING SUBMISSIONS
# ==========================================================================
@app.route("/api/grading-submissions", methods=["POST"])
def create_grading():
    authenticate()
    require_role(ROLES)
    d = body()
    customer_id = d.get("customer_id")
    if g.role == "Customer" and customer_id is not None and customer_id != g.user_id:
        raise err("ERR_UNAUTHORIZED", "Customer may only act on own resources")
    customer_id = req_str(d, "customer_id")
    get_entity(db.customers, customer_id)
    description = req_str(d, "description")
    declared_value = req_int(d, "declared_value_cents", minimum=0)
    e = base_common()
    e.update({
        "customer_id": customer_id,
        "description": description,
        "declared_value_cents": declared_value,
        "grade_result": None,
        "dispute_count": 0,
        "status": "INTAKE",
    })
    db.grading_submissions[e["id"]] = e
    return ok(serialize(e), "object", 201)


@app.route("/api/grading-submissions/<gid>", methods=["GET"])
def get_grading(gid):
    authenticate()
    require_role(ROLES)
    return get_response(db.grading_submissions, gid, owner_field="customer_id")


@app.route("/api/grading-submissions", methods=["GET"])
def list_grading():
    authenticate()
    require_role(ROLES)
    return list_response(
        db.grading_submissions,
        owner_field="customer_id",
        filters={"customer_id": "customer_id", "status": "status"},
    )


@app.route("/api/grading-submissions/<gid>/transition", methods=["POST"])
def transition_grading(gid):
    authenticate()
    require_role(ROLES)
    sub = get_entity(db.grading_submissions, gid)
    d = body()
    to_status = req_str(d, "to_status")
    cur = sub["status"]
    # Actor RBAC: only the dispute (RETURNED -> AT_GRADER) is a Customer action.
    if g.role == "Customer":
        if not (to_status == "AT_GRADER" and cur == "RETURNED"):
            raise err("ERR_UNAUTHORIZED", "Customers may only dispute a returned grade")
        if sub["customer_id"] != g.user_id:
            raise err("ERR_UNAUTHORIZED", "Customer may only act on own resources")
    customer = db.customers.get(sub["customer_id"])
    if cur == "INTAKE" and to_status == "SUBMITTED":
        if customer and customer["status"] != "ACTIVE":
            raise err("ERR_CUSTOMER_BANNED", "Customer is banned")
        sub["status"] = "SUBMITTED"
    elif cur == "SUBMITTED" and to_status == "AT_GRADER":
        sub["status"] = "AT_GRADER"
    elif cur == "AT_GRADER" and to_status == "RETURNED":
        grade = d.get("grade_result")
        if grade is None or isinstance(grade, bool) or not isinstance(grade, (int, float)):
            v_error("'grade_result' is required and must be a number")
        sub["grade_result"] = grade
        sub["status"] = "RETURNED"
    elif cur == "RETURNED" and to_status == "AT_GRADER":
        if sub["dispute_count"] >= DISPUTE_LIMIT:
            raise err("ERR_DISPUTE_LIMIT_REACHED", "Dispute limit reached")
        sub["dispute_count"] += 1
        sub["status"] = "AT_GRADER"
    elif cur == "RETURNED" and to_status == "READY_FOR_PICKUP":
        sub["status"] = "READY_FOR_PICKUP"
    elif cur == "READY_FOR_PICKUP" and to_status == "PICKED_UP":
        sub["status"] = "PICKED_UP"
    else:
        raise err("ERR_INVALID_STATE", f"Cannot transition grading from {cur} to {to_status}")
    touch(sub)
    return ok(serialize(sub), "object", 200)


# ==========================================================================
# EVENTS
# ==========================================================================
@app.route("/api/events", methods=["POST"])
def create_event():
    authenticate()
    require_role({"Clerk", "Manager"})
    d = body()
    name = req_str(d, "name")
    store_location = req_str(d, "store_location")
    starts_at = req_dt(d, "starts_at")
    ends_at = req_dt(d, "ends_at")
    if not (ends_at > starts_at):
        v_error("ends_at must be strictly after starts_at")
    capacity = req_int(d, "capacity", minimum=0)
    # time overlap on same store_location, non-cancelled events, half-open
    for ev in db.events.values():
        if ev["store_location"] == store_location and ev["status"] != "CANCELLED":
            es = parse_ts(ev["starts_at"])
            ee = parse_ts(ev["ends_at"])
            if starts_at < ee and es < ends_at:
                raise err("ERR_EVENT_TIME_CONFLICT", "Event overlaps another at same location")
    e = base_common()
    e.update({
        "name": name,
        "store_location": store_location,
        "starts_at": fmt_ts(starts_at),
        "ends_at": fmt_ts(ends_at),
        "capacity": capacity,
        "registered_count": 0,
        "status": "DRAFT",
    })
    db.events[e["id"]] = e
    return ok(serialize(e), "object", 201)


@app.route("/api/events/<eid>", methods=["GET"])
def get_event(eid):
    authenticate()
    require_role(ROLES)
    return get_response(db.events, eid)


@app.route("/api/events", methods=["GET"])
def list_events():
    authenticate()
    require_role(ROLES)
    return list_response(db.events, filters={"status": "status", "store_location": "store_location"})


@app.route("/api/events/<eid>/transition", methods=["POST"])
def transition_event(eid):
    authenticate()
    require_role({"Clerk", "Manager"})
    ev = get_entity(db.events, eid)
    d = body()
    to_status = req_str(d, "to_status")
    cur = ev["status"]
    if cur == "DRAFT" and to_status == "OPEN":
        ev["status"] = "OPEN"
    elif cur == "OPEN" and to_status == "CLOSED":
        ev["status"] = "CLOSED"
    elif cur == "CLOSED" and to_status == "COMPLETED":
        ev["status"] = "COMPLETED"
        for reg in db.event_registrations.values():
            if reg["event_id"] == eid and reg["status"] == "REGISTERED":
                reg["status"] = "NO_SHOW"
                ev["registered_count"] -= 1
                touch(reg)
    elif cur == "OPEN" and to_status == "CANCELLED":
        ev["status"] = "CANCELLED"
        for reg in db.event_registrations.values():
            if reg["event_id"] == eid and reg["status"] in {"REGISTERED", "CHECKED_IN"}:
                reg["status"] = "CANCELLED"
                touch(reg)
        ev["registered_count"] = 0
    elif cur == "DRAFT" and to_status == "CANCELLED":
        ev["status"] = "CANCELLED"
    else:
        raise err("ERR_INVALID_STATE", f"Cannot transition event from {cur} to {to_status}")
    touch(ev)
    return ok(serialize(ev), "object", 200)


# ==========================================================================
# EVENT REGISTRATIONS
# ==========================================================================
@app.route("/api/event-registrations", methods=["POST"])
def create_registration():
    authenticate()
    require_role(ROLES)
    d = body()
    customer_id = d.get("customer_id")
    if g.role == "Customer" and customer_id is not None and customer_id != g.user_id:
        raise err("ERR_UNAUTHORIZED", "Customer may only act on own resources")
    customer_id = req_str(d, "customer_id")
    get_entity(db.customers, customer_id)
    event_id = req_str(d, "event_id")
    ev = get_entity(db.events, event_id)
    # temporal: before starts_at
    starts_at = parse_ts(ev["starts_at"])
    if starts_at is not None and not (db.clock < starts_at):
        raise err("ERR_EVENT_ALREADY_STARTED", "Event has already started")
    # referential: event OPEN
    if ev["status"] != "OPEN":
        raise err("ERR_EVENT_CLOSED", "Event is not open for registration")
    # duplicate
    for reg in db.event_registrations.values():
        if reg["event_id"] == event_id and reg["customer_id"] == customer_id \
                and reg["status"] in {"REGISTERED", "CHECKED_IN"}:
            raise err("ERR_DUPLICATE_REGISTRATION", "Customer already registered for this event")
    # capacity
    if ev["registered_count"] >= ev["capacity"]:
        raise err("ERR_EVENT_FULL", "Event is full")
    # registration time conflict (30-min buffer each side)
    ev_start = parse_ts(ev["starts_at"])
    ev_end = parse_ts(ev["ends_at"])
    buf = timedelta(minutes=30)
    for reg in db.event_registrations.values():
        if reg["customer_id"] == customer_id and reg["status"] in {"REGISTERED", "CHECKED_IN"}:
            other = db.events.get(reg["event_id"])
            if not other:
                continue
            os_ = parse_ts(other["starts_at"]) - buf
            oe_ = parse_ts(other["ends_at"]) + buf
            if ev_start < oe_ and os_ < ev_end:
                raise err("ERR_REGISTRATION_TIME_CONFLICT", "Overlaps another registration")
    e = base_common()
    e.update({"customer_id": customer_id, "event_id": event_id, "status": "REGISTERED"})
    db.event_registrations[e["id"]] = e
    ev["registered_count"] += 1
    touch(ev)
    return ok(serialize(e), "object", 201)


@app.route("/api/event-registrations/<rid>", methods=["GET"])
def get_registration(rid):
    authenticate()
    require_role(ROLES)
    return get_response(db.event_registrations, rid, owner_field="customer_id")


@app.route("/api/event-registrations", methods=["GET"])
def list_registrations():
    authenticate()
    require_role(ROLES)
    return list_response(
        db.event_registrations,
        owner_field="customer_id",
        filters={"customer_id": "customer_id", "event_id": "event_id", "status": "status"},
    )


@app.route("/api/event-registrations/<rid>/transition", methods=["POST"])
def transition_registration(rid):
    authenticate()
    require_role(ROLES)
    reg = get_entity(db.event_registrations, rid)
    d = body()
    to_status = req_str(d, "to_status")
    # Actor RBAC: CANCELLED is Customer; CHECKED_IN/NO_SHOW are Clerk.
    if g.role == "Customer":
        if to_status != "CANCELLED":
            raise err("ERR_UNAUTHORIZED", "Customers may only cancel their registration")
        if reg["customer_id"] != g.user_id:
            raise err("ERR_UNAUTHORIZED", "Customer may only act on own resources")
    ev = db.events.get(reg["event_id"])
    cur = reg["status"]
    if cur == "REGISTERED" and to_status == "CHECKED_IN":
        if not ev or ev["status"] != "OPEN":
            raise err("ERR_EVENT_CLOSED", "Event is not open")
        reg["status"] = "CHECKED_IN"
    elif cur == "REGISTERED" and to_status == "CANCELLED":
        reg["status"] = "CANCELLED"
        if ev:
            ev["registered_count"] -= 1
            touch(ev)
    elif cur == "CHECKED_IN" and to_status == "NO_SHOW":
        reg["status"] = "NO_SHOW"
        if ev:
            ev["registered_count"] -= 1
            touch(ev)
    else:
        raise err("ERR_INVALID_STATE", f"Cannot transition registration from {cur} to {to_status}")
    touch(reg)
    return ok(serialize(reg), "object", 200)


# ==========================================================================
# CONSIGNMENTS
# ==========================================================================
@app.route("/api/consignments", methods=["POST"])
def create_consignment():
    authenticate()
    require_role(ROLES)
    d = body()
    consignor_id = d.get("consignor_id")
    if g.role == "Customer" and consignor_id is not None and consignor_id != g.user_id:
        raise err("ERR_UNAUTHORIZED", "Customer may only consign own items")
    consignor_id = req_str(d, "consignor_id")
    get_entity(db.customers, consignor_id)
    description = req_str(d, "description")
    asking_price = req_int(d, "asking_price_cents", minimum=0)
    commission_pct = d.get("commission_pct", 0.30)
    if commission_pct is None:
        commission_pct = 0.30
    if not isinstance(commission_pct, (int, float)) or isinstance(commission_pct, bool):
        v_error("commission_pct must be a number")
    if not (commission_pct >= 0 and commission_pct < 1):
        v_error("commission_pct must be in [0, 1)")
    e = base_common()
    e.update({
        "consignor_id": consignor_id,
        "description": description,
        "asking_price_cents": asking_price,
        "commission_pct": commission_pct,
        "sale_price_cents": None,
        "provisional_payout_cents": None,
        "final_payout_cents": None,
        "status": "RECEIVED",
    })
    db.consignments[e["id"]] = e
    return ok(serialize(e), "object", 201)


@app.route("/api/consignments/<cid>", methods=["GET"])
def get_consignment(cid):
    authenticate()
    require_role(ROLES)
    return get_response(db.consignments, cid, owner_field="consignor_id")


@app.route("/api/consignments", methods=["GET"])
def list_consignments():
    authenticate()
    require_role(ROLES)
    return list_response(
        db.consignments,
        owner_field="consignor_id",
        filters={"consignor_id": "consignor_id", "status": "status"},
    )


@app.route("/api/consignments/<cid>/transition", methods=["POST"])
def transition_consignment(cid):
    authenticate()
    require_role({"Clerk", "Manager"})
    con = get_entity(db.consignments, cid)
    d = body()
    to_status = req_str(d, "to_status")
    cur = con["status"]
    consignor = db.customers.get(con["consignor_id"])
    commission = Decimal(str(con["commission_pct"]))
    if cur == "RECEIVED" and to_status == "LISTED":
        if consignor and consignor["status"] != "ACTIVE":
            raise err("ERR_CUSTOMER_BANNED", "Consignor is banned")
        con["provisional_payout_cents"] = round_half_up(
            Decimal(con["asking_price_cents"]) * (Decimal(1) - commission)
        )
        con["status"] = "LISTED"
    elif cur == "LISTED" and to_status == "SOLD":
        sale_price = d.get("sale_price_cents")
        if sale_price is None:
            raise err("ERR_SALE_PRICE_REQUIRED", "sale_price_cents is required")
        if not isinstance(sale_price, int) or isinstance(sale_price, bool) or sale_price < 0:
            v_error("sale_price_cents must be a non-negative integer")
        con["sale_price_cents"] = sale_price
        con["final_payout_cents"] = round_half_up(
            Decimal(sale_price) * (Decimal(1) - commission)
        )
        con["status"] = "SOLD"
    elif cur == "LISTED" and to_status == "RETURNED_TO_CONSIGNOR":
        con["status"] = "RETURNED_TO_CONSIGNOR"
    elif cur == "SOLD" and to_status == "PAID_OUT":
        if g.role != "Manager":
            raise err("ERR_UNAUTHORIZED", "Only a Manager may pay out a consignment")
        con["status"] = "PAID_OUT"
        payout = con["final_payout_cents"] or 0
        if consignor:
            consignor["store_credit_cents"] += payout
            txn = base_common(common=False)
            txn.update({
                "customer_id": consignor["id"],
                "amount_cents": payout,
                "reason": "CONSIGNMENT_PAYOUT",
                "balance_after_cents": consignor["store_credit_cents"],
            })
            db.credit_transactions[txn["id"]] = txn
            recompute_tier(consignor)
            touch(consignor)
    else:
        raise err("ERR_INVALID_STATE", f"Cannot transition consignment from {cur} to {to_status}")
    touch(con)
    return ok(serialize(con), "object", 200)


# ==========================================================================
# CHECKOUT
# ==========================================================================
@app.route("/api/checkout", methods=["POST"])
def checkout():
    authenticate()
    require_role({"Clerk", "Manager"})
    d = body()
    customer_id = req_str(d, "customer_id")
    customer = get_entity(db.customers, customer_id)
    line_items = d.get("line_items")
    if not isinstance(line_items, list) or len(line_items) == 0:
        v_error("line_items must be a non-empty array")
    parsed = []
    for li in line_items:
        if not isinstance(li, dict):
            v_error("each line item must be an object")
        up = li.get("unit_price_cents")
        qty = li.get("quantity")
        if not isinstance(up, int) or isinstance(up, bool) or up < 0:
            v_error("unit_price_cents must be a non-negative integer")
        if not isinstance(qty, int) or isinstance(qty, bool) or qty < 1:
            v_error("quantity must be an integer >= 1")
        parsed.append((up, qty))
    pay_credit_only = bool(d.get("pay_with_store_credit_only", False))

    amount_due = sum(up * qty for up, qty in parsed)
    if pay_credit_only and customer["store_credit_cents"] < amount_due:
        raise err("ERR_INSUFFICIENT_STORE_CREDIT", "Insufficient store credit")
    store_credit_applied = min(customer["store_credit_cents"], amount_due)
    charge = amount_due - store_credit_applied

    # loyalty points: floor per line, then sum
    mult = Decimal(TIER_MULT[customer["loyalty_tier"]])
    points = 0
    for up, qty in parsed:
        line_total = up * qty
        val = (Decimal(line_total) / Decimal(100)) * mult
        points += int(val.to_integral_value(rounding=ROUND_FLOOR))

    # commit
    customer["store_credit_cents"] -= store_credit_applied
    if store_credit_applied > 0:
        txn = base_common(common=False)
        txn.update({
            "customer_id": customer["id"],
            "amount_cents": -store_credit_applied,
            "reason": "REDEMPTION",
            "balance_after_cents": customer["store_credit_cents"],
        })
        db.credit_transactions[txn["id"]] = txn
    customer["lifetime_spend_cents"] += amount_due
    customer["loyalty_points_balance"] += points
    recompute_tier(customer)
    touch(customer)

    return ok({
        "amount_due_cents": amount_due,
        "store_credit_applied_cents": store_credit_applied,
        "charge_cents": charge,
        "loyalty_points_earned": points,
    }, "object", 200)


# ==========================================================================
# LOGICAL CLOCK
# ==========================================================================
@app.route("/api/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authenticate()
    require_role({"Clerk", "Manager"})
    d = body()
    raw = d.get("to_iso8601")
    if not isinstance(raw, str):
        v_error("'to_iso8601' is required")
    dt = parse_ts(raw)
    if dt is None:
        v_error("'to_iso8601' must be a valid ISO 8601 datetime")
    db.clock = dt
    return ok({"current_utc": fmt_ts(dt)}, "object", 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
