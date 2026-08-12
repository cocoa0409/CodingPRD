"""Mutual-aid agreements and mutual-aid request lifecycle."""
from flask import Blueprint, request

from db import store, base_entity, touch, serialize, parse_date
from errors import (
    ApiError, ERR_AGREEMENT_NOT_FOUND, ERR_REQUEST_NOT_FOUND,
    ERR_AGREEMENT_WINDOW_INVALID, ERR_AGREEMENT_WINDOW_OVERLAP,
    ERR_AGREEMENT_NOT_ACTIVE, ERR_REQUEST_NOT_ACTIONABLE,
)
from middleware import require, json_body, need_str, need_enum, need_date_str, ALL_ROLES
from response import success, paginated
from services import calc

bp = Blueprint("mutual_aid", __name__)


def get_agreement_or_404(aid):
    a = store.agreements.get(aid)
    if a is None:
        raise ApiError(ERR_AGREEMENT_NOT_FOUND, 404, "Mutual-aid agreement id does not exist")
    return a


def get_request_or_404(rid):
    r = store.requests.get(rid)
    if r is None:
        raise ApiError(ERR_REQUEST_NOT_FOUND, 404, "Mutual-aid request id does not exist")
    return r


@bp.post("/arff/mutual-aid-agreements")
def create_agreement():
    require(["AirportManager"])
    data = json_body()
    partner = need_str(data, "partner_airport_code", nonempty=True)
    max_level = need_enum(data, "max_alert_level", calc.ALERT_LEVELS)
    start_raw = need_date_str(data, "start_date")
    end_raw = need_date_str(data, "end_date")
    start = parse_date(start_raw)
    end = parse_date(end_raw)
    if start > end:
        raise ApiError(ERR_AGREEMENT_WINDOW_INVALID, 422,
                       "start_date must be at-or-before end_date")
    for other in store.agreements.values():
        if other["partner_airport_code"] == partner and other["status"] in ("DRAFT", "ACTIVE"):
            # closed-interval overlap: touching endpoints conflict
            if start <= other["_end_date"] and other["_start_date"] <= end:
                raise ApiError(ERR_AGREEMENT_WINDOW_OVERLAP, 409,
                               "Agreement window overlaps an existing agreement for this partner")
    a = base_entity()
    a.update({
        "partner_airport_code": partner,
        "max_alert_level": max_level,
        "start_date": start_raw,
        "end_date": end_raw,
        "status": "DRAFT",
        "_start_date": start,
        "_end_date": end,
    })
    store.agreements[a["id"]] = a
    return success(serialize(a), "object", 201)


@bp.get("/arff/mutual-aid-agreements")
def list_agreements():
    require(ALL_ROLES)
    items = list(store.agreements.values())
    partner = request.args.get("partner_airport_code")
    if partner is not None:
        items = [a for a in items if a["partner_airport_code"] == partner]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return paginated(items)


@bp.get("/arff/mutual-aid-agreements/<aid>")
def get_agreement(aid):
    require(ALL_ROLES)
    return success(serialize(get_agreement_or_404(aid)), "object", 200)


@bp.post("/arff/mutual-aid-agreements/<aid>/activate")
def activate_agreement(aid):
    require(["AirportManager"])
    a = get_agreement_or_404(aid)
    if a["status"] != "DRAFT":
        raise ApiError(ERR_AGREEMENT_NOT_ACTIVE, 409, "Agreement must be DRAFT to activate")
    a["status"] = "ACTIVE"
    touch(a)
    return success(serialize(a), "object", 200)


@bp.post("/arff/mutual-aid-agreements/<aid>/terminate")
def terminate_agreement(aid):
    require(["AirportManager"])
    a = get_agreement_or_404(aid)
    if a["status"] != "ACTIVE":
        raise ApiError(ERR_AGREEMENT_NOT_ACTIVE, 409, "Agreement must be ACTIVE to terminate")
    a["status"] = "TERMINATED"
    touch(a)
    return success(serialize(a), "object", 200)


@bp.get("/arff/mutual-aid-agreements/<aid>/mutual-aid-requests")
def list_agreement_requests(aid):
    require(ALL_ROLES)
    get_agreement_or_404(aid)
    items = [r for r in store.requests.values() if r["agreement_id"] == aid]
    return paginated(items)


@bp.post("/arff/mutual-aid-requests/<rid>/deploy")
def deploy_request(rid):
    require(["ArffChief"])
    r = get_request_or_404(rid)
    if r["status"] != "REQUESTED":
        raise ApiError(ERR_REQUEST_NOT_ACTIONABLE, 409, "Request must be REQUESTED to deploy")
    r["status"] = "DEPLOYED"
    touch(r)
    return success(serialize(r), "object", 200)


@bp.post("/arff/mutual-aid-requests/<rid>/release")
def release_request(rid):
    require(["ArffChief"])
    r = get_request_or_404(rid)
    if r["status"] != "DEPLOYED":
        raise ApiError(ERR_REQUEST_NOT_ACTIONABLE, 409, "Request must be DEPLOYED to release")
    r["status"] = "RELEASED"
    touch(r)
    return success(serialize(r), "object", 200)


@bp.post("/arff/mutual-aid-requests/<rid>/decline")
def decline_request(rid):
    require(["ArffChief"])
    r = get_request_or_404(rid)
    if r["status"] != "REQUESTED":
        raise ApiError(ERR_REQUEST_NOT_ACTIONABLE, 409, "Request must be REQUESTED to decline")
    r["status"] = "DECLINED"
    touch(r)
    return success(serialize(r), "object", 200)
