"""School endpoints: create, get, list per district."""

from flask import Blueprint

from db import STORE, new_entity, public
from errors import raise_err, ERR_DISTRICT_NOT_FOUND, ERR_SCHOOL_NOT_FOUND
from middleware import auth_context, require_role, ALL_ROLES
from response import ok, paginated
from validate import body, req_str, req_int, opt_enum

bp = Blueprint("schools", __name__)

HTF_TIERS = ("NONE", "MODERATE", "HIGH")


@bp.route("/schools", methods=["POST"])
def create_school():
    _, role = auth_context()
    data = body()
    district_id = req_str(data, "district_id")
    name = req_str(data, "name")
    total = req_int(data, "coverage_budget_total_cents")
    tier = opt_enum(data, "hard_to_fill_tier", HTF_TIERS, "NONE")
    require_role(role, ["DistrictAdmin"])
    if district_id not in STORE.districts:
        raise_err(ERR_DISTRICT_NOT_FOUND, "district id does not exist")
    s = new_entity(STORE.schools, {
        "district_id": district_id,
        "name": name,
        "hard_to_fill_tier": tier,
        "coverage_budget_total_cents": total,
        "coverage_budget_committed_cents": 0,
        "coverage_budget_spent_cents": 0,
    })
    return ok(serialize_school(s), status=201)


def serialize_school(s):
    out = public(s)
    out["coverage_budget_available_cents"] = (
        s["coverage_budget_total_cents"]
        - s["coverage_budget_committed_cents"]
        - s["coverage_budget_spent_cents"])
    return out


@bp.route("/schools/<sid>", methods=["GET"])
def get_school(sid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    s = STORE.schools.get(sid)
    if s is None:
        raise_err(ERR_SCHOOL_NOT_FOUND, "school id does not exist")
    return ok(serialize_school(s))


@bp.route("/districts/<did>/schools", methods=["GET"])
def list_district_schools(did):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    if did not in STORE.districts:
        raise_err(ERR_DISTRICT_NOT_FOUND, "district id does not exist")
    items = sorted((s for s in STORE.schools.values() if s["district_id"] == did),
                   key=lambda s: (s["created_at"], s["_seq"]))
    page, meta = paginated(items)
    return ok([serialize_school(s) for s in page], pagination=meta)
