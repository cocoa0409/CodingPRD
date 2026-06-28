from flask import Blueprint

from db import db, stamp_create
from middleware import auth
from response import object_response, list_response
from services.query import get_or_404, paginate
from services.calc import RATING_VALUE
from validate import get_body, req_enum, pagination_params

bp = Blueprint("cpars", __name__)

RATINGS = set(RATING_VALUE.keys())


@bp.route("/contracts/<contract_id>/cpars", methods=["POST"])
def file_cpars(contract_id):
    auth(["ContractingOfficer"])
    contract = get_or_404(db.contracts, contract_id)
    body = get_body()
    rating = req_enum(body, "rating", RATINGS)

    report = {
        "contract_id": contract_id,
        "rating": rating,
        "rating_value": RATING_VALUE[rating],
    }
    stamp_create(report)
    db.cpars[report["id"]] = report
    return object_response(report, status=201)


@bp.route("/contracts/<contract_id>/cpars", methods=["GET"])
def list_cpars(contract_id):
    auth(["Vendor", "ContractingOfficer", "Auditor"])
    get_or_404(db.contracts, contract_id)
    limit, offset = pagination_params()
    items = [r for r in db.cpars.values() if r["contract_id"] == contract_id]
    page, total = paginate(items, limit, offset)
    return list_response(page, limit, offset, total)
