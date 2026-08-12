"""ExtensionRequest endpoints: draft, submit, approve/deny, revise loop."""
from flask import g

import db
import domain
from domain import extension_json, sort_entities, TERMINAL_LIFECYCLE, MAX_TOTAL_EXTENSION_DAYS
from envelope import success
from errors import ApiError
from routes.common import (require_roles, body, req_str, req_int, paginate, get_or_404)
from routes.properties import ALL_ROLES, request_arg


def _req_days(d):
    days = req_int(d, "requested_extension_days")
    if days < 1 or days > MAX_TOTAL_EXTENSION_DAYS:
        raise ApiError("ERR_VALIDATION", 400, "requested_extension_days must be in 1..1825")
    return days


def create_extension():
    require_roles("ComplianceOfficer")
    d = body()
    property_id = req_str(d, "property_id")
    days = _req_days(d)
    justification = req_str(d, "justification")
    get_or_404(db.properties, property_id, "Property")
    e = domain.base_entity()
    e.update({
        "property_id": property_id,
        "requested_extension_days": days,
        "justification": justification,
        "status": "DRAFT",
        "submitted_by_user_id": None,
        "decided_by_user_id": None,
    })
    db.extensions[e["id"]] = e
    return success(extension_json(e), 201)


def list_extensions():
    require_roles(*ALL_ROLES)
    pid = request_arg("property_id")
    status = request_arg("status")
    items = [e for e in db.extensions.values()
             if (pid is None or e["property_id"] == pid)
             and (status is None or e["status"] == status)]
    return paginate(sort_entities(items), extension_json)


def get_extension(entity_id):
    require_roles(*ALL_ROLES)
    return success(extension_json(get_or_404(db.extensions, entity_id, "Extension request")))


def submit_extension(entity_id):
    require_roles("ComplianceOfficer")
    e = get_or_404(db.extensions, entity_id, "Extension request")
    if e["status"] != "DRAFT":
        raise ApiError("ERR_EXTENSION_INVALID_STATE", 409, "Only a DRAFT request can be submitted")
    p = db.properties[e["property_id"]]
    if p["lifecycle_status"] in TERMINAL_LIFECYCLE:
        raise ApiError("ERR_PROPERTY_ALREADY_TERMINAL", 409,
                       "The regulator will not consider a terminal property")
    e["status"] = "SUBMITTED"
    e["submitted_by_user_id"] = g.user_id
    domain.bump(e)
    return success(extension_json(e), 200)


def approve_extension(entity_id):
    require_roles("OREOCommittee")
    e = get_or_404(db.extensions, entity_id, "Extension request")
    if e["status"] != "SUBMITTED":
        raise ApiError("ERR_EXTENSION_INVALID_STATE", 409, "Only a SUBMITTED request can be approved")
    p = db.properties[e["property_id"]]
    approved = domain.extension_days_approved(p["id"])
    if approved + e["requested_extension_days"] > MAX_TOTAL_EXTENSION_DAYS:
        raise ApiError("ERR_EXTENSION_CAP_EXCEEDED", 422,
                       "Approval would exceed the 1825-day aggregate allowance")
    e["status"] = "APPROVED"
    e["decided_by_user_id"] = g.user_id
    domain.bump(e)
    domain.bump(p)  # extension_days_approved and holding_deadline are derived
    return success(extension_json(e), 200)


def deny_extension(entity_id):
    require_roles("OREOCommittee")
    e = get_or_404(db.extensions, entity_id, "Extension request")
    if e["status"] != "SUBMITTED":
        raise ApiError("ERR_EXTENSION_INVALID_STATE", 409, "Only a SUBMITTED request can be denied")
    e["status"] = "DENIED"
    e["decided_by_user_id"] = g.user_id
    domain.bump(e)
    return success(extension_json(e), 200)


def revise_extension(entity_id):
    require_roles("ComplianceOfficer")
    d = body()
    days = _req_days(d)
    e = get_or_404(db.extensions, entity_id, "Extension request")
    if e["status"] != "DENIED":
        raise ApiError("ERR_EXTENSION_INVALID_STATE", 409, "Only a DENIED request can be revised")
    e["status"] = "DRAFT"
    e["requested_extension_days"] = days
    domain.bump(e)
    return success(extension_json(e), 200)
