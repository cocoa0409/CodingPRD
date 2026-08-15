"""Route, ServiceVisit, and ScanEvent endpoints."""
from flask import Blueprint, request

import response
from db import store, fmt_dt
from errors import err
from middleware import extract_identity, require_role, ALL_ROLES
from common import (
    new_entity, touch, public, get_json, get_or_404, fk_exists,
    require_str, optional_str, require_enum, optional_enum, require_int,
    optional_int, parse_date, parse_datetime, require_from_state,
    require_store_manager, require_driver, parse_pagination, list_page,
)
from services import (
    get_or_create_balance, recompute_posture, recompute_shrink_ratio,
    match_preconditions_hold, price_scan, apply_scan_to_inventory,
)

bp = Blueprint("field", __name__)

VISIT_TERMINAL = {"CONFIRMED", "MISSED", "CANCELLED"}
ROUTE_STATUSES = ["ACTIVE", "INACTIVE"]


# =============================================================================
# Routes (PRD Section 3.5)
# =============================================================================

@bp.route("/routes", methods=["POST"])
def create_route():
    _, role = extract_identity(request.headers)
    require_role(role, ["JobberAdmin"])
    body = get_json(request)
    fk_exists(body, "program_id", store.programs)
    program_id = require_str(body, "program_id")
    name = require_str(body, "name")
    driver = require_str(body, "assigned_driver_id")
    freq = optional_int(body, "service_frequency_days", 7)
    route = new_entity({
        "program_id": program_id,
        "name": name,
        "assigned_driver_id": driver,
        "service_frequency_days": freq,
        "status": "ACTIVE",
    })
    store.routes[route["id"]] = route
    return response.success(public(route), http_status=201)


@bp.route("/routes", methods=["GET"])
def list_routes():
    _, role = extract_identity(request.headers)
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    rows = store.routes.values()
    for param in ("program_id", "status"):
        val = request.args.get(param)
        if val is not None:
            rows = [r for r in rows if r[param] == val]
    page, meta = list_page(rows, limit, offset)
    return response.success(page, is_list=True, pagination=meta)


@bp.route("/routes/<rid>", methods=["GET"])
def get_route(rid):
    _, role = extract_identity(request.headers)
    require_role(role, ALL_ROLES)
    route = get_or_404(store.routes, rid, "route")
    return response.success(public(route))


@bp.route("/routes/<rid>", methods=["PATCH"])
def update_route(rid):
    _, role = extract_identity(request.headers)
    require_role(role, ["JobberAdmin"])
    route = get_or_404(store.routes, rid, "route")
    body = get_json(request)
    driver = optional_str(body, "assigned_driver_id")
    freq = optional_int(body, "service_frequency_days", None)
    status = optional_enum(body, "status", ROUTE_STATUSES)
    if driver is not None:
        route["assigned_driver_id"] = driver
    if freq is not None:
        route["service_frequency_days"] = freq
    if status is not None:
        route["status"] = status
    touch(route)
    return response.success(public(route))


# =============================================================================
# Service visits (PRD Section 3.5)
# =============================================================================

@bp.route("/service-visits", methods=["POST"])
def create_visit():
    _, role = extract_identity(request.headers)
    require_role(role, ["JobberAdmin"])
    body = get_json(request)
    fk_exists(body, "route_id", store.routes)
    fk_exists(body, "store_agreement_id", store.agreements)
    route_id = require_str(body, "route_id")
    agreement_id = require_str(body, "store_agreement_id")
    scheduled = parse_date(body.get("scheduled_date"), "scheduled_date")
    route = store.routes[route_id]
    agreement = store.agreements[agreement_id]
    # Stage 25 precedes stage 27 on the PRD Section 2.8 ladder.
    if agreement["program_id"] != route["program_id"]:
        raise err("ERR_ROUTE_PROGRAM_MISMATCH",
                  "the agreement does not belong to the route's program")
    if agreement["status"] != "ACTIVE":
        raise err("ERR_AGREEMENT_NOT_ACTIVE", "agreement is not ACTIVE")
    visit = new_entity({
        "route_id": route_id,
        "store_agreement_id": agreement_id,
        "scheduled_date": scheduled.strftime("%Y-%m-%d"),
        "status": "SCHEDULED",
        "submitted_lines": [],
        "total_counted_units": 0,
        "total_restock_units": 0,
        "total_variance_units": 0,
        "applied_restock_value_cents": 0,
        "auto_restock_flag": False,
        "suggested_restock_units": 0,
    })
    store.service_visits[visit["id"]] = visit
    return response.success(public(visit), http_status=201)


@bp.route("/service-visits", methods=["GET"])
def list_visits():
    _, role = extract_identity(request.headers)
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    rows = store.service_visits.values()
    for param in ("route_id", "store_agreement_id", "status"):
        val = request.args.get(param)
        if val is not None:
            rows = [v for v in rows if v[param] == val]
    page, meta = list_page(rows, limit, offset)
    return response.success(page, is_list=True, pagination=meta)


@bp.route("/service-visits/<vid>", methods=["GET"])
def get_visit(vid):
    _, role = extract_identity(request.headers)
    require_role(role, ALL_ROLES)
    visit = get_or_404(store.service_visits, vid, "service visit")
    return response.success(public(visit))


@bp.route("/service-visits/<vid>/check-in", methods=["POST"])
def check_in_visit(vid):
    user_id, role = extract_identity(request.headers)
    require_role(role, ["RouteDriver"])
    visit = get_or_404(store.service_visits, vid, "service visit")
    get_json(request)
    route = store.routes[visit["route_id"]]
    agreement = store.agreements[visit["store_agreement_id"]]
    require_driver(user_id, route)
    require_from_state(visit, ["SCHEDULED"], VISIT_TERMINAL, "service visit", target="CHECKED_IN")
    # Day-of discipline: the clock date must equal the scheduled date.
    if store.today_str() != visit["scheduled_date"]:
        raise err("ERR_VISIT_WINDOW_CLOSED", "check-in is only allowed on the scheduled date")
    if agreement["status"] != "ACTIVE":
        raise err("ERR_AGREEMENT_NOT_ACTIVE", "agreement is not ACTIVE")
    visit["status"] = "CHECKED_IN"
    touch(visit)
    return response.success(public(visit))


@bp.route("/service-visits/<vid>/submit-counts", methods=["POST"])
def submit_counts(vid):
    user_id, role = extract_identity(request.headers)
    require_role(role, ["RouteDriver"])
    visit = get_or_404(store.service_visits, vid, "service visit")
    body = get_json(request)
    lines = body.get("lines")
    if not isinstance(lines, list):
        raise err("ERR_INVALID_REQUEST", "lines must be an array")
    # Line shape (stage 5) and per-line product existence (stage 4).
    parsed = []
    for line in lines:
        if not isinstance(line, dict):
            raise err("ERR_INVALID_REQUEST", "each line must be an object")
        pid = line.get("product_id")
        if not isinstance(pid, str) or pid == "":
            raise err("ERR_INVALID_REQUEST", "line product_id is required")
        if pid not in store.products:
            raise err("ERR_NOT_FOUND", "product_id %s does not exist" % pid)
        counted = line.get("counted_units")
        restock = line.get("restock_units")
        for value, field in ((counted, "counted_units"), (restock, "restock_units")):
            if not isinstance(value, int) or isinstance(value, bool):
                raise err("ERR_INVALID_REQUEST", "line %s must be an integer" % field)
        if counted < 0 or restock < 0:
            raise err("ERR_RANGE_INVALID", "line units must be >= 0")
        parsed.append({"product_id": pid, "counted_units": counted, "restock_units": restock})
    route = store.routes[visit["route_id"]]
    agreement = store.agreements[visit["store_agreement_id"]]
    require_driver(user_id, route)
    require_from_state(visit, ["CHECKED_IN"], VISIT_TERMINAL, "service visit", target="COUNTS_SUBMITTED")
    # Every product named must belong to the agreement's program.
    for line in parsed:
        if store.products[line["product_id"]]["program_id"] != agreement["program_id"]:
            raise err("ERR_PRODUCT_NOT_IN_PROGRAM",
                      "line product is not in the agreement's program")
    # Fiscal cap: submitted restock value may not exceed the agreement cap.
    restock_value = sum(
        line["restock_units"] * store.products[line["product_id"]]["jobber_cost_cents"]
        for line in parsed
    )
    if restock_value > agreement["restock_value_cap_cents"]:
        raise err("ERR_RESTOCK_VALUE_CAP_EXCEEDED",
                  "submitted restock value exceeds the agreement cap")
    # Freeze the submission and compute the totals snapshot.
    visit["submitted_lines"] = parsed
    visit["total_counted_units"] = sum(l["counted_units"] for l in parsed)
    visit["total_restock_units"] = sum(l["restock_units"] for l in parsed)
    visit["total_variance_units"] = sum(
        l["counted_units"] - _book_units(agreement["id"], l["product_id"]) for l in parsed
    )
    visit["applied_restock_value_cents"] = restock_value
    visit["status"] = "COUNTS_SUBMITTED"
    touch(visit)
    return response.success(public(visit))


def _book_units(agreement_id, product_id):
    from services import get_balance
    balance = get_balance(agreement_id, product_id)
    return balance["on_hand_units"] if balance is not None else 0


@bp.route("/service-visits/<vid>/confirm", methods=["POST"])
def confirm_visit(vid):
    user_id, role = extract_identity(request.headers)
    require_role(role, ["RetailerManager"])
    visit = get_or_404(store.service_visits, vid, "service visit")
    get_json(request)
    agreement = store.agreements[visit["store_agreement_id"]]
    require_store_manager(user_id, agreement)
    require_from_state(visit, ["COUNTS_SUBMITTED"], VISIT_TERMINAL, "service visit", target="CONFIRMED")
    if agreement["status"] != "ACTIVE":
        raise err("ERR_AGREEMENT_NOT_ACTIVE", "agreement is not ACTIVE")
    # Rewrite the inventory ledger: the physical count resets the book.
    for line in visit["submitted_lines"]:
        balance = get_or_create_balance(agreement["id"], line["product_id"])
        balance["on_hand_units"] = line["counted_units"] + line["restock_units"]
        balance["lifetime_delivered_units"] += line["restock_units"]
        recompute_posture(balance)
        touch(balance)
    # The agreement absorbs the delivery and both versions advance.
    agreement["cumulative_delivered_units"] += visit["total_restock_units"]
    recompute_shrink_ratio(agreement)
    touch(agreement)
    visit["status"] = "CONFIRMED"
    touch(visit)
    return response.success(public(visit))


@bp.route("/service-visits/<vid>/dispute", methods=["POST"])
def dispute_visit(vid):
    user_id, role = extract_identity(request.headers)
    require_role(role, ["RetailerManager"])
    visit = get_or_404(store.service_visits, vid, "service visit")
    get_json(request)  # optional reason accepted and ignored
    agreement = store.agreements[visit["store_agreement_id"]]
    require_store_manager(user_id, agreement)
    require_from_state(visit, ["COUNTS_SUBMITTED"], VISIT_TERMINAL, "service visit", target="DISPUTED")
    visit["status"] = "DISPUTED"
    touch(visit)
    return response.success(public(visit))


@bp.route("/service-visits/<vid>/recount", methods=["POST"])
def recount_visit(vid):
    user_id, role = extract_identity(request.headers)
    require_role(role, ["RouteDriver"])
    visit = get_or_404(store.service_visits, vid, "service visit")
    get_json(request)
    route = store.routes[visit["route_id"]]
    require_driver(user_id, route)
    require_from_state(visit, ["DISPUTED"], VISIT_TERMINAL, "service visit", target="CHECKED_IN")
    # Revision loop: clear the frozen submission so the driver counts afresh.
    visit["submitted_lines"] = []
    visit["total_counted_units"] = 0
    visit["total_restock_units"] = 0
    visit["total_variance_units"] = 0
    visit["applied_restock_value_cents"] = 0
    visit["status"] = "CHECKED_IN"
    touch(visit)
    return response.success(public(visit))


@bp.route("/service-visits/<vid>/cancel", methods=["POST"])
def cancel_visit(vid):
    _, role = extract_identity(request.headers)
    require_role(role, ["JobberAdmin"])
    visit = get_or_404(store.service_visits, vid, "service visit")
    get_json(request)
    require_from_state(visit, ["SCHEDULED"], VISIT_TERMINAL, "service visit", target="CANCELLED")
    visit["status"] = "CANCELLED"
    touch(visit)
    return response.success(public(visit))


# =============================================================================
# Scan events (PRD Section 3.6) — append-only ledger
# =============================================================================

@bp.route("/scan-events", methods=["POST"])
def create_scan():
    user_id, role = extract_identity(request.headers)
    require_role(role, ["RetailerManager"])
    body = get_json(request)
    # Stage 4: body FK references. (void_of_event_id is validated by the
    # stage-29 void-target rule instead — PRD Section 3.6.)
    fk_exists(body, "store_agreement_id", store.agreements)
    fk_exists(body, "product_id", store.products)
    # Stage 5: shape.
    agreement_id = require_str(body, "store_agreement_id")
    product_id = require_str(body, "product_id")
    client_event_id = require_str(body, "client_event_id")
    quantity = require_int(body, "quantity")
    scanned_at = fmt_dt(parse_datetime(body.get("scanned_at"), "scanned_at"))
    # Stage 6: enums.
    event_type = require_enum(body, "event_type", ["SALE", "RETURN", "VOID"])
    # Stage 7: ranges.
    if quantity < 1:
        raise err("ERR_RANGE_INVALID", "quantity must be >= 1")
    agreement = store.agreements[agreement_id]
    product = store.products[product_id]
    # Stage 8: store-identity rule.
    require_store_manager(user_id, agreement)
    # Stage 19: client_event_id is the retailer's idempotency key per agreement.
    for s in store.scan_events.values():
        if s["store_agreement_id"] == agreement_id and s["client_event_id"] == client_event_id:
            raise err("ERR_DUPLICATE_SCAN_EVENT",
                      "client_event_id already ingested for this agreement")
    # Stage 29: the void family is rejected outright, never persisted.
    void_of = None
    if event_type == "VOID":
        target_id = body.get("void_of_event_id")
        target = store.scan_events.get(target_id) if isinstance(target_id, str) else None
        if (target is None
                or target["status"] != "MATCHED"
                or target["event_type"] == "VOID"
                or target["store_agreement_id"] != agreement_id
                or target["quantity"] != quantity):
            raise err("ERR_VOID_TARGET_INVALID", "void target is invalid")
        void_of = target_id
    scan = new_entity({
        "store_agreement_id": agreement_id,
        "product_id": product_id,
        "client_event_id": client_event_id,
        "event_type": event_type,
        "quantity": quantity,
        "scanned_at": scanned_at,
        "void_of_event_id": void_of,
        "status": "UNMATCHED",
        "unit_price_cents": None,
        "line_value_cents": None,
        "jobber_funding_cents": None,
        "is_promo_priced": False,
        "settled_in_statement_id": None,
    }, common=False)  # append-only: no updated_at / version (PRD 2.4)
    # Synchronous resolution: land MATCHED only when all preconditions hold.
    if match_preconditions_hold(scan, agreement, product):
        scan["status"] = "MATCHED"
        price_scan(scan, agreement, product)
        store.scan_events[scan["id"]] = scan
        apply_scan_to_inventory(scan)
    else:
        store.scan_events[scan["id"]] = scan
    return response.success(public(scan), http_status=201)


@bp.route("/scan-events", methods=["GET"])
def list_scans():
    _, role = extract_identity(request.headers)
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    rows = store.scan_events.values()
    for param in ("store_agreement_id", "product_id", "event_type", "status",
                  "void_of_event_id", "settled_in_statement_id"):
        val = request.args.get(param)
        if val is not None:
            rows = [s for s in rows if s[param] == val]
    page, meta = list_page(rows, limit, offset)
    return response.success(page, is_list=True, pagination=meta)


@bp.route("/scan-events/<sid>", methods=["GET"])
def get_scan(sid):
    _, role = extract_identity(request.headers)
    require_role(role, ALL_ROLES)
    scan = get_or_404(store.scan_events, sid, "scan event")
    return response.success(public(scan))


@bp.route("/scan-events/<sid>/resolve", methods=["POST"])
def resolve_scan(sid):
    """Re-run the match after master-data repair (PRD Section 3.6)."""
    _, role = extract_identity(request.headers)
    require_role(role, ["JobberAdmin"])
    scan = get_or_404(store.scan_events, sid, "scan event")
    get_json(request)
    if scan["status"] != "UNMATCHED":
        raise err("ERR_INVALID_STATE", "scan event is not UNMATCHED")
    agreement = store.agreements[scan["store_agreement_id"]]
    product = store.products[scan["product_id"]]
    if not match_preconditions_hold(scan, agreement, product):
        raise err("ERR_INVALID_STATE", "match preconditions do not hold")
    # Same valuation, inventory, and reorder effects as a native match.
    scan["status"] = "MATCHED"
    price_scan(scan, agreement, product)
    apply_scan_to_inventory(scan)
    return response.success(public(scan))
