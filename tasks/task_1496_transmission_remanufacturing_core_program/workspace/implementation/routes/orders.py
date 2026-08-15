"""RemanOrder endpoints and the reman pipeline transitions."""

import uuid
from datetime import timedelta

from flask import Blueprint, request

from db import db
from errors import (
    ApiError, ERR_MODEL_NOT_FOUND, ERR_ORDER_NOT_FOUND,
    ERR_ORDER_NOT_READY_FOR_KIT, ERR_ORDER_NOT_READY_FOR_ASSEMBLY,
    ERR_ORDER_NOT_READY_FOR_CALIBRATION, ERR_CAL_NOT_DRAFT,
    ERR_SOD_VERIFICATION_FORBIDDEN, ERR_CAL_STALE,
    ERR_ORDER_NOT_SHIPPABLE, ERR_ORDER_NOT_CANCELLABLE,
    ERR_ORDER_NOT_RESYNCABLE, ERR_STALE_VERSION,
)
from middleware import require_role
from response import success
from services.allocation import (
    try_allocate, apply_picks, release_reservations, promotion_scan,
)
from services.calculations import provisional_credit
from services.serializers import order_view
from validators import (
    get_json_body, require_fields, check_string, check_int,
    parse_limit_offset, paginate,
)

bp = Blueprint("orders", __name__)

CANCELLABLE = {"QUEUED", "PART_HOLD", "ASSEMBLY", "CALIBRATION"}
RESYNCABLE = {"QUEUED", "PART_HOLD", "ASSEMBLY", "CALIBRATION", "REWORK"}
CAL_DRAFTABLE = {"CALIBRATION", "REWORK"}
CAL_MAX_AGE = timedelta(hours=72)


def _get_order(oid):
    o = db.reman_orders.get(oid)
    if o is None:
        raise ApiError(ERR_ORDER_NOT_FOUND, "RemanOrder id does not exist", 404)
    return o


def _snapshot_spec(model):
    return {
        "required_parts": model["required_parts"],
        "dyno_targets": model["dyno_targets"],
        "flat_rate_hours": model["flat_rate_hours"],
        "labor_cap_cents": model["labor_cap_cents"],
        "core_deposit_cents": model["core_deposit_cents"],
        "warranty_days": model["warranty_days"],
    }


@bp.post("/api/reman-orders")
def create_order():
    require_role({"RemanPlanner"})
    body = get_json_body()
    require_fields(body, ["transmission_model_id", "buyer_ref"])
    check_string(body["transmission_model_id"], "transmission_model_id")
    check_string(body["buyer_ref"], "buyer_ref")

    model = db.transmission_models.get(body["transmission_model_id"])
    if model is None:
        raise ApiError(ERR_MODEL_NOT_FOUND, "TransmissionModel id does not exist", 404)

    now = db.now()
    o = {
        "id": str(uuid.uuid4()),
        "transmission_model_id": model["id"],
        "buyer_ref": body["buyer_ref"],
        "pinned_spec": _snapshot_spec(model),
        "model_spec_version_pin": model["spec_version"],
        "status": "QUEUED",
        "shortage_parts": [],
        "reserved_parts": [],
        "surcharge_labor_minutes": 0,
        "cal_status": "NONE",
        "cal_generation": 0,
        "solenoid_trims": None,
        "tcm_flash_version": None,
        "tcm_flash_version_applied": None,
        "cal_created_by_id": None,
        "cal_created_at": None,
        "dyno_attempts_used": 0,
        "last_shift_quality_score": None,
        "core_settlement_status": "PENDING",
        "shipped_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.reman_orders[o["id"]] = o
    return success(order_view(o), "object", 201)


@bp.get("/api/reman-orders")
def list_orders():
    require_role({"Any"})
    items = list(db.reman_orders.values())
    tmid = request.args.get("transmission_model_id")
    status = request.args.get("status")
    if tmid is not None:
        items = [o for o in items if o["transmission_model_id"] == tmid]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    items.sort(key=lambda o: o["created_at"])
    limit, offset = parse_limit_offset(request.args)
    page, pg = paginate(items, limit, offset)
    return success([order_view(o) for o in page], "array", 200, pg)


@bp.get("/api/reman-orders/<oid>")
def get_order(oid):
    require_role({"Any"})
    return success(order_view(_get_order(oid)), "object", 200)


@bp.post("/api/reman-orders/<oid>/kit-reserve")
def kit_reserve(oid):
    require_role({"RemanPlanner"})
    o = _get_order(oid)
    if o["status"] not in {"QUEUED", "PART_HOLD"}:
        raise ApiError(
            ERR_ORDER_NOT_READY_FOR_KIT,
            "kit-reserve requires status QUEUED or PART_HOLD",
            409,
        )
    picks, shortages = try_allocate(o)
    now = db.now()
    if picks is None:
        # All-or-nothing: reserve nothing, record shortage families.
        o["shortage_parts"] = shortages
        o["status"] = "PART_HOLD"
        o["updated_at"] = now
        o["version"] += 1
        return success(order_view(o), "object", 200)
    apply_picks(o, picks)
    o["status"] = "ASSEMBLY"
    o["updated_at"] = now
    o["version"] += 1
    return success(order_view(o), "object", 200)


@bp.post("/api/reman-orders/<oid>/complete-assembly")
def complete_assembly(oid):
    require_role({"RemanTechnician"})
    o = _get_order(oid)
    if o["status"] != "ASSEMBLY":
        raise ApiError(
            ERR_ORDER_NOT_READY_FOR_ASSEMBLY,
            "complete-assembly requires status ASSEMBLY",
            409,
        )
    o["status"] = "CALIBRATION"
    o["updated_at"] = db.now()
    o["version"] += 1
    return success(order_view(o), "object", 200)


@bp.put("/api/reman-orders/<oid>/calibration")
def put_calibration(oid):
    user_id, _ = require_role({"Calibrator"})
    body = get_json_body()
    require_fields(body, ["solenoid_trims", "tcm_flash_version"])
    if not isinstance(body["solenoid_trims"], list):
        from validators import invalid
        invalid("Field solenoid_trims must be an array")
    check_string(body["tcm_flash_version"], "tcm_flash_version")

    o = _get_order(oid)
    if o["status"] not in CAL_DRAFTABLE:
        raise ApiError(
            ERR_ORDER_NOT_READY_FOR_CALIBRATION,
            "calibration draft requires status CALIBRATION or REWORK",
            409,
        )
    o["solenoid_trims"] = body["solenoid_trims"]
    o["tcm_flash_version"] = body["tcm_flash_version"]
    o["cal_status"] = "DRAFT"
    o["cal_generation"] += 1
    o["cal_created_by_id"] = user_id
    o["cal_created_at"] = db.now()
    o["updated_at"] = db.now()
    o["version"] += 1
    return success(order_view(o), "object", 200)


@bp.post("/api/reman-orders/<oid>/verify-calibration")
def verify_calibration(oid):
    user_id, _ = require_role({"Calibrator"})
    o = _get_order(oid)
    # State gate (priority 6) before SoD (7) before staleness (8).
    if o["status"] not in CAL_DRAFTABLE:
        raise ApiError(
            ERR_ORDER_NOT_READY_FOR_CALIBRATION,
            "verify-calibration requires status CALIBRATION or REWORK",
            409,
        )
    if o["cal_status"] != "DRAFT":
        raise ApiError(
            ERR_CAL_NOT_DRAFT, "verify-calibration requires cal_status DRAFT", 409
        )
    if user_id == o["cal_created_by_id"]:
        raise ApiError(
            ERR_SOD_VERIFICATION_FORBIDDEN,
            "verify-calibration X-User-ID equals cal_created_by_id (segregation of duties)",
            403,
        )
    if db.now() - o["cal_created_at"] > CAL_MAX_AGE:
        raise ApiError(
            ERR_CAL_STALE, "calibration draft older than 72h at verify time", 422
        )
    o["cal_status"] = "VERIFIED"
    o["tcm_flash_version_applied"] = o["tcm_flash_version"]
    o["status"] = "DYNO_QUEUE"
    o["updated_at"] = db.now()
    o["version"] += 1
    return success(order_view(o), "object", 200)


@bp.post("/api/reman-orders/<oid>/resync-spec")
def resync_spec(oid):
    require_role({"RemanPlanner"})
    body = get_json_body()
    require_fields(body, ["expected_reman_order_version"])
    check_int(body["expected_reman_order_version"], "expected_reman_order_version")

    o = _get_order(oid)
    # OCC (priority 5) precedes the state gate (priority 6).
    if body["expected_reman_order_version"] != o["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            "expected_reman_order_version does not match the order's current version",
            412,
        )
    if o["status"] not in RESYNCABLE:
        raise ApiError(
            ERR_ORDER_NOT_RESYNCABLE,
            "resync-spec requires status in {QUEUED, PART_HOLD, ASSEMBLY, CALIBRATION, REWORK}",
            409,
        )
    model = db.transmission_models.get(o["transmission_model_id"])
    if model is None:
        raise ApiError(ERR_MODEL_NOT_FOUND, "TransmissionModel id does not exist", 404)
    o["pinned_spec"] = _snapshot_spec(model)
    o["model_spec_version_pin"] = model["spec_version"]
    o["updated_at"] = db.now()
    o["version"] += 1
    return success(order_view(o), "object", 200)


@bp.post("/api/reman-orders/<oid>/ship")
def ship(oid):
    require_role({"RemanPlanner"})
    o = _get_order(oid)
    if o["status"] != "DYNO_PASSED":
        raise ApiError(
            ERR_ORDER_NOT_SHIPPABLE, "ship requires status DYNO_PASSED", 409
        )
    now = db.now()
    o["status"] = "SHIPPED"
    o["shipped_at"] = now
    # Consume reservations: qty_reserved -= qty AND qty_on_hand -= qty.
    for line in o["reserved_parts"]:
        part = db.hard_parts.get(line["hard_part_id"])
        if part is not None:
            part["qty_reserved"] -= line["qty"]
            part["qty_on_hand"] -= line["qty"]
            part["updated_at"] = now
            part["version"] += 1
    # Create the core deposit invoice (OPEN) with provisional credit 0.8x.
    deposit = o["pinned_spec"]["core_deposit_cents"]
    inv = {
        "id": str(uuid.uuid4()),
        "reman_order_id": o["id"],
        "buyer_ref": o["buyer_ref"],
        "deposit_cents": deposit,
        "issued_at": now,
        "provisional_credit_cents": provisional_credit(deposit),
        "final_credit_cents": None,
        "forfeited_cents": None,
        "status": "OPEN",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.core_deposit_invoices[inv["id"]] = inv
    o["updated_at"] = now
    o["version"] += 1
    return success(order_view(o), "object", 200)


@bp.post("/api/reman-orders/<oid>/cancel")
def cancel(oid):
    require_role({"RemanPlanner"})
    o = _get_order(oid)
    if o["status"] not in CANCELLABLE:
        raise ApiError(
            ERR_ORDER_NOT_CANCELLABLE,
            "cancel requires status in {QUEUED, PART_HOLD, ASSEMBLY, CALIBRATION}",
            409,
        )
    release_reservations(o)
    if o["status"] == "CALIBRATION" and o["cal_status"] == "DRAFT":
        o["cal_status"] = "SUPERSEDED"
    o["status"] = "CANCELLED"
    o["updated_at"] = db.now()
    o["version"] += 1
    promotion_scan()
    return success(order_view(o), "object", 200)
