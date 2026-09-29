"""Closing packages: recording and document delivery (PRD 3.8)."""

from flask import Blueprint

import auth
import derive
import errors
import validators
from envelope import listing, ok
from errors import fail
from helpers import collect, get_package, page
from store import db

bp = Blueprint("closing", __name__)

PACKAGE_STATUSES = ("AWAITING_RECORDING", "RECORDED", "DELIVERED")
DELIVERY_METHODS = ("COURIER", "ELECTRONIC_PORTAL", "CERTIFIED_MAIL")


@bp.post("/closing-packages/<package_id>/record")
def record_package(package_id):
    auth.require(auth.CONTRACT_ADMINISTRATOR)
    data = validators.body()
    reference = validators.string(data, "recording_reference", 1, 120)
    jurisdiction = validators.string(data, "recording_jurisdiction", 1, 120)
    package = get_package(package_id)

    if package["status"] != "AWAITING_RECORDING":
        fail(errors.ERR_INVALID_CLOSING_PACKAGE_STATE, "package is not AWAITING_RECORDING")
    agreement = db.agreements.get(package["agreement_id"])
    if agreement is None or agreement["fulfillment_status"] != "FUNDED":
        fail(errors.ERR_INVALID_AGREEMENT_STATE, "the agreement is not FUNDED")

    derive.setf(package, "status", "RECORDED")
    derive.setf(package, "recording_reference", reference)
    derive.setf(package, "recording_jurisdiction", jurisdiction)
    derive.setf(package, "recorded_at", db.now())
    derive.setf(agreement, "fulfillment_status", "RECORDED")
    return ok(package)


@bp.post("/closing-packages/<package_id>/deliver")
def deliver_package(package_id):
    auth.require(auth.CONTRACT_ADMINISTRATOR)
    data = validators.body()
    method = validators.enum(data, "delivery_method", DELIVERY_METHODS)
    package = get_package(package_id)

    if package["status"] != "RECORDED":
        fail(errors.ERR_INVALID_CLOSING_PACKAGE_STATE, "package is not RECORDED")

    derive.setf(package, "status", "DELIVERED")
    derive.setf(package, "delivery_method", method)
    derive.setf(package, "documents_delivered_at", db.now())
    agreement = db.agreements.get(package["agreement_id"])
    if agreement is not None:
        derive.setf(agreement, "fulfillment_status", "DOCS_DELIVERED")
    return ok(package)


@bp.get("/closing-packages/<package_id>")
def read_package(package_id):
    auth.require_any()
    return ok(get_package(package_id))


@bp.get("/closing-packages")
def list_packages():
    auth.require_any()
    limit, offset = page()
    rows = collect(
        db.packages,
        (("agreement_id", "agreement_id"), ("status", "status", PACKAGE_STATUSES)),
    )
    return listing(rows, limit, offset)
