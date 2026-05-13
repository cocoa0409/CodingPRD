"""Grant Batch routes."""

from flask import Blueprint, request
from db import DB, new_id
from middleware import auth_required
from response import success_response, list_response
from errors import (
    raise_error,
    ERR_INVALID_REQUEST, ERR_PLAN_NOT_ACTIVE, ERR_BATCH_NOT_OPEN,
    ERR_PENDING_GRANTS_EXIST, ERR_CROSS_RESOURCE_MISMATCH,
)
from services.common import (
    init_common, init_append_only, bump_version, check_occ, get_body,
    get_or_404, get_pagination, paginate_list, sort_by_created_at_asc,
    require_string, require_enum, require_positive_int,
)
from services.time_util import format_iso, parse_iso
from services.serializers import serialize_batch, serialize_price_version


bp = Blueprint("batches", __name__)

ALGORITHMS = {"ANNIVERSARY_BATCH", "CONTINUOUS_DAILY"}
PERIODS = {1, 3, 12}


@bp.post("/option-plans/<plan_id>/grant-batches")
@auth_required(["PlanAdministrator"])
def create_batch(plan_id):
    plan = get_or_404("option_plans", plan_id)
    body = get_body()
    label = require_string(body, "batch_label")

    cliff_months = body.get("cliff_months")
    if not isinstance(cliff_months, int) or isinstance(cliff_months, bool) or cliff_months < 0:
        raise_error(ERR_INVALID_REQUEST, "cliff_months must be non-negative integer")
    vtm = body.get("vesting_total_months")
    if not isinstance(vtm, int) or isinstance(vtm, bool) or vtm < 1:
        raise_error(ERR_INVALID_REQUEST, "vesting_total_months must be positive integer")
    vpm = body.get("vesting_period_months")
    if vpm not in PERIODS:
        raise_error(ERR_INVALID_REQUEST, "vesting_period_months must be 1, 3 or 12")
    algorithm = require_enum(body, "vesting_algorithm", ALGORITHMS)
    perf = body.get("performance_condition_required", False)
    if not isinstance(perf, bool):
        raise_error(ERR_INVALID_REQUEST, "performance_condition_required must be boolean")
    init_price = body.get("initial_price_per_option_cents")
    if not isinstance(init_price, int) or isinstance(init_price, bool) or init_price < 1:
        raise_error(ERR_INVALID_REQUEST, "initial_price_per_option_cents must be positive integer")

    # Unique-within-plan label
    for b in DB["grant_batches"].values():
        if b["plan_id"] == plan_id and b["batch_label"] == label:
            raise_error(ERR_INVALID_REQUEST, "batch_label must be unique within plan")

    bid = new_id()
    batch = {
        "id": bid,
        "plan_id": plan_id,
        "batch_label": label,
        "cliff_months": cliff_months,
        "vesting_total_months": vtm,
        "vesting_period_months": vpm,
        "vesting_algorithm": algorithm,
        "performance_condition_required": perf,
        "initial_price_per_option_cents": init_price,
        "status": "DRAFT",
    }
    init_common(batch)
    DB["grant_batches"][bid] = batch
    return success_response(serialize_batch(batch), http_status=201)


@bp.get("/option-plans/<plan_id>/grant-batches")
@auth_required(["PlanAdministrator", "BoardSecretary", "ShareholderRegistrar", "AuditViewer"])
def list_batches(plan_id):
    get_or_404("option_plans", plan_id)
    limit, offset = get_pagination()
    items = [b for b in DB["grant_batches"].values() if b["plan_id"] == plan_id]
    items = sort_by_created_at_asc(items)
    sliced, total = paginate_list(items, limit, offset)
    return list_response([serialize_batch(b) for b in sliced], total, limit, offset)


@bp.post("/option-plans/<plan_id>/grant-batches/<batch_id>/open")
@auth_required(["PlanAdministrator"])
def open_batch(plan_id, batch_id):
    plan = get_or_404("option_plans", plan_id)
    batch = get_or_404("grant_batches", batch_id)
    if batch["plan_id"] != plan_id:
        raise_error(ERR_CROSS_RESOURCE_MISMATCH, "Batch does not belong to plan")
    body = get_body()
    check_occ(batch, body)
    # state precondition: batch must be DRAFT
    if batch["status"] != "DRAFT":
        raise_error(ERR_BATCH_NOT_OPEN, "Batch not in DRAFT")
    # body-shape preconditions
    if batch["cliff_months"] > batch["vesting_total_months"]:
        raise_error(ERR_INVALID_REQUEST, "cliff_months > vesting_total_months")
    if batch["vesting_total_months"] % batch["vesting_period_months"] != 0:
        raise_error(ERR_INVALID_REQUEST, "vesting_total_months not divisible by vesting_period_months")
    if plan["status"] != "ACTIVE":
        raise_error(ERR_PLAN_NOT_ACTIVE, "Plan not ACTIVE")
    batch["status"] = "OPEN_FOR_GRANTS"
    bump_version(batch)
    # Create initial price version v1
    vid = new_id()
    version = {
        "id": vid,
        "plan_id": plan_id,
        "batch_id": batch_id,
        "version_index": 1,
        "parent_version_id": None,
        "cause": "INITIAL",
        "corporate_event_id": None,
        "price_per_option_cents": batch["initial_price_per_option_cents"],
        "effective_from_ts": plan.get("current_clock_ts"),
        "disclosed_at": None,
    }
    init_append_only(version)
    DB["exercise_price_versions"][vid] = version
    return success_response(serialize_batch(batch))


@bp.post("/option-plans/<plan_id>/grant-batches/<batch_id>/lock")
@auth_required(["PlanAdministrator"])
def lock_batch(plan_id, batch_id):
    get_or_404("option_plans", plan_id)
    batch = get_or_404("grant_batches", batch_id)
    if batch["plan_id"] != plan_id:
        raise_error(ERR_CROSS_RESOURCE_MISMATCH, "Batch does not belong to plan")
    body = get_body()
    check_occ(batch, body)
    if batch["status"] != "OPEN_FOR_GRANTS":
        raise_error(ERR_BATCH_NOT_OPEN, "Batch not in OPEN_FOR_GRANTS")
    pending_grant_states = {"DRAFT", "BOARD_APPROVED", "SHAREHOLDER_APPROVED"}
    for g in DB["grants"].values():
        if g["batch_id"] == batch_id and g["status"] in pending_grant_states:
            raise_error(ERR_PENDING_GRANTS_EXIST, "Batch has pending grants")
    batch["status"] = "LOCKED"
    bump_version(batch)
    return success_response(serialize_batch(batch))


@bp.get("/grant-batches/<batch_id>/exercise-price-versions")
@auth_required(["PlanAdministrator", "Grantee", "AuditViewer"])
def list_price_versions(batch_id):
    get_or_404("grant_batches", batch_id)
    items = [v for v in DB["exercise_price_versions"].values() if v["batch_id"] == batch_id]
    items.sort(key=lambda v: v["version_index"])
    limit, offset = get_pagination()
    total = len(items)
    sliced = items[offset:offset + limit]
    from response import list_response as _lr
    return _lr([serialize_price_version(v) for v in sliced], total, limit, offset)


@bp.post("/exercise-price-versions/<version_id>/disclose")
@auth_required(["PlanAdministrator"])
def disclose_version(version_id):
    v = get_or_404("exercise_price_versions", version_id)
    plan = get_or_404("option_plans", v["plan_id"])
    v["disclosed_at"] = plan.get("current_clock_ts")
    from services.audit import append_audit
    append_audit(plan, "PRICE_VERSION_CREATED", "ExercisePriceVersion", version_id,
                 {"action": "disclose", "version_id": version_id})
    return success_response(serialize_price_version(v))
