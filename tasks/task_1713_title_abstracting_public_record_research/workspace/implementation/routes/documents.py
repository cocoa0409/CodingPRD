"""RecordDocument endpoints: recording instruments, chain-of-title linkage,
verify / flag / void dispositions."""

import db
from errors import (
    ApiError,
    ERR_ORDER_NOT_FOUND,
    ERR_ASSIGNMENT_NOT_FOUND,
    ERR_DOCUMENT_NOT_FOUND,
    ERR_FORBIDDEN,
    ERR_INVALID_STATE,
    ERR_ORDER_TERMINAL,
    ERR_DUPLICATE_INSTRUMENT,
    ERR_CHAIN_LINK_INVALID,
)
from middleware import authenticate, ALL_ROLES
from response import success_obj, success_list
from routes import make_blueprint
from services import (
    TERMINAL_ORDER_STATES,
    document_view,
    documents_of_order,
    compute_chain_break,
)
from util import (
    body_json,
    check_shape,
    pagination_params,
    paginate,
    apply_filters,
    require_fk,
)

bp = make_blueprint("documents")

_CREATE_SPEC = {
    "order_id": {"type": "string", "required": True},
    "assignment_id": {"type": "string", "required": True},
    "instrument_type": {
        "type": "enum",
        "required": True,
        "values": {"DEED", "MORTGAGE", "LIEN", "JUDGMENT", "TAX_LIEN", "EASEMENT", "RESTRICTION"},
    },
    "grantor_name": {"type": "string", "required": True},
    "grantee_name": {"type": "string", "required": True},
    "instrument_number": {"type": "string", "required": True},
    "recording_date": {"type": "date", "required": True},
    "prior_document_id": {"type": "string"},
    "exception_applies": {"type": "boolean"},
}

_FLAG_SPEC = {
    "reason": {"type": "string", "required": True},
}

_VOID_SPEC = {
    "reason": {"type": "string"},
}

CRITICAL_FLAG_TYPES = ("LIEN", "JUDGMENT", "TAX_LIEN")


def _get_document_or_404(did):
    return require_fk("documents", did, ERR_DOCUMENT_NOT_FOUND, "document")


def _require_order_not_terminal(order):
    if order["status"] in TERMINAL_ORDER_STATES:
        raise ApiError(ERR_ORDER_TERMINAL, 409, "parent order is terminal")


def _require_own_assignment(uid, document):
    assignment = db.get("assignments", document["assignment_id"])
    if assignment is None or assignment["abstracter_ref"] != uid:
        raise ApiError(ERR_FORBIDDEN, 403, "only the assigned abstracter may act on this document")
    return assignment


@bp.post("/record-documents")
def create_document():
    uid, role = authenticate(["Abstracter"])
    body = body_json()
    check_shape(body, _CREATE_SPEC)
    # Existence, left to right: order, then assignment, then prior document.
    order = require_fk("orders", body["order_id"], ERR_ORDER_NOT_FOUND, "order")
    assignment = require_fk("assignments", body["assignment_id"], ERR_ASSIGNMENT_NOT_FOUND, "assignment")
    if assignment["abstracter_ref"] != uid:
        raise ApiError(ERR_FORBIDDEN, 403, "only the assigned abstracter may record documents")
    prior = None
    if body.get("prior_document_id") is not None:
        prior = require_fk("documents", body["prior_document_id"], ERR_DOCUMENT_NOT_FOUND, "prior document")
    _require_order_not_terminal(order)

    # instrument_number unique within the order among non-VOID documents.
    for d in documents_of_order(order["id"]):
        if d["status"] != "VOID" and d["instrument_number"] == body["instrument_number"]:
            raise ApiError(ERR_DUPLICATE_INSTRUMENT, 409, "instrument_number already recorded for this order")

    # Chain-link integrity: prior must be a DEED of the same order, not VOID.
    if prior is not None:
        if prior["order_id"] != order["id"] or prior["instrument_type"] != "DEED" or prior["status"] == "VOID":
            raise ApiError(ERR_CHAIN_LINK_INVALID, 422, "prior_document_id must reference a non-VOID DEED of the same order")

    document = db.new_entity("documents", {
        "order_id": body["order_id"],
        "assignment_id": body["assignment_id"],
        "instrument_type": body["instrument_type"],
        "grantor_name": body["grantor_name"],
        "grantee_name": body["grantee_name"],
        "instrument_number": body["instrument_number"],
        "recording_date": body["recording_date"],
        "prior_document_id": body.get("prior_document_id"),
        "chain_break_flag": compute_chain_break(body["instrument_type"], body["grantor_name"], prior),
        "exception_applies": body.get("exception_applies") if body.get("exception_applies") is not None else False,
        "status": "REPORTED",
    })
    return success_obj(document_view(document), 201)


@bp.get("/record-documents/<did>")
def get_document(did):
    authenticate(ALL_ROLES)
    return success_obj(document_view(_get_document_or_404(did)), 200)


@bp.get("/record-documents")
def list_documents():
    authenticate(ALL_ROLES)
    limit, offset = pagination_params()
    items = apply_filters(
        db.all_of("documents"),
        ["order_id", "assignment_id", "prior_document_id", "instrument_type", "status"],
    )
    page, total, has_more = paginate(items, limit, offset)
    return success_list([document_view(d) for d in page], limit, offset, total, has_more)


@bp.post("/record-documents/<did>/verify")
def verify_document(did):
    uid, role = authenticate(["Abstracter"])
    document = _get_document_or_404(did)
    assignment = _require_own_assignment(uid, document)
    _require_order_not_terminal(db.get("orders", document["order_id"]))
    if assignment["status"] != "IN_PROGRESS":
        raise ApiError(ERR_INVALID_STATE, 409, "assignment is not IN_PROGRESS")
    if document["status"] not in ("REPORTED", "FLAGGED_FOR_CURATIVE"):
        raise ApiError(ERR_INVALID_STATE, 409, "document cannot be verified from its current state")
    document["status"] = "VERIFIED"
    db.touch(document)
    return success_obj(document_view(document), 200)


@bp.post("/record-documents/<did>/flag")
def flag_document(did):
    uid, role = authenticate(["Abstracter"])
    body = body_json()
    check_shape(body, _FLAG_SPEC)
    document = _get_document_or_404(did)
    assignment = _require_own_assignment(uid, document)
    _require_order_not_terminal(db.get("orders", document["order_id"]))
    if assignment["status"] != "IN_PROGRESS":
        raise ApiError(ERR_INVALID_STATE, 409, "assignment is not IN_PROGRESS")
    if document["status"] != "REPORTED":
        raise ApiError(ERR_INVALID_STATE, 409, "only a REPORTED document can be flagged")
    document["status"] = "FLAGGED_FOR_CURATIVE"
    db.touch(document)
    # Cascade: the system raises a CurativeRequirement (raiser null).
    severity = "CRITICAL" if document["instrument_type"] in CRITICAL_FLAG_TYPES else "STANDARD"
    db.new_entity("curatives", {
        "order_id": document["order_id"],
        "record_document_id": document["id"],
        "raised_by_examiner_ref": None,
        "description": body["reason"],
        "severity": severity,
        "resolution_note": None,
        "status": "OPEN",
    })
    return success_obj(document_view(document), 200)


@bp.post("/record-documents/<did>/void")
def void_document(did):
    uid, role = authenticate(["Abstracter", "OperationsManager"])
    body = body_json()
    check_shape(body, _VOID_SPEC)
    document = _get_document_or_404(did)
    if role == "Abstracter":
        _require_own_assignment(uid, document)
    _require_order_not_terminal(db.get("orders", document["order_id"]))
    if document["status"] != "REPORTED":
        raise ApiError(ERR_INVALID_STATE, 409, "only a REPORTED document can be voided")
    document["status"] = "VOID"
    db.touch(document)
    return success_obj(document_view(document), 200)
