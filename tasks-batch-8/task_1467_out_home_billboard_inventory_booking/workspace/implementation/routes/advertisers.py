"""AdvertiserAccount endpoints (PRD 3.4)."""
from flask import Blueprint, request

import db
import domain
from errors import ApiError, err_invalid_request, err_invalid_state
from middleware import require_roles
from response import success, paginate, sort_created
from serializers import advertiser_out, campaign_out
from util import req_int, req_str, opt_int

bp = Blueprint("advertisers", __name__, url_prefix="/api")


def get_advertiser_or_404(aid):
    a = db.advertisers.get(aid)
    if a is None:
        raise ApiError("ERR_ADVERTISER_NOT_FOUND", 404, "Advertiser not found")
    return a


@bp.route("/advertiser-accounts", methods=["POST"])
def create_advertiser():
    require_roles("SalesPlanner")
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_invalid_request("Request body must be a JSON object")
    a = db.new_resource()
    a.update({
        "name": req_str(body, "name"),
        "credit_limit_cents": req_int(body, "credit_limit_cents", 0),
        "credit_balance_cents": 0,
        "exposure_cents": 0,
        "status": "ACTIVE",
    })
    db.advertisers[a["id"]] = a
    return success(advertiser_out(a), code=201)


@bp.route("/advertiser-accounts/<aid>", methods=["GET"])
def get_advertiser(aid):
    require_roles("SalesPlanner", "SalesManager", "FinanceAnalyst")
    a = get_advertiser_or_404(aid)
    return success(advertiser_out(a))


@bp.route("/advertiser-accounts/<aid>", methods=["PUT"])
def update_advertiser(aid):
    require_roles("FinanceAnalyst")
    a = get_advertiser_or_404(aid)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_invalid_request("Request body must be a JSON object")

    new_limit = opt_int(body, "credit_limit_cents", 0)
    new_status = None
    if "status" in body and body["status"] is not None:
        if body["status"] not in ("ACTIVE", "CREDIT_HOLD", "SUSPENDED"):
            raise err_invalid_request("Unknown advertiser status")
        new_status = body["status"]

    if new_status is not None and new_status != a["status"]:
        allowed = {
            ("ACTIVE", "CREDIT_HOLD"), ("CREDIT_HOLD", "ACTIVE"),
            ("ACTIVE", "SUSPENDED"), ("CREDIT_HOLD", "SUSPENDED"),
            ("SUSPENDED", "ACTIVE"),
        }
        if (a["status"], new_status) not in allowed:
            raise err_invalid_state(
                "Advertiser cannot transition %s -> %s"
                % (a["status"], new_status))

    # Family 14: lowering the limit below current exposure is rejected
    if new_limit is not None and new_limit < a["exposure_cents"]:
        raise ApiError("ERR_CREDIT_LIMIT_EXCEEDED", 402,
                       "credit_limit_cents may not be lowered below current "
                       "exposure")

    if new_limit is not None:
        a["credit_limit_cents"] = new_limit
    if new_status is not None:
        a["status"] = new_status
    db.touch(a)
    return success(advertiser_out(a))


@bp.route("/advertiser-accounts/<aid>/campaigns", methods=["GET"])
def advertiser_campaigns(aid):
    require_roles("SalesPlanner", "SalesManager", "FinanceAnalyst")
    a = get_advertiser_or_404(aid)
    items = sort_created([c for c in db.campaigns.values()
                          if c["advertiser_id"] == a["id"]])
    page, meta = paginate(items)
    return success([campaign_out(c) for c in page], response_type="array",
                   page_meta=meta)
