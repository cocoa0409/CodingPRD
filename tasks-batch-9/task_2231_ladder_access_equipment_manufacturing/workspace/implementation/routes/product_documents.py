"""ProductDocument endpoints (PRD 3.3)."""

from flask import Blueprint

import calc
import lookup
import response
import serialize
import store
import validate
from auth import authorize
from errors import fail
from store import db, mark_dirty, now

bp = Blueprint("product_documents", __name__)


def _check_label_rules(doc_kind, placement_zone, pictogram_count, includes_assembly):
    """Ladder step 31 — ERR_LABEL_PLACEMENT_INVALID."""
    if doc_kind in calc.LABEL_DOC_KINDS:
        if placement_zone is None:
            fail("ERR_LABEL_PLACEMENT_INVALID", "placement_zone is required for label kinds")
    else:
        if placement_zone is not None:
            fail("ERR_LABEL_PLACEMENT_INVALID", "placement_zone must be null for non-label kinds")
    if doc_kind == "WARNING_LABEL" and (pictogram_count or 0) < calc.MIN_WARNING_PICTOGRAMS:
        fail(
            "ERR_LABEL_PLACEMENT_INVALID",
            "a WARNING_LABEL requires at least %d pictograms" % calc.MIN_WARNING_PICTOGRAMS,
        )
    if doc_kind == "ASSEMBLY_INSTRUCTION_SHEET" and not includes_assembly:
        fail(
            "ERR_LABEL_PLACEMENT_INVALID",
            "an ASSEMBLY_INSTRUCTION_SHEET requires includes_assembly_instructions true",
        )


@bp.post("/product-documents")
@authorize("DesignEngineer", "ComplianceOfficer")
def create_product_document():
    data = validate.body()

    product = None
    if validate.present(data, "product_id"):
        product = lookup.product(data["product_id"])

    validate.req_id(data, "product_id")
    doc_kind = validate.req_enum(data, "doc_kind", calc.DOC_KINDS)
    document_version = validate.req_str(data, "document_version")
    text_digest = validate.req_str(data, "text_digest")
    placement_zone = validate.opt_enum(data, "placement_zone", calc.PLACEMENT_ZONES)
    pictogram_count = validate.opt_int(data, "pictogram_count", minimum=0, default=0)
    includes_assembly = validate.req_bool(data, "includes_assembly_instructions", default=False)

    _check_label_rules(doc_kind, placement_zone, pictogram_count, includes_assembly)

    document = store.base_record()
    document.update(
        {
            "product_id": product["id"],
            "doc_kind": doc_kind,
            "document_version": document_version,
            "text_digest": text_digest,
            "placement_zone": placement_zone,
            "pictogram_count": pictogram_count,
            "includes_assembly_instructions": includes_assembly,
            "status": "DRAFT",
            "approved_at": None,
        }
    )
    db.product_documents[document["id"]] = document
    store.register_new(document)
    return response.created(document, serialize.product_document)


@bp.post("/product-documents/<document_id>/approve")
@authorize("ComplianceOfficer")
def approve_product_document(document_id):
    document = lookup.product_document(document_id)

    if document["status"] != "DRAFT":
        fail("ERR_DOCUMENT_NOT_DRAFT", "status must be DRAFT to approve")

    _check_label_rules(
        document["doc_kind"],
        document["placement_zone"],
        document["pictogram_count"],
        document["includes_assembly_instructions"],
    )

    for other in lookup.documents_of_product(document["product_id"]):
        if other["id"] == document["id"]:
            continue
        if other["doc_kind"] == document["doc_kind"] and other["status"] == "APPROVED":
            other["status"] = "SUPERSEDED"
            mark_dirty(other)

    document["status"] = "APPROVED"
    document["approved_at"] = now()
    mark_dirty(document)
    return response.obj(document, serialize.product_document)
