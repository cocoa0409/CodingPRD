"""Amendment routes."""

from flask import Blueprint, request, g
import middleware
import response
from services import lc as svc

bp = Blueprint("amendments", __name__)


@bp.route("/letters-of-credit/<lc_id>/amendments", methods=["POST"])
def initiate(lc_id):
    middleware.require_auth()
    middleware.require_role("IssuingBank")
    return response.success(svc.initiate_amendment(lc_id, request.get_json(silent=True) or {}, g.user_id), 201)


@bp.route("/letters-of-credit/<lc_id>/amendments", methods=["GET"])
def list_amendments(lc_id):
    middleware.require_auth()
    middleware.require_role(
        "Applicant", "Beneficiary",
        "IssuingBank", "AdvisingBank", "ConfirmingBank",
        "Operator", "Auditor",
    )
    limit, offset = response.parse_pagination(request.args)
    filters = {}
    if request.args.get("status"):
        filters["status"] = request.args.get("status")
    items, total = svc.list_amendments(lc_id, filters, limit, offset)
    return response.success_list(items, total, limit, offset)


@bp.route("/letters-of-credit/<lc_id>/amendments/<amendment_id>", methods=["GET"])
def get_amendment(lc_id, amendment_id):
    middleware.require_auth()
    middleware.require_role(
        "Applicant", "Beneficiary",
        "IssuingBank", "AdvisingBank", "ConfirmingBank",
        "Operator", "Auditor",
    )
    return response.success(svc.get_amendment(lc_id, amendment_id))


@bp.route("/letters-of-credit/<lc_id>/amendments/<amendment_id>/applicant-consent", methods=["POST"])
def applicant_consent(lc_id, amendment_id):
    middleware.require_auth()
    middleware.require_role("Applicant")
    return response.success(svc.applicant_consent(lc_id, amendment_id, request.get_json(silent=True) or {}, g.user_id))


@bp.route("/letters-of-credit/<lc_id>/amendments/<amendment_id>/beneficiary-consent", methods=["POST"])
def beneficiary_consent(lc_id, amendment_id):
    middleware.require_auth()
    middleware.require_role("Beneficiary")
    return response.success(svc.beneficiary_consent(lc_id, amendment_id, request.get_json(silent=True) or {}, g.user_id))


@bp.route("/letters-of-credit/<lc_id>/amendments/<amendment_id>/confirming-bank-consent", methods=["POST"])
def confirming_bank_consent(lc_id, amendment_id):
    middleware.require_auth()
    middleware.require_role("ConfirmingBank")
    return response.success(svc.confirming_bank_consent(lc_id, amendment_id, request.get_json(silent=True) or {}, g.user_id))


@bp.route("/letters-of-credit/<lc_id>/amendments/<amendment_id>/withdraw", methods=["POST"])
def withdraw(lc_id, amendment_id):
    middleware.require_auth()
    middleware.require_role("IssuingBank")
    return response.success(svc.withdraw_amendment(lc_id, amendment_id, request.get_json(silent=True) or {}, g.user_id))
