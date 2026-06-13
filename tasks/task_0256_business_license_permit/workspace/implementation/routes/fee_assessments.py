from flask import Blueprint

import middleware
import response
from services.entities import touch, get_fee_assessment
from services.serialize import public

bp = Blueprint("fee_assessments", __name__)


@bp.route("/fee-assessments/<fid>", methods=["GET"])
def get_one(fid):
    ident = middleware.authenticate()
    middleware.require_roles(ident, ["LicensingOfficer", "Applicant"])
    rec = get_fee_assessment(fid)
    return response.object_response(public(rec), 200)


@bp.route("/fee-assessments/<fid>/settle", methods=["POST"])
def settle(fid):
    ident = middleware.authenticate()
    middleware.require_roles(ident, ["LicensingOfficer", "Applicant"])
    rec = get_fee_assessment(fid)
    rec["settled"] = True
    touch(rec)
    return response.object_response(public(rec), 200)
