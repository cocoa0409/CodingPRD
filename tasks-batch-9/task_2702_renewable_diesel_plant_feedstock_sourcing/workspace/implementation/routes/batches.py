"""Finished product batches: certification and distribution (PRD 3.7)."""
from flask import Blueprint

import response
import store
import validate
from constants import ASTM_ANNEXES, SAF_MAX_FREEZE_POINT_C
from errors import (
    ERR_INVALID_BATCH_CERT_STATE,
    ERR_INVALID_BATCH_DISTRIBUTION_STATE,
    ERR_INVALID_RUN_STATE,
    ERR_SAF_CERTIFICATION_REQUIRED,
    ERR_SAF_SPEC_OUT_OF_RANGE,
    fail,
)
from routes.helpers import find, listing
from store import bump, q

bp = Blueprint("batches", __name__)


@bp.get("/product-batches/<batch_id>")
def read_batch(batch_id):
    validate.auth("PlantOperator", "ComplianceOfficer", "IndependentVerifier")
    return response.ok(find("batch", batch_id))


@bp.get("/product-batches")
def list_batches():
    validate.auth("PlantOperator", "ComplianceOfficer", "IndependentVerifier")
    rows, limit, offset = listing(store.table_rows(store.batches), {
        "run_id": "run_id",
        "product_type": "product_type",
        "cert_status": "cert_status",
        "distribution_status": "distribution_status",
    })
    return response.page(rows, limit, offset)


@bp.post("/product-batches/<batch_id>/certification-requests")
def request_certification(batch_id):
    validate.auth("ComplianceOfficer")
    batch = find("batch", batch_id)
    data = validate.body()
    annex = validate.get_enum(data, "astm_annex", ASTM_ANNEXES)
    freeze_point = validate.get_num(data, "freeze_point_c", -80, 0, 1)

    if batch["cert_status"] not in ("UNCERTIFIED", "CERT_REJECTED"):
        fail(ERR_INVALID_BATCH_CERT_STATE,
             "A batch at %s cannot take a certification request." % batch["cert_status"])

    run = store.runs.get(batch["run_id"])
    if run is None or run["status"] not in ("COMPLETED", "RECONCILED"):
        fail(ERR_INVALID_RUN_STATE,
             "The producing campaign must be COMPLETED or RECONCILED.")

    batch["astm_annex"] = annex
    batch["freeze_point_c"] = q(freeze_point, 1)
    batch["cert_reject_reason"] = None
    batch["cert_status"] = "CERT_PENDING"
    bump(batch)
    return response.ok(batch)


@bp.post("/product-batches/<batch_id>/certification-decisions")
def decide_certification(batch_id):
    validate.auth("IndependentVerifier")
    batch = find("batch", batch_id)
    data = validate.body()
    decision = validate.get_enum(data, "decision", ("CERTIFY", "REJECT"))
    note = validate.get_str(data, "note", 1, 500, required=False, default=None)

    if batch["cert_status"] != "CERT_PENDING":
        fail(ERR_INVALID_BATCH_CERT_STATE,
             "Only a CERT_PENDING batch may be decided; this one is %s."
             % batch["cert_status"])

    if decision == "CERTIFY":
        if batch["product_type"] == "SAF":
            if batch["astm_annex"] is None:
                fail(ERR_SAF_SPEC_OUT_OF_RANGE,
                     "A SAF batch requires a recorded astm_annex to be certified.")
            if batch["freeze_point_c"] is None \
                    or batch["freeze_point_c"] > SAF_MAX_FREEZE_POINT_C:
                fail(ERR_SAF_SPEC_OUT_OF_RANGE,
                     "A SAF batch must have freeze_point_c at or below %s degrees Celsius."
                     % SAF_MAX_FREEZE_POINT_C)
        batch["cert_status"] = "CERTIFIED"
    else:
        batch["cert_status"] = "CERT_REJECTED"
        batch["cert_reject_reason"] = note
    bump(batch)
    return response.ok(batch)


@bp.post("/product-batches/<batch_id>/reservations")
def reserve_batch(batch_id):
    validate.auth("ComplianceOfficer")
    batch = find("batch", batch_id)
    data = validate.body()
    offtaker = validate.get_str(data, "offtaker_name", 1, 120)

    if batch["distribution_status"] != "IN_TANK":
        fail(ERR_INVALID_BATCH_DISTRIBUTION_STATE,
             "Only an IN_TANK batch may be reserved; this one is %s."
             % batch["distribution_status"])

    batch["offtaker_name"] = offtaker
    batch["distribution_status"] = "RESERVED"
    bump(batch)
    return response.ok(batch)


@bp.post("/product-batches/<batch_id>/reservation-releases")
def release_reservation(batch_id):
    validate.auth("ComplianceOfficer")
    batch = find("batch", batch_id)
    if batch["distribution_status"] != "RESERVED":
        fail(ERR_INVALID_BATCH_DISTRIBUTION_STATE,
             "Only a RESERVED batch may be released; this one is %s."
             % batch["distribution_status"])
    batch["distribution_status"] = "IN_TANK"
    batch["offtaker_name"] = None
    bump(batch)
    return response.ok(batch)


@bp.post("/product-batches/<batch_id>/shipments")
def ship_batch(batch_id):
    validate.auth("ComplianceOfficer")
    batch = find("batch", batch_id)
    if batch["distribution_status"] != "RESERVED":
        fail(ERR_INVALID_BATCH_DISTRIBUTION_STATE,
             "Only a RESERVED batch may ship; this one is %s."
             % batch["distribution_status"])
    if batch["product_type"] == "SAF" and batch["cert_status"] != "CERTIFIED":
        fail(ERR_SAF_CERTIFICATION_REQUIRED,
             "A SAF batch must be CERTIFIED before it may ship.")
    batch["distribution_status"] = "SHIPPED"
    bump(batch)
    return response.ok(batch)
