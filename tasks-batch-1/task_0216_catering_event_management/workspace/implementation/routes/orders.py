"""Order routes: create/edit/get/list, the lifecycle + settlement state
machines (confirm, guarantee, invoice, payments, settle, fulfill, cancel),
and order sub-resource listings (PRD §3.2-§3.9).
"""
from flask import Blueprint, request

from common import (
    get_json, stamp_create, touch, paginate, parse_dt,
    require_int, opt_int, require, hours_floor,
)
from db import db
from errors import (
    err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_BELOW_MIN_HEADCOUNT, ERR_DIETARY_EXCEEDS_HEADCOUNT, ERR_VALIDATION_WINDOW,
    ERR_NOT_RESOURCE_OWNER, ERR_PACKAGE_RETIRED, ERR_LEAD_TIME_VIOLATED,
    ERR_VENUE_OVERBOOKED, ERR_OPEN_CHANGE_REQUEST, ERR_BALANCE_UNPAID,
    ERR_STAFF_POOL_EXHAUSTED, ERR_INVALID_PAYMENT,
)
from middleware import authenticate, authorize
from response import success, success_list
from serializers import (
    ser_order, ser_addon, ser_leg, ser_change_request, ser_ledger, ser_reservation,
)
from services import calculations
from services.helpers import (
    get_or_404, append_ledger, ledger_balance, recompute_route,
    order_reservation, staffing_demand, require_order_version,
    parse_order_version, check_order_version,
)

bp = Blueprint("orders", __name__)

LIFECYCLE = {"DRAFT", "CONFIRMED", "GUARANTEED", "FULFILLED", "CANCELLED"}
SETTLEMENT = {"UNBILLED", "DEPOSIT_HELD", "INVOICED", "SETTLED", "REFUNDED", "FORFEITED"}


# ---------------------------------------------------------------------------
# Ownership: Client-acted order operations (PRD §2.1, priority 3)
# ---------------------------------------------------------------------------
def check_order_ownership(user_id, role, order):
    if role == "Client" and order["client_id"] != user_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "client does not own this order")


def _validate_dietary(dietary_counts, headcount):
    if not isinstance(dietary_counts, dict):
        raise err(ERR_INVALID_REQUEST, "dietary_counts must be an object")
    total = 0
    for k, v in dietary_counts.items():
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise err(ERR_INVALID_REQUEST, "dietary_counts values must be non-negative integers")
        total += v
    if total > headcount:
        raise err(ERR_DIETARY_EXCEEDS_HEADCOUNT,
                  "sum of dietary_counts exceeds in-scope headcount")


# ===========================================================================
# Create / list / get / edit
# ===========================================================================
@bp.route("/catering/orders", methods=["POST"])
def create_order():
    user_id, role = authenticate()
    authorize(role, {"Client", "SalesCoordinator"})
    body = get_json()

    # existence (left-to-right): client, package, venue (PRD §2.6)
    client_id = require(body, "client_id")
    if not isinstance(client_id, str):
        raise err(ERR_INVALID_REQUEST, "client_id must be a string")
    client = get_or_404(db.clients, client_id)
    package_id = require(body, "package_id")
    if not isinstance(package_id, str):
        raise err(ERR_INVALID_REQUEST, "package_id must be a string")
    package = get_or_404(db.packages, package_id)
    venue_id = require(body, "venue_id")
    if not isinstance(venue_id, str):
        raise err(ERR_INVALID_REQUEST, "venue_id must be a string")
    get_or_404(db.venues, venue_id)

    # ownership: a Client may only open its own orders (PRD §2.1)
    if role == "Client" and client_id != user_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "client may only create its own orders")

    booked_headcount = require_int(body, "booked_headcount", minimum=1)
    event_start = parse_dt(require(body, "event_start"))
    event_end = parse_dt(require(body, "event_end"))
    dietary_counts = body.get("dietary_counts")
    if dietary_counts is None:
        dietary_counts = {}

    # window validity (PRD §3.2): event_end strictly after event_start
    if event_end <= event_start:
        raise err(ERR_VALIDATION_WINDOW, "event_end must be after event_start")

    # min headcount (PRD §3.2)
    if booked_headcount < package["min_headcount"]:
        raise err(ERR_BELOW_MIN_HEADCOUNT, "booked_headcount below package min_headcount")

    # dietary <= booked headcount in scope (PRD §3.2)
    _validate_dietary(dietary_counts, booked_headcount)

    rec = {
        "client_id": client_id,
        "package_id": package_id,
        "venue_id": venue_id,
        "route_id": None,
        "booked_headcount": booked_headcount,
        "guaranteed_headcount": None,
        "event_start": event_start,
        "event_end": event_end,
        "locked_package_version": None,
        "dietary_counts": dietary_counts,
        "lifecycle_status": "DRAFT",
        "settlement_status": "UNBILLED",
        "provisional_total_cents": 0,
        "final_total_cents": None,
        "deposit_due_cents": 0,
    }
    stamp_create(rec)
    db.orders[rec["id"]] = rec
    return success(ser_order(rec), status=201)


@bp.route("/catering/orders/<oid>", methods=["GET"])
def get_order(oid):
    user_id, role = authenticate()
    authorize(role, {"CateringAdmin", "Client", "SalesCoordinator", "EventCaptain"})
    rec = get_or_404(db.orders, oid)
    check_order_ownership(user_id, role, rec)
    return success(ser_order(rec))


@bp.route("/catering/orders", methods=["GET"])
def list_orders():
    _, role = authenticate()
    authorize(role, {"CateringAdmin", "SalesCoordinator"})
    rows = list(db.orders.values())
    for f in ("client_id", "package_id", "venue_id", "route_id",
              "lifecycle_status", "settlement_status"):
        val = request.args.get(f)
        if val is not None:
            rows = [r for r in rows if r[f] == val]
    page, limit, offset, total = paginate(rows)
    return success_list([ser_order(r) for r in page], limit, offset, total)


@bp.route("/catering/orders/<oid>", methods=["PATCH"])
def edit_order(oid):
    user_id, role = authenticate()
    authorize(role, {"Client", "SalesCoordinator"})
    rec = get_or_404(db.orders, oid)
    check_order_ownership(user_id, role, rec)
    body = get_json()
    expected = parse_order_version(body)
    # edits allowed only while DRAFT (PRD §3.2)
    if rec["lifecycle_status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "edits permitted only while DRAFT")

    check_order_version(expected, rec)

    package = db.packages[rec["package_id"]]

    new_booked = rec["booked_headcount"]
    if "booked_headcount" in body and body["booked_headcount"] is not None:
        new_booked = require_int(body, "booked_headcount", minimum=1)
        if new_booked < package["min_headcount"]:
            raise err(ERR_BELOW_MIN_HEADCOUNT, "booked_headcount below package min_headcount")

    new_start = rec["event_start"]
    if "event_start" in body and body["event_start"] is not None:
        new_start = parse_dt(body["event_start"])
    new_end = rec["event_end"]
    if "event_end" in body and body["event_end"] is not None:
        new_end = parse_dt(body["event_end"])
    if new_end <= new_start:
        raise err(ERR_VALIDATION_WINDOW, "event_end must be after event_start")

    new_dietary = rec["dietary_counts"]
    if "dietary_counts" in body and body["dietary_counts"] is not None:
        new_dietary = body["dietary_counts"]
    _validate_dietary(new_dietary, new_booked)

    rec["booked_headcount"] = new_booked
    rec["event_start"] = new_start
    rec["event_end"] = new_end
    rec["dietary_counts"] = new_dietary
    touch(rec)
    return success(ser_order(rec))


# ===========================================================================
# confirm (DRAFT -> CONFIRMED; settlement UNBILLED -> DEPOSIT_HELD) PRD §3.5
# ===========================================================================
@bp.route("/catering/orders/<oid>/confirm", methods=["POST"])
def confirm_order(oid):
    _, role = authenticate()
    authorize(role, {"SalesCoordinator"})
    order = get_or_404(db.orders, oid)
    body = get_json()
    expected = parse_order_version(body)

    # state (PRD §3.12: state precedes business rules including OCC staleness)
    if order["lifecycle_status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "order is not DRAFT")

    # OCC version mismatch (business rule, after state)
    check_order_version(expected, order)

    package = db.packages[order["package_id"]]
    venue = db.venues[order["venue_id"]]

    # business rules (priority order PRD §3.12):
    # 7 package retired
    if package["status"] != "ACTIVE":
        raise err(ERR_PACKAGE_RETIRED, "package is RETIRED")
    # (booked >= min already enforced at create/edit; re-check defensively)
    if order["booked_headcount"] < package["min_headcount"]:
        raise err(ERR_BELOW_MIN_HEADCOUNT, "booked_headcount below package min_headcount")
    # 8 lead-time / cutoff gate
    hours_out = hours_floor((order["event_start"] - db.logical_now()).total_seconds())
    if hours_out < package["lead_time_hours"]:
        raise err(ERR_LEAD_TIME_VIOLATED, "confirmation inside lead-time window")
    # 10 venue overbooked: count confirmed-or-later, non-cancelled orders at
    # this venue whose half-open [start,end) window overlaps, excluding this
    # order (PRD §3.1 venue field: "confirmed-or-later, non-cancelled orders";
    # SCAFFOLD Venue.max_overlapping_events). DRAFT orders are not counted.
    overlap = 0
    for o in db.orders.values():
        if o["id"] == order["id"]:
            continue
        if o["lifecycle_status"] not in ("CONFIRMED", "GUARANTEED", "FULFILLED"):
            continue
        if o["venue_id"] != order["venue_id"]:
            continue
        # half-open [start,end) overlap
        if o["event_start"] < order["event_end"] and order["event_start"] < o["event_end"]:
            overlap += 1
    if overlap >= venue["max_overlapping_events"]:
        raise err(ERR_VENUE_OVERBOOKED, "venue overlapping-event cap reached")
    # 17 staff pool capacity
    demand = staffing_demand(order["id"])
    if demand > db.staff_remaining():
        raise err(ERR_STAFF_POOL_EXHAUSTED, "staffing reservation exceeds remaining pool")

    # --- side effects (atomic) ---
    order["locked_package_version"] = package["version"]
    order["provisional_total_cents"] = calculations.order_grand_total(order, "provisional")
    order["deposit_due_cents"] = calculations.deposit_amount(order)
    order["settlement_status"] = "DEPOSIT_HELD"
    append_ledger(order["id"], "DEPOSIT_HOLD", order["deposit_due_cents"], "confirmation deposit hold")

    res = {
        "order_id": order["id"],
        "reserved_staff": demand,
        "status": "HELD",
    }
    stamp_create(res)
    db.staffing_reservations[res["id"]] = res

    order["lifecycle_status"] = "CONFIRMED"
    touch(order)
    return success(ser_order(order))


# ===========================================================================
# guarantee (CONFIRMED -> GUARANTEED) PRD §3.6
# ===========================================================================
@bp.route("/catering/orders/<oid>/guarantee", methods=["POST"])
def guarantee_order(oid):
    _, role = authenticate()
    authorize(role, {"SalesCoordinator"})
    order = get_or_404(db.orders, oid)
    body = get_json()
    expected = parse_order_version(body)
    guaranteed_headcount = require_int(body, "guaranteed_headcount", minimum=1)

    if order["lifecycle_status"] != "CONFIRMED":
        raise err(ERR_INVALID_STATE, "order is not CONFIRMED")

    check_order_version(expected, order)

    package = db.packages[order["package_id"]]
    if guaranteed_headcount < package["min_headcount"]:
        raise err(ERR_BELOW_MIN_HEADCOUNT, "guaranteed_headcount below package min_headcount")
    # cannot guarantee a past event (PRD §3.6)
    if db.logical_now() >= order["event_start"]:
        raise err(ERR_INVALID_STATE, "cannot guarantee a past event")
    # no open change request (PRD §3.6)
    for cr in db.change_requests.values():
        if cr["order_id"] == order["id"] and cr["status"] in ("PROPOSED", "COUNTERED"):
            raise err(ERR_OPEN_CHANGE_REQUEST, "open change request blocks guarantee")

    order["guaranteed_headcount"] = guaranteed_headcount
    order["lifecycle_status"] = "GUARANTEED"
    touch(order)
    return success(ser_order(order))


# ===========================================================================
# invoice (settlement DEPOSIT_HELD -> INVOICED) PRD §3.7
# ===========================================================================
@bp.route("/catering/orders/<oid>/invoice", methods=["POST"])
def invoice_order(oid):
    _, role = authenticate()
    authorize(role, {"SalesCoordinator"})
    order = get_or_404(db.orders, oid)
    body = get_json()
    expected = parse_order_version(body)

    if not (order["lifecycle_status"] == "GUARANTEED" and order["settlement_status"] == "DEPOSIT_HELD"):
        raise err(ERR_INVALID_STATE, "order not in GUARANTEED/DEPOSIT_HELD")

    check_order_version(expected, order)

    order["final_total_cents"] = calculations.order_grand_total(order, "final")
    order["settlement_status"] = "INVOICED"
    append_ledger(order["id"], "DEPOSIT_APPLY", -order["deposit_due_cents"], "deposit applied to invoice")
    touch(order)
    return success(ser_order(order))


# ===========================================================================
# payments (append DEPOSIT_APPLY +amount) PRD §3.7
# ===========================================================================
@bp.route("/catering/orders/<oid>/payments", methods=["POST"])
def record_payment(oid):
    user_id, role = authenticate()
    authorize(role, {"Client", "SalesCoordinator"})
    order = get_or_404(db.orders, oid)
    check_order_ownership(user_id, role, order)
    body = get_json()
    require_order_version(body, order)
    amount_cents = require_int(body, "amount_cents")

    if amount_cents <= 0:
        raise err(ERR_INVALID_PAYMENT, "payment amount_cents must be positive")
    if order["final_total_cents"] is None:
        # nothing to pay against yet; an overpayment guard implies an invoice
        raise err(ERR_INVALID_PAYMENT, "order has no invoice to pay against")
    new_balance = ledger_balance(order["id"]) + amount_cents
    if new_balance > order["final_total_cents"]:
        raise err(ERR_INVALID_PAYMENT, "payment would push balance above final_total_cents")

    append_ledger(order["id"], "DEPOSIT_APPLY", amount_cents, "client payment")
    touch(order)
    return success(ser_order(order))


# ===========================================================================
# settle (settlement INVOICED -> SETTLED) PRD §3.7
# ===========================================================================
@bp.route("/catering/orders/<oid>/settle", methods=["POST"])
def settle_order(oid):
    _, role = authenticate()
    authorize(role, {"SalesCoordinator"})
    order = get_or_404(db.orders, oid)
    body = get_json()
    expected = parse_order_version(body)

    if order["settlement_status"] != "INVOICED":
        raise err(ERR_INVALID_STATE, "order is not INVOICED")

    check_order_version(expected, order)

    if ledger_balance(order["id"]) != order["final_total_cents"]:
        raise err(ERR_BALANCE_UNPAID, "ledger balance does not equal final_total_cents")

    order["settlement_status"] = "SETTLED"
    touch(order)
    return success(ser_order(order))


# ===========================================================================
# fulfill (GUARANTEED -> FULFILLED) PRD §3.8
# ===========================================================================
@bp.route("/catering/orders/<oid>/fulfill", methods=["POST"])
def fulfill_order(oid):
    _, role = authenticate()
    authorize(role, {"EventCaptain"})
    order = get_or_404(db.orders, oid)
    body = get_json()
    expected = parse_order_version(body)

    if order["lifecycle_status"] != "GUARANTEED":
        raise err(ERR_INVALID_STATE, "order is not GUARANTEED")
    if order["settlement_status"] != "SETTLED":
        raise err(ERR_INVALID_STATE, "order is not SETTLED")
    legs = [l for l in db.delivery_legs.values() if l["order_id"] == order["id"]]
    if not all(l["stop_status"] == "DELIVERED" for l in legs):
        raise err(ERR_INVALID_STATE, "not every delivery leg is DELIVERED")

    check_order_version(expected, order)

    res = order_reservation(order["id"])
    if res is not None and res["status"] == "HELD":
        res["status"] = "RELEASED"
        touch(res)

    order["lifecycle_status"] = "FULFILLED"
    touch(order)
    return success(ser_order(order))


# ===========================================================================
# cancel (lifecycle -> CANCELLED) PRD §3.9
# ===========================================================================
@bp.route("/catering/orders/<oid>/cancel", methods=["POST"])
def cancel_order(oid):
    user_id, role = authenticate()
    authorize(role, {"Client"})
    order = get_or_404(db.orders, oid)
    check_order_ownership(user_id, role, order)
    body = get_json()
    expected = parse_order_version(body)

    lifecycle = order["lifecycle_status"]
    # state validity (PRD §3.12: state precedes the OCC staleness business rule)
    if lifecycle not in ("DRAFT", "CONFIRMED", "GUARANTEED"):
        raise err(ERR_INVALID_STATE, "order cannot be cancelled from its current state")
    if lifecycle in ("CONFIRMED", "GUARANTEED") and order["settlement_status"] == "SETTLED":
        raise err(ERR_INVALID_STATE, "a settled order cannot be cancelled")

    check_order_version(expected, order)

    if lifecycle == "DRAFT":
        # draft holds no deposit; settlement stays UNBILLED, no ledger entry
        order["lifecycle_status"] = "CANCELLED"
        touch(order)
        return success(ser_order(order))

    if lifecycle in ("CONFIRMED", "GUARANTEED"):
        fraction, refunded, forfeited = calculations.cancellation_settlement(order)
        if fraction > 0:
            order["settlement_status"] = "REFUNDED"
            append_ledger(order["id"], "REFUND", -refunded, "cancellation refund")
            if forfeited > 0:
                append_ledger(order["id"], "FORFEIT", forfeited, "cancellation forfeit")
        else:
            order["settlement_status"] = "FORFEITED"
            append_ledger(order["id"], "FORFEIT", order["deposit_due_cents"], "cancellation full forfeit")

        # release staffing reservation
        res = order_reservation(order["id"])
        if res is not None and res["status"] == "HELD":
            res["status"] = "RELEASED"
            touch(res)

        # cascade: every PLANNED leg -> FAILED; recompute its route posture
        affected_routes = set()
        for l in db.delivery_legs.values():
            if l["order_id"] == order["id"] and l["stop_status"] == "PLANNED":
                l["stop_status"] = "FAILED"
                touch(l)
                affected_routes.add(l["route_id"])
        for rid in affected_routes:
            if rid in db.routes:
                recompute_route(db.routes[rid])

        order["lifecycle_status"] = "CANCELLED"
        touch(order)
        return success(ser_order(order))

    # FULFILLED or already CANCELLED
    raise err(ERR_INVALID_STATE, "order cannot be cancelled from its current state")


# ===========================================================================
# Order sub-resource listings (reverse-reachability) PRD §2.6
# ===========================================================================
@bp.route("/catering/orders/<oid>/add-ons", methods=["GET"])
def list_order_addons(oid):
    user_id, role = authenticate()
    authorize(role, {"CateringAdmin", "Client", "SalesCoordinator"})
    order = get_or_404(db.orders, oid)
    check_order_ownership(user_id, role, order)
    rows = [a for a in db.add_ons.values() if a["order_id"] == oid]
    page, limit, offset, total = paginate(rows)
    return success_list([ser_addon(r) for r in page], limit, offset, total)


@bp.route("/catering/orders/<oid>/delivery-legs", methods=["GET"])
def list_order_legs(oid):
    user_id, role = authenticate()
    authorize(role, {"CateringAdmin", "Client", "SalesCoordinator", "EventCaptain"})
    order = get_or_404(db.orders, oid)
    check_order_ownership(user_id, role, order)
    rows = [l for l in db.delivery_legs.values() if l["order_id"] == oid]
    page, limit, offset, total = paginate(rows)
    return success_list([ser_leg(r) for r in page], limit, offset, total)


@bp.route("/catering/orders/<oid>/change-requests", methods=["GET"])
def list_order_change_requests(oid):
    user_id, role = authenticate()
    authorize(role, {"CateringAdmin", "Client", "SalesCoordinator"})
    order = get_or_404(db.orders, oid)
    check_order_ownership(user_id, role, order)
    rows = [c for c in db.change_requests.values() if c["order_id"] == oid]
    page, limit, offset, total = paginate(rows)
    return success_list([ser_change_request(r) for r in page], limit, offset, total)


@bp.route("/catering/orders/<oid>/ledger", methods=["GET"])
def list_order_ledger(oid):
    user_id, role = authenticate()
    authorize(role, {"CateringAdmin", "Client", "SalesCoordinator"})
    order = get_or_404(db.orders, oid)
    check_order_ownership(user_id, role, order)
    rows = [e for e in db.ledger_entries.values() if e["order_id"] == oid]
    page, limit, offset, total = paginate(rows)
    return success_list([ser_ledger(r) for r in page], limit, offset, total)


@bp.route("/catering/orders/<oid>/staffing-reservation", methods=["GET"])
def list_order_staffing(oid):
    _, role = authenticate()
    authorize(role, {"CateringAdmin", "SalesCoordinator"})
    get_or_404(db.orders, oid)
    rows = [r for r in db.staffing_reservations.values() if r["order_id"] == oid]
    page, limit, offset, total = paginate(rows)
    return success_list([ser_reservation(r) for r in page], limit, offset, total)


# ===========================================================================
# Add-on create + fetch (PRD §3.3)
# ===========================================================================
@bp.route("/catering/orders/<oid>/add-ons", methods=["POST"])
def create_addon(oid):
    user_id, role = authenticate()
    authorize(role, {"Client", "SalesCoordinator"})
    order = get_or_404(db.orders, oid)
    check_order_ownership(user_id, role, order)
    body = get_json()

    # add-ons only while DRAFT (PRD §3.3)
    if order["lifecycle_status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "add-ons may only be attached while DRAFT")

    from common import require_enum
    kind = require_enum(body, "kind", {"DELIVERY", "SETUP", "STAFFING"})
    unit_cents = require_int(body, "unit_cents", minimum=0)
    quantity = require_int(body, "quantity", minimum=1)
    per_head_scaled = body.get("per_head_scaled")
    if per_head_scaled is None:
        per_head_scaled = False
    if not isinstance(per_head_scaled, bool):
        raise err(ERR_INVALID_REQUEST, "per_head_scaled must be a boolean")
    staff_ratio = body.get("staff_ratio")
    if per_head_scaled:
        if staff_ratio is None or isinstance(staff_ratio, bool) or not isinstance(staff_ratio, int) or staff_ratio < 1:
            raise err(ERR_INVALID_REQUEST, "staff_ratio must be an integer >= 1 when per_head_scaled is true")
    else:
        staff_ratio = None

    rec = {
        "order_id": oid,
        "kind": kind,
        "unit_cents": unit_cents,
        "quantity": quantity,
        "per_head_scaled": per_head_scaled,
        "staff_ratio": staff_ratio,
    }
    stamp_create(rec)
    db.add_ons[rec["id"]] = rec
    return success(ser_addon(rec), status=201)


@bp.route("/catering/add-ons/<aid>", methods=["GET"])
def get_addon(aid):
    _, role = authenticate()
    authorize(role, {"CateringAdmin", "Client", "SalesCoordinator"})
    rec = get_or_404(db.add_ons, aid)
    return success(ser_addon(rec))
