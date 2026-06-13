"""Payer enrollment lifecycle and panel management."""
from flask import Blueprint, request

from db import store
from errors import err
from middleware import require_auth, require_role
from response import success_array, success_object
from services.calc import compute_effective_date
from services.common import (
    parse_pagination,
    paginate,
    require_body,
    sort_by_created,
)
from services.lookups import get_enrollment, get_provider
from services.model import make_record, serialize, touch

bp = Blueprint("enrollments", __name__)

NON_TERMINAL = ("REQUESTED", "SUBMITTED", "ACTIVE")


@bp.route("/providers/<rid>/payer-enrollments", methods=["POST"])
def request_enrollment(rid):
    _, role = require_auth()
    require_role(role, {"EnrollmentCoordinator"})
    prov = get_provider(rid)
    body = require_body()

    payer_id = body.get("payer_id")
    if not isinstance(payer_id, str) or payer_id.strip() == "":
        raise err("ERR_INVALID_REQUEST", "payer_id is required.")

    # body FK: payer must exist and be in the provider's org
    payer = store.payers.get(payer_id)
    if payer is None or payer["org_id"] != prov["org_id"]:
        raise err("ERR_REFERENCED_RESOURCE_NOT_FOUND",
                  "payer_id does not reference an in-org payer.")

    # priority 14.5: ongoing-singleton duplicate-payer-enrollment check
    for enr in store.payer_enrollments.values():
        if (enr["provider_id"] == rid and enr["payer_id"] == payer_id
                and enr["status"] in NON_TERMINAL):
            raise err("ERR_DUPLICATE_PAYER_ENROLLMENT",
                      "A non-terminal enrollment with this payer already exists.")

    org = store.orgs.get(prov["org_id"])
    rec = make_record("payer_enrollments", {
        "provider_id": rid,
        "payer_id": payer_id,
        "requested_at": org["current_utc"],
        "effective_date": None,
        "status": "REQUESTED",
        "termination_reason": None,
    })
    return success_object(serialize(rec), 201)


@bp.route("/providers/<rid>/payer-enrollments", methods=["GET"])
def list_provider_enrollments(rid):
    _, role = require_auth()
    require_role(role, {"EnrollmentCoordinator", "CredentialingSpecialist",
                        "MedicalDirector", "SystemAdmin"})
    get_provider(rid)
    limit, offset = parse_pagination()
    rows = [e for e in store.payer_enrollments.values() if e["provider_id"] == rid]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return success_array([serialize(r) for r in page], limit, offset, total, 200)


@bp.route("/payer-enrollments", methods=["GET"])
def list_enrollments():
    _, role = require_auth()
    require_role(role, {"EnrollmentCoordinator", "SystemAdmin"})
    payer_id = request.args.get("payer_id")
    limit, offset = parse_pagination()
    rows = [e for e in store.payer_enrollments.values()
            if payer_id is None or e["payer_id"] == payer_id]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return success_array([serialize(r) for r in page], limit, offset, total, 200)


@bp.route("/payer-enrollments/<rid>", methods=["GET"])
def get_enrollment_route(rid):
    _, role = require_auth()
    require_role(role, {"EnrollmentCoordinator", "CredentialingSpecialist",
                        "MedicalDirector", "SystemAdmin"})
    rec = get_enrollment(rid)
    return success_object(serialize(rec), 200)


@bp.route("/payer-enrollments/<rid>/submit", methods=["POST"])
def submit_enrollment(rid):
    _, role = require_auth()
    require_role(role, {"EnrollmentCoordinator"})
    enr = get_enrollment(rid)
    prov = store.providers.get(enr["provider_id"])

    if enr["status"] != "REQUESTED":
        raise err("ERR_ENROLLMENT_NOT_REQUESTED", "Enrollment is not REQUESTED.")
    if prov is None or prov["credentialing_status"] != "CLEARED":
        raise err("ERR_PROVIDER_NOT_CLEARED", "Provider is not CLEARED.")

    enr["status"] = "SUBMITTED"
    touch(enr)
    return success_object(serialize(enr), 200)


@bp.route("/payer-enrollments/<rid>/activate", methods=["POST"])
def activate_enrollment(rid):
    _, role = require_auth()
    require_role(role, {"EnrollmentCoordinator"})
    enr = get_enrollment(rid)
    prov = store.providers.get(enr["provider_id"])
    payer = store.payers.get(enr["payer_id"])

    if enr["status"] != "SUBMITTED":
        raise err("ERR_ENROLLMENT_NOT_SUBMITTED", "Enrollment is not SUBMITTED.")
    if prov is None or prov["credentialing_status"] != "CLEARED":
        raise err("ERR_PROVIDER_NOT_CLEARED", "Provider is not CLEARED.")

    active_count = sum(1 for e in store.payer_enrollments.values()
                       if e["payer_id"] == enr["payer_id"] and e["status"] == "ACTIVE")
    if active_count >= payer["panel_capacity"]:
        raise err("ERR_PANEL_AT_CAPACITY", "Payer panel is at capacity.")

    org = store.orgs.get(prov["org_id"])
    enr["effective_date"] = compute_effective_date(prov, payer, org)
    enr["status"] = "ACTIVE"
    touch(enr)
    return success_object(serialize(enr), 200)


@bp.route("/payer-enrollments/<rid>/terminate", methods=["POST"])
def terminate_enrollment(rid):
    _, role = require_auth()
    require_role(role, {"EnrollmentCoordinator"})
    enr = get_enrollment(rid)
    body = require_body()

    termination_reason = body.get("termination_reason")

    if enr["status"] != "ACTIVE":
        raise err("ERR_ENROLLMENT_NOT_ACTIVE", "Enrollment is not ACTIVE.")
    if not isinstance(termination_reason, str) or termination_reason.strip() == "":
        raise err("ERR_TERMINATION_REASON_REQUIRED", "termination_reason is required.")

    enr["status"] = "TERMINATED"
    enr["termination_reason"] = termination_reason
    touch(enr)
    return success_object(serialize(enr), 200)
