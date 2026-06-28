"""Crew endpoints (PRD §3.8)."""
from flask import Blueprint

import db
import errors
import helpers
from middleware import authenticate, authorize, get_json_body
from response import object_response
from serializers import serialize
from services import factory

bp = Blueprint("crews", __name__)


@bp.route("/crews", methods=["POST"])
def create_crew():
    _uid, role = authenticate()
    authorize(role, ["Scheduler"])
    body = get_json_body()
    name = helpers.require_string(body, "name")
    home_region = helpers.require_string(body, "home_region")
    daily_capacity = helpers.require_int(body, "daily_capacity")
    active = helpers.optional_bool(body, "active", True)
    # daily_capacity >= 1 (SCAFFOLD §1.1).
    if daily_capacity < 1:
        raise errors.err(errors.ERR_VALIDATION, "daily_capacity must be at least 1")
    entity = factory.create_crew(name, home_region, daily_capacity, active)
    return object_response(serialize(entity), status=201)


@bp.route("/crews/<crew_id>", methods=["GET"])
def get_crew(crew_id):
    _uid, role = authenticate()
    authorize(role, ["Scheduler"])
    entity = helpers.find_or_404(db.crews, crew_id)
    return object_response(serialize(entity), status=200)
