from flask import Blueprint, request

from db import store
import errors
import middleware
import response
from services import validate
from services import calc
from services.entities import (
    stamp_create, touch, get_transfer, get_license, get_business, get_activity_category,
    create_fee_assessment,
)
from services.serialize import public, public_list

bp = Blueprint("transfers", __name__)


@bp.route("/transfers", methods=["POST"])
def create_transfer():
    ident = middleware.authenticate()
    middleware.require_roles(ident, ["Applicant", "LicensingOfficer"])
    data = validate.body()

    license_id = validate.require_str(data, "license_id")
    from_business_id = validate.require_str(data, "from_business_id")
    to_business_id = validate.require_str(data, "to_business_id")

    # existence (404)
    lic = get_license(license_id)
    get_business(from_business_id)
    get_business(to_business_id)

    # business rule: target license must be ACTIVE (PRD §3.9: at request)
    if lic["status"] != "ACTIVE":
        raise errors.ApiError(errors.ERR_LICENSE_NOT_TRANSFERABLE, 409,
                              "License is not transferable")

    rec = {
        "license_id": license_id,
        "from_business_id": from_business_id,
        "to_business_id": to_business_id,
        "status": "REQUESTED",
        "transfer_fee": 0,
    }
    stamp_create(rec)
    store.transfers[rec["id"]] = rec
    return response.object_response(public(rec), 201)


@bp.route("/transfers/<tid>", methods=["GET"])
def get_one(tid):
    ident = middleware.authenticate()
    middleware.require_roles(ident, ["Applicant", "LicensingOfficer"])
    rec = get_transfer(tid)
    return response.object_response(public(rec), 200)


@bp.route("/transfers", methods=["GET"])
def list_all():
    ident = middleware.authenticate()
    middleware.require_roles(ident, ["Applicant", "LicensingOfficer"])
    limit, offset = middleware.parse_pagination()
    license_id = request.args.get("license_id")
    from_business_id = request.args.get("from_business_id")
    to_business_id = request.args.get("to_business_id")
    items = list(store.transfers.values())
    if license_id is not None:
        items = [t for t in items if t.get("license_id") == license_id]
    if from_business_id is not None:
        items = [t for t in items if t.get("from_business_id") == from_business_id]
    if to_business_id is not None:
        items = [t for t in items if t.get("to_business_id") == to_business_id]
    items.sort(key=lambda r: r["created_at"])
    page, total = middleware.paginate(items, limit, offset)
    return response.array_response(public_list(page), limit, offset, total, 200)


@bp.route("/transfers/<tid>/approve", methods=["POST"])
def approve(tid):
    ident = middleware.authenticate()
    middleware.require_roles(ident, ["LicensingOfficer"])
    tr = get_transfer(tid)

    if tr["status"] != "REQUESTED":
        raise errors.invalid_state("Transfer must be REQUESTED to approve")

    lic = get_license(tr["license_id"])
    # business rule precedence: license transferability before standing of target
    if lic["status"] != "ACTIVE":
        raise errors.ApiError(errors.ERR_LICENSE_NOT_TRANSFERABLE, 409,
                              "License is not transferable")
    to_business = get_business(tr["to_business_id"])
    if to_business["standing"] != "GOOD":
        raise errors.ApiError(errors.ERR_BUSINESS_NOT_IN_GOOD_STANDING, 409,
                              "Transfer target business not in good standing")

    tr["status"] = "APPROVED"
    touch(tr)
    return response.object_response(public(tr), 200)


@bp.route("/transfers/<tid>/reject", methods=["POST"])
def reject(tid):
    ident = middleware.authenticate()
    middleware.require_roles(ident, ["LicensingOfficer"])
    tr = get_transfer(tid)

    if tr["status"] != "REQUESTED":
        raise errors.invalid_state("Transfer must be REQUESTED to reject")

    tr["status"] = "REJECTED"
    touch(tr)
    return response.object_response(public(tr), 200)


@bp.route("/transfers/<tid>/complete", methods=["POST"])
def complete(tid):
    ident = middleware.authenticate()
    middleware.require_roles(ident, ["LicensingOfficer"])
    tr = get_transfer(tid)
    data = validate.body()

    # well-formedness (400): expected_license_version is a non-optional integer
    expected_version = validate.require_int(data, "expected_license_version")

    # state legality (409)
    if tr["status"] != "APPROVED":
        raise errors.invalid_state("Transfer must be APPROVED to complete")

    lic = get_license(tr["license_id"])
    # business rule: license must still be ACTIVE
    if lic["status"] != "ACTIVE":
        raise errors.ApiError(errors.ERR_LICENSE_NOT_TRANSFERABLE, 409,
                              "License is not transferable")

    # OCC (412): expected_license_version must equal current License.version
    if expected_version != lic["version"]:
        raise errors.ApiError(errors.ERR_STALE_VERSION, 412,
                              "expected_license_version does not match current license version")

    cat = get_activity_category(lic["activity_category_id"])
    fee = calc.transfer_fee(cat["risk_tier"])

    # reassign holding business only (owner name not copied)
    lic["business_id"] = tr["to_business_id"]
    touch(lic)

    tr["transfer_fee"] = fee
    tr["status"] = "COMPLETED"
    touch(tr)

    create_fee_assessment("TRANSFER_FEE", fee, license_id=lic["id"], settled=False)
    return response.object_response(public(tr), 200)


@bp.route("/transfers/<tid>/cancel", methods=["POST"])
def cancel(tid):
    ident = middleware.authenticate()
    middleware.require_roles(ident, ["Applicant", "LicensingOfficer"])
    tr = get_transfer(tid)

    if tr["status"] not in ("REQUESTED", "APPROVED"):
        raise errors.invalid_state("Transfer must be REQUESTED or APPROVED to cancel")

    tr["status"] = "CANCELLED"
    tr["transfer_fee"] = 0
    touch(tr)
    return response.object_response(public(tr), 200)
