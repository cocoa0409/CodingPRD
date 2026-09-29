"""Commission ledger reads (PRD 3.7)."""
from flask import Blueprint

import serializers
from db import db
from middleware import ALL_ROLES, endpoint
from response import ok, paginated
from routes.common import filters, get_or_404, listing, matches

bp = Blueprint("comp_records", __name__)


@bp.route("/compensation-records", methods=["GET"])
@endpoint(*ALL_ROLES)
def list_records():
    active = filters("loan_application_id", "originator_id", "compensation_plan_id",
                     "status", "variant")
    rows = listing(db.compensation_records, lambda r: matches(r, active))
    return paginated(rows, serializers.compensation_record)


@bp.route("/compensation-records/<row_id>", methods=["GET"])
@endpoint(*ALL_ROLES)
def get_record(row_id):
    row = get_or_404(db.compensation_records, row_id)
    return ok(serializers.compensation_record(row))
