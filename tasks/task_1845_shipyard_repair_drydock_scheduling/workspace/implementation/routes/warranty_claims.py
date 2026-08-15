"""WarrantyClaim endpoints: filing, acceptance (spawning zero-priced rework),
and denial."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_OWNERSHIP_MISMATCH,
    ERR_WARRANTY_EXPIRED,
    ERR_WORK_ITEM_NOT_IN_PROJECT,
)
from middleware import require_roles
from response import success_list, success_object
from services.serializers import serialize, serialize_list
from util import (
    apply_filters,
    get_json_body,
    paginate,
    parse_iso8601,
    parse_pagination,
    require_int,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("warranty_claims", __name__)

READ_ROLES = ("YardAdmin", "ProjectManager", "CommercialApprover", "ShipownerRep")


def get_claim_or_404(claim_id: str) -> dict:
    claim = db.warranty_claims.get(claim_id)
    if claim is None:
        raise_err(ERR_NOT_FOUND, "WarrantyClaim id does not exist")
    return claim


@bp.route("/v1/warranty-claims", methods=["POST"])
@require_roles("ShipownerRep")
def create_warranty_claim(_user_id: str, _role: str):
    body = get_json_body()
    # Rung 3: well-formedness.
    project_id = require_string(body, "project_id")
    work_item_id = require_string(body, "work_item_id")
    description = require_string(body, "description")

    # Rung 4: referenced ids exist.
    project = db.projects.get(project_id)
    if project is None:
        raise_err(ERR_NOT_FOUND, "RepairProject id does not exist")
    item = db.work_items.get(work_item_id)
    if item is None:
        raise_err(ERR_NOT_FOUND, "WorkItem id does not exist")

    # Rung 6: the filer must be the owning ShipownerRep of the vessel.
    vessel = db.vessels[project["vessel_id"]]
    if _user_id != vessel["owner_user_id"]:
        raise_err(ERR_OWNERSHIP_MISMATCH, "caller is not the vessel's owner representative")

    # Rung 9: the project must be DELIVERED and inside the warranty window;
    # filing exactly at warranty_end_utc is allowed.
    if project["status"] != "DELIVERED" or project.get("warranty_end_utc") is None:
        raise_err(ERR_WARRANTY_EXPIRED, "the project is not in its warranty window")
    if db.clock_dt() > parse_iso8601(project["warranty_end_utc"], "warranty_end_utc"):
        raise_err(ERR_WARRANTY_EXPIRED, "the warranty window has closed")

    # Rung 10: the defective item must belong to the project.
    if item["project_id"] != project_id:
        raise_err(ERR_WORK_ITEM_NOT_IN_PROJECT, "work item belongs to a different project")

    claim = {
        "project_id": project_id,
        "work_item_id": work_item_id,
        "description": description,
        "filed_by_user_id": _user_id,
        "status": "FILED",
        "rework_work_item_id": None,
        "denial_reason": None,
    }
    db.stamp_new(claim)
    db.warranty_claims[claim["id"]] = claim
    return success_object(serialize(claim), 201)


@bp.route("/v1/warranty-claims", methods=["GET"])
@require_roles(*READ_ROLES)
def list_warranty_claims(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.warranty_claims.values()))
    items = apply_filters(items, ["project_id", "work_item_id", "rework_work_item_id", "status"])
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


@bp.route("/v1/warranty-claims/<claim_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_warranty_claim(claim_id: str, _user_id: str, _role: str):
    return success_object(serialize(get_claim_or_404(claim_id)))


@bp.route("/v1/warranty-claims/<claim_id>/accept", methods=["POST"])
@require_roles("ProjectManager")
def accept_warranty_claim(claim_id: str, _user_id: str, _role: str):
    # Rung 3: rework duration is part of well-formedness.
    body = get_json_body()
    rework_duration_days = require_int(body, "rework_duration_days")
    if rework_duration_days < 1:
        raise_err(ERR_INVALID_REQUEST, "rework_duration_days must be >= 1")

    claim = get_claim_or_404(claim_id)
    if claim["status"] != "FILED":
        raise_err(ERR_INVALID_STATE, "accept requires a FILED claim")

    # Materialise the zero-priced rework line; the yard absorbs the cost, so
    # the project's contracted price is unchanged.
    source = db.work_items[claim["work_item_id"]]
    rework = {
        "project_id": claim["project_id"],
        "description": source["description"],
        "trade_code": source["trade_code"],
        "pricing_mode": source["pricing_mode"],
        "quantity": source.get("quantity"),
        "unit_price_cents": source.get("unit_price_cents"),
        "estimated_hours": source.get("estimated_hours"),
        "hourly_rate_cents": source.get("hourly_rate_cents"),
        "materials_cost_cents": source.get("materials_cost_cents", 0),
        "duration_days": rework_duration_days,
        "depends_on_ids": [],
        "requires_hot_work": False,
        "subcontractor_id": None,
        "origin_kind": "WARRANTY_REWORK",
        "origin_change_order_id": None,
        "line_total_cents": 0,
        "status": "PLANNED",
        "completed_at_utc": None,
    }
    db.stamp_new(rework)
    db.work_items[rework["id"]] = rework

    claim["status"] = "ACCEPTED"
    claim["rework_work_item_id"] = rework["id"]
    db.touch(claim)
    return success_object(serialize(claim))


@bp.route("/v1/warranty-claims/<claim_id>/deny", methods=["POST"])
@require_roles("ProjectManager")
def deny_warranty_claim(claim_id: str, _user_id: str, _role: str):
    # Rung 3: a non-empty reason is part of well-formedness.
    body = get_json_body()
    reason = require_string(body, "reason")
    claim = get_claim_or_404(claim_id)
    if claim["status"] != "FILED":
        raise_err(ERR_INVALID_STATE, "deny requires a FILED claim")
    claim["status"] = "DENIED"
    claim["denial_reason"] = reason
    db.touch(claim)
    return success_object(serialize(claim))
