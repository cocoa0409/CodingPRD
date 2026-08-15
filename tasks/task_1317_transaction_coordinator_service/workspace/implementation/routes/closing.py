"""Closing verifications: title / lender confirmation (segregation of duties)."""
from flask import Blueprint, request

import middleware as mw
from db import store, touch, pub, pub_list
from response import ok_object, ok_list

bp = Blueprint("closing", __name__)


def _recompute_overall(cv):
    overall = "CLEAR_TO_CLOSE" if (
        cv["title_status"] == "CLEARED"
        and cv["lender_status"] in ("CLEAR_TO_CLOSE", "NOT_REQUIRED")) else "PENDING"
    if cv["overall_status"] != overall:
        cv["overall_status"] = overall
        return True
    return False


@bp.get("/tc/closing-verifications/<closingVerificationId>")
def get_cv(closingVerificationId):
    mw.auth()
    rec = mw.get_or_404("closing_verification", closingVerificationId)
    return ok_object(pub("closing_verification", rec))


@bp.get("/tc/closing-verifications")
def list_cvs():
    mw.auth()
    limit, offset = mw.page_params()
    recs = list(store.closing_verifications.values())
    recs = mw.filter_eq(recs, "file_id", request.args.get("file_id"))
    page, total = mw.apply_page(recs, limit, offset)
    return ok_list(pub_list("closing_verification", page), limit, offset, total)


@bp.post("/tc/closing-verifications/<closingVerificationId>/confirm-title")
def confirm_title(closingVerificationId):
    uid, role = mw.auth()
    mw.require_roles(role, {"TitleRep"})
    rec = mw.get_or_404("closing_verification", closingVerificationId)
    changed = False
    if rec["title_status"] == "PENDING":
        rec["title_status"] = "CLEARED"
        changed = True
    changed = _recompute_overall(rec) or changed
    if changed:
        touch(rec)
    return ok_object(pub("closing_verification", rec))


@bp.post("/tc/closing-verifications/<closingVerificationId>/confirm-lender")
def confirm_lender(closingVerificationId):
    uid, role = mw.auth()
    mw.require_roles(role, {"LenderRep"})
    rec = mw.get_or_404("closing_verification", closingVerificationId)
    changed = False
    if rec["lender_status"] == "PENDING":
        rec["lender_status"] = "CLEAR_TO_CLOSE"
        changed = True
    # a NOT_REQUIRED lender side never moves
    changed = _recompute_overall(rec) or changed
    if changed:
        touch(rec)
    return ok_object(pub("closing_verification", rec))
