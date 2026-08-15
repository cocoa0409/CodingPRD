"""WasteLog (PRD 3.8) and the test clock (PRD 2.5)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error, ERR_VALIDATION, ERR_REFERENCE_INVALID, ERR_SAFETY_VIOLATION,
    ERR_CAPACITY_FULL,
)
from helpers import (
    get_body, req_field, req_int, req_enum, get_or_404, new_id, now_ts,
)
from middleware import get_caller, check_role_allowed
from response import success_object
from routes.common import public
from services import core
from util import CLOCK

bp = Blueprint("waste_logs", __name__)

REASONS = {"OVERPRODUCTION", "SPOILAGE", "SAFETY_DISCARD", "PACKAGING_DAMAGE"}
DISPOSITIONS = {"DISCARD", "COMPOST", "RESCUE_REDIRECT"}


@bp.route("/kitchen/waste-logs", methods=["POST"])
def create_waste_log():
    body = get_body()
    caller = get_caller()
    check_role_allowed(caller, ["KitchenManager", "FoodSafetyOfficer"])

    menu_day_id = req_field(body, "menu_day_id", str)
    food_batch_id = req_field(body, "food_batch_id", str)
    servings_wasted = req_int(body, "servings_wasted", minimum=1)
    reason = req_enum(body, "reason", REASONS)
    disposition = req_enum(body, "disposition", DISPOSITIONS)

    md = db["menu_days"].get(menu_day_id)
    if md is None:
        raise_error(ERR_REFERENCE_INVALID, f"menu day not found: {menu_day_id}")
    batch = db["food_batches"].get(food_batch_id)
    if batch is None:
        raise_error(ERR_REFERENCE_INVALID, f"food batch not found: {food_batch_id}")

    # SAFETY_DISCARD restricted to QUARANTINED or expired batches.
    if reason == "SAFETY_DISCARD":
        expired = not core.batch_not_expired(batch)
        if batch["status"] != "QUARANTINED" and not expired:
            raise_error(ERR_SAFETY_VIOLATION,
                        "SAFETY_DISCARD requires the batch to be QUARANTINED or expired")

    # Conservation ceiling: cannot waste more than remains.
    if servings_wasted > batch["remaining_servings"]:
        raise_error(ERR_CAPACITY_FULL,
                    "servings_wasted exceeds batch remaining_servings")

    rec = {
        "id": new_id(),
        "menu_day_id": menu_day_id,
        "food_batch_id": food_batch_id,
        "servings_wasted": servings_wasted,
        "reason": reason,
        "disposition": disposition,
        "logged_at": now_ts(),
        "created_at": now_ts(),
    }
    db["waste_logs"][rec["id"]] = rec

    core.recalc_batch_remaining(batch)
    return success_object(public(rec), 201)


@bp.route("/kitchen/waste-logs/<wid>", methods=["GET"])
def get_waste_log(wid):
    caller = get_caller()
    check_role_allowed(caller, ["ProgramAdmin", "KitchenManager", "FoodSafetyOfficer"])
    rec = get_or_404("waste_logs", wid)
    return success_object(public(rec))
