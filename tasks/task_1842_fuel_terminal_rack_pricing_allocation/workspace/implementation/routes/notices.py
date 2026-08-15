from flask import Blueprint, request

from clock import now_iso, today_str
from db import db
from errors import (
    ApiError, ERR_INVALID_POOL, ERR_NOTICE_DATE_IN_PAST,
    ERR_NOTICE_NOT_DRAFT, not_found,
)
from helpers import (
    get_body, list_query, new_entity, ser_notice, touch,
)
from middleware import require_roles
from response import success_list, success_object
from routes.schedules import _check_terminal_occ
from services import apply_allocation_notice

bp = Blueprint("notices", __name__)

_ROLES = ["PlatformAdmin", "AllocationManager", "TerminalOperator"]


def _get_notice(notice_id):
    n = db.allocation_notices.get(notice_id)
    if n is None:
        raise not_found("AllocationNotice {} does not exist".format(notice_id))
    return n


@bp.post("/rack/allocation-notices")
def create_notice():
    require_roles(["AllocationManager"])
    body = get_body()
    if body.get("terminal_id") not in db.terminals:
        raise not_found("Terminal {} does not exist".format(body.get("terminal_id")))
    n = new_entity({
        "terminal_id": body.get("terminal_id"),
        "effective_date": body.get("effective_date"),
        "total_pool_gallons": body.get("total_pool_gallons"),
        "allocation_method": body.get("allocation_method"),
        "status": "DRAFT",
        "published_at": None,
    })
    db.allocation_notices[n["id"]] = n
    return success_object(ser_notice(n), 201)


@bp.get("/rack/allocation-notices/<noticeId>")
def get_notice(noticeId):
    require_roles(_ROLES)
    return success_object(ser_notice(_get_notice(noticeId)))


@bp.get("/rack/allocation-notices")
def list_notices():
    require_roles(_ROLES)
    page, total, limit, offset = list_query(
        db.allocation_notices.values(), request.args,
        ["terminal_id", "effective_date", "status"],
    )
    return success_list([ser_notice(n) for n in page], total, limit, offset)


@bp.post("/rack/allocation-notices/<noticeId>/publish")
def publish_notice(noticeId):
    require_roles(["AllocationManager"])
    n = _get_notice(noticeId)
    # Ordered gauntlet (PRD §3.4): DRAFT -> date -> pool -> OCC.
    if n["status"] != "DRAFT":
        raise ApiError(
            ERR_NOTICE_NOT_DRAFT, 409,
            "AllocationNotice must be DRAFT to publish",
        )
    if n["effective_date"] < today_str():
        raise ApiError(
            ERR_NOTICE_DATE_IN_PAST, 422,
            "effective_date is before the logical clock's current date",
        )
    pool = n.get("total_pool_gallons")
    if not isinstance(pool, int) or isinstance(pool, bool) or pool <= 0:
        raise ApiError(ERR_INVALID_POOL, 422, "total_pool_gallons must be > 0")
    terminal = db.terminals.get(n["terminal_id"])
    if terminal is None:
        raise not_found("Terminal {} does not exist".format(n["terminal_id"]))
    _check_terminal_occ(get_body(), terminal)

    # Supersede any other PUBLISHED notice for the same (terminal, date).
    for other in list(db.allocation_notices.values()):
        if (
            other["id"] != n["id"]
            and other["status"] == "PUBLISHED"
            and other["terminal_id"] == n["terminal_id"]
            and other["effective_date"] == n["effective_date"]
        ):
            other["status"] = "SUPERSEDED"
            touch(other)

    n["status"] = "PUBLISHED"
    n["published_at"] = now_iso()
    touch(n)
    apply_allocation_notice(n)
    return success_object(ser_notice(n))
