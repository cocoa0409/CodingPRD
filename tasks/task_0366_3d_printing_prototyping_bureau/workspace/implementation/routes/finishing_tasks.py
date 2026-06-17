"""FinishingTask routes: attach, schedule (cooldown buffer), complete, skip."""

from flask import Blueprint, request

import errors
import validation as V
from db import DB, LOCK, stamp_create, touch
from middleware import require_auth, require_role
from pagination import paginate
from response import object_response, array_response
from services import domain, ownership

bp = Blueprint("finishing_tasks", __name__)

KINDS = ("SUPPORT_REMOVAL", "SANDING", "DYE_BLACK", "UV_CURE", "POLISH")
READ_ROLES = ("Customer", "BureauAdmin", "Operator", "QAReviewer")


@bp.route("/bureaus/finishing-tasks", methods=["POST"])
def create_finishing_task():
    with LOCK:
        principal = require_auth()
        require_role(principal, ("Customer", "Operator"))
        body = V.get_body()
        order_line_id = V.require_id(body, "order_line_id")
        kind = V.require_enum(body, "kind", KINDS)
        addon = V.require_nonneg_int(body, "addon_cents")
        station_start = V.require_nonneg_int(body, "station_start_min")
        station_duration = V.require_positive_int(body, "station_duration_min")

        line = DB.order_lines.get(order_line_id)
        if line is None:
            raise errors.reference_not_found()

        if principal.role == "Customer" and principal.user_id != ownership.line_customer_id(line):
            raise errors.forbidden()

        task = stamp_create({
            "bureau_id": line["bureau_id"],
            "order_line_id": order_line_id,
            "kind": kind,
            "addon_cents": addon,
            "station_start_min": station_start,
            "station_duration_min": station_duration,
            "status": "PENDING",
        })
        DB.finishing_tasks[task["id"]] = task

        # Recompute line finishing total and the owning order totals.
        domain.recompute_line_finishing_total(line)
        order = DB.orders.get(line["order_id"])
        if order is not None:
            domain.recompute_order_totals(order)
        return object_response(task, 201)


@bp.route("/bureaus/finishing-tasks/<task_id>", methods=["GET"])
def get_finishing_task(task_id):
    with LOCK:
        principal = require_auth()
        require_role(principal, READ_ROLES)
        task = domain.get_or_404(DB.finishing_tasks, task_id)
        if principal.role == "Customer":
            line = DB.order_lines.get(task["order_line_id"])
            owner = ownership.line_customer_id(line) if line else None
            if principal.user_id != owner:
                raise errors.forbidden()
        return object_response(task, 200)


@bp.route("/bureaus/finishing-tasks", methods=["GET"])
def list_finishing_tasks():
    with LOCK:
        principal = require_auth()
        require_role(principal, READ_ROLES)
        items = list(DB.finishing_tasks.values())
        for key in ("bureau_id", "order_line_id", "status"):
            val = request.args.get(key)
            if val is not None:
                items = [t for t in items if t.get(key) == val]
        if principal.role == "Customer":
            def owned(t):
                line = DB.order_lines.get(t["order_line_id"])
                return line is not None and ownership.line_customer_id(line) == principal.user_id
            items = [t for t in items if owned(t)]
        page, limit, offset, total = paginate(items)
        return array_response(page, limit, offset, total)


@bp.route("/bureaus/finishing-tasks/<task_id>/schedule", methods=["POST"])
def schedule_finishing_task(task_id):
    with LOCK:
        principal = require_auth()
        require_role(principal, ("Operator",))
        task = domain.get_or_404(DB.finishing_tasks, task_id)
        if task["status"] != "PENDING":
            raise errors.invalid_state()

        bureau = DB.bureaus[task["bureau_id"]]
        buffer_min = bureau["cooldown_buffer_min"]
        new_start = task["station_start_min"]
        new_end = new_start + task["station_duration_min"]  # closed-interval end

        # Closed-interval overlap with cooldown buffer against SCHEDULED tasks of
        # the same kind in the same bureau: the gap must be strictly > buffer.
        for other in DB.finishing_tasks.values():
            if other["id"] == task["id"]:
                continue
            if other["bureau_id"] != task["bureau_id"]:
                continue
            if other["kind"] != task["kind"]:
                continue
            if other["status"] != "SCHEDULED":
                continue
            o_start = other["station_start_min"]
            o_end = o_start + other["station_duration_min"]
            # Gap between the two closed intervals [new_start,new_end] and
            # [o_start,o_end]. If they overlap or touch, gap <= 0.
            if new_start > o_end:
                gap = new_start - o_end
            elif o_start > new_end:
                gap = o_start - new_end
            else:
                gap = 0  # overlapping/touching closed intervals
            if not (gap > buffer_min):
                raise errors.conflict(
                    errors.ERR_STATION_SLOT_CONFLICT,
                    "Station slot violates cooldown buffer",
                )

        task["status"] = "SCHEDULED"
        touch(task)
        return object_response(task, 200)


@bp.route("/bureaus/finishing-tasks/<task_id>/complete", methods=["POST"])
def complete_finishing_task(task_id):
    with LOCK:
        principal = require_auth()
        require_role(principal, ("Operator",))
        task = domain.get_or_404(DB.finishing_tasks, task_id)
        if task["status"] != "SCHEDULED":
            raise errors.invalid_state()
        task["status"] = "DONE"
        touch(task)
        _maybe_bubble(task)
        return object_response(task, 200)


@bp.route("/bureaus/finishing-tasks/<task_id>/skip", methods=["POST"])
def skip_finishing_task(task_id):
    with LOCK:
        principal = require_auth()
        require_role(principal, ("Operator",))
        task = domain.get_or_404(DB.finishing_tasks, task_id)
        if task["status"] not in ("PENDING", "SCHEDULED"):
            raise errors.invalid_state()
        task["status"] = "SKIPPED"
        touch(task)
        _maybe_bubble(task)
        return object_response(task, 200)


def _maybe_bubble(task):
    line = DB.order_lines.get(task["order_line_id"])
    if not line:
        return
    order = DB.orders.get(line["order_id"])
    if order is not None:
        domain.bubble_on_finishing_resolved(order)
