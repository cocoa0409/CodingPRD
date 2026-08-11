"""Funder endpoints."""

import services as S
from db import store
from middleware import ALL_READ_ROLES, actor, body, require_roles
from response import ok, paginate
from util import get_bool, get_enum, get_str

FUNDER_TYPES = ("FEDERAL", "STATE", "FOUNDATION", "CORPORATE")


def create_funder():
    _, role = actor()
    require_roles(role, {"SystemAdmin"})
    data = body()
    funder = S.stamp({
        "name": get_str(data, "name"),
        "funder_type": get_enum(data, "funder_type", FUNDER_TYPES),
        "contact_email": get_str(data, "contact_email"),
        "requires_match": get_bool(data, "requires_match", default=False),
    })
    store["funders"][funder["id"]] = funder
    return ok(S.ser_funder(funder), code=201)


def get_funder(funder_id):
    _, role = actor()
    require_roles(role, ALL_READ_ROLES)
    return ok(S.ser_funder(S.get_funder(funder_id)))


def register(app):
    app.add_url_rule("/funders", "funders_create", create_funder, methods=["POST"])
    app.add_url_rule("/funders/<funder_id>", "funders_get", get_funder, methods=["GET"])
