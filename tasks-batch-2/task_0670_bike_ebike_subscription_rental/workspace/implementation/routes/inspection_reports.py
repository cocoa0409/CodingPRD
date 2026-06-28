from flask import Blueprint, request

from db import db
from middleware import require_role
from response import object_response, array_response
from services.common import parse_pagination, paginate
from services.lookups import get_report
from services.serialize import inspection_report_view

inspection_reports_bp = Blueprint("inspection_reports", __name__)

VIEW_ROLES = {"OpsAdmin", "FieldTech", "Subscriber", "FleetManager"}


@inspection_reports_bp.route("/inspection-reports/<report_id>", methods=["GET"])
def fetch_report(report_id):
    require_role(VIEW_ROLES)
    report = get_report(report_id)
    return object_response(inspection_report_view(report), 200)


@inspection_reports_bp.route("/inspection-reports", methods=["GET"])
def list_reports():
    require_role(VIEW_ROLES)
    limit, offset = parse_pagination()
    records = list(db.inspection_reports.values())
    rental_id = request.args.get("rental_id")
    if rental_id:
        records = [r for r in records if r["rental_id"] == rental_id]
    page, total = paginate(records, limit, offset)
    return array_response([inspection_report_view(r) for r in page], limit, offset, total)
