"""Area-code relief planning, public comment and the relief order (PRD 3.9)."""

from flask import Blueprint

from db import (
    base_record,
    by_created,
    by_created_desc,
    days,
    db,
    light_record,
    now,
    touch,
)
from errors import fail
from middleware import (
    ROLE_ADMIN,
    ROLE_APPROVER,
    ROLE_CARRIER,
    ROLE_COMMENTER,
    body,
    check_action_role,
    opt_dt,
    opt_enum,
    opt_id,
    opt_int,
    opt_str,
    opt_str_list,
    req_dt,
    req_enum,
    req_str,
    require_roles,
)
from response import object_response, paginate
from routes.common import NPA_PATTERN, field, filter_rows
from routes.npas import new_npa
from services import constants as C
from services import calc, core, serialize

bp = Blueprint("relief", __name__)

READERS = (ROLE_ADMIN, ROLE_APPROVER, ROLE_CARRIER, ROLE_COMMENTER)

PLAN_ACTION_ROLES = {
    "OPEN_COMMENT": (ROLE_ADMIN,),
    "CLOSE_AND_RECOMMEND": (ROLE_ADMIN,),
    "ORDER": (ROLE_APPROVER,),
    "WITHDRAW": (ROLE_ADMIN,),
}

WORKING_STATUSES = ("PUBLIC_COMMENT", "OVERLAY_RECOMMENDED", "SPLIT_RECOMMENDED")


def _check_window_buffer(npa_id, effective_at, exclude_plan_id=None):
    if effective_at is None:
        return
    rows = [
        p
        for p in db.relief_plans.values()
        if p["npa_id"] == npa_id
        and p["status"] != "WITHDRAWN"
        and p["id"] != exclude_plan_id
    ]
    if not rows:
        return
    newest = by_created_desc(rows)[0]
    boundary = serialize.window_end_at(newest)
    if boundary is None:
        return
    if effective_at < boundary + days(C.RELIEF_WINDOW_BUFFER_DAYS):
        fail(
            "ERR_RELIEF_WINDOW_OVERLAP",
            "effective_at must clear the 90-day relief buffer",
        )


@bp.route("/numbering/npas/<npa_id>/relief-plans", methods=["POST"])
def create_plan(npa_id):
    require_roles(ROLE_ADMIN)
    payload = body()
    planned = opt_enum(payload, "planned_relief_type", C.RELIEF_TYPES, "UNDETERMINED")
    window_days = opt_int(
        payload,
        "comment_window_days",
        C.COMMENT_WINDOW_MIN_DAYS,
        C.COMMENT_WINDOW_MAX_DAYS,
        C.COMMENT_WINDOW_DAYS,
    )
    new_code = opt_str(payload, "new_npa_code", 3, 3, NPA_PATTERN)
    effective_at = opt_dt(payload, "effective_at")

    npa = core.get_npa(npa_id)

    _check_window_buffer(npa["id"], effective_at)

    record = base_record(
        npa_id=npa["id"],
        planned_relief_type=planned,
        status="PLANNING",
        comment_window_days=window_days,
        comment_window_open_at=None,
        comment_window_close_at=None,
        recommended_relief_type=None,
        support_overlay_weight=None,
        support_split_weight=None,
        recommender_user_id=None,
        ordering_user_id=None,
        new_npa_code=new_code,
        effective_at=effective_at,
        permissive_dialing_end_at=None,
        successor_npa_id=None,
    )
    db.relief_plans[record["id"]] = record
    return object_response(serialize.relief_plan(record), 201)


@bp.route("/numbering/npas/<npa_id>/relief-plans", methods=["GET"])
def list_npa_plans(npa_id):
    require_roles(*READERS)
    npa = core.get_npa(npa_id)
    rows = by_created(
        [p for p in db.relief_plans.values() if p["npa_id"] == npa["id"]]
    )
    rows = filter_rows(rows, [("status", field("status"))])
    return paginate(rows, serialize.relief_plan)


@bp.route("/numbering/relief-plans", methods=["GET"])
def list_plans():
    require_roles(*READERS)
    rows = by_created(db.relief_plans.values())
    rows = filter_rows(
        rows,
        [
            ("npa_id", field("npa_id")),
            ("successor_npa_id", field("successor_npa_id")),
            ("status", field("status")),
            ("recommended_relief_type", field("recommended_relief_type")),
        ],
    )
    return paginate(rows, serialize.relief_plan)


@bp.route("/numbering/relief-plans/<plan_id>", methods=["GET"])
def get_plan(plan_id):
    require_roles(*READERS)
    return object_response(serialize.relief_plan(core.get_plan(plan_id)))


@bp.route("/numbering/relief-plans/<plan_id>/comments", methods=["POST"])
def file_comment(plan_id):
    require_roles(ROLE_COMMENTER, ROLE_CARRIER)
    payload = body()
    commenter_type = req_enum(payload, "commenter_type", C.COMMENTER_TYPES)
    position = req_enum(payload, "position", C.COMMENT_POSITIONS)
    text = req_str(payload, "body", 1, 1000)
    opt_id(payload, "relief_plan_id")

    plan = core.get_plan(plan_id)

    if plan["status"] in ("ORDERED", "WITHDRAWN"):
        fail("ERR_TERMINAL_STATE", "the plan is closed")

    instant = now()
    opened = plan["comment_window_open_at"]
    closes = plan["comment_window_close_at"]
    if opened is None or closes is None or instant < opened or instant >= closes:
        fail("ERR_COMMENT_WINDOW_CLOSED", "the comment window is not open")

    record = light_record(
        relief_plan_id=plan["id"],
        commenter_type=commenter_type,
        position=position,
        body=text,
        weight=float(C.COMMENT_WEIGHTS[commenter_type]),
        submitted_at=instant,
    )
    db.comments[record["id"]] = record

    tally = calc.comment_tally(plan["id"])
    plan["support_overlay_weight"] = tally["overlay_weight"]
    plan["support_split_weight"] = tally["split_weight"]
    touch(plan)

    return object_response(serialize.comment(record), 201)


@bp.route("/numbering/relief-plans/<plan_id>/comments", methods=["GET"])
def list_comments(plan_id):
    require_roles(*READERS)
    plan = core.get_plan(plan_id)
    rows = [c for c in db.comments.values() if c["relief_plan_id"] == plan["id"]]
    rows.sort(key=lambda c: (c["submitted_at"], c["_seq"]))
    rows = filter_rows(
        rows,
        [
            ("position", field("position")),
            ("commenter_type", field("commenter_type")),
        ],
    )
    return paginate(rows, serialize.comment)


@bp.route("/numbering/relief-plans/<plan_id>/transitions", methods=["POST"])
def transition_plan(plan_id):
    actor = require_roles(ROLE_ADMIN, ROLE_APPROVER)
    payload = body()
    action = req_enum(payload, "action", C.RELIEF_ACTIONS)
    if action == "ORDER":
        new_code = req_str(payload, "new_npa_code", 3, 3, NPA_PATTERN)
        effective_at = req_dt(payload, "effective_at")
        if effective_at <= now():
            fail("ERR_INVALID_REQUEST", "effective_at must be after the logical clock")
    else:
        new_code = opt_str(payload, "new_npa_code", 3, 3, NPA_PATTERN)
        effective_at = opt_dt(payload, "effective_at")
    moved_ids = opt_str_list(payload, "moved_rate_center_ids")

    plan = core.get_plan(plan_id)

    moved = []
    if moved_ids:
        for rate_center_id in moved_ids:
            moved.append(core.get_rate_center(rate_center_id))

    check_action_role(actor, action, PLAN_ACTION_ROLES)

    if plan["status"] in ("ORDERED", "WITHDRAWN"):
        fail("ERR_TERMINAL_STATE", "the plan is closed")

    npa = core.get_npa(plan["npa_id"])
    status = plan["status"]

    if action == "OPEN_COMMENT":
        if status != "PLANNING":
            fail("ERR_INVALID_STATE_TRANSITION", "OPEN_COMMENT is not available")
        if npa["status"] not in ("JEOPARDY", "EXHAUSTED", "RELIEF_PLANNED"):
            fail("ERR_INVALID_STATE_TRANSITION", "the area code is not in relief")
        for other in db.relief_plans.values():
            if (
                other["npa_id"] == npa["id"]
                and other["id"] != plan["id"]
                and other["status"] in WORKING_STATUSES
            ):
                fail(
                    "ERR_INVALID_STATE_TRANSITION",
                    "another consultation is already running",
                )
        instant = now()
        plan["status"] = "PUBLIC_COMMENT"
        plan["comment_window_open_at"] = instant
        plan["comment_window_close_at"] = instant + days(plan["comment_window_days"])
        touch(plan)
        if npa["status"] != "RELIEF_PLANNED":
            npa["status"] = "RELIEF_PLANNED"
            touch(npa)
    elif action == "CLOSE_AND_RECOMMEND":
        if status != "PUBLIC_COMMENT":
            fail("ERR_INVALID_STATE_TRANSITION", "CLOSE_AND_RECOMMEND is not available")
        closes = plan["comment_window_close_at"]
        if closes is None or now() < closes:
            fail("ERR_INVALID_STATE_TRANSITION", "the comment window is still open")
        tally = calc.comment_tally(plan["id"])
        plan["support_overlay_weight"] = tally["overlay_weight"]
        plan["support_split_weight"] = tally["split_weight"]
        plan["recommended_relief_type"] = tally["recommendation"]
        plan["recommender_user_id"] = actor.user_id
        plan["status"] = (
            "SPLIT_RECOMMENDED"
            if tally["recommendation"] == "GEOGRAPHIC_SPLIT"
            else "OVERLAY_RECOMMENDED"
        )
        touch(plan)
    elif action == "ORDER":
        if status not in ("OVERLAY_RECOMMENDED", "SPLIT_RECOMMENDED"):
            fail("ERR_INVALID_STATE_TRANSITION", "ORDER is not available")
        if plan["recommender_user_id"] is not None and (
            actor.user_id == plan["recommender_user_id"]
        ):
            fail("ERR_SEGREGATION_OF_DUTIES", "the recommender may not order relief")
        _check_window_buffer(npa["id"], effective_at, plan["id"])
        for existing in db.npas.values():
            if existing["npa_code"] == new_code:
                fail("ERR_DUPLICATE_NPA_CODE", "npa_code %s already exists" % new_code)
        _order_relief(plan, npa, actor, new_code, effective_at, moved)
    else:
        if status not in ("PLANNING",) + WORKING_STATUSES:
            fail("ERR_INVALID_STATE_TRANSITION", "WITHDRAW is not available")
        plan["status"] = "WITHDRAWN"
        touch(plan)
        still_working = [
            p
            for p in db.relief_plans.values()
            if p["npa_id"] == npa["id"]
            and p["id"] != plan["id"]
            and p["status"] in WORKING_STATUSES
        ]
        if npa["status"] == "RELIEF_PLANNED" and not still_working:
            npa["status"] = "ACTIVE"
            if not core.recompute_npa_posture(npa):
                touch(npa)

    return object_response(serialize.relief_plan(plan))


def _order_relief(plan, npa, actor, new_code, effective_at, moved):
    is_split = plan["recommended_relief_type"] == "GEOGRAPHIC_SPLIT"
    parent_rate_centers = core.rate_centers_of_npa(npa["id"])

    if is_split:
        if not moved:
            fail("ERR_INVALID_REQUEST", "moved_rate_center_ids is required for a split")
        for rate_center in moved:
            if rate_center["npa_id"] != npa["id"]:
                fail(
                    "ERR_INVALID_REQUEST",
                    "a moved rate center must belong to the plan's area code",
                )

    successor = new_npa(
        new_code,
        npa["state_code"],
        "GEOGRAPHIC" if is_split else "OVERLAY",
        npa["id"],
    )
    successor["permissive_dialing_end_at"] = effective_at + days(
        C.PERMISSIVE_DIALING_DAYS
    )

    plan["new_npa_code"] = new_code
    plan["effective_at"] = effective_at
    plan["permissive_dialing_end_at"] = successor["permissive_dialing_end_at"]
    plan["successor_npa_id"] = successor["id"]
    plan["ordering_user_id"] = actor.user_id
    plan["status"] = "ORDERED"
    touch(plan)

    if not is_split:
        if not core.apply_posture(npa, "ACTIVE"):
            touch(npa)
        return

    parent_blocks = core.blocks_of_npa(npa["id"])

    moved_ids = set()
    for rate_center in moved:
        if rate_center["id"] in moved_ids:
            continue
        moved_ids.add(rate_center["id"])
        rate_center["npa_id"] = successor["id"]
        for block in core.blocks_of_rate_center(rate_center["id"]):
            block["npa_id"] = successor["id"]
        touch(rate_center)

    if len(moved_ids) >= len(parent_rate_centers):
        # The parent has nothing left: it retires, and the inventory that was
        # still sitting in its pool retires with it (PRD 3.9) - the only path
        # by which a block reaches RETIRED.
        npa["status"] = "RETIRED"
        for block in parent_blocks:
            if block["allocation_status"] == "POOL_AVAILABLE":
                block["allocation_status"] = "RETIRED"
    touch(npa)
