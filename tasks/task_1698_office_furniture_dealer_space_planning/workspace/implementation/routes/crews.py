"""Crew routes: DealerAdmin-managed install crews with suspend/activate."""
from flask import Blueprint

from errors import raise_error, ERR_INVALID_STATE
from middleware import ALL_ROLES
from response import success_object
from routes.helpers import authorize, list_response, get_response
from serialize import public
from services.core import get_or_404, new_entity, touch
from validate import body_dict, req_str, req_int

bp = Blueprint("crews", __name__)


@bp.route("/api/crews", methods=["POST"])
def create_crew():
    authorize(["DealerAdmin"])
    body = body_dict()
    dealership_id = req_str(body, "dealership_id")
    name = req_str(body, "name")
    size = req_int(body, "size", minv=1)
    get_or_404("dealerships", dealership_id)
    crew = new_entity("crews", {
        "dealership_id": dealership_id,
        "name": name,
        "size": size,
        "status": "ACTIVE",
    })
    return success_object(public(crew), status=201)


@bp.route("/api/crews", methods=["GET"])
def list_crews():
    authorize(ALL_ROLES)
    return list_response("crews", ["dealership_id", "status"])


@bp.route("/api/crews/<crew_id>", methods=["GET"])
def get_crew(crew_id):
    authorize(ALL_ROLES)
    return get_response("crews", crew_id)


@bp.route("/api/crews/<crew_id>/suspend", methods=["POST"])
def suspend_crew(crew_id):
    authorize(["DealerAdmin"])
    crew = get_or_404("crews", crew_id)
    if crew["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, f"cannot suspend a crew in status {crew['status']}")
    crew["status"] = "SUSPENDED"
    touch(crew)
    return success_object(public(crew))


@bp.route("/api/crews/<crew_id>/activate", methods=["POST"])
def activate_crew(crew_id):
    authorize(["DealerAdmin"])
    crew = get_or_404("crews", crew_id)
    if crew["status"] != "SUSPENDED":
        raise_error(ERR_INVALID_STATE, f"cannot activate a crew in status {crew['status']}")
    crew["status"] = "ACTIVE"
    touch(crew)
    return success_object(public(crew))
