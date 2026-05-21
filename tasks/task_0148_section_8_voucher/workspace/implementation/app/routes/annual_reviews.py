"""/annual-reviews routes."""

from flask import Blueprint

from app import store
from app.envelope import success_response
from app.errors import forbidden_role, not_found
from app.routes._helpers import get_json_body, with_auth
from app.serializers import serialize_annual_review
from app.services import annual_reviews as svc


bp = Blueprint("annual_reviews", __name__)


def _ownership_visible_applicant(caller, ar: dict) -> bool:
    tenancy = store.tenancies.get(ar["tenancy_id"])
    if tenancy is None:
        return False
    voucher = store.vouchers.get(tenancy["voucher_id"])
    if voucher is None:
        return False
    return voucher.get("applicant_id") == caller.user_id


@bp.get("/annual-reviews/<ar_id>")
@with_auth("Applicant", "CaseWorker")
def get_review(ar_id, caller=None):
    ar = store.annual_reviews.get(ar_id)
    if ar is None:
        raise not_found("AnnualReview not found")
    if caller.role == "Applicant" and not _ownership_visible_applicant(caller, ar):
        raise forbidden_role("Applicant may only read own annual reviews")
    return success_response(serialize_annual_review(ar))


@bp.post("/annual-reviews/<ar_id>/submit")
@with_auth("Applicant")
def submit_review(ar_id, caller=None):
    body = get_json_body()
    with store.lock():
        ar = svc.submit(ar_id, body)
    return success_response(serialize_annual_review(ar))


@bp.post("/annual-reviews/<ar_id>/mark-deficient")
@with_auth("CaseWorker")
def mark_deficient(ar_id, caller=None):
    body = get_json_body()
    with store.lock():
        ar = svc.mark_deficient(ar_id, body)
    return success_response(serialize_annual_review(ar))


@bp.post("/annual-reviews/<ar_id>/resubmit")
@with_auth("Applicant")
def resubmit_review(ar_id, caller=None):
    body = get_json_body()
    with store.lock():
        ar = svc.resubmit(ar_id, body)
    return success_response(serialize_annual_review(ar))


@bp.post("/annual-reviews/<ar_id>/approve")
@with_auth("CaseWorker")
def approve_review(ar_id, caller=None):
    body = get_json_body()
    with store.lock():
        ar = svc.approve(ar_id, body)
    return success_response(serialize_annual_review(ar))


@bp.post("/annual-reviews/<ar_id>/deny")
@with_auth("CaseWorker")
def deny_review(ar_id, caller=None):
    body = get_json_body()
    with store.lock():
        ar = svc.deny(ar_id, body)
    return success_response(serialize_annual_review(ar))
