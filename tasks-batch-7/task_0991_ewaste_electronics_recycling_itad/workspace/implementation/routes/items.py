"""Item endpoints: read, triage, sanitization records, CODD, listings."""

from flask import Blueprint

import db
import serialize
import utils
from errors import (ApiError, ERR_DATA_SANITIZATION_UNVERIFIED,
                    ERR_INVALID_STATE, ERR_ITEM_NOT_FOUND,
                    ERR_MANIFEST_NOT_RECEIVED,
                    ERR_SANITIZATION_METHOD_NOT_ALLOWED, ERR_VALIDATION)
from middleware import require_roles, check_owns_account
from response import ok_object, paginate, sort_created
from services import calculations as calc

bp = Blueprint("items", __name__)

DISPOSITIONS = {"RESALE", "REFURB", "RECYCLE"}

# Triage transitions (PRD §3.4): from-state -> allowed target dispositions.
TRIAGE_ALLOWED = {
    "INTAKE": {"RESALE", "REFURB", "RECYCLE"},
    "FOR_REFURB": {"RESALE", "RECYCLE"},
    "FOR_RESALE": {"RECYCLE"},
}
TRIAGE_TARGET = {"RESALE": "FOR_RESALE", "REFURB": "FOR_REFURB", "RECYCLE": "FOR_RECYCLE"}


def get_item_or_404(item_id):
    item = db.items.get(item_id)
    if item is None:
        raise ApiError(ERR_ITEM_NOT_FOUND, 404, "no Item with the given id")
    return item


def item_account_id(item):
    manifest = db.manifests.get(item["manifest_id"])
    return manifest["account_id"] if manifest else None


@bp.get("/itad/items/<item_id>")
def read_item(item_id):
    uid, role = require_roles("PlatformAdmin", "AccountManager", "IntakeOperator",
                              "LogisticsCoordinator", "ComplianceOfficer",
                              "DestructionTechnician")
    item = get_item_or_404(item_id)
    check_owns_account(uid, role, item_account_id(item))
    return ok_object(serialize.item(item))


@bp.post("/itad/items/<item_id>/triage")
def triage_item(item_id):
    uid, role = require_roles("IntakeOperator")
    item = get_item_or_404(item_id)
    data = utils.body_json()
    disposition = utils.req_enum(data, "disposition", DISPOSITIONS)
    allowed = TRIAGE_ALLOWED.get(item["processing_status"], set())
    if disposition not in allowed:
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"cannot triage {disposition} from {item['processing_status']}")
    manifest = db.manifests[item["manifest_id"]]
    if manifest["status"] != "RECEIVED":
        raise ApiError(ERR_MANIFEST_NOT_RECEIVED, 409,
                       "triage requires the owning manifest to be RECEIVED")
    item["disposition"] = disposition
    item["processing_status"] = TRIAGE_TARGET[disposition]
    if disposition == "RECYCLE":
        item["provisional_value_cents"] = 0
    else:
        item["provisional_value_cents"] = calc.quote_estimate_cents(item)
    utils.touch(item)
    return ok_object(serialize.item(item))


@bp.post("/itad/items/<item_id>/sanitizations")
def log_sanitization(item_id):
    uid, role = require_roles("DestructionTechnician")
    item = get_item_or_404(item_id)
    data = utils.body_json()
    method = utils.req_enum(data, "method", calc.SANITIZATION_METHODS)
    outcome = utils.req_enum(data, "outcome", {"PASS", "FAIL"})
    if item["processing_status"] == "INTAKE":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "sanitization attempts are logged on triaged items")
    if not item["data_bearing"]:
        raise ApiError(ERR_VALIDATION, 400, "item is not data-bearing")
    policy = calc.active_policy()
    if policy is not None and method not in policy["sanitization_methods_allowed"]:
        raise ApiError(ERR_SANITIZATION_METHOD_NOT_ALLOWED, 422,
                       "method is not allowed by the active compliance policy")
    record = {
        "id": utils.new_id(),
        "item_id": item["id"],
        "method": method,
        "outcome": outcome,
        "logged_by_id": uid,
        "verified_by_id": None,
        "status": "LOGGED",
    }
    utils.stamp_new(record)
    db.sanitizations[record["id"]] = record
    if outcome == "PASS":
        item["data_status"] = "SANITIZED"
        utils.touch(item)
    return ok_object(serialize.sanitization(record), code=201)


@bp.get("/itad/items/<item_id>/sanitizations")
def list_sanitizations(item_id):
    uid, role = require_roles("PlatformAdmin", "ComplianceOfficer",
                              "DestructionTechnician", "IntakeOperator")
    item = get_item_or_404(item_id)
    records = sort_created([s for s in db.sanitizations.values()
                            if s["item_id"] == item["id"]])
    return paginate([serialize.sanitization(s) for s in records])


@bp.post("/itad/items/<item_id>/certificates")
def issue_codd(item_id):
    uid, role = require_roles("ComplianceOfficer")
    item = get_item_or_404(item_id)
    data = utils.body_json()
    cert_type = utils.req_str(data, "cert_type")
    if cert_type != "DATA_DESTRUCTION":
        raise ApiError(ERR_VALIDATION, 400,
                       "cert_type must be DATA_DESTRUCTION for item certificates")
    if item["data_status"] != "VERIFIED":
        raise ApiError(ERR_DATA_SANITIZATION_UNVERIFIED, 422,
                       "issuing a CODD requires data_status VERIFIED")
    certificate = {
        "id": utils.new_id(),
        "cert_type": "DATA_DESTRUCTION",
        "item_id": item["id"],
        "batch_id": None,
        "certificate_number": utils.new_cert_number(),
        "issued_by_id": uid,
        "status": "ISSUED",
    }
    utils.stamp_new(certificate)
    db.certificates[certificate["id"]] = certificate
    return ok_object(serialize.certificate(certificate), code=201)


@bp.get("/itad/items/<item_id>/certificates")
def list_item_certificates(item_id):
    uid, role = require_roles("PlatformAdmin", "ComplianceOfficer",
                              "AccountManager", "IntakeOperator")
    item = get_item_or_404(item_id)
    check_owns_account(uid, role, item_account_id(item))
    records = sort_created([c for c in db.certificates.values()
                            if c.get("item_id") == item["id"]])
    return paginate([serialize.certificate(c) for c in records])


@bp.get("/itad/items/<item_id>/listings")
def list_item_listings(item_id):
    uid, role = require_roles("PlatformAdmin", "IntakeOperator", "AccountManager")
    item = get_item_or_404(item_id)
    check_owns_account(uid, role, item_account_id(item))
    records = sort_created([l for l in db.listings.values()
                            if l["item_id"] == item["id"]])
    return paginate([serialize.listing(l) for l in records])
