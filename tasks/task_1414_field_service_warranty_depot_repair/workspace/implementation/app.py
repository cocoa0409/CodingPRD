"""Field Service Warranty Depot Repair API — Flask application."""
import os
from datetime import date, timedelta

from flask import Flask, request

from db import (store, new_id, now_wall_iso, clock_now, clock_iso, touch,
                parse_iso_datetime, parse_iso_date)
from errors import (ApiError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN, ERR_NOT_OWNER,
                    ERR_VALIDATION, ERR_CUSTOMER_NOT_FOUND, ERR_MODEL_NOT_FOUND,
                    ERR_UNIT_NOT_FOUND, ERR_PART_NOT_FOUND,
                    ERR_FAILURE_CODE_NOT_FOUND, ERR_BAY_NOT_FOUND,
                    ERR_LOANER_UNIT_NOT_FOUND, ERR_RMA_NOT_FOUND,
                    ERR_QUOTE_NOT_FOUND, ERR_RESERVATION_NOT_FOUND,
                    ERR_ESCALATION_NOT_FOUND, ERR_REPAIR_LINE_NOT_FOUND,
                    ERR_INVALID_LINE_STATE, ERR_STALE_RMA_VERSION,
                    ERR_INVALID_RMA_STATE, ERR_INVALID_QUOTE_STATE,
                    ERR_INVALID_RESERVATION_STATE, ERR_INVALID_LOANER_STATE,
                    ERR_INVALID_ESCALATION_STATE, ERR_UNIT_CUSTOMER_MISMATCH,
                    ERR_SERIAL_MISMATCH, ERR_DUPLICATE_SERIAL,
                    ERR_UNIT_HAS_OPEN_RMA, ERR_INVALID_BAY_WINDOW,
                    ERR_BAY_INACTIVE, ERR_BAY_OVERLAP,
                    ERR_INVALID_LOANER_WINDOW, ERR_LOANER_WINDOW_OVERLAP,
                    ERR_SERVICE_OPTION_INCOMPATIBLE, ERR_LOANER_MODEL_MISMATCH,
                    ERR_LOANER_UNAVAILABLE, ERR_CREDIT_LIMIT_EXCEEDED,
                    ERR_INSUFFICIENT_STOCK, ERR_QUOTE_EXPIRED,
                    ERR_PAYMENT_REQUIRED, ERR_MODEL_CONTAINMENT,
                    ERR_ENGINEERING_REVIEW_PENDING, ERR_SEGREGATION_OF_DUTIES,
                    ERR_NO_WORK_RECORDED, ERR_EXCHANGE_NOT_FULFILLED,
                    ERR_LOANER_OUTSTANDING, validation, invalid_rma_state,
                    invalid_quote_state, invalid_reservation_state,
                    invalid_loaner_state, invalid_escalation_state,
                    invalid_line_state)
from middleware import actor, require_roles, check_owner
from response import success, error
import services
from services import (notify, warranty_eligibility, recurring_failure_score,
                      evaluate_recurring_and_escalate, final_estimate,
                      repair_vs_replace_decision, build_quote, latest_quote,
                      open_sla_pause, close_sla_pause, settlement,
                      compute_late_fee, release_deposit, serialize,
                      serialize_list, business_days, RMA_TERMINAL,
                      SLA_TRACKED_STATUSES, BAY_OCCUPYING_STATUSES,
                      ESCALATION_DEDUP_STATES, AUTO_CANCEL_DAYS,
                      MONITORING_DAYS, round_half_up)

app = Flask(__name__)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def handle_404(exc):
    return error(ERR_VALIDATION, "Route not found", 404)


@app.errorhandler(405)
def handle_405(exc):
    return error(ERR_VALIDATION, "Method not allowed", 405)


@app.errorhandler(Exception)
def handle_generic(exc):
    app.logger.exception("Unhandled error")
    return error(ERR_VALIDATION, "Internal error: %s" % exc, 500)


# ------------------------------------------------------------------ helpers

def body():
    if not request.is_json:
        return {}
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def req_str(data, field):
    v = data.get(field)
    if v is None or not isinstance(v, str) or v == "":
        raise validation(f"Missing or invalid required field: {field}")
    return v


def req_int(data, field):
    v = data.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, int):
        raise validation(f"Missing or invalid required field: {field}")
    return v


def opt_int(data, field, default=None):
    v = data.get(field)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, int):
        raise validation(f"Invalid integer field: {field}")
    return v


def opt_str(data, field, default=None):
    v = data.get(field)
    if v is None:
        return default
    if not isinstance(v, str):
        raise validation(f"Invalid string field: {field}")
    return v


def req_enum(data, field, choices):
    v = data.get(field)
    if v not in choices:
        raise validation(f"Missing or invalid enum field: {field}")
    return v


def opt_enum(data, field, choices, default=None):
    v = data.get(field)
    if v is None:
        return default
    if v not in choices:
        raise validation(f"Invalid enum field: {field}")
    return v


def req_date(data, field):
    v = data.get(field)
    if v is None:
        raise validation(f"Missing required field: {field}")
    try:
        d = parse_iso_date(v)
    except Exception:
        raise validation(f"Invalid ISO date: {field}")
    return v


def get_or_404(table, entity_id, error_id, what):
    e = store.__dict__[table].get(entity_id)
    if e is None:
        raise ApiError(error_id, f"{what} not found", 404)
    return e


def pagination_params():
    try:
        limit = int(request.args.get("limit", 10))
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        raise validation("Invalid limit/offset")
    if limit < 1 or limit > 100 or offset < 0:
        raise validation("Invalid limit/offset range")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    return page, {"limit": limit, "offset": offset, "total_count": total,
                  "has_more": offset + limit < total}


def new_entity(fields):
    now = now_wall_iso()
    e = {"id": new_id(), "created_at": now, "updated_at": now, "version": 1}
    e.update(fields)
    return e


def find_rma_by_id_or_404(rma_id):
    return get_or_404("rmas", rma_id, ERR_RMA_NOT_FOUND, "RMA")


# ====================================================================
# Clock & ops
# ====================================================================

@app.route("/depot/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles("DepotManager")
    data = body()
    to = data.get("to_iso8601")
    if not to:
        raise validation("Missing to_iso8601")
    try:
        dt = parse_iso_datetime(to)
    except Exception:
        raise validation("Invalid to_iso8601")
    store.clock = dt
    return success({"current_utc": clock_iso()})


@app.route("/depot/ops/run_daily_close", methods=["POST"])
def run_daily_close():
    require_roles("DepotManager")
    now = clock_now()
    today = now.date()
    expired_quote_ids = []
    auto_cancelled_rma_ids = []
    sla_breached_rma_ids = []
    late_fee_reservation_ids = []
    closed_final_escalation_ids = []

    with store.lock:
        # 1. Expire SENT quotes past expires_at (strictly before clock)
        for q in list(store.quotes.values()):
            if q["status"] == "SENT":
                exp = parse_iso_datetime(q["expires_at"])
                if exp < now:
                    q["status"] = "EXPIRED"
                    touch(q)
                    expired_quote_ids.append(q["id"])
                    rma = store.rmas.get(q["rma_id"])
                    if rma:
                        notify(rma, "QUOTE_EXPIRED", "Quote expired")

        # 2. Auto-cancel AUTHORIZED RMAs whose authorized_at is > 30 days old
        cutoff = now - timedelta(days=AUTO_CANCEL_DAYS)
        for rma in list(store.rmas.values()):
            if rma["status"] == "AUTHORIZED" and rma.get("authorized_at"):
                auth_at = parse_iso_datetime(rma["authorized_at"])
                if auth_at < cutoff:
                    rma["status"] = "CANCELLED"
                    rma["closed_at"] = None
                    touch(rma)
                    # release reservations
                    for res in store.loaner_reservations.values():
                        if res["rma_id"] == rma["id"] and res["status"] == "RESERVED":
                            res["status"] = "CANCELLED"
                            touch(res)
                            lu = store.loaner_units.get(res["loaner_unit_id"])
                            if lu and lu["status"] == "RESERVED":
                                lu["status"] = "AVAILABLE"
                                touch(lu)
                            release_deposit(res)
                    auto_cancelled_rma_ids.append(rma["id"])
                    notify(rma, "CANCELLED", "RMA auto-cancelled: not received within 30 days")

        # 3. SLA evaluation
        for rma in list(store.rmas.values()):
            if rma["status"] in SLA_TRACKED_STATUSES and rma.get("received_at"):
                unit = store.units.get(rma["unit_id"])
                model = store.product_models.get(unit["model_id"]) if unit else None
                if not model:
                    continue
                recv_date = parse_iso_datetime(rma["received_at"]).date()
                elapsed = business_days(recv_date, today)
                paused = 0
                for iv in rma.get("sla_pause_intervals", []):
                    f = parse_iso_datetime(iv["from"]).date()
                    t = parse_iso_datetime(iv["to"]).date()
                    paused += business_days(f, t)
                # currently open pause: count from open-from date to today
                if rma.get("_pause_open_from"):
                    f = parse_iso_datetime(rma["_pause_open_from"]).date()
                    paused += business_days(f, today)
                net = elapsed - paused
                if net > model["sla_turnaround_business_days"] and not rma.get("sla_breached"):
                    rma["sla_breached"] = True
                    touch(rma)
                    sla_breached_rma_ids.append(rma["id"])
                    notify(rma, "SLA_BREACH", "Turnaround SLA breached")

        # 4. Late fee accrual on SHIPPED LOANER reservations
        for res in list(store.loaner_reservations.values()):
            if res["status"] == "SHIPPED" and res["mode"] == "LOANER" and res.get("due_date"):
                due_d = date.fromisoformat(res["due_date"])
                if today > due_d:
                    new_fee = compute_late_fee(res, today)
                    if new_fee != res.get("late_fee_cents", 0):
                        res["late_fee_cents"] = new_fee
                        touch(res)
                    if not res.get("late_notification_sent"):
                        res["late_notification_sent"] = True
                        touch(res)
                        rma = store.rmas.get(res["rma_id"])
                        if rma:
                            notify(rma, "LOANER_LATE", "Loaner unit is late")
                    if res["id"] not in late_fee_reservation_ids:
                        late_fee_reservation_ids.append(res["id"])

        # 5. Close MONITORING escalations past monitoring_until
        for esc in list(store.engineering_escalations.values()):
            if esc["status"] == "MONITORING" and esc.get("monitoring_until"):
                mu = date.fromisoformat(esc["monitoring_until"])
                if today > mu:
                    esc["status"] = "CLOSED_FINAL"
                    touch(esc)
                    closed_final_escalation_ids.append(esc["id"])

    return success({
        "expired_quote_ids": expired_quote_ids,
        "auto_cancelled_rma_ids": auto_cancelled_rma_ids,
        "sla_breached_rma_ids": sla_breached_rma_ids,
        "late_fee_reservation_ids": late_fee_reservation_ids,
        "closed_final_escalation_ids": closed_final_escalation_ids,
    })


# ====================================================================
# Customers
# ====================================================================

@app.route("/depot/customers", methods=["POST"])
def create_customer():
    require_roles("IntakeAgent")
    data = body()
    name = req_str(data, "name")
    email = req_str(data, "email")
    credit = opt_int(data, "credit_limit_cents", 100000)
    tier = opt_enum(data, "loyalty_tier", {"STANDARD", "PREFERRED"}, "STANDARD")
    c = new_entity({
        "name": name,
        "email": email,
        "credit_limit_cents": credit,
        "loyalty_tier": tier,
        "deposit_exposure_cents": 0,
    })
    store.customers[c["id"]] = c
    return success(serialize(c), status=201)


@app.route("/depot/customers/<customerId>", methods=["GET"])
def get_customer(customerId):
    uid, role = require_roles("Customer", "IntakeAgent", "DepotManager", "WarrantyAdministrator")
    check_owner(uid, role, customerId)
    c = get_or_404("customers", customerId, ERR_CUSTOMER_NOT_FOUND, "Customer")
    return success(serialize(c))


# ====================================================================
# Product models
# ====================================================================

@app.route("/depot/product-models", methods=["POST"])
def create_model():
    require_roles("DepotManager")
    data = body()
    m = new_entity({
        "model_code": req_str(data, "model_code"),
        "description": req_str(data, "description"),
        "standard_warranty_days": req_int(data, "standard_warranty_days"),
        "registration_bonus_days": opt_int(data, "registration_bonus_days", 30),
        "replacement_cost_cents": req_int(data, "replacement_cost_cents"),
        "flat_rate_repair_cents": req_int(data, "flat_rate_repair_cents"),
        "labor_rate_cents_per_minute": req_int(data, "labor_rate_cents_per_minute"),
        "replace_threshold_pct": req_int(data, "replace_threshold_pct"),
        "sla_turnaround_business_days": req_int(data, "sla_turnaround_business_days"),
        "loaner_grace_days": opt_int(data, "loaner_grace_days", 10),
        "recurring_failure_threshold": opt_int(data, "recurring_failure_threshold", 3),
        "quote_valid_days": opt_int(data, "quote_valid_days", 14),
        "containment_flag": False,
    })
    store.product_models[m["id"]] = m
    return success(serialize(m), status=201)


@app.route("/depot/product-models/<modelId>", methods=["GET"])
def get_model_route(modelId):
    require_roles("IntakeAgent", "DepotTechnician", "DepotManager",
                  "WarrantyAdministrator", "EngineeringLead")
    m = get_or_404("product_models", modelId, ERR_MODEL_NOT_FOUND, "Product model")
    return success(serialize(m))


# ====================================================================
# Units
# ====================================================================

@app.route("/depot/units", methods=["POST"])
def create_unit():
    require_roles("IntakeAgent")
    data = body()
    serial = req_str(data, "serial_number")
    model_id = req_str(data, "model_id")
    customer_id = req_str(data, "customer_id")
    channel = req_enum(data, "channel", {"RETAIL", "ENTERPRISE"})
    purchase_date = req_date(data, "purchase_date")
    ship_date = req_date(data, "ship_date")
    registration_date = data.get("registration_date")
    if registration_date is not None:
        try:
            parse_iso_date(registration_date)
        except Exception:
            raise validation("Invalid ISO date: registration_date")

    # existence of FK references
    get_or_404("product_models", model_id, ERR_MODEL_NOT_FOUND, "Product model")
    get_or_404("customers", customer_id, ERR_CUSTOMER_NOT_FOUND, "Customer")

    # duplicate serial
    for u in store.units.values():
        if u["serial_number"] == serial:
            raise ApiError(ERR_DUPLICATE_SERIAL, "Unit serial_number already registered", 409)

    u = new_entity({
        "serial_number": serial,
        "model_id": model_id,
        "customer_id": customer_id,
        "channel": channel,
        "purchase_date": purchase_date,
        "ship_date": ship_date,
        "registration_date": registration_date,
        "disposition": "ACTIVE",
    })
    store.units[u["id"]] = u
    return success(serialize(u), status=201)


@app.route("/depot/units/<unitId>", methods=["GET"])
def get_unit_route(unitId):
    uid, role = require_roles("Customer", "IntakeAgent", "DepotTechnician", "DepotManager")
    u = get_or_404("units", unitId, ERR_UNIT_NOT_FOUND, "Unit")
    check_owner(uid, role, u["customer_id"])
    return success(serialize(u))


@app.route("/depot/units", methods=["GET"])
def list_units():
    require_roles("IntakeAgent", "DepotTechnician", "DepotManager")
    limit, offset = pagination_params()
    items = sorted(store.units.values(), key=lambda e: e["created_at"])
    cid = request.args.get("customer_id")
    mid = request.args.get("model_id")
    sn = request.args.get("serial_number")
    if cid:
        items = [u for u in items if u["customer_id"] == cid]
    if mid:
        items = [u for u in items if u["model_id"] == mid]
    if sn:
        items = [u for u in items if u["serial_number"] == sn]
    page, pg = paginate(items, limit, offset)
    return success(serialize_list(page), response_type="array", pagination=pg)


# ====================================================================
# Parts
# ====================================================================

@app.route("/depot/parts", methods=["POST"])
def create_part():
    require_roles("DepotManager")
    data = body()
    initial_stock = req_int(data, "initial_stock")
    p = new_entity({
        "sku": req_str(data, "sku"),
        "name": req_str(data, "name"),
        "unit_cost_cents": req_int(data, "unit_cost_cents"),
        "stock_on_hand": initial_stock,
        "reorder_point": opt_int(data, "reorder_point", 0),
    })
    store.parts[p["id"]] = p
    return success(serialize(p), status=201)


@app.route("/depot/parts/<partId>", methods=["GET"])
def get_part(partId):
    require_roles("DepotTechnician", "DepotManager")
    p = get_or_404("parts", partId, ERR_PART_NOT_FOUND, "Part")
    return success(serialize(p))


@app.route("/depot/parts/<partId>/restock", methods=["POST"])
def restock_part(partId):
    require_roles("DepotManager")
    data = body()
    qty = req_int(data, "quantity")
    if qty < 1:
        raise validation("quantity must be >= 1")
    p = get_or_404("parts", partId, ERR_PART_NOT_FOUND, "Part")
    p["stock_on_hand"] += qty
    touch(p)
    # resume matching AWAITING_PARTS RMAs in created_at ASC order
    awaiting = [r for r in store.rmas.values()
                if r["status"] == "AWAITING_PARTS"
                and any(line.get("part_id") == partId for line in r.get("planned_parts", []))]
    awaiting.sort(key=lambda r: r["created_at"])
    for rma in awaiting:
        rma["status"] = "IN_REPAIR"
        touch(rma)
    return success(serialize(p))


# ====================================================================
# Failure codes
# ====================================================================

@app.route("/depot/failure-codes", methods=["POST"])
def create_failure_code():
    require_roles("EngineeringLead")
    data = body()
    fc = new_entity({
        "code": req_str(data, "code"),
        "description": req_str(data, "description"),
        "severity": req_enum(data, "severity", {"LOW", "MEDIUM", "HIGH", "CRITICAL"}),
    })
    store.failure_codes[fc["id"]] = fc
    return success(serialize(fc), status=201)


# ====================================================================
# Depot bays
# ====================================================================

@app.route("/depot/depot-bays", methods=["POST"])
def create_bay():
    require_roles("DepotManager")
    data = body()
    b = new_entity({
        "bay_code": req_str(data, "bay_code"),
        "status": "ACTIVE",
    })
    store.depot_bays[b["id"]] = b
    return success(serialize(b), status=201)


@app.route("/depot/depot-bays/<bayId>", methods=["GET"])
def get_bay(bayId):
    require_roles("DepotTechnician", "DepotManager")
    b = get_or_404("depot_bays", bayId, ERR_BAY_NOT_FOUND, "Bay")
    return success(serialize(b))


@app.route("/depot/depot-bays/<bayId>/deactivate", methods=["POST"])
def deactivate_bay(bayId):
    require_roles("DepotManager")
    b = get_or_404("depot_bays", bayId, ERR_BAY_NOT_FOUND, "Bay")
    b["status"] = "OUT_OF_SERVICE"
    touch(b)
    return success(serialize(b))


@app.route("/depot/depot-bays/<bayId>/reactivate", methods=["POST"])
def reactivate_bay(bayId):
    require_roles("DepotManager")
    b = get_or_404("depot_bays", bayId, ERR_BAY_NOT_FOUND, "Bay")
    b["status"] = "ACTIVE"
    touch(b)
    return success(serialize(b))


# ====================================================================
# Loaner units
# ====================================================================

@app.route("/depot/loaner-units", methods=["POST"])
def create_loaner_unit():
    require_roles("DepotManager")
    data = body()
    model_id = req_str(data, "model_id")
    get_or_404("product_models", model_id, ERR_MODEL_NOT_FOUND, "Product model")
    lu = new_entity({
        "asset_tag": req_str(data, "asset_tag"),
        "model_id": model_id,
        "condition_grade": req_enum(data, "condition_grade", {"A", "B", "C"}),
        "deposit_value_cents": req_int(data, "deposit_value_cents"),
        "status": "AVAILABLE",
        "completed_loan_cycles": 0,
    })
    store.loaner_units[lu["id"]] = lu
    return success(serialize(lu), status=201)


@app.route("/depot/loaner-units/<loanerUnitId>", methods=["GET"])
def get_loaner_unit(loanerUnitId):
    require_roles("IntakeAgent", "DepotTechnician", "DepotManager")
    lu = get_or_404("loaner_units", loanerUnitId, ERR_LOANER_UNIT_NOT_FOUND, "Loaner unit")
    return success(serialize(lu))


@app.route("/depot/loaner-units", methods=["GET"])
def list_loaner_units():
    require_roles("IntakeAgent", "DepotManager")
    limit, offset = pagination_params()
    items = sorted(store.loaner_units.values(), key=lambda e: e["created_at"])
    mid = request.args.get("model_id")
    st = request.args.get("status")
    if mid:
        items = [u for u in items if u["model_id"] == mid]
    if st:
        items = [u for u in items if u["status"] == st]
    page, pg = paginate(items, limit, offset)
    return success(serialize_list(page), response_type="array", pagination=pg)


@app.route("/depot/loaner-units/<loanerUnitId>/inspect", methods=["POST"])
def inspect_loaner_unit(loanerUnitId):
    require_roles("DepotTechnician")
    data = body()
    outcome = req_enum(data, "outcome", {"PASS", "FAIL"})
    lu = get_or_404("loaner_units", loanerUnitId, ERR_LOANER_UNIT_NOT_FOUND, "Loaner unit")
    if lu["status"] != "INSPECTION":
        raise invalid_loaner_state("Loaner unit not in INSPECTION")
    if outcome == "PASS":
        lu["status"] = "AVAILABLE"
        lu["completed_loan_cycles"] += 1
    else:
        lu["status"] = "RETIRED"
    touch(lu)
    return success(serialize(lu))


# ====================================================================
# RMAs
# ====================================================================

@app.route("/depot/rmas", methods=["POST"])
def create_rma():
    uid, role = require_roles("Customer", "IntakeAgent")
    data = body()
    customer_id = req_str(data, "customer_id")
    unit_id = req_str(data, "unit_id")
    reported_issue = req_str(data, "reported_issue")
    service_option = opt_enum(data, "service_option",
                              {"STANDARD", "LOANER", "ADVANCE_EXCHANGE"}, "STANDARD")

    if role == "Customer":
        check_owner(uid, role, customer_id)

    get_or_404("customers", customer_id, ERR_CUSTOMER_NOT_FOUND, "Customer")
    unit = get_or_404("units", unit_id, ERR_UNIT_NOT_FOUND, "Unit")

    if unit["customer_id"] != customer_id:
        raise ApiError(ERR_UNIT_CUSTOMER_MISMATCH,
                       "Unit is not owned by the payload customer", 422)

    rma = new_entity({
        "rma_number": store.next_rma_number(),
        "customer_id": customer_id,
        "unit_id": unit_id,
        "service_option": service_option,
        "reported_issue": reported_issue,
        "status": "DRAFT",
        "coverage_path": None,
        "warranty_end_date_used": None,
        "goodwill_pct": 0,
        "warranty_override_by": None,
        "provisional_estimate_cents": None,
        "final_estimate_cents": None,
        "decision": None,
        "decision_overridden": False,
        "repairability": None,
        "labor_minutes_est": None,
        "planned_parts": [],
        "diagnosed_by": None,
        "repair_completed_by": None,
        "primary_failure_code_id": None,
        "bay_id": None,
        "bay_start_date": None,
        "bay_end_date": None,
        "authorized_at": None,
        "received_at": None,
        "shipped_at": None,
        "closed_at": None,
        "sla_pause_intervals": [],
        "sla_breached": False,
        "engineering_review_pending": False,
        "rework_count": 0,
        "return_reason": None,
        "current_quote_id": None,
        "settlement_gross_cents": None,
        "settlement_loyalty_credit_cents": None,
        "settlement_total_cents": None,
    })
    rma["_pause_open_from"] = None
    store.rmas[rma["id"]] = rma
    return success(serialize(rma), status=201)


@app.route("/depot/rmas/<rmaId>", methods=["GET"])
def get_rma(rmaId):
    uid, role = require_roles("Customer", "IntakeAgent", "DepotTechnician",
                              "DepotManager", "WarrantyAdministrator", "EngineeringLead")
    rma = find_rma_by_id_or_404(rmaId)
    check_owner(uid, role, rma["customer_id"])
    return success(serialize(rma))


@app.route("/depot/rmas", methods=["GET"])
def list_rmas():
    require_roles("IntakeAgent", "DepotTechnician", "DepotManager",
                  "WarrantyAdministrator", "EngineeringLead")
    limit, offset = pagination_params()
    items = sorted(store.rmas.values(), key=lambda e: e["created_at"])
    for key in ("customer_id", "unit_id", "bay_id", "status",
                "primary_failure_code_id", "current_quote_id"):
        v = request.args.get(key)
        if v:
            items = [r for r in items if str(r.get(key)) == v]
    page, pg = paginate(items, limit, offset)
    return success(serialize_list(page), response_type="array", pagination=pg)


@app.route("/depot/rmas/<rmaId>", methods=["PATCH"])
def patch_rma(rmaId):
    uid, role = require_roles("Customer", "IntakeAgent")
    rma = find_rma_by_id_or_404(rmaId)
    check_owner(uid, role, rma["customer_id"])
    data = body()
    expected = data.get("expected_rma_version")
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
        raise validation("Missing or invalid expected_rma_version")
    if expected != rma["version"]:
        raise ApiError(ERR_STALE_RMA_VERSION, "expected_rma_version does not match", 412)
    if rma["status"] != "DRAFT":
        raise invalid_rma_state("Only DRAFT RMAs can be edited")
    if "reported_issue" in data:
        v = data["reported_issue"]
        if not isinstance(v, str) or v == "":
            raise validation("Invalid reported_issue")
        rma["reported_issue"] = v
    if "service_option" in data:
        v = data["service_option"]
        if v not in {"STANDARD", "LOANER", "ADVANCE_EXCHANGE"}:
            raise validation("Invalid service_option")
        rma["service_option"] = v
    touch(rma)
    return success(serialize(rma))


@app.route("/depot/rmas/<rmaId>/authorize", methods=["POST"])
def authorize_rma(rmaId):
    require_roles("IntakeAgent")
    rma = find_rma_by_id_or_404(rmaId)
    if rma["status"] != "DRAFT":
        raise invalid_rma_state("RMA must be DRAFT to authorize")
    for other in store.rmas.values():
        if (other["id"] != rma["id"] and other["unit_id"] == rma["unit_id"]
                and other["status"] not in RMA_TERMINAL):
            raise ApiError(ERR_UNIT_HAS_OPEN_RMA,
                           "Another non-terminal RMA exists for the same unit", 409)
    unit = store.units.get(rma["unit_id"])
    model = store.product_models.get(unit["model_id"])
    coverage, end_used = warranty_eligibility(unit, model, clock_now().date())
    rma["coverage_path"] = coverage
    rma["warranty_end_date_used"] = end_used
    rma["provisional_estimate_cents"] = model["flat_rate_repair_cents"]
    rma["authorized_at"] = clock_iso()
    rma["status"] = "AUTHORIZED"
    touch(rma)
    notify(rma, "RMA_AUTHORIZED", "RMA authorized")
    return success(serialize(rma))


@app.route("/depot/rmas/<rmaId>/receive", methods=["POST"])
def receive_rma(rmaId):
    require_roles("IntakeAgent")
    rma = find_rma_by_id_or_404(rmaId)
    if rma["status"] != "AUTHORIZED":
        raise invalid_rma_state("RMA must be AUTHORIZED to receive")
    data = body()
    serial = data.get("serial_number")
    unit = store.units.get(rma["unit_id"])
    if serial != unit["serial_number"]:
        raise ApiError(ERR_SERIAL_MISMATCH,
                       "Payload serial_number differs from the unit's registered serial", 409)
    rma["received_at"] = clock_iso()
    rma["status"] = "RECEIVED"
    touch(rma)
    notify(rma, "RECEIVED", "Unit received at depot")
    return success(serialize(rma))


@app.route("/depot/rmas/<rmaId>/triage", methods=["POST"])
def triage_rma(rmaId):
    require_roles("IntakeAgent")
    rma = find_rma_by_id_or_404(rmaId)
    if rma["status"] != "RECEIVED":
        raise invalid_rma_state("RMA must be RECEIVED to triage")
    data = body()
    fc_id = data.get("primary_failure_code_id")
    fc = store.failure_codes.get(fc_id) if fc_id else None
    if fc is None:
        raise ApiError(ERR_FAILURE_CODE_NOT_FOUND, "Failure code not found", 404)
    rma["primary_failure_code_id"] = fc_id
    rma["status"] = "TRIAGED"
    touch(rma)
    evaluate_recurring_and_escalate(rma, fc_id)
    return success(serialize(rma))


@app.route("/depot/rmas/<rmaId>/diagnose", methods=["POST"])
def diagnose_rma(rmaId):
    uid, _ = require_roles("DepotTechnician")
    rma = find_rma_by_id_or_404(rmaId)
    if rma["status"] != "TRIAGED":
        raise invalid_rma_state("RMA must be TRIAGED to diagnose")
    data = body()
    labor_minutes_est = data.get("labor_minutes_est")
    if labor_minutes_est is None or isinstance(labor_minutes_est, bool) or not isinstance(labor_minutes_est, int):
        raise validation("Missing or invalid labor_minutes_est")
    repairability = req_enum(data, "repairability", {"REPAIRABLE", "BER"})
    planned_parts = data.get("planned_parts") or []
    if not isinstance(planned_parts, list):
        raise validation("planned_parts must be an array")
    cleaned_parts = []
    for line in planned_parts:
        if not isinstance(line, dict):
            raise validation("planned_parts lines must be objects")
        pid = line.get("part_id")
        qty = line.get("quantity")
        part = store.parts.get(pid) if pid else None
        if part is None:
            raise ApiError(ERR_PART_NOT_FOUND, "Part not found", 404)
        if qty is None or isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
            raise validation("planned_parts quantity must be >= 1")
        cleaned_parts.append({"part_id": pid, "quantity": qty})

    unit = store.units.get(rma["unit_id"])
    model = store.product_models.get(unit["model_id"])

    est = final_estimate(model, labor_minutes_est, cleaned_parts)
    decision = repair_vs_replace_decision(rma, model, est, repairability)

    rma["final_estimate_cents"] = est
    rma["decision"] = decision
    rma["repairability"] = repairability
    rma["labor_minutes_est"] = labor_minutes_est
    rma["planned_parts"] = cleaned_parts
    rma["diagnosed_by"] = uid

    # Auto-route in the same request
    if decision == "REPAIR":
        if rma["coverage_path"] in ("IN_WARRANTY", "GOODWILL_FULL"):
            rma["status"] = "IN_REPAIR"
        else:
            rma["status"] = "AWAITING_QUOTE_APPROVAL"
            quote = build_quote(rma, model, labor_minutes_est, cleaned_parts,
                                rma.get("goodwill_pct", 0), False)
            rma["current_quote_id"] = quote["id"]
            open_sla_pause(rma)
            notify(rma, "QUOTE_SENT", "Quote sent to customer")
    else:
        rma["status"] = "REPLACEMENT_PENDING"
    touch(rma)
    return success(serialize(rma))


@app.route("/depot/rmas/<rmaId>/schedule-bay", methods=["POST"])
def schedule_bay(rmaId):
    require_roles("DepotTechnician")
    rma = find_rma_by_id_or_404(rmaId)
    if rma["status"] not in ("TRIAGED", "DIAGNOSED", "IN_REPAIR", "AWAITING_PARTS"):
        raise invalid_rma_state("Bay booking not valid in current RMA state")
    data = body()
    bay_id = data.get("bay_id")
    bay = store.depot_bays.get(bay_id) if bay_id else None
    if bay is None:
        raise ApiError(ERR_BAY_NOT_FOUND, "Bay not found", 404)
    start_s = data.get("start_date")
    end_s = data.get("end_date")
    try:
        start_d = parse_iso_date(start_s)
        end_d = parse_iso_date(end_s)
    except Exception:
        raise ApiError(ERR_INVALID_BAY_WINDOW, "Bay booking dates must be ISO dates", 422)
    if end_d < start_d:
        raise ApiError(ERR_INVALID_BAY_WINDOW, "Bay booking end_date before start_date", 422)
    if bay["status"] != "ACTIVE":
        raise ApiError(ERR_BAY_INACTIVE, "Bay is OUT_OF_SERVICE", 409)
    # Overlap with 1-day buffer: new [s-1d, e+1d] vs existing [bs, be]
    ns = start_d - timedelta(days=1)
    ne = end_d + timedelta(days=1)
    for other in store.rmas.values():
        if (other["id"] != rma["id"] and other.get("bay_id") == bay_id
                and other["status"] in BAY_OCCUPYING_STATUSES
                and other.get("bay_start_date") and other.get("bay_end_date")):
            bs = date.fromisoformat(other["bay_start_date"])
            be = date.fromisoformat(other["bay_end_date"])
            if ns <= be and bs <= ne:
                raise ApiError(ERR_BAY_OVERLAP,
                               "Bay booking conflicts with an existing booking", 409)
    rma["bay_id"] = bay_id
    rma["bay_start_date"] = start_s
    rma["bay_end_date"] = end_s
    touch(rma)
    return success(serialize(rma))


@app.route("/depot/rmas/<rmaId>/await-parts", methods=["POST"])
def await_parts(rmaId):
    require_roles("DepotTechnician")
    rma = find_rma_by_id_or_404(rmaId)
    if rma["status"] != "IN_REPAIR":
        raise invalid_rma_state("RMA must be IN_REPAIR to await parts")
    rma["status"] = "AWAITING_PARTS"
    touch(rma)
    return success(serialize(rma))


@app.route("/depot/rmas/<rmaId>/parts", methods=["POST"])
def consume_part(rmaId):
    uid, _ = require_roles("DepotTechnician")
    rma = find_rma_by_id_or_404(rmaId)
    data = body()
    expected = data.get("expected_rma_version")
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
        raise validation("Missing or invalid expected_rma_version")
    if expected != rma["version"]:
        raise ApiError(ERR_STALE_RMA_VERSION, "expected_rma_version does not match", 412)
    if rma["status"] not in ("IN_REPAIR", "AWAITING_PARTS"):
        raise invalid_rma_state("Parts can only be consumed while IN_REPAIR or AWAITING_PARTS")
    part_id = data.get("part_id")
    part = store.parts.get(part_id) if part_id else None
    if part is None:
        raise ApiError(ERR_PART_NOT_FOUND, "Part not found", 404)
    fc_id = data.get("failure_code_id")
    fc = store.failure_codes.get(fc_id) if fc_id else None
    if fc is None:
        raise ApiError(ERR_FAILURE_CODE_NOT_FOUND, "Failure code not found", 404)
    qty = data.get("quantity")
    if qty is None or isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
        raise validation("quantity must be >= 1")
    if part["stock_on_hand"] < qty:
        raise ApiError(ERR_INSUFFICIENT_STOCK, "Part stock_on_hand below requested quantity", 409)

    line = new_entity({
        "rma_id": rma["id"],
        "part_id": part_id,
        "failure_code_id": fc_id,
        "quantity": qty,
        "unit_cost_cents": part["unit_cost_cents"],
        "line_total_cents": qty * part["unit_cost_cents"],
        "status": "CONSUMED",
        "consumed_by": uid,
    })
    store.repair_lines[line["id"]] = line
    part["stock_on_hand"] -= qty
    touch(part)
    touch(rma)  # increments RMA version
    evaluate_recurring_and_escalate(rma, fc_id)
    return success(serialize(line))


@app.route("/depot/rmas/<rmaId>/repair-complete", methods=["POST"])
def repair_complete(rmaId):
    uid, _ = require_roles("DepotTechnician")
    rma = find_rma_by_id_or_404(rmaId)
    if rma["status"] != "IN_REPAIR":
        raise invalid_rma_state("RMA must be IN_REPAIR to complete repair")
    has_work = any(l["rma_id"] == rma["id"] and l["status"] == "CONSUMED"
                   for l in store.repair_lines.values())
    if not has_work:
        raise ApiError(ERR_NO_WORK_RECORDED,
                       "No CONSUMED repair line recorded for this RMA", 409)
    rma["repair_completed_by"] = uid
    rma["status"] = "QA_HOLD"
    touch(rma)
    return success(serialize(rma))


@app.route("/depot/rmas/<rmaId>/qa-release", methods=["POST"])
def qa_release(rmaId):
    uid, _ = require_roles("DepotTechnician")
    rma = find_rma_by_id_or_404(rmaId)
    if rma["status"] != "QA_HOLD":
        raise invalid_rma_state("RMA must be in QA_HOLD")
    data = body()
    outcome = req_enum(data, "outcome", {"PASS", "FAIL"})
    # Safety gates first: engineering review (priority 8) then SoD (priority 9)
    if outcome == "PASS" and rma.get("engineering_review_pending"):
        raise ApiError(ERR_ENGINEERING_REVIEW_PENDING,
                       "qa-release PASS blocked while engineering review pending", 409)
    if rma.get("repair_completed_by") is not None and uid == rma["repair_completed_by"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES,
                       "QA releasing technician must differ from repair_completed_by", 403)
    if outcome == "PASS":
        rma["status"] = "READY_TO_SHIP"
    else:
        rma["status"] = "IN_REPAIR"
        rma["rework_count"] = rma.get("rework_count", 0) + 1
    touch(rma)
    return success(serialize(rma))


@app.route("/depot/rmas/<rmaId>/ship", methods=["POST"])
def ship_rma(rmaId):
    require_roles("DepotTechnician")
    rma = find_rma_by_id_or_404(rmaId)
    data = body()
    if rma["status"] not in ("READY_TO_SHIP", "REPLACEMENT_PENDING"):
        raise invalid_rma_state("RMA must be READY_TO_SHIP or REPLACEMENT_PENDING to ship")
    unit = store.units.get(rma["unit_id"])
    model = store.product_models.get(unit["model_id"])
    if rma["status"] == "REPLACEMENT_PENDING":
        if model.get("containment_flag"):
            raise ApiError(ERR_MODEL_CONTAINMENT,
                           "Replacement shipment blocked by engineering containment", 409)
        if rma["service_option"] == "ADVANCE_EXCHANGE":
            fulfilled = any(res["rma_id"] == rma["id"]
                            and res["mode"] == "ADVANCE_EXCHANGE"
                            and res["status"] == "SHIPPED"
                            for res in store.loaner_reservations.values())
            if not fulfilled:
                raise ApiError(ERR_EXCHANGE_NOT_FULFILLED,
                               "ADVANCE_EXCHANGE requires a SHIPPED exchange reservation", 409)
    carrier = data.get("carrier")
    tracking = data.get("tracking_number")
    if not isinstance(carrier, str) or not carrier or not isinstance(tracking, str) or not tracking:
        raise validation("carrier and tracking_number are required")

    rma["shipped_at"] = clock_iso()
    if rma["status"] == "READY_TO_SHIP":
        if rma.get("return_reason") is None and rma.get("decision") == "REPAIR":
            rma["return_reason"] = "REPAIRED"
        # else keeps existing value (e.g., UNREPAIRED)
    else:
        rma["return_reason"] = "REPLACED"
    rma["status"] = "SHIPPED"
    # due_date for LOANER-mode reservations still SHIPPED
    ship_date = clock_now().date()
    due = ship_date + timedelta(days=model["loaner_grace_days"])
    for res in store.loaner_reservations.values():
        if res["rma_id"] == rma["id"] and res["mode"] == "LOANER" and res["status"] == "SHIPPED":
            res["due_date"] = due.isoformat()
            touch(res)
    touch(rma)
    notify(rma, "SHIPPED", "Unit shipped")
    return success(serialize(rma))


@app.route("/depot/rmas/<rmaId>/close", methods=["POST"])
def close_rma(rmaId):
    require_roles("IntakeAgent", "DepotManager")
    rma = find_rma_by_id_or_404(rmaId)
    if rma["status"] != "SHIPPED":
        raise invalid_rma_state("RMA must be SHIPPED to close")
    for res in store.loaner_reservations.values():
        if res["rma_id"] == rma["id"] and res["status"] in ("RESERVED", "SHIPPED"):
            raise ApiError(ERR_LOANER_OUTSTANDING,
                           "Close blocked by outstanding loaner reservation", 409)
    gross, credit, total = settlement(rma)
    rma["settlement_gross_cents"] = gross
    rma["settlement_loyalty_credit_cents"] = credit
    rma["settlement_total_cents"] = total
    rma["closed_at"] = clock_iso()
    rma["status"] = "CLOSED"
    touch(rma)

    # Recurrence bookkeeping: reopen matching MONITORING escalation
    unit = store.units.get(rma["unit_id"])
    if unit and rma.get("primary_failure_code_id"):
        today = clock_now().date()
        for esc in store.engineering_escalations.values():
            if (esc["model_id"] == unit["model_id"]
                    and esc["failure_code_id"] == rma["primary_failure_code_id"]
                    and esc["status"] == "MONITORING"
                    and esc.get("monitoring_until")
                    and today <= date.fromisoformat(esc["monitoring_until"])):
                esc["status"] = "OPEN"
                esc["recurrence_count"] = esc.get("recurrence_count", 0) + 1
                touch(esc)
                notify(rma, "ESCALATION_OPENED", "Escalation reopened due to recurrence")
    notify(rma, "CLOSED", "RMA closed")
    return success(serialize(rma))


@app.route("/depot/rmas/<rmaId>/cancel", methods=["POST"])
def cancel_rma(rmaId):
    uid, role = require_roles("Customer", "IntakeAgent")
    rma = find_rma_by_id_or_404(rmaId)
    check_owner(uid, role, rma["customer_id"])
    if rma["status"] not in ("DRAFT", "AUTHORIZED"):
        raise invalid_rma_state("Only DRAFT or AUTHORIZED RMAs can be cancelled")
    was_authorized = rma["status"] == "AUTHORIZED"
    rma["status"] = "CANCELLED"
    touch(rma)
    if was_authorized:
        for res in store.loaner_reservations.values():
            if res["rma_id"] == rma["id"] and res["status"] == "RESERVED":
                res["status"] = "CANCELLED"
                touch(res)
                lu = store.loaner_units.get(res["loaner_unit_id"])
                if lu and lu["status"] == "RESERVED":
                    lu["status"] = "AVAILABLE"
                    touch(lu)
                release_deposit(res)
    notify(rma, "CANCELLED", "RMA cancelled")
    return success(serialize(rma))


@app.route("/depot/rmas/<rmaId>/return-unrepaired", methods=["POST"])
def return_unrepaired(rmaId):
    require_roles("IntakeAgent")
    rma = find_rma_by_id_or_404(rmaId)
    if rma["status"] != "QUOTE_DECLINED":
        raise invalid_rma_state("RMA must be QUOTE_DECLINED")
    rma["return_reason"] = "UNREPAIRED"
    close_sla_pause(rma)
    rma["status"] = "READY_TO_SHIP"
    touch(rma)
    return success(serialize(rma))


@app.route("/depot/rmas/<rmaId>/scrap", methods=["POST"])
def scrap_rma(rmaId):
    uid, _ = require_roles("DepotManager")
    rma = find_rma_by_id_or_404(rmaId)
    if rma["status"] != "QUOTE_DECLINED":
        raise invalid_rma_state("RMA must be QUOTE_DECLINED to scrap")
    if rma.get("warranty_override_by") is not None and uid == rma["warranty_override_by"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES,
                       "Scrapping manager must differ from warranty_override_by", 403)
    unit = store.units.get(rma["unit_id"])
    if unit:
        unit["disposition"] = "SCRAPPED"
        touch(unit)
    close_sla_pause(rma)
    gross, credit, total = settlement(rma)
    rma["settlement_gross_cents"] = gross
    rma["settlement_loyalty_credit_cents"] = credit
    rma["settlement_total_cents"] = total
    rma["status"] = "SCRAPPED"
    touch(rma)
    return success(serialize(rma))


@app.route("/depot/rmas/<rmaId>/override-decision", methods=["POST"])
def override_decision(rmaId):
    uid, _ = require_roles("DepotManager")
    rma = find_rma_by_id_or_404(rmaId)
    data = body()
    new_decision = req_enum(data, "new_decision", {"REPAIR", "REPLACE"})
    reason = data.get("reason")
    if not isinstance(reason, str) or not reason:
        raise validation("reason is required")

    if new_decision == "REPAIR":
        if rma["status"] != "REPLACEMENT_PENDING":
            raise invalid_rma_state("Override to REPAIR requires REPLACEMENT_PENDING")
        if rma.get("diagnosed_by") is not None and uid == rma["diagnosed_by"]:
            raise ApiError(ERR_SEGREGATION_OF_DUTIES,
                           "Overriding manager must differ from diagnosed_by", 403)
        rma["decision"] = "REPAIR"
        rma["decision_overridden"] = True
        unit = store.units.get(rma["unit_id"])
        model = store.product_models.get(unit["model_id"])
        if rma["coverage_path"] in ("IN_WARRANTY", "GOODWILL_FULL"):
            rma["status"] = "IN_REPAIR"
        else:
            rma["status"] = "AWAITING_QUOTE_APPROVAL"
            quote = build_quote(rma, model, rma["labor_minutes_est"],
                                rma.get("planned_parts", []),
                                rma.get("goodwill_pct", 0), False)
            rma["current_quote_id"] = quote["id"]
            open_sla_pause(rma)
            notify(rma, "QUOTE_SENT", "Quote sent to customer")
    else:  # REPLACE
        if rma["status"] != "AWAITING_QUOTE_APPROVAL":
            raise invalid_rma_state("Override to REPLACE requires AWAITING_QUOTE_APPROVAL")
        current = store.quotes.get(rma["current_quote_id"]) if rma.get("current_quote_id") else None
        if current is not None and current["status"] == "APPROVED":
            raise invalid_rma_state("Cannot override over an APPROVED quote")
        if rma.get("diagnosed_by") is not None and uid == rma["diagnosed_by"]:
            raise ApiError(ERR_SEGREGATION_OF_DUTIES,
                           "Overriding manager must differ from diagnosed_by", 403)
        rma["decision"] = "REPLACE"
        rma["decision_overridden"] = True
        if current is not None and current["status"] == "SENT":
            current["status"] = "SUPERSEDED"
            touch(current)
        rma["current_quote_id"] = None
        close_sla_pause(rma)
        rma["status"] = "REPLACEMENT_PENDING"
    touch(rma)
    return success(serialize(rma))


@app.route("/depot/rmas/<rmaId>/warranty-override", methods=["POST"])
def warranty_override(rmaId):
    uid, _ = require_roles("WarrantyAdministrator")
    rma = find_rma_by_id_or_404(rmaId)
    data = body()
    override_coverage = req_enum(data, "override_coverage", {"GOODWILL_FULL", "GOODWILL_PARTIAL"})
    goodwill_pct = opt_int(data, "goodwill_pct", 0)
    reason = data.get("reason")
    if not isinstance(reason, str) or not reason:
        raise validation("reason is required")

    rma["coverage_path"] = override_coverage
    rma["goodwill_pct"] = goodwill_pct
    rma["warranty_override_by"] = uid

    unit = store.units.get(rma["unit_id"])
    model = store.product_models.get(unit["model_id"]) if unit else None

    current = store.quotes.get(rma["current_quote_id"]) if rma.get("current_quote_id") else None
    if current is not None and current["status"] == "SENT":
        current["status"] = "SUPERSEDED"
        touch(current)
        # replacement quote with goodwill discount
        lines_input = [{"part_id": l["part_id"], "quantity": l["quantity"]} for l in current["lines"]]
        new_quote = build_quote(rma, model, current["labor_minutes"], lines_input,
                                goodwill_pct, current.get("expedite", False))
        rma["current_quote_id"] = new_quote["id"]
        notify(rma, "QUOTE_SENT", "Revised quote sent to customer")

    if rma["status"] == "AWAITING_QUOTE_APPROVAL" and override_coverage == "GOODWILL_FULL":
        close_sla_pause(rma)
        rma["status"] = "IN_REPAIR"

    touch(rma)
    return success(serialize(rma))


# ====================================================================
# Quotes
# ====================================================================

@app.route("/depot/rmas/<rmaId>/quotes", methods=["POST"])
def create_quote_revision(rmaId):
    require_roles("DepotTechnician")
    rma = find_rma_by_id_or_404(rmaId)
    data = body()
    expected = data.get("expected_rma_version")
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
        raise validation("Missing or invalid expected_rma_version")
    if expected != rma["version"]:
        raise ApiError(ERR_STALE_RMA_VERSION, "expected_rma_version does not match", 412)

    latest = latest_quote(rma["id"])
    if rma["status"] == "AWAITING_QUOTE_APPROVAL":
        allowed = {"SENT", "EXPIRED"}
    elif rma["status"] == "QUOTE_DECLINED":
        allowed = {"DECLINED", "EXPIRED"}
    else:
        raise invalid_rma_state("RMA not awaiting quote approval or declined")
    if latest is None or latest["status"] not in allowed:
        raise invalid_quote_state("Latest quote not in a revisable state")

    labor_minutes = data.get("labor_minutes")
    if labor_minutes is None or isinstance(labor_minutes, bool) or not isinstance(labor_minutes, int):
        raise validation("Missing or invalid labor_minutes")
    parts_lines = data.get("parts_lines") or []
    if not isinstance(parts_lines, list):
        raise validation("parts_lines must be an array")
    cleaned = []
    for line in parts_lines:
        if not isinstance(line, dict):
            raise validation("parts_lines entries must be objects")
        pid = line.get("part_id")
        qty = line.get("quantity")
        part = store.parts.get(pid) if pid else None
        if part is None:
            raise ApiError(ERR_PART_NOT_FOUND, "Part not found", 404)
        if qty is None or isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
            raise validation("parts_lines quantity must be >= 1")
        cleaned.append({"part_id": pid, "quantity": qty})
    discount_pct = opt_int(data, "discount_pct", rma.get("goodwill_pct", 0))
    expedite = bool(data.get("expedite", False))

    unit = store.units.get(rma["unit_id"])
    model = store.product_models.get(unit["model_id"])

    latest["status"] = "SUPERSEDED"
    touch(latest)
    quote = build_quote(rma, model, labor_minutes, cleaned, discount_pct, expedite)
    rma["current_quote_id"] = quote["id"]
    if rma["status"] == "QUOTE_DECLINED":
        rma["status"] = "AWAITING_QUOTE_APPROVAL"
    touch(rma)  # increments version
    notify(rma, "QUOTE_SENT", "Quote sent to customer")
    return success(serialize(quote), status=201)


@app.route("/depot/quotes/<quoteId>", methods=["GET"])
def get_quote(quoteId):
    uid, role = require_roles("Customer", "IntakeAgent", "DepotTechnician", "DepotManager")
    q = get_or_404("quotes", quoteId, ERR_QUOTE_NOT_FOUND, "Quote")
    rma = store.rmas.get(q["rma_id"])
    if rma:
        check_owner(uid, role, rma["customer_id"])
    return success(serialize(q))


@app.route("/depot/rmas/<rmaId>/quotes", methods=["GET"])
def list_rma_quotes(rmaId):
    uid, role = require_roles("Customer", "IntakeAgent", "DepotTechnician", "DepotManager")
    rma = find_rma_by_id_or_404(rmaId)
    check_owner(uid, role, rma["customer_id"])
    limit, offset = pagination_params()
    items = sorted([q for q in store.quotes.values() if q["rma_id"] == rma["id"]],
                   key=lambda e: e["created_at"])
    page, pg = paginate(items, limit, offset)
    return success(serialize_list(page), response_type="array", pagination=pg)


@app.route("/depot/quotes/<quoteId>/approve", methods=["POST"])
def approve_quote(quoteId):
    uid, role = require_roles("Customer")
    q = get_or_404("quotes", quoteId, ERR_QUOTE_NOT_FOUND, "Quote")
    rma = store.rmas.get(q["rma_id"])
    if rma:
        check_owner(uid, role, rma["customer_id"])
    if rma is None or rma.get("current_quote_id") != q["id"] or q["status"] != "SENT":
        raise invalid_quote_state("Quote is not the current SENT quote")
    now = clock_now()
    if now > parse_iso_datetime(q["expires_at"]):
        raise ApiError(ERR_QUOTE_EXPIRED, "Quote has expired", 409)
    data = body()
    payment_reference = data.get("payment_reference")
    if not isinstance(payment_reference, str) or not payment_reference:
        raise ApiError(ERR_PAYMENT_REQUIRED, "payment_reference is required", 402)
    q["status"] = "APPROVED"
    q["decided_at"] = clock_iso()
    q["payment_reference"] = payment_reference
    touch(q)
    rma["status"] = "IN_REPAIR"
    close_sla_pause(rma)
    touch(rma)
    notify(rma, "QUOTE_APPROVED", "Quote approved by customer")
    return success(serialize(q))


@app.route("/depot/quotes/<quoteId>/decline", methods=["POST"])
def decline_quote(quoteId):
    uid, role = require_roles("Customer")
    q = get_or_404("quotes", quoteId, ERR_QUOTE_NOT_FOUND, "Quote")
    rma = store.rmas.get(q["rma_id"])
    if rma:
        check_owner(uid, role, rma["customer_id"])
    if rma is None or rma.get("current_quote_id") != q["id"] or q["status"] != "SENT":
        raise invalid_quote_state("Quote is not the current SENT quote")
    q["status"] = "DECLINED"
    q["decided_at"] = clock_iso()
    touch(q)
    rma["status"] = "QUOTE_DECLINED"
    touch(rma)  # SLA pause remains open
    notify(rma, "QUOTE_DECLINED", "Quote declined by customer")
    return success(serialize(q))


# ====================================================================
# Loaner reservations
# ====================================================================

@app.route("/depot/rmas/<rmaId>/loaner-reservations", methods=["POST"])
def create_loaner_reservation(rmaId):
    require_roles("IntakeAgent")
    rma = find_rma_by_id_or_404(rmaId)
    data = body()
    start_s = data.get("start_date")
    end_s = data.get("end_date")
    try:
        start_d = parse_iso_date(start_s)
        end_d = parse_iso_date(end_s)
    except Exception:
        raise ApiError(ERR_INVALID_LOANER_WINDOW, "Loaner window dates must be ISO dates", 422)
    if not (end_d > start_d):
        raise ApiError(ERR_INVALID_LOANER_WINDOW,
                       "Loaner window end_date must be strictly after start_date", 422)

    unit = store.units.get(rma["unit_id"])
    customer = store.customers.get(rma["customer_id"])

    # Pinned order (§2.8): window shape -> window overlap -> service-option /
    # model compatibility -> deposit credit check. An explicit pick is governed
    # solely by the half-open window-conflict rule: adjacency (new start equal
    # to the existing end) is allowed even while the unit is RESERVED or
    # SHIPPED_OUT (§3.7).
    explicit_id = data.get("loaner_unit_id")
    if explicit_id is not None:
        lu = store.loaner_units.get(explicit_id)
        if lu is None:
            raise ApiError(ERR_LOANER_UNIT_NOT_FOUND, "Loaner unit not found", 404)
        # window overlap check on the explicit unit
        for res in store.loaner_reservations.values():
            if res["loaner_unit_id"] == lu["id"] and res["status"] in ("RESERVED", "SHIPPED"):
                s2 = date.fromisoformat(res["start_date"])
                e2 = date.fromisoformat(res["end_date"])
                if start_d < e2 and s2 < end_d:
                    raise ApiError(ERR_LOANER_WINDOW_OVERLAP,
                                   "Loaner unit already committed for an overlapping window", 409)
        if rma["service_option"] not in ("LOANER", "ADVANCE_EXCHANGE"):
            raise ApiError(ERR_SERVICE_OPTION_INCOMPATIBLE,
                           "Loaner reservation requires LOANER or ADVANCE_EXCHANGE service option", 422)
        if lu["model_id"] != unit["model_id"]:
            raise ApiError(ERR_LOANER_MODEL_MISMATCH,
                           "Loaner unit model differs from RMA unit model", 422)
        chosen = lu
    else:
        if rma["service_option"] not in ("LOANER", "ADVANCE_EXCHANGE"):
            raise ApiError(ERR_SERVICE_OPTION_INCOMPATIBLE,
                           "Loaner reservation requires LOANER or ADVANCE_EXCHANGE service option", 422)
        # selector: AVAILABLE, model match, grade A/B; cycles ASC, created_at ASC
        candidates = [lu for lu in store.loaner_units.values()
                      if lu["status"] == "AVAILABLE"
                      and lu["model_id"] == unit["model_id"]
                      and lu["condition_grade"] in ("A", "B")]
        # exclude units with overlapping reservations
        def overlaps(lu):
            for res in store.loaner_reservations.values():
                if res["loaner_unit_id"] == lu["id"] and res["status"] in ("RESERVED", "SHIPPED"):
                    s2 = date.fromisoformat(res["start_date"])
                    e2 = date.fromisoformat(res["end_date"])
                    if start_d < e2 and s2 < end_d:
                        return True
            return False
        candidates = [lu for lu in candidates if not overlaps(lu)]
        if not candidates:
            raise ApiError(ERR_LOANER_UNAVAILABLE,
                           "No AVAILABLE loaner of the right model with grade A/B", 409)
        candidates.sort(key=lambda lu: (lu["completed_loan_cycles"], lu["created_at"]))
        chosen = candidates[0]

    # credit check
    if customer["deposit_exposure_cents"] + chosen["deposit_value_cents"] > customer["credit_limit_cents"]:
        raise ApiError(ERR_CREDIT_LIMIT_EXCEEDED,
                       "Reservation would exceed customer credit limit", 402)

    res = new_entity({
        "rma_id": rma["id"],
        "loaner_unit_id": chosen["id"],
        "mode": rma["service_option"],
        "start_date": start_s,
        "end_date": end_s,
        "status": "RESERVED",
        "shipped_at": None,
        "due_date": None,
        "returned_at": None,
        "late_fee_cents": 0,
        "damage_fee_cents": 0,
        "forfeit_charge_cents": 0,
        "late_notification_sent": False,
    })
    store.loaner_reservations[res["id"]] = res
    if chosen["status"] == "AVAILABLE":
        # PRD §3.7: "Creating the reservation moves the chosen loaner unit from
        # AVAILABLE to RESERVED". An adjacent-window pick of an already-RESERVED
        # unit leaves that status in place (no transition to undo).
        chosen["status"] = "RESERVED"
        touch(chosen)
    customer["deposit_exposure_cents"] += chosen["deposit_value_cents"]
    touch(customer)
    return success(serialize(res), status=201)


@app.route("/depot/loaner-reservations/<reservationId>", methods=["GET"])
def get_reservation(reservationId):
    uid, role = require_roles("Customer", "IntakeAgent", "DepotTechnician", "DepotManager")
    res = get_or_404("loaner_reservations", reservationId, ERR_RESERVATION_NOT_FOUND, "Reservation")
    rma = store.rmas.get(res["rma_id"])
    if rma:
        check_owner(uid, role, rma["customer_id"])
    return success(serialize(res))


@app.route("/depot/loaner-reservations", methods=["GET"])
def list_reservations():
    require_roles("IntakeAgent", "DepotTechnician", "DepotManager")
    limit, offset = pagination_params()
    items = sorted(store.loaner_reservations.values(), key=lambda e: e["created_at"])
    for key in ("rma_id", "loaner_unit_id", "status"):
        v = request.args.get(key)
        if v:
            items = [r for r in items if str(r.get(key)) == v]
    page, pg = paginate(items, limit, offset)
    return success(serialize_list(page), response_type="array", pagination=pg)


@app.route("/depot/loaner-reservations/<reservationId>/ship", methods=["POST"])
def ship_reservation(reservationId):
    require_roles("IntakeAgent")
    res = get_or_404("loaner_reservations", reservationId, ERR_RESERVATION_NOT_FOUND, "Reservation")
    if res["status"] != "RESERVED":
        raise invalid_reservation_state("Reservation must be RESERVED to ship")
    lu = store.loaner_units.get(res["loaner_unit_id"])
    res["status"] = "SHIPPED"
    res["shipped_at"] = clock_iso()
    touch(res)
    if lu:
        lu["status"] = "SHIPPED_OUT"
        touch(lu)
    return success(serialize(res))


@app.route("/depot/loaner-reservations/<reservationId>/return", methods=["POST"])
def return_reservation(reservationId):
    require_roles("IntakeAgent")
    res = get_or_404("loaner_reservations", reservationId, ERR_RESERVATION_NOT_FOUND, "Reservation")
    if res["status"] != "SHIPPED":
        raise invalid_reservation_state("Reservation must be SHIPPED to return")
    if res["mode"] != "LOANER":
        raise invalid_reservation_state("Return is a LOANER-mode workflow")
    data = body()
    condition = req_enum(data, "condition", {"OK", "DAMAGED"})
    damage_assessment = opt_int(data, "damage_assessment_cents", 0)
    lu = store.loaner_units.get(res["loaner_unit_id"])

    # finalize late fee
    res["late_fee_cents"] = compute_late_fee(res, clock_now().date())
    if condition == "DAMAGED":
        deposit = lu["deposit_value_cents"] if lu else 0
        res["damage_fee_cents"] = min(damage_assessment, deposit)
        res["status"] = "CLOSED_DAMAGED"
    else:
        res["status"] = "CLOSED_RETURNED"
    res["returned_at"] = clock_iso()
    touch(res)
    if lu:
        lu["status"] = "INSPECTION"
        touch(lu)
    release_deposit(res)
    return success(serialize(res))


@app.route("/depot/loaner-reservations/<reservationId>/cancel", methods=["POST"])
def cancel_reservation(reservationId):
    require_roles("IntakeAgent")
    res = get_or_404("loaner_reservations", reservationId, ERR_RESERVATION_NOT_FOUND, "Reservation")
    if res["status"] != "RESERVED":
        raise invalid_reservation_state("Only RESERVED reservations can be cancelled")
    res["status"] = "CANCELLED"
    touch(res)
    lu = store.loaner_units.get(res["loaner_unit_id"])
    if lu and lu["status"] == "RESERVED":
        lu["status"] = "AVAILABLE"
        touch(lu)
    release_deposit(res)
    return success(serialize(res))


@app.route("/depot/loaner-reservations/<reservationId>/forfeit", methods=["POST"])
def forfeit_reservation(reservationId):
    require_roles("IntakeAgent", "DepotManager")
    res = get_or_404("loaner_reservations", reservationId, ERR_RESERVATION_NOT_FOUND, "Reservation")
    if res["status"] != "SHIPPED":
        raise invalid_reservation_state("Only SHIPPED reservations can be forfeited")
    lu = store.loaner_units.get(res["loaner_unit_id"])
    res["late_fee_cents"] = compute_late_fee(res, clock_now().date())
    deposit = lu["deposit_value_cents"] if lu else 0
    res["forfeit_charge_cents"] = deposit + res["late_fee_cents"]
    res["status"] = "CLOSED_FORFEITED"
    touch(res)
    if lu:
        lu["status"] = "RETIRED"
        touch(lu)
    release_deposit(res)
    return success(serialize(res))


# ====================================================================
# Engineering escalations
# ====================================================================

@app.route("/depot/engineering-escalations", methods=["POST"])
def create_escalation():
    require_roles("EngineeringLead")
    data = body()
    rma_id = data.get("rma_id")
    fc_id = data.get("failure_code_id")
    rma = store.rmas.get(rma_id) if rma_id else None
    if rma is None:
        raise ApiError(ERR_RMA_NOT_FOUND, "RMA not found", 404)
    fc = store.failure_codes.get(fc_id) if fc_id else None
    if fc is None:
        raise ApiError(ERR_FAILURE_CODE_NOT_FOUND, "Failure code not found", 404)
    unit = store.units.get(rma["unit_id"])
    esc = new_entity({
        "rma_id": rma["id"],
        "model_id": unit["model_id"],
        "failure_code_id": fc_id,
        "trigger_source": "MANUAL",
        "status": "OPEN",
        "monitoring_until": None,
        "recurrence_count": 0,
        "resolution_note": None,
    })
    store.engineering_escalations[esc["id"]] = esc
    if not rma.get("engineering_review_pending"):
        rma["engineering_review_pending"] = True
        touch(rma)
    return success(serialize(esc), status=201)


@app.route("/depot/engineering-escalations/<escalationId>", methods=["GET"])
def get_escalation(escalationId):
    require_roles("DepotTechnician", "DepotManager", "EngineeringLead")
    esc = get_or_404("engineering_escalations", escalationId, ERR_ESCALATION_NOT_FOUND, "Escalation")
    return success(serialize(esc))


@app.route("/depot/engineering-escalations", methods=["GET"])
def list_escalations():
    require_roles("DepotTechnician", "DepotManager", "EngineeringLead")
    limit, offset = pagination_params()
    items = sorted(store.engineering_escalations.values(), key=lambda e: e["created_at"])
    for key in ("rma_id", "failure_code_id", "model_id", "status"):
        v = request.args.get(key)
        if v:
            items = [e for e in items if str(e.get(key)) == v]
    page, pg = paginate(items, limit, offset)
    return success(serialize_list(page), response_type="array", pagination=pg)


@app.route("/depot/engineering-escalations/<escalationId>/acknowledge", methods=["POST"])
def acknowledge_escalation(escalationId):
    require_roles("EngineeringLead")
    esc = get_or_404("engineering_escalations", escalationId, ERR_ESCALATION_NOT_FOUND, "Escalation")
    if esc["status"] != "OPEN":
        raise invalid_escalation_state("Escalation must be OPEN to acknowledge")
    esc["status"] = "ACKNOWLEDGED"
    touch(esc)
    return success(serialize(esc))


@app.route("/depot/engineering-escalations/<escalationId>/contain", methods=["POST"])
def contain_escalation(escalationId):
    require_roles("EngineeringLead")
    esc = get_or_404("engineering_escalations", escalationId, ERR_ESCALATION_NOT_FOUND, "Escalation")
    if esc["status"] not in ("OPEN", "ACKNOWLEDGED"):
        raise invalid_escalation_state("Escalation must be OPEN or ACKNOWLEDGED to contain")
    esc["status"] = "CONTAINMENT_ACTIVE"
    touch(esc)
    model = store.product_models.get(esc["model_id"])
    if model and not model.get("containment_flag"):
        model["containment_flag"] = True
        touch(model)
    return success(serialize(esc))


@app.route("/depot/engineering-escalations/<escalationId>/resolve", methods=["POST"])
def resolve_escalation(escalationId):
    require_roles("EngineeringLead")
    esc = get_or_404("engineering_escalations", escalationId, ERR_ESCALATION_NOT_FOUND, "Escalation")
    if esc["status"] not in ("OPEN", "ACKNOWLEDGED", "CONTAINMENT_ACTIVE"):
        raise invalid_escalation_state("Escalation cannot be resolved from current state")
    data = body()
    note = data.get("resolution_note")
    if not isinstance(note, str) or not note:
        raise validation("resolution_note is required")
    esc["resolution_note"] = note
    # RESOLVED then immediately MONITORING
    monitoring_until = clock_now().date() + timedelta(days=MONITORING_DAYS)
    esc["status"] = "MONITORING"
    esc["monitoring_until"] = monitoring_until.isoformat()
    touch(esc)
    # clear engineering_review_pending on RMAs sharing (model, failure code)
    for rma in store.rmas.values():
        unit = store.units.get(rma["unit_id"])
        if (unit and unit["model_id"] == esc["model_id"]
                and rma.get("primary_failure_code_id") == esc["failure_code_id"]
                and rma.get("engineering_review_pending")):
            rma["engineering_review_pending"] = False
            touch(rma)
    # release containment_flag if no other CONTAINMENT_ACTIVE for this model
    model = store.product_models.get(esc["model_id"])
    if model:
        still_contained = any(e["id"] != esc["id"] and e["model_id"] == esc["model_id"]
                              and e["status"] == "CONTAINMENT_ACTIVE"
                              for e in store.engineering_escalations.values())
        if not still_contained and model.get("containment_flag"):
            model["containment_flag"] = False
            touch(model)
    return success(serialize(esc))


# ====================================================================
# Repair lines
# ====================================================================

@app.route("/depot/repair-lines/<repairLineId>", methods=["GET"])
def get_repair_line(repairLineId):
    require_roles("DepotTechnician", "DepotManager", "EngineeringLead")
    line = get_or_404("repair_lines", repairLineId, ERR_REPAIR_LINE_NOT_FOUND, "Repair line")
    return success(serialize(line))


@app.route("/depot/repair-lines", methods=["GET"])
def list_repair_lines():
    require_roles("DepotTechnician", "DepotManager", "EngineeringLead")
    limit, offset = pagination_params()
    items = sorted(store.repair_lines.values(), key=lambda e: e["created_at"])
    for key in ("rma_id", "part_id", "failure_code_id", "status"):
        v = request.args.get(key)
        if v:
            items = [l for l in items if str(l.get(key)) == v]
    page, pg = paginate(items, limit, offset)
    return success(serialize_list(page), response_type="array", pagination=pg)


@app.route("/depot/repair-lines/<repairLineId>/reverse", methods=["POST"])
def reverse_repair_line(repairLineId):
    require_roles("DepotTechnician")
    line = get_or_404("repair_lines", repairLineId, ERR_REPAIR_LINE_NOT_FOUND, "Repair line")
    if line["status"] != "CONSUMED":
        raise invalid_line_state("Repair line is not CONSUMED")
    rma = store.rmas.get(line["rma_id"])
    if rma is None or rma["status"] not in ("IN_REPAIR", "AWAITING_PARTS"):
        raise invalid_rma_state("RMA must be IN_REPAIR or AWAITING_PARTS to reverse a line")
    line["status"] = "REVERSED"
    touch(line)
    part = store.parts.get(line["part_id"])
    if part:
        part["stock_on_hand"] += line["quantity"]
        touch(part)
    return success(serialize(line))


# ====================================================================
# Notifications
# ====================================================================

@app.route("/depot/rmas/<rmaId>/notifications", methods=["GET"])
def list_notifications(rmaId):
    uid, role = require_roles("Customer", "IntakeAgent", "DepotManager")
    rma = find_rma_by_id_or_404(rmaId)
    check_owner(uid, role, rma["customer_id"])
    limit, offset = pagination_params()
    items = sorted([n for n in store.notification_events.values() if n["rma_id"] == rma["id"]],
                   key=lambda e: e["created_at"])
    et = request.args.get("event_type")
    if et:
        items = [n for n in items if n["event_type"] == et]
    page, pg = paginate(items, limit, offset)
    return success(serialize_list(page), response_type="array", pagination=pg)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
