"""CrossPromoObligation, DisclosureFiling, and logical-clock endpoints."""
from flask import Blueprint

import db
import errors
import middleware
import response
import util

bp = Blueprint("extras", __name__)


def crosspromo_view(o):
    return {k: o[k] for k in ("id", "contract_id", "owed_count", "fulfilled_count",
                              "status", "created_at", "updated_at", "version")}


def disclosure_view(d):
    return {k: d[k] for k in ("id", "contract_id", "disclosure_text", "status",
                              "created_at", "updated_at", "version")}


@bp.route("/contracts/<cid>/cross-promos", methods=["GET"])
def list_cross_promos(cid):
    middleware.require_roles("AgencyAdmin", "IntegrationManager", "BrandRep",
                             "ProductionRep")
    c = db.contracts.get(cid)
    if c is None:
        raise errors.not_found("Contract not found")
    limit, offset = util.pagination_params()
    items = [x for x in db.cross_promos.values() if x["contract_id"] == cid]
    items = util.sort_created(util.status_filter(items))
    page, total = util.paginate(items, limit, offset)
    return response.success_list([crosspromo_view(x) for x in page], limit, offset, total)


@bp.route("/cross-promos/<cid>/fulfill", methods=["POST"])
def fulfill_cross_promo(cid):
    middleware.require_roles("IntegrationManager")
    middleware.get_json_body(required=False)
    o = db.cross_promos.get(cid)
    if o is None:
        raise errors.not_found("Cross-promo obligation not found")
    if o["status"] not in ("OWED", "PARTIALLY_FULFILLED"):
        raise errors.invalid_state("Obligation is already FULFILLED")
    o["fulfilled_count"] += 1
    if o["fulfilled_count"] >= o["owed_count"]:
        o["status"] = "FULFILLED"
    else:
        o["status"] = "PARTIALLY_FULFILLED"
    util.touch(o)
    return response.success_object(crosspromo_view(o))


@bp.route("/contracts/<cid>/disclosures", methods=["POST"])
def create_disclosure(cid):
    middleware.require_roles("IntegrationManager")
    body = middleware.get_json_body()
    text = body.get("disclosure_text")
    if text is not None and not isinstance(text, str):
        raise errors.invalid_request("Field 'disclosure_text' must be a string")
    c = db.contracts.get(cid)
    if c is None:
        raise errors.not_found("Contract not found")
    if c["status"] == "TERMINATED":
        raise errors.already_terminal("Contract is TERMINATED")
    ent = util.new_entity()
    ent.update({"contract_id": cid, "disclosure_text": text, "status": "DRAFT"})
    db.disclosures[ent["id"]] = ent
    return response.success_object(disclosure_view(ent), 201)


@bp.route("/contracts/<cid>/disclosures", methods=["GET"])
def list_disclosures(cid):
    middleware.require_roles("AgencyAdmin", "IntegrationManager", "BrandRep",
                             "NetworkStandardsReviewer", "VerificationAnalyst")
    c = db.contracts.get(cid)
    if c is None:
        raise errors.not_found("Contract not found")
    limit, offset = util.pagination_params()
    items = [x for x in db.disclosures.values() if x["contract_id"] == cid]
    items = util.sort_created(util.status_filter(items))
    page, total = util.paginate(items, limit, offset)
    return response.success_list([disclosure_view(x) for x in page], limit, offset, total)


@bp.route("/disclosures/<did>/file", methods=["POST"])
def file_disclosure(did):
    middleware.require_roles("IntegrationManager")
    middleware.get_json_body(required=False)
    d = db.disclosures.get(did)
    if d is None:
        raise errors.not_found("Disclosure filing not found")
    if d["status"] == "ACKNOWLEDGED":
        raise errors.already_terminal("Disclosure filing is ACKNOWLEDGED")
    if d["status"] != "DRAFT":
        raise errors.invalid_state("Disclosure filing is not DRAFT")
    c = db.contracts.get(d["contract_id"])
    episode = db.episodes.get(c["episode_id"]) if c is not None else None
    if episode is not None and episode["status"] in ("AIRED", "VERIFIED"):
        raise errors.ApiError(errors.ERR_EPISODE_ALREADY_AIRED, 409,
                              "Disclosure cannot be filed once the episode aired")
    if not d.get("disclosure_text"):
        raise errors.invalid_request("disclosure_text must be non-empty at file time")
    d["status"] = "FILED"
    util.touch(d)
    return response.success_object(disclosure_view(d))


@bp.route("/disclosures/<did>/acknowledge", methods=["POST"])
def acknowledge_disclosure(did):
    middleware.require_roles("NetworkStandardsReviewer")
    middleware.get_json_body(required=False)
    d = db.disclosures.get(did)
    if d is None:
        raise errors.not_found("Disclosure filing not found")
    if d["status"] == "ACKNOWLEDGED":
        raise errors.already_terminal("Disclosure filing is ACKNOWLEDGED")
    if d["status"] != "FILED":
        raise errors.invalid_state("Disclosure filing is not FILED")
    d["status"] = "ACKNOWLEDGED"
    util.touch(d)
    return response.success_object(disclosure_view(d))


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    middleware.require_roles("AgencyAdmin")
    body = middleware.get_json_body()
    to = util.req_str(body, "to_iso8601")
    dt = util.parse_iso(to)
    db.clock["current_utc"] = dt.strftime("%Y-%m-%dT%H:%M:%S.") + \
        ("%03d" % (dt.microsecond // 1000)) + "Z"
    return response.success_object({"current_utc": db.clock["current_utc"]})
