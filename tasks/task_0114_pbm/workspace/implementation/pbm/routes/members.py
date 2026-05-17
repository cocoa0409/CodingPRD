"""/pbm/members — Member enrollment and suspension."""
from __future__ import annotations

from flask import Blueprint, request

from ..auth import require_roles
from ..envelope import success, list_success
from ..errors import (
    APIError,
    ERR_INVALID_STATE,
    ERR_RESOURCE_NOT_FOUND,
)
from ..store import STORE
from ..validation import (
    check_version,
    get_json_body,
    paginate,
    parse_pagination,
    require_field,
)

bp = Blueprint("members", __name__)


def _serialize(m: dict) -> dict:
    return {
        "id": m["id"],
        "plan_id": m["plan_id"],
        "full_name": m["full_name"],
        "date_of_birth": m["date_of_birth"],
        "enrollment_status": m["enrollment_status"],
        "ytd_deductible_paid_cents": m["ytd_deductible_paid_cents"],
        "ytd_oop_paid_cents": m["ytd_oop_paid_cents"],
        "benefit_year_start": m["benefit_year_start"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


@bp.post("/pbm/members")
@require_roles("PBMAdmin")
def create_member():
    body = get_json_body()
    plan_id = require_field(body, "plan_id")
    full_name = require_field(body, "full_name")
    dob = require_field(body, "date_of_birth")

    with STORE.lock:
        if plan_id not in STORE.plans:
            raise APIError(ERR_RESOURCE_NOT_FOUND, f"Plan {plan_id} not found", 404)
        member = STORE.init_common_fields({
            "plan_id": plan_id,
            "full_name": full_name,
            "date_of_birth": dob,
            "enrollment_status": "ACTIVE",
            "ytd_deductible_paid_cents": 0,
            "ytd_oop_paid_cents": 0,
            "benefit_year_start": STORE.now_ts(),
        })
        STORE.members[member["id"]] = member
    return success(_serialize(member), status=201)


@bp.get("/pbm/members")
@require_roles("PBMAdmin", "ClinicalReviewer", "ClaimsAdjudicator")
def list_members():
    limit, offset = parse_pagination()
    plan_id_filter = request.args.get("plan_id")
    status_filter = request.args.get("enrollment_status")
    with STORE.lock:
        items = list(STORE.members.values())
    if plan_id_filter:
        items = [m for m in items if m["plan_id"] == plan_id_filter]
    if status_filter:
        items = [m for m in items if m["enrollment_status"] == status_filter]
    items.sort(key=lambda m: (m["created_at"], m["id"]))
    page, total = paginate(items, limit, offset)
    return list_success([_serialize(m) for m in page], limit=limit, offset=offset, total_count=total)


@bp.get("/pbm/members/<mid>")
@require_roles("PBMAdmin", "ClinicalReviewer", "ClaimsAdjudicator")
def get_member(mid: str):
    with STORE.lock:
        member = STORE.members.get(mid)
    if member is None:
        raise APIError(ERR_RESOURCE_NOT_FOUND, f"Member {mid} not found", 404)
    return success(_serialize(member))


@bp.post("/pbm/members/<mid>/suspend")
@require_roles("PBMAdmin")
def suspend_member(mid: str):
    body = get_json_body()
    with STORE.lock:
        member = STORE.members.get(mid)
        if member is None:
            raise APIError(ERR_RESOURCE_NOT_FOUND, f"Member {mid} not found", 404)
        if member["enrollment_status"] != "ACTIVE":
            raise APIError(
                ERR_INVALID_STATE,
                f"Member must be ACTIVE to suspend; current={member['enrollment_status']}",
                409,
            )
        check_version(body, member)
        member["enrollment_status"] = "SUSPENDED"
        STORE.bump(member)
        return success(_serialize(member))
