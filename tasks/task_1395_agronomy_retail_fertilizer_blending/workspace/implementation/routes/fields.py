"""Field and SoilTest routes."""

from flask import Blueprint, request, g

import db
from errors import not_found, invalid_transition
from middleware import require_roles, check_grower_ownership, ALL_ROLES
from response import success_object, success_list
from services.core import scaffold_entity, touch, public, now_stamp_helper
from util import (
    get_body, require, optional, reject_unknown, as_string, as_number, as_enum,
    as_int, parse_pagination, paginate, parse_instant,
)

bp = Blueprint("fields", __name__)

WATERSHED_ZONES = {"STANDARD", "PROTECTED", "CRITICAL"}


def _get_grower(gid):
    x = db.growers.get(gid)
    if x is None:
        raise not_found("Grower not found")
    return x


def _get_field(fid):
    x = db.fields.get(fid)
    if x is None:
        raise not_found("Field not found")
    return x


def _get_soil_test(sid):
    x = db.soil_tests.get(sid)
    if x is None:
        raise not_found("Soil test not found")
    return x


# ---------------------------------------------------------------------------
# Fields
# ---------------------------------------------------------------------------

@bp.post("/agronomy/growers/<growerId>/fields")
def create_field(growerId):
    require_roles("Grower", "Agronomist", "BranchAdmin")
    grower = _get_grower(growerId)
    check_grower_ownership(grower["id"])
    body = get_body()
    reject_unknown(body, {"name", "acres", "watershed_zone"})
    name = as_string(require(body, "name"), "name")
    acres = as_number(require(body, "acres"), "acres", minimum=0, exclusive_min=True)
    wz = as_enum(optional(body, "watershed_zone", "STANDARD"), "watershed_zone", WATERSHED_ZONES)
    field = scaffold_entity(db.fields, {
        "grower_id": grower["id"],
        "name": name,
        "acres": float(acres),
        "watershed_zone": wz,
    })
    return success_object(public(field), 201)


@bp.get("/agronomy/growers/<growerId>/fields")
def list_grower_fields(growerId):
    require_roles(*ALL_ROLES)
    grower = _get_grower(growerId)
    check_grower_ownership(grower["id"])
    limit, offset = parse_pagination()
    items = [f for f in db.fields.values() if f["grower_id"] == grower["id"]]
    items.sort(key=lambda x: (x["created_at"], x["id"]))
    total = len(items)
    return success_list([public(x) for x in paginate(items, limit, offset)], limit, offset, total)


@bp.get("/agronomy/fields")
def list_fields():
    require_roles(*ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.fields.values())
    if "grower_id" in request.args:
        gid = request.args["grower_id"]
        items = [f for f in items if f["grower_id"] == gid]
    # Grower-role callers only see their own fields
    if g.role == "Grower":
        items = [f for f in items if f["grower_id"] == g.user_id]
    items.sort(key=lambda x: (x["created_at"], x["id"]))
    total = len(items)
    return success_list([public(x) for x in paginate(items, limit, offset)], limit, offset, total)


@bp.get("/agronomy/fields/<fieldId>")
def get_field(fieldId):
    require_roles(*ALL_ROLES)
    field = _get_field(fieldId)
    check_grower_ownership(field["grower_id"])
    return success_object(public(field))


# ---------------------------------------------------------------------------
# Soil tests
# ---------------------------------------------------------------------------

@bp.post("/agronomy/fields/<fieldId>/soil-tests")
def request_soil_test(fieldId):
    require_roles("Grower", "Agronomist")
    field = _get_field(fieldId)
    check_grower_ownership(field["grower_id"])
    body = get_body()
    reject_unknown(body, {"lab_code"})
    lab_code = optional(body, "lab_code", None)
    if lab_code is not None:
        lab_code = as_string(lab_code, "lab_code")
    st = scaffold_entity(db.soil_tests, {
        "field_id": field["id"],
        "lab_code": lab_code,
        "sampled_at": None,
        "p_ppm": None,
        "k_ppm": None,
        "ph": None,
        "organic_matter_pct": None,
        "status": "REQUESTED",
    })
    return success_object(public(st), 201)


@bp.get("/agronomy/fields/<fieldId>/soil-tests")
def list_soil_tests(fieldId):
    require_roles(*ALL_ROLES)
    field = _get_field(fieldId)
    check_grower_ownership(field["grower_id"])
    limit, offset = parse_pagination()
    items = [s for s in db.soil_tests.values() if s["field_id"] == field["id"]]
    items.sort(key=lambda x: (x["created_at"], x["id"]))
    total = len(items)
    return success_list([public(x) for x in paginate(items, limit, offset)], limit, offset, total)


@bp.get("/agronomy/soil-tests/<soilTestId>")
def get_soil_test(soilTestId):
    require_roles(*ALL_ROLES)
    st = _get_soil_test(soilTestId)
    field = db.fields.get(st["field_id"])
    if field is not None:
        check_grower_ownership(field["grower_id"])
    return success_object(public(st))


@bp.post("/agronomy/soil-tests/<soilTestId>/record-sampling")
def record_sampling(soilTestId):
    require_roles("Agronomist")
    st = _get_soil_test(soilTestId)
    body = get_body()
    reject_unknown(body, {"sampled_at"})
    if st["status"] != "REQUESTED":
        raise invalid_transition("Soil test not REQUESTED")
    if "sampled_at" in body and body["sampled_at"] is not None:
        st["sampled_at"] = now_stamp_helper_from_dt(parse_instant(body["sampled_at"], "sampled_at"))
    else:
        st["sampled_at"] = now_stamp_helper()
    st["status"] = "SAMPLED"
    touch(st)
    return success_object(public(st))


@bp.post("/agronomy/soil-tests/<soilTestId>/post-results")
def post_results(soilTestId):
    require_roles("Agronomist")
    st = _get_soil_test(soilTestId)
    body = get_body()
    reject_unknown(body, {"p_ppm", "k_ppm", "ph", "organic_matter_pct"})
    p_ppm = as_int(require(body, "p_ppm"), "p_ppm", minimum=0)
    k_ppm = as_int(require(body, "k_ppm"), "k_ppm", minimum=0)
    ph = as_number(require(body, "ph"), "ph")
    om = optional(body, "organic_matter_pct", None)
    if om is not None:
        om = float(as_number(om, "organic_matter_pct"))
    if st["status"] != "SAMPLED":
        raise invalid_transition("Soil test not SAMPLED")
    st["p_ppm"] = p_ppm
    st["k_ppm"] = k_ppm
    st["ph"] = float(ph)
    st["organic_matter_pct"] = om
    st["status"] = "RESULTED"
    touch(st)
    return success_object(public(st))


def now_stamp_helper_from_dt(dt):
    from response import iso8601_ms
    return iso8601_ms(dt)
