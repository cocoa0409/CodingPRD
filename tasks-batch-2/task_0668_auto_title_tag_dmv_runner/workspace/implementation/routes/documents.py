"""DocumentItem endpoints (PRD §3.2; scaffold §1.5)."""

from flask import Blueprint

import errors
import repo
from db import db
from helpers import get_json_body, require_str, require_enum
from middleware import require_roles
from response import success
from serializers import document_item_out

bp = Blueprint("documents", __name__)


@bp.route("/dmv/documents", methods=["POST"])
@require_roles("IntakeClerk")
def create_document():
    body = get_json_body()
    transaction_id = require_str(body, "transaction_id")
    checklist_code = require_enum(body, "checklist_code", {
        "TITLE_CERT", "BILL_OF_SALE", "ODOMETER", "ID_PROOF", "INSURANCE",
        "LIEN_RELEASE", "LIEN_INSTRUMENT", "POWER_OF_ATTORNEY",
    })
    file_ref = require_str(body, "file_ref")

    txn = db.transactions.get(transaction_id)
    if txn is None:
        raise errors.not_found("transaction not found")

    rec = repo.make_document_item(transaction_id, checklist_code, file_ref)
    return success(document_item_out(rec), 201)


@bp.route("/dmv/documents/<did>", methods=["GET"])
@require_roles("PlatformAdmin", "FeeAnalyst", "IntakeClerk", "AccountHolder")
def get_document(did):
    from flask import g
    d = db.document_items.get(did)
    if d is None:
        raise errors.not_found("document not found")
    if g.user_role == "AccountHolder":
        txn = db.transactions.get(d["transaction_id"])
        if txn is None or txn["account_id"] != g.user_id:
            raise errors.not_resource_owner("AccountHolder may only read own documents")
    return success(document_item_out(d), 200)


@bp.route("/dmv/documents/<did>/verify", methods=["POST"])
@require_roles("IntakeClerk")
def verify_document(did):
    body = get_json_body()
    decision = require_enum(body, "decision", {"VERIFIED", "REJECTED", "RESET"})

    d = db.document_items.get(did)
    if d is None:
        raise errors.not_found("document not found")

    txn = db.transactions.get(d["transaction_id"])
    if txn is None:
        raise errors.not_found("owning transaction not found")

    # All document decisions permitted only while lifecycle in {DRAFT,QUOTED,REJECTED}.
    if txn["lifecycle_status"] not in ("DRAFT", "QUOTED", "REJECTED"):
        raise errors.invalid_state(
            "document decisions allowed only while transaction is DRAFT/QUOTED/REJECTED"
        )

    current = d["doc_status"]
    # State-machine transitions:
    #   VERIFIED: PENDING -> VERIFIED
    #   REJECTED: PENDING -> REJECTED
    #   RESET:    REJECTED -> PENDING
    if decision == "VERIFIED":
        if current != "PENDING":
            raise errors.invalid_state("document must be PENDING to verify")
        d["doc_status"] = "VERIFIED"
    elif decision == "REJECTED":
        if current != "PENDING":
            raise errors.invalid_state("document must be PENDING to reject")
        d["doc_status"] = "REJECTED"
    else:  # RESET
        if current != "REJECTED":
            raise errors.invalid_state("document must be REJECTED to reset")
        d["doc_status"] = "PENDING"

    repo.bump(d)
    return success(document_item_out(d), 200)
