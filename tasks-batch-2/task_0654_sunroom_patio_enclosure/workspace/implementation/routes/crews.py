"""InstallCrew endpoints (PRD §3.6)."""
from flask import Blueprint

import errors
import response
from db import db
from middleware import require_roles
from services import common, serialize

bp = Blueprint("crews", __name__)


@bp.route("/crews", methods=["POST"])
def create_crew():
    require_roles({"InstallManager"})
    body = common.get_json()

    name = common.require_field(body, "name", expected_types=["string"])
    max_wind_mph = common.require_field(
        body, "max_wind_mph", expected_types=["integer"],
        validator=lambda v: v >= 0)
    certified_four_season = common.optional_field(
        body, "certified_four_season", False, expected_types=["boolean"])
    active = common.optional_field(body, "active", True, expected_types=["boolean"])

    entity = {
        "name": name,
        "max_wind_mph": max_wind_mph,
        "certified_four_season": certified_four_season,
        "active": active,
    }
    common.stamp_create(entity)
    db.install_crews[entity["id"]] = entity
    return response.success(serialize.crew(entity), status=201)


@bp.route("/crews/<cid>", methods=["GET"])
def get_crew(cid):
    require_roles({"InstallManager"})
    crew = common.get_crew(cid)
    return response.success(serialize.crew(crew), status=200)


@bp.route("/crews/<cid>/install-jobs", methods=["GET"])
def list_crew_jobs(cid):
    require_roles({"InstallManager", "SalesDesigner"})
    limit, offset = common.parse_pagination()
    common.get_crew(cid)  # existence (priority 4)
    items = [j for j in db.install_jobs.values() if j["crew_id"] == cid]
    page, total = common.paginate(items, limit, offset)
    return response.array([serialize.install_job(j) for j in page],
                          limit, offset, total)
