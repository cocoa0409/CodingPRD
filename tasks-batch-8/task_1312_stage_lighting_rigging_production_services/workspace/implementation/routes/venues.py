"""Venue endpoints."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import raise_err, ERR_RESOURCE_NOT_FOUND
from middleware import require_roles
from response import success_object, success_list
from util import (
    apply_filters,
    get_json_body,
    optional_int,
    optional_number,
    paginate,
    parse_pagination,
    require_enum,
    require_int,
    require_number,
    require_string,
    serialize,
    serialize_list,
    sort_by_created_at,
)

bp = Blueprint("venues", __name__)

UNION_RULESETS = {"IATSE", "TEAMSTERS", "NON_UNION"}


def get_venue_or_404(venue_id: str) -> dict:
    venue = db.venues.get(venue_id)
    if venue is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "Venue id does not exist")
    return venue


@bp.route("/venues", methods=["POST"])
@require_roles("ProductionManager")
def create_venue(_user_id: str, _role: str):
    body = get_json_body()
    name = require_string(body, "name")
    union_ruleset = require_enum(body, "union_ruleset", UNION_RULESETS)
    max_point = require_number(body, "max_point_capacity_kg", minimum=0, exclusive_min=True)
    bay_limit = require_number(body, "bay_aggregate_limit_kg", minimum=0, exclusive_min=True)
    house_amps = require_int(body, "house_power_amps_per_phase", minimum=0, exclusive_min=True)
    dock_doors = require_int(body, "dock_doors", minimum=1)
    min_call = optional_number(body, "min_call_hours", 4, minimum=0, exclusive_min=True)
    ot1 = optional_number(body, "ot1_threshold_hours", 8, minimum=0, exclusive_min=True)
    ot2 = optional_number(body, "ot2_threshold_hours", 12, minimum=0, exclusive_min=True)
    turnaround = optional_number(body, "turnaround_min_hours", 8, minimum=0)
    publish_lead = optional_int(body, "crew_call_publish_lead_hours", 48, minimum=0)
    eng_lead = optional_int(body, "engineering_submission_lead_hours", 72, minimum=0)

    venue = {
        "name": name,
        "union_ruleset": union_ruleset,
        "max_point_capacity_kg": max_point,
        "bay_aggregate_limit_kg": bay_limit,
        "house_power_amps_per_phase": house_amps,
        "dock_doors": dock_doors,
        "min_call_hours": min_call,
        "ot1_threshold_hours": ot1,
        "ot2_threshold_hours": ot2,
        "turnaround_min_hours": turnaround,
        "crew_call_publish_lead_hours": publish_lead,
        "engineering_submission_lead_hours": eng_lead,
    }
    db.stamp_new(venue)
    db.venues[venue["id"]] = venue
    return success_object(serialize(venue), 201)


@bp.route("/venues", methods=["GET"])
@require_roles("Any")
def list_venues(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.venues.values()))
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


@bp.route("/venues/<venue_id>", methods=["GET"])
@require_roles("Any")
def get_venue(venue_id: str, _user_id: str, _role: str):
    return success_object(serialize(get_venue_or_404(venue_id)))


@bp.route("/venues/<venue_id>/productions", methods=["GET"])
@require_roles("Any")
def list_venue_productions(venue_id: str, _user_id: str, _role: str):
    get_venue_or_404(venue_id)
    limit, offset = parse_pagination()
    items = [p for p in db.productions.values() if p["venue_id"] == venue_id]
    items = sort_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)
