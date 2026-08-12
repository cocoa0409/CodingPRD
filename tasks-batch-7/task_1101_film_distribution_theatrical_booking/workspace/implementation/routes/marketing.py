"""MarketingCommitment endpoints."""
from flask import Blueprint, request
from decimal import Decimal

from db import db
from middleware import require_roles
from response import success_object
from errors import (
    err_invalid_request, err_invalid_state, err_referential,
    err_coop_budget, err_film_not_bookable, err_not_found,
)
from services.core import (
    serialize_marketing_commitment, get_marketing_commitment, get_market,
    get_distributor, new_entity_common, touch, compute_coop_committed,
)
from util import dec_pct
from ._helpers import get_json_body, require_fields, paginate_list

bp = Blueprint("marketing", __name__)


def _mc_scope_filter(mc, did):
    m = db.markets.get(mc["market_id"])
    return m and m["distributor_id"] == did


@bp.route("/distributors/<did>/markets/<mid>/marketing-commitments", methods=["POST"])
@require_roles("MarketingLead")
def create_marketing_commitment(did, mid, _user_id, _role):
    get_market(did, mid)
    body = get_json_body()
    require_fields(body, ["film_id", "committed_cents", "coop_share_pct"])
    film = db.films.get(body["film_id"])
    if not film or film["distributor_id"] != did:
        raise err_referential("film_id not resolvable")
    theatre_id = body.get("theatre_id")
    if theatre_id is not None:
        theatre = db.theatres.get(theatre_id)
        if not theatre or theatre["distributor_id"] != did:
            raise err_referential("theatre_id not resolvable")
    if not isinstance(body["committed_cents"], int) or body["committed_cents"] < 0:
        raise err_invalid_request("committed_cents must be non-negative integer")
    pct = dec_pct(body["coop_share_pct"])
    if pct is None:
        raise err_invalid_request("coop_share_pct invalid")
    common = new_entity_common()
    mc = {
        **common,
        "market_id": mid,
        "film_id": body["film_id"],
        "theatre_id": theatre_id,
        "committed_cents": body["committed_cents"],
        "spent_cents": 0,
        "status": "DRAFT",
        "coop_share_pct": pct,
    }
    db.marketing_commitments[mc["id"]] = mc
    return success_object(serialize_marketing_commitment(mc), 201)


@bp.route("/distributors/<did>/markets/<mid>/marketing-commitments/<mcid>", methods=["GET"])
@require_roles("PlatformAdmin", "Booker", "MarketingLead", "Auditor")
def read_marketing_commitment(did, mid, mcid, _user_id, _role):
    return success_object(serialize_marketing_commitment(get_marketing_commitment(did, mid, mcid)))


@bp.route("/distributors/<did>/markets/<mid>/marketing-commitments", methods=["GET"])
@require_roles("PlatformAdmin", "Booker", "MarketingLead", "Auditor")
def list_marketing_commitments_market(did, mid, _user_id, _role):
    get_market(did, mid)
    items = [m for m in db.marketing_commitments.values() if m["market_id"] == mid]
    filters = {}
    for k in ("film_id", "theatre_id", "status", "market_id"):
        if k in request.args:
            filters[k] = request.args.get(k)
    return paginate_list(items, serialize_marketing_commitment, filters)


@bp.route("/distributors/<did>/marketing-commitments", methods=["GET"])
@require_roles("PlatformAdmin", "Booker", "MarketingLead", "Auditor")
def list_marketing_commitments_distributor(did, _user_id, _role):
    get_distributor(did)
    items = [m for m in db.marketing_commitments.values() if _mc_scope_filter(m, did)]
    filters = {}
    for k in ("film_id", "theatre_id", "market_id", "status"):
        if k in request.args:
            filters[k] = request.args.get(k)
    return paginate_list(items, serialize_marketing_commitment, filters)


@bp.route("/distributors/<did>/films/<fid>/marketing-commitments", methods=["GET"])
@require_roles("PlatformAdmin", "Booker", "MarketingLead", "Auditor")
def list_marketing_commitments_film(did, fid, _user_id, _role):
    from services.core import get_film
    get_film(did, fid)
    items = [m for m in db.marketing_commitments.values()
             if m["film_id"] == fid and _mc_scope_filter(m, did)]
    return paginate_list(items, serialize_marketing_commitment)


@bp.route("/distributors/<did>/theatres/<tid>/marketing-commitments", methods=["GET"])
@require_roles("PlatformAdmin", "Booker", "MarketingLead", "Auditor")
def list_marketing_commitments_theatre(did, tid, _user_id, _role):
    from services.core import get_theatre
    get_theatre(did, tid)
    items = [m for m in db.marketing_commitments.values()
             if m["theatre_id"] == tid and _mc_scope_filter(m, did)]
    return paginate_list(items, serialize_marketing_commitment)


@bp.route("/distributors/<did>/markets/<mid>/marketing-commitments/<mcid>/commit", methods=["POST"])
@require_roles("MarketingLead")
def commit_marketing(did, mid, mcid, _user_id, _role):
    market = get_market(did, mid)
    mc = get_marketing_commitment(did, mid, mcid)
    if mc["status"] != "DRAFT":
        raise err_invalid_state("MarketingCommitment must be DRAFT")
    # Film lifecycle check
    film = db.films.get(mc["film_id"])
    if not film or film["lifecycle_status"] not in ("PRE_RELEASE", "IN_RELEASE", "HOLDOVER_PHASE"):
        raise err_film_not_bookable()
    # 4x weekly cap
    projected = compute_coop_committed(mid) + mc["committed_cents"]
    if projected > market["weekly_coop_budget_cents"] * 4:
        raise err_coop_budget()
    mc["status"] = "COMMITTED"
    touch(mc)
    return success_object(serialize_marketing_commitment(mc))


@bp.route("/distributors/<did>/markets/<mid>/marketing-commitments/<mcid>/cancel", methods=["POST"])
@require_roles("MarketingLead")
def cancel_marketing(did, mid, mcid, _user_id, _role):
    mc = get_marketing_commitment(did, mid, mcid)
    if mc["status"] not in ("DRAFT", "COMMITTED"):
        raise err_invalid_state("MarketingCommitment must be DRAFT or COMMITTED")
    if mc["spent_cents"] != 0:
        raise err_invalid_state("Cannot cancel: spent_cents must be 0")
    mc["status"] = "CANCELLED"
    touch(mc)
    return success_object(serialize_marketing_commitment(mc))
