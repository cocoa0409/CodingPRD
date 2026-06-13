from flask import Blueprint

from db import store
import errors
import middleware
import response
from services import validate
from services.entities import stamp_create, touch, get_endorsement, get_license
from services.serialize import public

bp = Blueprint("endorsements", __name__)


@bp.route("/endorsements", methods=["POST"])
def create_endorsement():
    ident = middleware.authenticate()
    middleware.require_roles(ident, ["LicensingOfficer"])
    data = validate.body()

    license_id = validate.require_str(data, "license_id")
    kind = validate.require_enum(data, "kind", validate.ENDORSEMENT_KINDS)
    condition_text = validate.require_str(data, "condition_text")

    get_license(license_id)  # existence (404)

    rec = {
        "license_id": license_id,
        "kind": kind,
        "status": "ACTIVE",
        "condition_text": condition_text,
    }
    stamp_create(rec)
    store.endorsements[rec["id"]] = rec
    return response.object_response(public(rec), 201)


@bp.route("/endorsements/<eid>", methods=["GET"])
def get_one(eid):
    ident = middleware.authenticate()
    middleware.require_roles(ident, ["Applicant", "LicensingOfficer", "InspectionOfficer"])
    rec = get_endorsement(eid)
    return response.object_response(public(rec), 200)


@bp.route("/endorsements/<eid>/suspend", methods=["POST"])
def suspend(eid):
    ident = middleware.authenticate()
    middleware.require_roles(ident, ["LicensingOfficer"])
    end = get_endorsement(eid)

    if end["status"] != "ACTIVE":
        raise errors.invalid_state("Endorsement must be ACTIVE to suspend")
    lic = get_license(end["license_id"])
    if lic["status"] not in ("ACTIVE", "DELINQUENT"):
        raise errors.invalid_state("Parent license must be ACTIVE or DELINQUENT")

    end["status"] = "SUSPENDED"
    touch(end)
    return response.object_response(public(end), 200)


@bp.route("/endorsements/<eid>/reinstate", methods=["POST"])
def reinstate(eid):
    ident = middleware.authenticate()
    middleware.require_roles(ident, ["LicensingOfficer"])
    end = get_endorsement(eid)

    if end["status"] != "SUSPENDED":
        raise errors.invalid_state("Endorsement must be SUSPENDED to reinstate")
    lic = get_license(end["license_id"])
    if lic["status"] != "ACTIVE":
        raise errors.invalid_state("Parent license must be ACTIVE to reinstate")

    end["status"] = "ACTIVE"
    touch(end)
    return response.object_response(public(end), 200)


@bp.route("/endorsements/<eid>/void", methods=["POST"])
def void(eid):
    ident = middleware.authenticate()
    middleware.require_roles(ident, ["LicensingOfficer"])
    end = get_endorsement(eid)

    if end["status"] not in ("ACTIVE", "SUSPENDED"):
        raise errors.invalid_state("Endorsement must be ACTIVE or SUSPENDED to void")

    end["status"] = "VOIDED"
    touch(end)
    return response.object_response(public(end), 200)
