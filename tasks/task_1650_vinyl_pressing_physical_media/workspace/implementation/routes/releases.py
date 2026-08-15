"""Release endpoints."""

import re
from datetime import date

from flask import Blueprint, request

import db
import serializers
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_RELEASE_NOT_FOUND,
    ERR_CUSTOMER_NOT_FOUND, ERR_DUPLICATE_CODE, ERR_STALE_VERSION,
)
from middleware import get_auth, require_role, get_pagination, apply_pagination
from response import success_object, success_list
from services import risk as risk_service
from services.constants import FORMATS, WEIGHTS

bp = Blueprint("releases", __name__)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def valid_date_str(s):
    if not isinstance(s, str) or not _DATE_RE.match(s):
        return False
    try:
        date.fromisoformat(s)
        return True
    except ValueError:
        return False


def get_release_or_404(release_id):
    r = db.releases.get(release_id)
    if not r:
        raise ApiError(ERR_RELEASE_NOT_FOUND, "Release id does not exist", 404)
    return r


@bp.route("/releases", methods=["POST"])
def create_release():
    _, role = get_auth()
    require_role(role, ["CustomerServiceRep"])
    body = request.get_json(silent=True) or {}

    customer_id = body.get("customer_id")
    catalog_number = body.get("catalog_number")
    title = body.get("title")
    fmt = body.get("format")
    weight_gram = body.get("weight_gram")
    release_date = body.get("release_date")

    if not isinstance(customer_id, str) or not customer_id:
        raise ApiError(ERR_INVALID_REQUEST, "customer_id is required", 400)
    # existence of body-referenced FK (priority 3 before shape on its own
    # fields? spec: existence of path ids first, then body FKs, then shape)
    customer = db.customers.get(customer_id)
    if not customer:
        raise ApiError(ERR_CUSTOMER_NOT_FOUND, "customer_id does not exist", 404)

    if not isinstance(catalog_number, str) or not catalog_number:
        raise ApiError(ERR_INVALID_REQUEST, "catalog_number is required", 400)
    if not isinstance(title, str) or not title:
        raise ApiError(ERR_INVALID_REQUEST, "title is required", 400)
    if fmt not in FORMATS:
        raise ApiError(ERR_INVALID_REQUEST, "format must be LP, EP, or SINGLE_7", 400)
    if weight_gram not in WEIGHTS or isinstance(weight_gram, bool):
        raise ApiError(ERR_INVALID_REQUEST, "weight_gram must be 140 or 180", 400)
    if not valid_date_str(release_date):
        raise ApiError(ERR_INVALID_REQUEST, "release_date must be yyyy-mm-dd", 400)

    # catalog_number unique per customer
    for r in db.releases.values():
        if r["customer_id"] == customer_id and r["catalog_number"] == catalog_number:
            raise ApiError(ERR_DUPLICATE_CODE, "catalog_number already used for this customer", 409)

    now = db.timestamp_now()
    release = {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "customer_id": customer_id,
        "catalog_number": catalog_number,
        "title": title,
        "format": fmt,
        "weight_gram": weight_gram,
        "release_date": release_date,
        "status": "SETUP",
        "risk_level": "ON_TRACK",
        "projected_completion_date": None,
        "slack_days": None,
    }
    db.releases[release["id"]] = release
    return success_object(serializers.release(release), 201)


@bp.route("/releases", methods=["GET"])
def list_releases():
    get_auth()
    limit, offset = get_pagination()
    customer_id = request.args.get("customer_id")
    items = list(db.releases.values())
    if customer_id is not None:
        items = [r for r in items if r["customer_id"] == customer_id]
    page, total = apply_pagination(items, limit, offset)
    return success_list([serializers.release(r) for r in page], limit, offset, total)


@bp.route("/releases/<rid>", methods=["GET"])
def get_release(rid):
    get_auth()
    return success_object(serializers.release(get_release_or_404(rid)))


@bp.route("/releases/<rid>/date-revisions", methods=["POST"])
def date_revision(rid):
    _, role = get_auth()
    require_role(role, ["CustomerServiceRep"])
    release = get_release_or_404(rid)
    body = request.get_json(silent=True) or {}

    new_date = body.get("new_release_date")
    reason = body.get("reason")
    expected = body.get("expected_release_version")

    if not valid_date_str(new_date):
        raise ApiError(ERR_INVALID_REQUEST, "new_release_date must be yyyy-mm-dd", 400)
    if reason is not None and not isinstance(reason, str):
        raise ApiError(ERR_INVALID_REQUEST, "reason must be a string", 400)
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError(ERR_INVALID_REQUEST, "expected_release_version is required", 400)

    # State: always permitted while not FULFILLED
    if release["status"] == "FULFILLED":
        raise ApiError(ERR_INVALID_REQUEST, "release is FULFILLED", 400)

    if expected != release["version"]:
        raise ApiError(ERR_STALE_VERSION, "expected_release_version is stale", 412)

    release["release_date"] = new_date
    release["version"] += 1
    release["updated_at"] = db.timestamp_now()
    risk_service.recompute_release_risk(release, "DATE_REVISION", None)
    return success_object(serializers.release(release))


@bp.route("/releases/<rid>/risk", methods=["GET"])
def release_risk(rid):
    get_auth()
    release = get_release_or_404(rid)
    projected, slack, level = risk_service.compute_release_risk(release)
    # persist the computed view
    release["projected_completion_date"] = projected.isoformat() if projected else None
    release["slack_days"] = slack
    release["risk_level"] = level
    return success_object({
        "release_id": release["id"],
        "projected_completion_date": release["projected_completion_date"],
        "slack_days": release["slack_days"],
        "risk_level": release["risk_level"],
    })


@bp.route("/releases/<rid>/delay-notices", methods=["GET"])
def release_delay_notices(rid):
    get_auth()
    release = get_release_or_404(rid)
    limit, offset = get_pagination()
    items = [n for n in db.delay_notices.values() if n["release_id"] == release["id"]]
    page, total = apply_pagination(items, limit, offset)
    return success_list([serializers.delay_notice(n) for n in page], limit, offset, total)
