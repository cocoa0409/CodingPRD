"""DistributionRecord routes: get, list (read-only; authored by delivery cascade)."""
from flask import Blueprint, request

from db import db, sorted_by_created
from middleware import authenticate, authorize
from validators import parse_pagination
from lookups import get_distribution_path
from response import success_object, success_array
import serializers as ser

bp = Blueprint("distribution_records", __name__)


@bp.route("/yearbooks/distribution-records/<record_id>", methods=["GET"])
def get_record(record_id):
    _, role = authenticate()
    authorize(role, {"Adviser", "SalesRep"})
    record = get_distribution_path(record_id)
    return success_object(ser.distribution_record(record), 200)


@bp.route("/yearbooks/distribution-records", methods=["GET"])
def list_records():
    _, role = authenticate()
    authorize(role, {"Adviser", "SalesRep"})
    limit, offset = parse_pagination()
    yearbook_id = request.args.get("yearbook_id")
    presale_order_id = request.args.get("presale_order_id")
    records = list(db.distribution_records.values())
    if yearbook_id is not None:
        records = [r for r in records if r["yearbook_id"] == yearbook_id]
    if presale_order_id is not None:
        records = [r for r in records if r["presale_order_id"] == presale_order_id]
    records = sorted_by_created(records)
    total = len(records)
    page = records[offset:offset + limit]
    return success_array([ser.distribution_record(r) for r in page], limit, offset, total, 200)
