"""Product endpoints (PRD 3.1, 3.3, 3.7, 3.10)."""

from decimal import Decimal

from flask import Blueprint

import calc
import cascade
import lookup
import response
import serialize
import store
import validate
from auth import authorize
from errors import ApiError, fail
from routes._common import paged
from store import db, mark_dirty, now

bp = Blueprint("products", __name__)

READERS = (
    "DesignEngineer",
    "DesignApprover",
    "TestLabTechnician",
    "ProductionSupervisor",
    "ComplianceOfficer",
    "CertificationBody",
    "SafetyDirector",
)


@bp.post("/products")
@authorize("DesignEngineer")
def create_product():
    data = validate.body()
    model_code = validate.req_str(data, "model_code", max_length=40)
    product_type = validate.req_enum(data, "product_type", calc.PRODUCT_TYPES)
    material = validate.req_enum(data, "material", calc.MATERIALS)
    duty_rating = validate.req_enum(data, "duty_rating", calc.DUTY_RATINGS)
    working_length_ft = validate.req_number(
        data, "working_length_ft", minimum=0, maximum=60, exclusive_min=True
    )
    retail_sku = validate.req_str(data, "retail_sku")

    for existing in db.products.values():
        if existing["model_code"] == model_code:
            fail("ERR_DUPLICATE_KEY", "model_code already exists: %s" % model_code)

    derived = calc.derive_product_requirements(
        product_type, material, duty_rating, working_length_ft
    )
    product = store.base_record()
    product.update(
        {
            "model_code": model_code,
            "product_type": product_type,
            "material": material,
            "duty_rating": duty_rating,
            "working_length_ft": working_length_ft,
            "retail_sku": retail_sku,
            "rated_load_lb": derived["rated_load_lb"],
            "safety_factor": derived["safety_factor"],
            "required_test_load_lb": derived["required_test_load_lb"],
            "required_pull_force_lbf": derived["required_pull_force_lbf"],
            "max_allowed_deflection_in": derived["max_allowed_deflection_in"],
            "design_status": "DRAFT",
            "market_status": "NOT_RELEASED",
            "design_frozen_at": None,
            "frozen_revision_id": None,
            "market_status_changed_at": None,
            "stop_ship_reason_code": None,
            "held_registration_count": 0,
            "risk_score_gross": Decimal("0.00"),
            "risk_score_mitigated": Decimal("0.00"),
            "dhf_retention_until": None,
            "retention_anchor_source": None,
        }
    )
    db.products[product["id"]] = product
    store.register_new(product)
    return response.created(product, serialize.product)


@bp.get("/products/<product_id>")
@authorize(*READERS)
def get_product(product_id):
    product = lookup.product(product_id)
    return response.obj(product, serialize.product)


@bp.get("/products")
@authorize(*READERS)
def list_products():
    spec = {
        "frozen_revision_id": "frozen_revision_id",
        "product_type": "product_type",
        "material": "material",
        "duty_rating": "duty_rating",
        "design_status": "design_status",
        "market_status": "market_status",
    }
    return paged(lookup.rows(db.products), spec, serialize.product)


@bp.post("/products/<product_id>/freeze-design")
@authorize("DesignApprover")
def freeze_design(product_id):
    product = lookup.product(product_id)
    data = validate.body()

    # step 4 — body foreign key
    revision = None
    if validate.present(data, "frozen_revision_id"):
        revision = lookup.design_revision(data["frozen_revision_id"])
    # step 6 — shape
    validate.req_id(data, "frozen_revision_id")

    # step 18 — product state
    if product["design_status"] != "DRAFT":
        fail("ERR_PRODUCT_STATE_INVALID", "design_status must be DRAFT to freeze")

    # step 32 — revision belongs to the product
    if revision["product_id"] != product["id"]:
        fail("ERR_REVISION_PRODUCT_MISMATCH", "revision belongs to another product")

    # step 36 — revision approved and not superseded
    if revision["status"] != "APPROVED" or revision["superseded_at"] is not None:
        fail("ERR_REVISION_NOT_APPROVED", "revision must be APPROVED and not superseded")

    # step 38 — qualifying campaign pinned to this revision
    qualified = False
    for campaign in lookup.campaigns_of_product(product["id"]):
        if (
            campaign["design_revision_id"] == revision["id"]
            and campaign["purpose"] == "DESIGN_QUALIFICATION"
            and campaign["status"] == "PASSED"
        ):
            qualified = True
            break
    if not qualified:
        fail(
            "ERR_QUALIFYING_CAMPAIGN_MISSING",
            "a PASSED DESIGN_QUALIFICATION campaign on this revision is required",
        )

    product["design_status"] = "DESIGN_FROZEN"
    product["design_frozen_at"] = now()
    product["frozen_revision_id"] = revision["id"]
    mark_dirty(product)
    cascade.recompute_dhf_retention(product)
    return response.obj(product, serialize.product)


@bp.post("/products/<product_id>/release-to-retail")
@authorize("ComplianceOfficer")
def release_to_retail(product_id):
    product = lookup.product(product_id)

    # step 18
    if product["market_status"] != "NOT_RELEASED":
        fail("ERR_PRODUCT_STATE_INVALID", "market_status must be NOT_RELEASED")

    # step 30 — complete approved label / document set
    approved = set(
        document["doc_kind"]
        for document in lookup.documents_of_product(product["id"])
        if document["status"] == "APPROVED"
    )
    for kind in calc.REQUIRED_DOC_KINDS:
        if kind not in approved:
            fail("ERR_LABEL_SET_INCOMPLETE", "missing APPROVED document of kind %s" % kind)

    # step 37
    if product["design_status"] != "DESIGN_FROZEN":
        fail("ERR_DESIGN_NOT_FROZEN", "design_status must be DESIGN_FROZEN")

    # step 40
    listed = [
        record
        for record in lookup.listings_of_product(product["id"])
        if record["status"] == "LISTED"
    ]
    if not listed:
        fail("ERR_NO_ACTIVE_LISTING", "at least one LISTED listing record is required")

    product["market_status"] = "RETAIL_RELEASED"
    product["market_status_changed_at"] = now()
    mark_dirty(product)
    return response.obj(product, serialize.product)


@bp.post("/products/<product_id>/stop-ship")
@authorize("ComplianceOfficer", "SafetyDirector")
def stop_ship(product_id):
    product = lookup.product(product_id)
    data = validate.body()
    reason_code = validate.req_enum(data, "reason_code", calc.STOP_SHIP_REASONS)

    if product["market_status"] != "RETAIL_RELEASED":
        fail("ERR_PRODUCT_STATE_INVALID", "market_status must be RETAIL_RELEASED")

    cascade.product_enter_stop_ship(product, reason_code)
    return response.obj(product, serialize.product)


@bp.post("/products/<product_id>/resume-ship")
@authorize("SafetyDirector")
def resume_ship(product_id):
    product = lookup.product(product_id)

    if product["market_status"] != "STOP_SHIP":
        fail("ERR_PRODUCT_STATE_INVALID", "market_status must be STOP_SHIP")
    if product["risk_score_mitigated"] >= calc.RISK_CLEAR_THRESHOLD:
        fail(
            "ERR_RISK_SCORE_ABOVE_THRESHOLD",
            "risk_score_mitigated must be below %s" % calc.RISK_CLEAR_THRESHOLD,
        )
    for lot in lookup.lots_of_product(product["id"]):
        if lot["status"] == "QUARANTINED":
            fail("ERR_QUARANTINE_HOLD_PRESENT", "a QUARANTINED lot is still open")
    if product["held_registration_count"] != 0:
        fail("ERR_QUARANTINE_HOLD_PRESENT", "registrations are still on hold")

    cascade.product_resume_ship(product)
    return response.obj(product, serialize.product)


@bp.get("/products/<product_id>/documents")
@authorize(
    "DesignEngineer", "DesignApprover", "ComplianceOfficer", "CertificationBody", "SafetyDirector"
)
def list_product_documents(product_id):
    product = lookup.product(product_id)
    spec = {"doc_kind": "doc_kind", "status": "status"}
    return paged(lookup.documents_of_product(product["id"]), spec, serialize.product_document)


@bp.get("/products/<product_id>/liability-dossier")
@authorize("ComplianceOfficer", "SafetyDirector")
def liability_dossier(product_id):
    product = lookup.product(product_id)

    revisions = lookup.revisions_of_product(product["id"])
    approved_kinds = set(
        document["doc_kind"]
        for document in lookup.documents_of_product(product["id"])
        if document["status"] == "APPROVED"
    )
    passed_campaigns = [
        campaign
        for campaign in lookup.campaigns_of_product(product["id"])
        if campaign["status"] == "PASSED"
    ]
    released_lots = [
        lot for lot in lookup.lots_of_product(product["id"]) if lot["status"] == "RELEASED"
    ]
    open_incidents = [
        incident
        for incident in lookup.incidents_of_product(product["id"])
        if incident["status"] not in ("CLOSED", "NOT_SUBSTANTIATED")
    ]

    payload = {
        "product_id": product["id"],
        "model_code": product["model_code"],
        "design_history_revision_count": len(revisions),
        "approved_document_kinds": [k for k in calc.DOC_KINDS if k in approved_kinds],
        "passed_campaign_count": len(passed_campaigns),
        "released_lot_count": len(released_lots),
        "open_incident_count": len(open_incidents),
        "risk_score_gross": float(product["risk_score_gross"]),
        "risk_score_mitigated": float(product["risk_score_mitigated"]),
        "dhf_retention_until": response.fmt_instant(product["dhf_retention_until"]),
        "retention_anchor_source": product["retention_anchor_source"],
    }
    return response.raw(payload)
