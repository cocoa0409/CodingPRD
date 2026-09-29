"""SampleShipment and RegulatoryDocument endpoints (PRD §3.8)."""

from flask import Blueprint, request

import constants as K
import serializers as S
from db import base_entity, db, now_logical, touch
from errors import fail
from middleware import ALL_ROLES, auth
from response import created, ok
from routes.common import list_response, need
from services import cascade, graph, ledger
from validate import (as_int, as_pattern, as_str, body_json, optional, require)

bp = Blueprint("shipments", __name__)


def _shipment(shipment_id):
    return need(db.shipments, shipment_id, "ERR_SHIPMENT_NOT_FOUND", "shipment")


@bp.post("/shipments")
def create_shipment():
    auth(["AccountManager"])
    body = body_json()
    sample_lot_id = as_str(require(body, "sample_lot_id"), "sample_lot_id")
    destination_country = as_pattern(require(body, "destination_country"),
                                     "destination_country", r"^[A-Z]{2}$")
    shipped_g = as_int(require(body, "shipped_g"), "shipped_g", minimum=1)
    carrier = optional(body, "carrier")
    if carrier is not None:
        carrier = as_str(carrier, "carrier")

    lot = need(db.lots, sample_lot_id, "ERR_LOT_NOT_FOUND", "sample lot")
    if lot["disposition_status"] != "RELEASED":
        fail("ERR_LOT_NOT_RELEASED",
             "the lot's disposition is %s" % lot["disposition_status"])
    if shipped_g > ledger.available_g(lot):
        fail("ERR_INSUFFICIENT_SAMPLE_MASS",
             "the lot only offers %d unallocated gram(s)"
             % ledger.available_g(lot))

    brief = graph.brief_of_lot(lot)
    shipment = base_entity()
    shipment.update({
        "sample_lot_id": lot["id"],
        "brief_id": brief["id"] if brief is not None else None,
        "destination_country": destination_country,
        "shipped_g": shipped_g,
        "carrier": carrier,
        "status": "DRAFT",
        "required_document_types": [],
        "packet_valid_until": None,
        "tracking_reference": None,
        "dispatched_at": None,
        "block_reason": None,
        "cancellation_reason": None,
    })
    db.shipments[shipment["id"]] = shipment
    ledger.reconcile_lot(lot)
    return created(S.shipment_out(shipment))


@bp.get("/shipments")
def list_shipments():
    auth(ALL_ROLES)
    sample_lot_id = request.args.get("sample_lot_id")
    brief_id = request.args.get("brief_id")
    status = request.args.get("status")
    destination_country = request.args.get("destination_country")
    rows = []
    for shipment in db.shipments.values():
        if sample_lot_id is not None and shipment["sample_lot_id"] != sample_lot_id:
            continue
        if brief_id is not None and shipment["brief_id"] != brief_id:
            continue
        if status is not None and shipment["status"] != status:
            continue
        if destination_country is not None and \
                shipment["destination_country"] != destination_country:
            continue
        rows.append(shipment)
    return list_response(rows, S.shipment_out)


@bp.get("/shipments/<shipment_id>")
def get_shipment(shipment_id):
    auth(ALL_ROLES)
    return ok(S.shipment_out(_shipment(shipment_id)))


@bp.post("/shipments/<shipment_id>/assemble-packet")
def assemble_packet(shipment_id):
    auth(["RegulatoryAffairs"])
    body_json()
    shipment = _shipment(shipment_id)
    if shipment["status"] not in ("DRAFT", "BLOCKED"):
        fail("ERR_SHIPMENT_STATE_INVALID",
             "cannot assemble a packet for a shipment in status %s"
             % shipment["status"])

    lot = db.lots.get(shipment["sample_lot_id"])
    formula = db.formulas.get(lot["formula_id"]) if lot is not None else None
    brief = db.briefs.get(shipment["brief_id"])
    cascade.assemble_packet(shipment, formula, brief)

    shipment["status"] = "PACKET_ASSEMBLED"
    shipment["block_reason"] = None
    touch(shipment)
    return ok(S.shipment_out(shipment))


@bp.post("/shipments/<shipment_id>/dispatch")
def dispatch_shipment(shipment_id):
    auth(["RegulatoryAffairs"])
    body = body_json()
    tracking_reference = as_str(require(body, "tracking_reference"),
                                "tracking_reference")
    shipment = _shipment(shipment_id)
    if shipment["status"] != "PACKET_ASSEMBLED":
        fail("ERR_SHIPMENT_STATE_INVALID",
             "cannot dispatch a shipment in status %s" % shipment["status"])

    documents = ledger.documents_of_shipment(shipment["id"])

    # priority 58 - no revoked certificate may sit behind the packet
    for document in documents:
        record = db.records.get(document["substantiation_id"]) \
            if document["substantiation_id"] else None
        if record is not None and record["status"] != "VERIFIED":
            fail("ERR_SUBSTANTIATION_REVOKED",
                 "the %s document points at a %s certificate"
                 % (document["doc_type"], record["status"]))

    # priority 68 - the packet must not have expired
    if shipment["packet_valid_until"] is not None and \
            shipment["packet_valid_until"] < now_logical():
        fail("ERR_PACKET_EXPIRED", "the documentation packet has expired")

    # priority 73 - every document must still be pinned to the live version
    for document in documents:
        if document["status"] != "PINNED":
            fail("ERR_PINNED_DOC_STALE",
                 "the %s document is %s" % (document["doc_type"],
                                            document["status"]))
        record = db.records.get(document["substantiation_id"]) \
            if document["substantiation_id"] else None
        if record is not None and \
                document["pinned_substantiation_version"] != record["version"]:
            fail("ERR_PINNED_DOC_STALE",
                 "the %s document pins an outdated certificate version"
                 % document["doc_type"])

    shipment["status"] = "DISPATCHED"
    shipment["tracking_reference"] = tracking_reference
    shipment["dispatched_at"] = now_logical()
    touch(shipment)
    return ok(S.shipment_out(shipment))


@bp.post("/shipments/<shipment_id>/cancel")
def cancel_shipment(shipment_id):
    auth(["AccountManager"])
    body = body_json()
    reason = as_str(require(body, "cancellation_reason"), "cancellation_reason")
    shipment = _shipment(shipment_id)
    if shipment["status"] not in ("DRAFT", "PACKET_ASSEMBLED", "BLOCKED"):
        fail("ERR_SHIPMENT_STATE_INVALID",
             "cannot cancel a shipment in status %s" % shipment["status"])
    cascade.cancel_shipment(shipment, reason)
    return ok(S.shipment_out(shipment))


# --- RegulatoryDocument -----------------------------------------------------

@bp.get("/regulatory-documents")
def list_documents():
    auth(ALL_ROLES)
    shipment_id = request.args.get("shipment_id")
    substantiation_id = request.args.get("substantiation_id")
    doc_type = request.args.get("doc_type")
    status = request.args.get("status")
    rows = []
    for document in db.documents.values():
        if shipment_id is not None and document["shipment_id"] != shipment_id:
            continue
        if substantiation_id is not None and \
                document["substantiation_id"] != substantiation_id:
            continue
        if doc_type is not None and document["doc_type"] != doc_type:
            continue
        if status is not None and document["status"] != status:
            continue
        rows.append(document)
    return list_response(rows, S.document_out)


@bp.get("/regulatory-documents/<document_id>")
def get_document(document_id):
    auth(ALL_ROLES)
    document = need(db.documents, document_id, "ERR_DOCUMENT_NOT_FOUND",
                    "regulatory document")
    return ok(S.document_out(document))
