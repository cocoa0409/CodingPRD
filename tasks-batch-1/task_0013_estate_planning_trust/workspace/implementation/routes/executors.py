"""Executor routes."""
from __future__ import annotations

from flask import Blueprint, g, request

import db
from common import (
    get_body,
    pagination_params,
    require_enum,
    require_string,
    stamp_common_fields,
    touch,
)
from errors import (
    APIError,
    ERR_DUPLICATE_EXECUTOR_ACTIVE,
    forbidden,
    invalid_state,
    not_found,
)
from middleware import require_roles
from response import created, list_response, success
from views import view_executor


bp = Blueprint("executors", __name__)

ROLE_TYPES = {"EXECUTOR", "TRUSTEE"}


@bp.post("/executors")
@require_roles("EstatePlanner")
def create_executor():
    body = get_body()
    estate_id = require_string(body, "estate_id")
    if estate_id not in db.estates:
        raise not_found("Estate")

    full_legal_name = require_string(body, "full_legal_name")
    role_type = require_enum(body, "role_type", ROLE_TYPES)
    is_also = body.get("is_also_beneficiary", False)
    if not isinstance(is_also, bool):
        from errors import APIError as E, ERR_INVALID_REQUEST as EE
        raise E(EE, "is_also_beneficiary must be boolean if provided.", 400)

    now = db.now_utc()
    x = {
        "estate_id": estate_id,
        "full_legal_name": full_legal_name,
        "role_type": role_type,
        "status": "NOMINATED",
        "is_also_beneficiary": is_also,
    }
    stamp_common_fields(x, now)
    db.executors[x["id"]] = x
    return created(view_executor(x))


@bp.get("/executors/<xid>")
@require_roles("EstatePlanner", "Executor", "Judge")
def get_executor(xid: str):
    x = db.executors.get(xid)
    if x is None:
        raise not_found("Executor")
    return success(view_executor(x))


@bp.get("/executors")
@require_roles("EstatePlanner", "Executor", "Judge")
def list_executors():
    limit, offset = pagination_params()
    estate_id = request.args.get("estate_id")
    status = request.args.get("status")

    items = list(db.executors.values())
    if estate_id is not None:
        items = [x for x in items if x["estate_id"] == estate_id]
    if status is not None:
        items = [x for x in items if x["status"] == status]

    items.sort(key=lambda x: x["created_at"])
    total = len(items)
    page = [view_executor(x) for x in items[offset:offset + limit]]
    return list_response(page, limit=limit, offset=offset, total_count=total)


@bp.post("/executors/<xid>/accept")
@require_roles("Executor")
def accept_executor(xid: str):
    x = db.executors.get(xid)
    if x is None:
        raise not_found("Executor")

    # Ownership: the calling Executor must be this Executor row.
    if g.user_id != x["id"]:
        raise forbidden("Only the named candidate may accept this executor nomination.")

    if x["status"] != "NOMINATED":
        raise invalid_state("Executor must be NOMINATED to accept.")

    estate = db.estates.get(x["estate_id"])
    if estate is None:
        raise not_found("Estate")
    if estate["status"] not in ("DRAFT", "ALIVE", "DECEASED"):
        raise invalid_state("Estate must be in DRAFT, ALIVE, or DECEASED to accept executor.")

    # Duplicate executor active check (priority 13)
    if x["role_type"] == "EXECUTOR":
        for other in db.executors.values():
            if other["id"] == x["id"]:
                continue
            if (
                other["estate_id"] == x["estate_id"]
                and other["role_type"] == "EXECUTOR"
                and other["status"] in ("ACCEPTED", "COURT_CONFIRMED")
            ):
                raise APIError(
                    ERR_DUPLICATE_EXECUTOR_ACTIVE,
                    "Another EXECUTOR is already ACCEPTED or COURT_CONFIRMED on this estate.",
                    422,
                )

    now = db.now_utc()
    x["status"] = "ACCEPTED"
    touch(x, now)
    estate["executor_user_id"] = x["id"]
    touch(estate, now)
    return success(view_executor(x))


@bp.post("/executors/<xid>/decline")
@require_roles("Executor")
def decline_executor(xid: str):
    x = db.executors.get(xid)
    if x is None:
        raise not_found("Executor")
    if g.user_id != x["id"]:
        raise forbidden("Only the named candidate may decline this executor nomination.")
    if x["status"] != "NOMINATED":
        raise invalid_state("Executor must be NOMINATED to decline.")

    estate = db.estates.get(x["estate_id"])
    if estate is None:
        raise not_found("Estate")
    if estate["status"] == "CLOSED":
        raise invalid_state("Cannot decline executor on CLOSED estate.")

    now = db.now_utc()
    x["status"] = "DECLINED"
    touch(x, now)
    if estate.get("executor_user_id") == x["id"]:
        estate["executor_user_id"] = None
        touch(estate, now)
    return success(view_executor(x))
