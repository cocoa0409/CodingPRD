"""RentComparable endpoints."""

from flask import Blueprint, request

import db
from middleware import require_roles
from response import success_object, success_list
from routes.helpers import parse_pagination, sorted_page

bp = Blueprint("rent_comparables", __name__)


def serialize_comparable(r):
    return {
        "id": r["id"],
        "zip_code": r["zip_code"],
        "bedroom_count": r["bedroom_count"],
        "rent_cents": r["rent_cents"],
        "survey_date": r["survey_date"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


@bp.route("/hcv/rent-comparables", methods=["POST"])
def create_comparable():
    require_roles("HousingAuthorityAdmin")
    body = request.get_json(force=True, silent=True) or {}
    rec = db.make_record({
        "zip_code": body.get("zip_code"),
        "bedroom_count": body.get("bedroom_count"),
        "rent_cents": body.get("rent_cents"),
        "survey_date": body.get("survey_date"),
    })
    db.rent_comparables[rec["id"]] = rec
    return success_object(serialize_comparable(rec), 201)


@bp.route("/hcv/rent-comparables", methods=["GET"])
def list_comparables():
    require_roles("HousingAuthorityAdmin")
    limit, offset = parse_pagination()
    zip_code = request.args.get("zip_code")
    bedroom_count = request.args.get("bedroom_count")
    rows = list(db.rent_comparables.values())
    if zip_code is not None:
        rows = [r for r in rows if r["zip_code"] == zip_code]
    if bedroom_count is not None:
        try:
            bc = int(bedroom_count)
            rows = [r for r in rows if r["bedroom_count"] == bc]
        except ValueError:
            rows = []
    page, total = sorted_page(rows, limit, offset)
    return success_list([serialize_comparable(r) for r in page], total, limit, offset)
