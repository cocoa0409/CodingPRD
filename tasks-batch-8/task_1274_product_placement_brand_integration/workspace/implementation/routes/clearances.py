"""CompetitiveClearance endpoints."""
from flask import Blueprint

import db
import errors
import middleware
import response
import util
from services import calc
from routes.brands import clearance_view

bp = Blueprint("clearances", __name__)


@bp.route("/episodes/<eid>/clearances", methods=["POST"])
def create_clearance(eid):
    middleware.require_roles("IntegrationManager")
    body = middleware.get_json_body()
    brand_id = body.get("brand_id")
    if not isinstance(brand_id, str):
        raise errors.invalid_request("Field 'brand_id' is required and must be a string")
    if "expected_episode_version" not in body:
        raise errors.invalid_request("Field 'expected_episode_version' is required")
    expected = body["expected_episode_version"]
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise errors.invalid_request("Field 'expected_episode_version' must be an integer")
    e = db.episodes.get(eid)
    if e is None:
        raise errors.not_found("Episode not found")
    brand = db.brands.get(brand_id)
    if brand is None:
        raise errors.not_found("Brand not found")
    if expected != e["version"]:
        raise errors.stale_version("expected_episode_version does not match episode version")
    if e["status"] in ("AIRED", "VERIFIED"):
        raise errors.ApiError(errors.ERR_EPISODE_ALREADY_AIRED, 409,
                              "Clearance requests cannot be created once the episode aired")
    if brand["status"] != "ACTIVE":
        raise errors.ApiError(errors.ERR_BRAND_SUSPENDED, 409,
                              "Brand is SUSPENDED")
    ent = util.new_entity()
    ent.update({"episode_id": eid, "brand_id": brand_id,
                "category": brand["category"], "risk_score": 0,
                "decided_by_user_id": None, "status": "REQUESTED"})
    db.clearances[ent["id"]] = ent
    util.touch(e)  # creating a clearance increments the episode's version
    return response.success_object(clearance_view(ent), 201)


@bp.route("/episodes/<eid>/clearances", methods=["GET"])
def list_episode_clearances(eid):
    middleware.require_roles("AgencyAdmin", "IntegrationManager", "BrandRep",
                             "ClearanceOfficer", "NetworkStandardsReviewer")
    e = db.episodes.get(eid)
    if e is None:
        raise errors.not_found("Episode not found")
    limit, offset = util.pagination_params()
    items = [x for x in db.clearances.values() if x["episode_id"] == eid]
    items = util.sort_created(util.status_filter(items))
    page, total = util.paginate(items, limit, offset)
    return response.success_list([clearance_view(x) for x in page], limit, offset, total)


@bp.route("/clearances/<cid>/decide", methods=["POST"])
def decide_clearance(cid):
    user_id, _ = middleware.require_roles("ClearanceOfficer")
    body = middleware.get_json_body()
    decision = util.req_enum(body, "decision", ["GRANT", "DENY"])
    c = db.clearances.get(cid)
    if c is None:
        raise errors.not_found("Clearance not found")
    if c["status"] in ("DENIED", "RELEASED"):
        raise errors.already_terminal("Clearance is terminal")
    if c["status"] != "REQUESTED":
        raise errors.invalid_state("Clearance is not REQUESTED")
    if decision == "DENY":
        c["status"] = "DENIED"
        c["decided_by_user_id"] = user_id
        util.touch(c)
        return response.success_object(clearance_view(c))

    # GRANT path
    episode = db.episodes[c["episode_id"]]
    score, policy = calc.clearance_conflict_score(c)
    c["risk_score"] = score
    # 1. category exclusivity
    for other in db.clearances.values():
        if other["id"] == cid:
            continue
        if (other["episode_id"] == c["episode_id"] and other["category"] == c["category"]
                and other["status"] == "GRANTED"):
            c["decided_by_user_id"] = user_id
            util.touch(c)
            raise errors.ApiError(errors.ERR_CATEGORY_EXCLUSIVITY_CONFLICT, 409,
                                  "A GRANTED clearance already exists for this episode and category")
    # 2. air-date proximity
    if calc.proximity_hit(episode, c["category"]):
        c["decided_by_user_id"] = user_id
        util.touch(c)
        raise errors.ApiError(errors.ERR_AIRDATE_PROXIMITY_CONFLICT, 409,
                              "A same-category GRANTED clearance exists within the policy air-date window")
    # 3. risk score deny threshold
    threshold = calc.STRICT_DENY_THRESHOLD if policy == "STRICT" else calc.STANDARD_DENY_THRESHOLD
    if score >= threshold:
        c["decided_by_user_id"] = user_id
        util.touch(c)
        raise errors.ApiError(errors.ERR_AIRDATE_PROXIMITY_CONFLICT, 409,
                              "Clearance risk score %d meets the deny threshold" % score)
    c["status"] = "GRANTED"
    c["decided_by_user_id"] = user_id
    util.touch(c)
    return response.success_object(clearance_view(c))


@bp.route("/clearances/<cid>/release", methods=["POST"])
def release_clearance(cid):
    middleware.require_roles("ClearanceOfficer")
    middleware.get_json_body(required=False)
    c = db.clearances.get(cid)
    if c is None:
        raise errors.not_found("Clearance not found")
    if c["status"] in ("DENIED", "RELEASED"):
        raise errors.already_terminal("Clearance is terminal")
    if c["status"] != "GRANTED":
        raise errors.invalid_state("Clearance is not GRANTED")
    c["status"] = "RELEASED"
    util.touch(c)
    return response.success_object(clearance_view(c))
