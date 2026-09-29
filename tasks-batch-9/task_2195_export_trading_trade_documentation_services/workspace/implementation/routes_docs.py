"""Trade documents, the invoice totalling chain and the void cascade."""
from decimal import Decimal

import calc
import ledgers
import valid
from authz import apply_page, authenticate, pagination
from core import ApiError, dq, ok, ok_list
from db import insert, ordered, require, serialize, serialize_all, store, touch
from routes_orders import guard_restricted
from routes_reviews import new_finding

from flask import Blueprint, request

bp = Blueprint("docs", __name__)

D = Decimal
DOC_TYPES = ("COMMERCIAL_INVOICE", "PACKING_LIST", "CERTIFICATE_OF_ORIGIN",
             "BILL_OF_LADING", "INSURANCE_CERTIFICATE", "INSPECTION_CERTIFICATE")
VALUED_TYPES = ("COMMERCIAL_INVOICE", "INSURANCE_CERTIFICATE")
DOC_READ = ("ExportOpsCoordinator", "DocumentaryCreditReviewer",
            "FinanceCollectionsOfficer", "TradeComplianceOfficer", "PlatformAdmin")
LINK_READ = ("DocumentaryCreditReviewer", "ExportOpsCoordinator",
             "FinanceCollectionsOfficer", "PlatformAdmin")


def document_state_invalid(message="the document state does not permit this"):
    raise ApiError("ERR_DOCUMENT_STATE_INVALID", 409, message)


def links_of_document(document_id):
    return [l for l in ordered(store.links) if l["trade_document_id"] == document_id]


def build_document(order, doc_type, user_id, revision=1, supersedes=None,
                   status="DRAFT", on_board_date=None):
    """Generates a document row with the five snapshotted figures."""
    lines = calc.order_lines(order["id"])
    gross = D("0.000")
    for line in lines:
        if line["quantity"] > 0:
            gross += line["gross_weight_kg"]
    packages = sum(line["package_count"] for line in lines)
    if doc_type in VALUED_TYPES:
        declared, invoice_currency, _shares = calc.invoice_chain(order, persist=True)
    else:
        declared, invoice_currency = D("0.00"), D("0.00")
    row = {
        "export_order_id": order["id"],
        "supersedes_document_id": supersedes,
        "generated_by_user_id": user_id,
        "doc_type": doc_type,
        "revision": revision,
        "status": status,
        "pinned_order_version": order["version"],
        "total_gross_weight_kg": dq(gross, 3),
        "total_package_count": packages,
        "origin_country_code": order["origin_country_code"],
        "declared_total_usd": declared,
        "declared_total_invoice_currency": invoice_currency,
        "on_board_date": on_board_date if doc_type == "BILL_OF_LADING" else None,
        "void_reason": None,
    }
    return insert(store.documents, row)


@bp.post("/trade-documents")
def generate_document():
    caller = authenticate(("ExportOpsCoordinator",))
    body = valid.body()
    order = valid.fk(body, "export_order_id", store.orders, "ERR_ORDER_NOT_FOUND")
    doc_type = valid.enum(body, "doc_type", DOC_TYPES)
    guard_restricted(store.buyers[order["buyer_id"]])
    row = build_document(order, doc_type, caller.user_id)
    return ok(serialize(row), 201)


@bp.get("/trade-documents")
def list_documents():
    authenticate(DOC_READ)
    limit, offset = pagination()
    rows = ordered(store.documents)
    for field in ("export_order_id", "supersedes_document_id", "doc_type", "status"):
        value = request.args.get(field)
        if value:
            rows = [r for r in rows if r[field] == value]
    page, total = apply_page(rows, limit, offset)
    return ok_list(serialize_all(page), limit, offset, total)


@bp.get("/trade-documents/<document_id>")
def read_document(document_id):
    authenticate(DOC_READ)
    row = require(store.documents, document_id, "ERR_DOCUMENT_NOT_FOUND")
    return ok(serialize(row))


@bp.post("/trade-documents/<document_id>/issue")
def issue_document(document_id):
    authenticate(("ExportOpsCoordinator",))
    document = require(store.documents, document_id, "ERR_DOCUMENT_NOT_FOUND")
    order = store.orders[document["export_order_id"]]

    if document["status"] != "DRAFT":
        document_state_invalid("only a DRAFT document may be issued")
    if order["fulfillment_status"] in ("COMPLIANCE_BLOCKED", "CANCELLED"):
        ledgers.order_state_invalid()
    guard_restricted(store.buyers[order["buyer_id"]])
    for other in store.documents.values():
        if other["export_order_id"] == order["id"] \
                and other["doc_type"] == document["doc_type"] \
                and other["status"] == "ISSUED":
            raise ApiError("ERR_DUPLICATE_ISSUED_DOCUMENT", 409,
                           "an issued document of this type already exists")
    if document["pinned_order_version"] != order["version"]:
        raise ApiError("ERR_DOCUMENT_STALE_SOURCE", 409,
                       "the pinned order version is stale")
    if document["doc_type"] == "CERTIFICATE_OF_ORIGIN" \
            and document["origin_country_code"] != order["origin_country_code"]:
        raise ApiError("ERR_DOCUMENT_STALE_SOURCE", 409,
                       "the snapshotted origin country no longer matches the order")

    document["status"] = "ISSUED"
    touch(document)
    if document["doc_type"] == "COMMERCIAL_INVOICE":
        ledgers.recompute_outstanding_receivable(order)
    touch(order)
    return ok(serialize(document))


@bp.post("/trade-documents/<document_id>/regenerate")
def regenerate_document(document_id):
    caller = authenticate(("ExportOpsCoordinator",))
    document = require(store.documents, document_id, "ERR_DOCUMENT_NOT_FOUND")
    body = valid.body()
    valid.string(body, "reason", max_len=1000)
    order = store.orders[document["export_order_id"]]

    if document["status"] not in ("DRAFT", "ISSUED"):
        document_state_invalid("only a DRAFT or ISSUED document may be regenerated")
    if order["fulfillment_status"] == "CANCELLED":
        ledgers.order_state_invalid()
    active = [l for l in links_of_document(document["id"])
              if l["link_status"] == "ACTIVE"]
    if document["status"] == "ISSUED":
        for link in active:
            presentation = store.presentations.get(link["document_presentation_id"])
            if presentation is not None and presentation["status"] == "HONOURED":
                document_state_invalid(
                    "the document has been paid against and cannot be revised")

    document["status"] = "SUPERSEDED"
    touch(document)
    if document["doc_type"] == "COMMERCIAL_INVOICE":
        ledgers.recompute_outstanding_receivable(order)
    for link in active:
        link["link_status"] = "REPLACED"
        touch(link)
    row = build_document(order, document["doc_type"], caller.user_id,
                         revision=document["revision"] + 1,
                         supersedes=document["id"],
                         on_board_date=document["on_board_date"])
    return ok(serialize(row), 201)


@bp.post("/trade-documents/<document_id>/void")
def void_document(document_id):
    authenticate(("ExportOpsCoordinator",))
    document = require(store.documents, document_id, "ERR_DOCUMENT_NOT_FOUND")
    body = valid.body()
    reason = valid.string(body, "void_reason", max_len=1000)
    order = store.orders[document["export_order_id"]]

    if document["status"] not in ("DRAFT", "ISSUED"):
        document_state_invalid("only a DRAFT or ISSUED document may be voided")
    links = links_of_document(document["id"])
    if document["status"] == "DRAFT":
        if links:
            document_state_invalid("a DRAFT document with links may not be voided")
        document["void_reason"] = reason
        document["status"] = "VOIDED"
        touch(document)
        return ok(serialize(document))

    active = [l for l in links if l["link_status"] == "ACTIVE"]
    for link in active:
        presentation = store.presentations.get(link["document_presentation_id"])
        if presentation is not None and presentation["status"] == "HONOURED":
            document_state_invalid(
                "an active link belongs to an honoured presentation")

    document["void_reason"] = reason
    document["status"] = "VOIDED"
    touch(document)
    if document["doc_type"] == "COMMERCIAL_INVOICE":
        ledgers.recompute_outstanding_receivable(order)

    touched_presentations = []
    for link in active:
        link["link_status"] = "INVALIDATED"
        touch(link)
        presentation = store.presentations.get(link["document_presentation_id"])
        if presentation is None or presentation["status"] != "PRESENTED":
            continue
        if presentation["id"] in [p["id"] for p in touched_presentations]:
            continue
        touched_presentations.append(presentation)

    for presentation in touched_presentations:
        presentation["status"] = "DISCREPANT"
        new_finding(letter_of_credit_id=presentation["letter_of_credit_id"],
                    document_presentation_id=presentation["id"], source="DOCUMENT",
                    code="DOC_VOIDED", severity="CRITICAL", clause_ref="DOCUMENTS",
                    detail="the tendered document was voided", cure_status="OPEN",
                    raised_in_round=presentation["presentation_round"])
        presentation["open_finding_count"] = calc.open_finding_count(presentation["id"])
        touch(presentation)
        target = store.orders[presentation["export_order_id"]]
        if target["settlement_status"] == "DOCS_PRESENTED" \
                and not ledgers.has_complying_presentation(target["id"]):
            target["settlement_status"] = "LC_ACCEPTED"
            touch(target)
    return ok(serialize(document))


@bp.get("/presentation-document-links")
def list_links():
    authenticate(LINK_READ)
    limit, offset = pagination()
    rows = ordered(store.links)
    for field in ("document_presentation_id", "trade_document_id", "link_status"):
        value = request.args.get(field)
        if value:
            rows = [r for r in rows if r[field] == value]
    page, total = apply_page(rows, limit, offset)
    return ok_list(serialize_all(page), limit, offset, total)


@bp.get("/presentation-document-links/<link_id>")
def read_link(link_id):
    authenticate(LINK_READ)
    row = require(store.links, link_id, "ERR_DOCUMENT_NOT_FOUND")
    return ok(serialize(row))
