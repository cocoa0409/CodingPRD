"""ProductionVendor and ProductionBatch endpoints."""
from flask import Blueprint, request

from core import (
    STORE, ApiError, ok, ok_list, body, req_field, req_int,
    new_entity, touch, pub, sort_created, get_or_404, require_roles,
    parse_date, now, NETWORKS, CAPABILITY_FLAGS,
)

bp = Blueprint("vendors_batches", __name__)

BATCH_READ = ("ProgramManager", "OperationsAnalyst", "FinanceController", "PlatformAdmin")


def _get_program(pid):
    return get_or_404("programs", pid, "program")


def _get_vendor(vid):
    return get_or_404("vendors", vid, "vendor")


def _get_batch(bid):
    return get_or_404("batches", bid, "production batch")


# ---------------------------------------------------------------------------
# ProductionVendor
# ---------------------------------------------------------------------------

@bp.post("/issuing/vendors")
@require_roles("PlatformAdmin")
def create_vendor():
    data = body()
    vendor_code = req_field(data, "vendor_code")
    if not isinstance(vendor_code, str) or not vendor_code:
        raise ApiError("ERR_VALIDATION", 400, "vendor_code must be a non-empty string")
    capability_flags = req_field(data, "capability_flags")
    if not isinstance(capability_flags, list) or not capability_flags or \
            any(f not in CAPABILITY_FLAGS for f in capability_flags):
        raise ApiError("ERR_VALIDATION", 400,
                       "capability_flags must be a non-empty subset of %s"
                       % list(CAPABILITY_FLAGS))
    capacity = req_int(data, "daily_capacity_cards", min_value=1)
    supported = req_field(data, "supported_networks")
    if not isinstance(supported, list) or \
            any(n not in NETWORKS for n in supported):
        raise ApiError("ERR_VALIDATION", 400,
                       "supported_networks must be a subset of %s" % list(NETWORKS))
    is_active = data.get("is_active", True)
    if not isinstance(is_active, bool):
        raise ApiError("ERR_VALIDATION", 400, "is_active must be a boolean")
    for v in STORE["vendors"].values():
        if v["vendor_code"] == vendor_code:
            raise ApiError("ERR_VALIDATION", 409,
                           "vendor_code %s already exists" % vendor_code)
    v = new_entity()
    v.update({
        "vendor_code": vendor_code,
        "capability_flags": capability_flags,
        "daily_capacity_cards": capacity,
        "supported_networks": supported,
        "is_active": is_active,
    })
    STORE["vendors"][v["id"]] = v
    return ok(pub(v), 201)


@bp.get("/issuing/vendors/<vid>")
@require_roles("ProgramManager", "OperationsAnalyst", "PlatformAdmin")
def get_vendor(vid):
    return ok(pub(_get_vendor(vid)))


@bp.get("/issuing/vendors/<vid>/production-batches")
@require_roles("ProgramManager", "OperationsAnalyst", "PlatformAdmin")
def list_vendor_batches(vid):
    _get_vendor(vid)
    items = [b for b in STORE["batches"].values() if b["vendor_id"] == vid]
    status = request.args.get("status")
    if status is not None:
        items = [b for b in items if b["status"] == status]
    return ok_list([pub(b) for b in sort_created(items)])


# ---------------------------------------------------------------------------
# ProductionBatch
# ---------------------------------------------------------------------------

@bp.post("/issuing/programs/<pid>/production-batches")
@require_roles("OperationsAnalyst")
def create_batch(pid):
    _get_program(pid)
    data = body()
    vendor_id = req_field(data, "vendor_id")
    if not isinstance(vendor_id, str) or vendor_id not in STORE["vendors"]:
        raise ApiError("ERR_INVALID_REFERENCE", 422,
                       "vendor_id does not resolve to an existing vendor")
    raw_date = req_field(data, "scheduled_for_utc_date")
    try:
        parse_date(raw_date)
    except ValueError:
        raise ApiError("ERR_VALIDATION", 400,
                       "scheduled_for_utc_date must be a YYYY-MM-DD date")
    requested = req_int(data, "requested_card_count", min_value=1)
    unit_cost = req_int(data, "unit_cost_cents", min_value=0)
    b = new_entity()
    b.update({
        "program_id": pid,
        "vendor_id": vendor_id,
        "scheduled_for_utc_date": raw_date,
        "requested_card_count": requested,
        "fulfilled_card_count": 0,
        "unit_cost_cents": unit_cost,
        "status": "PLANNED",
    })
    STORE["batches"][b["id"]] = b
    return ok(pub(b), 201)


@bp.get("/issuing/programs/<pid>/production-batches")
@require_roles(*BATCH_READ)
def list_program_batches(pid):
    _get_program(pid)
    items = [b for b in STORE["batches"].values() if b["program_id"] == pid]
    status = request.args.get("status")
    if status is not None:
        items = [b for b in items if b["status"] == status]
    vendor_id = request.args.get("vendor_id")
    if vendor_id is not None:
        items = [b for b in items if b["vendor_id"] == vendor_id]
    return ok_list([pub(b) for b in sort_created(items)])


@bp.get("/issuing/production-batches/<bid>")
@require_roles(*BATCH_READ)
def get_batch(bid):
    return ok(pub(_get_batch(bid)))


@bp.post("/issuing/production-batches/<bid>/submit")
@require_roles("OperationsAnalyst")
def submit_batch(bid):
    b = _get_batch(bid)
    if b["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE", 409, "submit requires status PLANNED")
    prog = STORE["programs"].get(b["program_id"])
    if prog is None or prog["posture"] != "LIVE":
        raise ApiError("ERR_PROGRAM_NOT_LIVE", 409,
                       "batch submit requires program posture LIVE")
    vendor = STORE["vendors"].get(b["vendor_id"])
    if vendor is None:
        raise ApiError("ERR_INVALID_REFERENCE", 422, "vendor no longer exists")
    if not vendor["is_active"]:
        raise ApiError("ERR_VENDOR_INACTIVE", 409, "vendor is not active")
    if prog["network"] not in vendor["supported_networks"]:
        raise ApiError("ERR_VENDOR_NETWORK_MISMATCH", 409,
                       "vendor does not support network %s" % prog["network"])
    if b["requested_card_count"] > vendor["daily_capacity_cards"]:
        raise ApiError("ERR_VENDOR_CAPACITY_EXCEEDED", 409,
                       "requested_card_count exceeds vendor daily capacity")
    batch_date = parse_date(b["scheduled_for_utc_date"])
    if batch_date < now().date():
        raise ApiError("ERR_BATCH_DATE_PAST", 409,
                       "scheduled_for_utc_date is in the past")
    for other in STORE["batches"].values():
        if other["id"] == b["id"]:
            continue
        if other["vendor_id"] == b["vendor_id"] and \
                other["scheduled_for_utc_date"] == b["scheduled_for_utc_date"] and \
                other["status"] in ("SUBMITTED", "IN_PRODUCTION"):
            raise ApiError("ERR_VENDOR_BATCH_OVERLAP", 409,
                           "another batch for this vendor and date is in flight")
    b["status"] = "SUBMITTED"
    touch(b)
    return ok(pub(b))


@bp.post("/issuing/production-batches/<bid>/start")
@require_roles("OperationsAnalyst")
def start_batch(bid):
    b = _get_batch(bid)
    if b["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "start requires status SUBMITTED")
    b["status"] = "IN_PRODUCTION"
    touch(b)
    return ok(pub(b))


@bp.post("/issuing/production-batches/<bid>/mark_shipped")
@require_roles("OperationsAnalyst")
def ship_batch(bid):
    b = _get_batch(bid)
    if b["status"] != "IN_PRODUCTION":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "mark_shipped requires status IN_PRODUCTION")
    data = body()
    fulfilled = req_int(data, "fulfilled_card_count", min_value=0)
    if fulfilled > b["requested_card_count"]:
        raise ApiError("ERR_FULFILLED_EXCEEDS_REQUESTED", 409,
                       "fulfilled_card_count exceeds requested_card_count")
    b["fulfilled_card_count"] = fulfilled
    b["status"] = "SHIPPED"
    touch(b)
    return ok(pub(b))


@bp.post("/issuing/production-batches/<bid>/mark_delivered")
@require_roles("OperationsAnalyst")
def deliver_batch(bid):
    b = _get_batch(bid)
    if b["status"] != "SHIPPED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "mark_delivered requires status SHIPPED")
    b["status"] = "DELIVERED"
    touch(b)
    return ok(pub(b))


@bp.post("/issuing/production-batches/<bid>/cancel")
@require_roles("OperationsAnalyst")
def cancel_batch(bid):
    b = _get_batch(bid)
    if b["status"] not in ("PLANNED", "SUBMITTED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "cancel requires status PLANNED or SUBMITTED")
    b["status"] = "CANCELLED"
    touch(b)
    return ok(pub(b))


@bp.post("/issuing/production-batches/<bid>/mark_failed")
@require_roles("OperationsAnalyst")
def fail_batch(bid):
    b = _get_batch(bid)
    if b["status"] != "IN_PRODUCTION":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "mark_failed requires status IN_PRODUCTION")
    b["status"] = "FAILED"
    # Cards are not linked to batches in this model; the minted-not-active
    # cascade has no reachable cards.
    touch(b)
    return ok(pub(b))
