"""Helpers shared by the route modules: filtering, listing and small guards."""
from db import store
from errors import ApiError
from middleware import ALL_ROLES, authenticate
from reqval import pagination
from response import listing

READ_ROLES = ALL_ROLES


def filtered(collection, specs):
    """Rows of a collection in creation order, narrowed by equality filters."""
    out = []
    for row in store.values(collection):
        keep = True
        for field, value in specs:
            if value is None:
                continue
            if row.get(field) != value:
                keep = False
                break
        if keep:
            out.append(row)
    return out


def list_response(collection, specs):
    limit, offset = pagination()
    return listing(filtered(collection, specs), limit, offset)


def read_one(collection, row_id):
    authenticate(READ_ROLES)
    return store.require(collection, row_id)


def season_of_version(version):
    return store.get("seasons", version["season_id"])


def version_of_leg(leg):
    return store.require("schedule_versions", leg["schedule_version_id"])


def require_season_open(season):
    if season is None or season["status"] != "OPEN":
        raise ApiError("ERR_SEASON_NOT_OPEN")


def require_carrier_active(carrier):
    if carrier is None or carrier["status"] != "ACTIVE":
        raise ApiError("ERR_CARRIER_SUSPENDED")


def decision_of(payload, field, allowed):
    """A two-valued command word such as ACCEPT/REJECT, validated in band 3."""
    from reqval import bad, req_str

    value = req_str(payload, field, 1, 40)
    if value not in allowed:
        bad("Field '%s' must be one of %s." % (field, ", ".join(allowed)))
    return value
