"""Work order endpoints: create/list/get/amend, prepare, predip, route,
load-run start, inspections, strips, ship, cancel, child listings."""
from decimal import Decimal

from flask import Blueprint, request

from db import store, get_clock, format_ts
from errors import (
    ERR_ALLOY_BATH_INCOMPATIBLE,
    ERR_BATH_CAPACITY_EXCEEDED,
    ERR_BATH_CONCENTRATION_OUT_OF_BAND,
    ERR_BATH_LIFE_INSUFFICIENT,
    ERR_BATH_NOT_ACTIVE,
    ERR_BATH_OCCUPIED,
    ERR_CUSTOMER_CREDIT_HOLD,
    ERR_CUSTOMER_SUSPENDED,
    ERR_DOSE_VERIFICATION_PENDING,
    ERR_FIXTURE_CAPACITY_INSUFFICIENT,
    ERR_FIXTURE_OCCUPIED,
    ERR_FIXTURE_ROUTING_MODE_MISMATCH,
    ERR_INVALID_REQUEST,
    ERR_MASKING_MINUTES_REQUIRED,
    ERR_NOT_FOUND,
    ERR_PREDIP_REQUIRED,
    ERR_PROCESS_TYPE_MISMATCH,
    ERR_RESOURCE_NOT_OWNED,
    ERR_ROUTING_MODE_NOT_SUPPORTED,
    ERR_STALE_VERSION,
    ERR_WORK_ORDER_NOT_AWAITING_INSPECTION,
    ERR_WORK_ORDER_NOT_CANCELLABLE,
    ERR_WORK_ORDER_NOT_COMPLETE,
    ERR_WORK_ORDER_NOT_RECEIVED,
    ERR_WORK_ORDER_NOT_REJECTED,
    ERR_WORK_ORDER_NOT_ROUTABLE,
    ERR_WORK_ORDER_NOT_ROUTED,
    ERR_WORK_ORDER_NOT_STRIPPING,
    raise_err,
)
from helpers import (
    body_json,
    check_boolean,
    check_enum,
    check_integer,
    check_number,
    check_string,
    get_or_404,
    is_int,
    is_number,
    paginate,
    parse_pagination,
    stamp_event,
    stamp_new,
    touch,
)
from middleware import require_roles, check_customer_owns, STAFF_ROLES
from response import success_list, success_object
from serializers import (
    inspection_view,
    load_run_view,
    salt_spray_lot_view,
    work_order_view,
)
from services import chemistry, pricing
from services.cascades import cascade_bath_exhausted

bp = Blueprint("work_orders", __name__)

PROCESS_TYPES = {"ANODIZE", "PLATE"}
ROUTING_MODES = {"RACK", "BARREL"}
DEFECT_TYPES = {"NONE", "BURN", "STAIN", "PITTING", "ADHESION", "UNDERTHICKNESS"}
MAX_REWORKS = 2

EARLY_CANCEL_STATES = {"RECEIVED", "READY_FOR_ROUTING", "ROUTED", "ROUTE_HELD"}
LATE_CANCEL_STATES = {"AWAITING_INSPECTION", "REJECTED", "STRIPPING", "AWAITING_LOT_TEST"}

WO_READ_ROLES = {"Customer", "LineOperator", "LabChemist", "QCInspector", "EHSOfficer", "ShopManager"}


def _surface_total(part_count, area_per_part):
    return Decimal(str(part_count)) * Decimal(str(area_per_part))


# ---------------------------------------------------------------------------
# Create / list / get / amend
# ---------------------------------------------------------------------------

@bp.route("/work-orders", methods=["POST"])
def create_work_order():
    user_id, role = require_roles({"Customer", "ShopManager"})
    data = body_json()
    customer_id = data.get("customer_id")
    if customer_id is None or not isinstance(customer_id, str):
        raise_err(ERR_INVALID_REQUEST, "customer_id is required")
    # Tier 3: ownership scoping on creation body
    if role == "Customer" and customer_id != user_id:
        raise_err(ERR_RESOURCE_NOT_OWNED, "Customer may only create work orders for itself")
    # Tier 4: FK existence
    customer = store.customers.get(customer_id)
    if customer is None:
        raise_err(ERR_NOT_FOUND, "customer not found")

    # Tier 5: schema
    part_number = check_string(data, "part_number", required=True)
    alloy_code = check_string(data, "alloy_code", required=True)
    process_type = check_enum(data, "process_type", PROCESS_TYPES, required=True)
    routing_mode = check_enum(data, "routing_mode", ROUTING_MODES, required=True)
    part_count = check_integer(data, "part_count", required=True, gte=1)
    area_per_part = check_number(data, "surface_area_dm2_per_part", required=True, gt=0)
    spec_min = check_number(data, "thickness_spec_min_um", required=True, gt=0)
    spec_max = check_number(data, "thickness_spec_max_um", required=True)
    if Decimal(str(spec_max)) < Decimal(str(spec_min)):
        raise_err(ERR_INVALID_REQUEST, "thickness_spec_max_um must be >= thickness_spec_min_um")
    requires_masking = check_boolean(data, "requires_masking", required=False, default=False)
    requires_salt_spray = check_boolean(data, "requires_salt_spray", required=False, default=False)

    # Tier 11: fiscal gates at creation
    if customer["credit_hold"]:
        raise_err(ERR_CUSTOMER_CREDIT_HOLD, "customer is on credit hold")
    if customer["status"] != "ACTIVE":
        raise_err(ERR_CUSTOMER_SUSPENDED, "customer is suspended")

    wo = stamp_new({
        "customer_id": customer_id,
        "part_number": part_number,
        "alloy_code": alloy_code,
        "process_type": process_type,
        "routing_mode": routing_mode,
        "part_count": part_count,
        "surface_area_dm2_per_part": area_per_part,
        "surface_area_total_dm2": _surface_total(part_count, area_per_part),
        "thickness_spec_min_um": spec_min,
        "thickness_spec_max_um": spec_max,
        "requires_masking": requires_masking,
        "masking_minutes_actual": None,
        "requires_salt_spray": requires_salt_spray,
        "predip_completed": False,
        "bath_id": None,
        "fixture_id": None,
        "routed_chemistry_family": None,
        "rework_count": 0,
        "pending_strip": False,
        "last_defect_type": None,
        "provisional_quote_cents": None,
        "final_invoice_cents": None,
        "completed_load_count": 0,
        "cancellation_fee_cents": None,
        "status": "RECEIVED",
    })
    wo["provisional_quote_cents"] = pricing.compute_price(wo, "provisional")
    store.work_orders[wo["id"]] = wo
    return success_object(work_order_view(wo), status=201)


@bp.route("/work-orders", methods=["GET"])
def list_work_orders():
    user_id, role = require_roles(WO_READ_ROLES)
    limit, offset = parse_pagination()
    items = sorted(store.work_orders.values(), key=lambda w: (w["created_at"], w["id"]))
    if role == "Customer":
        items = [w for w in items if w["customer_id"] == user_id]
    customer_id = request.args.get("customer_id")
    bath_id = request.args.get("bath_id")
    fixture_id = request.args.get("fixture_id")
    status = request.args.get("status")
    if customer_id is not None:
        items = [w for w in items if w["customer_id"] == customer_id]
    if bath_id is not None:
        items = [w for w in items if w.get("bath_id") == bath_id]
    if fixture_id is not None:
        items = [w for w in items if w.get("fixture_id") == fixture_id]
    if status is not None:
        items = [w for w in items if w["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([work_order_view(w) for w in page], limit, offset, total)


@bp.route("/work-orders/<wo_id>", methods=["GET"])
def get_work_order(wo_id):
    user_id, role = require_roles(WO_READ_ROLES)
    wo = store.work_orders.get(wo_id)
    if wo is None:
        raise_err(ERR_NOT_FOUND, "work order not found")
    check_customer_owns(role, user_id, wo["customer_id"])
    return success_object(work_order_view(wo))


@bp.route("/work-orders/<wo_id>", methods=["PATCH"])
def amend_work_order(wo_id):
    user_id, role = require_roles({"Customer", "ShopManager"})
    # Tier 4: existence (ownership tier 3 needs the resource to compare ids)
    wo = store.work_orders.get(wo_id)
    if wo is None:
        raise_err(ERR_NOT_FOUND, "work order not found")
    # Tier 3: ownership scoping
    check_customer_owns(role, user_id, wo["customer_id"])

    # Tier 5: schema
    data = body_json()
    expected_version = data.get("expected_work_order_version")
    if expected_version is None or not is_int(expected_version):
        raise_err(ERR_INVALID_REQUEST, "expected_work_order_version is required and must be an integer")
    new_part_count = wo["part_count"]
    new_area_per_part = wo["surface_area_dm2_per_part"]
    new_spec_min = wo["thickness_spec_min_um"]
    new_spec_max = wo["thickness_spec_max_um"]
    new_requires_masking = wo["requires_masking"]
    new_requires_salt_spray = wo["requires_salt_spray"]
    if "part_count" in data:
        new_part_count = check_integer(data, "part_count", required=True, gte=1)
    if "surface_area_dm2_per_part" in data:
        new_area_per_part = check_number(data, "surface_area_dm2_per_part", required=True, gt=0)
    if "thickness_spec_min_um" in data:
        new_spec_min = check_number(data, "thickness_spec_min_um", required=True, gt=0)
    if "thickness_spec_max_um" in data:
        new_spec_max = check_number(data, "thickness_spec_max_um", required=True)
    if "requires_masking" in data:
        new_requires_masking = check_boolean(data, "requires_masking", required=True)
    if "requires_salt_spray" in data:
        new_requires_salt_spray = check_boolean(data, "requires_salt_spray", required=True)
    if Decimal(str(new_spec_max)) < Decimal(str(new_spec_min)):
        raise_err(ERR_INVALID_REQUEST, "thickness_spec_max_um must be >= thickness_spec_min_um")

    # Tier 6: OCC
    if expected_version != wo["version"]:
        raise_err(ERR_STALE_VERSION, "expected_work_order_version does not match the work order's current version")

    # Tier 7: only RECEIVED orders may be amended
    if wo["status"] != "RECEIVED":
        raise_err(ERR_WORK_ORDER_NOT_RECEIVED, "amendment requires status RECEIVED")

    wo["part_count"] = new_part_count
    wo["surface_area_dm2_per_part"] = new_area_per_part
    wo["surface_area_total_dm2"] = _surface_total(new_part_count, new_area_per_part)
    wo["thickness_spec_min_um"] = new_spec_min
    wo["thickness_spec_max_um"] = new_spec_max
    wo["requires_masking"] = new_requires_masking
    wo["requires_salt_spray"] = new_requires_salt_spray
    wo["provisional_quote_cents"] = pricing.compute_price(wo, "provisional")
    touch(wo)
    return success_object(work_order_view(wo))


@bp.route("/work-orders/<wo_id>/prepare", methods=["POST"])
def prepare_work_order(wo_id):
    user_id, role = require_roles({"LineOperator", "ShopManager"})
    wo = get_or_404(store.work_orders, wo_id)
    data = body_json()
    masking_minutes = data.get("masking_minutes")

    # Tier 7: state
    if wo["status"] != "RECEIVED":
        raise_err(ERR_WORK_ORDER_NOT_RECEIVED, "prepare requires status RECEIVED")
    # Masking rule: required iff requires_masking; must be absent otherwise
    if wo["requires_masking"]:
        if masking_minutes is None:
            raise_err(ERR_MASKING_MINUTES_REQUIRED, "masking_minutes is required when requires_masking is true")
        if not is_int(masking_minutes) or masking_minutes < 0:
            raise_err(ERR_INVALID_REQUEST, "masking_minutes must be a non-negative integer")
    else:
        if masking_minutes is not None:
            raise_err(ERR_MASKING_MINUTES_REQUIRED, "masking_minutes must be absent when requires_masking is false")

    wo["masking_minutes_actual"] = masking_minutes if wo["requires_masking"] else 0
    wo["status"] = "READY_FOR_ROUTING"
    wo["provisional_quote_cents"] = pricing.compute_price(wo, "provisional")
    touch(wo)
    return success_object(work_order_view(wo))


@bp.route("/work-orders/<wo_id>/complete-predip", methods=["POST"])
def complete_predip(wo_id):
    user_id, role = require_roles({"LineOperator", "ShopManager"})
    wo = get_or_404(store.work_orders, wo_id)
    wo["predip_completed"] = True
    touch(wo)
    return success_object(work_order_view(wo))


@bp.route("/work-orders/<wo_id>/route", methods=["POST"])
def route_work_order(wo_id):
    user_id, role = require_roles({"LineOperator", "ShopManager"})
    # Tier 4: path existence, then body FKs (bath_id, fixture_id)
    wo = get_or_404(store.work_orders, wo_id)
    data = body_json()
    bath_id = data.get("bath_id")
    fixture_id = data.get("fixture_id")
    planned_duration = data.get("planned_duration_minutes")
    planned_density = data.get("planned_current_density_a_dm2")

    # Tier 5 schema basics for required fields before FK resolution? No —
    # tier 4 (existence incl. body FKs) precedes tier 5 (schema). bath_id must
    # be present to resolve; treat missing as schema error only after existence
    # of provided ids. PRD pins existence of FK references in the body at tier 4.
    bath = None
    if bath_id is not None:
        if not isinstance(bath_id, str):
            raise_err(ERR_INVALID_REQUEST, "bath_id must be a string")
        bath = store.baths.get(bath_id)
        if bath is None:
            raise_err(ERR_NOT_FOUND, "bath not found")
    fixture = None
    if fixture_id is not None:
        if not isinstance(fixture_id, str):
            raise_err(ERR_INVALID_REQUEST, "fixture_id must be a string")
        fixture = store.fixtures.get(fixture_id)
        if fixture is None:
            raise_err(ERR_NOT_FOUND, "fixture not found")

    # Tier 5: schema
    if bath is None:
        raise_err(ERR_INVALID_REQUEST, "bath_id is required")
    if planned_duration is None or not is_int(planned_duration) or planned_duration < 1:
        raise_err(ERR_INVALID_REQUEST, "planned_duration_minutes must be an integer >= 1")
    if planned_density is None or not is_number(planned_density) or not (planned_density > 0):
        raise_err(ERR_INVALID_REQUEST, "planned_current_density_a_dm2 must be a number > 0")

    # Tier 7: work order state first, then bath state
    if wo["status"] not in ("READY_FOR_ROUTING", "ROUTE_HELD"):
        raise_err(ERR_WORK_ORDER_NOT_ROUTABLE, "route requires status READY_FOR_ROUTING or ROUTE_HELD")
    if bath["status"] != "ACTIVE":
        raise_err(ERR_BATH_NOT_ACTIVE, "bath must be ACTIVE")

    # Tier 8: chemistry/alloy safety
    rule = _find_compat_rule(wo["alloy_code"], wo["process_type"], bath["chemistry_family"])
    if rule is None or rule["compatibility"] == "INCOMPATIBLE":
        raise_err(ERR_ALLOY_BATH_INCOMPATIBLE, "alloy is incompatible with this bath chemistry")
    if bath["current_concentration_g_l"] is None:
        raise_err(ERR_BATH_CONCENTRATION_OUT_OF_BAND, "bath has not been titrated")

    # Tier 10: structural constraints
    if bath["process_type"] != wo["process_type"]:
        raise_err(ERR_PROCESS_TYPE_MISMATCH, "bath process_type differs from work order process_type")
    if wo["routing_mode"] not in bath["routing_modes_supported"]:
        raise_err(ERR_ROUTING_MODE_NOT_SUPPORTED, "routing mode not supported by bath")
    if wo["routing_mode"] == "RACK":
        if fixture is None:
            raise_err(ERR_FIXTURE_ROUTING_MODE_MISMATCH, "RACK routing requires a fixture_id")
        if fixture["routing_mode"] != "RACK":
            raise_err(ERR_FIXTURE_ROUTING_MODE_MISMATCH, "fixture routing_mode must be RACK")
        if Decimal(str(fixture["capacity_dm2"])) < Decimal(str(wo["surface_area_total_dm2"])):
            raise_err(ERR_FIXTURE_CAPACITY_INSUFFICIENT, "fixture capacity is insufficient")
    else:  # BARREL
        if fixture is not None:
            raise_err(ERR_FIXTURE_ROUTING_MODE_MISMATCH, "fixture_id must be null for BARREL routing")

    # Tier 11: fiscal gates — bath life sufficiency, then customer gates
    estimate = chemistry.estimate_amp_hours(
        wo["surface_area_total_dm2"], planned_density, planned_duration
    )
    effective = chemistry.effective_remaining_ah(bath)
    if effective is None or Decimal(effective) < estimate:
        raise_err(ERR_BATH_LIFE_INSUFFICIENT, "effective remaining bath life is insufficient")
    customer = store.customers.get(wo["customer_id"])
    if customer is not None:
        if customer["credit_hold"]:
            raise_err(ERR_CUSTOMER_CREDIT_HOLD, "customer is on credit hold")
        if customer["status"] != "ACTIVE":
            raise_err(ERR_CUSTOMER_SUSPENDED, "customer is suspended")

    wo["bath_id"] = bath["id"]
    wo["fixture_id"] = fixture["id"] if fixture else None
    wo["routed_chemistry_family"] = bath["chemistry_family"]
    wo["status"] = "ROUTED"
    touch(wo)
    return success_object(work_order_view(wo))


@bp.route("/work-orders/<wo_id>/load-runs", methods=["POST"])
def start_load_run(wo_id):
    user_id, role = require_roles({"LineOperator", "ShopManager"})
    wo = get_or_404(store.work_orders, wo_id)
    data = body_json()
    duration_minutes = data.get("duration_minutes")
    current_density = data.get("current_density_a_dm2")
    expected_bath_version = data.get("expected_bath_version")

    # Tier 5: schema (before OCC per pinned tiers)
    if duration_minutes is None or not is_int(duration_minutes) or duration_minutes < 1:
        raise_err(ERR_INVALID_REQUEST, "duration_minutes must be an integer >= 1")
    if current_density is None or not is_number(current_density) or not (current_density > 0):
        raise_err(ERR_INVALID_REQUEST, "current_density_a_dm2 must be a number > 0")
    if expected_bath_version is None or not is_int(expected_bath_version):
        raise_err(ERR_INVALID_REQUEST, "expected_bath_version is required and must be an integer")

    bath = store.baths.get(wo.get("bath_id")) if wo.get("bath_id") else None

    # Tier 6: OCC on the routed bath's version — before state checks
    if bath is None:
        # Unrouted order: the state check below reports it; OCC has no parent.
        pass
    else:
        if expected_bath_version != bath["version"]:
            raise_err(ERR_STALE_VERSION, "expected_bath_version does not match the bath's current version")

    # Tier 7: work order state first, then bath state
    if wo["status"] != "ROUTED":
        raise_err(ERR_WORK_ORDER_NOT_ROUTED, "load start requires status ROUTED")
    if bath is None:
        raise_err(ERR_WORK_ORDER_NOT_ROUTED, "work order is not routed to a bath")
    if bath["status"] != "ACTIVE":
        raise_err(ERR_BATH_NOT_ACTIVE, "bath must be ACTIVE")
    if bath["active_load_run_id"] is not None:
        raise_err(ERR_BATH_OCCUPIED, "bath already has a RUNNING load run")

    # Tier 8: safety
    if bath["dose_verification_pending"]:
        raise_err(ERR_DOSE_VERIFICATION_PENDING, "a dose is awaiting verification by titration")
    if not chemistry.concentration_in_band(bath):
        raise_err(ERR_BATH_CONCENTRATION_OUT_OF_BAND, "current concentration is outside the control band")
    rule = _find_compat_rule(wo["alloy_code"], wo["process_type"], bath["chemistry_family"])
    if rule is not None and rule["compatibility"] == "CONDITIONAL" and not wo["predip_completed"]:
        raise_err(ERR_PREDIP_REQUIRED, "predip is required for CONDITIONAL compatibility")

    # Tier 9: temporal — fixture occupation (half-open intervals)
    if wo["routing_mode"] == "RACK" and wo.get("fixture_id"):
        for r in store.load_runs.values():
            if r["status"] == "RUNNING" and r.get("fixture_id") == wo["fixture_id"]:
                raise_err(ERR_FIXTURE_OCCUPIED, "fixture is occupied by another RUNNING load")

    # Tier 11: nameplate capacity + customer gates
    estimate = chemistry.estimate_amp_hours(wo["surface_area_total_dm2"], current_density, duration_minutes)
    used = Decimal(str(bath["amp_hour_used"]))
    reserved = Decimal(str(bath["amp_hour_reserved"]))
    capacity = Decimal(str(bath["amp_hour_capacity"]))
    if used + reserved + estimate > capacity:
        raise_err(ERR_BATH_CAPACITY_EXCEEDED, "amp-hour capacity would be exceeded")
    customer = store.customers.get(wo["customer_id"])
    if customer is not None:
        if customer["credit_hold"]:
            raise_err(ERR_CUSTOMER_CREDIT_HOLD, "customer is on credit hold")
        if customer["status"] != "ACTIVE":
            raise_err(ERR_CUSTOMER_SUSPENDED, "customer is suspended")

    run = stamp_new({
        "work_order_id": wo["id"],
        "bath_id": bath["id"],
        "fixture_id": wo.get("fixture_id"),
        "duration_minutes": duration_minutes,
        "current_density_a_dm2": current_density,
        "surface_area_dm2": wo["surface_area_total_dm2"],
        "estimated_amp_hours": estimate,
        "amp_hours_consumed": None,
        "started_at": format_ts(get_clock()),
        "ended_at": None,
        "status": "RUNNING",
    })
    store.load_runs[run["id"]] = run
    bath["amp_hour_reserved"] = chemistry.round2(Decimal(str(bath["amp_hour_reserved"])) + estimate)
    bath["active_load_run_id"] = run["id"]
    touch(bath)
    wo["status"] = "IN_PROCESS"
    touch(wo)
    return success_object(load_run_view(run), status=201)


@bp.route("/work-orders/<wo_id>/load-runs", methods=["GET"])
def list_work_order_load_runs(wo_id):
    user_id, role = require_roles(WO_READ_ROLES)
    wo = store.work_orders.get(wo_id)
    if wo is None:
        raise_err(ERR_NOT_FOUND, "work order not found")
    check_customer_owns(role, user_id, wo["customer_id"])
    limit, offset = parse_pagination()
    items = [r for r in store.load_runs.values() if r["work_order_id"] == wo["id"]]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    page, total = paginate(items, limit, offset)
    return success_list([load_run_view(r) for r in page], limit, offset, total)


@bp.route("/work-orders/<wo_id>/inspections", methods=["POST"])
def create_inspection(wo_id):
    user_id, role = require_roles({"QCInspector", "ShopManager"})
    wo = get_or_404(store.work_orders, wo_id)
    data = body_json()
    readings = data.get("thickness_readings_um")
    defect_type = data.get("defect_type")

    # Tier 5: schema
    if not isinstance(readings, list) or len(readings) < 3:
        raise_err(ERR_INVALID_REQUEST, "thickness_readings_um must be an array of at least 3 readings")
    for r in readings:
        if not is_number(r) or not (r > 0):
            raise_err(ERR_INVALID_REQUEST, "each thickness reading must be a number > 0")
    if defect_type not in DEFECT_TYPES:
        raise_err(ERR_INVALID_REQUEST, "defect_type is invalid")

    # Tier 7: state
    if wo["status"] != "AWAITING_INSPECTION":
        raise_err(ERR_WORK_ORDER_NOT_AWAITING_INSPECTION, "inspection requires status AWAITING_INSPECTION")

    thickness_min = min(readings)
    thickness_max = max(readings)
    thickness_ok = (
        Decimal(str(thickness_min)) >= Decimal(str(wo["thickness_spec_min_um"]))
        and Decimal(str(thickness_max)) <= Decimal(str(wo["thickness_spec_max_um"]))
    )

    # Disposition rule
    if thickness_ok and defect_type == "NONE":
        disposition = "PASS"
    elif defect_type in ("BURN", "ADHESION"):
        disposition = "SCRAP_REJECT"
    elif wo["rework_count"] >= MAX_REWORKS:
        disposition = "SCRAP_REJECT"
    else:
        disposition = "REWORKABLE_REJECT"

    # Link to the latest COMPLETED load run of this work order
    completed = [r for r in store.load_runs.values()
                 if r["work_order_id"] == wo["id"] and r["status"] == "COMPLETED"]
    completed.sort(key=lambda r: (r["created_at"], r["id"]))
    latest_run_id = completed[-1]["id"] if completed else None

    report = stamp_event({
        "work_order_id": wo["id"],
        "load_run_id": latest_run_id,
        "thickness_readings_um": list(readings),
        "defect_type": defect_type,
        "thickness_min_um": thickness_min,
        "thickness_max_um": thickness_max,
        "thickness_ok": thickness_ok,
        "disposition": disposition,
    })
    store.inspections[report["id"]] = report

    if disposition == "PASS":
        wo["status"] = "AWAITING_LOT_TEST" if wo["requires_salt_spray"] else "COMPLETE"
    elif disposition == "SCRAP_REJECT":
        wo["status"] = "SCRAPPED"
    else:  # REWORKABLE_REJECT
        wo["status"] = "REJECTED"
        wo["pending_strip"] = True
        wo["last_defect_type"] = defect_type
    touch(wo)
    return success_object(inspection_view(report), status=201)


@bp.route("/work-orders/<wo_id>/inspections", methods=["GET"])
def list_inspections(wo_id):
    user_id, role = require_roles(WO_READ_ROLES)
    wo = store.work_orders.get(wo_id)
    if wo is None:
        raise_err(ERR_NOT_FOUND, "work order not found")
    check_customer_owns(role, user_id, wo["customer_id"])
    limit, offset = parse_pagination()
    items = [i for i in store.inspections.values() if i["work_order_id"] == wo["id"]]
    items.sort(key=lambda i: (i["created_at"], i["id"]))
    page, total = paginate(items, limit, offset)
    return success_list([inspection_view(i) for i in page], limit, offset, total)


@bp.route("/work-orders/<wo_id>/start-strip", methods=["POST"])
def start_strip(wo_id):
    user_id, role = require_roles({"LineOperator", "ShopManager"})
    wo = get_or_404(store.work_orders, wo_id)
    data = body_json()
    strip_method = data.get("strip_method")
    if strip_method is None or not isinstance(strip_method, str):
        raise_err(ERR_INVALID_REQUEST, "strip_method is required")
    if wo["status"] != "REJECTED":
        raise_err(ERR_WORK_ORDER_NOT_REJECTED, "start-strip requires status REJECTED")
    wo["status"] = "STRIPPING"
    touch(wo)
    return success_object(work_order_view(wo))


@bp.route("/work-orders/<wo_id>/complete-strip", methods=["POST"])
def complete_strip(wo_id):
    user_id, role = require_roles({"LineOperator", "ShopManager"})
    wo = get_or_404(store.work_orders, wo_id)
    if wo["status"] != "STRIPPING":
        raise_err(ERR_WORK_ORDER_NOT_STRIPPING, "complete-strip requires status STRIPPING")
    wo["rework_count"] += 1
    wo["pending_strip"] = False
    wo["bath_id"] = None
    wo["fixture_id"] = None
    wo["routed_chemistry_family"] = None
    wo["predip_completed"] = False
    wo["status"] = "READY_FOR_ROUTING"
    touch(wo)
    return success_object(work_order_view(wo))


@bp.route("/work-orders/<wo_id>/ship", methods=["POST"])
def ship_work_order(wo_id):
    user_id, role = require_roles({"LineOperator", "ShopManager"})
    wo = get_or_404(store.work_orders, wo_id)
    if wo["status"] != "COMPLETE":
        raise_err(ERR_WORK_ORDER_NOT_COMPLETE, "ship requires status COMPLETE")
    customer = store.customers.get(wo["customer_id"])
    if customer is not None:
        if customer["credit_hold"]:
            raise_err(ERR_CUSTOMER_CREDIT_HOLD, "customer is on credit hold")
        if customer["status"] != "ACTIVE":
            raise_err(ERR_CUSTOMER_SUSPENDED, "customer is suspended")
    wo["final_invoice_cents"] = pricing.compute_price(wo, "final")
    wo["status"] = "SHIPPED"
    touch(wo)
    return success_object(work_order_view(wo))


@bp.route("/work-orders/<wo_id>/cancel", methods=["POST"])
def cancel_work_order(wo_id):
    user_id, role = require_roles({"Customer", "ShopManager"})
    wo = store.work_orders.get(wo_id)
    if wo is None:
        raise_err(ERR_NOT_FOUND, "work order not found")
    # Tier 3: ownership — a Customer may only reach its own orders
    check_customer_owns(role, user_id, wo["customer_id"])

    status = wo["status"]
    if role == "Customer":
        if status in EARLY_CANCEL_STATES:
            fee = 0
        else:
            raise_err(ERR_WORK_ORDER_NOT_CANCELLABLE, "owner cancel is permitted only from early states")
    else:  # ShopManager
        if status in EARLY_CANCEL_STATES:
            fee = 0
        elif status in LATE_CANCEL_STATES:
            fee = pricing.compute_cancellation_fee(wo)
        else:
            raise_err(ERR_WORK_ORDER_NOT_CANCELLABLE, "cancel not permitted from this state")

    wo["cancellation_fee_cents"] = fee
    wo["bath_id"] = None
    wo["fixture_id"] = None
    wo["routed_chemistry_family"] = None
    wo["status"] = "CANCELLED"
    touch(wo)
    return success_object(work_order_view(wo))


@bp.route("/work-orders/<wo_id>/salt-spray-lots", methods=["GET"])
def list_work_order_lots(wo_id):
    user_id, role = require_roles(WO_READ_ROLES)
    wo = store.work_orders.get(wo_id)
    if wo is None:
        raise_err(ERR_NOT_FOUND, "work order not found")
    check_customer_owns(role, user_id, wo["customer_id"])
    limit, offset = parse_pagination()
    items = [l for l in store.salt_spray_lots.values() if l["work_order_id"] == wo["id"]]
    items.sort(key=lambda l: (l["created_at"], l["id"]))
    page, total = paginate(items, limit, offset)
    return success_list([salt_spray_lot_view(l) for l in page], limit, offset, total)


def _find_compat_rule(alloy_code, process_type, chemistry_family):
    for r in store.compat_rules.values():
        if (
            r["alloy_code"] == alloy_code
            and r["process_type"] == process_type
            and r["chemistry_family"] == chemistry_family
        ):
            return r
    return None
