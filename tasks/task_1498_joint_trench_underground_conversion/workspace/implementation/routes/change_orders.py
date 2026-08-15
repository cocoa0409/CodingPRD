"""ChangeOrder endpoints: create, price/approve/incorporate (freeze + cost/LD
cascade), revise, reject, withdraw."""

from __future__ import annotations

from flask import Blueprint

import db
from db import touch, stamp_new
from errors import raise_err, ERR_VALIDATION, ERR_INVALID_STATE
from middleware import require_roles
from response import success_object, success_list
from services import domain
from services.serializers import change_order_view
from util import (
    get_json_body,
    get_or_404,
    is_int,
    parse_pagination,
    paginate,
    query_arg,
    require_enum,
    require_field,
    require_id_array,
    require_string,
    sort_created,
)

bp = Blueprint("change_orders", __name__, url_prefix="/api/change-orders")

PM = "ProgramManager"
ANY = "Any"

DELAY_CAUSES = {"EXCUSABLE", "NEGLIGENT", "MIXED"}
TRANSITION_TARGETS = {"PRICED", "PROPOSED", "APPROVED", "INCORPORATED",
                      "REJECTED", "WITHDRAWN"}


@bp.route("", methods=["POST"])
@require_roles(PM)
def create_change_order(_user_id: str, _role: str):
    body = get_json_body()
    if body.get("project_id") is not None:
        get_or_404(db.projects, body["project_id"], "Project")
    project_id = require_string(body, "project_id")
    description = require_string(body, "description")
    segment_ids = require_id_array(body, "segment_ids", default=[])
    for sid in segment_ids:
        get_or_404(db.segments, sid, "TrenchSegment")

    order = stamp_new({
        "project_id": project_id,
        "description": description,
        "segment_ids": list(segment_ids),
        "delta_cost_cents": None,
        "delta_delay_days": None,
        "delay_cause": None,
        "status": "PROPOSED",
        "revision_count": 0,
    })
    db.change_orders[order["id"]] = order
    return success_object(change_order_view(order), 201)


@bp.route("", methods=["GET"])
@require_roles(ANY)
def list_change_orders(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = list(db.change_orders.values())
    project_id = query_arg("project_id")
    status = query_arg("status")
    segment_id = query_arg("segment_ids")
    if project_id:
        items = [c for c in items if c["project_id"] == project_id]
    if status:
        items = [c for c in items if c["status"] == status]
    if segment_id:
        items = [c for c in items if segment_id in (c.get("segment_ids") or [])]
    items = sort_created(items)
    page, total = paginate(items, limit, offset)
    return success_list([change_order_view(c) for c in page], limit, offset, total)


@bp.route("/<cid>", methods=["GET"])
@require_roles(ANY)
def get_change_order(cid: str, _user_id: str, _role: str):
    return success_object(change_order_view(get_or_404(db.change_orders, cid,
                                                       "ChangeOrder")))


@bp.route("/<cid>/transition", methods=["POST"])
@require_roles(PM)
def transition_change_order(cid: str, _user_id: str, _role: str):
    order = get_or_404(db.change_orders, cid, "ChangeOrder")
    body = get_json_body()
    to = require_field(body, "to")
    if not isinstance(to, str) or to not in TRANSITION_TARGETS:
        raise_err(ERR_VALIDATION, f"to must be one of {sorted(TRANSITION_TARGETS)}")

    current = order["status"]
    if current in {"INCORPORATED", "REJECTED", "WITHDRAWN"}:
        raise_err(ERR_INVALID_STATE, f"change order is terminal ({current})")

    if to == "PRICED":
        if current != "PROPOSED":
            raise_err(ERR_INVALID_STATE, f"cannot move {current} -> PRICED")
        delta_cost = require_field(body, "delta_cost_cents")
        if not is_int(delta_cost):
            raise_err(ERR_VALIDATION, "delta_cost_cents must be an integer")
        delta_delay = require_field(body, "delta_delay_days")
        if not is_int(delta_delay):
            raise_err(ERR_VALIDATION, "delta_delay_days must be an integer")
        if delta_delay < 0:
            raise_err(ERR_VALIDATION, "delta_delay_days must be >= 0")
        delay_cause = require_enum(body, "delay_cause", DELAY_CAUSES)
        order["delta_cost_cents"] = delta_cost
        order["delta_delay_days"] = delta_delay
        order["delay_cause"] = delay_cause
        order["status"] = "PRICED"

    elif to == "PROPOSED":
        # Revision cycle: PRICED -> PROPOSED clears the pricing fields.
        if current != "PRICED":
            raise_err(ERR_INVALID_STATE, f"cannot move {current} -> PROPOSED")
        order["revision_count"] += 1
        order["delta_cost_cents"] = None
        order["delta_delay_days"] = None
        order["delay_cause"] = None
        order["status"] = "PROPOSED"

    elif to == "APPROVED":
        if current != "PRICED":
            raise_err(ERR_INVALID_STATE, f"cannot move {current} -> APPROVED")
        # Referenced segments (or all, when project-wide) freeze — derived at read.
        order["status"] = "APPROVED"

    elif to == "INCORPORATED":
        if current != "APPROVED":
            raise_err(ERR_INVALID_STATE, f"cannot move {current} -> INCORPORATED")
        order["status"] = "INCORPORATED"
        project = db.projects[order["project_id"]]
        domain.incorporation_cascade(project, order)

    elif to in {"REJECTED", "WITHDRAWN"}:
        if current not in {"PROPOSED", "PRICED"}:
            raise_err(ERR_INVALID_STATE, f"cannot move {current} -> {to}")
        order["status"] = to

    touch(order)
    return success_object(change_order_view(order))
