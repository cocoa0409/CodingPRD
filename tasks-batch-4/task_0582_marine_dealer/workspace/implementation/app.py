"""Marine Dealer API — Flask application (PRD task 0582).

In-memory store; empty on every boot. Listens on $PORT (default 10000), 0.0.0.0.
"""
import os
from functools import wraps
from datetime import timedelta

from flask import Flask, request

from store import (db, ROLES, new_record, touch, now, parse_dt,
                   CURTAILMENT_DUE_DAYS, BAY_BUFFER_MINUTES)
from errors import (ApiError, err,
                    ERR_UNAUTHENTICATED, ERR_FORBIDDEN, ERR_NOT_FOUND,
                    ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_STALE_UNIT_VERSION,
                    ERR_UNIT_NOT_AVAILABLE, ERR_UNIT_HAS_ACTIVE_DEAL,
                    ERR_DOWN_PAYMENT_TOO_LOW, ERR_OPEN_RECALL_BLOCKS_DELIVERY,
                    ERR_PART_REQUIRED_FOR_LINE, ERR_HOURS_REQUIRED_FOR_LABOR,
                    ERR_INVALID_QUANTITY, ERR_INSUFFICIENT_STOCK,
                    ERR_RESERVATION_DATES_INVALID, ERR_SCHEDULE_WINDOW_INVALID,
                    ERR_BERTH_CLOSED, ERR_UNIT_EXCEEDS_BERTH, ERR_BERTH_DOUBLE_BOOKED,
                    ERR_BAY_SCHEDULE_CONFLICT, ERR_CURTAILMENT_NOT_DUE,
                    ERR_CURTAILMENT_EXCEEDS_PRINCIPAL)
from response import object_response, array_response, error_response
import calc
import validate as V
import serializers as S

app = Flask(__name__)

ALL_ROLES = ("Manager", "SalesRep", "ServiceAdvisor", "PartsClerk")

UNIT_TYPES = {"BOAT", "MOTOR", "TRAILER"}
ACQ_TYPES = {"FLOOR_PLAN", "CASH", "CONSIGNMENT", "TRADE_IN"}
FIN_TYPES = {"CASH", "RETAIL_FINANCE"}
RO_TYPES = {"DIAGNOSTIC", "FLAT_RATE", "CUSTOM"}
FLAT_CODES = {"WINTERIZE", "REPOWER"}
LINE_TYPES = {"LABOR", "PART"}
BERTH_TYPES = {"WET_SLIP", "DRY_RACK"}
BAY_TYPES = {"RIGGING", "MECHANICAL", "HAUL_OUT"}


# ---- error handling ---------------------------------------------------------

@app.errorhandler(ApiError)
def _handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def _handle_404(e):
    return error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def _handle_405(e):
    return error_response("ERR_NOT_FOUND", "Method not allowed", 404)


@app.errorhandler(Exception)
def _handle_uncaught(e):
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.message, e.http_status)
    return error_response("ERR_INTERNAL", "Internal server error: %s" % e, 500)


# ---- auth / rbac ------------------------------------------------------------

def require_roles(*allowed):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role = request.headers.get("X-User-Role")
            if not role or role not in ROLES:
                raise err(ERR_UNAUTHENTICATED, "Missing or unrecognized X-User-Role header")
            if role not in allowed:
                raise err(ERR_FORBIDDEN, "Role '%s' may not perform this operation" % role)
            return fn(*args, **kwargs)
        return wrapper
    return deco


# ---- helpers ----------------------------------------------------------------

def get_body():
    b = request.get_json(silent=True)
    if b is None:
        b = {}
    if not isinstance(b, dict):
        raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return b


def _get(coll, rid):
    rec = coll.get(rid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Referenced resource does not exist")
    return rec


def sorted_records(coll):
    return sorted(coll.values(), key=lambda r: (r["created_at"], r["_seq"]))


def paginate(items):
    limit = 10
    offset = 0
    lim_raw = request.args.get("limit")
    off_raw = request.args.get("offset")
    if lim_raw is not None:
        try:
            limit = int(lim_raw)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, "limit must be an integer")
        limit = max(1, min(100, limit))
    if off_raw is not None:
        try:
            offset = int(off_raw)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, "offset must be an integer")
        offset = max(0, offset)
    total = len(items)
    page = items[offset:offset + limit]
    return page, limit, offset, total


def req_dt(body, field):
    """Required datetime string -> aware datetime, else 400."""
    raw = V.req_str(body, field)
    dt = parse_dt(raw)
    if dt is None:
        raise err(ERR_INVALID_REQUEST, "Field '%s' must be an ISO 8601 timestamp" % field)
    return dt


def active_consignment_for_unit(unit_id):
    for c in db.consignments.values():
        if c["unit_id"] == unit_id and c["status"] == "ACTIVE":
            return c
    return None


# =============================================================================
# Logical clock
# =============================================================================

@app.route("/_clock/set_current_utc", methods=["POST"])
@require_roles(*ALL_ROLES)
def clock_set():
    body = get_body()
    dt = req_dt(body, "to_iso8601")
    db.clock = dt
    return object_response({}, 200)


# =============================================================================
# Unit
# =============================================================================

@app.route("/units", methods=["POST"])
@require_roles("Manager")
def unit_create():
    body = get_body()
    rec = new_record({
        "hin": V.req_str(body, "hin"),
        "make": V.req_str(body, "make"),
        "model": V.req_str(body, "model"),
        "model_year": V.req_int(body, "model_year"),
        "unit_type": V.req_enum(body, "unit_type", UNIT_TYPES),
        "length_ft": V.req_num(body, "length_ft"),
        "cost_cents": V.req_int(body, "cost_cents"),
        "list_price_cents": V.req_int(body, "list_price_cents"),
        "acquisition_type": V.req_enum(body, "acquisition_type", ACQ_TYPES),
        "open_recall": V.opt_bool(body, "open_recall", False),
        "status": "INTAKE",
    })
    db.units[rec["id"]] = rec
    return object_response(S.serialize_unit(rec), 201)


@app.route("/units/<rid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def unit_get(rid):
    return object_response(S.serialize_unit(_get(db.units, rid)), 200)


@app.route("/units", methods=["GET"])
@require_roles(*ALL_ROLES)
def unit_list():
    items = sorted_records(db.units)
    status = request.args.get("status")
    if status is not None:
        items = [u for u in items if u["status"] == status]
    acq = request.args.get("acquisition_type")
    if acq is not None:
        items = [u for u in items if u["acquisition_type"] == acq]
    page, limit, offset, total = paginate(items)
    return array_response([S.serialize_unit(u) for u in page], limit, offset, total)


@app.route("/units/<rid>/list", methods=["POST"])
@require_roles("Manager")
def unit_list_for_sale(rid):
    u = _get(db.units, rid)
    if u["status"] != "INTAKE":
        raise err(ERR_INVALID_STATE, "Unit must be INTAKE to be listed")
    u["status"] = "AVAILABLE"
    touch(u)
    return object_response(S.serialize_unit(u), 200)


# =============================================================================
# FloorPlan
# =============================================================================

@app.route("/floor-plans", methods=["POST"])
@require_roles("Manager")
def floor_plan_create():
    body = get_body()
    # existence (priority 3)
    if V.present(body, "unit_id"):
        unit = _get(db.units, body["unit_id"])
    else:
        unit = None
    # structural (priority 4)
    unit_id = V.req_str(body, "unit_id")
    if unit is None:
        unit = _get(db.units, unit_id)
    lender_name = V.req_str(body, "lender_name")
    principal_cents = V.req_int(body, "principal_cents")
    apr_bps = V.req_int(body, "apr_bps")
    advanced_at = req_dt(body, "advanced_at")
    curtailment_pct_bps = V.req_int(body, "curtailment_pct_bps")
    expected_unit_version = V.req_int(body, "expected_unit_version")
    # concurrency (priority 7)
    if expected_unit_version != unit["version"]:
        raise err(ERR_STALE_UNIT_VERSION, "expected_unit_version does not match current Unit.version")
    # supersede prior ACTIVE/CURTAILED plans for the unit
    for fp in list(db.floor_plans.values()):
        if fp["unit_id"] == unit_id and fp["status"] in ("ACTIVE", "CURTAILED"):
            fp["status"] = "SUPERSEDED"
            touch(fp)
    rec = new_record({
        "unit_id": unit_id,
        "lender_name": lender_name,
        "principal_cents": principal_cents,
        "outstanding_principal_cents": principal_cents,
        "apr_bps": apr_bps,
        "advanced_at": advanced_at,
        "curtailment_pct_bps": curtailment_pct_bps,
        "status": "ACTIVE",
        "_payoff_snapshot": None,
        "_pre_payoff_outstanding": None,
    })
    db.floor_plans[rec["id"]] = rec
    # unit.version += 1 (OCC) and floor_plan_balance recomputed (read-time)
    touch(unit)
    return object_response(S.serialize_floor_plan(rec), 201)


@app.route("/floor-plans/<rid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def floor_plan_get(rid):
    return object_response(S.serialize_floor_plan(_get(db.floor_plans, rid)), 200)


@app.route("/floor-plans", methods=["GET"])
@require_roles(*ALL_ROLES)
def floor_plan_list():
    items = sorted_records(db.floor_plans)
    unit_id = request.args.get("unit_id")
    if unit_id is not None:
        items = [f for f in items if f["unit_id"] == unit_id]
    status = request.args.get("status")
    if status is not None:
        items = [f for f in items if f["status"] == status]
    page, limit, offset, total = paginate(items)
    return array_response([S.serialize_floor_plan(f) for f in page], limit, offset, total)


@app.route("/floor-plans/<rid>/curtail", methods=["POST"])
@require_roles("Manager")
def floor_plan_curtail(rid):
    fp = _get(db.floor_plans, rid)
    body = get_body()
    payment_cents = V.req_int(body, "payment_cents")
    # state (priority 8)
    if fp["status"] not in ("ACTIVE", "CURTAILED"):
        raise err(ERR_INVALID_STATE, "Floor plan must be ACTIVE or CURTAILED to curtail")
    # temporal seasoning (priority 18)
    if calc.days_out(now(), fp["advanced_at"]) < CURTAILMENT_DUE_DAYS:
        raise err(ERR_CURTAILMENT_NOT_DUE, "Curtailment not yet due")
    # fiscal (priority 19)
    if payment_cents > fp["outstanding_principal_cents"]:
        raise err(ERR_CURTAILMENT_EXCEEDS_PRINCIPAL, "Payment exceeds outstanding principal")
    fp["outstanding_principal_cents"] -= payment_cents
    fp["status"] = "CURTAILED"
    touch(fp)
    unit = db.units.get(fp["unit_id"])
    if unit is not None:
        touch(unit)  # floor_plan_balance_cents recomputed
    return object_response(S.serialize_floor_plan(fp), 200)


# =============================================================================
# Deal
# =============================================================================

@app.route("/deals", methods=["POST"])
@require_roles("SalesRep")
def deal_create():
    body = get_body()
    if V.present(body, "unit_id"):
        _get(db.units, body["unit_id"])
    unit_id = V.req_str(body, "unit_id")
    _get(db.units, unit_id)
    customer_name = V.req_str(body, "customer_name")
    sale_price_cents = V.req_int(body, "sale_price_cents")
    financing_type = V.req_enum(body, "financing_type", FIN_TYPES)
    tax_rate_bps = V.req_int(body, "tax_rate_bps")
    doc_fee_cents = V.req_int(body, "doc_fee_cents")
    down_payment_cents = V.req_int(body, "down_payment_cents")
    trade_allowance_cents = V.opt_int(body, "trade_allowance_cents", 0)
    trade_lien_payoff_cents = V.opt_int(body, "trade_lien_payoff_cents", 0)
    # business constraint (priority 10)
    for d in db.deals.values():
        if d["unit_id"] == unit_id and d["status"] in ("DRAFT", "SIGNED", "FUNDED"):
            raise err(ERR_UNIT_HAS_ACTIVE_DEAL, "Unit already has a non-terminal deal")
    trade_equity, tax_cents, amount_due = calc.deal_financials(
        sale_price_cents, tax_rate_bps, doc_fee_cents, down_payment_cents,
        trade_allowance_cents, trade_lien_payoff_cents)
    rec = new_record({
        "unit_id": unit_id,
        "customer_name": customer_name,
        "sale_price_cents": sale_price_cents,
        "financing_type": financing_type,
        "tax_rate_bps": tax_rate_bps,
        "doc_fee_cents": doc_fee_cents,
        "down_payment_cents": down_payment_cents,
        "trade_allowance_cents": trade_allowance_cents,
        "trade_lien_payoff_cents": trade_lien_payoff_cents,
        "status": "DRAFT",
        "trade_equity_cents": trade_equity,
        "tax_cents": tax_cents,
        "amount_due_cents": amount_due,
        "_paid_floor_plan_id": None,
        "_consignment_id": None,
    })
    db.deals[rec["id"]] = rec
    return object_response(S.serialize_deal(rec), 201)


@app.route("/deals/<rid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def deal_get(rid):
    return object_response(S.serialize_deal(_get(db.deals, rid)), 200)


@app.route("/deals", methods=["GET"])
@require_roles(*ALL_ROLES)
def deal_list():
    items = sorted_records(db.deals)
    unit_id = request.args.get("unit_id")
    if unit_id is not None:
        items = [d for d in items if d["unit_id"] == unit_id]
    status = request.args.get("status")
    if status is not None:
        items = [d for d in items if d["status"] == status]
    page, limit, offset, total = paginate(items)
    return array_response([S.serialize_deal(d) for d in page], limit, offset, total)


@app.route("/deals/<rid>/sign", methods=["POST"])
@require_roles("SalesRep")
def deal_sign(rid):
    deal = _get(db.deals, rid)
    if deal["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Deal must be DRAFT to sign")
    unit = db.units[deal["unit_id"]]
    if unit["status"] != "AVAILABLE":
        raise err(ERR_UNIT_NOT_AVAILABLE, "Unit must be AVAILABLE to sign the deal")
    deal["status"] = "SIGNED"
    touch(deal)
    unit["status"] = "RESERVED"
    touch(unit)
    return object_response(S.serialize_deal(deal), 200)


def _unit_sold_cascade(unit, deal):
    """Unit RESERVED -> SOLD: pay off floor plan, settle consignment."""
    fp = S.active_floor_plan_for_unit(unit["id"])
    if fp is not None:
        fp["_pre_payoff_outstanding"] = fp["outstanding_principal_cents"]
        d_out = calc.days_out(now(), fp["advanced_at"])
        fp["_payoff_snapshot"] = calc.payoff(fp["outstanding_principal_cents"], fp["apr_bps"], d_out)
        fp["outstanding_principal_cents"] = 0
        fp["status"] = "PAID_OFF"
        touch(fp)
        deal["_paid_floor_plan_id"] = fp["id"]
    if unit["acquisition_type"] == "CONSIGNMENT":
        c = active_consignment_for_unit(unit["id"])
        if c is not None:
            c["status"] = "SOLD"
            c["payout_cents"] = calc.consignment_payout(deal["sale_price_cents"], c["commission_bps"])
            touch(c)
            deal["_consignment_id"] = c["id"]
    unit["status"] = "SOLD"
    touch(unit)  # floor_plan_balance_cents recomputed to 0 (read-time)


def _unit_sold_compensate(unit, deal):
    """Unit SOLD -> AVAILABLE (deal cancel from FUNDED): reverse the cascade."""
    fp_id = deal.get("_paid_floor_plan_id")
    if fp_id:
        fp = db.floor_plans.get(fp_id)
        if fp is not None and fp["status"] == "PAID_OFF":
            fp["outstanding_principal_cents"] = fp["_pre_payoff_outstanding"]
            fp["status"] = "ACTIVE"
            fp["_payoff_snapshot"] = None
            touch(fp)
        deal["_paid_floor_plan_id"] = None
    c_id = deal.get("_consignment_id")
    if c_id:
        c = db.consignments.get(c_id)
        if c is not None and c["status"] == "SOLD":
            c["status"] = "ACTIVE"
            c["payout_cents"] = 0
            touch(c)
        deal["_consignment_id"] = None
    unit["status"] = "AVAILABLE"
    touch(unit)


@app.route("/deals/<rid>/fund", methods=["POST"])
@require_roles("Manager")
def deal_fund(rid):
    deal = _get(db.deals, rid)
    if deal["status"] != "SIGNED":
        raise err(ERR_INVALID_STATE, "Deal must be SIGNED to fund")
    if deal["down_payment_cents"] < calc.min_down_required(deal["sale_price_cents"]):
        raise err(ERR_DOWN_PAYMENT_TOO_LOW, "Down payment below the minimum required")
    deal["status"] = "FUNDED"
    touch(deal)
    unit = db.units[deal["unit_id"]]
    _unit_sold_cascade(unit, deal)
    return object_response(S.serialize_deal(deal), 200)


@app.route("/deals/<rid>/deliver", methods=["POST"])
@require_roles("SalesRep")
def deal_deliver(rid):
    deal = _get(db.deals, rid)
    if deal["status"] != "FUNDED":
        raise err(ERR_INVALID_STATE, "Deal must be FUNDED to deliver")
    unit = db.units[deal["unit_id"]]
    if unit["open_recall"]:
        raise err(ERR_OPEN_RECALL_BLOCKS_DELIVERY, "Delivery blocked by open recall")
    deal["status"] = "DELIVERED"
    touch(deal)
    unit["status"] = "DELIVERED"
    touch(unit)  # warranty_registered becomes true (derived from status)
    return object_response(S.serialize_deal(deal), 200)


@app.route("/deals/<rid>/cancel", methods=["POST"])
@require_roles("Manager")
def deal_cancel(rid):
    deal = _get(db.deals, rid)
    st = deal["status"]
    if st not in ("DRAFT", "SIGNED", "FUNDED"):
        raise err(ERR_INVALID_STATE, "Deal cannot be cancelled from its current state")
    if st == "SIGNED":
        unit = db.units[deal["unit_id"]]
        unit["status"] = "AVAILABLE"
        touch(unit)
    elif st == "FUNDED":
        unit = db.units[deal["unit_id"]]
        _unit_sold_compensate(unit, deal)
    deal["status"] = "CANCELLED"
    touch(deal)
    return object_response(S.serialize_deal(deal), 200)


# =============================================================================
# Consignment
# =============================================================================

@app.route("/consignments", methods=["POST"])
@require_roles("Manager")
def consignment_create():
    body = get_body()
    if V.present(body, "unit_id"):
        _get(db.units, body["unit_id"])
    unit_id = V.req_str(body, "unit_id")
    _get(db.units, unit_id)
    rec = new_record({
        "unit_id": unit_id,
        "consignor_name": V.req_str(body, "consignor_name"),
        "agreed_floor_cents": V.req_int(body, "agreed_floor_cents"),
        "commission_bps": V.req_int(body, "commission_bps"),
        "status": "ACTIVE",
        "payout_cents": 0,
    })
    db.consignments[rec["id"]] = rec
    return object_response(S.serialize_consignment(rec), 201)


@app.route("/consignments/<rid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def consignment_get(rid):
    return object_response(S.serialize_consignment(_get(db.consignments, rid)), 200)


@app.route("/consignments", methods=["GET"])
@require_roles(*ALL_ROLES)
def consignment_list():
    items = sorted_records(db.consignments)
    unit_id = request.args.get("unit_id")
    if unit_id is not None:
        items = [c for c in items if c["unit_id"] == unit_id]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, limit, offset, total = paginate(items)
    return array_response([S.serialize_consignment(c) for c in page], limit, offset, total)


@app.route("/consignments/<rid>/return", methods=["POST"])
@require_roles("Manager")
def consignment_return(rid):
    c = _get(db.consignments, rid)
    if c["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Consignment must be ACTIVE to return")
    c["status"] = "RETURNED"
    touch(c)
    unit = db.units.get(c["unit_id"])
    if unit is not None:
        unit["status"] = "RETURNED"
        touch(unit)
    return object_response(S.serialize_consignment(c), 200)


# =============================================================================
# RepairOrder
# =============================================================================

@app.route("/repair-orders", methods=["POST"])
@require_roles("ServiceAdvisor")
def repair_order_create():
    body = get_body()
    # existence: unit_id then service_bay_id (priority 3)
    if V.present(body, "unit_id"):
        _get(db.units, body["unit_id"])
    if V.present(body, "service_bay_id"):
        _get(db.service_bays, body["service_bay_id"])
    # structural (priority 4)
    unit_id = V.req_str(body, "unit_id")
    _get(db.units, unit_id)
    service_bay_id = V.req_str(body, "service_bay_id")
    _get(db.service_bays, service_bay_id)
    customer_name = V.req_str(body, "customer_name")
    ro_type = V.req_enum(body, "ro_type", RO_TYPES)
    labor_rate = V.req_int(body, "labor_rate_cents_per_hour")
    tax_rate_bps = V.req_int(body, "tax_rate_bps")
    scheduled_start = req_dt(body, "scheduled_start")
    scheduled_end = req_dt(body, "scheduled_end")
    flat_rate_code = None
    flat_rate_hours = None
    flat_rate_parts_cents = None
    estimated_hours = None
    if ro_type == "FLAT_RATE":
        flat_rate_code = V.req_enum(body, "flat_rate_code", FLAT_CODES)
        flat_rate_hours = V.req_num(body, "flat_rate_hours")
        flat_rate_parts_cents = V.req_int(body, "flat_rate_parts_cents")
    else:
        estimated_hours = V.req_num(body, "estimated_hours")
    # temporal window (priority 12)
    if not (scheduled_end > scheduled_start):
        raise err(ERR_SCHEDULE_WINDOW_INVALID, "scheduled_end must be after scheduled_start")
    # bay conflict (priority 16): closed window + 30-min buffer at each end
    buf = timedelta(minutes=BAY_BUFFER_MINUTES)
    for other in db.repair_orders.values():
        if other["service_bay_id"] != service_bay_id:
            continue
        if other["status"] == "INVOICED":
            continue
        if (scheduled_start <= other["scheduled_end"] + buf
                and other["scheduled_start"] <= scheduled_end + buf):
            raise err(ERR_BAY_SCHEDULE_CONFLICT, "Repair order overlaps another in the same bay")
    estimate = calc.estimate_total(ro_type, labor_rate, tax_rate_bps,
                                   flat_rate_hours, flat_rate_parts_cents, estimated_hours)
    rec = new_record({
        "unit_id": unit_id,
        "service_bay_id": service_bay_id,
        "customer_name": customer_name,
        "ro_type": ro_type,
        "flat_rate_code": flat_rate_code,
        "flat_rate_hours": flat_rate_hours,
        "flat_rate_parts_cents": flat_rate_parts_cents,
        "estimated_hours": estimated_hours,
        "labor_rate_cents_per_hour": labor_rate,
        "tax_rate_bps": tax_rate_bps,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "status": "OPEN",
        "estimate_total_cents": estimate,
        "final_total_cents": None,
    })
    db.repair_orders[rec["id"]] = rec
    return object_response(S.serialize_repair_order(rec), 201)


@app.route("/repair-orders/<rid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def repair_order_get(rid):
    return object_response(S.serialize_repair_order(_get(db.repair_orders, rid)), 200)


@app.route("/repair-orders", methods=["GET"])
@require_roles(*ALL_ROLES)
def repair_order_list():
    items = sorted_records(db.repair_orders)
    unit_id = request.args.get("unit_id")
    if unit_id is not None:
        items = [r for r in items if r["unit_id"] == unit_id]
    bay = request.args.get("service_bay_id")
    if bay is not None:
        items = [r for r in items if r["service_bay_id"] == bay]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, limit, offset, total = paginate(items)
    return array_response([S.serialize_repair_order(r) for r in page], limit, offset, total)


@app.route("/repair-orders/<rid>/start", methods=["POST"])
@require_roles("ServiceAdvisor")
def repair_order_start(rid):
    ro = _get(db.repair_orders, rid)
    if ro["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "Repair order must be OPEN to start")
    ro["status"] = "IN_PROGRESS"
    touch(ro)
    return object_response(S.serialize_repair_order(ro), 200)


def _compute_final_total(ro):
    subtotal = 0
    for sl in db.service_lines.values():
        if (sl["repair_order_id"] == ro["id"] and sl["status"] == "ACTIVE"
                and not sl["warranty_covered"]):
            subtotal += S.line_extended_cents(sl)
    return calc.final_total(subtotal, ro["tax_rate_bps"])


@app.route("/repair-orders/<rid>/complete", methods=["POST"])
@require_roles("ServiceAdvisor")
def repair_order_complete(rid):
    ro = _get(db.repair_orders, rid)
    if ro["status"] != "IN_PROGRESS":
        raise err(ERR_INVALID_STATE, "Repair order must be IN_PROGRESS to complete")
    ro["final_total_cents"] = _compute_final_total(ro)
    ro["status"] = "COMPLETED"
    touch(ro)
    return object_response(S.serialize_repair_order(ro), 200)


@app.route("/repair-orders/<rid>/reopen", methods=["POST"])
@require_roles("ServiceAdvisor")
def repair_order_reopen(rid):
    ro = _get(db.repair_orders, rid)
    if ro["status"] != "COMPLETED":
        raise err(ERR_INVALID_STATE, "Repair order must be COMPLETED to reopen")
    ro["final_total_cents"] = None
    ro["status"] = "IN_PROGRESS"
    touch(ro)
    return object_response(S.serialize_repair_order(ro), 200)


@app.route("/repair-orders/<rid>/invoice", methods=["POST"])
@require_roles("ServiceAdvisor")
def repair_order_invoice(rid):
    ro = _get(db.repair_orders, rid)
    if ro["status"] != "COMPLETED":
        raise err(ERR_INVALID_STATE, "Repair order must be COMPLETED to invoice")
    part_lines = [sl for sl in db.service_lines.values()
                  if sl["repair_order_id"] == ro["id"] and sl["status"] == "ACTIVE"
                  and sl["line_type"] == "PART" and not sl["warranty_covered"]]
    # stock check (priority 21)
    for sl in part_lines:
        part = db.parts.get(sl["part_id"])
        if part is None or sl["quantity"] > part["on_hand_qty"]:
            raise err(ERR_INSUFFICIENT_STOCK, "Insufficient stock to invoice")
    # consume
    for sl in part_lines:
        part = db.parts[sl["part_id"]]
        part["on_hand_qty"] -= sl["quantity"]
        sl["status"] = "CONSUMED"
        touch(sl)
        touch(part)  # available_qty recomputed
    ro["status"] = "INVOICED"
    touch(ro)
    return object_response(S.serialize_repair_order(ro), 200)


# =============================================================================
# ServiceLine
# =============================================================================

@app.route("/service-lines", methods=["POST"])
@require_roles("ServiceAdvisor")
def service_line_create():
    body = get_body()
    # existence: repair_order_id then part_id (priority 3)
    if V.present(body, "repair_order_id"):
        _get(db.repair_orders, body["repair_order_id"])
    if V.present(body, "part_id"):
        _get(db.parts, body["part_id"])
    # structural (priority 4)
    repair_order_id = V.req_str(body, "repair_order_id")
    _get(db.repair_orders, repair_order_id)
    line_type = V.req_enum(body, "line_type", LINE_TYPES)
    # referential (priority 5, 6) and quantity (priority 20)
    if line_type == "PART" and not V.present(body, "part_id"):
        raise err(ERR_PART_REQUIRED_FOR_LINE, "PART service line requires part_id")
    if line_type == "LABOR" and not V.present(body, "hours"):
        raise err(ERR_HOURS_REQUIRED_FOR_LABOR, "LABOR service line requires hours")
    hours = None
    quantity = None
    part_id = None
    if line_type == "PART":
        part_id = body["part_id"]
        q = body.get("quantity")
        if q is None or isinstance(q, bool) or not isinstance(q, int) or q < 1:
            raise err(ERR_INVALID_QUANTITY, "PART service line quantity must be >= 1")
        quantity = q
    else:
        hours = V.as_num(body["hours"], "hours")
    unit_price_cents = V.opt_int(body, "unit_price_cents", None)
    warranty_covered = V.opt_bool(body, "warranty_covered", False)
    rec = new_record({
        "repair_order_id": repair_order_id,
        "line_type": line_type,
        "part_id": part_id,
        "hours": hours,
        "quantity": quantity,
        "unit_price_cents": unit_price_cents,
        "warranty_covered": warranty_covered,
        "status": "ACTIVE",
    })
    db.service_lines[rec["id"]] = rec
    if line_type == "PART":
        part = db.parts.get(part_id)
        if part is not None:
            touch(part)  # reserves inventory: reserved_qty/available_qty recomputed
    return object_response(S.serialize_service_line(rec), 201)


@app.route("/service-lines/<rid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def service_line_get(rid):
    return object_response(S.serialize_service_line(_get(db.service_lines, rid)), 200)


@app.route("/service-lines", methods=["GET"])
@require_roles(*ALL_ROLES)
def service_line_list():
    items = sorted_records(db.service_lines)
    ro_id = request.args.get("repair_order_id")
    if ro_id is not None:
        items = [s for s in items if s["repair_order_id"] == ro_id]
    part_id = request.args.get("part_id")
    if part_id is not None:
        items = [s for s in items if s.get("part_id") == part_id]
    page, limit, offset, total = paginate(items)
    return array_response([S.serialize_service_line(s) for s in page], limit, offset, total)


@app.route("/service-lines/<rid>/void", methods=["POST"])
@require_roles("ServiceAdvisor")
def service_line_void(rid):
    sl = _get(db.service_lines, rid)
    if sl["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Service line must be ACTIVE to void")
    ro = db.repair_orders.get(sl["repair_order_id"])
    if ro is None or ro["status"] not in ("OPEN", "IN_PROGRESS", "COMPLETED"):
        raise err(ERR_INVALID_STATE, "Parent repair order is not in a voidable state")
    sl["status"] = "VOID"
    touch(sl)
    if sl["line_type"] == "PART":
        part = db.parts.get(sl["part_id"])
        if part is not None:
            touch(part)  # releases reservation: reserved_qty/available_qty recomputed
    return object_response(S.serialize_service_line(sl), 200)


# =============================================================================
# Part
# =============================================================================

@app.route("/parts", methods=["POST"])
@require_roles("PartsClerk")
def part_create():
    body = get_body()
    rec = new_record({
        "sku": V.req_str(body, "sku"),
        "name": V.req_str(body, "name"),
        "on_hand_qty": V.req_int(body, "on_hand_qty"),
        "unit_cost_cents": V.req_int(body, "unit_cost_cents"),
        "list_price_cents": V.req_int(body, "list_price_cents"),
        "reorder_point": V.req_int(body, "reorder_point"),
    })
    db.parts[rec["id"]] = rec
    return object_response(S.serialize_part(rec), 201)


@app.route("/parts/<rid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def part_get(rid):
    return object_response(S.serialize_part(_get(db.parts, rid)), 200)


@app.route("/parts", methods=["GET"])
@require_roles(*ALL_ROLES)
def part_list():
    items = sorted_records(db.parts)
    sku = request.args.get("sku")
    if sku is not None:
        items = [p for p in items if p["sku"] == sku]
    page, limit, offset, total = paginate(items)
    return array_response([S.serialize_part(p) for p in page], limit, offset, total)


@app.route("/parts/<rid>/receive", methods=["POST"])
@require_roles("PartsClerk")
def part_receive(rid):
    part = _get(db.parts, rid)
    body = get_body()
    quantity = V.req_int(body, "quantity")
    part["on_hand_qty"] += quantity
    touch(part)
    return object_response(S.serialize_part(part), 200)


# =============================================================================
# Berth
# =============================================================================

@app.route("/berths", methods=["POST"])
@require_roles("Manager")
def berth_create():
    body = get_body()
    rec = new_record({
        "berth_code": V.req_str(body, "berth_code"),
        "berth_type": V.req_enum(body, "berth_type", BERTH_TYPES),
        "max_length_ft": V.req_num(body, "max_length_ft"),
        "status": "OPEN",
    })
    db.berths[rec["id"]] = rec
    return object_response(S.serialize_berth(rec), 201)


@app.route("/berths/<rid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def berth_get(rid):
    return object_response(S.serialize_berth(_get(db.berths, rid)), 200)


@app.route("/berths/<rid>/close", methods=["POST"])
@require_roles("Manager")
def berth_close(rid):
    b = _get(db.berths, rid)
    if b["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "Berth must be OPEN to close")
    b["status"] = "CLOSED"
    touch(b)
    return object_response(S.serialize_berth(b), 200)


# =============================================================================
# ServiceBay
# =============================================================================

@app.route("/service-bays", methods=["POST"])
@require_roles("Manager")
def service_bay_create():
    body = get_body()
    rec = new_record({
        "bay_code": V.req_str(body, "bay_code"),
        "bay_type": V.req_enum(body, "bay_type", BAY_TYPES),
    })
    db.service_bays[rec["id"]] = rec
    return object_response(S.serialize_service_bay(rec), 201)


@app.route("/service-bays/<rid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def service_bay_get(rid):
    return object_response(S.serialize_service_bay(_get(db.service_bays, rid)), 200)


# =============================================================================
# SlipReservation
# =============================================================================

@app.route("/slip-reservations", methods=["POST"])
@require_roles("ServiceAdvisor")
def slip_reservation_create():
    body = get_body()
    # existence: berth_id then unit_id (priority 3)
    if V.present(body, "berth_id"):
        _get(db.berths, body["berth_id"])
    if V.present(body, "unit_id"):
        _get(db.units, body["unit_id"])
    # structural (priority 4)
    berth_id = V.req_str(body, "berth_id")
    berth = _get(db.berths, berth_id)
    unit_id = V.req_str(body, "unit_id")
    unit = _get(db.units, unit_id)
    start_date = req_dt(body, "start_date")
    end_date = req_dt(body, "end_date")
    daily_rate_cents = V.req_int(body, "daily_rate_cents")
    # dates well-formed (priority 11)
    if not (end_date > start_date):
        raise err(ERR_RESERVATION_DATES_INVALID, "end_date must be after start_date")
    # berth open (priority 13)
    if berth["status"] != "OPEN":
        raise err(ERR_BERTH_CLOSED, "Berth is CLOSED")
    # fit (priority 14)
    if unit["length_ft"] > berth["max_length_ft"]:
        raise err(ERR_UNIT_EXCEEDS_BERTH, "Unit exceeds berth maximum length")
    # overlap (priority 15): half-open [start, end)
    for other in db.slip_reservations.values():
        if other["berth_id"] != berth_id or other["status"] != "RESERVED":
            continue
        if start_date < other["end_date"] and other["start_date"] < end_date:
            raise err(ERR_BERTH_DOUBLE_BOOKED, "Reservation overlaps an existing one on this berth")
    nights = calc.nights_between(start_date, end_date)
    total = nights * daily_rate_cents
    rec = new_record({
        "berth_id": berth_id,
        "unit_id": unit_id,
        "start_date": start_date,
        "end_date": end_date,
        "daily_rate_cents": daily_rate_cents,
        "status": "RESERVED",
        "nights": nights,
        "total_cents": total,
    })
    db.slip_reservations[rec["id"]] = rec
    return object_response(S.serialize_slip_reservation(rec), 201)


@app.route("/slip-reservations/<rid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def slip_reservation_get(rid):
    return object_response(S.serialize_slip_reservation(_get(db.slip_reservations, rid)), 200)


@app.route("/slip-reservations", methods=["GET"])
@require_roles(*ALL_ROLES)
def slip_reservation_list():
    items = sorted_records(db.slip_reservations)
    berth_id = request.args.get("berth_id")
    if berth_id is not None:
        items = [s for s in items if s["berth_id"] == berth_id]
    unit_id = request.args.get("unit_id")
    if unit_id is not None:
        items = [s for s in items if s["unit_id"] == unit_id]
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, limit, offset, total = paginate(items)
    return array_response([S.serialize_slip_reservation(s) for s in page], limit, offset, total)


@app.route("/slip-reservations/<rid>/end", methods=["POST"])
@require_roles("ServiceAdvisor")
def slip_reservation_end(rid):
    sr = _get(db.slip_reservations, rid)
    if sr["status"] != "RESERVED":
        raise err(ERR_INVALID_STATE, "Reservation must be RESERVED to end")
    sr["status"] = "ENDED"
    touch(sr)
    return object_response(S.serialize_slip_reservation(sr), 200)


@app.route("/slip-reservations/<rid>/cancel", methods=["POST"])
@require_roles("ServiceAdvisor")
def slip_reservation_cancel(rid):
    sr = _get(db.slip_reservations, rid)
    if sr["status"] != "RESERVED":
        raise err(ERR_INVALID_STATE, "Reservation must be RESERVED to cancel")
    sr["status"] = "CANCELLED"
    touch(sr)
    return object_response(S.serialize_slip_reservation(sr), 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
