"""Tax document endpoints."""

from datetime import timedelta

from flask import request

from .auth import require, require_owner
from .blueprint import bp
from .calc import DOC_VALIDITY_DAYS
from .envelope import ok_list, ok_obj
from .errors import ApiError, bad_request, invalid_state, not_found
from .serialize import ser_tax_document
from .store import STORE, new_entity, now, touch
from .util import body, opt_str, paged, pagination_params, req_enum, req_str, sort_created

DOC_KINDS = ("W9", "W8BEN")
READ_ROLES = ["DeskAdmin", "FinanceUser", "Contributor"]


def _kind_matches_residency(doc_kind, tax_residency):
    return (doc_kind == "W9" and tax_residency == "DOMESTIC_US") or (
        doc_kind == "W8BEN" and tax_residency == "FOREIGN"
    )


@bp.post("/freelance-desk/contributors/<cid>/tax-documents")
def create_tax_document(cid):
    uid, role = require(["Contributor"])
    c = STORE.contributors.get(cid)
    if c is None:
        not_found("Contributor")
    require_owner(uid, cid)
    b = body()
    doc_kind = req_enum(b, "doc_kind", DOC_KINDS)
    treaty_country = opt_str(b, "treaty_country")
    # Priority 9: kind <-> residency match; W8BEN requires treaty_country
    if not _kind_matches_residency(doc_kind, c["tax_residency"]):
        raise ApiError(
            "ERR_TAX_DOC_MISMATCH",
            422,
            "doc_kind must match contributor tax_residency (W9/DOMESTIC_US, W8BEN/FOREIGN)",
        )
    if doc_kind == "W8BEN" and not treaty_country:
        raise ApiError("ERR_TAX_DOC_MISMATCH", 422, "W8BEN requires treaty_country")
    # Priority 15: remaining field shape
    if doc_kind == "W9" and treaty_country is not None:
        bad_request("treaty_country must be null for W9")
    tin_last4 = req_str(b, "tin_last4")
    if len(tin_last4) != 4 or not tin_last4.isdigit():
        bad_request("tin_last4 must be exactly 4 digits")

    submitted = now()
    e = new_entity()
    e.update({
        "contributor_id": cid,
        "doc_kind": doc_kind,
        "treaty_country": treaty_country,
        "tin_last4": tin_last4,
        "submitted_at": submitted,
        "expires_at": submitted + timedelta(days=DOC_VALIDITY_DAYS),
        "status": "SUBMITTED",
    })
    STORE.tax_documents[e["id"]] = e
    return ok_obj(ser_tax_document(e), 201)


@bp.get("/freelance-desk/contributors/<cid>/tax-documents")
def list_tax_documents(cid):
    uid, role = require(READ_ROLES)
    if cid not in STORE.contributors:
        not_found("Contributor")
    if role == "Contributor":
        require_owner(uid, cid)
    items = [t for t in STORE.tax_documents.values() if t["contributor_id"] == cid]
    status = request.args.get("status")
    if status:
        items = [t for t in items if t["status"] == status]
    kind = request.args.get("doc_kind")
    if kind:
        items = [t for t in items if t["doc_kind"] == kind]
    items = sort_created(items)
    limit, offset = pagination_params()
    page, total = paged(items, limit, offset)
    return ok_list([ser_tax_document(t) for t in page], limit, offset, total)


@bp.get("/freelance-desk/tax-documents/<tid>")
def get_tax_document(tid):
    uid, role = require(READ_ROLES)
    t = STORE.tax_documents.get(tid)
    if t is None:
        not_found("TaxDocument")
    if role == "Contributor":
        require_owner(uid, t["contributor_id"])
    return ok_obj(ser_tax_document(t))


@bp.post("/freelance-desk/tax-documents/<tid>/verify")
def verify_tax_document(tid):
    require(["FinanceUser"])
    t = STORE.tax_documents.get(tid)
    if t is None:
        not_found("TaxDocument")
    if t["status"] != "SUBMITTED":
        invalid_state("Only a SUBMITTED tax document can be verified or rejected")
    b = body()
    decision = req_enum(b, "decision", ("VERIFY", "REJECT"))
    if decision == "VERIFY":
        c = STORE.contributors.get(t["contributor_id"])
        if c is None or not _kind_matches_residency(t["doc_kind"], c["tax_residency"]):
            raise ApiError(
                "ERR_TAX_DOC_MISMATCH",
                422,
                "doc_kind does not match contributor tax_residency",
            )
        t["status"] = "VERIFIED"
    else:
        t["status"] = "REJECTED"
    touch(t)
    return ok_obj(ser_tax_document(t))
