"""PressOrder endpoints: intake, quote, confirm, tooling start, schedule
commits, production events, cancel, plus child-collection list endpoints."""

import math
from datetime import timedelta

from flask import Blueprint, request

import db
import serializers
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_PRESS_ORDER_NOT_FOUND,
    ERR_RELEASE_NOT_FOUND, ERR_ORDER_BELOW_MINIMUM, ERR_VARIANT_SUM_MISMATCH,
    ERR_VARIANT_BELOW_MINIMUM, ERR_STALE_VERSION, ERR_ORDER_INVALID_STATE,
    ERR_CUSTOMER_SUSPENDED, ERR_CREDIT_LIMIT_EXCEEDED,
    ERR_LEAD_TIME_VIOLATION, ERR_PRESS_LINE_NOT_FOUND,
    ERR_PRESS_DATE_NOT_REACHED, ERR_SLOT_UNITS_MISMATCH,
    ERR_UNAUTHORIZED_ROLE,
)
from middleware import (
    get_auth, require_role, require_customer_ownership, get_pagination,
    apply_pagination,
)
from response import success_object, success_list
from services import pricing, risk as risk_service, scheduling
from services.constants import (
    COLOR_CONFIGS, COLOR_FAMILY_OF, VARIANT_MIN_QTY, TOLERANCE,
    SIDES_CHOICES, PLATING_ROUTES, OVERRUN_POLICIES, ORDER_MIN_UNITS,
    MIN_LEAD_DAYS,
)
from .releases import valid_date_str, get_release_or_404
from .customers import get_customer_or_404

bp = Blueprint("press_orders", __name__)


def get_order_or_404(order_id):
    o = db.press_orders.get(order_id)
    if not o:
        raise ApiError(ERR_PRESS_ORDER_NOT_FOUND, "Press order id does not exist", 404)
    return o


def validate_variants(variants, quantity_ordered):
    """Variant composition rules (priority 8)."""
    if not isinstance(variants, list) or not variants:
        raise ApiError(ERR_VARIANT_SUM_MISMATCH, "variants must be a non-empty array", 422)
    total = 0
    for v in variants:
        if not isinstance(v, dict):
            raise ApiError(ERR_INVALID_REQUEST, "variant entries must be objects", 400)
        cfg = v.get("color_config")
        qty = v.get("quantity")
        if cfg not in COLOR_CONFIGS:
            raise ApiError(ERR_INVALID_REQUEST, "invalid color_config", 400)
        if not isinstance(qty, int) or isinstance(qty, bool) or qty <= 0:
            raise ApiError(ERR_INVALID_REQUEST, "variant quantity must be a positive integer", 400)
        total += qty
    if total != quantity_ordered:
        raise ApiError(ERR_VARIANT_SUM_MISMATCH, "Variant quantities do not sum to quantity_ordered", 422)
    for v in variants:
        if v["quantity"] < VARIANT_MIN_QTY[v["color_config"]]:
            raise ApiError(
                ERR_VARIANT_BELOW_MINIMUM,
                f"Variant {v['color_config']} is below its minimum quantity",
                422,
            )


def derive_tolerance(variants):
    return min(TOLERANCE[v["color_config"]] for v in variants)


def derive_color_family(variants):
    best = None
    for v in variants:
        if best is None or v["quantity"] > best["quantity"]:
            best = v
    return COLOR_FAMILY_OF[best["color_config"]]


@bp.route("/press-orders", methods=["POST"])
def create_press_order():
    _, role = get_auth()
    require_role(role, ["CustomerServiceRep"])
    body = request.get_json(silent=True) or {}

    release_id = body.get("release_id")
    quantity_ordered = body.get("quantity_ordered")
    sides = body.get("sides", 2)
    plating_route = body.get("plating_route", "TWO_STEP")
    variants = body.get("variants")
    overrun_policy = body.get("overrun_policy")
    requested_completion_date = body.get("requested_completion_date")

    if not isinstance(release_id, str) or not release_id:
        raise ApiError(ERR_INVALID_REQUEST, "release_id is required", 400)
    release = db.releases.get(release_id)
    if not release:
        raise ApiError(ERR_RELEASE_NOT_FOUND, "release_id does not exist", 404)

    # shape
    if not isinstance(quantity_ordered, int) or isinstance(quantity_ordered, bool) or quantity_ordered <= 0:
        raise ApiError(ERR_INVALID_REQUEST, "quantity_ordered must be a positive integer", 400)
    if sides not in SIDES_CHOICES or isinstance(sides, bool):
        raise ApiError(ERR_INVALID_REQUEST, "sides must be 1 or 2", 400)
    if plating_route not in PLATING_ROUTES:
        raise ApiError(ERR_INVALID_REQUEST, "invalid plating_route", 400)
    if overrun_policy is not None and overrun_policy not in OVERRUN_POLICIES:
        raise ApiError(ERR_INVALID_REQUEST, "invalid overrun_policy", 400)
    if requested_completion_date is not None and not valid_date_str(requested_completion_date):
        raise ApiError(ERR_INVALID_REQUEST, "requested_completion_date must be yyyy-mm-dd", 400)
    if not isinstance(variants, list):
        raise ApiError(ERR_INVALID_REQUEST, "variants must be an array", 400)

    # composition (priority 8): order minimum, variant sum, per-variant min
    if quantity_ordered < ORDER_MIN_UNITS:
        raise ApiError(ERR_ORDER_BELOW_MINIMUM, "quantity_ordered is below the 100 unit minimum", 422)
    validate_variants(variants, quantity_ordered)

    # temporal (priority 10): lead time
    if requested_completion_date is not None:
        from datetime import date as _date
        req = _date.fromisoformat(requested_completion_date)
        min_date = db.today_logical() + timedelta(days=MIN_LEAD_DAYS)
        if req < min_date:
            raise ApiError(
                ERR_LEAD_TIME_VIOLATION,
                "requested_completion_date is earlier than today + 21 days",
                422,
            )

    now = db.timestamp_now()
    order = {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "release_id": release_id,
        "quantity_ordered": quantity_ordered,
        "sides": sides,
        "plating_route": plating_route,
        "overrun_policy": overrun_policy,
        "variants": [{"color_config": v["color_config"], "quantity": v["quantity"]} for v in variants],
        "requested_completion_date": requested_completion_date,
        "production_status": "DRAFT",
        "billing_status": "UNBILLED",
        "discount_pct_snapshot": 0,
        "tolerance_pct": derive_tolerance(variants),
        "color_family": derive_color_family(variants),
        "intake_seq": db.next_intake_seq(),
        "quote_pressing_cents": 0,
        "quote_surcharge_cents": 0,
        "quote_tooling_cents": 0,
        "quote_setup_cents": 0,
        "quote_subtotal_cents": 0,
        "quote_discount_cents": 0,
        "quote_total_cents": 0,
        "tp_round": 0,
        "repress_round": 0,
        "repress_fault": "NONE",
        "pressed_units_total": 0,
        "rejected_units_total": 0,
        "accepted_units": 0,
        "cancel_fee_cents": 0,
        "_tp_revision_count": 0,
    }
    db.press_orders[order["id"]] = order
    return success_object(serializers.press_order(order), 201)


@bp.route("/press-orders", methods=["GET"])
def list_press_orders():
    get_auth()
    limit, offset = get_pagination()
    release_id = request.args.get("release_id")
    production_status = request.args.get("production_status")
    items = list(db.press_orders.values())
    if release_id is not None:
        items = [o for o in items if o["release_id"] == release_id]
    if production_status is not None:
        items = [o for o in items if o["production_status"] == production_status]
    page, total = apply_pagination(items, limit, offset)
    return success_list([serializers.press_order(o) for o in page], limit, offset, total)


@bp.route("/press-orders/<oid>", methods=["GET"])
def get_press_order(oid):
    get_auth()
    return success_object(serializers.press_order(get_order_or_404(oid)))


@bp.route("/press-orders/<oid>/quotes", methods=["POST"])
def quote_order(oid):
    _, role = get_auth()
    require_role(role, ["CustomerServiceRep"])
    order = get_order_or_404(oid)
    body = request.get_json(silent=True) or {}

    expected = body.get("expected_press_order_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError(ERR_INVALID_REQUEST, "expected_press_order_version is required", 400)

    # state precondition (priority 5)
    if order["production_status"] not in ("DRAFT", "QUOTED"):
        raise ApiError(ERR_ORDER_INVALID_STATE, "Order must be DRAFT or QUOTED to quote", 409)

    # OCC (requote stale version)
    if expected != order["version"]:
        raise ApiError(ERR_STALE_VERSION, "expected_press_order_version is stale", 412)

    # variant composition re-enforced at quote time (priority 8)
    if order["quantity_ordered"] < ORDER_MIN_UNITS:
        raise ApiError(ERR_ORDER_BELOW_MINIMUM, "quantity_ordered is below the 100 unit minimum", 422)
    validate_variants(order["variants"], order["quantity_ordered"])

    release = db.releases[order["release_id"]]
    customer = db.customers[release["customer_id"]]
    quote = pricing.compute_quote(order, release, customer)
    order.update(quote)
    order["production_status"] = "QUOTED"
    order["version"] += 1
    order["updated_at"] = db.timestamp_now()
    return success_object(serializers.press_order(order))


@bp.route("/press-orders/<oid>/confirm", methods=["POST"])
def confirm_order(oid):
    user_id, role = get_auth()
    require_role(role, ["Customer"])
    order = get_order_or_404(oid)
    release = get_release_or_404(order["release_id"])
    require_customer_ownership(user_id, role, release)

    body = request.get_json(silent=True) or {}
    expected = body.get("expected_press_order_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError(ERR_INVALID_REQUEST, "expected_press_order_version is required", 400)

    if order["production_status"] != "QUOTED":
        raise ApiError(ERR_ORDER_INVALID_STATE, "Order must be QUOTED to confirm", 409)
    if expected != order["version"]:
        raise ApiError(ERR_STALE_VERSION, "expected_press_order_version is stale", 412)

    customer = db.customers[release["customer_id"]]
    if customer["status"] != "ACTIVE":
        raise ApiError(ERR_CUSTOMER_SUSPENDED, "Customer is SUSPENDED", 409)

    outstanding = pricing.credit_outstanding(customer["id"], db.invoices)
    if outstanding + order["quote_total_cents"] > customer["credit_limit_cents"]:
        raise ApiError(ERR_CREDIT_LIMIT_EXCEEDED, "Credit limit exceeded", 402)

    order["production_status"] = "CONFIRMED"
    order["version"] += 1
    order["updated_at"] = db.timestamp_now()

    # First confirm flips the release SETUP -> IN_PRODUCTION
    if release["status"] == "SETUP":
        release["status"] = "IN_PRODUCTION"
        release["version"] += 1
        release["updated_at"] = db.timestamp_now()

    return success_object(serializers.press_order(order))


@bp.route("/press-orders/<oid>/start-tooling", methods=["POST"])
def start_tooling(oid):
    _, role = get_auth()
    require_role(role, ["ProductionPlanner"])
    order = get_order_or_404(oid)

    if order["production_status"] != "CONFIRMED":
        raise ApiError(ERR_ORDER_INVALID_STATE, "Order must be CONFIRMED to start tooling", 409)

    now = db.timestamp_now()
    job = {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "press_order_id": order["id"],
        "round_number": order["tp_round"] + 1,
        "status": "QUEUED",
        "attempt_count": 0,
        "plating_bath_id": None,
        "plating_start": None,
        "plating_end": None,
        "defect_note": None,
    }
    db.tooling_jobs[job["id"]] = job

    order["production_status"] = "TOOLING"
    order["version"] += 1
    order["updated_at"] = db.timestamp_now()
    return success_object(serializers.press_order(order))


@bp.route("/press-orders/<oid>/schedule-commits", methods=["POST"])
def schedule_commit(oid):
    _, role = get_auth()
    require_role(role, ["ProductionPlanner"])
    order = get_order_or_404(oid)
    body = request.get_json(silent=True) or {}

    expected = body.get("expected_press_order_version")
    slots = body.get("slots")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError(ERR_INVALID_REQUEST, "expected_press_order_version is required", 400)
    if not isinstance(slots, list) or not slots:
        raise ApiError(ERR_INVALID_REQUEST, "slots must be a non-empty array", 400)

    # shape: each slot needs press_line_id, date, start_hour, end_hour,
    # planned_units
    parsed = []
    for s in slots:
        if not isinstance(s, dict):
            raise ApiError(ERR_INVALID_REQUEST, "slot entries must be objects", 400)
        line_id = s.get("press_line_id")
        d = s.get("date")
        sh = s.get("start_hour")
        eh = s.get("end_hour")
        pu = s.get("planned_units")
        if not isinstance(line_id, str) or not line_id:
            raise ApiError(ERR_INVALID_REQUEST, "slot press_line_id is required", 400)
        line = db.press_lines.get(line_id)
        if not line:
            raise ApiError(ERR_PRESS_LINE_NOT_FOUND, "press_line_id does not exist", 404)
        if not valid_date_str(d):
            raise ApiError(ERR_INVALID_REQUEST, "slot date must be yyyy-mm-dd", 400)
        if not isinstance(sh, int) or isinstance(sh, bool) or not isinstance(eh, int) or isinstance(eh, bool):
            raise ApiError(ERR_INVALID_REQUEST, "slot hours must be integers", 400)
        if not isinstance(pu, int) or isinstance(pu, bool) or pu <= 0:
            raise ApiError(ERR_INVALID_REQUEST, "planned_units must be a positive integer", 400)
        scheduling.validate_production_hours(line, sh, eh)
        parsed.append({"line": line, "date": d, "start_hour": sh, "end_hour": eh, "planned_units": pu})

    # state precondition (priority 5)
    if order["production_status"] != "QUEUED":
        raise ApiError(ERR_ORDER_INVALID_STATE, "Order must be QUEUED to commit a schedule", 409)

    # OCC
    if expected != order["version"]:
        raise ApiError(ERR_STALE_VERSION, "expected_press_order_version is stale", 412)

    # unit feasibility (per-slot and total) — priority 12 per scaffold, but
    # PRD §3.6 lists unit feasibility first; interval occupation is priority 9
    # and capacity is 12. Per the normative priority list: state (5) -> OCC is
    # separate (priority listed under concurrency rules; PRD treats
    # ERR_STALE_VERSION at its own check) -> interval (9) -> temporal (10) ->
    # credit (11) -> capacity (12) which includes SLOT_UNITS_MISMATCH.
    # Check interval occupation before capacity/quota errors.
    candidates_by_line_date = {}
    for p in parsed:
        key = (p["line"]["id"], p["date"])
        candidates_by_line_date.setdefault(key, []).append(p)

    for (line_id, d), cand_list in candidates_by_line_date.items():
        new_slots = [
            {"start_hour": c["start_hour"], "end_hour": c["end_hour"],
             "color_family": order["color_family"]}
            for c in cand_list
        ]
        scheduling.check_slot_conflicts(line_id, d, new_slots)

    # capacity + unit feasibility (priority 12)
    remaining_requirement = order["quantity_ordered"] - order["accepted_units"]
    total_planned = sum(p["planned_units"] for p in parsed)
    if total_planned < remaining_requirement:
        raise ApiError(
            ERR_SLOT_UNITS_MISMATCH,
            "Total planned units are below the order's remaining requirement",
            422,
        )
    for p in parsed:
        rate = scheduling.hourly_rate(p["line"])
        hours = p["end_hour"] - p["start_hour"]
        if p["planned_units"] > hours * rate:
            raise ApiError(
                ERR_SLOT_UNITS_MISMATCH,
                "A slot's planned_units exceeds hours x hourly rate",
                422,
            )

    # daily capacity per line+date (including existing slots)
    adds = {}
    for p in parsed:
        adds.setdefault(p["line"]["id"], {}).setdefault(p["date"], 0)
        adds[p["line"]["id"]][p["date"]] += p["planned_units"]
    for line_id, by_date in adds.items():
        scheduling.check_daily_capacity(db.press_lines[line_id], None, by_date)

    # create slots
    now = db.timestamp_now()
    for p in parsed:
        slot = {
            "id": db.new_id(),
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "press_line_id": p["line"]["id"],
            "press_order_id": order["id"],
            "slot_kind": "PRODUCTION",
            "date": p["date"],
            "start_hour": p["start_hour"],
            "end_hour": p["end_hour"],
            "planned_units": p["planned_units"],
            "color_family": order["color_family"],
            "freed": False,
        }
        db.press_slots[slot["id"]] = slot

    order["production_status"] = "SCHEDULED"
    order["version"] += 1
    order["updated_at"] = now

    release = db.releases[order["release_id"]]
    risk_service.recompute_release_risk(release, "SCHEDULE", order["id"])
    return success_object(serializers.press_order(order))


@bp.route("/press-orders/<oid>/production-events", methods=["POST"])
def production_event(oid):
    _, role = get_auth()
    require_role(role, ["PressOperator"])
    order = get_order_or_404(oid)
    body = request.get_json(silent=True) or {}
    event = body.get("event")
    if event not in ("START_PRESSING", "COMPLETE_PRESSING"):
        raise ApiError(ERR_INVALID_REQUEST, "event must be START_PRESSING or COMPLETE_PRESSING", 400)

    if event == "START_PRESSING":
        if order["production_status"] != "SCHEDULED":
            raise ApiError(ERR_ORDER_INVALID_STATE, "Order must be SCHEDULED to start pressing", 409)
        # temporal: clock date >= earliest slot date
        slot_dates = [
            s["date"] for s in db.press_slots.values()
            if s.get("press_order_id") == order["id"]
            and s["slot_kind"] == "PRODUCTION" and not s.get("freed", False)
        ]
        if slot_dates and db.today_logical().isoformat() < min(slot_dates):
            raise ApiError(
                ERR_PRESS_DATE_NOT_REACHED,
                "The logical clock date has not reached the order's earliest slot date",
                409,
            )
        order["production_status"] = "PRESSING"
    else:
        if order["production_status"] != "PRESSING":
            raise ApiError(ERR_ORDER_INVALID_STATE, "Order must be PRESSING to complete pressing", 409)
        order["production_status"] = "QC_REVIEW"

    order["version"] += 1
    order["updated_at"] = db.timestamp_now()
    return success_object(serializers.press_order(order))


@bp.route("/press-orders/<oid>/cancel", methods=["POST"])
def cancel_order(oid):
    _, role = get_auth()
    require_role(role, ["CustomerServiceRep"])
    order = get_order_or_404(oid)
    body = request.get_json(silent=True) or {}
    # reason is optional and informational

    if order["production_status"] in ("PRESSING", "QC_REVIEW", "COMPLETED", "CANCELLED"):
        raise ApiError(ERR_ORDER_INVALID_STATE, "Order cannot be cancelled from its current state", 409)

    prior_state = order["production_status"]
    fee = pricing.cancellation_fee(order)
    order["cancel_fee_cents"] = fee
    order["production_status"] = "CANCELLED"
    order["version"] += 1
    order["updated_at"] = db.timestamp_now()

    release = db.releases[order["release_id"]]

    # auto-create CANCELLATION_FEE invoice when fee > 0
    if fee > 0:
        now = db.timestamp_now()
        invoice = {
            "id": db.new_id(),
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "press_order_id": order["id"],
            "customer_id": release["customer_id"],
            "parent_invoice_id": None,
            "kind": "CANCELLATION_FEE",
            "gross_cents": fee,
            "discount_cents": 0,
            "net_cents": fee,
            "paid_cents": 0,
            "credited_cents": 0,
            "lines": [{
                "label": "cancellation_fee",
                "gross_cents": fee,
                "discount_cents": 0,
                "net_cents": fee,
            }],
            "status": "ISSUED",
        }
        db.invoices[invoice["id"]] = invoice
        if order["billing_status"] == "UNBILLED":
            order["billing_status"] = "INVOICED"
        customer = db.customers.get(release["customer_id"])
        if customer is not None:
            customer["trailing_billed_cents"] += invoice["net_cents"]
            customer["updated_at"] = db.timestamp_now()

    # cascade children terminal
    for job in db.tooling_jobs.values():
        if job["press_order_id"] == order["id"] and job["status"] in (
            "QUEUED", "CUTTING", "AWAITING_BATH", "PLATING", "FAILED"
        ):
            job["status"] = "CANCELLED"
            job["version"] += 1
            job["updated_at"] = db.timestamp_now()
    for tp in db.test_pressings.values():
        if tp["press_order_id"] == order["id"] and tp["status"] in ("PRODUCED", "UNDER_REVIEW"):
            tp["status"] = "SUPERSEDED"
            tp["version"] += 1
            tp["updated_at"] = db.timestamp_now()
    for pj in db.print_jobs.values():
        if pj["press_order_id"] == order["id"] and pj["status"] in ("CREATED", "AT_PRINTER", "PROOF_REVIEW"):
            pj["status"] = "CANCELLED"
            pj["version"] += 1
            pj["updated_at"] = db.timestamp_now()

    # free slots + waitlist promotion when cancelling from SCHEDULED
    if prior_state == "SCHEDULED":
        freed = []
        for s in db.press_slots.values():
            if (s.get("press_order_id") == order["id"]
                    and s["slot_kind"] == "PRODUCTION" and not s.get("freed", False)):
                s["freed"] = True
                s["version"] += 1
                s["updated_at"] = db.timestamp_now()
                freed.append(dict(s))
        if freed:
            scheduling.waitlist_promotion(freed, order["id"])

    # release risk + possible FULFILLED flip
    risk_service.recompute_release_risk(release, "SCHEDULE", order["id"])
    maybe_fulfill_release(release)

    return success_object(serializers.press_order(order))


def maybe_fulfill_release(release):
    """Release -> FULFILLED when every order of the release is terminal."""
    orders = [o for o in db.press_orders.values() if o["release_id"] == release["id"]]
    if orders and all(o["production_status"] in ("COMPLETED", "CANCELLED") for o in orders):
        if release["status"] != "FULFILLED":
            release["status"] = "FULFILLED"
            release["version"] += 1
            release["updated_at"] = db.timestamp_now()
            # risk view: no open orders -> null projection
            release["projected_completion_date"] = None
            release["slack_days"] = None
            release["risk_level"] = "ON_TRACK"


# --- Reverse-reachability list endpoints --------------------------------------

@bp.route("/press-orders/<oid>/slots", methods=["GET"])
def order_slots(oid):
    get_auth()
    order = get_order_or_404(oid)
    limit, offset = get_pagination()
    items = [s for s in db.press_slots.values() if s.get("press_order_id") == order["id"]]
    page, total = apply_pagination(items, limit, offset)
    return success_list([serializers.press_slot(s) for s in page], limit, offset, total)


@bp.route("/press-orders/<oid>/tooling-jobs", methods=["GET"])
def order_tooling_jobs(oid):
    get_auth()
    order = get_order_or_404(oid)
    limit, offset = get_pagination()
    items = [j for j in db.tooling_jobs.values() if j["press_order_id"] == order["id"]]
    page, total = apply_pagination(items, limit, offset)
    return success_list([serializers.tooling_job(j) for j in page], limit, offset, total)


@bp.route("/press-orders/<oid>/test-pressings", methods=["GET"])
def order_test_pressings(oid):
    get_auth()
    order = get_order_or_404(oid)
    limit, offset = get_pagination()
    items = [t for t in db.test_pressings.values() if t["press_order_id"] == order["id"]]
    page, total = apply_pagination(items, limit, offset)
    return success_list([serializers.test_pressing(t) for t in page], limit, offset, total)


@bp.route("/press-orders/<oid>/print-jobs", methods=["GET"])
def order_print_jobs(oid):
    get_auth()
    order = get_order_or_404(oid)
    limit, offset = get_pagination()
    items = [p for p in db.print_jobs.values() if p["press_order_id"] == order["id"]]
    page, total = apply_pagination(items, limit, offset)
    return success_list([serializers.print_job(p) for p in page], limit, offset, total)


@bp.route("/press-orders/<oid>/qc-reports", methods=["GET"])
def order_qc_reports(oid):
    get_auth()
    order = get_order_or_404(oid)
    limit, offset = get_pagination()
    items = [q for q in db.qc_reports.values() if q["press_order_id"] == order["id"]]
    page, total = apply_pagination(items, limit, offset)
    return success_list([serializers.qc_report(q) for q in page], limit, offset, total)


@bp.route("/press-orders/<oid>/delay-notices", methods=["GET"])
def order_delay_notices(oid):
    get_auth()
    order = get_order_or_404(oid)
    limit, offset = get_pagination()
    items = [n for n in db.delay_notices.values() if n["press_order_id"] == order["id"]]
    page, total = apply_pagination(items, limit, offset)
    return success_list([serializers.delay_notice(n) for n in page], limit, offset, total)


@bp.route("/press-orders/<oid>/inventory-lots", methods=["GET"])
def order_inventory_lots(oid):
    get_auth()
    order = get_order_or_404(oid)
    limit, offset = get_pagination()
    items = [l for l in db.inventory_lots.values() if l["release_id"] == order["release_id"]]
    page, total = apply_pagination(items, limit, offset)
    return success_list([serializers.inventory_lot(l) for l in page], limit, offset, total)
