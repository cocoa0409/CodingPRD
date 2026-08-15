"""Credential endpoints."""
from flask import Blueprint, request

import db
from envelope import success_list, success_object
from errors import ERR_ALREADY_TERMINAL, ERR_INVALID_STATE, raise_err
from middleware import authenticate, get_or_404, require_roles
from services.coverage import expire_credential_cascade
from validation import get_body, opt_str, paginate, pagination_params, req_date, req_enum, req_str

bp = Blueprint("credentials", __name__)

ROLES = {"SystemAdmin", "ContractorOps", "HRRecruiter"}
CREDENTIABLE_STATES = ("TRAINING", "TESTING", "CERTIFIED", "ACTIVE", "SUSPENDED")


@bp.route("/busops/credentials", methods=["POST"])
def create_credential():
    body = get_body()
    driver_id = req_str(body, "driver_id")
    kind = req_enum(body, "kind", ("CDL_B", "S_ENDORSEMENT", "FIRST_AID"))
    issued_on = req_date(body, "issued_on")
    expires_on = req_date(body, "expires_on")
    actor = authenticate()
    require_roles(actor, {"HRRecruiter"})
    driver = get_or_404("drivers", driver_id, "Driver")
    if driver["status"] == "TERMINATED":
        raise_err(
            ERR_ALREADY_TERMINAL, "Cannot record a credential for a TERMINATED driver"
        )
    if driver["status"] not in CREDENTIABLE_STATES:
        raise_err(
            ERR_INVALID_STATE,
            "Credentials may be recorded only for drivers in TRAINING, TESTING, "
            "CERTIFIED, ACTIVE, or SUSPENDED",
        )

    rec = {
        "id": db.new_id(),
        "driver_id": driver_id,
        "kind": kind,
        "issued_on": issued_on,
        "expires_on": expires_on,
        "status": "ACTIVE",
    }
    db.stamp_new(rec)
    db.STORES["credentials"][rec["id"]] = rec
    return success_object(db.public(rec), status=201)


@bp.route("/busops/credentials", methods=["GET"])
def list_credentials():
    limit, offset = pagination_params()
    actor = authenticate()
    require_roles(actor, ROLES)
    items = list(db.all_of("credentials"))
    driver_id = request.args.get("driver_id")
    kind = request.args.get("kind")
    status = request.args.get("status")
    if driver_id is not None:
        items = [c for c in items if c["driver_id"] == driver_id]
    if kind is not None:
        items = [c for c in items if c["kind"] == kind]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, info = paginate(items, limit, offset)
    return success_list(page, info)


@bp.route("/busops/credentials/<rid>", methods=["GET"])
def get_credential(rid):
    actor = authenticate()
    require_roles(actor, ROLES)
    rec = get_or_404("credentials", rid, "Credential")
    return success_object(db.public(rec))


@bp.route("/busops/credentials/<rid>/revoke", methods=["POST"])
def revoke_credential(rid):
    body = get_body()
    opt_str(body, "reason")
    actor = authenticate()
    require_roles(actor, {"HRRecruiter"})
    rec = get_or_404("credentials", rid, "Credential")
    if rec["status"] == "REVOKED":
        raise_err(ERR_ALREADY_TERMINAL, "Credential is REVOKED (terminal)")
    if rec["status"] != "ACTIVE":
        raise_err(
            ERR_INVALID_STATE,
            "Credential in state %s cannot be revoked" % rec["status"],
        )
    rec["status"] = "REVOKED"
    db.touch(rec)
    expire_credential_cascade(rec)
    return success_object(db.public(rec))
