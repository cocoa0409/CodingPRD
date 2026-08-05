"""The activity/equipment catalogue, loans, fulfilment and return."""

from flask import Blueprint, request

import calc
import config
import lookup
import serialize
from auth import authenticate
from envelope import created, ok, paginate, pagination
from errors import ApiError
from store import base_row, db, now, now_iso, ordered, touch
from validate import filter_enum, json_body

bp = Blueprint("kits", __name__)
P = config.API_PREFIX


@bp.post(P + "/kit-items")
def create_kit_item():
    authenticate([config.ROLE_CLINIC_ADMIN])
    b = json_body()
    name = b.str_req("name")
    b.enum_shape_req("item_class")
    replacement_cost = b.num_req("replacement_cost")
    useful_life_months = b.int_req("useful_life_months", minimum=1)
    in_service_date = b.date_req("in_service_date")
    initial_qty = b.int_req("initial_qty")
    item_class = b.enum_req("item_class", config.ITEM_CLASSES)

    row = base_row()
    row.update({
        "name": name,
        "item_class": item_class,
        "replacement_cost": calc.f2(replacement_cost),
        "useful_life_months": useful_life_months,
        "in_service_date": in_service_date,
        "initial_qty": initial_qty,
        "on_hand_qty": initial_qty,
        "on_loan_qty": 0,
        "dispensed_qty": 0,
        "retired_qty": 0,
    })
    db.kit_items[row["id"]] = row
    return created(serialize.kit_item(row))


@bp.get(P + "/kit-items/<id>")
def get_kit_item(id):
    authenticate(config.READ_ROLES)
    return ok(serialize.kit_item(lookup.kit_item_or_404(id)))


@bp.post(P + "/kit-loans")
def create_kit_loan():
    authenticate([config.ROLE_FRONT_DESK, config.ROLE_VISION_THERAPIST])
    b = json_body()
    kit_item_id = b.str_req("kit_item_id")
    patient_id = b.str_req("patient_id")
    plan_id = b.str_req("plan_id")
    quantity = b.int_req("quantity", non_negative=True)

    lookup.patient_or_404(patient_id)                                      # rung 5
    plan = lookup.plan_or_404(plan_id)                                     # rung 8
    lookup.kit_item_or_404(kit_item_id)                                    # rung 11
    lookup.gate_for_patient_id(patient_id)                                 # rung 12
    if plan["status"] != "ACTIVE":                                         # rung 15
        raise ApiError("ERR_PLAN_NOT_ACTIVE")

    row = base_row()
    row.update({
        "kit_item_id": kit_item_id,
        "patient_id": patient_id,
        "plan_id": plan_id,
        "quantity": quantity,
        "status": "REQUESTED",
        "checked_out_at": None,
        "due_at": None,
        "returned_at": None,
        "returned_condition": None,
        "damage_fee_amount": 0.0,
        "recall_due_at": None,
        "recalled_at": None,
        "issued_by_user_id": None,
    })
    db.kit_loans[row["id"]] = row
    return created(serialize.kit_loan(row))


@bp.get(P + "/kit-loans/<id>")
def get_kit_loan(id):
    authenticate(config.READ_ROLES)
    return ok(serialize.kit_loan(lookup.kit_loan_or_404(id)))


@bp.get(P + "/kit-loans")
def list_kit_loans():
    authenticate(config.READ_ROLES)
    limit, offset = pagination(request.args)
    status = filter_enum(request.args, "status", config.LOAN_STATUSES)
    kit_item_id = request.args.get("kit_item_id")
    patient_id = request.args.get("patient_id")
    plan_id = request.args.get("plan_id")

    def match(row):
        if kit_item_id and row["kit_item_id"] != kit_item_id:
            return False
        if patient_id and row["patient_id"] != patient_id:
            return False
        if plan_id and row["plan_id"] != plan_id:
            return False
        if status and row["status"] != status:
            return False
        return True

    return paginate(ordered(db.kit_loans, match), limit, offset, serialize.kit_loan)


@bp.post(P + "/kit-loans/<id>/fulfill")
def fulfill_kit_loan(id):
    caller = authenticate([config.ROLE_FRONT_DESK, config.ROLE_VISION_THERAPIST])
    b = json_body()
    due_at = b.instant_opt("due_at")
    loan = lookup.kit_loan_or_404(id)                                      # rung 11
    item = lookup.kit_item_or_404(loan["kit_item_id"])
    lookup.gate_for_patient_id(loan["patient_id"])                         # rung 12
    if loan["status"] != "REQUESTED":                                      # rung 14
        raise ApiError("ERR_INVALID_STATE", "Only a REQUESTED loan may be fulfilled.")

    # rung 28: stock availability, and the serialized-item quantity rule -- the
    # PRD describes the quantity==1 rule at creation but enforces it here.
    if item["on_hand_qty"] < loan["quantity"]:
        raise ApiError("ERR_KIT_STOCK_DEPLETED")
    if item["item_class"] == "LOANABLE_SERIALIZED" and loan["quantity"] != 1:
        raise ApiError("ERR_KIT_STOCK_DEPLETED")

    quantity = loan["quantity"]
    if item["item_class"] == "LOANABLE_SERIALIZED":
        loan["status"] = "CHECKED_OUT"
        item["on_hand_qty"] -= quantity
        item["on_loan_qty"] += quantity
    else:
        loan["status"] = "DISPENSED"
        item["on_hand_qty"] -= quantity
        item["dispensed_qty"] += quantity
    loan["checked_out_at"] = now_iso()
    loan["issued_by_user_id"] = caller.user_id
    if due_at is not None:
        loan["due_at"] = due_at
    touch(loan)
    touch(item)
    return ok(serialize.kit_loan(loan))


@bp.post(P + "/kit-loans/<id>/return")
def return_kit_loan(id):
    authenticate([config.ROLE_FRONT_DESK, config.ROLE_VISION_THERAPIST])
    b = json_body()
    b.enum_shape_req("returned_condition")                                 # rung 3
    condition = b.enum_req("returned_condition", config.RETURNED_CONDITIONS)  # rung 4
    loan = lookup.kit_loan_or_404(id)                                      # rung 11
    item = lookup.kit_item_or_404(loan["kit_item_id"])
    # OUTSIDE the clinical write gate (PRD §2.8) so equipment can still be
    # recovered from a discharged patient.
    if loan["status"] not in ("CHECKED_OUT", "RECALLED", "REQUESTED"):     # rung 14
        raise ApiError("ERR_INVALID_STATE", "This loan cannot be returned from its current state.")

    loan["returned_condition"] = condition
    loan["returned_at"] = now_iso()

    if loan["status"] == "REQUESTED":
        # A withdrawal rather than a return: nothing ever left the shelf.
        loan["status"] = "CANCELLED"
        touch(loan)
        return ok(serialize.kit_loan(loan))

    quantity = loan["quantity"]
    loan["status"] = "RETURNED"
    loan["damage_fee_amount"] = calc.kit_damage_fee(item, condition, now().date())
    item["on_loan_qty"] -= quantity
    if condition == "LOST":
        item["retired_qty"] += quantity
    else:
        item["on_hand_qty"] += quantity
    touch(loan)
    touch(item)
    return ok(serialize.kit_loan(loan))
