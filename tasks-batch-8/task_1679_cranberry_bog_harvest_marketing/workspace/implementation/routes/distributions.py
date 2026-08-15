"""PatronageDistribution endpoints: get, list, approve/pay transitions."""
from flask import Blueprint

from db import store, touch
from errors import ApiError
from middleware import authenticate, require_roles, ANY_ROLE
from response import ok, paginate
from validation import get_body, req_enum

bp = Blueprint("distributions", __name__)

DISTRIBUTION_STATUSES = {"COMPUTED", "APPROVED", "PAID"}
DISTRIBUTION_TRANSITIONS = {
    ("COMPUTED", "APPROVED"),
    ("APPROVED", "PAID"),
}


@bp.get("/coop/distributions/<distribution_id>")
def get_distribution(distribution_id):
    _, role = authenticate()
    require_roles(role, ANY_ROLE)
    dist = store.distributions.get(distribution_id)
    if dist is None:
        raise ApiError("ERR_NOT_FOUND", 404, "PatronageDistribution not found")
    return ok(dist)


@bp.get("/coop/distributions")
def list_distributions():
    _, role = authenticate()
    require_roles(role, ANY_ROLE)
    rows = list(store.distributions.values())
    rows = paginate.filter(rows, "pool_id")
    rows = paginate.filter(rows, "member_id")
    rows = paginate.filter(rows, "status")
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.post("/coop/distributions/<distribution_id>/transition")
def transition_distribution(distribution_id):
    body = get_body()
    to = req_enum(body, "to", DISTRIBUTION_STATUSES)

    _, role = authenticate()
    require_roles(role, {"PoolManager"})

    dist = store.distributions.get(distribution_id)
    if dist is None:
        raise ApiError("ERR_NOT_FOUND", 404, "PatronageDistribution not found")

    if (dist["status"], to) not in DISTRIBUTION_TRANSITIONS:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Distribution transition %s -> %s is not defined"
                       % (dist["status"], to))

    dist["status"] = to
    touch(dist)
    return ok(dist)
