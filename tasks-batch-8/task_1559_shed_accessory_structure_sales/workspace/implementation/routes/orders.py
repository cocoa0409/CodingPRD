"""Order endpoints: create/get/list/amend/submit-site-check/schedule/start/
complete/cancel/payments."""

from flask import Blueprint, request, g

import db
from errors import (
    invalid_request, invalid_state, forbidden, ApiError,
    ERR_STALE_VERSION, ERR_ANCHOR_REQUIRED, ERR_CONFIG_OUT_OF_BOUNDS,
    ERR_DELIVERY_MODE_UNSUPPORTED, ERR_ASSESSOR_WINDOW_CONFLICT,
    ERR_CREW_DATE_CONFLICT, ERR_DATE_IN_PAST, ERR_DEPOSIT_INSUFFICIENT,
)
from middleware import authenticate, require_roles, check_customer_owns_order
from response import success_object, success_list
from services.common import (
    new_id, get_body, require, optional, MISSING, check_enum, check_iso_date,
    get_customer, get_model, get_jurisdiction, get_order, paginate,
    latest_permit_app_for_order,
)
from services.pricing import (
    compute_area_sqft, compute_order_pricing, compute_required_deposit_cents,
    round_half_up_cents, ADMIN_FEE_CENTS, RESTOCK_BP,
)
from decimal import Decimal
from services.cascade import (
    bump, create_permit_application, advance_order_to_ready, create_rto_contract,
    maybe_close_order,
)

bp = Blueprint("orders", __name__)

READ_ROLES = ("Customer", "SalesRep", "PermitCoordinator", "InstallCrew",
              "FinanceManager", "OperationsAdmin")

ALL_ROLES = READ_ROLES


def _validate_option_list(options):
    for o in options:
        check_enum(o, {"WINDOW", "LOFT", "RAMP", "ELECTRICAL"}, "options")


def _apply_config_rules(order_fields: dict, model: dict, jurisdiction: dict):
    """PRD §3.2 pinned order: anchoring -> dimension bounds -> delivery mode."""
    if jurisdiction["anchoring_required"] and order_fields["anchor_type"] == "NONE":
        raise ApiError(ERR_ANCHOR_REQUIRED,
                       "anchor_type NONE while jurisdiction.anchoring_required is true", 422)
    w, d = order_fields["width_ft"], order_fields["depth_ft"]
    if not (model["min_width_ft"] <= w <= model["max_width_ft"]
            and model["min_depth_ft"] <= d <= model["max_depth_ft"]):
        raise ApiError(ERR_CONFIG_OUT_OF_BOUNDS,
                       "width_ft/depth_ft outside model min/max bounds", 422)
    if order_fields["delivery_mode"] not in model["supported_delivery_modes"]:
        raise ApiError(ERR_DELIVERY_MODE_UNSUPPORTED,
                       "delivery_mode not in model.supported_delivery_modes", 422)


def _recompute_pricing(order: dict):
    model = db.models[order["model_id"]]
    jurisdiction = db.jurisdictions[order["jurisdiction_id"]]
    order["area_sqft"] = compute_area_sqft(order["width_ft"], order["depth_ft"])
    priced = compute_order_pricing(order, model, jurisdiction)
    order["structure_price_cents"] = priced["structure_price_cents"]
    return priced


@bp.post("/api/orders")
def create_order():
    authenticate()
    require_roles("SalesRep")
    body = get_body()

    # --- Request shape (priority 3) ---
    customer_id = require(body, "customer_id", "str")
    model_id = require(body, "model_id", "str")
    jurisdiction_id = require(body, "jurisdiction_id", "str")
    width_ft = require(body, "width_ft", "num")
    depth_ft = require(body, "depth_ft", "num")
    delivery_mode = require(body, "delivery_mode", "str")
    check_enum(delivery_mode, {"PRE_BUILT", "ON_SITE_BUILD"}, "delivery_mode")
    foundation_type = require(body, "foundation_type", "str")
    check_enum(foundation_type, {"GRAVEL_PAD", "CONCRETE_SLAB", "PIERS", "NONE"}, "foundation_type")
    anchor_type = require(body, "anchor_type", "str")
    check_enum(anchor_type, {"AUGER_STRAP", "NONE"}, "anchor_type")
    purchase_type = require(body, "purchase_type", "str")
    check_enum(purchase_type, {"CASH", "RTO"}, "purchase_type")
    options = optional(body, "options", "array", default=[])
    _validate_option_list(options)
    rto_term_months = optional(body, "rto_term_months", "int", default=None, allow_none=True)
    if purchase_type == "RTO":
        if rto_term_months is None:
            raise invalid_request("rto_term_months is required when purchase_type == RTO")
        if not (12 <= rto_term_months <= 60):
            raise invalid_request("rto_term_months must be between 12 and 60")
    removal_requested = optional(body, "removal_requested", "bool", default=False)
    old_structure_area_sqft = optional(body, "old_structure_area_sqft", "num",
                                       default=None, allow_none=True)
    if removal_requested and old_structure_area_sqft is None:
        raise invalid_request("old_structure_area_sqft is required when removal_requested")
    trade_in_appraised_cents = optional(body, "trade_in_appraised_cents", "int",
                                        default=None, allow_none=True)

    # --- Existence (priority 4): body FK references ---
    get_customer(customer_id)
    model = get_model(model_id)
    jurisdiction = get_jurisdiction(jurisdiction_id)

    fields = {
        "width_ft": width_ft, "depth_ft": depth_ft, "delivery_mode": delivery_mode,
        "anchor_type": anchor_type,
    }
    # --- Business rules in pinned order (anchor -> bounds -> delivery mode) ---
    _apply_config_rules(fields, model, jurisdiction)

    now = db.now_iso()
    order = {
        "id": new_id(),
        "customer_id": customer_id,
        "model_id": model_id,
        "jurisdiction_id": jurisdiction_id,
        "width_ft": width_ft,
        "depth_ft": depth_ft,
        "area_sqft": 0,
        "options": list(options),
        "delivery_mode": delivery_mode,
        "foundation_type": foundation_type,
        "anchor_type": anchor_type,
        "purchase_type": purchase_type,
        "rto_term_months": rto_term_months,
        "removal_requested": removal_requested,
        "old_structure_area_sqft": old_structure_area_sqft,
        "trade_in_appraised_cents": trade_in_appraised_cents,
        "site_prep_required": False,
        "site_prep_fee_cents": 0,
        "structure_price_cents": 0,
        "quoted_total_cents": 0,
        "final_total_cents": None,
        "collected_cents": 0,
        "refunded_cents": 0,
        "retained_cents": 0,
        "status": "DRAFT",
        "scheduled_date": None,
        "crew_id": None,
        "completed_at": None,
        "warranty_ends_at": None,
        "structure_state": "NOT_INSTALLED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    priced = _recompute_pricing(order)
    order["quoted_total_cents"] = priced["total_cents"]
    db.orders[order["id"]] = order
    return success_object(order, 201)


@bp.get("/api/orders")
def list_orders():
    authenticate()
    require_roles(*READ_ROLES)
    customer_id = request.args.get("customer_id")
    model_id = request.args.get("model_id")
    jurisdiction_id = request.args.get("jurisdiction_id")
    status = request.args.get("status")

    rows = list(db.orders.values())
    if customer_id is not None:
        rows = [o for o in rows if o["customer_id"] == customer_id]
    if model_id is not None:
        rows = [o for o in rows if o["model_id"] == model_id]
    if jurisdiction_id is not None:
        rows = [o for o in rows if o["jurisdiction_id"] == jurisdiction_id]
    if status is not None:
        rows = [o for o in rows if o["status"] == status]
    if g.role == "Customer":
        rows = [o for o in rows if o["customer_id"] == g.user_id]
    rows.sort(key=lambda o: o["created_at"])
    limit, offset = paginate(request.args, rows)
    return success_list(rows[offset:offset + limit], limit, offset, len(rows))


@bp.get("/api/orders/<oid>")
def read_order(oid):
    authenticate()
    require_roles(*READ_ROLES)
    order = get_order(oid)
    check_customer_owns_order(order)
    return success_object(order)


@bp.put("/api/orders/<oid>")
def amend_order(oid):
    authenticate()
    require_roles("SalesRep")
    body = get_body()

    # Request shape
    expected = require(body, "expected_order_version", "int")
    width_ft = optional(body, "width_ft", "num", default=MISSING)
    depth_ft = optional(body, "depth_ft", "num", default=MISSING)
    options = optional(body, "options", "array", default=MISSING)
    if options is not MISSING:
        _validate_option_list(options)
    delivery_mode = optional(body, "delivery_mode", "str", default=MISSING)
    if delivery_mode is not MISSING:
        check_enum(delivery_mode, {"PRE_BUILT", "ON_SITE_BUILD"}, "delivery_mode")
    foundation_type = optional(body, "foundation_type", "str", default=MISSING)
    if foundation_type is not MISSING:
        check_enum(foundation_type, {"GRAVEL_PAD", "CONCRETE_SLAB", "PIERS", "NONE"},
                   "foundation_type")
    anchor_type = optional(body, "anchor_type", "str", default=MISSING)
    if anchor_type is not MISSING:
        check_enum(anchor_type, {"AUGER_STRAP", "NONE"}, "anchor_type")
    rto_term_months = optional(body, "rto_term_months", "int", default=MISSING)
    removal_requested = optional(body, "removal_requested", "bool", default=MISSING)
    old_structure_area_sqft = optional(body, "old_structure_area_sqft", "num", default=MISSING)
    trade_in_appraised_cents = optional(body, "trade_in_appraised_cents", "int", default=MISSING)

    # Existence
    order = get_order(oid)

    # OCC guard (§2.7)
    if expected != order["version"]:
        raise ApiError(ERR_STALE_VERSION,
                       "expected_order_version does not match current version", 412)

    # State: amend only in DRAFT
    if order["status"] != "DRAFT":
        raise invalid_state("Amendment is only allowed while the order is in DRAFT")

    # Apply changes to a candidate view
    candidate = dict(order)
    if width_ft is not MISSING:
        candidate["width_ft"] = width_ft
    if depth_ft is not MISSING:
        candidate["depth_ft"] = depth_ft
    if options is not MISSING:
        candidate["options"] = list(options)
    if delivery_mode is not MISSING:
        candidate["delivery_mode"] = delivery_mode
    if foundation_type is not MISSING:
        candidate["foundation_type"] = foundation_type
    if anchor_type is not MISSING:
        candidate["anchor_type"] = anchor_type
    if rto_term_months is not MISSING:
        candidate["rto_term_months"] = rto_term_months
    if removal_requested is not MISSING:
        candidate["removal_requested"] = removal_requested
    if old_structure_area_sqft is not MISSING:
        candidate["old_structure_area_sqft"] = old_structure_area_sqft
    if trade_in_appraised_cents is not MISSING:
        candidate["trade_in_appraised_cents"] = trade_in_appraised_cents

    # Conditional requirements against the merged configuration
    if candidate["purchase_type"] == "RTO":
        rtm = candidate.get("rto_term_months")
        if rtm is None:
            raise invalid_request("rto_term_months is required when purchase_type == RTO")
        if not (12 <= rtm <= 60):
            raise invalid_request("rto_term_months must be between 12 and 60")
    if candidate["removal_requested"] and candidate.get("old_structure_area_sqft") is None:
        raise invalid_request("old_structure_area_sqft is required when removal_requested")

    model = db.models[order["model_id"]]
    jurisdiction = db.jurisdictions[order["jurisdiction_id"]]
    _apply_config_rules(candidate, model, jurisdiction)

    # Commit
    for k in ("width_ft", "depth_ft", "options", "delivery_mode", "foundation_type",
              "anchor_type", "rto_term_months", "removal_requested",
              "old_structure_area_sqft", "trade_in_appraised_cents"):
        order[k] = candidate[k]
    priced = _recompute_pricing(order)
    order["quoted_total_cents"] = priced["total_cents"]
    bump(order)
    return success_object(order)


@bp.post("/api/orders/<oid>/submit-site-check")
def submit_site_check(oid):
    authenticate()
    require_roles("SalesRep")
    body = get_body()
    assessor_id = require(body, "assessor_id", "str")
    scheduled_date = require(body, "scheduled_date", "str")
    check_iso_date(scheduled_date, "scheduled_date")
    window_start_hour = require(body, "window_start_hour", "int")
    if not (6 <= window_start_hour <= 20):
        raise invalid_request("window_start_hour must be between 6 and 20")

    order = get_order(oid)
    if order["status"] != "DRAFT":
        raise invalid_state("Site check can only be submitted from DRAFT")

    # Business checks, PRD §3.3 order: assessor window conflict first, then date
    new_start, new_end = window_start_hour, window_start_hour + 2
    for a in db.site_assessments.values():
        if (a["assessor_id"] == assessor_id and a["scheduled_date"] == scheduled_date
                and a["status"] == "REQUESTED"):
            a_start, a_end = a["window_start_hour"], a["window_start_hour"] + 2
            if new_start < a_end and a_start < new_end:
                raise ApiError(ERR_ASSESSOR_WINDOW_CONFLICT,
                               "Overlapping half-open 2h assessor window for same assessor and date",
                               409)
    current_date = db.get_clock()[0:10]
    if scheduled_date < current_date:
        raise ApiError(ERR_DATE_IN_PAST, "scheduled_date before current logical date", 422)

    now = db.now_iso()
    assessment = {
        "id": new_id(),
        "order_id": order["id"],
        "assessor_id": assessor_id,
        "scheduled_date": scheduled_date,
        "window_start_hour": window_start_hour,
        "status": "REQUESTED",
        "measured_access_width_in": None,
        "measured_slope_pct": None,
        "setback_front_ft": None,
        "setback_side_ft": None,
        "setback_rear_ft": None,
        "ground_prep_needed": None,
        "prep_cost_cents": None,
        "verdict": None,
        "reported_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.site_assessments[assessment["id"]] = assessment

    order["status"] = "SITE_REVIEW"
    bump(order)
    return success_object(assessment, 201)


def _crew_conflict(crew_id: str, scheduled_date: str) -> bool:
    """Whole-day occupancy shared across orders (SCHEDULED/IN_PROGRESS) and
    service tickets (SCHEDULED)."""
    for o in db.orders.values():
        if (o.get("crew_id") == crew_id and o.get("scheduled_date") == scheduled_date
                and o["status"] in ("SCHEDULED", "IN_PROGRESS")):
            return True
    for t in db.service_tickets.values():
        if (t.get("crew_id") == crew_id and t.get("scheduled_date") == scheduled_date
                and t["status"] == "SCHEDULED"):
            return True
    return False


@bp.post("/api/orders/<oid>/schedule")
def schedule_order(oid):
    authenticate()
    require_roles("SalesRep")
    body = get_body()
    scheduled_date = require(body, "scheduled_date", "str")
    check_iso_date(scheduled_date, "scheduled_date")
    crew_id = require(body, "crew_id", "str")

    order = get_order(oid)
    if order["status"] != "READY_TO_SCHEDULE":
        raise invalid_state("Order must be READY_TO_SCHEDULE to be scheduled")

    # PRD §3.5 order: crew occupancy, then calendar, then money
    if _crew_conflict(crew_id, scheduled_date):
        raise ApiError(ERR_CREW_DATE_CONFLICT,
                       "Crew already occupies the requested whole calendar date", 409)
    current_date = db.get_clock()[0:10]
    if scheduled_date < current_date:
        raise ApiError(ERR_DATE_IN_PAST, "scheduled_date before current logical date", 422)
    if order["purchase_type"] == "CASH":
        required = compute_required_deposit_cents(order["quoted_total_cents"])
        if order["collected_cents"] < required:
            raise ApiError(ERR_DEPOSIT_INSUFFICIENT,
                           "CASH order scheduling without collected_cents >= 20% of quoted_total_cents",
                           402)

    order["scheduled_date"] = scheduled_date
    order["crew_id"] = crew_id
    order["status"] = "SCHEDULED"
    bump(order)
    return success_object(order)


@bp.post("/api/orders/<oid>/start")
def start_order(oid):
    authenticate()
    require_roles("InstallCrew")
    get_body()
    order = get_order(oid)
    if order["status"] != "SCHEDULED":
        raise invalid_state("Order must be SCHEDULED to start")
    current_date = db.get_clock()[0:10]
    if current_date < order["scheduled_date"]:
        raise invalid_state("Cannot start before the order's scheduled_date")
    order["status"] = "IN_PROGRESS"
    bump(order)
    return success_object(order)


@bp.post("/api/orders/<oid>/complete")
def complete_order(oid):
    authenticate()
    require_roles("InstallCrew")
    get_body()
    order = get_order(oid)
    if order["status"] != "IN_PROGRESS":
        raise invalid_state("Order must be IN_PROGRESS to complete")

    now = db.now_iso()
    order["completed_at"] = now
    completed_dt = db.parse_iso(now)
    try:
        warranty_dt = completed_dt.replace(year=completed_dt.year + 1)
    except ValueError:  # Feb 29 -> Feb 28
        warranty_dt = completed_dt.replace(year=completed_dt.year + 1, day=28)
    order["warranty_ends_at"] = db.format_iso(warranty_dt)
    order["final_total_cents"] = _recompute_pricing(order)["total_cents"]
    order["structure_state"] = "INSTALLED"
    order["status"] = "COMPLETED"
    bump(order)

    if order["purchase_type"] == "RTO":
        create_rto_contract(order)
    maybe_close_order(order)
    return success_object(order)


@bp.post("/api/orders/<oid>/cancel")
def cancel_order(oid):
    authenticate()
    require_roles("SalesRep", "Customer")
    body = get_body()
    optional(body, "reason", "str", default=None, allow_none=True)

    order = get_order(oid)
    check_customer_owns_order(order)

    if order["status"] not in ("DRAFT", "SITE_REVIEW", "PERMIT_REVIEW",
                               "READY_TO_SCHEDULE", "SCHEDULED"):
        raise invalid_state("Order cannot be cancelled from its current state")

    # Refund waterfall (PRD §3.6)
    collected = order["collected_cents"]
    bucket1 = ADMIN_FEE_CENTS
    bucket2 = 0
    latest_app = latest_permit_app_for_order(order["id"])
    if (latest_app is not None and latest_app["status"] in ("SUBMITTED", "APPROVED")
            and order["status"] in ("PERMIT_REVIEW", "READY_TO_SCHEDULE", "SCHEDULED")):
        bucket2 = latest_app["fee_cents"]
    bucket3 = 0
    if order["status"] in ("READY_TO_SCHEDULE", "SCHEDULED"):
        bucket3 = round_half_up_cents(Decimal(order["structure_price_cents"])
                                      * Decimal(RESTOCK_BP) / Decimal(10000))
    retained = min(collected, bucket1 + bucket2 + bucket3)
    refund = collected - retained

    order["retained_cents"] = retained
    order["status"] = "CANCELLED"

    # Conditional cascades
    # REQUESTED assessments -> CANCELLED (REPORTED untouched)
    for a in db.site_assessments.values():
        if a["order_id"] == order["id"] and a["status"] == "REQUESTED":
            a["status"] = "CANCELLED"
            bump(a)
    # SUBMITTED permit applications -> WITHDRAWN
    for p in db.permit_applications.values():
        if p["order_id"] == order["id"] and p["status"] == "SUBMITTED":
            p["status"] = "WITHDRAWN"
            bump(p)

    # Cancelling a SCHEDULED order frees the crew day
    if order["scheduled_date"] is not None:
        order["crew_id"] = None
        order["scheduled_date"] = None

    # Record the refund
    if refund > 0:
        now = db.now_iso()
        payment = {
            "id": new_id(),
            "order_id": order["id"],
            "rto_contract_id": None,
            "kind": "REFUND",
            "amount_cents": refund,
            "method": None,
            "idempotency_key": None,
            "applied_to_late_fees_cents": 0,
            "applied_to_principal_cents": 0,
            "recorded_by": g.user_id,
            "created_at": now,
        }
        db.payments[payment["id"]] = payment
        order["refunded_cents"] = sum(
            p["amount_cents"] for p in db.payments.values()
            if p["order_id"] == order["id"] and p["kind"] == "REFUND")

    bump(order)
    return success_object(order)
