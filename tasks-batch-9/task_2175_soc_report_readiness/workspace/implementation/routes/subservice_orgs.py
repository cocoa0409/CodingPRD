from flask import Blueprint, request

import auth
import calcs
import services
import store
import validators as v
from auth import ALL_ROLES
from envelope import ok, ok_page
from errors import ApiError
from store import DB

bp = Blueprint("subservice_orgs", __name__)

METHODS = ("CARVE_OUT", "INCLUSIVE")


@bp.post("/soc/subservice-organizations")
def create_org():
    auth.authenticate({"ComplianceLead"})
    body = auth.body()
    engagement = v.fk(body, "engagement_id", "engagements")
    v.req_id(body, "engagement_id")
    name = v.req_str(body, "name", 1, 200)
    services_provided = v.req_str(body, "services_provided", 1, 1000)
    coverage_start = v.req_dt(body, "coverage_start")
    coverage_end = v.req_dt(body, "coverage_end")
    if coverage_end < coverage_start:
        raise ApiError("ERR_VALIDATION")

    for row in DB["subservice_organizations"].values():
        if row["engagement_id"] == engagement["id"] and row["name"] == name:
            raise ApiError("ERR_DUPLICATE_RESOURCE")

    row = store.new_row(
        "subservice_organizations",
        {
            "engagement_id": engagement["id"],
            "name": name,
            "services_provided": services_provided,
            "method": "CARVE_OUT",
            "coverage_start": store.fmt_iso(coverage_start),
            "coverage_end": store.fmt_iso(coverage_end),
            "csoc_articulated": False,
            "csoc_narrative": None,
            "inclusive_control_count": 0,
            "carved_out_at": None,
        },
    )
    return ok(store.public(row), 201)


@bp.get("/soc/subservice-organizations/<subservice_organization_id>")
def read_org(subservice_organization_id):
    auth.authenticate(ALL_ROLES)
    row = store.get_or_404("subservice_organizations", subservice_organization_id)
    return ok(store.public(row))


@bp.get("/soc/subservice-organizations")
def list_orgs():
    auth.authenticate(ALL_ROLES)
    limit, offset = auth.pagination()
    items = store.rows("subservice_organizations")
    for key in ("engagement_id", "method"):
        value = request.args.get(key)
        if value is not None:
            items = [r for r in items if r[key] == value]
    page, total = auth.paginate(items, limit, offset)
    return ok_page([store.public(r) for r in page], limit, offset, total)


@bp.post("/soc/subservice-organizations/<subservice_organization_id>/set-method")
def set_method(subservice_organization_id):
    auth.authenticate({"ComplianceLead"})
    row = store.get_or_404("subservice_organizations", subservice_organization_id)
    body = auth.body()
    method = v.req_enum(body, "method", METHODS)
    narrative = v.opt_str(body, "csoc_narrative", 1, 5000)

    engagement = DB["engagements"][row["engagement_id"]]
    services.require_phase(engagement, {"SCOPING", "READINESS"})

    if method == row["method"]:
        raise ApiError("ERR_TRANSITION_NOT_ALLOWED")

    if method == "CARVE_OUT":
        if narrative is None:
            raise ApiError("ERR_INVALID_STATE")
        services.switch_to_carve_out(row, engagement, narrative)
    else:
        this_start = store.parse_iso(row["coverage_start"])
        this_end = store.parse_iso(row["coverage_end"])
        for other in store.rows("subservice_organizations"):
            if other["id"] == row["id"]:
                continue
            if other["engagement_id"] != engagement["id"]:
                continue
            if other["method"] != "INCLUSIVE":
                continue
            other_start = store.parse_iso(other["coverage_start"])
            other_end = store.parse_iso(other["coverage_end"])
            if this_end <= other_end:
                earlier_end, later_start = this_end, other_start
            else:
                earlier_end, later_start = other_end, this_start
            clear = store.floor_days(later_start, earlier_end) - 1
            if clear < calcs.SUBSERVICE_BUFFER_DAYS:
                raise ApiError("ERR_SUBSERVICE_WINDOW_BUFFER")
        services.switch_to_inclusive(row, engagement)

    return ok(store.public(row))
