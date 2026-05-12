"""Refund endpoints — draft, submit, approve/reject, execute, get."""

from flask import Blueprint, g

from db import DB, LOCK
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_ORDER_NOT_ELIGIBLE,
    ERR_REFUND_DOCUMENTS_INCOMPLETE,
    ERR_REFUND_NOT_ELIGIBLE,
    ERR_PAYMENT_REVERSED,
    forbidden,
    not_found,
)
from middleware import require_roles
from response import success_object
from services.calculations import compute_refund_amount
from services.common import check_occ, emit_audit, get_body, stamp_create, touch
from services.serializers import serialize_refund


bp = Blueprint("refunds", __name__)


REQUIRED_DOC_BY_REASON = {
    "RETURN": "SHIPMENT_RETURN_RECEIPT",
    "ORDER_CANCELLATION": "CANCELLATION_AGREEMENT",
    "ERRONEOUS_DECLARATION": "AMENDMENT_DECISION",
}


def _find_payment_notice_for(declaration_id: str):
    for pn in DB.payment_notices.values():
        if pn["declaration_id"] == declaration_id:
            return pn
    return None


def _can_view_refund(rf: dict) -> bool:
    role = g.role
    if role in ("CustomsOfficer", "FinanceOfficer", "Auditor"):
        return True
    dec = DB.declarations.get(rf["declaration_id"])
    if dec is None:
        return False
    if role == "Declarant":
        return dec["declarant_id"] == g.user_id
    return False


@bp.route("/refunds", methods=["POST"])
@require_roles("Declarant")
def create_refund():
    body = get_body()
    declaration_id = body.get("declaration_id")
    refund_reason = body.get("refund_reason")
    supporting_documents = body.get("supporting_documents")

    if not isinstance(declaration_id, str):
        raise APIError(ERR_INVALID_REQUEST, "declaration_id required", 400)
    if refund_reason not in ("RETURN", "ORDER_CANCELLATION", "ERRONEOUS_DECLARATION"):
        raise APIError(ERR_INVALID_REQUEST, "Invalid refund_reason", 400)
    if not isinstance(supporting_documents, list):
        raise APIError(ERR_INVALID_REQUEST, "supporting_documents must be array", 400)

    with LOCK:
        dec = DB.declarations.get(declaration_id)
        if dec is None:
            raise not_found("Declaration not found")
        if dec["declarant_id"] != g.user_id:
            raise forbidden("Declarant does not own this declaration")
        rf = {
            "declaration_id": declaration_id,
            "refund_reason": refund_reason,
            "supporting_documents": list(supporting_documents),
            "refundable_amount_cny_minor": None,
            "executed_amount_cny_minor": 0,
            "status": "DRAFT",
            "rejection_reason": None,
        }
        stamp_create(rf)
        DB.refunds[rf["id"]] = rf
        return success_object(serialize_refund(rf), status=201)


@bp.route("/refunds/<refund_id>/submit", methods=["POST"])
@require_roles("Declarant")
def submit_refund(refund_id):
    body = get_body()
    with LOCK:
        rf = DB.refunds.get(refund_id)
        if rf is None:
            raise not_found("Refund not found")
        dec = DB.declarations.get(rf["declaration_id"])
        if dec is None:
            raise not_found("Declaration not found")
        if dec["declarant_id"] != g.user_id:
            raise forbidden("Declarant does not own this refund")

        if rf["status"] != "DRAFT":
            raise APIError(ERR_INVALID_STATE_TRANSITION,
                           "Submit only from DRAFT", 409)
        if dec["status"] not in ("RELEASED", "AMENDED"):
            raise APIError(ERR_INVALID_STATE_TRANSITION,
                           "Declaration must be RELEASED or AMENDED", 409)
        pn = _find_payment_notice_for(dec["id"])
        if pn is None:
            raise APIError(ERR_INVALID_STATE_TRANSITION,
                           "No PaymentNotice for declaration", 409)
        if pn["status"] == "REVERSED":
            raise APIError(ERR_PAYMENT_REVERSED, "Payment is reversed", 409)
        if pn["status"] != "PAID":
            raise APIError(ERR_INVALID_STATE_TRANSITION,
                           "PaymentNotice must be PAID", 409)

        order = DB.orders.get(dec["order_id"])
        if order is None:
            raise not_found("Order not found")

        # Cross-entity guard
        if rf["refund_reason"] == "RETURN" and order["status"] != "RETURNED":
            raise APIError(ERR_ORDER_NOT_ELIGIBLE,
                           "Return refund requires Order in RETURNED", 409)
        if rf["refund_reason"] == "ORDER_CANCELLATION" and order["status"] != "CANCELLED":
            raise APIError(ERR_ORDER_NOT_ELIGIBLE,
                           "Order cancellation refund requires Order in CANCELLED", 409)

        # Document completeness
        required_doc = REQUIRED_DOC_BY_REASON.get(rf["refund_reason"])
        if required_doc:
            provided_types = []
            for d in rf.get("supporting_documents") or []:
                if isinstance(d, dict) and "doc_type" in d:
                    provided_types.append(d["doc_type"])
            if required_doc not in provided_types:
                raise APIError(ERR_REFUND_DOCUMENTS_INCOMPLETE,
                               f"Missing required document type: {required_doc}", 422)

        # Erroneous-declaration fiscal check
        if rf["refund_reason"] == "ERRONEOUS_DECLARATION":
            current_total = int(dec.get("total_tax_cny_minor") or 0)
            paid_amount = int(pn["amount_cny_minor"])
            if current_total >= paid_amount:
                raise APIError(ERR_REFUND_NOT_ELIGIBLE,
                               "Amended tax is not strictly less than paid tax", 409)

        # At-most-one-EXECUTED-refund-per-declaration check
        for other in DB.refunds.values():
            if other["id"] == rf["id"]:
                continue
            if other["declaration_id"] == dec["id"] and other["status"] == "EXECUTED":
                raise APIError(ERR_INVALID_STATE_TRANSITION,
                               "Another EXECUTED refund already exists", 409)

        check_occ(rf, body)
        amount = compute_refund_amount(rf["refund_reason"], pn, dec)
        rf["refundable_amount_cny_minor"] = int(amount)
        rf["status"] = "SUBMITTED"
        touch(rf)
        emit_audit("REFUND", rf["id"], "REFUND_DECISION",
                   before_value={"status": "DRAFT"},
                   after_value={"status": "SUBMITTED",
                                "refundable_amount_cny_minor": int(amount),
                                "decision": "submitted"})
        return success_object(serialize_refund(rf), status=200)


@bp.route("/refunds/<refund_id>/approve", methods=["POST"])
@require_roles("CustomsOfficer")
def approve_refund(refund_id):
    body = get_body()
    with LOCK:
        rf = DB.refunds.get(refund_id)
        if rf is None:
            raise not_found("Refund not found")
        if rf["status"] != "SUBMITTED":
            raise APIError(ERR_INVALID_STATE_TRANSITION,
                           "Approve only from SUBMITTED", 409)
        pn = _find_payment_notice_for(rf["declaration_id"])
        if pn is not None and pn["status"] == "REVERSED":
            raise APIError(ERR_PAYMENT_REVERSED, "Payment reversed", 409)
        check_occ(rf, body)
        rf["status"] = "APPROVED"
        touch(rf)
        emit_audit("REFUND", rf["id"], "REFUND_DECISION",
                   before_value={"status": "SUBMITTED"},
                   after_value={"status": "APPROVED", "decision": "approved"})
        return success_object(serialize_refund(rf), status=200)


@bp.route("/refunds/<refund_id>/reject", methods=["POST"])
@require_roles("CustomsOfficer")
def reject_refund(refund_id):
    body = get_body()
    rejection_reason = body.get("rejection_reason")
    if not isinstance(rejection_reason, str) or rejection_reason.strip() == "":
        raise APIError(ERR_INVALID_REQUEST, "rejection_reason required", 400)
    with LOCK:
        rf = DB.refunds.get(refund_id)
        if rf is None:
            raise not_found("Refund not found")
        if rf["status"] != "SUBMITTED":
            raise APIError(ERR_INVALID_STATE_TRANSITION,
                           "Reject only from SUBMITTED", 409)
        check_occ(rf, body)
        rf["status"] = "REJECTED"
        rf["rejection_reason"] = rejection_reason
        touch(rf)
        emit_audit("REFUND", rf["id"], "REFUND_DECISION",
                   before_value={"status": "SUBMITTED"},
                   after_value={"status": "REJECTED",
                                "rejection_reason": rejection_reason,
                                "decision": "rejected"})
        return success_object(serialize_refund(rf), status=200)


@bp.route("/refunds/<refund_id>/execute", methods=["POST"])
@require_roles("FinanceOfficer")
def execute_refund(refund_id):
    body = get_body()
    with LOCK:
        rf = DB.refunds.get(refund_id)
        if rf is None:
            raise not_found("Refund not found")
        if rf["status"] != "APPROVED":
            raise APIError(ERR_INVALID_STATE_TRANSITION,
                           "Execute only from APPROVED", 409)
        check_occ(rf, body)
        rf["executed_amount_cny_minor"] = int(rf.get("refundable_amount_cny_minor") or 0)
        rf["status"] = "EXECUTED"
        touch(rf)
        emit_audit("REFUND", rf["id"], "REFUND_DECISION",
                   before_value={"status": "APPROVED"},
                   after_value={"status": "EXECUTED",
                                "executed_amount_cny_minor": rf["executed_amount_cny_minor"],
                                "decision": "executed"})
        emit_audit("REFUND", rf["id"], "EXTERNAL_SYNC",
                   before_value={},
                   after_value={"external_system": "ERP_ORDER_UPDATE"})
        return success_object(serialize_refund(rf), status=200)


@bp.route("/refunds/<refund_id>", methods=["GET"])
@require_roles("Declarant", "CustomsOfficer", "FinanceOfficer", "Auditor")
def get_refund(refund_id):
    rf = DB.refunds.get(refund_id)
    if rf is None:
        raise not_found("Refund not found")
    if not _can_view_refund(rf):
        raise forbidden("Cannot view this refund")
    return success_object(serialize_refund(rf), status=200)
