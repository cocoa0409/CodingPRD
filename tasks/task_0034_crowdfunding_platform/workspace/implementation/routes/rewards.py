"""Reward tier CRUD (DRAFT only)."""

from flask import Blueprint, g

from clock import parse_iso
from db import DB, LOCK, new_id
from errors import (
    cross_project,
    duplicate_tier,
    forbidden,
    invalid_state,
    not_found,
    validation_error,
)
from middleware import require_roles
from response import success_array, success_object
from services.common import (
    bump_version,
    check_occ,
    get_json_body,
    paginate,
    parse_pagination,
    require_positive_int,
    require_str,
    stamp_create,
)
from services.serializers import reward_view


bp = Blueprint("rewards", __name__)


VALID_REWARD_TYPES = {"PHYSICAL", "DIGITAL"}


@bp.route("/projects/<project_id>/rewards", methods=["POST"])
@require_roles("Initiator")
def create_reward(project_id):
    body = get_json_body()
    with LOCK:
        project = DB.projects.get(project_id)
        if project is None:
            raise not_found()
        if project["initiator_id"] != g.user_id:
            raise forbidden("Initiator does not own this project")
        if project["status"] != "DRAFT":
            raise invalid_state("Rewards can only be created while project is in DRAFT")

        tier_label = require_str(body, "tier_label")
        # Uniqueness check
        for r in DB.rewards.values():
            if r["project_id"] == project_id and r["tier_label"] == tier_label:
                raise duplicate_tier()

        pledge_amount_cents = require_positive_int(body, "pledge_amount_cents")
        reward_type = body.get("reward_type")
        if reward_type not in VALID_REWARD_TYPES:
            raise validation_error("reward_type must be PHYSICAL or DIGITAL")
        inventory_limit = body.get("inventory_limit")
        if inventory_limit is not None:
            if isinstance(inventory_limit, bool) or not isinstance(inventory_limit, int) or inventory_limit < 0:
                raise validation_error("inventory_limit must be a non-negative integer or null")
        estimated_delivery = body.get("estimated_delivery")
        if estimated_delivery is not None:
            try:
                estimated_delivery = parse_iso(estimated_delivery)
            except ValueError as e:
                raise validation_error(str(e))

        rec = stamp_create({
            "id": new_id(),
            "project_id": project_id,
            "tier_label": tier_label,
            "pledge_amount_cents": pledge_amount_cents,
            "reward_type": reward_type,
            "inventory_limit": inventory_limit,
            "inventory_claimed": 0,
            "estimated_delivery": estimated_delivery,
        })
        DB.rewards[rec["id"]] = rec
    return success_object(reward_view(rec), status=201)


@bp.route("/projects/<project_id>/rewards", methods=["GET"])
@require_roles("Initiator", "Backer", "ContentReviewer", "LegalReviewer", "FinancialReviewer", "PlatformAdmin")
def list_rewards(project_id):
    limit, offset = parse_pagination()
    with LOCK:
        project = DB.projects.get(project_id)
        if project is None:
            raise not_found()
        items = [r for r in DB.rewards.values() if r["project_id"] == project_id]
        items.sort(key=lambda r: r["created_at"])
        page, total, has_more = paginate(items, limit, offset)
        return success_array([reward_view(r) for r in page], limit=limit, offset=offset,
                             total_count=total, has_more=has_more)


@bp.route("/projects/<project_id>/rewards/<id>", methods=["PATCH"])
@require_roles("Initiator")
def patch_reward(project_id, id):
    body = get_json_body()
    with LOCK:
        project = DB.projects.get(project_id)
        if project is None:
            raise not_found()
        rec = DB.rewards.get(id)
        if rec is None:
            raise not_found()
        if rec["project_id"] != project_id:
            raise cross_project("Reward does not belong to project")
        if project["initiator_id"] != g.user_id:
            raise forbidden()
        if project["status"] != "DRAFT":
            raise invalid_state("Reward edits only allowed in DRAFT")
        check_occ(rec, body)

        if "tier_label" in body:
            new_label = require_str(body, "tier_label")
            for r in DB.rewards.values():
                if r["project_id"] == project_id and r["id"] != id and r["tier_label"] == new_label:
                    raise duplicate_tier()
            rec["tier_label"] = new_label
        if "pledge_amount_cents" in body:
            rec["pledge_amount_cents"] = require_positive_int(body, "pledge_amount_cents")
        if "reward_type" in body:
            rt = body["reward_type"]
            if rt not in VALID_REWARD_TYPES:
                raise validation_error("reward_type invalid")
            rec["reward_type"] = rt
        if "inventory_limit" in body:
            il = body["inventory_limit"]
            if il is not None and (isinstance(il, bool) or not isinstance(il, int) or il < 0):
                raise validation_error("inventory_limit must be non-negative integer or null")
            rec["inventory_limit"] = il
        if "estimated_delivery" in body:
            ed = body["estimated_delivery"]
            if ed is not None:
                try:
                    rec["estimated_delivery"] = parse_iso(ed)
                except ValueError as e:
                    raise validation_error(str(e))
            else:
                rec["estimated_delivery"] = None
        bump_version(rec)
        return success_object(reward_view(rec))
