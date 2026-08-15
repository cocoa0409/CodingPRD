"""SewerDistrict endpoints."""
from flask import Blueprint

import db
from middleware import get_actor, require_roles
from response import success_object, success_list
from errors import err_invalid_request, err_conflict
from services.common import (
    body, require_string, require_number, require_int, parse_pagination, paginate,
    get_district, sweep_notice_expiry,
)

bp = Blueprint("districts", __name__)

ALL_ROLES = ["DistrictEngineer", "Coder", "QaReviewer", "CrewLead", "CustomerServiceRep"]


def district_view(d):
    return {
        "id": d["id"],
        "name": d["name"],
        "ii_reduction_target_pct": d["ii_reduction_target_pct"],
        "notice_lead_hours": d["notice_lead_hours"],
        "warranty_months": d["warranty_months"],
        "budget_cents": d["budget_cents"],
        "budget_committed_cents": d["budget_committed_cents"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


@bp.post("/sewer/districts")
def create_district():
    actor = get_actor()
    require_roles(actor, ["DistrictEngineer"])
    payload = body()
    name = require_string(payload, "name")
    target = require_number(payload, "ii_reduction_target_pct")
    if target < 0 or target > 100:
        raise err_invalid_request("ii_reduction_target_pct must be 0-100")
    budget = require_int(payload, "budget_cents")
    notice_lead = payload.get("notice_lead_hours", 48)
    if not isinstance(notice_lead, int) or isinstance(notice_lead, bool) or notice_lead < 0:
        raise err_invalid_request("notice_lead_hours must be a non-negative integer")
    warranty_months = payload.get("warranty_months", 12)
    if not isinstance(warranty_months, int) or isinstance(warranty_months, bool) or warranty_months < 0:
        raise err_invalid_request("warranty_months must be a non-negative integer")
    # name uniqueness across the API
    for d in db.districts.values():
        if d["name"] == name:
            raise err_invalid_request("name must be unique")
    ent = {
        "id": db.new_id(),
        "name": name,
        "ii_reduction_target_pct": target,
        "notice_lead_hours": notice_lead,
        "warranty_months": warranty_months,
        "budget_cents": budget,
        "budget_committed_cents": 0,
    }
    db.stamp_new(ent)
    db.districts[ent["id"]] = ent
    sweep_notice_expiry()
    return success_object(district_view(ent), status=201)


@bp.get("/sewer/districts/<id>")
def get_district_route(id):
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    d = get_district(id)
    return success_object(district_view(d))


@bp.get("/sewer/districts")
def list_districts():
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.districts.values())
    page, total = paginate(items, limit, offset)
    return success_list([district_view(d) for d in page], limit, offset, total)
