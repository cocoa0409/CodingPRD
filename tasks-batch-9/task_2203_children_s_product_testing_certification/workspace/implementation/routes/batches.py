"""Production batches, tracking labels and distribution control (PRD 3.8)."""

from flask import Blueprint

import auth
import clock
import db
import paging
import refs
import response
import validation
from errors import ApiError
from routes.products import guard_not_archived
from services import calc, engine

bp = Blueprint("batches", __name__)

DISTRIBUTION_STATES = {"HELD", "RELEASED", "STOP_DISTRIBUTION", "DESTROYED"}
BATCH_READ_ROLES = (
    "ComplianceAdministrator",
    "CertificationOfficer",
    "DistributionManager",
)


def _coverage_start(certificate):
    if certificate["issuance_status"] == "DRAFT":
        return certificate["created_at"]
    if certificate["issued_at"] is not None:
        return certificate["issued_at"]
    return certificate["created_at"]


def require_inside_coverage(certificate, produced_on):
    if produced_on < _coverage_start(certificate):
        raise ApiError("ERR_BATCH_OUTSIDE_CERTIFICATE_COVERAGE")
    year, month = certificate["manufacture_date_month"].split("-")
    produced = clock.to_utc(produced_on)
    if produced.year != int(year) or produced.month != int(month):
        raise ApiError("ERR_BATCH_OUTSIDE_CERTIFICATE_COVERAGE")


@bp.post("/products/<product_id>/production-batches")
def record_batch(product_id):
    auth.require_roles("DistributionManager")
    body = validation.json_body()
    certificate_id = validation.id_field(body, "certificate_id")
    batch_code = validation.string_field(
        body, "batch_code", min_len=4, max_len=17, pattern=validation.RE_BATCH_CODE
    )
    produced_on = validation.datetime_field(body, "produced_on")
    quantity = validation.int_field(body, "quantity", minimum=1)
    label_on_product = validation.bool_field(
        body, "label_on_product", required=False, default=False
    )
    label_on_packaging = validation.bool_field(
        body, "label_on_packaging", required=False, default=False
    )
    label_batch_code_printed = validation.bool_field(
        body, "label_batch_code_printed", required=False, default=False
    )

    product = refs.product(product_id)
    certificate = refs.require_child_of("certificates", certificate_id, product["id"])
    guard_not_archived(product)
    require_inside_coverage(certificate, produced_on)
    for existing in db.find("production_batches", product_id=product["id"]):
        if existing["batch_code"] == batch_code:
            raise ApiError("ERR_BATCH_CODE_DUPLICATE")

    draft = {
        "product_id": product["id"],
        "certificate_id": certificate["id"],
        "batch_code": batch_code,
        "produced_on": produced_on,
        "quantity": quantity,
        "label_on_product": label_on_product,
        "label_on_packaging": label_on_packaging,
        "label_batch_code_printed": label_batch_code_printed,
        "tracking_label_compliant": False,
        "distribution_state": "HELD",
        "released_at": None,
        "release_rescind_count": 0,
    }
    draft["tracking_label_compliant"] = calc.tracking_label_compliant(draft, product)
    row = db.insert("production_batches", draft)
    engine.recompute_distribution(product)
    engine.bump("products", product)
    return response.object_response(db.serialize("production_batches", row), 201)


@bp.get("/production-batches/<batch_id>")
def get_batch(batch_id):
    auth.require_roles(*BATCH_READ_ROLES)
    row = refs.batch(batch_id)
    return response.object_response(db.serialize("production_batches", row))


@bp.get("/production-batches")
def list_batches():
    auth.require_roles(*BATCH_READ_ROLES)
    product_id = validation.query_string("product_id")
    certificate_id = validation.query_string("certificate_id")
    distribution_state = validation.query_enum(
        "distribution_state", DISTRIBUTION_STATES
    )
    return paging.build(
        "production_batches",
        [
            paging.eq_filter("product_id", product_id),
            paging.eq_filter("certificate_id", certificate_id),
            paging.eq_filter("distribution_state", distribution_state),
        ],
    )


@bp.post("/production-batches/<batch_id>/tracking-label")
def update_tracking_label(batch_id):
    auth.require_roles("DistributionManager")
    body = validation.json_body()
    label_on_product = validation.bool_field(body, "label_on_product")
    label_on_packaging = validation.bool_field(body, "label_on_packaging")
    label_batch_code_printed = validation.bool_field(body, "label_batch_code_printed")
    batch = refs.batch(batch_id)
    product = refs.product(batch["product_id"])
    guard_not_archived(product)
    if batch["distribution_state"] not in ("HELD", "STOP_DISTRIBUTION"):
        raise ApiError("ERR_BATCH_STATE_INVALID")

    batch["label_on_product"] = label_on_product
    batch["label_on_packaging"] = label_on_packaging
    batch["label_batch_code_printed"] = label_batch_code_printed
    batch["tracking_label_compliant"] = calc.tracking_label_compliant(batch, product)
    engine.bump("production_batches", batch)
    return response.object_response(db.serialize("production_batches", batch))


@bp.post("/production-batches/<batch_id>/release")
def release_batch(batch_id):
    auth.require_roles("DistributionManager")
    batch = refs.batch(batch_id)
    product = refs.product(batch["product_id"])
    certificate = refs.certificate(batch["certificate_id"])
    guard_not_archived(product)
    if (
        certificate["issuance_status"] != "ISSUED"
        or certificate["accompaniment_status"] != "FURNISHED"
    ):
        raise ApiError("ERR_CERTIFICATE_STATE_INVALID")
    if batch["distribution_state"] != "HELD":
        raise ApiError("ERR_BATCH_STATE_INVALID")
    if product["compliance_posture"] != "CLEARED":
        raise ApiError("ERR_PRODUCT_POSTURE_NOT_CLEARED")
    if not batch["tracking_label_compliant"]:
        raise ApiError("ERR_TRACKING_LABEL_NONCOMPLIANT")

    batch["distribution_state"] = "RELEASED"
    batch["released_at"] = clock.now()
    engine.bump("production_batches", batch)
    engine.recompute_distribution(product)
    engine.bump("products", product)
    return response.object_response(db.serialize("production_batches", batch))


@bp.post("/production-batches/<batch_id>/rescind-release")
def rescind_release(batch_id):
    auth.require_roles("DistributionManager")
    batch = refs.batch(batch_id)
    product = refs.product(batch["product_id"])
    guard_not_archived(product)
    if batch["distribution_state"] != "RELEASED":
        raise ApiError("ERR_BATCH_STATE_INVALID")

    batch["distribution_state"] = "HELD"
    batch["released_at"] = None
    batch["release_rescind_count"] += 1
    engine.bump("production_batches", batch)
    engine.recompute_distribution(product)
    engine.bump("products", product)
    return response.object_response(db.serialize("production_batches", batch))
