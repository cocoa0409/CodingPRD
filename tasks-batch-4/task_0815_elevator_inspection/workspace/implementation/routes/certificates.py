from flask import Blueprint, g, request

import errors
from auth import require
from common import (
    get_body,
    lookup,
    paginate,
    parse_pagination,
    require_int,
    require_string,
)
from constants import INTERVAL_MONTHS
from envelope import array_response, object_response
from services import logic
from services.logic import effective_cert_status, serialize_certificate
from store import base_fields, db, new_id, touch

bp = Blueprint("certificates", __name__)


@bp.route("/certificates", methods=["POST"])
@require("Registrar")
def create_certificate():
    body = get_body()
    device_id = require_string(body, "device_id")
    source_inspection_id = require_string(body, "source_inspection_id")
    expected_version = require_int(body, "expected_device_version")

    # FK existence (priority 4)
    device = lookup(db.devices, device_id, "ERR_DEVICE_NOT_FOUND")
    inspection = lookup(db.inspections, source_inspection_id, "ERR_INSPECTION_NOT_FOUND")

    # OCC (priority 6)
    if expected_version != device["version"]:
        raise errors.ApiError("ERR_STALE_DEVICE_VERSION", 412,
                              "expected_device_version does not match the device version.")
    # Source inspection PASSED (priority 8)
    if inspection["status"] != "PASSED":
        raise errors.ApiError("ERR_SOURCE_INSPECTION_NOT_PASSED", 409,
                              "Source inspection is not PASSED.")
    # Zero OPEN deficiencies on the device (priority 12)
    if any(d["status"] == "OPEN" for d in logic.device_deficiencies(device_id)):
        raise errors.ApiError("ERR_OPEN_DEFICIENCIES_EXIST", 409,
                              "Device has open deficiencies.")
    # Source inspection device mismatch (priority 15)
    if inspection["device_id"] != device_id:
        raise errors.ApiError("ERR_INSPECTION_DEVICE_MISMATCH", 409,
                              "Source inspection belongs to a different device.")
    # Outstanding balance must be 0 (priority 16)
    if logic.outstanding_balance(device_id) != 0:
        raise errors.ApiError("ERR_OUTSTANDING_BALANCE", 402,
                              "Device has an outstanding balance.")

    # Supersede prior active certificate.
    prior = logic.active_cert(device)
    if prior is not None:
        prior["status"] = "SUPERSEDED"
        touch(prior)

    issue_period = db.current_period_index
    cert = base_fields()
    cert.update({
        "device_id": device_id,
        "source_inspection_id": source_inspection_id,
        "certificate_number": "CERT-" + new_id()[:12].upper(),
        "issue_period": issue_period,
        "expiry_period": issue_period + INTERVAL_MONTHS[device["category"]],
        "posted_period": None,
        "status": "ISSUED",
        "_pre_suspension_status": None,
    })
    db.certificates[cert["id"]] = cert

    if device["status"] == "REGISTERED":
        device["status"] = "ACTIVE"
    touch(device)  # supersede-in-place advances device.version by 1

    return object_response(serialize_certificate(cert), 201)


@bp.route("/certificates/<certificate_id>", methods=["GET"])
@require("Registrar", "SafetyAdministrator", "LicensedInspector", "BuildingOwner")
def get_certificate(certificate_id):
    c = lookup(db.certificates, certificate_id, "ERR_CERTIFICATE_NOT_FOUND")
    return object_response(serialize_certificate(c), 200)


@bp.route("/certificates", methods=["GET"])
@require("Registrar", "SafetyAdministrator", "LicensedInspector", "BuildingOwner")
def list_certificates():
    limit, offset = parse_pagination()
    device_id = request.args.get("device_id")
    source_inspection_id = request.args.get("source_inspection_id")
    status = request.args.get("status")
    items = list(db.certificates.values())
    if device_id is not None:
        items = [c for c in items if c["device_id"] == device_id]
    if source_inspection_id is not None:
        items = [c for c in items if c["source_inspection_id"] == source_inspection_id]
    if status is not None:
        items = [c for c in items if effective_cert_status(c) == status]
    page, total = paginate(items, limit, offset)
    return array_response([serialize_certificate(c) for c in page], limit, offset, total)


@bp.route("/certificates/<certificate_id>/post", methods=["POST"])
@require("BuildingOwner")
def post_certificate(certificate_id):
    c = lookup(db.certificates, certificate_id, "ERR_CERTIFICATE_NOT_FOUND")
    device = db.devices[c["device_id"]]
    if device["owner_id"] != g.user_id:
        raise errors.not_resource_owner()
    if c["status"] != "ISSUED":
        raise errors.ApiError("ERR_CERTIFICATE_NOT_POSTABLE", 409,
                              "Certificate is not postable.")
    c["status"] = "POSTED"
    c["posted_period"] = db.current_period_index
    touch(c)
    return object_response(serialize_certificate(c), 200)
