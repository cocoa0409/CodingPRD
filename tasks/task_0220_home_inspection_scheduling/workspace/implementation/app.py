"""Home Inspection Scheduling & Reporting API — entry point and all routes.

Storage is in-memory only (see db.py). The store starts empty on every boot;
nothing is seeded. Run with `bash start.sh`, which reads $PORT and binds 0.0.0.0.
"""
import os

from flask import Flask, request

import errors
import response
import calculations as calc
import scheduling
from db import db, now_iso
from middleware import authenticate, require_roles
from common import (
    make_common,
    touch,
    get_json_body,
    parse_pagination,
    paginate,
    sort_by_created,
    require_field,
    require_string,
    require_int,
    optional_int,
    require_enum,
    require_number,
    optional_number,
)
from services import (
    active_addons_for_order,
    recompute_order_duration,
    compute_quoted_fee,
    compute_final_fee,
    recompute_amount_due,
    report_for_order,
    booked_minutes,
    NON_TERMINAL_ORDER_STATUSES,
)

app = Flask(__name__)

INSPECTION_TYPES = {"BUYER", "SELLER", "FOUR_POINT", "WIND_MIT"}
ADDON_KINDS = {"RADON", "TERMITE", "SEWER"}
DEFECT_SEVERITIES = {"MINOR", "MAJOR", "CRITICAL"}
CLIENT_ROLES = {"BUYER", "SELLER"}


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(errors.ApiError)
def handle_api_error(exc):
    return response.error_response(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def handle_404(exc):
    return response.error_response(errors.ERR_NOT_FOUND, "Resource not found.", 404)


@app.errorhandler(405)
def handle_405(exc):
    # Method not allowed — treat the route/method combination as not found.
    return response.error_response(errors.ERR_NOT_FOUND, "Resource not found.", 404)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, errors.ApiError):
        return handle_api_error(exc)
    return response.error_response("ERR_INTERNAL", "Internal server error: %s" % exc, 500)


# ---------------------------------------------------------------------------
# Lookup helpers (existence -> ERR_NOT_FOUND)
# ---------------------------------------------------------------------------
def get_or_404(collection, entity_id):
    ent = collection.get(entity_id)
    if ent is None:
        raise errors.not_found()
    return ent


# ===========================================================================
# Territory
# ===========================================================================
@app.route("/territories", methods=["POST"])
def create_territory():
    caller = authenticate()
    require_roles(caller, {"Scheduler"})
    body = get_json_body()
    name = require_string(body, "name")
    zip_codes = require_field(body, "zip_codes")
    if not isinstance(zip_codes, list) or not all(isinstance(z, str) for z in zip_codes):
        raise errors.invalid_request("zip_codes must be an array of strings.")
    travel_buffer = optional_int(body, "travel_buffer_minutes", 30, minimum=0, maximum=240)

    ent = make_common(with_version=True)
    ent.update({
        "name": name,
        "zip_codes": list(zip_codes),
        "travel_buffer_minutes": travel_buffer,
    })
    db.territories[ent["id"]] = ent
    return response.object_response(ent, status=201)


@app.route("/territories/<tid>", methods=["GET"])
def get_territory(tid):
    caller = authenticate()
    require_roles(caller, {"Scheduler", "Inspector"})
    ent = get_or_404(db.territories, tid)
    return response.object_response(ent, status=200)


@app.route("/territories", methods=["GET"])
def list_territories():
    caller = authenticate()
    require_roles(caller, {"Scheduler", "Inspector"})
    limit, offset = parse_pagination()
    items = sort_by_created(list(db.territories.values()))
    page, meta = paginate(items, limit, offset)
    return response.array_response(page, meta)


# ===========================================================================
# FeeSchedule
# ===========================================================================
@app.route("/fee-schedules", methods=["POST"])
def create_fee_schedule():
    caller = authenticate()
    require_roles(caller, {"Scheduler"})
    body = get_json_body()
    label = require_string(body, "label")
    base_rate = require_int(body, "base_rate_cents", minimum=0)
    t1_rate = require_int(body, "tier1_rate_cents_per_sqft", minimum=0)
    t2_rate = require_int(body, "tier2_rate_cents_per_sqft", minimum=0)
    t3_rate = require_int(body, "tier3_rate_cents_per_sqft", minimum=0)
    radon = require_int(body, "addon_radon_cents", minimum=0)
    termite = require_int(body, "addon_termite_cents", minimum=0)
    sewer = require_int(body, "addon_sewer_cents", minimum=0)
    tier1_max = optional_int(body, "tier1_max_sqft", 2000, minimum=1)
    tier2_max = optional_int(body, "tier2_max_sqft", 4000)
    if tier2_max <= tier1_max:
        raise errors.invalid_request("tier2_max_sqft must be greater than tier1_max_sqft.")
    discount = optional_number(body, "reinspection_discount_pct", 0.5, minimum=0, maximum=1)

    ent = make_common(with_version=True)
    ent.update({
        "label": label,
        "base_rate_cents": base_rate,
        "tier1_max_sqft": tier1_max,
        "tier2_max_sqft": tier2_max,
        "tier1_rate_cents_per_sqft": t1_rate,
        "tier2_rate_cents_per_sqft": t2_rate,
        "tier3_rate_cents_per_sqft": t3_rate,
        "addon_radon_cents": radon,
        "addon_termite_cents": termite,
        "addon_sewer_cents": sewer,
        "reinspection_discount_pct": discount,
        "status": "DRAFT",
    })
    db.fee_schedules[ent["id"]] = ent
    return response.object_response(ent, status=201)


@app.route("/fee-schedules/<fid>/publish", methods=["POST"])
def publish_fee_schedule(fid):
    caller = authenticate()
    require_roles(caller, {"Scheduler"})
    ent = get_or_404(db.fee_schedules, fid)
    if ent["status"] != "DRAFT":
        raise errors.invalid_state("Fee schedule is not in DRAFT.")
    ent["status"] = "PUBLISHED"
    touch(ent)
    return response.object_response(ent, status=200)


@app.route("/fee-schedules/<fid>", methods=["GET"])
def get_fee_schedule(fid):
    caller = authenticate()
    require_roles(caller, {"Scheduler", "Inspector"})
    ent = get_or_404(db.fee_schedules, fid)
    return response.object_response(ent, status=200)


# ===========================================================================
# Inspector
# ===========================================================================
@app.route("/inspectors", methods=["POST"])
def create_inspector():
    caller = authenticate()
    require_roles(caller, {"Scheduler"})
    body = get_json_body()
    full_name = require_string(body, "full_name")
    territory_id = require_string(body, "territory_id")
    certifications = require_field(body, "certifications")
    if not isinstance(certifications, list) or not all(
        isinstance(c, str) and c in INSPECTION_TYPES for c in certifications
    ):
        raise errors.invalid_request("certifications must be a subset of inspection types.")
    daily_cap = optional_int(body, "daily_capacity_minutes", 480, minimum=1)
    # Referenced territory must exist (FK existence after body well-formedness).
    get_or_404(db.territories, territory_id)

    ent = make_common(with_version=True)
    ent.update({
        "full_name": full_name,
        "territory_id": territory_id,
        "certifications": list(certifications),
        "daily_capacity_minutes": daily_cap,
        "status": "ACTIVE",
    })
    db.inspectors[ent["id"]] = ent
    return response.object_response(ent, status=201)


@app.route("/inspectors/<iid>", methods=["GET"])
def get_inspector(iid):
    caller = authenticate()
    require_roles(caller, {"Scheduler", "Inspector"})
    ent = get_or_404(db.inspectors, iid)
    return response.object_response(ent, status=200)


@app.route("/inspectors", methods=["GET"])
def list_inspectors():
    caller = authenticate()
    require_roles(caller, {"Scheduler", "Inspector"})
    limit, offset = parse_pagination()
    territory_id = request.args.get("territory_id")
    items = list(db.inspectors.values())
    if territory_id is not None:
        items = [i for i in items if i["territory_id"] == territory_id]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return response.array_response(page, meta)


@app.route("/inspectors/<iid>/suspend", methods=["POST"])
def suspend_inspector(iid):
    caller = authenticate()
    require_roles(caller, {"Scheduler"})
    ent = get_or_404(db.inspectors, iid)
    if ent["status"] != "ACTIVE":
        raise errors.invalid_state("Inspector is not ACTIVE.")
    ent["status"] = "SUSPENDED"
    touch(ent)
    return response.object_response(ent, status=200)


@app.route("/inspectors/<iid>/daily-load", methods=["GET"])
def inspector_daily_load(iid):
    caller = authenticate()
    require_roles(caller, {"Scheduler", "Inspector"})
    ent = get_or_404(db.inspectors, iid)
    date_str = request.args.get("date")
    if date_str is None or date_str == "":
        raise errors.validation_range("date query parameter is required.")
    # Validate YYYY-MM-DD shape.
    import datetime as _dt
    try:
        _dt.datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        raise errors.validation_range("date must be YYYY-MM-DD.")
    data = {
        "inspector_id": ent["id"],
        "date": date_str,
        "booked_minutes": booked_minutes(ent["id"], date_str),
        "daily_capacity_minutes": ent["daily_capacity_minutes"],
    }
    return response.object_response(data, status=200)


# ===========================================================================
# Client / Agent (leaner: id + created_at only)
# ===========================================================================
@app.route("/clients", methods=["POST"])
def create_client():
    caller = authenticate()
    require_roles(caller, {"Scheduler"})
    body = get_json_body()
    full_name = require_string(body, "full_name")
    email = require_string(body, "email")
    role_in_deal = require_enum(body, "role_in_deal", CLIENT_ROLES)

    ent = make_common(with_version=False)
    ent.update({
        "full_name": full_name,
        "email": email,
        "role_in_deal": role_in_deal,
    })
    db.clients[ent["id"]] = ent
    return response.object_response(ent, status=201)


@app.route("/clients/<cid>", methods=["GET"])
def get_client(cid):
    caller = authenticate()
    require_roles(caller, {"Scheduler", "Client"})
    ent = get_or_404(db.clients, cid)
    return response.object_response(ent, status=200)


@app.route("/agents", methods=["POST"])
def create_agent():
    caller = authenticate()
    require_roles(caller, {"Scheduler"})
    body = get_json_body()
    full_name = require_string(body, "full_name")
    email = require_string(body, "email")
    brokerage = require_string(body, "brokerage")

    ent = make_common(with_version=False)
    ent.update({
        "full_name": full_name,
        "email": email,
        "brokerage": brokerage,
    })
    db.agents[ent["id"]] = ent
    return response.object_response(ent, status=201)


@app.route("/agents/<aid>", methods=["GET"])
def get_agent(aid):
    caller = authenticate()
    require_roles(caller, {"Scheduler", "Agent"})
    ent = get_or_404(db.agents, aid)
    return response.object_response(ent, status=200)


# ===========================================================================
# Property
# ===========================================================================
@app.route("/properties", methods=["POST"])
def create_property():
    caller = authenticate()
    require_roles(caller, {"Scheduler", "Client", "Agent"})
    body = get_json_body()
    address_line = require_string(body, "address_line")
    zip_code = require_string(body, "zip_code")
    square_footage = require_int(body, "square_footage", minimum=1)
    year_built = require_int(body, "year_built", minimum=1850, maximum=2100)

    ent = make_common(with_version=True)
    ent.update({
        "address_line": address_line,
        "zip_code": zip_code,
        "square_footage": square_footage,
        "year_built": year_built,
    })
    db.properties[ent["id"]] = ent
    return response.object_response(ent, status=201)


@app.route("/properties/<pid>", methods=["GET"])
def get_property(pid):
    caller = authenticate()
    require_roles(caller, {"Scheduler", "Client", "Agent"})
    ent = get_or_404(db.properties, pid)
    return response.object_response(ent, status=200)


# ===========================================================================
# InspectionOrder
# ===========================================================================
@app.route("/inspection-orders", methods=["POST"])
def create_order():
    caller = authenticate()
    require_roles(caller, {"Scheduler", "Client", "Agent"})
    body = get_json_body()
    property_id = require_string(body, "property_id")
    client_id = require_string(body, "client_id")
    agent_id = require_string(body, "agent_id")
    fee_schedule_id = require_string(body, "fee_schedule_id")
    inspection_type = require_enum(body, "inspection_type", INSPECTION_TYPES)

    # FK existence (after body well-formedness).
    get_or_404(db.properties, property_id)
    get_or_404(db.clients, client_id)
    get_or_404(db.agents, agent_id)
    fs = get_or_404(db.fee_schedules, fee_schedule_id)
    # Only a PUBLISHED schedule may be pinned (ERR_INVALID_REQUEST per PRD §3.1).
    if fs["status"] != "PUBLISHED":
        raise errors.invalid_request("Fee schedule must be PUBLISHED to pin to an order.")

    ent = make_common(with_version=True)  # version starts at 1
    ent.update({
        "property_id": property_id,
        "client_id": client_id,
        "agent_id": agent_id,
        "fee_schedule_id": fee_schedule_id,
        "inspector_id": None,
        "parent_order_id": None,
        "order_kind": "PRIMARY",
        "inspection_type": inspection_type,
        "scheduled_start": None,
        "scheduled_date": None,
        "duration_minutes": None,
        "status": "REQUESTED",
        "quoted_fee_cents": None,
        "final_fee_cents": None,
        "amount_paid_cents": 0,
        "amount_refunded_cents": 0,
        "amount_due_cents": 0,
    })
    # amount_due at REQUESTED: effective fee 0.
    recompute_amount_due(ent)
    db.inspection_orders[ent["id"]] = ent
    return response.object_response(ent, status=201)


@app.route("/inspection-orders/<oid>", methods=["GET"])
def get_order(oid):
    caller = authenticate()
    require_roles(caller, {"Scheduler", "Inspector", "Client", "Agent"})
    ent = get_or_404(db.inspection_orders, oid)
    return response.object_response(ent, status=200)


@app.route("/inspection-orders", methods=["GET"])
def list_orders():
    caller = authenticate()
    require_roles(caller, {"Scheduler", "Inspector", "Client", "Agent"})
    limit, offset = parse_pagination()
    items = list(db.inspection_orders.values())
    filters = {
        "property_id": request.args.get("property_id"),
        "inspector_id": request.args.get("inspector_id"),
        "parent_order_id": request.args.get("parent_order_id"),
        "client_id": request.args.get("client_id"),
        "agent_id": request.args.get("agent_id"),
        "fee_schedule_id": request.args.get("fee_schedule_id"),
        "status": request.args.get("status"),
    }
    for field, val in filters.items():
        if val is not None:
            items = [o for o in items if o.get(field) == val]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return response.array_response(page, meta)


@app.route("/inspection-orders/<oid>/schedule", methods=["POST"])
def schedule_order(oid):
    caller = authenticate()
    require_roles(caller, {"Scheduler"})
    order = get_or_404(db.inspection_orders, oid)
    body = get_json_body()
    inspector_id = require_string(body, "inspector_id")
    scheduled_start_raw = require_field(body, "scheduled_start")
    start_dt = scheduling.parse_iso_datetime(scheduled_start_raw)

    # FK existence.
    inspector = get_or_404(db.inspectors, inspector_id)

    # State precondition: must be REQUESTED.
    if order["status"] != "REQUESTED":
        raise errors.invalid_state("Order is not in REQUESTED status.")
    # Inspector must be ACTIVE.
    if inspector["status"] != "ACTIVE":
        raise errors.invalid_state("Inspector is not ACTIVE.")

    prop = db.properties[order["property_id"]]

    # Compute the duration this booking would consume (base + ACTIVE add-ons).
    recompute_order_duration(order)
    duration = order["duration_minutes"]
    scheduled_date = scheduling.calendar_date(start_dt)

    # Business checks in pinned priority order.
    scheduling.check_certification(order, inspector, prop)
    territory = scheduling.check_territory(inspector, prop)
    scheduling.check_double_booking(inspector, territory, start_dt, duration, exclude_order_id=order["id"])
    scheduling.check_same_day_property(order["property_id"], scheduled_date, exclude_order_id=order["id"])
    scheduling.check_daily_capacity(inspector, scheduled_date, duration, exclude_order_id=order["id"])

    # Side effects.
    order["inspector_id"] = inspector_id
    order["scheduled_start"] = scheduled_start_raw
    order["scheduled_date"] = scheduled_date
    order["status"] = "SCHEDULED"
    order["quoted_fee_cents"] = compute_quoted_fee(order)
    recompute_amount_due(order)
    touch(order)
    return response.object_response(order, status=200)


@app.route("/inspection-orders/<oid>/unschedule", methods=["POST"])
def unschedule_order(oid):
    caller = authenticate()
    require_roles(caller, {"Scheduler"})
    order = get_or_404(db.inspection_orders, oid)
    if order["status"] != "SCHEDULED":
        raise errors.invalid_state("Order is not in SCHEDULED status.")
    # Returning to REQUESTED releases the slot; ledger credit is implicit because
    # booked_minutes only counts booked-state orders and the order leaves that set.
    order["status"] = "REQUESTED"
    order["inspector_id"] = None
    order["scheduled_start"] = None
    order["scheduled_date"] = None
    order["quoted_fee_cents"] = None
    recompute_amount_due(order)
    touch(order)
    return response.object_response(order, status=200)


@app.route("/inspection-orders/<oid>/start", methods=["POST"])
def start_order(oid):
    caller = authenticate()
    require_roles(caller, {"Inspector"})
    order = get_or_404(db.inspection_orders, oid)
    if order["status"] != "SCHEDULED":
        raise errors.invalid_state("Order is not in SCHEDULED status.")
    if order["inspector_id"] != caller.user_id:
        raise errors.not_assigned_inspector()
    order["status"] = "IN_PROGRESS"
    recompute_amount_due(order)
    touch(order)
    return response.object_response(order, status=200)


@app.route("/inspection-orders/<oid>/report", methods=["POST"])
def create_report(oid):
    caller = authenticate()
    require_roles(caller, {"Inspector"})
    order = get_or_404(db.inspection_orders, oid)
    body = get_json_body()
    measured = require_int(body, "measured_square_footage", minimum=1)

    if order["status"] != "IN_PROGRESS":
        raise errors.invalid_state("Order is not in IN_PROGRESS status.")
    if order["inspector_id"] != caller.user_id:
        raise errors.not_assigned_inspector()
    if report_for_order(order["id"]) is not None:
        raise errors.invalid_state("A report already exists for this order.")

    report = make_common(with_version=True)
    report.update({
        "order_id": order["id"],
        "measured_square_footage": measured,
        "provisional_risk_score": 0,
        "final_risk_score": None,
        "severity_band": None,
        "status": "DRAFT",
    })
    db.reports[report["id"]] = report

    order["status"] = "REPORT_DRAFT"
    recompute_amount_due(order)
    touch(order)
    return response.object_response(report, status=201)


@app.route("/inspection-orders/<oid>/pay", methods=["POST"])
def pay_order(oid):
    caller = authenticate()
    require_roles(caller, {"Scheduler", "Client", "Agent"})
    order = get_or_404(db.inspection_orders, oid)
    body = get_json_body()
    amount = require_int(body, "amount_cents", minimum=0)
    order["amount_paid_cents"] += amount
    recompute_amount_due(order)
    touch(order)
    return response.object_response(order, status=200)


@app.route("/inspection-orders/<oid>/deliver", methods=["POST"])
def deliver_order(oid):
    caller = authenticate()
    require_roles(caller, {"Scheduler"})
    order = get_or_404(db.inspection_orders, oid)

    if order["status"] != "REPORT_DRAFT":
        raise errors.invalid_state("Order is not in REPORT_DRAFT status.")
    report = report_for_order(order["id"])
    if report is None or report["status"] != "APPROVED":
        raise errors.invalid_state("Order's report is not APPROVED.")

    # Compute final fee first so the paid-in-full check uses the final balance.
    order["final_fee_cents"] = compute_final_fee(order)
    # Provisionally evaluate amount_due against the final fee while still REPORT_DRAFT
    # to determine the payment gate; effective fee at REPORT_DRAFT is quoted, so
    # build the final-due figure explicitly.
    final_due = (
        order["final_fee_cents"]
        - order["amount_paid_cents"]
        + order["amount_refunded_cents"]
    )
    if final_due > 0:
        # Roll back the speculative final fee write before failing.
        order["final_fee_cents"] = None
        raise errors.ApiError(errors.ERR_ORDER_UNPAID, 402, "Order is not fully paid.")

    # Commit delivery.
    order["status"] = "DELIVERED"
    recompute_amount_due(order)  # now uses final fee (status DELIVERED)

    # Cascade link 1: report locked into its delivered state. The Report status
    # enum has no DELIVERED member (DRAFT/SUBMITTED/APPROVED/REJECTED/VOIDED), and
    # the PRD declares no extra report field for this, so the lock is enforced
    # structurally: the report stays APPROVED and a DELIVERED order admits no
    # further report transitions. No undeclared field is added to the report.

    # Cascade link 2: create CLIENT + AGENT delivery rows snapshotting severity_band.
    client = db.clients[order["client_id"]]
    agent = db.agents[order["agent_id"]]
    band = report.get("severity_band")
    for recipient_kind, email in (("CLIENT", client["email"]), ("AGENT", agent["email"])):
        delivery = make_common(with_version=True)
        delivery.update({
            "order_id": order["id"],
            "recipient_kind": recipient_kind,
            "recipient_email": email,
            "severity_band_snapshot": band,
            "status": "SENT",
        })
        db.deliveries[delivery["id"]] = delivery
        # Cascade link 3: each delivery creation participates in recomputing amount_due.
        recompute_amount_due(order)

    touch(order)
    return response.object_response(order, status=200)


@app.route("/inspection-orders/<oid>/cancel", methods=["POST"])
def cancel_order(oid):
    caller = authenticate()
    require_roles(caller, {"Scheduler"})
    order = get_or_404(db.inspection_orders, oid)

    if order["status"] not in NON_TERMINAL_ORDER_STATUSES:
        raise errors.invalid_state("Order is not in a cancellable (non-terminal) state.")

    # Move to CANCELLED. The inspector ledger credit is implicit: booked_minutes
    # only counts booked-state orders, and CANCELLED is not a booked state, so the
    # order's duration stops counting against the date once cancelled.
    order["status"] = "CANCELLED"

    # Refund every paid cent (money conserved).
    order["amount_refunded_cents"] += order["amount_paid_cents"]
    recompute_amount_due(order)

    # Cascade link 1: void any report on this order.
    report = report_for_order(order["id"])
    if report is not None and report["status"] != "VOIDED":
        report["status"] = "VOIDED"
        # Cascade link 2: all that report's non-VOIDED defects -> VOIDED.
        for d in db.defects.values():
            if d["report_id"] == report["id"] and d["status"] != "VOIDED":
                d["status"] = "VOIDED"
                touch(d)
        touch(report)

    # Any SENT delivery on this order -> CANCELLED.
    for dlv in db.deliveries.values():
        if dlv["order_id"] == order["id"] and dlv["status"] == "SENT":
            dlv["status"] = "CANCELLED"
            touch(dlv)

    touch(order)
    return response.object_response(order, status=200)


@app.route("/inspection-orders/<oid>/reinspect", methods=["POST"])
def reinspect_order(oid):
    caller = authenticate()
    require_roles(caller, {"Scheduler"})
    parent = get_or_404(db.inspection_orders, oid)
    body = get_json_body()
    inspector_id = require_string(body, "inspector_id")
    scheduled_start_raw = require_field(body, "scheduled_start")
    expected_version = require_int(body, "expected_order_version")
    start_dt = scheduling.parse_iso_datetime(scheduled_start_raw)

    # FK existence.
    inspector = get_or_404(db.inspectors, inspector_id)

    # State: parent must be DELIVERED.
    if parent["status"] != "DELIVERED":
        raise errors.invalid_state("Parent order is not DELIVERED.")

    parent_report = report_for_order(parent["id"])

    # Inspector must be ACTIVE.
    if inspector["status"] != "ACTIVE":
        raise errors.invalid_state("Inspector is not ACTIVE.")

    prop = db.properties[parent["property_id"]]

    # Re-inspection-specific gating, in priority order per validations table:
    # certification (7) -> territory (8) -> double-booking (9) -> same-day (10)
    # -> reinspection-too-soon (11) -> not-warranted (12) -> daily-capacity (14)
    # -> stale-version (16). The PRD §3.8 narrative lists severity-band and OCC
    # among the gating preconditions alongside the schedule checks; the validations
    # table fixes the precedence used when several fail at once.

    # Build the prospective new order's duration (base type + no add-ons yet).
    new_duration = calc.order_duration_minutes(parent["inspection_type"], [])
    scheduled_date = scheduling.calendar_date(start_dt)

    scheduling.check_certification(parent, inspector, prop)
    territory = scheduling.check_territory(inspector, prop)
    scheduling.check_double_booking(inspector, territory, start_dt, new_duration)
    scheduling.check_same_day_property(parent["property_id"], scheduled_date)

    # Re-inspection too soon: >= MIN_REINSPECTION_GAP_HOURS after parent scheduled_start.
    parent_start = scheduling.parse_iso_datetime(parent["scheduled_start"])
    gap_hours = (start_dt - parent_start).total_seconds() / 3600.0
    if gap_hours < scheduling.MIN_REINSPECTION_GAP_HOURS:
        raise errors.ApiError(
            errors.ERR_REINSPECTION_TOO_SOON, 409,
            "Re-inspection is scheduled too soon after the parent appointment.",
        )

    # Not warranted: parent severity_band must be MAJOR or CRITICAL.
    if parent_report is None or parent_report.get("severity_band") not in ("MAJOR", "CRITICAL"):
        raise errors.ApiError(
            errors.ERR_REINSPECTION_NOT_WARRANTED, 409,
            "Parent inspection did not grade MAJOR/CRITICAL.",
        )

    # Daily capacity.
    scheduling.check_daily_capacity(inspector, scheduled_date, new_duration)

    # OCC: expected_order_version must match the parent's current version.
    if expected_version != parent["version"]:
        raise errors.ApiError(
            errors.ERR_STALE_VERSION, 412,
            "expected_order_version does not match the parent order's version.",
        )

    # Create the new re-inspection order, already SCHEDULED.
    new_order = make_common(with_version=True)
    new_order.update({
        "property_id": parent["property_id"],
        "client_id": parent["client_id"],
        "agent_id": parent["agent_id"],
        "fee_schedule_id": parent["fee_schedule_id"],
        "inspector_id": inspector_id,
        "parent_order_id": parent["id"],
        "order_kind": "REINSPECTION",
        "inspection_type": parent["inspection_type"],
        "scheduled_start": scheduled_start_raw,
        "scheduled_date": scheduled_date,
        "duration_minutes": new_duration,
        "status": "SCHEDULED",
        "quoted_fee_cents": None,
        "final_fee_cents": None,
        "amount_paid_cents": 0,
        "amount_refunded_cents": 0,
        "amount_due_cents": 0,
    })
    db.inspection_orders[new_order["id"]] = new_order

    # Quoted fee then discount by the parent final-fee band.
    fs = db.fee_schedules[new_order["fee_schedule_id"]]
    quoted = compute_quoted_fee(new_order)
    new_order["quoted_fee_cents"] = calc.reinspection_fee_cents(
        quoted, parent["final_fee_cents"], fs["reinspection_discount_pct"]
    )
    recompute_amount_due(new_order)

    # Parent version bump records the spawned child.
    touch(parent)

    return response.object_response(new_order, status=201)


# ===========================================================================
# AddOn
# ===========================================================================
@app.route("/inspection-orders/<oid>/addons", methods=["POST"])
def create_addon(oid):
    caller = authenticate()
    require_roles(caller, {"Scheduler", "Client", "Agent"})
    order = get_or_404(db.inspection_orders, oid)
    body = get_json_body()
    kind = require_enum(body, "kind", ADDON_KINDS)

    # Order must be REQUESTED or SCHEDULED (not yet started); kind unique per order.
    if order["status"] not in ("REQUESTED", "SCHEDULED"):
        raise errors.ApiError(
            errors.ERR_DUPLICATE_ADDON, 409,
            "Order has already started; add-ons cannot be attached.",
        )
    for a in db.addons.values():
        if a["order_id"] == order["id"] and a["kind"] == kind and a["status"] == "ACTIVE":
            raise errors.ApiError(
                errors.ERR_DUPLICATE_ADDON, 409,
                "An ACTIVE add-on of this kind already exists on the order.",
            )

    fs = db.fee_schedules[order["fee_schedule_id"]]
    price_map = {
        "RADON": fs["addon_radon_cents"],
        "TERMITE": fs["addon_termite_cents"],
        "SEWER": fs["addon_sewer_cents"],
    }
    addon = make_common(with_version=True)
    addon.update({
        "order_id": order["id"],
        "kind": kind,
        "price_cents": price_map[kind],
        "added_duration_minutes": calc.ADDON_DURATION[kind],
        "status": "ACTIVE",
    })
    db.addons[addon["id"]] = addon

    # Recompute order duration; if SCHEDULED recompute quoted fee.
    recompute_order_duration(order)
    if order["status"] == "SCHEDULED":
        order["quoted_fee_cents"] = compute_quoted_fee(order)
    recompute_amount_due(order)
    touch(order)

    return response.object_response(addon, status=201)


@app.route("/inspection-orders/<oid>/addons", methods=["GET"])
def list_addons(oid):
    caller = authenticate()
    require_roles(caller, {"Scheduler", "Inspector", "Client", "Agent"})
    get_or_404(db.inspection_orders, oid)
    limit, offset = parse_pagination()
    items = [a for a in db.addons.values() if a["order_id"] == oid]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return response.array_response(page, meta)


@app.route("/addons/<aid>/remove", methods=["POST"])
def remove_addon(aid):
    caller = authenticate()
    require_roles(caller, {"Scheduler", "Client", "Agent"})
    addon = get_or_404(db.addons, aid)
    order = db.inspection_orders.get(addon["order_id"])
    if order is None:
        raise errors.not_found()
    # Only on a not-yet-started order.
    if order["status"] not in ("REQUESTED", "SCHEDULED"):
        raise errors.invalid_state("Order has already started; add-on cannot be removed.")
    if addon["status"] != "ACTIVE":
        raise errors.invalid_state("Add-on is not ACTIVE.")

    addon["status"] = "REMOVED"
    touch(addon)

    recompute_order_duration(order)
    if order["status"] == "SCHEDULED":
        order["quoted_fee_cents"] = compute_quoted_fee(order)
    recompute_amount_due(order)
    touch(order)
    return response.object_response(addon, status=200)


# ===========================================================================
# Report
# ===========================================================================
@app.route("/reports/<rid>", methods=["GET"])
def get_report(rid):
    caller = authenticate()
    require_roles(caller, {"Scheduler", "Inspector", "Client", "Agent"})
    ent = get_or_404(db.reports, rid)
    return response.object_response(ent, status=200)


@app.route("/inspection-orders/<oid>/reports", methods=["GET"])
def list_order_reports(oid):
    caller = authenticate()
    require_roles(caller, {"Scheduler", "Inspector", "Client", "Agent"})
    get_or_404(db.inspection_orders, oid)
    limit, offset = parse_pagination()
    items = [r for r in db.reports.values() if r["order_id"] == oid]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return response.array_response(page, meta)


def _defects_for_report(report_id):
    return [d for d in db.defects.values() if d["report_id"] == report_id]


@app.route("/reports/<rid>/submit", methods=["POST"])
def submit_report(rid):
    caller = authenticate()
    require_roles(caller, {"Inspector"})
    report = get_or_404(db.reports, rid)
    order = db.inspection_orders[report["order_id"]]

    if report["status"] != "DRAFT":
        raise errors.invalid_state("Report is not in DRAFT.")
    if order["inspector_id"] != caller.user_id:
        raise errors.not_assigned_inspector()
    if order["status"] != "REPORT_DRAFT":
        raise errors.invalid_state("Owning order is not in REPORT_DRAFT.")

    # Provisional risk score over all non-VOIDED defects.
    severities = [
        d["severity"] for d in _defects_for_report(report["id"])
        if d["status"] != "VOIDED"
    ]
    report["provisional_risk_score"] = calc.risk_score(severities)
    report["status"] = "SUBMITTED"
    touch(report)
    return response.object_response(report, status=200)


@app.route("/reports/<rid>/approve", methods=["POST"])
def approve_report(rid):
    caller = authenticate()
    require_roles(caller, {"Scheduler"})
    report = get_or_404(db.reports, rid)
    if report["status"] != "SUBMITTED":
        raise errors.invalid_state("Report is not SUBMITTED.")

    # Resolve each LOGGED defect: MAJOR/CRITICAL -> CONFIRMED, MINOR -> CLEARED.
    for d in _defects_for_report(report["id"]):
        if d["status"] == "LOGGED":
            if d["severity"] in ("MAJOR", "CRITICAL"):
                d["status"] = "CONFIRMED"
            else:  # MINOR
                d["status"] = "CLEARED"
            touch(d)

    # Final risk score over CONFIRMED defects only.
    confirmed = [
        d["severity"] for d in _defects_for_report(report["id"])
        if d["status"] == "CONFIRMED"
    ]
    report["final_risk_score"] = calc.risk_score(confirmed)
    report["severity_band"] = calc.severity_band(report["final_risk_score"])
    report["status"] = "APPROVED"
    touch(report)
    return response.object_response(report, status=200)


@app.route("/reports/<rid>/reject", methods=["POST"])
def reject_report(rid):
    caller = authenticate()
    require_roles(caller, {"Scheduler"})
    report = get_or_404(db.reports, rid)
    if report["status"] != "SUBMITTED":
        raise errors.invalid_state("Report is not SUBMITTED.")
    report["status"] = "REJECTED"
    touch(report)
    return response.object_response(report, status=200)


@app.route("/reports/<rid>/revise", methods=["POST"])
def revise_report(rid):
    caller = authenticate()
    require_roles(caller, {"Inspector"})
    report = get_or_404(db.reports, rid)
    order = db.inspection_orders[report["order_id"]]
    if report["status"] != "REJECTED":
        raise errors.invalid_state("Report is not REJECTED.")
    if order["inspector_id"] != caller.user_id:
        raise errors.not_assigned_inspector()
    report["status"] = "DRAFT"
    touch(report)
    return response.object_response(report, status=200)


# ===========================================================================
# Defect
# ===========================================================================
@app.route("/reports/<rid>/defects", methods=["POST"])
def create_defect(rid):
    caller = authenticate()
    require_roles(caller, {"Inspector"})
    report = get_or_404(db.reports, rid)
    order = db.inspection_orders[report["order_id"]]
    body = get_json_body()
    location = require_string(body, "location")
    severity = require_enum(body, "severity", DEFECT_SEVERITIES)

    # Defects are logged on a DRAFT report by the assigned inspector.
    if report["status"] != "DRAFT":
        raise errors.invalid_state("Report is not in DRAFT.")
    if order["inspector_id"] != caller.user_id:
        raise errors.not_assigned_inspector()

    defect = make_common(with_version=True)
    defect.update({
        "report_id": report["id"],
        "location": location,
        "severity": severity,
        "status": "LOGGED",
    })
    db.defects[defect["id"]] = defect

    # Logging a defect increments the report's version.
    touch(report)
    return response.object_response(defect, status=201)


@app.route("/reports/<rid>/defects", methods=["GET"])
def list_defects(rid):
    caller = authenticate()
    require_roles(caller, {"Scheduler", "Inspector", "Client", "Agent"})
    get_or_404(db.reports, rid)
    limit, offset = parse_pagination()
    items = [d for d in db.defects.values() if d["report_id"] == rid]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return response.array_response(page, meta)


# ===========================================================================
# Delivery
# ===========================================================================
@app.route("/inspection-orders/<oid>/deliveries", methods=["GET"])
def list_deliveries(oid):
    caller = authenticate()
    require_roles(caller, {"Scheduler", "Inspector", "Client", "Agent"})
    get_or_404(db.inspection_orders, oid)
    limit, offset = parse_pagination()
    items = [d for d in db.deliveries.values() if d["order_id"] == oid]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return response.array_response(page, meta)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
