"""Subscription documents: upload, review queue, accept/reject (PRD 3.3)."""
from flask import Blueprint

import resolve
from db import db
from errors import raise_error
from middleware import SPONSOR, COMPLIANCE, INVESTOR, endpoint
from response import success_list, success_object
from serializers import ser_document
from services.domain import stamp_new_light, sorted_items
from util import CLOCK, fmt_dt
from validate import get_body, req_enum, req_str, pagination, apply_filters

bp = Blueprint("documents", __name__)
RS = {"strict_slashes": False}

DOC_TYPES = ("SUBSCRIPTION_AGREEMENT", "W9", "ACCREDITATION_LETTER",
             "ID_PROOF", "SUITABILITY_QUESTIONNAIRE")


def _visible_subscription_or_404(caller, sub):
    if caller.role == INVESTOR and sub["investor_id"] != caller.user_id:
        raise_error("ERR_SUBSCRIPTION_NOT_FOUND",
                    f"subscription not found: {sub['id']}")


@bp.route("/syndications/<syndicationId>/offerings/<offeringId>/subscriptions/<subscriptionId>/documents",
          methods=["POST"], **RS)
@endpoint(INVESTOR)
def upload_document(caller, syndicationId, offeringId, subscriptionId):
    sub = resolve.subscription(syndicationId, offeringId, subscriptionId)
    body = get_body()
    doc_type = req_enum(body, "doc_type", DOC_TYPES)
    file_uri = req_str(body, "file_uri")
    if caller.user_id != sub["investor_id"]:
        raise_error("ERR_INSUFFICIENT_PERMISSIONS",
                    "an investor may only upload documents to its own subscription")
    d = {
        "subscription_id": subscriptionId,
        "doc_type": doc_type,
        "file_uri": file_uri,
        "received_at": fmt_dt(CLOCK.now()),
        "review_status": "PENDING_REVIEW",
        "reviewed_by": None,
    }
    stamp_new_light(d)
    db["documents"][d["id"]] = d
    return success_object(ser_document(d), 201)


@bp.route("/syndications/<syndicationId>/offerings/<offeringId>/subscriptions/<subscriptionId>/documents",
          methods=["GET"], **RS)
@endpoint(SPONSOR, COMPLIANCE, INVESTOR)
def list_documents(caller, syndicationId, offeringId, subscriptionId):
    sub = resolve.subscription(syndicationId, offeringId, subscriptionId)
    _visible_subscription_or_404(caller, sub)
    limit, offset = pagination()
    items = [d for d in db["documents"].values() if d["subscription_id"] == subscriptionId]
    items = apply_filters(sorted_items(items),
                          {"doc_type": "doc_type", "review_status": "review_status"})
    page = items[offset:offset + limit]
    return success_list([ser_document(o) for o in page], len(items), limit, offset)


@bp.route("/syndications/<syndicationId>/offerings/<offeringId>/subscriptions/<subscriptionId>/documents/<documentId>",
          methods=["GET"], **RS)
@endpoint(SPONSOR, COMPLIANCE, INVESTOR)
def get_document(caller, syndicationId, offeringId, subscriptionId, documentId):
    sub = resolve.subscription(syndicationId, offeringId, subscriptionId)
    _visible_subscription_or_404(caller, sub)
    doc = db["documents"].get(documentId)
    if doc is None or doc["subscription_id"] != subscriptionId:
        raise_error("ERR_DOCUMENT_NOT_FOUND", f"document not found: {documentId}")
    return success_object(ser_document(doc))


def _review(caller, syndicationId, offeringId, subscriptionId, documentId, decision):
    doc = resolve.document(syndicationId, offeringId, subscriptionId, documentId)
    if doc["review_status"] != "PENDING_REVIEW":
        raise_error("ERR_INVALID_STATE",
                    f"cannot review a document in review_status {doc['review_status']}")
    doc["review_status"] = decision
    doc["reviewed_by"] = caller.user_id
    return success_object(ser_document(doc))


@bp.route("/syndications/<syndicationId>/offerings/<offeringId>/subscriptions/<subscriptionId>/documents/<documentId>/accept",
          methods=["POST"], **RS)
@endpoint(COMPLIANCE)
def accept_document(caller, syndicationId, offeringId, subscriptionId, documentId):
    return _review(caller, syndicationId, offeringId, subscriptionId, documentId, "ACCEPTED")


@bp.route("/syndications/<syndicationId>/offerings/<offeringId>/subscriptions/<subscriptionId>/documents/<documentId>/reject",
          methods=["POST"], **RS)
@endpoint(COMPLIANCE)
def reject_document(caller, syndicationId, offeringId, subscriptionId, documentId):
    return _review(caller, syndicationId, offeringId, subscriptionId, documentId, "REJECTED")
