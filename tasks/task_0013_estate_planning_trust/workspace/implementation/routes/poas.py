"""PowerOfAttorney routes."""
from __future__ import annotations

from flask import Blueprint, request

import db
from common import (
    get_body,
    pagination_params,
    parse_iso_datetime,
    require_enum,
    require_field,
    require_string,
    stamp_common_fields,
    touch,
)
from errors import (
    APIError,
    ERR_POA_INTERVAL_OVERLAP,
    invalid_state,
    not_found,
)
from middleware import require_roles
from response import created, list_response, success
from views import view_poa


bp = Blueprint("poas", __name__)

SCOPES = {"FINANCIAL", "HEALTHCARE", "DURABLE_FINANCIAL", "DURABLE_HEALTHCARE"}


@bp.post("/powers-of-attorney")
@require_roles("EstatePlanner")
def create_poa():
    body = get_body()
    decedent_id = require_string(body, "decedent_id")
    if decedent_id not in db.decedents:
        raise not_found("Decedent")
    agent_full_name = require_string(body, "agent_full_name")
    scope = require_enum(body, "scope", SCOPES)

    now = db.now_utc()
    p = {
        "decedent_id": decedent_id,
        "agent_full_name": agent_full_name,
        "scope": scope,
        "status": "DRAFT",
        "effective_at": None,
        "effective_until": None,
    }
    stamp_common_fields(p, now)
    db.powers_of_attorney[p["id"]] = p
    return created(view_poa(p))


@bp.get("/powers-of-attorney/<pid>")
@require_roles("EstatePlanner", "Executor")
def get_poa(pid: str):
    p = db.powers_of_attorney.get(pid)
    if p is None:
        raise not_found("PowerOfAttorney")
    return success(view_poa(p))


@bp.get("/powers-of-attorney")
@require_roles("EstatePlanner", "Executor")
def list_poas():
    limit, offset = pagination_params()
    decedent_id = request.args.get("decedent_id")
    status = request.args.get("status")

    items = list(db.powers_of_attorney.values())
    if decedent_id is not None:
        items = [p for p in items if p["decedent_id"] == decedent_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]

    items.sort(key=lambda p: p["created_at"])
    total = len(items)
    page = [view_poa(p) for p in items[offset:offset + limit]]
    return list_response(page, limit=limit, offset=offset, total_count=total)


def _intervals_overlap(a_start, a_end, b_start, b_end) -> bool:
    """Half-open [start, end). end=None => +inf."""
    # Overlap iff a_start < b_end and b_start < a_end.
    if a_end is not None and a_start >= a_end:
        # Degenerate; treat as no overlap.
        return False
    a_end_eff = a_end  # may be None
    b_end_eff = b_end
    # a_start < b_end_eff
    cond1 = (b_end_eff is None) or (a_start < b_end_eff)
    cond2 = (a_end_eff is None) or (b_start < a_end_eff)
    return cond1 and cond2


@bp.post("/powers-of-attorney/<pid>/activate")
@require_roles("EstatePlanner")
def activate_poa(pid: str):
    p = db.powers_of_attorney.get(pid)
    if p is None:
        raise not_found("PowerOfAttorney")
    if p["status"] != "DRAFT":
        raise invalid_state("POA must be DRAFT to activate.")

    body = get_body()
    effective_at = parse_iso_datetime(require_field(body, "effective_at"), "effective_at")
    effective_until = None
    if "effective_until" in body and body["effective_until"] is not None:
        effective_until = parse_iso_datetime(body["effective_until"], "effective_until")

    # Interval non-overlap check (priority 16)
    for other in db.powers_of_attorney.values():
        if other["id"] == p["id"]:
            continue
        if other["decedent_id"] != p["decedent_id"]:
            continue
        if other["scope"] != p["scope"]:
            continue
        if other["status"] != "ACTIVE":
            continue
        if _intervals_overlap(
            effective_at, effective_until,
            other["effective_at"], other["effective_until"],
        ):
            raise APIError(
                ERR_POA_INTERVAL_OVERLAP,
                "POA interval overlaps an existing ACTIVE POA of the same scope on this decedent.",
                422,
            )

    now = db.now_utc()
    p["effective_at"] = effective_at
    p["effective_until"] = effective_until
    p["status"] = "ACTIVE"
    touch(p, now)
    return success(view_poa(p))


@bp.post("/powers-of-attorney/<pid>/revoke")
@require_roles("EstatePlanner")
def revoke_poa(pid: str):
    p = db.powers_of_attorney.get(pid)
    if p is None:
        raise not_found("PowerOfAttorney")
    if p["status"] != "ACTIVE":
        raise invalid_state("POA must be ACTIVE to revoke.")
    now = db.now_utc()
    p["status"] = "REVOKED"
    touch(p, now)
    return success(view_poa(p))
