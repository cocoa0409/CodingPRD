"""Documents: request / submit / accept / reject."""
from flask import Blueprint, request

import errors as E
import middleware as mw
from db import store, mint, touch, pub, pub_list
from response import ok_object, ok_list

bp = Blueprint("documents", __name__)


def _reset_audit(file_rec):
    """Any Document status mutation after an audit invalidates it."""
    if file_rec is not None and file_rec["last_audit_status"] != "NONE":
        file_rec["last_audit_status"] = "NONE"
        touch(file_rec)


@bp.post("/tc/documents")
def create_document():
    uid, role = mw.auth()
    mw.require_roles(role, {"Coordinator"})
    data = mw.body()
    # priority 3: body FK existence
    file_rec = None
    if data.get("file_id") is not None:
        file_rec = mw.get_or_404("file", data["file_id"])
    # priority 4: ownership
    if file_rec is not None:
        mw.own_file(uid, file_rec)
    # priority 12: shape
    mw.validate_shape(data, [
        ("file_id", "string", True),
        ("doc_type", "enum", True, mw.DOC_TYPES),
    ])
    rec = mint({
        "file_id": data["file_id"],
        "doc_type": data["doc_type"],
        "status": "REQUESTED",
        "submitted_by_agent_id": None,
        "review_round": 1,
        "reject_reason": None,
    })
    store.documents[rec["id"]] = rec
    return ok_object(pub("document", rec), 201)


@bp.get("/tc/documents/<documentId>")
def get_document(documentId):
    mw.auth()
    rec = mw.get_or_404("document", documentId)
    return ok_object(pub("document", rec))


@bp.get("/tc/documents")
def list_documents():
    mw.auth()
    limit, offset = mw.page_params()
    recs = list(store.documents.values())
    recs = mw.filter_eq(recs, "file_id", request.args.get("file_id"))
    recs = mw.filter_eq(recs, "doc_type", request.args.get("doc_type"))
    recs = mw.filter_eq(recs, "status", request.args.get("status"))
    recs = mw.filter_eq(recs, "submitted_by_agent_id", request.args.get("submitted_by_agent_id"))
    page, total = mw.apply_page(recs, limit, offset)
    return ok_list(pub_list("document", page), limit, offset, total)


@bp.post("/tc/documents/<documentId>/submit")
def submit_document(documentId):
    uid, role = mw.auth()
    mw.require_roles(role, {"Agent"})
    rec = mw.get_or_404("document", documentId)
    file_rec = store.files.get(rec["file_id"])
    if file_rec is None or uid not in (file_rec.get("buyer_agent_id"), file_rec.get("seller_agent_id")):
        E.raise_err(E.ERR_AGENT_NOT_ON_FILE,
                    "Acting agent is neither buyer_agent_id nor seller_agent_id of the file")
    if rec["status"] not in ("REQUESTED", "REJECTED"):
        E.raise_err(E.ERR_DOCUMENT_INVALID_STATE,
                    "Only a REQUESTED or REJECTED document can be submitted")
    if rec["status"] == "REJECTED":
        rec["review_round"] += 1
    rec["status"] = "RECEIVED"
    rec["submitted_by_agent_id"] = uid
    touch(rec)
    _reset_audit(file_rec)
    return ok_object(pub("document", rec))


@bp.post("/tc/documents/<documentId>/accept")
def accept_document(documentId):
    uid, role = mw.auth()
    mw.require_roles(role, {"Coordinator"})
    rec = mw.get_or_404("document", documentId)
    file_rec = mw.own_file_chain(uid, rec, "document")
    if rec["status"] != "RECEIVED":
        E.raise_err(E.ERR_DOCUMENT_INVALID_STATE, "Only a RECEIVED document can be accepted")
    rec["status"] = "ACCEPTED"
    touch(rec)
    _reset_audit(file_rec)
    return ok_object(pub("document", rec))


@bp.post("/tc/documents/<documentId>/reject")
def reject_document(documentId):
    uid, role = mw.auth()
    mw.require_roles(role, {"Coordinator"})
    rec = mw.get_or_404("document", documentId)
    file_rec = mw.own_file_chain(uid, rec, "document")
    if rec["status"] != "RECEIVED":
        E.raise_err(E.ERR_DOCUMENT_INVALID_STATE, "Only a RECEIVED document can be rejected")
    data = mw.body()
    mw.validate_shape(data, [("reason", "string", True)])
    rec["status"] = "REJECTED"
    rec["reject_reason"] = data["reason"]
    touch(rec)
    _reset_audit(file_rec)
    return ok_object(pub("document", rec))
