"""The loss-reason taxonomy (PRD 3.6)."""
from flask import Blueprint

from db import db, new_row, touch
from errors import fail
from middleware import ANY_ROLE, endpoint
from response import list_response, object_response
from validate import (REASON_STATUS, body, fk_from_body, fk_from_query, opt_str,
                      paginate, pagination, present, query_bool, query_enum,
                      query_int, req_str, resolve)

from services import calc, serialize
from services.listing import by_created_at

bp = Blueprint("loss_reasons", __name__)

MAX_DEPTH = 3


def get_reason(reason_id):
    return resolve(db.loss_reasons, reason_id, "ERR_LOSS_REASON_NOT_FOUND")


def _recompute_subtree_depths(reason):
    reason["depth"] = calc.compute_depth(reason)
    stack = list(calc.children_of_reason(reason["id"]))
    while stack:
        node = stack.pop()
        new_depth = calc.compute_depth(node)
        if node["depth"] != new_depth:
            node["depth"] = new_depth
            touch(node)
        stack.extend(calc.children_of_reason(node["id"]))


@bp.post("/loss-reasons")
@endpoint(("ProgramAdmin",))
def create_reason():
    payload = body()
    program = fk_from_body(payload, "program_id", db.programs, "ERR_PROGRAM_NOT_FOUND")
    parent = fk_from_body(payload, "parent_reason_id", db.loss_reasons,
                          "ERR_LOSS_REASON_NOT_FOUND")
    program_id = req_str(payload, "program_id")
    code = req_str(payload, "code")
    label = req_str(payload, "label")
    parent_id = opt_str(payload, "parent_reason_id")
    if program is None:
        fail("ERR_PROGRAM_NOT_FOUND")

    for existing in db.loss_reasons.values():
        if existing["program_id"] == program_id and \
                existing["code"].lower() == code.lower():
            fail("ERR_DUPLICATE_RESOURCE_KEY",
                 "That code already exists in the program's taxonomy.")

    depth = 1 if parent is None else parent["depth"] + 1
    if depth > MAX_DEPTH:
        fail("ERR_TAXONOMY_DEPTH_EXCEEDED",
             "The taxonomy may not exceed three levels.")

    reason = new_row({
        "program_id": program_id,
        "parent_reason_id": parent_id if parent is not None else None,
        "code": code,
        "label": label,
        "depth": depth,
        "status": "ACTIVE",
    })
    db.loss_reasons[reason["id"]] = reason
    if parent is not None:
        # the parent's is_leaf flips to false, which bars it from new attributions
        touch(parent)
    return object_response(serialize.loss_reason(reason), 201)


@bp.get("/loss-reasons/<reason_id>")
@endpoint(ANY_ROLE)
def read_reason(reason_id):
    return object_response(serialize.loss_reason(get_reason(reason_id)))


@bp.get("/loss-reasons")
@endpoint(ANY_ROLE)
def list_reasons():
    program_id = fk_from_query("program_id", db.programs, "ERR_PROGRAM_NOT_FOUND")
    parent_id = fk_from_query("parent_reason_id", db.loss_reasons,
                              "ERR_LOSS_REASON_NOT_FOUND")
    status = query_enum("status", REASON_STATUS)
    is_leaf = query_bool("is_leaf")
    depth = query_int("depth")
    limit, offset = pagination()
    rows = list(db.loss_reasons.values())
    if program_id:
        rows = [r for r in rows if r["program_id"] == program_id]
    if parent_id:
        rows = [r for r in rows if r.get("parent_reason_id") == parent_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    if is_leaf is not None:
        rows = [r for r in rows if calc.is_leaf(r) == is_leaf]
    if depth is not None:
        rows = [r for r in rows if r["depth"] == depth]
    rows = sorted(by_created_at(rows), key=lambda r: (r["depth"], r["code"]))
    page, total = paginate(rows, limit, offset)
    return list_response([serialize.loss_reason(r) for r in page],
                         limit, offset, total)


@bp.patch("/loss-reasons/<reason_id>")
@endpoint(("ProgramAdmin",))
def amend_reason(reason_id):
    reason = get_reason(reason_id)
    payload = body()
    parent = fk_from_body(payload, "parent_reason_id", db.loss_reasons,
                          "ERR_LOSS_REASON_NOT_FOUND")
    label = None
    if present(payload, "label"):
        label = req_str(payload, "label")
    parent_supplied = "parent_reason_id" in payload
    parent_id = None
    if parent_supplied and payload["parent_reason_id"] is not None:
        parent_id = req_str(payload, "parent_reason_id")

    old_parent = db.loss_reasons.get(reason.get("parent_reason_id"))

    if parent_supplied:
        new_depth = 1 if parent is None else parent["depth"] + 1
        if new_depth > MAX_DEPTH:
            fail("ERR_TAXONOMY_DEPTH_EXCEEDED",
                 "The taxonomy may not exceed three levels.")
        if parent is not None:
            forbidden = {reason["id"]}
            forbidden.update(d["id"] for d in calc.descendants_of_reason(reason["id"]))
            if parent["id"] in forbidden:
                fail("ERR_TAXONOMY_CYCLE",
                     "A node may not be parented to itself or a descendant.")
        height = calc.subtree_height(reason["id"])
        if new_depth + height - 1 > MAX_DEPTH:
            fail("ERR_TAXONOMY_DEPTH_EXCEEDED",
                 "The taxonomy may not exceed three levels.")

    if label is not None:
        reason["label"] = label
    if parent_supplied:
        reason["parent_reason_id"] = parent_id
        _recompute_subtree_depths(reason)
    touch(reason)
    if parent_supplied:
        if old_parent is not None and old_parent["id"] != reason["id"]:
            touch(old_parent)
        if parent is not None and parent["id"] != reason["id"] and \
                (old_parent is None or parent["id"] != old_parent["id"]):
            touch(parent)
    return object_response(serialize.loss_reason(reason))


@bp.post("/loss-reasons/<reason_id>/deprecate")
@endpoint(("ProgramAdmin",))
def deprecate_reason(reason_id):
    reason = get_reason(reason_id)
    reason["status"] = "DEPRECATED"
    touch(reason)
    return object_response(serialize.loss_reason(reason))
