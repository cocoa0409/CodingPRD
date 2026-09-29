"""Seasonal campaigns and survey sites."""
from decimal import Decimal

from flask import Blueprint

import calc
import db
import guards
import response
import services
from errors import ApiError

bp = Blueprint("campaigns", __name__)

HABITATS = ["WETLAND", "FOREST", "GRASSLAND", "URBAN", "COASTAL"]
ALL_ROLES = ["ProgramAdmin", "Volunteer", "Expert", "ResearchPartner"]


def _page(rows, filters):
    rows = guards.apply_filters(rows, filters)
    page, limit, offset, total = guards.paginate(rows)
    return response.list_response([db.serialize(r) for r in page], limit, offset, total)


def _windows_intersect(a_start, a_end, b_start, b_end):
    return not (a_end < b_start or b_end < a_start)


@bp.post("/citizen-science/campaigns")
def create_campaign():
    guards.authenticate(["ProgramAdmin"])
    body = guards.validate_body([
        {"name": "name", "type": "string", "required": True},
        {"name": "protocol_id", "type": "id", "required": True},
        {"name": "season_start_date", "type": "date", "required": True},
        {"name": "season_end_date", "type": "date", "required": True},
        {"name": "target_observations_per_site", "type": "integer", "required": True, "gt": 0},
    ])
    if body["season_end_date"] < body["season_start_date"]:
        raise ApiError("ERR_INVALID_REQUEST")

    guards.get_protocol(body["protocol_id"])

    for other in db.campaigns.values():
        if other["protocol_id"] != body["protocol_id"]:
            continue
        if other["status"] == "ARCHIVED":
            continue
        if _windows_intersect(body["season_start_date"], body["season_end_date"],
                              other["_season_start"], other["_season_end"]):
            raise ApiError("ERR_SEASON_WINDOW_CONFLICT")

    row = db.new_row({
        "name": body["name"],
        "protocol_id": body["protocol_id"],
        "season_start_date": body["season_start_date"].isoformat(),
        "season_end_date": body["season_end_date"].isoformat(),
        "status": "PLANNED",
        "target_observations_per_site": body["target_observations_per_site"],
        "coverage_score": calc.rnd(Decimal("0.0"), 4),
        "gap_count": 0,
        "site_count": 0,
        "accepted_observation_count": 0,
    })
    row["_season_start"] = body["season_start_date"]
    row["_season_end"] = body["season_end_date"]
    db.campaigns[row["id"]] = row
    return response.object_response(db.serialize(row), 201)


@bp.get("/citizen-science/campaigns")
def list_campaigns():
    actor = guards.authenticate(ALL_ROLES)
    guards.resolve_actor(actor)
    return _page(db.all_rows(db.campaigns), ["protocol_id", "status"])


@bp.get("/citizen-science/campaigns/<pid>")
def read_campaign(pid):
    actor = guards.authenticate(ALL_ROLES)
    row = guards.get_campaign(pid)
    guards.resolve_actor(actor)
    return response.object_response(db.serialize(row))


@bp.post("/citizen-science/campaigns/<pid>/open")
def open_campaign(pid):
    guards.authenticate(["ProgramAdmin"])
    campaign = guards.get_campaign(pid)
    if campaign["status"] not in ("PLANNED", "CLOSED"):
        raise ApiError("ERR_CAMPAIGN_NOT_OPEN")
    protocol = db.protocols.get(campaign["protocol_id"])
    if protocol is None or protocol["status"] != "ACTIVE":
        raise ApiError("ERR_PROTOCOL_NOT_ACTIVE")
    if campaign["site_count"] < 1:
        raise ApiError("ERR_CAMPAIGN_HAS_NO_SITES")

    campaign["status"] = "OPEN"
    db.touch(campaign)
    services.recompute_coverage(campaign)
    return response.object_response(db.serialize(campaign))


@bp.post("/citizen-science/campaigns/<pid>/close")
def close_campaign(pid):
    guards.authenticate(["ProgramAdmin"])
    campaign = guards.get_campaign(pid)
    if campaign["status"] != "OPEN":
        raise ApiError("ERR_CAMPAIGN_NOT_OPEN")
    in_flight = any(o["review_status"] in ("SUBMITTED", "UNDER_REVIEW", "NEEDS_REVISION")
                    for o in services.campaign_observations(campaign["id"]))
    if in_flight:
        raise ApiError("ERR_OPEN_REVIEWS_PENDING")
    if campaign["site_count"] < 1:
        raise ApiError("ERR_CAMPAIGN_HAS_NO_SITES")

    campaign["status"] = "CLOSED"
    db.touch(campaign)
    services.recompute_coverage(campaign)
    return response.object_response(db.serialize(campaign))


@bp.post("/citizen-science/campaigns/<pid>/sites")
def create_site(pid):
    guards.authenticate(["ProgramAdmin"])
    campaign = guards.get_campaign(pid)
    body = guards.validate_body([
        {"name": "site_code", "type": "string", "required": True},
        {"name": "latitude", "type": "number", "required": True},
        {"name": "longitude", "type": "number", "required": True},
        {"name": "habitat_type", "type": "enum", "required": True, "values": HABITATS},
        {"name": "priority_weight", "type": "number", "required": False,
         "min": Decimal("0.50"), "max": Decimal("2.00"), "default": Decimal("1.0")},
    ])
    if campaign["status"] in ("PUBLISHED", "ARCHIVED"):
        raise ApiError("ERR_CAMPAIGN_NOT_OPEN")
    guards.require_unique(db.sites, "site_code", body["site_code"],
                          "campaign_id", campaign["id"])

    row = db.new_row({
        "campaign_id": campaign["id"],
        "site_code": body["site_code"],
        "latitude": body["latitude"],
        "longitude": body["longitude"],
        "habitat_type": body["habitat_type"],
        "priority_weight": body["priority_weight"],
        "accepted_observation_count": 0,
        "coverage_ratio": calc.rnd(Decimal("0.0"), 2),
        "coverage_status": "GAP",
    })
    db.sites[row["id"]] = row

    db.touch(campaign)
    services.recompute_coverage(campaign)
    return response.object_response(db.serialize(row), 201)


@bp.get("/citizen-science/campaigns/<pid>/sites")
def list_sites(pid):
    actor = guards.authenticate(ALL_ROLES)
    campaign = guards.get_campaign(pid)
    guards.resolve_actor(actor)
    rows = services.campaign_sites(campaign["id"])
    return _page(rows, ["coverage_status"])
