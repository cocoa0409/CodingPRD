"""GrindingBatch endpoints."""

from flask import Blueprint, request

from db import db
from errors import raise_err
from middleware import (
    require_roles, get_json_body, parse_pagination, paginate,
    req_field, opt_field, as_int, as_number,
)
from response import success
from services.calc import compute_yield_ratio
from services.helpers import (
    init_common, touch, serialize, serialize_list, sorted_by_creation,
    get_or_404,
)

bp = Blueprint("grinding", __name__)


@bp.post("/pallet-ops/grinding-batches")
def create_grinding_batch():
    require_roles("YardSupervisor")
    body = get_json_body()
    input_core_ids = req_field(body, "input_core_ids")
    if not isinstance(input_core_ids, list) or not input_core_ids:
        raise_err("ERR_INVALID_REQUEST", "input_core_ids must be a non-empty array")
    for cid in input_core_ids:
        if not isinstance(cid, str):
            raise_err("ERR_INVALID_REQUEST", "input_core_ids must contain string ids")
        rec = db.core_units.get(cid)
        if rec is None:
            raise_err(
                "ERR_REFERENCED_NOT_FOUND",
                "Referenced input core id does not exist: %s" % cid,
            )

    batch = {
        "input_core_ids": list(input_core_ids),
        "input_count": len(input_core_ids),
        "output_fiber_cuyd": None,
        "yield_ratio": None,
        "revenue_cents": 0,
        "status": "QUEUED",
    }
    init_common(batch)
    db.grinding_batches[batch["id"]] = batch
    return success(serialize(batch), status=201)


@bp.get("/pallet-ops/grinding-batches")
def list_grinding_batches():
    require_roles()
    limit, offset = parse_pagination()
    items = list(db.grinding_batches.values())
    status = request.args.get("status")
    if status is not None:
        items = [b for b in items if b["status"] == status]
    items = sorted_by_creation(items)
    page, pagination = paginate(items, limit, offset)
    return success(serialize_list(page), pagination=pagination, is_list=True)


@bp.get("/pallet-ops/grinding-batches/<gid>")
def get_grinding_batch(gid):
    require_roles()
    batch = get_or_404(db.grinding_batches, gid, "GrindingBatch")
    return success(serialize(batch))


@bp.post("/pallet-ops/grinding-batches/<gid>/start")
def start_grinding_batch(gid):
    require_roles("YardSupervisor")
    batch = get_or_404(db.grinding_batches, gid, "GrindingBatch")
    if batch["status"] != "QUEUED":
        raise_err("ERR_GRIND_NOT_QUEUED", "start requires grinding batch QUEUED")
    for cid in batch["input_core_ids"]:
        core = db.core_units.get(cid)
        if (
            core is None
            or core["grade"] != "SCRAP"
            or core["processing_status"] != "GRINDING_QUEUED"
        ):
            raise_err(
                "ERR_CORE_NOT_GRINDABLE",
                "Grind input cores must be grade SCRAP and GRINDING_QUEUED",
            )
    batch["status"] = "GRINDING"
    touch(batch)
    return success(serialize(batch))


@bp.post("/pallet-ops/grinding-batches/<gid>/complete")
def complete_grinding_batch(gid):
    require_roles("YardSupervisor")
    batch = get_or_404(db.grinding_batches, gid, "GrindingBatch")
    body = get_json_body()
    output_fiber = as_number(
        req_field(body, "output_fiber_cuyd"), "output_fiber_cuyd", minimum=0
    )
    revenue = opt_field(body, "revenue_cents", 0)
    revenue = as_int(revenue, "revenue_cents", minimum=0)

    if batch["status"] != "GRINDING":
        raise_err("ERR_GRIND_NOT_RUNNING", "complete requires grinding batch GRINDING")

    batch["output_fiber_cuyd"] = output_fiber
    batch["revenue_cents"] = revenue
    batch["yield_ratio"] = compute_yield_ratio(output_fiber, batch["input_count"])
    batch["status"] = "COMPLETED"
    touch(batch)

    for cid in batch["input_core_ids"]:
        core = db.core_units.get(cid)
        if core is not None:
            core["processing_status"] = "GROUND"
            touch(core)
    return success(serialize(batch))
