"""CleaningTask endpoints: create, list, START/QA_PASS/QA_FAIL/REWORK."""

from flask import Blueprint

from db import store
from errors import (
    validation,
    invalid_transition,
    item_not_salvageable,
    specialty_required,
    item_terminal,
)
from helpers import (
    get_body,
    require_enum,
    optional_string,
    make_common_fields,
    get_item,
    get_cleaning_task,
    touch,
)
from middleware import require_roles
from response import success_object, success
from services.recompute import recompute_room

bp = Blueprint("cleaning", __name__)

PROCESS_CODE_BY_CATEGORY = {
    "TEXTILE": "LAUNDER_DEODORIZE",
    "ELECTRONICS": "DRY_CORROSION_INHIBIT",
    "FURNITURE": "SURFACE_CLEAN",
    "DOCUMENT": "FREEZE_DRY",
    "APPLIANCE": "DEEP_CLEAN",
    "GENERAL": "STANDARD_CLEAN",
}
CLEANING_ACTIONS = {"START", "QA_PASS", "QA_FAIL", "REWORK"}
CLEANING_BASE_CENTS = 12000
DEODORIZATION_ADDER_CENTS = 4000
TERMINAL_ITEM_STATUSES = {"DISPOSED", "DELIVERED", "CLAIM_SETTLED"}


def serialize_task(task):
    return dict(task)


@bp.route("/api/items/<item_id>/cleaning-tasks", methods=["POST"])
def create_cleaning_task(item_id):
    user_id, role = require_roles("InventoryTechnician")
    item = get_item(item_id)
    if item["processing_status"] in TERMINAL_ITEM_STATUSES:
        raise item_terminal()
    if item["condition_triage"] != "SALVAGEABLE":
        raise item_not_salvageable()
    if item["item_category"] == "ARTWORK":
        raise specialty_required("ARTWORK items never receive a CleaningTask")
    task = make_common_fields()
    task.update({
        "item_id": item["id"],
        "process_code": PROCESS_CODE_BY_CATEGORY[item["item_category"]],
        "deodorization_required": bool(item["smoke_damage_flag"]),
        "status": "SCHEDULED",
        "rework_count": 0,
        "fee_cents": None,
        "qa_note": None,
    })
    store.cleaning_tasks[task["id"]] = task
    return success_object(serialize_task(task), status=201)


@bp.route("/api/items/<item_id>/cleaning-tasks", methods=["GET"])
def list_cleaning_tasks(item_id):
    user_id, role = require_roles("ProjectManager", "InventoryTechnician")
    item = get_item(item_id)
    tasks = [t for t in store.cleaning_tasks.values() if t["item_id"] == item["id"]]
    tasks.sort(key=lambda t: t["created_at"])
    return success([serialize_task(t) for t in tasks], status=200, response_type="array")


@bp.route("/api/cleaning-tasks/<task_id>/transition", methods=["POST"])
def transition_cleaning_task(task_id):
    user_id, role = require_roles("InventoryTechnician")
    body = get_body()
    action = require_enum(body, "action", CLEANING_ACTIONS)
    qa_note = optional_string(body, "qa_note")
    task = get_cleaning_task(task_id)
    item = store.items.get(task["item_id"])

    if action == "START":
        if task["status"] != "SCHEDULED":
            raise invalid_transition("CleaningTask is not SCHEDULED")
        if item is None or item["processing_status"] != "AWAITING_CLEANING":
            raise invalid_transition("Item is not AWAITING_CLEANING")
        task["status"] = "IN_PROGRESS"
        if qa_note is not None:
            task["qa_note"] = qa_note
        touch(task)
        item["processing_status"] = "IN_CLEANING"
        touch(item)
    elif action == "QA_PASS":
        if task["status"] != "IN_PROGRESS":
            raise invalid_transition("CleaningTask is not IN_PROGRESS")
        fee = CLEANING_BASE_CENTS
        if task["deodorization_required"]:
            fee += DEODORIZATION_ADDER_CENTS
        task["fee_cents"] = fee
        if qa_note is not None:
            task["qa_note"] = qa_note
        task["status"] = "PASSED"
        touch(task)
        if item is not None:
            item["processing_status"] = "CLEANED"
            touch(item)
    elif action == "QA_FAIL":
        if task["status"] != "IN_PROGRESS":
            raise invalid_transition("CleaningTask is not IN_PROGRESS")
        if qa_note is not None:
            task["qa_note"] = qa_note
        task["status"] = "FAILED"
        touch(task)
        # item stays IN_CLEANING
    elif action == "REWORK":
        if task["status"] != "FAILED":
            raise invalid_transition("CleaningTask is not FAILED")
        task["status"] = "IN_PROGRESS"
        task["rework_count"] += 1
        if qa_note is not None:
            task["qa_note"] = qa_note
        touch(task)

    if item is not None:
        room = store.rooms.get(item["room_id"])
        if room is not None:
            recompute_room(room)
            touch(room)
    return success_object(serialize_task(task))
