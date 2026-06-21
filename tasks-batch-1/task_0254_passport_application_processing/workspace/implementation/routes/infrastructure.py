"""Acceptance facilities, urgent-travel counters, acceptance agents, adjudicators."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import APIError, ERR_FK_NOT_FOUND, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from middleware import require_auth
from response import ok_array, ok_object
from routes._helpers import (
    get_body,
    order_by_created,
    paginate,
    parse_pagination,
    require_int,
    require_str,
    serialize,
    serialize_list,
    stamp_create,
)

bp = Blueprint("infrastructure", __name__)


# ---- Acceptance facilities ---------------------------------------------------
@bp.route("/acceptance-facilities", methods=["POST"])
def create_facility():
    require_auth(["Adjudicator"])
    body = get_body()
    for f in ("name", "state_code"):
        if f not in body or body.get(f) is None:
            raise APIError(ERR_INVALID_REQUEST, 400, f"Missing required field: {f}")
    name = require_str(body, "name")
    state_code = require_str(body, "state_code")
    if len(state_code) != 2 or not state_code.isupper():
        raise APIError(ERR_INVALID_REQUEST, 400, "state_code must be 2 uppercase letters")
    rec = {"name": name, "state_code": state_code}
    stamp_create(rec, full=True)
    db.acceptance_facilities[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.route("/acceptance-facilities/<rid>", methods=["GET"])
def get_facility(rid):
    require_auth(["Applicant", "AcceptanceAgent", "Adjudicator"])
    rec = db.acceptance_facilities.get(rid)
    if rec is None:
        raise APIError(ERR_NOT_FOUND, 404, "AcceptanceFacility not found")
    return ok_object(serialize(rec), 200)


# ---- Urgent-travel counters --------------------------------------------------
@bp.route("/urgent-travel-counters", methods=["POST"])
def create_counter():
    require_auth(["Adjudicator"])
    body = get_body()
    if "name" not in body or body.get("name") is None:
        raise APIError(ERR_INVALID_REQUEST, 400, "Missing required field: name")
    name = require_str(body, "name")
    buffer_min = 15
    if "cleanup_buffer_minutes" in body and body["cleanup_buffer_minutes"] is not None:
        buffer_min = require_int(body, "cleanup_buffer_minutes")
        if buffer_min < 0:
            raise APIError(ERR_INVALID_REQUEST, 400, "cleanup_buffer_minutes must be >= 0")
    rec = {"name": name, "cleanup_buffer_minutes": buffer_min}
    stamp_create(rec, full=True)
    db.urgent_travel_counters[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.route("/urgent-travel-counters/<rid>", methods=["GET"])
def get_counter(rid):
    require_auth(["Applicant", "AcceptanceAgent", "Adjudicator"])
    rec = db.urgent_travel_counters.get(rid)
    if rec is None:
        raise APIError(ERR_NOT_FOUND, 404, "UrgentTravelCounter not found")
    return ok_object(serialize(rec), 200)


# ---- Acceptance agents -------------------------------------------------------
@bp.route("/acceptance-agents", methods=["POST"])
def create_agent():
    require_auth(["Adjudicator"])
    body = get_body()
    for f in ("name", "badge_number", "facility_id"):
        if f not in body or body.get(f) is None:
            raise APIError(ERR_INVALID_REQUEST, 400, f"Missing required field: {f}")
    name = require_str(body, "name")
    badge = require_str(body, "badge_number")
    facility_id = require_str(body, "facility_id")
    # FK existence (priority 4)
    if facility_id not in db.acceptance_facilities:
        raise APIError(ERR_FK_NOT_FOUND, 422, "facility_id does not exist")
    # unique badge_number
    for a in db.acceptance_agents.values():
        if a["badge_number"] == badge:
            raise APIError(ERR_INVALID_REQUEST, 400, "badge_number already registered")
    rec = {"name": name, "badge_number": badge, "facility_id": facility_id}
    stamp_create(rec, full=True)
    db.acceptance_agents[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.route("/acceptance-agents/<rid>", methods=["GET"])
def get_agent(rid):
    require_auth(["Adjudicator", "AcceptanceAgent"])
    rec = db.acceptance_agents.get(rid)
    if rec is None:
        raise APIError(ERR_NOT_FOUND, 404, "AcceptanceAgent not found")
    return ok_object(serialize(rec), 200)


@bp.route("/acceptance-agents", methods=["GET"])
def list_agents():
    require_auth(["Adjudicator", "AcceptanceAgent"])
    limit, offset = parse_pagination()
    items = list(db.acceptance_agents.values())
    facility_id = request.args.get("facility_id")
    if facility_id is not None:
        items = [a for a in items if a["facility_id"] == facility_id]
    items = order_by_created(items)
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total, 200)


# ---- Adjudicators ------------------------------------------------------------
@bp.route("/adjudicators", methods=["POST"])
def create_adjudicator():
    require_auth(["Adjudicator"])
    body = get_body()
    for f in ("name", "passport_office_code"):
        if f not in body or body.get(f) is None:
            raise APIError(ERR_INVALID_REQUEST, 400, f"Missing required field: {f}")
    name = require_str(body, "name")
    code = require_str(body, "passport_office_code")
    for a in db.adjudicators.values():
        if a["passport_office_code"] == code:
            raise APIError(ERR_INVALID_REQUEST, 400, "passport_office_code already registered")
    rec = {"name": name, "passport_office_code": code}
    stamp_create(rec, full=True)
    db.adjudicators[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.route("/adjudicators/<rid>", methods=["GET"])
def get_adjudicator(rid):
    require_auth(["Adjudicator", "AcceptanceAgent"])
    rec = db.adjudicators.get(rid)
    if rec is None:
        raise APIError(ERR_NOT_FOUND, 404, "Adjudicator not found")
    return ok_object(serialize(rec), 200)
