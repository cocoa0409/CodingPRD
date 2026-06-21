"""Community endpoints (FemaAdmin manages; all roles read)."""

from flask import Blueprint

import errors
from db import db, new_id, now_ts
from middleware import require_roles
from response import success, list_success
from serializers import serialize_community, serialize_property
from services.calculations import crs_discount_pct
from helpers import (
    get_body, require_str, opt_bool, opt_int, require_int,
    parse_pagination, paginate, sort_by_created,
)

bp = Blueprint("communities", __name__)


def _validate_crs_class(value):
    if value < 1 or value > 10:
        raise errors.validation("crs_class must be an integer in [1,10]")


@bp.route("/communities", methods=["POST"])
@require_roles("FemaAdmin")
def create_community():
    body = get_body()
    name = require_str(body, "name")
    county_code = require_str(body, "county_code")
    participating = opt_bool(body, "participating", True)
    crs_class = opt_int(body, "crs_class", 10)
    _validate_crs_class(crs_class)

    ts = now_ts()
    cid = new_id()
    record = {
        "id": cid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "name": name,
        "county_code": county_code,
        "participating": participating,
        "crs_class": crs_class,
        "crs_discount_pct": float(crs_discount_pct(crs_class)),
    }
    db.communities[cid] = record
    return success(serialize_community(record), status=201)


@bp.route("/communities/<cid>", methods=["GET"])
@require_roles("FemaAdmin", "Underwriter", "Adjuster", "PolicyHolder")
def get_community(cid):
    record = db.communities.get(cid)
    if record is None:
        raise errors.not_found("Community not found")
    return success(serialize_community(record), status=200)


@bp.route("/communities/<cid>", methods=["PATCH"])
@require_roles("FemaAdmin")
def update_community(cid):
    body = get_body()
    record = db.communities.get(cid)
    if record is None:
        raise errors.not_found("Community not found")

    # OCC: expected_community_version required.
    expected = require_int(body, "expected_community_version")

    new_participating = record["participating"]
    new_crs_class = record["crs_class"]
    if "participating" in body and body["participating"] is not None:
        if not isinstance(body["participating"], bool):
            raise errors.validation("participating must be a boolean")
        new_participating = body["participating"]
    if "crs_class" in body and body["crs_class"] is not None:
        if isinstance(body["crs_class"], bool) or not isinstance(body["crs_class"], int):
            raise errors.validation("crs_class must be an integer")
        _validate_crs_class(body["crs_class"])
        new_crs_class = body["crs_class"]

    if expected != record["version"]:
        raise errors.ApiError(errors.ERR_STALE_POLICY_VERSION, 412,
                              "expected_community_version does not match live version")

    record["participating"] = new_participating
    record["crs_class"] = new_crs_class
    record["crs_discount_pct"] = float(crs_discount_pct(new_crs_class))
    record["version"] += 1
    record["updated_at"] = now_ts()
    return success(serialize_community(record), status=200)


@bp.route("/communities/<cid>/properties", methods=["GET"])
@require_roles("FemaAdmin", "Underwriter", "Adjuster")
def list_community_properties(cid):
    if db.communities.get(cid) is None:
        raise errors.not_found("Community not found")
    limit, offset = parse_pagination()
    items = [p for p in db.properties.values() if p["community_id"] == cid]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return list_success([serialize_property(p) for p in page], limit, offset, total)
