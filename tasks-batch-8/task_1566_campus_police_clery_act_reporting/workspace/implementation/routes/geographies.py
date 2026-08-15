"""Clery geography registry."""

from flask import Blueprint, request

from core import (db, enum_or_422, err, get_body, get_or_404, mint, opt_bool,
                  opt_str, paginate, pub, require_roles, success, touch,
                  _MISSING)

bp = Blueprint("geographies", __name__)

CATEGORIES = {"ON_CAMPUS", "ON_CAMPUS_RESIDENTIAL", "NON_CAMPUS", "PUBLIC_PROPERTY"}
GEO_STATUSES = {"ACTIVE", "RETIRED"}


@bp.post("/clery-geographies")
@require_roles("SystemAdmin")
def create_geography():
    data = get_body()
    name = data.get("name", _MISSING)
    if name is _MISSING or not isinstance(name, str):
        err("ERR_INVALID_REQUEST", 400, "Field name must be a string")
    category = data.get("category", _MISSING)
    if category is _MISSING or not isinstance(category, str):
        err("ERR_INVALID_REQUEST", 400, "Field category must be a string")
    is_res = opt_bool(data, "is_residential_facility", False)
    enum_or_422(category, CATEGORIES, "category")
    geo = mint({"name": name, "category": category,
                "is_residential_facility": is_res, "status": "ACTIVE"})
    db.geographies[geo["id"]] = geo
    return success(pub(geo), 201)


@bp.get("/clery-geographies")
@require_roles("SystemAdmin", "CleryCoordinator", "PoliceChief", "FederalReviewer")
def list_geographies():
    items = list(db.geographies.values())
    cat = request.args.get("category")
    if cat is not None:
        items = [e for e in items if e["category"] == cat]
    st = request.args.get("status")
    if st is not None:
        items = [e for e in items if e["status"] == st]
    window, page = paginate(items)
    return success([pub(e) for e in window], 200, page)


@bp.get("/clery-geographies/<gid>")
@require_roles("SystemAdmin", "CleryCoordinator", "PoliceChief", "FederalReviewer")
def get_geography(gid):
    return success(pub(get_or_404(db.geographies, gid)), 200)


@bp.patch("/clery-geographies/<gid>")
@require_roles("SystemAdmin")
def update_geography(gid):
    data = get_body()
    name = data.get("name", _MISSING)
    is_res = data.get("is_residential_facility", _MISSING)
    new_status = data.get("status", _MISSING)
    if name is not _MISSING and not isinstance(name, str):
        err("ERR_INVALID_REQUEST", 400, "Field name must be a string")
    if is_res is not _MISSING and not isinstance(is_res, bool):
        err("ERR_INVALID_REQUEST", 400, "Field is_residential_facility must be a boolean")
    if new_status is not _MISSING and not isinstance(new_status, str):
        err("ERR_INVALID_REQUEST", 400, "Field status must be a string")
    geo = get_or_404(db.geographies, gid)
    if new_status == "RETIRED" and geo["status"] != "RETIRED":
        for inc in db.incidents.values():
            if (inc["geography_id"] == gid
                    and inc["status"] not in ("UNFOUNDED", "WITHDRAWN")):
                err("ERR_GEOGRAPHY_IN_USE", 409,
                    "Geography referenced by a non-terminal incident report")
        for fi in db.fire_incidents.values():
            if fi["geography_id"] == gid:
                err("ERR_GEOGRAPHY_IN_USE", 409,
                    "Geography referenced by a fire incident")
    if new_status is not _MISSING:
        enum_or_422(new_status, GEO_STATUSES, "status")
    if name is not _MISSING:
        geo["name"] = name
    if is_res is not _MISSING:
        geo["is_residential_facility"] = is_res
    if new_status is not _MISSING:
        geo["status"] = new_status
    touch(geo)
    return success(pub(geo), 200)
