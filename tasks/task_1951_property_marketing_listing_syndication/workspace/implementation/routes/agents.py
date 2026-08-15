from flask import Blueprint

import clock
from db import store
from errors import ApiError, ERR_DUPLICATE_LICENSE
from middleware import (
    authenticate, require_roles, get_body, f_str, paginate,
)
from response import success_object, success_list
from services.ops import stamp
from services.serialize import agent_json

bp = Blueprint("agents", __name__)

READ_ROLES = ("ListingAgent", "MarketingCoordinator", "ComplianceOfficer",
              "MarketingDirector")


@bp.route("/agents", methods=["POST"])
def create_agent():
    _, role = authenticate()
    require_roles(role, ("MarketingDirector",))
    body = get_body()
    full_name = f_str(body, "full_name", required=True)
    license_number = f_str(body, "license_number", required=True)
    email = f_str(body, "email", required=True)
    if any(a["license_number"] == license_number for a in store.agents.values()):
        raise ApiError(ERR_DUPLICATE_LICENSE, 409,
                       "license_number already exists")
    now = clock.now()
    agent = stamp({
        "full_name": full_name,
        "license_number": license_number,
        "email": email,
    }, now)
    store.agents[agent["id"]] = agent
    return success_object(agent_json(agent), status=201)


@bp.route("/agents", methods=["GET"])
def list_agents():
    _, role = authenticate()
    require_roles(role, READ_ROLES)
    items = sorted(store.agents.values(),
                   key=lambda a: (a["created_at"], a["_seq"]))
    page, limit, offset, total = paginate(items)
    return success_list([agent_json(a) for a in page], limit, offset, total)
