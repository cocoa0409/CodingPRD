"""Fixture endpoints."""
from flask import Blueprint

from db import store
from errors import ERR_INVALID_REQUEST, raise_err
from helpers import (
    body_json,
    check_enum,
    check_integer,
    check_number,
    check_string,
    paginate,
    parse_pagination,
    stamp_new,
)
from middleware import require_roles, STAFF_ROLES
from response import success_list, success_object
from serializers import fixture_view
from services.pricing import amortization_cents_per_use

bp = Blueprint("fixtures", __name__)


@bp.route("/fixtures", methods=["POST"])
def create_fixture():
    user_id, role = require_roles({"ShopManager"})
    data = body_json()
    fixture_code = check_string(data, "fixture_code", required=True)
    routing_mode = check_enum(data, "routing_mode", {"RACK", "BARREL"}, required=True)
    capacity_dm2 = check_number(data, "capacity_dm2", required=True, gt=0)
    purchase_cost_cents = check_integer(data, "purchase_cost_cents", required=True, gte=0)
    rated_uses = check_integer(data, "rated_uses", required=True, gte=1)

    # Uniqueness of fixture_code (tier 10 structural)
    for f in store.fixtures.values():
        if f["fixture_code"] == fixture_code:
            raise_err(ERR_INVALID_REQUEST, "fixture_code must be unique")

    fixture = stamp_new({
        "fixture_code": fixture_code,
        "routing_mode": routing_mode,
        "capacity_dm2": capacity_dm2,
        "purchase_cost_cents": purchase_cost_cents,
        "rated_uses": rated_uses,
        "amortization_cents_per_use": amortization_cents_per_use(purchase_cost_cents, rated_uses),
    })
    store.fixtures[fixture["id"]] = fixture
    return success_object(fixture_view(fixture), status=201)


@bp.route("/fixtures", methods=["GET"])
def list_fixtures():
    user_id, role = require_roles(STAFF_ROLES)
    limit, offset = parse_pagination()
    items = sorted(store.fixtures.values(), key=lambda f: (f["created_at"], f["id"]))
    page, total = paginate(items, limit, offset)
    return success_list([fixture_view(f) for f in page], limit, offset, total)
