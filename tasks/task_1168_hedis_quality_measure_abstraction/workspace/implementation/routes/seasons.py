"""Clock + MeasurementSeason + MeasureSpecification routes."""
from flask import Blueprint, request

import errors
from db import db, new_id, parse_dt, format_ts
from middleware import require_roles, get_json_body, require_fields, require_enum, optional_enum, require_int, optional_int, optional_number, require_str
from response import success_object, success_list, parse_pagination
from serializers import season_view, spec_view
from services.core import touch, find_season, find_spec

bp = Blueprint("seasons", __name__)

ADMIN = ["QualityAdmin"]
ALL = ["QualityAdmin", "QualityAnalyst", "Abstractor", "OverReader",
       "ProviderRelations", "Auditor", "QualityDirector"]

SUPPLEMENTAL_SOURCES = {"LAB_FEED", "IMMUNIZATION_REGISTRY", "PHARMACY", "EHR"}


# ---------------------------------------------------------------- clock
@bp.post("/hedis/_clock/set_current_utc")
def set_clock():
    require_roles(ADMIN)
    body = get_json_body()
    require_fields(body, ["to_iso8601"])
    target = parse_dt(body.get("to_iso8601"))
    if target is None:
        raise errors.invalid_request("to_iso8601 must be an ISO8601 datetime")
    db.clock = target
    # side effect: auto-close OPEN seasons whose deadline is strictly earlier
    for s in db.seasons.values():
        if s["status"] == "OPEN" and s["submission_deadline"] < target:
            s["status"] = "SUBMISSION_CLOSED"
            touch(s)
    return success_object({"current_utc": format_ts(db.clock)})


# ---------------------------------------------------------------- seasons
@bp.post("/hedis/seasons")
def create_season():
    require_roles(ADMIN)
    body = get_json_body()
    require_fields(body, ["measurement_year", "submission_deadline",
                          "admin_data_cutoff", "approved_supplemental_sources"])
    year = require_int(body, "measurement_year")
    deadline = parse_dt(body.get("submission_deadline"))
    if deadline is None:
        raise errors.invalid_request("submission_deadline must be an ISO8601 datetime")
    cutoff = parse_dt(body.get("admin_data_cutoff"))
    if cutoff is None:
        raise errors.invalid_request("admin_data_cutoff must be an ISO8601 datetime")
    sources = body.get("approved_supplemental_sources")
    if not isinstance(sources, list) or any(not isinstance(x, str) or x not in SUPPLEMENTAL_SOURCES for x in sources):
        raise errors.invalid_request("approved_supplemental_sources must be drawn from LAB_FEED|IMMUNIZATION_REGISTRY|PHARMACY|EHR")
    rec = {
        "id": new_id(),
        "measurement_year": year,
        "submission_deadline": deadline,
        "admin_data_cutoff": cutoff,
        "approved_supplemental_sources": list(sources),
        "status": "DRAFT",
        "certified_run_count": 0,
        "created_at": db.clock,
        "updated_at": db.clock,
        "version": 1,
    }
    db.seasons[rec["id"]] = rec
    return success_object(season_view(rec), 201)


@bp.get("/hedis/seasons/<seasonId>")
def get_season(seasonId):
    require_roles(ALL)
    s = find_season(seasonId)
    return success_object(season_view(s))


@bp.post("/hedis/seasons/<seasonId>/open")
def open_season(seasonId):
    require_roles(ADMIN)
    s = find_season(seasonId)
    if s["status"] != "DRAFT":
        raise errors.invalid_state("Season must be DRAFT to open")
    s["status"] = "OPEN"
    touch(s)
    return success_object(season_view(s))


@bp.post("/hedis/seasons/<seasonId>/close-submission")
def close_season(seasonId):
    require_roles(ADMIN)
    s = find_season(seasonId)
    if s["status"] != "OPEN":
        raise errors.invalid_state("Season must be OPEN to close submission")
    s["status"] = "SUBMISSION_CLOSED"
    touch(s)
    return success_object(season_view(s))


@bp.get("/hedis/seasons/<id>/measure-specifications")
def list_season_specs(id):
    require_roles(ALL)
    find_season(id)
    items = [sp for sp in db.specs.values() if sp["season_id"] == id]
    status = request.args.get("status")
    if status is not None:
        items = [sp for sp in items if sp["status"] == status]
    items.sort(key=lambda sp: sp["created_at"])
    limit, offset = parse_pagination(request.args)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([spec_view(sp) for sp in page], limit, offset, total)


@bp.get("/hedis/seasons/<id>/audit-engagements")
def list_season_engagements(id):
    require_roles(["QualityAdmin", "QualityAnalyst", "Auditor", "QualityDirector"])
    find_season(id)
    items = [e for e in db.engagements.values() if e["season_id"] == id]
    status = request.args.get("status")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    items.sort(key=lambda e: e["created_at"])
    limit, offset = parse_pagination(request.args)
    total = len(items)
    page = items[offset:offset + limit]
    from serializers import engagement_view
    return success_list([engagement_view(e) for e in page], limit, offset, total)


# ---------------------------------------------------------------- specs
@bp.post("/hedis/measure-specifications")
def create_spec():
    require_roles(ADMIN)
    body = get_json_body()
    require_fields(body, ["season_id", "hedis_measure_code", "version_label",
                          "collection_method", "age_min", "age_max",
                          "continuous_enrollment_months", "anchor_date",
                          "expected_season_version"])
    season = find_season(body.get("season_id") if isinstance(body.get("season_id"), str) else "")
    # OCC (priority 5)
    expected = body.get("expected_season_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise errors.invalid_request("expected_season_version must be an integer")
    if expected != season["version"]:
        raise errors.stale_version()

    code = require_str(body, "hedis_measure_code")
    version_label = require_str(body, "version_label")
    collection_method = require_enum(body, "collection_method", ["ADMINISTRATIVE", "HYBRID"])
    hybrid_policy = optional_enum(body, "hybrid_policy", ["SAMPLE_ONLY", "ADMIN_SUPPLEMENTED"], "SAMPLE_ONLY")
    matching_policy = optional_enum(body, "matching_policy", ["EXACT", "TOLERANT"], "EXACT")
    sample_size_floor = optional_int(body, "sample_size_floor", 411)
    age_min = require_int(body, "age_min")
    age_max = require_int(body, "age_max")
    gender_requirement = optional_enum(body, "gender_requirement", ["ANY", "F", "M"], "ANY")
    cem = require_int(body, "continuous_enrollment_months")
    allowable_gap_days = optional_int(body, "allowable_gap_days", 45)
    anchor = parse_dt(body.get("anchor_date"))
    if anchor is None:
        raise errors.invalid_request("anchor_date must be an ISO8601 datetime")
    reporting_weight = optional_number(body, "reporting_weight", 1.0)

    # uniqueness (priority 10)
    for sp in db.specs.values():
        if sp["season_id"] == season["id"] and sp["hedis_measure_code"] == code:
            raise errors.ApiError(errors.ERR_DUPLICATE_MEASURE_CODE, 409,
                                  "(season_id, hedis_measure_code) already exists")

    rec = {
        "id": new_id(),
        "season_id": season["id"],
        "hedis_measure_code": code,
        "version_label": version_label,
        "collection_method": collection_method,
        "hybrid_policy": hybrid_policy,
        "matching_policy": matching_policy,
        "sample_size_floor": sample_size_floor,
        "age_min": age_min,
        "age_max": age_max,
        "gender_requirement": gender_requirement,
        "continuous_enrollment_months": cem,
        "allowable_gap_days": allowable_gap_days,
        "anchor_date": anchor,
        "reporting_weight": reporting_weight,
        "status": "LOADED",
        "created_at": db.clock,
        "updated_at": db.clock,
        "version": 1,
    }
    db.specs[rec["id"]] = rec
    touch(season)  # spec load increments season version
    return success_object(spec_view(rec), 201)


@bp.get("/hedis/measure-specifications/<specId>")
def get_spec(specId):
    require_roles(ALL)
    sp = find_spec(specId)
    return success_object(spec_view(sp))


@bp.post("/hedis/measure-specifications/<specId>/activate")
def activate_spec(specId):
    require_roles(ADMIN)
    sp = find_spec(specId)
    if sp["status"] != "LOADED":
        raise errors.invalid_state("Spec must be LOADED to activate")
    season = db.seasons.get(sp["season_id"])
    if season is None or season["status"] not in ("DRAFT", "OPEN"):
        raise errors.invalid_state("Spec's season must be DRAFT or OPEN to activate")
    sp["status"] = "ACTIVE"
    touch(sp)
    return success_object(spec_view(sp))


@bp.post("/hedis/measure-specifications/<specId>/retire")
def retire_spec(specId):
    require_roles(ADMIN)
    sp = find_spec(specId)
    if sp["status"] == "ACTIVE":
        # blocked while any pinned run is mid-flight
        for r in db.runs.values():
            if r["spec_id"] == sp["id"] and r["reporting_status"] in (
                    "POPULATION_PENDING", "POPULATED", "RATE_COMPUTED", "SUBMITTED"):
                raise errors.invalid_state("Active runs pin this specification")
    elif sp["status"] != "LOADED":
        raise errors.invalid_state("Spec must be LOADED or ACTIVE to retire")
    sp["status"] = "RETIRED"
    touch(sp)
    return success_object(spec_view(sp))
