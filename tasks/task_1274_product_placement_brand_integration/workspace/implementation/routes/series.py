"""Series / Episode / ScriptOpportunity endpoints."""
from flask import Blueprint

import db
import errors
import middleware
import response
import util

bp = Blueprint("series", __name__)

POLICIES = ["STANDARD", "STRICT"]


def series_view(s):
    return {k: s[k] for k in ("id", "name", "network_name", "clearance_policy",
                              "created_at", "updated_at", "version")}


def episode_view(e):
    return {k: e[k] for k in ("id", "series_id", "episode_number", "runtime_seconds",
                              "air_date", "created_by_user_id", "status",
                              "created_at", "updated_at", "version")}


def opportunity_view(o):
    return {k: o[k] for k in ("id", "episode_id", "scene_description",
                              "start_timecode_seconds", "end_timecode_seconds",
                              "estimated_exposure_seconds", "status",
                              "created_at", "updated_at", "version")}


@bp.route("/series", methods=["POST"])
def create_series():
    middleware.require_roles("AgencyAdmin")
    body = middleware.get_json_body()
    name = util.req_str(body, "name")
    network_name = util.req_str(body, "network_name")
    policy = util.opt_enum(body, "clearance_policy", POLICIES, "STANDARD")
    ent = util.new_entity()
    ent.update({"name": name, "network_name": network_name, "clearance_policy": policy})
    db.series[ent["id"]] = ent
    return response.success_object(series_view(ent), 201)


@bp.route("/series/<sid>", methods=["GET"])
def get_series(sid):
    middleware.require_roles(*middleware.ALL_ROLES)
    s = db.series.get(sid)
    if s is None:
        raise errors.not_found("Series not found")
    return response.success_object(series_view(s))


@bp.route("/series/<sid>/episodes", methods=["POST"])
def create_episode(sid):
    user_id, _ = middleware.require_roles("ProductionRep")
    body = middleware.get_json_body()
    ep_num = util.req_int(body, "episode_number", minimum=1)
    runtime = util.req_int(body, "runtime_seconds", minimum=1)
    air_date_raw = util.req_str(body, "air_date")
    util.parse_iso(air_date_raw)  # validate
    s = db.series.get(sid)
    if s is None:
        raise errors.not_found("Series not found")
    ent = util.new_entity()
    ent.update({"series_id": sid, "episode_number": ep_num, "runtime_seconds": runtime,
                "air_date": air_date_raw, "created_by_user_id": user_id,
                "status": "SCRIPT_REVIEW"})
    db.episodes[ent["id"]] = ent
    return response.success_object(episode_view(ent), 201)


@bp.route("/series/<sid>/episodes", methods=["GET"])
def list_episodes(sid):
    middleware.require_roles(*middleware.ALL_ROLES)
    s = db.series.get(sid)
    if s is None:
        raise errors.not_found("Series not found")
    limit, offset = util.pagination_params()
    items = [x for x in db.episodes.values() if x["series_id"] == sid]
    items = util.sort_created(util.status_filter(items))
    page, total = util.paginate(items, limit, offset)
    return response.success_list([episode_view(x) for x in page], limit, offset, total)


@bp.route("/episodes/<eid>", methods=["GET"])
def get_episode(eid):
    middleware.require_roles(*middleware.ALL_ROLES)
    e = db.episodes.get(eid)
    if e is None:
        raise errors.not_found("Episode not found")
    return response.success_object(episode_view(e))


@bp.route("/episodes/<eid>/lock", methods=["POST"])
def lock_episode(eid):
    middleware.require_roles("ProductionRep")
    middleware.get_json_body(required=False)
    e = db.episodes.get(eid)
    if e is None:
        raise errors.not_found("Episode not found")
    if e["status"] == "VERIFIED":
        raise errors.already_terminal("Episode is VERIFIED")
    if e["status"] != "SCRIPT_REVIEW":
        raise errors.invalid_state("Episode is not SCRIPT_REVIEW")
    e["status"] = "LOCKED"
    util.touch(e)
    return response.success_object(episode_view(e))


@bp.route("/episodes/<eid>/mark-aired", methods=["POST"])
def mark_aired(eid):
    middleware.require_roles("ProductionRep")
    middleware.get_json_body(required=False)
    e = db.episodes.get(eid)
    if e is None:
        raise errors.not_found("Episode not found")
    if e["status"] == "VERIFIED":
        raise errors.already_terminal("Episode is VERIFIED")
    if e["status"] != "LOCKED":
        raise errors.invalid_state("Episode is not LOCKED")
    if util.clock_now() < util.parse_iso(e["air_date"]):
        raise errors.ApiError(errors.ERR_AIR_DATE_NOT_REACHED, 409,
                              "Logical clock is earlier than episode air_date")
    e["status"] = "AIRED"
    util.touch(e)
    for opp in db.opportunities.values():
        if opp["episode_id"] == eid and opp["status"] == "RESERVED":
            opp["status"] = "CONSUMED"
            util.touch(opp)
    return response.success_object(episode_view(e))


@bp.route("/episodes/<eid>/opportunities", methods=["POST"])
def create_opportunity(eid):
    middleware.require_roles("ProductionRep")
    body = middleware.get_json_body()
    scene = util.req_str(body, "scene_description")
    start = util.req_int(body, "start_timecode_seconds", minimum=0)
    end = util.req_int(body, "end_timecode_seconds", minimum=0)
    est = util.req_int(body, "estimated_exposure_seconds", minimum=0)
    e = db.episodes.get(eid)
    if e is None:
        raise errors.not_found("Episode not found")
    if e["status"] == "VERIFIED":
        raise errors.already_terminal("Episode is VERIFIED")
    if e["status"] != "SCRIPT_REVIEW":
        raise errors.invalid_state("Episode is not SCRIPT_REVIEW")
    # scene window sanity before overlap
    if not (0 <= start < end <= e["runtime_seconds"]):
        raise errors.ApiError(errors.ERR_INVALID_SCENE_WINDOW, 400,
                              "Scene window fails 0 <= start < end <= runtime_seconds")
    for opp in db.opportunities.values():
        if opp["episode_id"] != eid:
            continue
        if opp["status"] not in ("IDENTIFIED", "PITCHED", "RESERVED"):
            continue
        if start < opp["end_timecode_seconds"] and opp["start_timecode_seconds"] < end:
            raise errors.ApiError(errors.ERR_SCENE_WINDOW_OVERLAP, 409,
                                  "Scene window overlaps an existing opportunity")
    ent = util.new_entity()
    ent.update({"episode_id": eid, "scene_description": scene,
                "start_timecode_seconds": start, "end_timecode_seconds": end,
                "estimated_exposure_seconds": est, "status": "IDENTIFIED"})
    db.opportunities[ent["id"]] = ent
    return response.success_object(opportunity_view(ent), 201)


@bp.route("/episodes/<eid>/opportunities", methods=["GET"])
def list_opportunities(eid):
    middleware.require_roles(*middleware.ALL_ROLES)
    e = db.episodes.get(eid)
    if e is None:
        raise errors.not_found("Episode not found")
    limit, offset = util.pagination_params()
    items = [x for x in db.opportunities.values() if x["episode_id"] == eid]
    items = util.sort_created(util.status_filter(items))
    page, total = util.paginate(items, limit, offset)
    return response.success_list([opportunity_view(x) for x in page], limit, offset, total)


@bp.route("/opportunities/<oid>", methods=["GET"])
def get_opportunity(oid):
    middleware.require_roles(*middleware.ALL_ROLES)
    o = db.opportunities.get(oid)
    if o is None:
        raise errors.not_found("Opportunity not found")
    return response.success_object(opportunity_view(o))


@bp.route("/opportunities/<oid>/withdraw", methods=["POST"])
def withdraw_opportunity(oid):
    middleware.require_roles("ProductionRep")
    middleware.get_json_body(required=False)
    o = db.opportunities.get(oid)
    if o is None:
        raise errors.not_found("Opportunity not found")
    if o["status"] in ("CONSUMED", "WITHDRAWN"):
        raise errors.already_terminal("Opportunity is terminal")
    if o["status"] != "IDENTIFIED":
        raise errors.invalid_state("Opportunity is not IDENTIFIED")
    o["status"] = "WITHDRAWN"
    util.touch(o)
    return response.success_object(opportunity_view(o))


@bp.route("/opportunities/<oid>/proposals", methods=["GET"])
def list_opportunity_proposals(oid):
    middleware.require_roles("AgencyAdmin", "IntegrationManager", "BrandRep",
                             "ProductionRep", "NetworkStandardsReviewer")
    o = db.opportunities.get(oid)
    if o is None:
        raise errors.not_found("Opportunity not found")
    limit, offset = util.pagination_params()
    items = [x for x in db.proposals.values() if x["opportunity_id"] == oid]
    items = util.sort_created(util.status_filter(items))
    page, total = util.paginate(items, limit, offset)
    from routes.proposals import proposal_view
    return response.success_list([proposal_view(x) for x in page], limit, offset, total)
