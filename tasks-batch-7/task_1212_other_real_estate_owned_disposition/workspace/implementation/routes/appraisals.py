"""Appraisal endpoints: OCC-guarded create, submit/certify/reject workflow."""
from flask import g

import db
import domain
from domain import appraisal_json, sort_entities, TERMINAL_LIFECYCLE
from envelope import success
from errors import ApiError
from routes.common import (require_roles, body, req_str, req_num, req_int, req_date,
                           paginate, get_or_404)
from routes.properties import ALL_ROLES, request_arg
from util import pdate


def create_appraisal():
    require_roles("Appraiser")
    d = body()
    # Entity-backed ownership (priority 2) runs ahead of full schema validation when possible.
    raw_aid = d.get("appraiser_id")
    if isinstance(raw_aid, str) and raw_aid != g.user_id:
        raise ApiError("ERR_FORBIDDEN", 403, "Appraiser may only create appraisals for self")
    property_id = req_str(d, "property_id")
    appraiser_id = req_str(d, "appraiser_id")
    effective_date = req_date(d, "effective_date")
    appraised_value = req_num(d, "appraised_value")
    if appraised_value <= 0:
        raise ApiError("ERR_VALIDATION", 400, "appraised_value must be greater than 0")
    expected_version = req_int(d, "expected_property_version")
    p = get_or_404(db.properties, property_id, "Property")
    appraiser = get_or_404(db.appraisers, appraiser_id, "Appraiser")
    if appraiser_id != g.user_id:
        raise ApiError("ERR_FORBIDDEN", 403, "Appraiser may only create appraisals for self")
    if expected_version != p["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_property_version does not match the property's current version")
    if p["lifecycle_status"] in TERMINAL_LIFECYCLE:
        raise ApiError("ERR_PROPERTY_ALREADY_TERMINAL", 409, "Property is terminal")
    if pdate(effective_date) > db.clock:
        raise ApiError("ERR_EFFECTIVE_DATE_IN_FUTURE", 422,
                       "Appraisal effective_date is after the current clock")
    if p["state_code"] not in appraiser["coverage_states"]:
        raise ApiError("ERR_APPRAISER_NOT_ELIGIBLE", 422,
                       "Appraiser is not licensed in the property's state")
    a = domain.base_entity()
    a.update({
        "property_id": property_id,
        "appraiser_id": appraiser_id,
        "effective_date": effective_date,
        "appraised_value": appraised_value,
        "status": "DRAFT",
        "submitted_by_user_id": None,
        "certified_by_user_id": None,
        "rejection_reason": None,
    })
    db.appraisals[a["id"]] = a
    domain.bump(p)
    return success(appraisal_json(a), 201)


def list_appraisals():
    require_roles(*ALL_ROLES)
    pid = request_arg("property_id")
    aid = request_arg("appraiser_id")
    status = request_arg("status")
    items = [a for a in db.appraisals.values()
             if (pid is None or a["property_id"] == pid)
             and (aid is None or a["appraiser_id"] == aid)
             and (status is None or a["status"] == status)]
    return paginate(sort_entities(items), appraisal_json)


def get_appraisal(entity_id):
    require_roles(*ALL_ROLES)
    return success(appraisal_json(get_or_404(db.appraisals, entity_id, "Appraisal")))


def submit_appraisal(entity_id):
    require_roles("Appraiser")
    a = get_or_404(db.appraisals, entity_id, "Appraisal")
    if a["appraiser_id"] != g.user_id:
        raise ApiError("ERR_FORBIDDEN", 403, "Only the owning appraiser may submit this appraisal")
    if a["status"] != "DRAFT":
        raise ApiError("ERR_APPRAISAL_INVALID_STATE", 409, "Only a DRAFT appraisal can be submitted")
    a["status"] = "SUBMITTED"
    a["submitted_by_user_id"] = g.user_id
    domain.bump(a)
    return success(appraisal_json(a), 200)


def certify_appraisal(entity_id):
    require_roles("ChiefAppraiser")
    a = get_or_404(db.appraisals, entity_id, "Appraisal")
    if a["status"] != "SUBMITTED":
        raise ApiError("ERR_APPRAISAL_INVALID_STATE", 409, "Only a SUBMITTED appraisal can be certified")
    if g.user_id == a["submitted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                       "Certifier must differ from the submitting appraiser")
    eff = pdate(a["effective_date"])
    duplicate = any(
        o["id"] != a["id"] and o["property_id"] == a["property_id"]
        and o["status"] == "CERTIFIED" and pdate(o["effective_date"]) == eff
        for o in db.appraisals.values()
    )
    if duplicate:
        raise ApiError("ERR_DUPLICATE_APPRAISAL_DATE", 409,
                       "Another CERTIFIED appraisal on this property carries this effective_date")
    domain.run_certification_cascade(a, g.user_id)
    return success(appraisal_json(a), 200)


def reject_appraisal(entity_id):
    require_roles("ChiefAppraiser")
    d = body()
    rejection_reason = req_str(d, "rejection_reason")
    a = get_or_404(db.appraisals, entity_id, "Appraisal")
    if a["status"] != "SUBMITTED":
        raise ApiError("ERR_APPRAISAL_INVALID_STATE", 409, "Only a SUBMITTED appraisal can be rejected")
    a["status"] = "DRAFT"
    a["rejection_reason"] = rejection_reason
    domain.bump(a)
    return success(appraisal_json(a), 200)
