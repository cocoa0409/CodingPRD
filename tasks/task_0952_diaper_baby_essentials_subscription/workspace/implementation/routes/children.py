"""Children, the size ladder and sensitivity screening (PRD 3.2)."""

from flask import Blueprint

import calc
import constants as C
import serialize
import services
import shapes
import store
from auth import (api, get_account, get_child, lookup, require_account_owner)
from envelope import ok, created, paginate
from errors import ApiError
from store import db, now, touch

bp = Blueprint("children", __name__)


def body_fk(data, name, collection, type_name):
    """Gate G3 rung 7 — body foreign keys, checked BEFORE the shape gate."""
    if name in data and data[name] is not None:
        return lookup(collection, data[name], type_name)
    return None


@api(bp, "POST", "/children", ["AccountHolder", "OpsAdmin"])
def create_child():
    data = shapes.body()
    body_fk(data, "account_id", db.accounts, "Account")
    parsed = shapes.validate(data, [
        shapes.field("account_id", required=True, kind="string"),
        shapes.field("name", required=True, kind="string"),
        shapes.field("birth_date", required=True, kind="date"),
        shapes.field("weight_grams", required=True, kind="int",
                     lo=C.WEIGHT_MIN_G, hi=C.WEIGHT_MAX_G),
        shapes.field("stage_pinned", kind="bool", default=False),
        shapes.field("hypoallergenic_required", kind="bool", default=False),
    ])
    require_account_owner(parsed["account_id"])

    row = store.base_row(full=True)
    row.update({
        "account_id": parsed["account_id"],
        "name": parsed["name"],
        "birth_date": store.parse_date(parsed["birth_date"]),
        "weight_grams": parsed["weight_grams"],
        # At creation the stage is simply the band the weight falls into,
        # with no clamping.
        "stage": calc.raw_stage(parsed["weight_grams"]),
        "stage_pinned": bool(parsed["stage_pinned"]),
        "hypoallergenic_required": bool(parsed["hypoallergenic_required"]),
        "archived": False,
    })
    db.children[row["id"]] = row
    return created(serialize.child(row))


@api(bp, "GET", "/children/<id>",
     ["AccountHolder", "RegistryOwner", "SupportAgent", "OpsAdmin"])
def read_child(id):
    return ok(serialize.child(get_child(id)))


@api(bp, "GET", "/children",
     ["AccountHolder", "RegistryOwner", "SupportAgent", "OpsAdmin"])
def list_children():
    account_id = shapes.qs("account_id")
    stage = shapes.qs("stage")
    rows = [r for r in db.children.values()
            if shapes.match(r, "account_id", account_id)
            and shapes.match(r, "stage", stage)]
    return paginate(rows, serialize.child)


@api(bp, "PATCH", "/children/<id>", ["AccountHolder"])
def update_child(id):
    child = get_child(id)
    parsed = shapes.validate(shapes.body(), [
        shapes.field("name", kind="string"),
        shapes.field("stage", kind="enum", members=C.STAGE_ORDER),
        shapes.field("stage_pinned", kind="bool"),
        shapes.field("hypoallergenic_required", kind="bool"),
    ])
    require_account_owner(child["account_id"])
    if shapes.supplied(parsed, "name"):
        child["name"] = parsed["name"]
    if shapes.supplied(parsed, "stage"):
        child["stage"] = parsed["stage"]
    if shapes.supplied(parsed, "stage_pinned"):
        child["stage_pinned"] = bool(parsed["stage_pinned"])
    if shapes.supplied(parsed, "hypoallergenic_required"):
        child["hypoallergenic_required"] = bool(parsed["hypoallergenic_required"])
    touch(child)
    return ok(serialize.child(child))


@api(bp, "POST", "/children/<id>/weight-measurements",
     ["AccountHolder", "OpsAdmin"])
def record_weight(id):
    child = get_child(id)
    parsed = shapes.validate(shapes.body(), [
        shapes.field("weight_grams", required=True, kind="int",
                     lo=C.WEIGHT_MIN_G, hi=C.WEIGHT_MAX_G),
    ])
    require_account_owner(child["account_id"])
    if child["archived"]:
        raise ApiError("ERR_CHILD_ARCHIVED")

    weight = parsed["weight_grams"]
    from_stage = child["stage"]
    to_stage = calc.clamped_stage(from_stage, weight)

    if to_stage == from_stage:
        # A measurement that would not change the stage never consults the cap.
        child["weight_grams"] = weight
        touch(child)
        return ok(serialize.child(child))

    sub = services.resize_subscription_for_child(child)

    if child["stage_pinned"]:
        # A pinned stage is a customer preference: the weight IS recorded, the
        # call succeeds, and the ResizeEvent is written REJECTED.
        child["weight_grams"] = weight
        touch(child)
        services.write_resize_event(
            sub, child, "AUTO", from_stage, to_stage, "REJECTED", None, weight,
            reject_reason="STAGE_PINNED")
        return ok(serialize.child(child))

    if sub is not None:
        used = services.auto_resize_count_in_period(sub["id"])
        if used >= C.AUTO_RESIZE_CAP_PER_PERIOD:
            # An exhausted cap is a policy limit: the WHOLE request is rejected.
            raise ApiError("ERR_RESIZE_CAP_EXCEEDED")

    child["weight_grams"] = weight
    child["stage"] = to_stage
    touch(child)

    if sub is not None:
        status, target_id, current = services.resize_target_cycle(sub)
        services.write_resize_event(sub, child, "AUTO", from_stage, to_stage,
                                    status, target_id, weight)
        if status == "APPLIED_CURRENT" and current is not None:
            services.reallocate_cycle(current)
    return ok(serialize.child(child))


@api(bp, "POST", "/children/<id>/allergen-flags",
     ["AccountHolder", "SupportAgent"])
def add_allergen_flag(id):
    child = get_child(id)
    parsed = shapes.validate(shapes.body(), [
        shapes.field("allergen_tag", required=True, kind="enum",
                     members=C.ALLERGEN_TAGS),
        shapes.field("severity", required=True, kind="enum", members=C.SEVERITIES),
        shapes.field("note", kind="string", default=None),
    ])
    require_account_owner(child["account_id"])
    if child["archived"]:
        raise ApiError("ERR_CHILD_ARCHIVED")

    row = store.base_row(full=False)
    row.update({
        "child_id": child["id"],
        "allergen_tag": parsed["allergen_tag"],
        "severity": parsed["severity"],
        "note": parsed["note"],
    })
    db.allergen_flags[row["id"]] = row
    # HOP 2 of the depth-5 cascade.
    services.rescreen_lines_for_child(child, "ALLERGEN_RESCREEN")
    return created(serialize.allergen_flag(row))


@api(bp, "GET", "/allergen-flags/<id>",
     ["AccountHolder", "SupportAgent", "OpsAdmin"])
def read_allergen_flag(id):
    return ok(serialize.allergen_flag(
        lookup(db.allergen_flags, id, "AllergenFlag")))


@api(bp, "GET", "/allergen-flags",
     ["AccountHolder", "SupportAgent", "OpsAdmin"])
def list_allergen_flags():
    child_id = shapes.qs("child_id")
    severity = shapes.qs("severity")
    rows = [r for r in db.allergen_flags.values()
            if shapes.match(r, "child_id", child_id)
            and shapes.match(r, "severity", severity)]
    return paginate(rows, serialize.allergen_flag)


@api(bp, "DELETE", "/allergen-flags/<id>", ["AccountHolder", "SupportAgent"])
def delete_allergen_flag(id):
    flag = lookup(db.allergen_flags, id, "AllergenFlag")
    child = db.children.get(flag["child_id"])
    if child is not None:
        require_account_owner(child["account_id"])
    payload = serialize.allergen_flag(flag)
    db.allergen_flags.pop(flag["id"], None)
    # Deliberately one-way: an already-substituted line is NOT reverted.
    return ok(payload)
