"""Clock, service centres, surge windows, queue review and the catalogue."""

from flask import Blueprint

import calc
import services as svc
from core import (
    db, dt_of, fail, get_body, iso, new_row, now, ordered, page, pagination,
    q_str, require, respond, respond_list, set_fields, v_bool, v_enum, v_instant,
    v_int, v_number, v_string,
)

bp = Blueprint("config", __name__)


# --------------------------------------------------------------------------- #
# Logical clock
# --------------------------------------------------------------------------- #

@bp.post("/_clock/set_current_utc")
def set_clock():
    require("ProgramAdmin")
    body = get_body()
    instant = v_instant(body, "current_utc", required=True)
    db.clock = instant
    return respond({"current_utc": iso(instant)})


# --------------------------------------------------------------------------- #
# Service centres
# --------------------------------------------------------------------------- #

@bp.post("/service-centers")
def create_center():
    require("ProgramAdmin")
    body = get_body()
    name = v_string(body, "name", required=True, min_len=1, max_len=120)
    region_code = v_string(body, "region_code", required=True, min_len=2, max_len=8)
    if region_code != region_code.upper():
        fail("ERR_INVALID_REQUEST", "Field 'region_code' must be uppercase.")
    cap = v_int(body, "liability_cap_cents", required=True, min_value=1)
    capacity = v_int(
        body, "bench_capacity_blocks_per_day", min_value=1, max_value=200, default=24
    )

    row = new_row()
    row.update({
        "name": name,
        "region_code": region_code,
        "liability_cap_cents": cap,
        "bench_capacity_blocks_per_day": capacity,
        "open_liability_cents": 0,
        "liability_utilization_pct": 0.0,
        "liability_posture": "OPEN",
        "active_queue_depth": 0,
        "current_surge_multiplier": 1.0,
        "breached_commitment_count": 0,
        "last_queue_review_at": None,
    })
    db.service_centers[row["id"]] = row
    return respond(svc.ser(row), 201)


@bp.get("/service-centers/<center_id>")
def read_center(center_id):
    require("ServiceAgent", "RepairTechnician", "PartsCoordinator", "ProgramAdmin")
    center = svc.need(db.service_centers, center_id, "ERR_SERVICE_CENTER_NOT_FOUND")
    return respond(svc.ser(center))


# --------------------------------------------------------------------------- #
# Surge windows
# --------------------------------------------------------------------------- #

@bp.post("/service-centers/<center_id>/surge-windows")
def create_surge_window(center_id):
    require("ProgramAdmin")
    center = svc.need(db.service_centers, center_id, "ERR_SERVICE_CENTER_NOT_FOUND")
    body = get_body()
    label = v_string(body, "label", required=True, min_len=1, max_len=120)
    start_at = v_instant(body, "start_date", required=True)
    end_at = v_instant(body, "end_date", required=True)
    multiplier = v_number(
        body, "multiplier", required=True, min_value=1.0, max_value=3.0, max_decimals=2
    )

    # check 32 -- ordered endpoints
    if start_at > end_at:
        fail("ERR_INVALID_WINDOW")

    # check 33 -- closed-inclusive overlap against ACTIVE windows of this centre
    for window in ordered(db.surge_windows):
        if window["service_center_id"] != center["id"] or window["status"] != "ACTIVE":
            continue
        other_start = dt_of(window["start_date"])
        other_end = dt_of(window["end_date"])
        if other_start <= end_at and start_at <= other_end:
            fail("ERR_SURGE_WINDOW_OVERLAP")

    row = new_row()
    row.update({
        "service_center_id": center["id"],
        "label": label,
        "start_date": iso(start_at),
        "end_date": iso(end_at),
        "multiplier": multiplier,
        "status": "ACTIVE",
    })
    db.surge_windows[row["id"]] = row

    svc.recompute_center_queue(center)
    return respond(svc.ser(row), 201)


@bp.get("/service-centers/<center_id>/surge-windows")
def list_surge_windows(center_id):
    require("ServiceAgent", "PartsCoordinator", "ProgramAdmin")
    center = svc.need(db.service_centers, center_id, "ERR_SERVICE_CENTER_NOT_FOUND")
    status = q_str("status")
    if status is not None and status not in ("ACTIVE", "RETIRED"):
        fail("ERR_INVALID_REQUEST", "Query parameter 'status' is not a recognised value.")
    limit, offset = pagination()
    rows = [
        w for w in ordered(db.surge_windows)
        if w["service_center_id"] == center["id"]
        and (status is None or w["status"] == status)
    ]
    window, total = page(rows, limit, offset)
    return respond_list(svc.ser_all(window), limit, offset, total)


# --------------------------------------------------------------------------- #
# Queue-review checkpoint
# --------------------------------------------------------------------------- #

@bp.post("/service-centers/<center_id>/queue-review")
def queue_review(center_id):
    require("ProgramAdmin")
    center = svc.need(db.service_centers, center_id, "ERR_SERVICE_CENTER_NOT_FOUND")
    clock = now()

    # sweep one -- expire stale provisional quotes
    for estimate in ordered(db.repair_estimates):
        if estimate["variant"] != "PROVISIONAL" or estimate["status"] != "SENT":
            continue
        order = db.repair_orders.get(estimate["repair_order_id"])
        if order is None or order["service_center_id"] != center["id"]:
            continue
        valid_until = dt_of(estimate["valid_until"])
        if valid_until is not None and valid_until < clock:
            set_fields(estimate, status="EXPIRED")
            if order["billing_status"] == "ESTIMATE_SENT":
                set_fields(order, billing_status="ESTIMATE_PENDING")

    # sweep two -- flag breached commitments
    breached = 0
    for order in ordered(db.repair_orders):
        if order["service_center_id"] != center["id"]:
            continue
        if order["work_status"] in calc.ORDER_WORK_TERMINAL:
            continue
        promised = dt_of(order["promised_return_at"])
        if promised is not None and promised < clock:
            set_fields(order, commitment_breached=True)
            breached += 1

    # sweep three -- retire elapsed surge windows
    for window in ordered(db.surge_windows):
        if window["service_center_id"] != center["id"] or window["status"] != "ACTIVE":
            continue
        end_at = dt_of(window["end_date"])
        if end_at is not None and end_at < clock:
            set_fields(window, status="RETIRED")

    # sweep four -- recompute the centre's derived surface in one mutation
    fields = svc.liability_fields(center)
    fields.update(svc.queue_fields(center))
    fields["breached_commitment_count"] = breached
    fields["last_queue_review_at"] = iso(clock)
    set_fields(center, **fields)

    return respond(svc.ser(center))


# --------------------------------------------------------------------------- #
# Catalogue models
# --------------------------------------------------------------------------- #

def _guard_cycle(model_id, successor_id):
    """Check 29 -- no self-reference and no loop through existing successor links."""
    if successor_id is None:
        return
    if successor_id == model_id:
        fail("ERR_SUCCESSOR_CYCLE")
    seen = set()
    cursor = successor_id
    while cursor:
        if cursor == model_id:
            fail("ERR_SUCCESSOR_CYCLE")
        if cursor in seen:
            return
        seen.add(cursor)
        nxt = db.gear_models.get(cursor)
        cursor = nxt.get("successor_model_id") if nxt is not None else None


@bp.post("/gear-models")
def create_model():
    require("ProgramAdmin")
    body = get_body()
    successor = svc.fk(body, "successor_model_id", db.gear_models, "ERR_GEAR_MODEL_NOT_FOUND")

    model_code = v_string(
        body, "model_code", required=True, min_len=3, max_len=32, pattern=r"^[A-Z0-9\-]+$"
    )
    name = v_string(body, "name", required=True, min_len=1, max_len=200)
    category = v_enum(body, "category", calc.CATEGORIES, required=True)
    msrp = v_int(body, "msrp_cents", required=True, min_value=1)
    release_year = v_int(body, "release_year", required=True, min_value=2000, max_value=2100)
    warranty_years = v_int(body, "warranty_years", required=True, min_value=0, max_value=30)
    lifetime = v_bool(body, "lifetime_warranty", default=False)
    discontinued_at = v_instant(body, "discontinued_at")

    _guard_cycle(None, successor["id"] if successor is not None else None)

    for existing in db.gear_models.values():
        if existing["model_code"] == model_code:
            fail("ERR_MODEL_CODE_TAKEN")

    row = new_row()
    row.update({
        "model_code": model_code,
        "name": name,
        "category": category,
        "msrp_cents": msrp,
        "release_year": release_year,
        "warranty_years": warranty_years,
        "lifetime_warranty": lifetime,
        "discontinued_at": iso(discontinued_at),
        "successor_model_id": successor["id"] if successor is not None else None,
        "parts_support_status": "NO_SUPPORT",
        "defect_claim_count": 0,
        "wear_denial_count": 0,
        "irreparable_count": 0,
        "repairability_flag": "NONE",
    })
    db.gear_models[row["id"]] = row
    svc.recompute_model_support(row)
    return respond(svc.ser(row), 201)


@bp.get("/gear-models/<model_id>")
def read_model(model_id):
    require("Customer", "ServiceAgent", "RepairTechnician", "PartsCoordinator", "ProgramAdmin")
    model = svc.need(db.gear_models, model_id, "ERR_GEAR_MODEL_NOT_FOUND")
    return respond(svc.ser(model))


@bp.get("/gear-models")
def list_models():
    require("Customer", "ServiceAgent", "RepairTechnician", "PartsCoordinator", "ProgramAdmin")
    category = q_str("category")
    if category is not None and category not in calc.CATEGORIES:
        fail("ERR_INVALID_REQUEST", "Query parameter 'category' is not a recognised value.")
    support = q_str("parts_support_status")
    if support is not None and support not in ("SUPPORTED", "SUBSTITUTION_ONLY", "NO_SUPPORT"):
        fail("ERR_INVALID_REQUEST", "Query parameter 'parts_support_status' is invalid.")
    flag = q_str("repairability_flag")
    if flag is not None and flag not in ("NONE", "WATCH", "REDESIGN_REQUESTED"):
        fail("ERR_INVALID_REQUEST", "Query parameter 'repairability_flag' is invalid.")
    successor_id = q_str("successor_model_id")
    limit, offset = pagination()

    rows = []
    for model in ordered(db.gear_models):
        if category is not None and model["category"] != category:
            continue
        if support is not None and model["parts_support_status"] != support:
            continue
        if flag is not None and model["repairability_flag"] != flag:
            continue
        if successor_id is not None and model["successor_model_id"] != successor_id:
            continue
        rows.append(model)
    window, total = page(rows, limit, offset)
    return respond_list(svc.ser_all(window), limit, offset, total)


@bp.patch("/gear-models/<model_id>")
def patch_model(model_id):
    require("ProgramAdmin")
    model = svc.need(db.gear_models, model_id, "ERR_GEAR_MODEL_NOT_FOUND")
    body = get_body()
    successor = svc.fk(body, "successor_model_id", db.gear_models, "ERR_GEAR_MODEL_NOT_FOUND")

    discontinued_at = v_instant(body, "discontinued_at")
    msrp = v_int(body, "msrp_cents", min_value=1)

    _guard_cycle(model["id"], successor["id"] if successor is not None else None)

    updates = {}
    if discontinued_at is not None:
        updates["discontinued_at"] = iso(discontinued_at)
    if successor is not None:
        updates["successor_model_id"] = successor["id"]
    if msrp is not None:
        updates["msrp_cents"] = msrp
    set_fields(model, **updates)

    svc.recompute_model_support(model)
    for item in ordered(db.gear_items):
        if item["gear_model_id"] == model["id"]:
            svc.rewrite_item_derived(item)

    return respond(svc.ser(model))
