"""Event packouts: create, seal (allergen gate), ship."""
from flask import Blueprint, request

from db import db, LOCK
from errors import ApiError
from middleware import (
    get_identity, require_roles, require_owner, get_json_body, parse_pagination,
)
from response import success, paginated
from services.common import (
    stamp_new, touch, public, find_member, get_or_404, sorted_by_creation,
    paginate, require_fields,
)

bp = Blueprint("packouts", __name__)


def _load_member_packout(member_id, packout_id):
    find_member(member_id)
    packout = get_or_404(db.event_packouts, packout_id)
    if packout["member_id"] != member_id:
        raise ApiError("ERR_NOT_FOUND")
    return packout


@bp.post("/members/<member_id>/packouts")
def create_packout(member_id):
    user_id, role = get_identity()
    require_roles(role, {"MemberOperator"})
    require_owner(role, user_id, member_id)
    body = get_json_body()
    with LOCK:
        member = find_member(member_id)
        require_fields(body, ["event_name", "batch_ids"])
        if not isinstance(body["event_name"], str) or not body["event_name"]:
            raise ApiError("ERR_INVALID_REQUEST")
        batch_ids = body["batch_ids"]
        if not isinstance(batch_ids, list):
            raise ApiError("ERR_INVALID_REQUEST")
        allergen_free = body.get("allergen_free_required", [])
        if allergen_free is None:
            allergen_free = []
        if not isinstance(allergen_free, list):
            raise ApiError("ERR_INVALID_REQUEST")

        # FK existence for every batch id (priority 5).
        batches = []
        for bid in batch_ids:
            batches.append(get_or_404(db.production_batches, bid))

        # Member active (priority 9).
        if member["status"] != "ACTIVE":
            raise ApiError("ERR_MEMBER_NOT_ACTIVE")

        # Every batch must be COMPLETED and owned by this member (priority 18).
        for batch in batches:
            if batch["member_id"] != member_id or batch["status"] != "COMPLETED":
                raise ApiError("ERR_BATCH_NOT_COMPLETED")

        combined_tags = []
        packed_units = 0
        for batch in batches:
            recipe = db.recipes.get(batch["recipe_id"])
            if recipe is not None:
                for tag in recipe.get("allergen_tags", []):
                    if tag not in combined_tags:
                        combined_tags.append(tag)
            packed_units += batch["actual_yield_units"] or 0

        packout = {
            "member_id": member_id,
            "event_name": body["event_name"],
            "batch_ids": list(batch_ids),
            "allergen_free_required": list(allergen_free),
            "combined_allergen_tags": combined_tags,
            "packed_unit_count": packed_units,
            "status": "DRAFT",
        }
        stamp_new(packout)
        db.event_packouts[packout["id"]] = packout
        return success(public(packout), 201)


@bp.get("/members/<member_id>/packouts")
def list_member_packouts(member_id):
    _, role = get_identity()
    require_roles(role, {"MemberOperator", "FacilityManager"})
    limit, offset = parse_pagination()
    status = request.args.get("status")
    with LOCK:
        find_member(member_id)
        records = [p for p in db.event_packouts.values() if p["member_id"] == member_id]
        records = sorted_by_creation(records)
        if status:
            records = [p for p in records if p["status"] == status]
        items, total = paginate(records, limit, offset)
    return paginated(items, total, limit, offset)


@bp.get("/members/<member_id>/packouts/<packout_id>")
def get_member_packout(member_id, packout_id):
    _, role = get_identity()
    require_roles(role, {"MemberOperator", "FacilityManager"})
    with LOCK:
        packout = _load_member_packout(member_id, packout_id)
        return success(public(packout))


@bp.post("/members/<member_id>/packouts/<packout_id>/seal")
def seal_packout(member_id, packout_id):
    user_id, role = get_identity()
    require_roles(role, {"MemberOperator"})
    require_owner(role, user_id, member_id)
    with LOCK:
        packout = _load_member_packout(member_id, packout_id)
        if packout["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE")
        conflict = set(packout["combined_allergen_tags"]) & set(packout["allergen_free_required"])
        if conflict:
            raise ApiError("ERR_ALLERGEN_CONFLICT")
        packout["status"] = "SEALED"
        touch(packout)
        return success(public(packout))


@bp.post("/members/<member_id>/packouts/<packout_id>/ship")
def ship_packout(member_id, packout_id):
    user_id, role = get_identity()
    require_roles(role, {"MemberOperator"})
    require_owner(role, user_id, member_id)
    with LOCK:
        packout = _load_member_packout(member_id, packout_id)
        if packout["status"] != "SEALED":
            raise ApiError("ERR_INVALID_STATE")
        packout["status"] = "SHIPPED"
        touch(packout)
        return success(public(packout))
