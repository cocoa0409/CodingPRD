"""Framework: JobFamily, JobLevel, GeoZone, ProgressionPolicy (§3.1)."""
from decimal import Decimal
from flask import Blueprint, request
from db import store, new_id
from middleware import require_roles, get_auth
from response import success_object, success_list
from errors import (
    not_found, invalid_request, invalid_enum, duplicate_policy, geo_cycle,
    referenced_entity_state, already_terminal,
)
from services.common import (
    now_iso, require_fields, parse_int, parse_pagination, sort_by_created_at,
    paginate, bump, parse_positive_number, parse_non_negative_number,
)
from services import geo as geo_svc

bp = Blueprint("framework", __name__)


# ---------------- JobFamily ----------------

def family_view(f):
    return {k: f[k] for k in ("id", "code", "name", "status", "created_at", "updated_at", "version")}


@bp.route("/comp/job-families", methods=["POST"])
def create_family():
    require_roles("CompAdmin")
    body = request.get_json(silent=True) or {}
    require_fields(body, ["code", "name"])
    code = body["code"]
    name = body["name"]
    if not isinstance(code, str) or not code:
        raise invalid_request("code must be a non-empty string")
    if not isinstance(name, str) or not name:
        raise invalid_request("name must be a non-empty string")
    for f in store.job_families.values():
        if f["code"] == code:
            raise invalid_request("code already taken")
    now = now_iso()
    f = {"id": new_id(), "code": code, "name": name, "status": "ACTIVE",
         "created_at": now, "updated_at": now, "version": 1}
    store.job_families[f["id"]] = f
    return success_object(family_view(f), 201)


@bp.route("/comp/job-families", methods=["GET"])
def list_families():
    get_auth()
    limit, offset = parse_pagination(request.args)
    rows = list(store.job_families.values())
    status_filter = request.args.get("status")
    if status_filter is not None:
        if status_filter not in ("ACTIVE", "RETIRED"):
            raise invalid_enum("status is not a declared member")
        rows = [f for f in rows if f["status"] == status_filter]
    rows = sort_by_created_at(rows)
    page, total = paginate(rows, limit, offset)
    return success_list([family_view(f) for f in page], limit, offset, total)


@bp.route("/comp/job-families/<fid>", methods=["GET"])
def get_family(fid):
    get_auth()
    f = store.job_families.get(fid)
    if f is None:
        raise not_found("job family not found")
    return success_object(family_view(f))


@bp.route("/comp/job-families/<fid>/retire", methods=["POST"])
def retire_family(fid):
    require_roles("CompAdmin")
    f = store.job_families.get(fid)
    if f is None:
        raise not_found("job family not found")
    if f["status"] == "RETIRED":
        raise already_terminal("family already RETIRED")
    # Blocked while referenced by non-SUPERSEDED bands or ACTIVE employees' profiles
    for b in store.pay_bands.values():
        if b["job_family_id"] == fid and b["status"] != "SUPERSEDED":
            raise referenced_entity_state("family referenced by non-SUPERSEDED band")
    for e in store.employees.values():
        if e["status"] != "ACTIVE":
            continue
        prof = store.job_profiles.get(e["job_profile_id"])
        if prof is not None and prof["job_family_id"] == fid:
            raise referenced_entity_state("family referenced by ACTIVE employee profile")
    f["status"] = "RETIRED"
    bump(f)
    return success_object(family_view(f))


# ---------------- JobLevel ----------------

def level_view(l):
    return {k: l[k] for k in ("id", "level_code", "title", "rank_order", "scope_criteria",
                              "min_years_experience", "created_at", "updated_at", "version")}


@bp.route("/comp/job-levels", methods=["POST"])
def create_level():
    require_roles("CompAdmin")
    body = request.get_json(silent=True) or {}
    require_fields(body, ["level_code", "title", "rank_order"])
    level_code = body["level_code"]
    if not isinstance(level_code, str) or not level_code:
        raise invalid_request("level_code must be a non-empty string")
    title = body["title"]
    if not isinstance(title, str) or not title:
        raise invalid_request("title must be a non-empty string")
    rank_order = parse_int(body["rank_order"], "rank_order")
    for l in store.job_levels.values():
        if l["level_code"] == level_code:
            raise invalid_request("level_code already taken")
        if l["rank_order"] == rank_order:
            raise invalid_request("rank_order already taken")
    scope_criteria = body.get("scope_criteria")
    min_years = body.get("min_years_experience", 0)
    min_years = parse_int(min_years, "min_years_experience", minimum=0)
    now = now_iso()
    l = {"id": new_id(), "level_code": level_code, "title": title,
         "rank_order": rank_order, "scope_criteria": scope_criteria,
         "min_years_experience": min_years,
         "created_at": now, "updated_at": now, "version": 1}
    store.job_levels[l["id"]] = l
    return success_object(level_view(l), 201)


@bp.route("/comp/job-levels", methods=["GET"])
def list_levels():
    get_auth()
    limit, offset = parse_pagination(request.args)
    rows = sort_by_created_at(list(store.job_levels.values()))
    page, total = paginate(rows, limit, offset)
    return success_list([level_view(l) for l in page], limit, offset, total)


@bp.route("/comp/job-levels/<lid>", methods=["GET"])
def get_level(lid):
    get_auth()
    l = store.job_levels.get(lid)
    if l is None:
        raise not_found("job level not found")
    return success_object(level_view(l))


# ---------------- GeoZone ----------------

def zone_view(z):
    return {k: z[k] for k in ("id", "zone_code", "name", "parent_zone_id",
                              "differential_ratio", "effective_ratio",
                              "created_at", "updated_at", "version")}


@bp.route("/comp/geo-zones", methods=["POST"])
def create_zone():
    require_roles("CompAdmin")
    body = request.get_json(silent=True) or {}
    require_fields(body, ["zone_code", "name", "differential_ratio"])
    zone_code = body["zone_code"]
    if not isinstance(zone_code, str) or not zone_code:
        raise invalid_request("zone_code must be a non-empty string")
    name = body["name"]
    if not isinstance(name, str) or not name:
        raise invalid_request("name must be a non-empty string")
    for z in store.geo_zones.values():
        if z["zone_code"] == zone_code:
            raise invalid_request("zone_code already taken")
    ratio = parse_positive_number(body["differential_ratio"], "differential_ratio")
    parent_id = body.get("parent_zone_id")
    if parent_id is not None:
        if parent_id not in store.geo_zones:
            raise not_found("parent zone not found")
    now = now_iso()
    z = {"id": new_id(), "zone_code": zone_code, "name": name,
         "parent_zone_id": parent_id,
         "differential_ratio": float(ratio),
         "effective_ratio": None,
         "created_at": now, "updated_at": now, "version": 1}
    # Cycle cannot occur on create since zone is new; parent chain walk will terminate.
    store.geo_zones[z["id"]] = z
    z["effective_ratio"] = float(geo_svc.compute_effective_ratio(z))
    return success_object(zone_view(z), 201)


@bp.route("/comp/geo-zones/<zid>", methods=["PATCH"])
def patch_zone(zid):
    require_roles("CompAdmin")
    body = request.get_json(silent=True) or {}
    z = store.geo_zones.get(zid)
    if z is None:
        raise not_found("geo zone not found")
    new_parent = body.get("parent_zone_id", z["parent_zone_id"])
    new_ratio = body.get("differential_ratio", z["differential_ratio"])
    if new_parent is not None and new_parent not in store.geo_zones:
        raise not_found("parent zone not found")
    new_ratio_dec = parse_positive_number(new_ratio, "differential_ratio")
    if geo_svc.would_create_cycle(zid, new_parent):
        raise geo_cycle()
    z["parent_zone_id"] = new_parent
    z["differential_ratio"] = float(new_ratio_dec)
    geo_svc.recompute_subtree(zid)
    bump(z)
    return success_object(zone_view(z))


@bp.route("/comp/geo-zones", methods=["GET"])
def list_zones():
    get_auth()
    limit, offset = parse_pagination(request.args)
    rows = list(store.geo_zones.values())
    parent_filter = request.args.get("parent_zone_id")
    if parent_filter is not None:
        rows = [z for z in rows if z.get("parent_zone_id") == parent_filter]
    rows = sort_by_created_at(rows)
    page, total = paginate(rows, limit, offset)
    return success_list([zone_view(z) for z in page], limit, offset, total)


@bp.route("/comp/geo-zones/<zid>", methods=["GET"])
def get_zone(zid):
    get_auth()
    z = store.geo_zones.get(zid)
    if z is None:
        raise not_found("geo zone not found")
    return success_object(zone_view(z))


# ---------------- ProgressionPolicy ----------------

def policy_view(p):
    return {k: p[k] for k in ("id", "job_family_id", "from_level_id", "to_level_id",
                              "min_midpoint_progression_pct", "max_overlap_pct",
                              "created_at", "updated_at", "version")}


@bp.route("/comp/progression-policies", methods=["POST"])
def create_policy():
    require_roles("CompManager")
    body = request.get_json(silent=True) or {}
    require_fields(body, ["job_family_id", "from_level_id", "to_level_id",
                          "min_midpoint_progression_pct", "max_overlap_pct"])
    fam_id = body["job_family_id"]
    from_id = body["from_level_id"]
    to_id = body["to_level_id"]
    if fam_id not in store.job_families:
        raise not_found("job family not found")
    if from_id not in store.job_levels:
        raise not_found("from level not found")
    if to_id not in store.job_levels:
        raise not_found("to level not found")
    from_lvl = store.job_levels[from_id]
    to_lvl = store.job_levels[to_id]
    if to_lvl["rank_order"] <= from_lvl["rank_order"]:
        raise invalid_request("to_level_id rank_order must exceed from_level_id rank_order")
    min_prog = parse_non_negative_number(body["min_midpoint_progression_pct"], "min_midpoint_progression_pct")
    max_ovl = parse_non_negative_number(body["max_overlap_pct"], "max_overlap_pct")
    for p in store.progression_policies.values():
        if (p["job_family_id"] == fam_id and p["from_level_id"] == from_id
                and p["to_level_id"] == to_id):
            raise duplicate_policy()
    now = now_iso()
    p = {"id": new_id(), "job_family_id": fam_id, "from_level_id": from_id,
         "to_level_id": to_id,
         "min_midpoint_progression_pct": float(min_prog),
         "max_overlap_pct": float(max_ovl),
         "created_at": now, "updated_at": now, "version": 1}
    store.progression_policies[p["id"]] = p
    return success_object(policy_view(p), 201)


@bp.route("/comp/progression-policies", methods=["GET"])
def list_policies():
    get_auth()
    limit, offset = parse_pagination(request.args)
    rows = list(store.progression_policies.values())
    for arg in ("job_family_id", "from_level_id", "to_level_id"):
        v = request.args.get(arg)
        if v is not None:
            rows = [p for p in rows if p[arg] == v]
    rows = sort_by_created_at(rows)
    page, total = paginate(rows, limit, offset)
    return success_list([policy_view(p) for p in page], limit, offset, total)


@bp.route("/comp/progression-policies/<pid>", methods=["GET"])
def get_policy(pid):
    get_auth()
    p = store.progression_policies.get(pid)
    if p is None:
        raise not_found("progression policy not found")
    return success_object(policy_view(p))
