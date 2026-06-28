"""Cabinet Refacing & Kitchen Refresh API — Flask entry point.

In-memory only. Store starts empty on every boot (no seeding). The logical
clock defaults to 2026-04-01T00:00:00Z.
"""
import os

from flask import Flask, request

import calculations as calc
from clock import parse_iso8601, format_iso8601_ms, add_days
from db import store, common_fields, touch
from errors import ApiError, err
from helpers import (
    get_json_body, parse_pagination, paginate, require_fields, require_str,
    require_int, require_number, require_enum, optional_bool, optional_int,
    MISSING,
)
from middleware import require_auth, require_role
from response import object_response, array_response, error_response
import services as svc
from services import (
    view, get_or_404, expire_quote_if_due, expire_project_active_quote,
    assert_project_owner,
)

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", "Method not allowed", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return error_response("ERR_INVALID_REQUEST", str(e), 422)


# ===========================================================================
# Logical clock (PlatformAdmin only) — §1.5
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _uid, role = require_auth()
    require_role(role, {"PlatformAdmin"})
    body = get_json_body()
    to_iso = require_str(body, "to_iso8601")
    try:
        dt = parse_iso8601(to_iso)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be a valid ISO 8601 instant")
    store.clock.set(dt)
    return object_response({}, 200)


# ===========================================================================
# Customers — §3.1
# ===========================================================================
@app.route("/customers", methods=["POST"])
def create_customer():
    _uid, role = require_auth()
    require_role(role, {"SalesRep", "PlatformAdmin"})
    body = get_json_body()
    email = require_str(body, "email")
    full_name = require_str(body, "full_name")
    state_code = require_str(body, "state_code")
    annual_income = require_int(body, "annual_income_cents", minimum=0)
    # state_code: two uppercase letters
    if len(state_code) != 2 or not state_code.isalpha() or not state_code.isupper():
        raise err("ERR_INVALID_REQUEST", "state_code must be two uppercase letters")
    # email unique among customers
    for c in store.customers.values():
        if c["email"] == email:
            raise err("ERR_INVALID_REQUEST", "email must be unique")
    cust = common_fields(store)
    cust.update({
        "email": email,
        "full_name": full_name,
        "state_code": state_code,
        "annual_income_cents": annual_income,
    })
    store.customers[cust["id"]] = cust
    return object_response(view(cust, svc.CUSTOMER_FIELDS), 201)


@app.route("/customers/<cid>", methods=["GET"])
def get_customer(cid):
    _uid, role = require_auth()
    require_role(role, {"SalesRep", "PlatformAdmin", "Customer"})
    cust = get_or_404(store.customers, cid)
    return object_response(view(cust, svc.CUSTOMER_FIELDS), 200)


# ===========================================================================
# Projects — §3.1
# ===========================================================================
@app.route("/projects", methods=["POST"])
def create_project():
    _uid, role = require_auth()
    require_role(role, {"SalesRep", "PlatformAdmin"})
    body = get_json_body()
    customer_id = require_str(body, "customer_id")
    address_line = require_str(body, "address_line")
    get_or_404(store.customers, customer_id)  # existence of body-referenced id
    proj = common_fields(store)
    proj.update({
        "customer_id": customer_id,
        "address_line": address_line,
        "status": "LEAD",
        "active_quote_id": None,
        "linear_feet": None,
        "door_count": None,
        "install_completed_at": None,  # internal: warranty anchor (PRD §3.10)
    })
    store.projects[proj["id"]] = proj
    return object_response(view(proj, svc.PROJECT_FIELDS), 201)


@app.route("/projects/<pid>", methods=["GET"])
def get_project(pid):
    _uid, role = require_auth()
    require_role(role, {"SalesRep", "Scheduler", "PlatformAdmin", "Customer"})
    proj = get_or_404(store.projects, pid)
    expire_project_active_quote(proj)
    return object_response(view(proj, svc.PROJECT_FIELDS), 200)


@app.route("/projects", methods=["GET"])
def list_projects():
    _uid, role = require_auth()
    require_role(role, {"SalesRep", "Scheduler", "PlatformAdmin"})
    limit, offset = parse_pagination()
    customer_id = request.args.get("customer_id")
    status = request.args.get("status")
    items = list(store.projects.values())
    if customer_id is not None:
        items = [p for p in items if p["customer_id"] == customer_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, total = paginate(items, limit, offset)
    return array_response([view(p, svc.PROJECT_FIELDS) for p in page],
                          limit, offset, total)


@app.route("/projects/<pid>/cancel", methods=["POST"])
def cancel_project(pid):
    _uid, role = require_auth()
    require_role(role, {"SalesRep", "PlatformAdmin"})
    proj = get_or_404(store.projects, pid)
    if proj["status"] not in ("LEAD", "MEASURED", "QUOTED"):
        raise err("ERR_INVALID_STATE", "Project cannot be cancelled in its current state")
    # cancels all SCHEDULED measures on the project
    for m in store.measures.values():
        if m["project_id"] == pid and m["status"] == "SCHEDULED":
            m["status"] = "CANCELLED"
            touch(store, m)
    # marks any is_active Quote SUPERSEDED
    for q in store.quotes.values():
        if q["project_id"] == pid and q.get("is_active"):
            q["status"] = "SUPERSEDED"
            q["is_active"] = False
            touch(store, q)
    proj["active_quote_id"] = None
    proj["status"] = "CANCELLED"
    touch(store, proj)
    return object_response(view(proj, svc.PROJECT_FIELDS), 200)


@app.route("/projects/<pid>/close", methods=["POST"])
def close_project(pid):
    _uid, role = require_auth()
    require_role(role, {"Scheduler", "PlatformAdmin"})
    proj = get_or_404(store.projects, pid)
    if proj["status"] != "INSTALLED":
        raise err("ERR_INVALID_STATE", "Project must be INSTALLED to close")
    for wc in store.warranty_claims.values():
        if wc["project_id"] == pid and wc["status"] in ("SUBMITTED", "APPROVED"):
            raise err("ERR_INVALID_STATE", "Open warranty claim blocks closing")
    proj["status"] = "CLOSED"
    touch(store, proj)
    return object_response(view(proj, svc.PROJECT_FIELDS), 200)


# ===========================================================================
# Measures — §3.2
# ===========================================================================
@app.route("/projects/<pid>/measures", methods=["POST"])
def create_measure(pid):
    _uid, role = require_auth()
    require_role(role, {"SalesRep", "PlatformAdmin"})
    proj = get_or_404(store.projects, pid)
    body = get_json_body()
    scheduled_for = require_str(body, "scheduled_for")
    try:
        parse_iso8601(scheduled_for)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "scheduled_for must be a valid ISO 8601 instant")
    m = common_fields(store)
    m.update({
        "project_id": pid,
        "scheduled_for": scheduled_for,
        "status": "SCHEDULED",
        "linear_feet": None,
        "door_count": None,
        "door_style": None,
        "finish_code": None,
    })
    store.measures[m["id"]] = m
    return object_response(view(m, svc.MEASURE_FIELDS), 201)


@app.route("/projects/<pid>/measures", methods=["GET"])
def list_measures(pid):
    _uid, role = require_auth()
    require_role(role, {"SalesRep", "Scheduler", "PlatformAdmin", "Customer"})
    get_or_404(store.projects, pid)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = [m for m in store.measures.values() if m["project_id"] == pid]
    if status is not None:
        items = [m for m in items if m["status"] == status]
    page, total = paginate(items, limit, offset)
    return array_response([view(m, svc.MEASURE_FIELDS) for m in page],
                          limit, offset, total)


@app.route("/measures/<mid>", methods=["GET"])
def get_measure(mid):
    _uid, role = require_auth()
    require_role(role, {"SalesRep", "Scheduler", "PlatformAdmin", "Customer"})
    m = get_or_404(store.measures, mid)
    return object_response(view(m, svc.MEASURE_FIELDS), 200)


@app.route("/projects/<pid>/measures/<mid>/complete", methods=["POST"])
def complete_measure(pid, mid):
    _uid, role = require_auth()
    require_role(role, {"SalesRep", "PlatformAdmin"})
    proj = get_or_404(store.projects, pid)        # left-to-right existence
    m = get_or_404(store.measures, mid)
    if m["project_id"] != pid:
        raise err("ERR_NOT_FOUND", "Measure does not belong to project")
    # state transition defined?
    if m["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Measure not in SCHEDULED")
    if proj["status"] not in ("LEAD", "MEASURED"):
        raise err("ERR_INVALID_STATE", "Project not in LEAD or MEASURED")
    body = get_json_body()
    linear_feet = require_number(body, "linear_feet")
    door_count = require_int(body, "door_count")
    door_style = require_str(body, "door_style")
    finish_code = require_enum(body, "finish_code",
                               {"LAMINATE", "THERMOFOIL", "WOOD_VENEER", "SOLID_WOOD", "PAINT"})
    if linear_feet <= 0:
        raise err("ERR_INVALID_REQUEST", "linear_feet must be > 0")
    if door_count < 0:
        raise err("ERR_INVALID_REQUEST", "door_count must be >= 0")
    m["linear_feet"] = linear_feet
    m["door_count"] = door_count
    m["door_style"] = door_style
    m["finish_code"] = finish_code
    m["status"] = "COMPLETED"
    touch(store, m)
    proj["linear_feet"] = linear_feet
    proj["door_count"] = door_count
    if proj["status"] == "LEAD":
        proj["status"] = "MEASURED"
    touch(store, proj)
    return object_response(view(m, svc.MEASURE_FIELDS), 200)


@app.route("/projects/<pid>/measures/<mid>/cancel", methods=["POST"])
def cancel_measure(pid, mid):
    _uid, role = require_auth()
    require_role(role, {"SalesRep", "PlatformAdmin"})
    get_or_404(store.projects, pid)
    m = get_or_404(store.measures, mid)
    if m["project_id"] != pid:
        raise err("ERR_NOT_FOUND", "Measure does not belong to project")
    if m["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Measure not in SCHEDULED")
    m["status"] = "CANCELLED"
    touch(store, m)
    return object_response(view(m, svc.MEASURE_FIELDS), 200)


# ===========================================================================
# Quotes — §3.3, §3.4, §3.5
# ===========================================================================
@app.route("/projects/<pid>/quotes", methods=["POST"])
def create_quote(pid):
    _uid, role = require_auth()
    require_role(role, {"SalesRep", "PlatformAdmin"})
    proj = get_or_404(store.projects, pid)
    body = get_json_body()
    measure_id = require_str(body, "measure_id")
    scope = require_enum(body, "scope", {"PAINT", "REFACE", "REDOOR"})
    measure = get_or_404(store.measures, measure_id)  # body-referenced existence
    # measure must belong to this project (ERR_MEASURE_PROJECT_MISMATCH)
    if measure["project_id"] != pid:
        raise err("ERR_MEASURE_PROJECT_MISMATCH",
                  "Measure does not belong to the project being quoted")
    estimate = calc.provisional_estimate(scope, measure["linear_feet"])
    q = common_fields(store)
    q.update({
        "project_id": pid,
        "measure_id": measure_id,
        "scope": scope,
        "status": "DRAFT",
        "estimate_total_cents": estimate,
        "firm_total_cents": None,
        "addons_total_cents": 0,
        "expires_at": None,
        "is_active": False,
    })
    store.quotes[q["id"]] = q
    return object_response(view(q, svc.QUOTE_FIELDS), 201)


@app.route("/projects/<pid>/quotes", methods=["GET"])
def list_project_quotes(pid):
    _uid, role = require_auth()
    require_role(role, {"SalesRep", "Scheduler", "PlatformAdmin", "Customer"})
    get_or_404(store.projects, pid)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    is_active = request.args.get("is_active")
    items = [q for q in store.quotes.values() if q["project_id"] == pid]
    for q in items:
        expire_quote_if_due(q)
    items = _filter_quotes(items, status, is_active)
    page, total = paginate(items, limit, offset)
    return array_response([view(q, svc.QUOTE_FIELDS) for q in page],
                          limit, offset, total)


@app.route("/quotes", methods=["GET"])
def list_quotes():
    _uid, role = require_auth()
    require_role(role, {"SalesRep", "Scheduler", "PlatformAdmin"})
    limit, offset = parse_pagination()
    measure_id = request.args.get("measure_id")
    project_id = request.args.get("project_id")
    status = request.args.get("status")
    is_active = request.args.get("is_active")
    items = list(store.quotes.values())
    for q in items:
        expire_quote_if_due(q)
    if measure_id is not None:
        items = [q for q in items if q["measure_id"] == measure_id]
    if project_id is not None:
        items = [q for q in items if q["project_id"] == project_id]
    items = _filter_quotes(items, status, is_active)
    page, total = paginate(items, limit, offset)
    return array_response([view(q, svc.QUOTE_FIELDS) for q in page],
                          limit, offset, total)


def _filter_quotes(items, status, is_active):
    if status is not None:
        items = [q for q in items if q["status"] == status]
    if is_active is not None:
        want = is_active.lower() in ("true", "1")
        items = [q for q in items if bool(q["is_active"]) == want]
    return items


@app.route("/quotes/<qid>", methods=["GET"])
def get_quote(qid):
    _uid, role = require_auth()
    require_role(role, {"SalesRep", "Scheduler", "PlatformAdmin", "Customer"})
    q = get_or_404(store.quotes, qid)
    expire_quote_if_due(q)
    return object_response(view(q, svc.QUOTE_FIELDS), 200)


def _recompute_firm_total(quote, measure):
    return calc.firm_quote_total(
        quote["scope"], measure["linear_feet"], measure["door_count"],
        measure["finish_code"], quote["addons_total_cents"],
    )


@app.route("/quotes/<qid>/issue", methods=["POST"])
def issue_quote(qid):
    _uid, role = require_auth()
    require_role(role, {"SalesRep", "PlatformAdmin"})
    q = get_or_404(store.quotes, qid)
    expire_quote_if_due(q)
    measure = store.measures.get(q["measure_id"])
    proj = store.projects.get(q["project_id"])
    if q["status"] not in ("DRAFT", "REVISING"):
        raise err("ERR_INVALID_STATE", "Quote not in DRAFT or REVISING")
    # measure must be COMPLETED (applies to both directions)
    if measure is None or measure["status"] != "COMPLETED":
        raise err("ERR_MEASURE_NOT_COMPLETED", "Linked measure is not COMPLETED")
    if q["status"] == "DRAFT":
        if proj["status"] not in ("MEASURED", "QUOTED"):
            raise err("ERR_INVALID_STATE", "Project not in MEASURED or QUOTED")
    # PRD §3.6: an approved add-on's price_cents is folded into the quote's
    # addons_total_cents the next time the quote is issued.
    q["addons_total_cents"] = sum(
        a["price_cents"] for a in store.addons.values()
        if a["quote_id"] == q["id"] and a["status"] == "APPROVED")
    # compute firm total
    q["firm_total_cents"] = _recompute_firm_total(q, measure)
    q["expires_at"] = format_iso8601_ms(add_days(store.clock.now, calc.QUOTE_VALID_DAYS))
    # supersede prior active quote on the same project
    for other in store.quotes.values():
        if other["id"] != q["id"] and other["project_id"] == q["project_id"] \
                and other.get("is_active"):
            other["status"] = "SUPERSEDED"
            other["is_active"] = False
            touch(store, other)
    q["is_active"] = True
    q["status"] = "QUOTED"
    proj["active_quote_id"] = q["id"]
    if proj["status"] == "MEASURED":
        proj["status"] = "QUOTED"
    touch(store, proj)
    touch(store, q)
    return object_response(view(q, svc.QUOTE_FIELDS), 200)


@app.route("/quotes/<qid>/reopen", methods=["POST"])
def reopen_quote(qid):
    _uid, role = require_auth()
    require_role(role, {"SalesRep", "PlatformAdmin"})
    q = get_or_404(store.quotes, qid)
    expire_quote_if_due(q)
    if q["status"] != "QUOTED" or not q.get("is_active"):
        raise err("ERR_INVALID_STATE", "Quote not in active QUOTED state")
    q["status"] = "REVISING"
    touch(store, q)
    return object_response(view(q, svc.QUOTE_FIELDS), 200)


@app.route("/quotes/<qid>/approve", methods=["POST"])
def approve_quote(qid):
    _uid, role = require_auth()
    require_role(role, {"Customer"})
    q = get_or_404(store.quotes, qid)
    proj = store.projects.get(q["project_id"])
    assert_project_owner(proj, _uid, role)
    body = get_json_body()
    expected_version = require_int(body, "expected_quote_version")
    expire_quote_if_due(q)
    if q["status"] == "EXPIRED":
        raise err("ERR_QUOTE_EXPIRED", "Quote has expired")
    if q["status"] != "QUOTED" or not q.get("is_active"):
        raise err("ERR_INVALID_STATE", "Quote not in active QUOTED state")
    # expiry: now strictly before expires_at
    if store.clock.now >= parse_iso8601(q["expires_at"]):
        raise err("ERR_QUOTE_EXPIRED", "Quote has expired")
    if expected_version != q["version"]:
        raise err("ERR_STALE_QUOTE_VERSION", "expected_quote_version is stale")
    # freeze addons_total_cents at sum of APPROVED addons on this quote
    approved_sum = sum(a["price_cents"] for a in store.addons.values()
                       if a["quote_id"] == q["id"] and a["status"] == "APPROVED")
    q["addons_total_cents"] = approved_sum
    q["status"] = "APPROVED"
    touch(store, q)
    proj["status"] = "SOLD"
    touch(store, proj)
    return object_response(view(q, svc.QUOTE_FIELDS), 200)


@app.route("/quotes/<qid>/decline", methods=["POST"])
def decline_quote(qid):
    _uid, role = require_auth()
    require_role(role, {"Customer"})
    q = get_or_404(store.quotes, qid)
    proj = store.projects.get(q["project_id"])
    assert_project_owner(proj, _uid, role)
    expire_quote_if_due(q)
    if q["status"] != "QUOTED":
        raise err("ERR_INVALID_STATE", "Quote not in QUOTED")
    q["status"] = "DECLINED"
    q["is_active"] = False
    if proj.get("active_quote_id") == q["id"]:
        proj["active_quote_id"] = None
        touch(store, proj)
    touch(store, q)
    return object_response(view(q, svc.QUOTE_FIELDS), 200)


# ===========================================================================
# Add-ons — §3.6
# ===========================================================================
@app.route("/quotes/<qid>/addons", methods=["POST"])
def create_addon(qid):
    _uid, role = require_auth()
    require_role(role, {"SalesRep", "PlatformAdmin"})
    q = get_or_404(store.quotes, qid)
    body = get_json_body()
    kind = require_enum(body, "kind", {"HARDWARE", "COUNTERTOP"})
    unit_price = require_int(body, "unit_price_cents", minimum=0)
    quantity = require_number(body, "quantity")
    if quantity <= 0:
        raise err("ERR_INVALID_REQUEST", "quantity must be > 0")
    price_cents = calc.round_half_up_cents(calc._d(unit_price) * calc._d(quantity))
    a = common_fields(store)
    a.update({
        "quote_id": qid,
        "kind": kind,
        "unit_price_cents": unit_price,
        "quantity": quantity,
        "status": "PROPOSED",
        "price_cents": price_cents,
    })
    store.addons[a["id"]] = a
    return object_response(view(a, svc.ADDON_FIELDS), 201)


@app.route("/quotes/<qid>/addons", methods=["GET"])
def list_addons(qid):
    _uid, role = require_auth()
    require_role(role, {"SalesRep", "Scheduler", "PlatformAdmin", "Customer"})
    get_or_404(store.quotes, qid)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = [a for a in store.addons.values() if a["quote_id"] == qid]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    page, total = paginate(items, limit, offset)
    return array_response([view(a, svc.ADDON_FIELDS) for a in page],
                          limit, offset, total)


@app.route("/addons/<aid>/approve", methods=["POST"])
def approve_addon(aid):
    _uid, role = require_auth()
    require_role(role, {"SalesRep", "PlatformAdmin"})
    a = get_or_404(store.addons, aid)
    if a["status"] != "PROPOSED":
        raise err("ERR_INVALID_STATE", "Add-on not in PROPOSED")
    a["status"] = "APPROVED"
    touch(store, a)
    return object_response(view(a, svc.ADDON_FIELDS), 200)


@app.route("/addons/<aid>/remove", methods=["POST"])
def remove_addon(aid):
    _uid, role = require_auth()
    require_role(role, {"SalesRep", "PlatformAdmin"})
    a = get_or_404(store.addons, aid)
    if a["status"] == "REMOVED":
        raise err("ERR_INVALID_STATE", "Add-on already removed")
    a["status"] = "REMOVED"
    touch(store, a)
    return object_response(view(a, svc.ADDON_FIELDS), 200)


# ===========================================================================
# Change orders — §3.7
# ===========================================================================
@app.route("/quotes/<qid>/change-orders", methods=["POST"])
def create_change_order(qid):
    _uid, role = require_auth()
    require_role(role, {"SalesRep", "PlatformAdmin"})
    q = get_or_404(store.quotes, qid)
    body = get_json_body()
    delta_lf = body.get("delta_linear_feet", 0)
    delta_dc = body.get("delta_door_count", 0)
    rush = body.get("rush", False)
    if isinstance(delta_lf, bool) or not isinstance(delta_lf, (int, float)):
        raise err("ERR_INVALID_REQUEST", "delta_linear_feet must be a number")
    if isinstance(delta_dc, bool) or not isinstance(delta_dc, int):
        raise err("ERR_INVALID_REQUEST", "delta_door_count must be an integer")
    if not isinstance(rush, bool):
        raise err("ERR_INVALID_REQUEST", "rush must be a boolean")
    co = common_fields(store)
    co.update({
        "quote_id": qid,
        "delta_linear_feet": delta_lf,
        "delta_door_count": delta_dc,
        "rush": rush,
        "status": "PENDING",
        "price_delta_cents": None,
        "lead_time_delta_days": None,
    })
    store.change_orders[co["id"]] = co
    return object_response(view(co, svc.CHANGE_ORDER_FIELDS), 201)


@app.route("/quotes/<qid>/change-orders", methods=["GET"])
def list_change_orders(qid):
    _uid, role = require_auth()
    require_role(role, {"SalesRep", "Scheduler", "PlatformAdmin", "Customer"})
    get_or_404(store.quotes, qid)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = [c for c in store.change_orders.values() if c["quote_id"] == qid]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, total = paginate(items, limit, offset)
    return array_response([view(c, svc.CHANGE_ORDER_FIELDS) for c in page],
                          limit, offset, total)


@app.route("/change-orders/<coid>", methods=["GET"])
def get_change_order(coid):
    _uid, role = require_auth()
    require_role(role, {"SalesRep", "Scheduler", "PlatformAdmin", "Customer"})
    co = get_or_404(store.change_orders, coid)
    return object_response(view(co, svc.CHANGE_ORDER_FIELDS), 200)


@app.route("/change-orders/<coid>/accept", methods=["POST"])
def accept_change_order(coid):
    _uid, role = require_auth()
    require_role(role, {"Customer"})
    co = get_or_404(store.change_orders, coid)
    q = store.quotes.get(co["quote_id"])
    proj = store.projects.get(q["project_id"])
    assert_project_owner(proj, _uid, role)
    body = get_json_body()
    expected_version = require_int(body, "expected_quote_version")
    if co["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Change order not in PENDING")
    if q["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "Linked quote is not APPROVED")
    if proj["status"] not in ("SOLD", "IN_PRODUCTION"):
        raise err("ERR_INVALID_STATE", "Project not in SOLD or IN_PRODUCTION")
    if expected_version != q["version"]:
        raise err("ERR_STALE_QUOTE_VERSION", "expected_quote_version is stale")

    measure = store.measures.get(q["measure_id"])
    price_delta, lead_delta = calc.change_order_delta(
        q["scope"], measure["finish_code"],
        co["delta_linear_feet"], co["delta_door_count"], co["rush"],
    )
    co["price_delta_cents"] = price_delta
    co["lead_time_delta_days"] = lead_delta
    co["status"] = "ACCEPTED"
    touch(store, co)

    # hop 1: re-price the quote
    q["firm_total_cents"] = (q["firm_total_cents"] or 0) + price_delta
    touch(store, q)

    # hop 2: extend material order lead time if PLACED/READY
    mo = None
    for cand in store.material_orders.values():
        if cand["quote_id"] == q["id"] and cand["status"] in ("PLACED", "READY"):
            mo = cand
            break
    if mo is not None:
        mo["lead_extension_days"] = mo["lead_extension_days"] + lead_delta
        mo["ready_at"] = format_iso8601_ms(add_days(
            parse_iso8601(mo["_placed_at"]),
            mo["base_lead_time_days"] + mo["lead_extension_days"],
        ))
        touch(store, mo)
        # hop 3: cancel a SCHEDULED install whose window_start < new ready_at
        new_ready = parse_iso8601(mo["ready_at"])
        for job in store.install_jobs.values():
            if job["material_order_id"] == mo["id"] and job["status"] == "SCHEDULED" \
                    and parse_iso8601(job["window_start"]) < new_ready:
                job["status"] = "CANCELLED"
                touch(store, job)
                if proj["status"] == "IN_PRODUCTION":
                    proj["status"] = "SOLD"
                    touch(store, proj)
    return object_response(view(co, svc.CHANGE_ORDER_FIELDS), 200)


@app.route("/change-orders/<coid>/reject", methods=["POST"])
def reject_change_order(coid):
    _uid, role = require_auth()
    require_role(role, {"Customer"})
    co = get_or_404(store.change_orders, coid)
    q = store.quotes.get(co["quote_id"])
    proj = store.projects.get(q["project_id"])
    assert_project_owner(proj, _uid, role)
    if co["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Change order not in PENDING")
    co["status"] = "REJECTED"
    touch(store, co)
    return object_response(view(co, svc.CHANGE_ORDER_FIELDS), 200)


# ===========================================================================
# Material orders — §3.8
# ===========================================================================
@app.route("/projects/<pid>/material-orders", methods=["POST"])
def create_material_order(pid):
    _uid, role = require_auth()
    require_role(role, {"Scheduler", "PlatformAdmin"})
    proj = get_or_404(store.projects, pid)
    body = get_json_body()
    quote_id = require_str(body, "quote_id")
    q = get_or_404(store.quotes, quote_id)
    if proj["status"] != "SOLD":
        raise err("ERR_INVALID_STATE", "Project not in SOLD")
    if q["status"] != "APPROVED" or not q.get("is_active") or q["project_id"] != pid:
        raise err("ERR_QUOTE_NOT_APPROVED", "Quote is not APPROVED and active on this project")
    measure = store.measures.get(q["measure_id"])
    base_lead = calc.base_lead_time_days(measure["finish_code"], q["scope"],
                                         measure["linear_feet"])
    placed_at = store.clock.now
    mo = common_fields(store)
    mo.update({
        "project_id": pid,
        "quote_id": quote_id,
        "status": "PLACED",
        "base_lead_time_days": base_lead,
        "lead_extension_days": 0,
        "ready_at": format_iso8601_ms(add_days(placed_at, base_lead + 0)),
        "_placed_at": format_iso8601_ms(placed_at),  # internal anchor
    })
    store.material_orders[mo["id"]] = mo
    proj["status"] = "IN_PRODUCTION"
    touch(store, proj)
    return object_response(view(mo, svc.MATERIAL_ORDER_FIELDS), 201)


@app.route("/projects/<pid>/material-orders", methods=["GET"])
def list_project_material_orders(pid):
    _uid, role = require_auth()
    require_role(role, {"SalesRep", "Scheduler", "PlatformAdmin", "Customer"})
    get_or_404(store.projects, pid)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = [m for m in store.material_orders.values() if m["project_id"] == pid]
    if status is not None:
        items = [m for m in items if m["status"] == status]
    page, total = paginate(items, limit, offset)
    return array_response([view(m, svc.MATERIAL_ORDER_FIELDS) for m in page],
                          limit, offset, total)


@app.route("/material-orders/<moid>", methods=["GET"])
def get_material_order(moid):
    _uid, role = require_auth()
    require_role(role, {"SalesRep", "Scheduler", "PlatformAdmin", "Customer"})
    mo = get_or_404(store.material_orders, moid)
    return object_response(view(mo, svc.MATERIAL_ORDER_FIELDS), 200)


@app.route("/material-orders", methods=["GET"])
def list_material_orders():
    _uid, role = require_auth()
    require_role(role, {"SalesRep", "Scheduler", "PlatformAdmin"})
    limit, offset = parse_pagination()
    quote_id = request.args.get("quote_id")
    status = request.args.get("status")
    items = list(store.material_orders.values())
    if quote_id is not None:
        items = [m for m in items if m["quote_id"] == quote_id]
    if status is not None:
        items = [m for m in items if m["status"] == status]
    page, total = paginate(items, limit, offset)
    return array_response([view(m, svc.MATERIAL_ORDER_FIELDS) for m in page],
                          limit, offset, total)


@app.route("/material-orders/<moid>/mark-ready", methods=["POST"])
def mark_ready_material_order(moid):
    _uid, role = require_auth()
    require_role(role, {"Scheduler", "PlatformAdmin"})
    mo = get_or_404(store.material_orders, moid)
    if mo["status"] != "PLACED":
        raise err("ERR_INVALID_STATE", "Material order not in PLACED")
    if store.clock.now < parse_iso8601(mo["ready_at"]):
        raise err("ERR_LEAD_TIME_NOT_ELAPSED", "Lead time has not elapsed")
    mo["status"] = "READY"
    touch(store, mo)
    return object_response(view(mo, svc.MATERIAL_ORDER_FIELDS), 200)


@app.route("/material-orders/<moid>/receive", methods=["POST"])
def receive_material_order(moid):
    _uid, role = require_auth()
    require_role(role, {"Scheduler", "PlatformAdmin"})
    mo = get_or_404(store.material_orders, moid)
    if mo["status"] != "READY":
        raise err("ERR_INVALID_STATE", "Material order not in READY")
    mo["status"] = "RECEIVED"
    touch(store, mo)
    return object_response(view(mo, svc.MATERIAL_ORDER_FIELDS), 200)


@app.route("/material-orders/<moid>/cancel", methods=["POST"])
def cancel_material_order(moid):
    _uid, role = require_auth()
    require_role(role, {"Scheduler", "PlatformAdmin"})
    mo = get_or_404(store.material_orders, moid)
    if mo["status"] != "PLACED":
        raise err("ERR_INVALID_STATE", "Material order not in PLACED")
    for job in store.install_jobs.values():
        if job["material_order_id"] == moid and job["status"] in ("SCHEDULED", "IN_PROGRESS", "DONE"):
            raise err("ERR_INVALID_STATE", "Active install job references this order")
    mo["status"] = "CANCELLED"
    touch(store, mo)
    proj = store.projects.get(mo["project_id"])
    if proj is not None and proj["status"] == "IN_PRODUCTION":
        proj["status"] = "SOLD"
        touch(store, proj)
    return object_response(view(mo, svc.MATERIAL_ORDER_FIELDS), 200)


# ===========================================================================
# Crews — §3.9
# ===========================================================================
@app.route("/crews", methods=["POST"])
def create_crew():
    _uid, role = require_auth()
    require_role(role, {"Scheduler", "PlatformAdmin"})
    body = get_json_body()
    name = require_str(body, "name")
    capacity = require_int(body, "daily_job_capacity", minimum=1)
    require_fields(body, ["skill_finishes"])
    skill_finishes = body["skill_finishes"]
    valid_finishes = {"LAMINATE", "THERMOFOIL", "WOOD_VENEER", "SOLID_WOOD", "PAINT"}
    if not isinstance(skill_finishes, list) or len(skill_finishes) == 0:
        raise err("ERR_INVALID_REQUEST", "skill_finishes must be a non-empty array")
    for f in skill_finishes:
        if f not in valid_finishes:
            raise err("ERR_INVALID_REQUEST", "skill_finishes contains an invalid finish_code")
    is_active = optional_bool(body, "is_active", default=True)
    crew = common_fields(store)
    crew.update({
        "name": name,
        "daily_job_capacity": capacity,
        "skill_finishes": skill_finishes,
        "is_active": is_active,
    })
    store.crews[crew["id"]] = crew
    return object_response(view(crew, svc.CREW_FIELDS), 201)


@app.route("/crews/<cid>", methods=["GET"])
def get_crew(cid):
    _uid, role = require_auth()
    require_role(role, {"Scheduler", "PlatformAdmin"})
    crew = get_or_404(store.crews, cid)
    return object_response(view(crew, svc.CREW_FIELDS), 200)


@app.route("/crews", methods=["GET"])
def list_crews():
    _uid, role = require_auth()
    require_role(role, {"Scheduler", "PlatformAdmin"})
    limit, offset = parse_pagination()
    is_active = request.args.get("is_active")
    items = list(store.crews.values())
    if is_active is not None:
        want = is_active.lower() in ("true", "1")
        items = [c for c in items if bool(c["is_active"]) == want]
    page, total = paginate(items, limit, offset)
    return array_response([view(c, svc.CREW_FIELDS) for c in page],
                          limit, offset, total)


# ===========================================================================
# Install jobs — §3.9, §3.10
# ===========================================================================
@app.route("/projects/<pid>/install-jobs", methods=["POST"])
def create_install_job(pid):
    _uid, role = require_auth()
    require_role(role, {"Scheduler", "PlatformAdmin"})
    proj = get_or_404(store.projects, pid)
    body = get_json_body()
    material_order_id = require_str(body, "material_order_id")
    crew_id = require_str(body, "crew_id")
    window_start_raw = require_str(body, "window_start")
    window_end_raw = require_str(body, "window_end")
    mo = get_or_404(store.material_orders, material_order_id)
    crew = get_or_404(store.crews, crew_id)
    try:
        window_start = parse_iso8601(window_start_raw)
        window_end = parse_iso8601(window_end_raw)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "window_start/window_end must be ISO 8601 instants")

    measure = store.measures.get(store.quotes[mo["quote_id"]]["measure_id"])
    finish_code = measure["finish_code"]

    # priority 11: crew certified + active
    if not crew["is_active"] or finish_code not in crew["skill_finishes"]:
        raise err("ERR_CREW_NOT_CERTIFIED", "Crew inactive or not certified for finish")
    # priority 12: window_start >= ready_at
    if window_start < parse_iso8601(mo["ready_at"]):
        raise err("ERR_WINDOW_BEFORE_READY", "Window starts before materials are ready")
    # priority 13: crew window overlap (half-open) with non-CANCELLED jobs
    for job in store.install_jobs.values():
        if job["crew_id"] == crew_id and job["status"] != "CANCELLED":
            js = parse_iso8601(job["window_start"])
            je = parse_iso8601(job["window_end"])
            if window_start < je and js < window_end:  # half-open overlap
                raise err("ERR_CREW_WINDOW_CONFLICT", "Window overlaps an existing booking")
    # priority 14: crew day-capacity for install_day
    install_day = window_start.astimezone(window_start.tzinfo).strftime("%Y-%m-%d")
    same_day_count = sum(
        1 for job in store.install_jobs.values()
        if job["crew_id"] == crew_id and job["status"] != "CANCELLED"
        and job["install_day"] == install_day
    )
    if same_day_count >= crew["daily_job_capacity"]:
        raise err("ERR_CREW_DAY_FULL", "Crew day capacity reached")
    # priority 15: window_end strictly greater than window_start
    if not (window_end > window_start):
        raise err("ERR_INVALID_WINDOW", "window_end must be after window_start")

    job = common_fields(store)
    job.update({
        "project_id": pid,
        "material_order_id": material_order_id,
        "crew_id": crew_id,
        "window_start": window_start_raw,
        "window_end": window_end_raw,
        "status": "SCHEDULED",
        "install_day": install_day,
    })
    store.install_jobs[job["id"]] = job
    return object_response(view(job, svc.INSTALL_JOB_FIELDS), 201)


@app.route("/projects/<pid>/install-jobs", methods=["GET"])
def list_project_install_jobs(pid):
    _uid, role = require_auth()
    require_role(role, {"SalesRep", "Scheduler", "PlatformAdmin", "Customer"})
    get_or_404(store.projects, pid)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = [j for j in store.install_jobs.values() if j["project_id"] == pid]
    if status is not None:
        items = [j for j in items if j["status"] == status]
    page, total = paginate(items, limit, offset)
    return array_response([view(j, svc.INSTALL_JOB_FIELDS) for j in page],
                          limit, offset, total)


@app.route("/install-jobs/<jid>", methods=["GET"])
def get_install_job(jid):
    _uid, role = require_auth()
    require_role(role, {"SalesRep", "Scheduler", "PlatformAdmin", "Customer", "InstallCrew"})
    job = get_or_404(store.install_jobs, jid)
    return object_response(view(job, svc.INSTALL_JOB_FIELDS), 200)


@app.route("/install-jobs", methods=["GET"])
def list_install_jobs():
    _uid, role = require_auth()
    require_role(role, {"Scheduler", "PlatformAdmin", "InstallCrew"})
    limit, offset = parse_pagination()
    crew_id = request.args.get("crew_id")
    material_order_id = request.args.get("material_order_id")
    status = request.args.get("status")
    items = list(store.install_jobs.values())
    if crew_id is not None:
        items = [j for j in items if j["crew_id"] == crew_id]
    if material_order_id is not None:
        items = [j for j in items if j["material_order_id"] == material_order_id]
    if status is not None:
        items = [j for j in items if j["status"] == status]
    page, total = paginate(items, limit, offset)
    return array_response([view(j, svc.INSTALL_JOB_FIELDS) for j in page],
                          limit, offset, total)


@app.route("/install-jobs/<jid>/start", methods=["POST"])
def start_install_job(jid):
    _uid, role = require_auth()
    require_role(role, {"InstallCrew", "PlatformAdmin"})
    job = get_or_404(store.install_jobs, jid)
    if job["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Install job not in SCHEDULED")
    mo = store.material_orders.get(job["material_order_id"])
    if mo is None or mo["status"] not in ("READY", "RECEIVED"):
        raise err("ERR_INVALID_STATE", "Material order not READY/RECEIVED")
    if store.clock.now < parse_iso8601(job["window_start"]):
        raise err("ERR_INVALID_STATE", "Current time before window_start")
    job["status"] = "IN_PROGRESS"
    touch(store, job)
    return object_response(view(job, svc.INSTALL_JOB_FIELDS), 200)


@app.route("/install-jobs/<jid>/complete", methods=["POST"])
def complete_install_job(jid):
    _uid, role = require_auth()
    require_role(role, {"InstallCrew", "PlatformAdmin"})
    job = get_or_404(store.install_jobs, jid)
    if job["status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", "Install job not in IN_PROGRESS")
    job["status"] = "DONE"
    touch(store, job)
    mo = store.material_orders.get(job["material_order_id"])
    if mo is not None and mo["status"] == "READY":
        mo["status"] = "RECEIVED"
        touch(store, mo)
    proj = store.projects.get(job["project_id"])
    if proj is not None and proj["status"] == "IN_PRODUCTION":
        proj["status"] = "INSTALLED"
        proj["install_completed_at"] = format_iso8601_ms(store.clock.now)
        touch(store, proj)
    return object_response(view(job, svc.INSTALL_JOB_FIELDS), 200)


@app.route("/install-jobs/<jid>/cancel", methods=["POST"])
def cancel_install_job(jid):
    _uid, role = require_auth()
    require_role(role, {"Scheduler", "PlatformAdmin"})
    job = get_or_404(store.install_jobs, jid)
    if job["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Install job not in SCHEDULED")
    job["status"] = "CANCELLED"
    touch(store, job)
    proj = store.projects.get(job["project_id"])
    if proj is not None and proj["status"] == "IN_PRODUCTION":
        proj["status"] = "SOLD"
        touch(store, proj)
    return object_response(view(job, svc.INSTALL_JOB_FIELDS), 200)


# ===========================================================================
# Warranty claims — §3.11
# ===========================================================================
@app.route("/projects/<pid>/warranty-claims", methods=["POST"])
def create_warranty_claim(pid):
    _uid, role = require_auth()
    require_role(role, {"Customer", "SalesRep", "PlatformAdmin"})
    proj = get_or_404(store.projects, pid)
    assert_project_owner(proj, _uid, role)
    body = get_json_body()
    description = require_str(body, "description")
    if proj["status"] not in ("INSTALLED", "CLOSED"):
        raise err("ERR_OUT_OF_WARRANTY", "Project is not INSTALLED or CLOSED")
    # covered iff now <= install_completed_at + WARRANTY_DAYS
    covered = False
    completed_at = proj.get("install_completed_at")
    if completed_at is not None:
        window_end = add_days(parse_iso8601(completed_at), calc.WARRANTY_DAYS)
        covered = store.clock.now <= window_end
    wc = common_fields(store)
    wc.update({
        "project_id": pid,
        "description": description,
        "status": "SUBMITTED",
        "covered": covered,
        "filed_at": format_iso8601_ms(store.clock.now),
    })
    store.warranty_claims[wc["id"]] = wc
    return object_response(view(wc, svc.WARRANTY_CLAIM_FIELDS), 201)


@app.route("/projects/<pid>/warranty-claims", methods=["GET"])
def list_warranty_claims(pid):
    _uid, role = require_auth()
    require_role(role, {"Customer", "SalesRep", "Scheduler", "PlatformAdmin"})
    get_or_404(store.projects, pid)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = [w for w in store.warranty_claims.values() if w["project_id"] == pid]
    if status is not None:
        items = [w for w in items if w["status"] == status]
    page, total = paginate(items, limit, offset)
    return array_response([view(w, svc.WARRANTY_CLAIM_FIELDS) for w in page],
                          limit, offset, total)


@app.route("/warranty-claims/<wid>", methods=["GET"])
def get_warranty_claim(wid):
    _uid, role = require_auth()
    require_role(role, {"Customer", "SalesRep", "Scheduler", "PlatformAdmin"})
    wc = get_or_404(store.warranty_claims, wid)
    return object_response(view(wc, svc.WARRANTY_CLAIM_FIELDS), 200)


@app.route("/warranty-claims/<wid>/adjudicate", methods=["POST"])
def adjudicate_warranty_claim(wid):
    _uid, role = require_auth()
    require_role(role, {"PlatformAdmin"})
    wc = get_or_404(store.warranty_claims, wid)
    body = get_json_body()
    decision = require_enum(body, "decision", {"APPROVE", "DENY"})
    if wc["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Claim not in SUBMITTED")
    if decision == "APPROVE":
        if not wc["covered"]:
            raise err("ERR_WARRANTY_NOT_COVERED", "Claim is outside the warranty window")
        wc["status"] = "APPROVED"
    else:
        wc["status"] = "DENIED"
    touch(store, wc)
    return object_response(view(wc, svc.WARRANTY_CLAIM_FIELDS), 200)


@app.route("/warranty-claims/<wid>/resolve", methods=["POST"])
def resolve_warranty_claim(wid):
    _uid, role = require_auth()
    require_role(role, {"PlatformAdmin"})
    wc = get_or_404(store.warranty_claims, wid)
    if wc["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "Claim not in APPROVED")
    wc["status"] = "RESOLVED"
    touch(store, wc)
    return object_response(view(wc, svc.WARRANTY_CLAIM_FIELDS), 200)


# ===========================================================================
# Financing applications — §3.12
# ===========================================================================
@app.route("/projects/<pid>/financing-applications", methods=["POST"])
def create_financing(pid):
    _uid, role = require_auth()
    require_role(role, {"Customer", "SalesRep", "PlatformAdmin"})
    proj = get_or_404(store.projects, pid)
    body = get_json_body()
    customer_id = require_str(body, "customer_id")
    amount_cents = require_int(body, "amount_cents")
    require_fields(body, ["term_months"])
    term_months = body["term_months"]
    cust = get_or_404(store.customers, customer_id)
    # ownership: applicant must own the project
    if proj["customer_id"] != customer_id:
        raise err("ERR_NOT_PROJECT_OWNER", "Applicant does not own the project")
    if role == "Customer":
        assert_project_owner(proj, _uid, role)
    if amount_cents <= 0:
        raise err("ERR_INVALID_REQUEST", "amount_cents must be > 0")
    if isinstance(term_months, bool) or term_months not in (12, 24, 36, 48, 60):
        raise err("ERR_INVALID_REQUEST", "term_months must be one of 12,24,36,48,60")
    monthly, dti = calc.financing_monthly_payment(
        amount_cents, term_months, cust["annual_income_cents"])
    fa = common_fields(store)
    fa.update({
        "project_id": pid,
        "customer_id": customer_id,
        "amount_cents": amount_cents,
        "term_months": term_months,
        "status": "SUBMITTED",
        "monthly_payment_cents": monthly,
        "dti_ratio": dti,
    })
    store.financing_applications[fa["id"]] = fa
    return object_response(view(fa, svc.FINANCING_FIELDS), 201)


@app.route("/projects/<pid>/financing-applications", methods=["GET"])
def list_project_financing(pid):
    _uid, role = require_auth()
    require_role(role, {"Customer", "SalesRep", "PlatformAdmin"})
    get_or_404(store.projects, pid)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = [f for f in store.financing_applications.values() if f["project_id"] == pid]
    if status is not None:
        items = [f for f in items if f["status"] == status]
    page, total = paginate(items, limit, offset)
    return array_response([view(f, svc.FINANCING_FIELDS) for f in page],
                          limit, offset, total)


@app.route("/financing-applications/<fid>", methods=["GET"])
def get_financing(fid):
    _uid, role = require_auth()
    require_role(role, {"Customer", "SalesRep", "PlatformAdmin"})
    fa = get_or_404(store.financing_applications, fid)
    return object_response(view(fa, svc.FINANCING_FIELDS), 200)


@app.route("/financing-applications", methods=["GET"])
def list_financing():
    _uid, role = require_auth()
    require_role(role, {"SalesRep", "PlatformAdmin"})
    limit, offset = parse_pagination()
    customer_id = request.args.get("customer_id")
    status = request.args.get("status")
    items = list(store.financing_applications.values())
    if customer_id is not None:
        items = [f for f in items if f["customer_id"] == customer_id]
    if status is not None:
        items = [f for f in items if f["status"] == status]
    page, total = paginate(items, limit, offset)
    return array_response([view(f, svc.FINANCING_FIELDS) for f in page],
                          limit, offset, total)


@app.route("/financing-applications/<fid>/approve", methods=["POST"])
def approve_financing(fid):
    _uid, role = require_auth()
    require_role(role, {"PlatformAdmin"})
    fa = get_or_404(store.financing_applications, fid)
    if fa["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Application not in SUBMITTED")
    if fa["dti_ratio"] > float(calc.DTI_MAX):
        raise err("ERR_DTI_EXCEEDED", "DTI ratio exceeds the maximum")
    fa["status"] = "APPROVED"
    touch(store, fa)
    return object_response(view(fa, svc.FINANCING_FIELDS), 200)


@app.route("/financing-applications/<fid>/decline", methods=["POST"])
def decline_financing(fid):
    _uid, role = require_auth()
    require_role(role, {"PlatformAdmin"})
    fa = get_or_404(store.financing_applications, fid)
    if fa["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Application not in SUBMITTED")
    fa["status"] = "DECLINED"
    touch(store, fa)
    return object_response(view(fa, svc.FINANCING_FIELDS), 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
