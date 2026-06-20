"""PriorAuthorization endpoints."""
from flask import Blueprint, request

import errors
from db import db
from errors import err
from middleware import get_auth, require_roles
from response import success, list_success
from store_helpers import (
    make_common, touch, public, sort_by_created, get_prior_auth, get_patient,
)
from validation import (
    get_body, require_str, require_enum, require_number,
    get_pagination, paginate,
)

bp = Blueprint("prior_auth", __name__)

ALL_ROLES = {"Pharmacist", "Nurse", "PriorAuthCoordinator"}
DECISIONS = {"APPROVE", "DENY"}


@bp.route("/prior-authorizations", methods=["POST"])
def create_prior_auth():
    _, role = get_auth()
    require_roles(role, {"PriorAuthCoordinator"})
    body = get_body()
    # FK existence (patient) before remaining body validation per §2.10.
    patient_id = require_str(body, "patient_id")
    get_patient(patient_id)
    drug_name = require_str(body, "drug_name")
    payer = require_str(body, "payer")

    with db.lock:
        entity = make_common()
        entity.update({
            "patient_id": patient_id,
            "drug_name": drug_name,
            "payer": payer,
            "authorized_units_mg": None,
            "status": "REQUESTED",
            "consumed_units_mg": 0,
        })
        db.prior_authorizations[entity["id"]] = entity
        return success(public(entity), status=201)


@bp.route("/prior-authorizations", methods=["GET"])
def list_prior_auths():
    _, role = get_auth()
    require_roles(role, ALL_ROLES)
    limit, offset = get_pagination()
    patient_id = request.args.get("patient_id")
    items = [p for p in db.prior_authorizations.values()
             if patient_id is None or p["patient_id"] == patient_id]
    items = sort_by_created(items)
    total = len(items)
    window = [public(p) for p in paginate(items, limit, offset)]
    return list_success(window, limit, offset, total)


@bp.route("/prior-authorizations/<pid>", methods=["GET"])
def get_one_prior_auth(pid):
    _, role = get_auth()
    require_roles(role, ALL_ROLES)
    entity = get_prior_auth(pid)
    return success(public(entity), status=200)


@bp.route("/prior-authorizations/<pid>/decide", methods=["POST"])
def decide_prior_auth(pid):
    _, role = get_auth()
    require_roles(role, {"PriorAuthCoordinator"})
    pa = get_prior_auth(pid)
    body = get_body()
    decision = require_enum(body, "decision", DECISIONS)
    # Body well-formedness (§2.10 priority 4) precedes the state check (priority 6):
    # an APPROVE decision requires a positive authorized_units_mg.
    authorized_units_mg = None
    if decision == "APPROVE":
        authorized_units_mg = require_number(body, "authorized_units_mg", gt=0)

    with db.lock:
        if pa["status"] != "REQUESTED":
            raise err(errors.ERR_PA_NOT_REQUESTED, "Prior authorization is not in REQUESTED state")
        if decision == "APPROVE":
            pa["authorized_units_mg"] = authorized_units_mg
            pa["status"] = "APPROVED"
        else:  # DENY
            pa["status"] = "DENIED"
        touch(pa, bump_version=True)
        return success(public(pa), status=200)
