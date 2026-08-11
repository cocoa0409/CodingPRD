"""SchoolSite endpoints."""
from flask import Blueprint, request

from db import new_record, public, store
from middleware import ALL_ROLES, authenticate, require_roles, scope_district
from response import success
from validation import (
    body,
    get_or_404,
    opt_str,
    paginate,
    parse_pagination,
    req_int,
    req_str,
)

bp = Blueprint("school_sites", __name__)


@bp.route("/v1/school-sites", methods=["POST"])
def create_school_site():
    caller = authenticate()
    require_roles(caller, ["DistrictBuyer"])
    data = body()

    district_id = data.get("district_id")
    # priority 3: ownership scope (when the FK resolves)
    if isinstance(district_id, str):
        existing = store.districts.get(district_id)
        if existing is not None:
            scope_district(caller, existing["id"])
    # priority 4: body FK existence
    if isinstance(district_id, str):
        get_or_404(store.districts, district_id, "district")
    # priority 5: shape
    district_id = req_str(data, "district_id")
    name = req_str(data, "name")
    capacity = req_int(data, "daily_crew_capacity", minimum=1)
    address = opt_str(data, "address", default=None)

    rec = new_record({
        "district_id": district_id,
        "name": name,
        "daily_crew_capacity": capacity,
        "address": address,
    })
    store.school_sites[rec["id"]] = rec
    return success(public(rec), code=201)


@bp.route("/v1/school-sites/<rid>", methods=["GET"])
def get_school_site(rid):
    caller = authenticate()
    require_roles(caller, ALL_ROLES)
    rec = get_or_404(store.school_sites, rid, "school site")
    return success(public(rec), code=200)


@bp.route("/v1/school-sites", methods=["GET"])
def list_school_sites():
    caller = authenticate()
    require_roles(caller, ALL_ROLES)
    limit, offset = parse_pagination()
    records = list(store.school_sites.values())
    district_id = request.args.get("district_id")
    if district_id is not None:
        records = [r for r in records if r["district_id"] == district_id]
    page, pg = paginate(records, limit, offset)
    return success([public(r) for r in page], code=200, response_type="array", pagination=pg)
