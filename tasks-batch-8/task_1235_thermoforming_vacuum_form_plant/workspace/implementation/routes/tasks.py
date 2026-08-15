"""AssemblyTask endpoints (PRD §3.8)."""

from flask import request

from db import STORE, new_record, bump
from errors import ApiError
from middleware import endpoint, ANY_ROLE
from response import ok_object, list_response
from serializers import ser_task
from services import get_order, get_spec, get_task
from util import (
    as_enum,
    as_positive_int,
    as_string,
    body_dict,
    opt_present,
    req_present,
)

from routes import bp

TASK_TYPES = {"TRIM", "INSERT", "BOND", "PACK"}


@bp.route("/assembly-tasks", methods=["POST"])
@endpoint({"ProductionScheduler"})
def create_task(user_id, role):
    body = body_dict(request.get_json(silent=True))
    order_id = as_string(req_present(body, "production_order_id"), "production_order_id")
    task_type = as_enum(req_present(body, "task_type"), "task_type", TASK_TYPES)
    sequence_no = as_positive_int(req_present(body, "sequence_no"), "sequence_no")
    # Conditional field: insert_part_code iff INSERT
    insert_part_code = opt_present(body, "insert_part_code")
    if task_type == "INSERT":
        if insert_part_code is None:
            raise ApiError(
                "ERR_INVALID_REQUEST", "insert_part_code is required when task_type is INSERT"
            )
        insert_part_code = as_string(insert_part_code, "insert_part_code")
    else:
        if insert_part_code is not None:
            raise ApiError(
                "ERR_INVALID_REQUEST", "insert_part_code must be null for non-INSERT tasks"
            )

    order = get_order(order_id)

    rec = new_record()
    rec.update({
        "production_order_id": order["id"],
        "task_type": task_type,
        "sequence_no": sequence_no,
        "insert_part_code": insert_part_code,
        "status": "PENDING",
    })
    STORE["assembly_tasks"][rec["id"]] = rec
    return ok_object(ser_task(rec), 201)


@bp.route("/assembly-tasks", methods=["GET"])
@endpoint(ANY_ROLE)
def list_tasks(user_id, role):
    items = list(STORE["assembly_tasks"].values())
    order_id = request.args.get("production_order_id")
    if order_id is not None:
        items = [t for t in items if t["production_order_id"] == order_id]
    status = request.args.get("status")
    if status is not None:
        items = [t for t in items if t["status"] == status]
    return list_response(items, ser_task)


@bp.route("/assembly-tasks/<taskId>", methods=["GET"])
@endpoint(ANY_ROLE)
def get_one_task(user_id, role, taskId):
    return ok_object(ser_task(get_task(taskId)))


@bp.route("/assembly-tasks/<taskId>/complete", methods=["POST"])
@endpoint({"ProductionScheduler"})
def complete_task(user_id, role, taskId):
    task = get_task(taskId)
    if task["status"] != "PENDING":
        raise ApiError("ERR_INVALID_TASK_STATE", "Task complete requires status PENDING")
    order = get_order(task["production_order_id"])
    if order["schedule_status"] not in ("RUNNING", "ON_HOLD", "COMPLETED"):
        raise ApiError(
            "ERR_INVALID_ORDER_STATE",
            "Task complete requires order schedule_status RUNNING, ON_HOLD, or COMPLETED",
        )
    # Every lower-sequence task of the same order must be COMPLETED
    for other in STORE["assembly_tasks"].values():
        if (
            other["production_order_id"] == order["id"]
            and other["sequence_no"] < task["sequence_no"]
            and other["status"] != "COMPLETED"
        ):
            raise ApiError(
                "ERR_ASSEMBLY_SEQUENCE_VIOLATION",
                "A lower-sequence task of this order is not COMPLETED",
            )
    if task["task_type"] == "PACK":
        if order["quality_status"] != "RELEASED":
            raise ApiError(
                "ERR_ORDER_QUALITY_NOT_RELEASED", "PACK requires order quality_status RELEASED"
            )
        spec = get_spec(order["packaging_spec_id"])
        if spec["status"] not in ("ACTIVE", "APPROVED"):
            raise ApiError(
                "ERR_PACK_SPEC_NOT_APPROVED", "PACK requires packaging spec ACTIVE or APPROVED"
            )
    task["status"] = "COMPLETED"
    bump(task)
    return ok_object(ser_task(task))
