"""Technician endpoints."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import raise_err, ERR_INVALID_REQUEST, ERR_RESOURCE_NOT_FOUND
from middleware import require_roles
from response import success_object, success_list
from util import (
    get_json_body,
    paginate,
    parse_pagination,
    require_enum,
    require_int,
    require_string,
    serialize,
    serialize_list,
    sort_by_created_at,
)

bp = Blueprint("technicians", __name__)

CLASSIFICATIONS = {"LIGHTING_TECH", "RIGGER", "STAGEHAND"}


def get_technician_or_404(technician_id: str) -> dict:
    tech = db.technicians.get(technician_id)
    if tech is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "Technician id does not exist")
    return tech


@bp.route("/technicians", methods=["POST"])
@require_roles("ProductionManager")
def create_technician(_user_id: str, _role: str):
    body = get_json_body()
    full_name = require_string(body, "full_name")
    union_card_no = require_string(body, "union_card_no")
    classification = require_enum(body, "classification", CLASSIFICATIONS)
    hourly_rate = require_int(body, "hourly_rate_cents", minimum=0, exclusive_min=True)

    # Unique-attribute collisions are schema-category failures (400).
    for tech in db.technicians.values():
        if tech["union_card_no"] == union_card_no:
            raise_err(ERR_INVALID_REQUEST, "union_card_no already registered")

    tech = {
        "full_name": full_name,
        "union_card_no": union_card_no,
        "classification": classification,
        "hourly_rate_cents": hourly_rate,
    }
    db.stamp_new(tech)
    db.technicians[tech["id"]] = tech
    return success_object(serialize(tech), 201)


@bp.route("/technicians/<technician_id>", methods=["GET"])
@require_roles("Any")
def get_technician(technician_id: str, _user_id: str, _role: str):
    return success_object(serialize(get_technician_or_404(technician_id)))


@bp.route("/technicians/<technician_id>/crew-assignments", methods=["GET"])
@require_roles("Any")
def list_technician_assignments(technician_id: str, _user_id: str, _role: str):
    get_technician_or_404(technician_id)
    limit, offset = parse_pagination()
    items = [a for a in db.crew_assignments.values() if a["technician_id"] == technician_id]
    items = sort_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)
