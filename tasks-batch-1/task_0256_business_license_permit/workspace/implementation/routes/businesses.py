from flask import Blueprint

from db import store
import middleware
import response
from services import validate
from services.entities import stamp_create, get_business
from services.serialize import public, public_list

bp = Blueprint("businesses", __name__)


@bp.route("/businesses", methods=["POST"])
def create_business():
    ident = middleware.authenticate()
    middleware.require_roles(ident, ["Applicant", "LicensingOfficer"])
    data = validate.body()

    legal_name = validate.require_str(data, "legal_name")
    owner_name = validate.require_str(data, "owner_name")
    zone_code = validate.require_str(data, "zone_code")

    rec = {
        "legal_name": legal_name,
        "owner_name": owner_name,
        "zone_code": zone_code,
        "standing": "GOOD",
        "prior_revocation_flag": False,
        "compliance_risk_score": 0,
    }
    stamp_create(rec)
    store.businesses[rec["id"]] = rec
    return response.object_response(public(rec), 201)


@bp.route("/businesses/<bid>", methods=["GET"])
def get_one(bid):
    ident = middleware.authenticate()
    middleware.require_roles(ident, ["Applicant", "LicensingOfficer", "InspectionOfficer"])
    rec = get_business(bid)
    return response.object_response(public(rec), 200)


@bp.route("/businesses/<bid>/applications", methods=["GET"])
def list_applications(bid):
    ident = middleware.authenticate()
    middleware.require_roles(ident, ["Applicant", "LicensingOfficer", "InspectionOfficer"])
    get_business(bid)  # left-to-right existence
    limit, offset = middleware.parse_pagination()
    items = [a for a in store.applications.values() if a.get("business_id") == bid]
    items.sort(key=lambda r: r["created_at"])
    page, total = middleware.paginate(items, limit, offset)
    return response.array_response(public_list(page), limit, offset, total, 200)


@bp.route("/businesses/<bid>/licenses", methods=["GET"])
def list_licenses(bid):
    ident = middleware.authenticate()
    middleware.require_roles(ident, ["Applicant", "LicensingOfficer", "InspectionOfficer"])
    get_business(bid)
    limit, offset = middleware.parse_pagination()
    items = [l for l in store.licenses.values() if l.get("business_id") == bid]
    items.sort(key=lambda r: r["created_at"])
    page, total = middleware.paginate(items, limit, offset)
    return response.array_response(public_list(page), limit, offset, total, 200)
