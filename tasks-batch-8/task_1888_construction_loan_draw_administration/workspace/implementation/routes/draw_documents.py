from flask import Blueprint, g, request

import db
from auth import ALL_ROLES, require_borrower_ownership, require_role
from db import pub, touch
from errors import ApiError
from respond import success, success_list
from services import get_or_404
from util import (
    get_body,
    opt_str,
    paginate,
    req_date,
    req_enum,
    req_int,
    req_str,
    sort_created,
)

bp = Blueprint("draw_documents", __name__)

DOC_TYPES = [
    "LIEN_WAIVER_CONDITIONAL",
    "LIEN_WAIVER_UNCONDITIONAL",
    "INVOICE",
    "INSURANCE_CERTIFICATE",
]


@bp.post("/draw-documents")
def create_draw_document():
    require_role(g.role, {"Borrower"})
    body = get_body()
    draw_id = body.get("draw_id")
    if draw_id is not None and draw_id not in db.draws:
        raise ApiError("ERR_NOT_FOUND", "DrawRequest not found")
    draw = db.draws.get(draw_id) if isinstance(draw_id, str) else None
    if draw is not None:
        loan = db.loans[draw["loan_id"]]
        require_borrower_ownership(g.uid, loan)
        if loan["status"] != "OPEN":
            raise ApiError(
                "ERR_LOAN_NOT_OPEN", "Documents can only be added under an OPEN loan"
            )
        if draw["status"] not in ("DRAFT", "REVISION_REQUESTED"):
            raise ApiError(
                "ERR_INVALID_STATE",
                "Documents can only be added to a DRAFT or REVISION_REQUESTED draw",
            )
    doc_type = req_enum(body, "doc_type", DOC_TYPES)
    party_name = req_str(body, "party_name")
    amount = req_int(body, "amount_cents", min_value=1)
    doc_date = req_date(body, "doc_date")
    reference_number = opt_str(body, "reference_number")
    draw_id = req_str(body, "draw_id")

    rec = db.base_record()
    rec.update(
        {
            "draw_id": draw_id,
            "doc_type": doc_type,
            "party_name": party_name,
            "reference_number": reference_number,
            "amount_cents": amount,
            "doc_date": doc_date,
            "status": "SUBMITTED",
            "rejection_reason": None,
        }
    )
    db.draw_documents[rec["id"]] = rec
    return success(pub(rec), 201)


@bp.get("/draw-documents/<rid>")
def get_draw_document(rid):
    require_role(g.role, ALL_ROLES)
    return success(pub(get_or_404(db.draw_documents, rid, "DrawDocument")))


@bp.get("/draw-documents")
def list_draw_documents():
    require_role(g.role, ALL_ROLES)
    items = list(db.draw_documents.values())
    f_draw = request.args.get("draw_id")
    f_type = request.args.get("doc_type")
    f_status = request.args.get("status")
    if f_draw is not None:
        items = [d for d in items if d["draw_id"] == f_draw]
    if f_type is not None:
        items = [d for d in items if d["doc_type"] == f_type]
    if f_status is not None:
        items = [d for d in items if d["status"] == f_status]
    page, total, limit, offset = paginate(sort_created(items))
    return success_list([pub(r) for r in page], total, limit, offset)


@bp.post("/draw-documents/<rid>/review")
def review_draw_document(rid):
    require_role(g.role, {"DrawProcessor"})
    doc = get_or_404(db.draw_documents, rid, "DrawDocument")
    if doc["status"] != "SUBMITTED":
        raise ApiError(
            "ERR_INVALID_STATE", "Only a SUBMITTED document can be reviewed"
        )
    body = get_body()
    decision = req_enum(body, "decision", ["VERIFIED", "REJECTED"])
    if decision == "REJECTED":
        doc["rejection_reason"] = req_str(body, "reason")
    doc["status"] = decision
    touch(doc)
    return success(pub(doc))
