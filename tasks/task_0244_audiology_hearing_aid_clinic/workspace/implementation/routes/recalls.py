"""Recall notice endpoints + fleet remediation."""

from flask import Blueprint, request

from db import db
import serialize
import validate
import errors
from middleware import require_auth, require_role, get_json_body
from response import object_response, array_response
from services.domain import get_or_404
from services.listing import list_page

bp = Blueprint("recalls", __name__)

SEVERITY_LEVELS = {"ADVISORY", "MANDATORY"}


@bp.post("/clinic/recalls")
def create_recall():
    auth = require_auth()
    require_role(auth, {"ClinicAdmin"})
    body = get_json_body()
    device_model_id = validate.require_str(body, "device_model_id")
    affected_fw = validate.require_str(body, "affected_firmware_version")
    target_fw = validate.require_str(body, "target_firmware_version")
    severity_level = validate.require_enum(body, "severity_level", SEVERITY_LEVELS)

    get_or_404(db.device_models, device_model_id)

    obj = {
        "device_model_id": device_model_id,
        "affected_firmware_version": affected_fw,
        "target_firmware_version": target_fw,
        "severity_level": severity_level,
        "affected_order_count": 0,
        "status": "DRAFT",
    }
    db.stamp_create(obj)
    with db.lock:
        db.recalls[obj["id"]] = obj
    return object_response(serialize.recall(obj), 201)


@bp.post("/clinic/recalls/<rid>/issue")
def issue_recall(rid):
    auth = require_auth()
    require_role(auth, {"ClinicAdmin"})
    body = get_json_body()

    with db.lock:
        # Existence (404) and state (409) precede business rules per the PRD
        # validation chain; the OCC body field is checked after them.
        recall = get_or_404(db.recalls, rid)
        if recall["status"] != "DRAFT":
            raise errors.invalid_state("Only a DRAFT recall may be issued.")
        # OCC field is non-optional (missing/wrong-type -> ERR_INVALID_REQUEST).
        expected = validate.require_int(body, "expected_recall_notice_version")
        # OCC value check (priority 19).
        if expected != recall["version"]:
            raise errors.stale_version("expected_recall_notice_version is stale.")

        # Direct fan-out: count WARRANTY_ACTIVE orders on this model whose fitted
        # firmware equals the affected firmware.
        matched = [o for o in db.orders.values()
                   if o["device_model_id"] == recall["device_model_id"]
                   and o.get("fitted_firmware_version") == recall["affected_firmware_version"]
                   and o["status"] == "WARRANTY_ACTIVE"]
        recall["affected_order_count"] = len(matched)
        recall["status"] = "ISSUED"
        db.touch(recall)
    return object_response(serialize.recall(recall))


@bp.post("/clinic/recalls/<rid>/close")
def close_recall(rid):
    auth = require_auth()
    require_role(auth, {"ClinicAdmin"})
    with db.lock:
        recall = get_or_404(db.recalls, rid)
        if recall["status"] != "ISSUED":
            raise errors.invalid_state("Only an ISSUED recall may be closed.")

        # MANDATORY: every affected order must have a COMPLETED RECALL_REPROGRAM
        # adjustment whose applied_firmware_version == target_firmware_version.
        if recall["severity_level"] == "MANDATORY":
            affected = [o for o in db.orders.values()
                        if o["device_model_id"] == recall["device_model_id"]
                        and o.get("fitted_firmware_version") == recall["affected_firmware_version"]
                        and o["status"] == "WARRANTY_ACTIVE"]
            for order in affected:
                if not _has_remediation(order, recall):
                    raise errors.ApiError(errors.ERR_RECALL_NOT_REMEDIATED, 422,
                                          "Not all affected orders have been remediated.")

        recall["status"] = "CLOSED"
        db.touch(recall)
    return object_response(serialize.recall(recall))


@bp.get("/clinic/recalls/<rid>")
def get_recall(rid):
    auth = require_auth()
    require_role(auth, {"ClinicAdmin", "Audiologist", "BillingClerk"})
    recall = get_or_404(db.recalls, rid)
    return object_response(serialize.recall(recall))


@bp.get("/clinic/recalls")
def list_recalls():
    auth = require_auth()
    require_role(auth, {"ClinicAdmin", "Audiologist", "BillingClerk"})
    a = request.args
    device_model_id = a.get("device_model_id")
    status = a.get("status")
    severity_level = a.get("severity_level")
    items = [r for r in db.recalls.values()
             if (device_model_id is None or r["device_model_id"] == device_model_id)
             and (status is None or r["status"] == status)
             and (severity_level is None or r["severity_level"] == severity_level)]
    page, limit, offset, total = list_page(a, items, serialize.recall)
    return array_response(page, limit, offset, total)


@bp.get("/clinic/recalls/<rid>/adjustments")
def list_recall_adjustments(rid):
    auth = require_auth()
    require_role(auth, {"ClinicAdmin", "Audiologist", "BillingClerk"})
    get_or_404(db.recalls, rid)
    status = request.args.get("status")
    items = [adj for adj in db.adjustments.values()
             if adj.get("recall_notice_id") == rid
             and (status is None or adj["status"] == status)]
    page, limit, offset, total = list_page(request.args, items, serialize.adjustment)
    return array_response(page, limit, offset, total)


def _has_remediation(order, recall):
    for adj in db.adjustments.values():
        if (adj["fitting_order_id"] == order["id"]
                and adj["status"] == "COMPLETED"
                and adj["reason"] == "RECALL_REPROGRAM"
                and adj.get("applied_firmware_version") == recall["target_firmware_version"]):
            return True
    return False
