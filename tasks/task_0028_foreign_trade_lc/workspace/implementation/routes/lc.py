"""LC root + lifecycle endpoints."""

from flask import Blueprint, request, g
import middleware
import response
from services import lc as svc

bp = Blueprint("lc", __name__)


@bp.route("/letters-of-credit", methods=["POST"])
def create():
    middleware.require_auth()
    middleware.require_role("Applicant")
    payload = request.get_json(silent=True) or {}
    return response.success(svc.create_draft(payload, g.role, g.user_id), 201)


@bp.route("/letters-of-credit", methods=["GET"])
def list_lcs():
    middleware.require_auth()
    middleware.require_role(
        "Operator", "Auditor",
        "IssuingBank", "AdvisingBank", "ConfirmingBank",
        "Applicant", "Beneficiary",
    )
    limit, offset = response.parse_pagination(request.args)
    filters = {}
    for k in ("lifecycle_status", "applicant_id", "beneficiary_id", "issuing_bank_id"):
        v = request.args.get(k)
        if v is not None:
            filters[k] = v
    items, total = svc.list_lcs(filters, limit, offset, g.role, g.user_id)
    return response.success_list(items, total, limit, offset)


@bp.route("/letters-of-credit/<lc_id>", methods=["GET"])
def get(lc_id):
    middleware.require_auth()
    middleware.require_role(
        "Applicant", "Beneficiary",
        "IssuingBank", "AdvisingBank", "ConfirmingBank", "NegotiatingBank",
        "Operator", "Auditor",
    )
    return response.success(svc.get_lc(lc_id, g.role, g.user_id))


@bp.route("/letters-of-credit/<lc_id>/submit", methods=["POST"])
def submit(lc_id):
    middleware.require_auth()
    middleware.require_role("Applicant")
    payload = request.get_json(silent=True) or {}
    return response.success(svc.submit(lc_id, payload, g.user_id))


@bp.route("/letters-of-credit/<lc_id>/return-to-applicant", methods=["POST"])
def return_to_applicant(lc_id):
    middleware.require_auth()
    middleware.require_role("IssuingBank")
    payload = request.get_json(silent=True) or {}
    return response.success(svc.return_to_applicant(lc_id, payload, g.user_id))


@bp.route("/letters-of-credit/<lc_id>/issue", methods=["POST"])
def issue(lc_id):
    middleware.require_auth()
    middleware.require_role("IssuingBank")
    payload = request.get_json(silent=True) or {}
    return response.success(svc.issue(lc_id, payload, g.user_id))


@bp.route("/letters-of-credit/<lc_id>/advise", methods=["POST"])
def advise(lc_id):
    middleware.require_auth()
    middleware.require_role("AdvisingBank")
    payload = request.get_json(silent=True) or {}
    return response.success(svc.advise(lc_id, payload, g.user_id))


@bp.route("/letters-of-credit/<lc_id>/confirm", methods=["POST"])
def confirm(lc_id):
    middleware.require_auth()
    middleware.require_role("ConfirmingBank")
    payload = request.get_json(silent=True) or {}
    return response.success(svc.confirm(lc_id, payload, g.user_id))


@bp.route("/letters-of-credit/<lc_id>/cancel", methods=["POST"])
def cancel(lc_id):
    middleware.require_auth()
    middleware.require_role("IssuingBank")
    payload = request.get_json(silent=True) or {}
    return response.success(svc.cancel(lc_id, payload, g.user_id))


@bp.route("/letters-of-credit/<lc_id>/audit-log", methods=["GET"])
def audit_log(lc_id):
    middleware.require_auth()
    middleware.require_role("Operator", "Auditor", "IssuingBank")
    limit, offset = response.parse_pagination(request.args)
    filters = {}
    if request.args.get("subject_type"):
        filters["subject_type"] = request.args.get("subject_type")
    items, total = svc.list_audit_log(lc_id, filters, limit, offset)
    return response.success_list(items, total, limit, offset)
