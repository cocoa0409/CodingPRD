"""Prior authorizations and unit draw-downs (PRD §3.6)."""

from flask import Blueprint, request

import db
import errors
import middleware as mw
import response as resp
import validate as v

bp = Blueprint("prior_authorizations", __name__)

ALL_ROLES = {"PracticeAdmin", "Podiatrist", "BillingSpecialist", "FrontDesk", "PayerAgent"}


@bp.route("/podiatry/prior-authorizations", methods=["POST"])
def create_pa():
    _, role = mw.authenticate()
    mw.require_role(role, {"BillingSpecialist"})
    body = mw.get_body()
    with db.lock():
        patient_id = v.as_str(body, "patient_id", required=True)
        if patient_id not in db.patients:
            raise errors.fk_not_found("patient_id references a non-existent patient.")
        service_category = v.as_enum(body, "service_category",
                                     {"DME", "ORTHOTIC", "IMAGING"}, required=True)
        hcpcs_code = v.as_str(body, "hcpcs_code", required=True)
        authorized_units = v.as_int(body, "authorized_units", required=True, minimum=1)
        valid_from = v.as_date(body, "valid_from_date", required=True)
        valid_through = v.as_date(body, "valid_through_date", required=True)
        entity = {
            "patient_id": patient_id,
            "service_category": service_category,
            "hcpcs_code": hcpcs_code,
            "authorized_units": authorized_units,
            "units_consumed": 0,
            "remaining_units": authorized_units,
            "valid_from_date": valid_from,
            "valid_through_date": valid_through,
            "status": "REQUESTED",
        }
        db.stamp_common(entity)
        db.prior_authorizations[entity["id"]] = entity
        return resp.success(entity, 201)


@bp.route("/podiatry/prior-authorizations", methods=["GET"])
def list_pas():
    _, role = mw.authenticate()
    mw.require_role(role, ALL_ROLES)
    patient_id = request.args.get("patient_id")
    items = [p for p in db.prior_authorizations.values()
             if patient_id is None or p["patient_id"] == patient_id]
    page, meta = mw.paginate(items)
    return resp.success(page, 200, pagination=meta)


@bp.route("/podiatry/prior-authorizations/<pa_id>", methods=["GET"])
def get_pa(pa_id):
    _, role = mw.authenticate()
    mw.require_role(role, ALL_ROLES)
    entity = db.prior_authorizations.get(pa_id)
    if entity is None:
        raise errors.not_found("Prior authorization not found.")
    return resp.success(entity, 200)


@bp.route("/podiatry/prior-authorizations/<pa_id>/approve", methods=["POST"])
def approve_pa(pa_id):
    _, role = mw.authenticate()
    mw.require_role(role, {"PayerAgent"})
    with db.lock():
        entity = db.prior_authorizations.get(pa_id)
        if entity is None:
            raise errors.not_found("Prior authorization not found.")
        if entity["status"] != "REQUESTED":
            raise errors.ApiError(errors.ERR_PA_BAD_STATE, 409,
                                  "PA must be REQUESTED to approve.")
        entity["status"] = "APPROVED"
        entity["units_consumed"] = 0
        entity["remaining_units"] = entity["authorized_units"]
        db.touch(entity)
        return resp.success(entity, 200)


@bp.route("/podiatry/prior-authorizations/<pa_id>/deny", methods=["POST"])
def deny_pa(pa_id):
    _, role = mw.authenticate()
    mw.require_role(role, {"PayerAgent"})
    with db.lock():
        entity = db.prior_authorizations.get(pa_id)
        if entity is None:
            raise errors.not_found("Prior authorization not found.")
        if entity["status"] != "REQUESTED":
            raise errors.ApiError(errors.ERR_PA_BAD_STATE, 409,
                                  "PA must be REQUESTED to deny.")
        entity["status"] = "DENIED"
        db.touch(entity)
        return resp.success(entity, 200)
