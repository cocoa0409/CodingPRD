"""Routes for /complaints/* endpoints."""
from flask import Blueprint, g, request

from db import public
from middleware import require_auth, get_pagination, get_json_body
from response import success, success_list
from services import complaint as svc


bp = Blueprint("complaints", __name__)


@bp.route("/complaints", methods=["POST"])
@require_auth(roles={"Patient"})
def submit():
    body = get_json_body()
    c = svc.submit_complaint(g.user_id, body)
    return success(public(c), status=201)


@bp.route("/complaints", methods=["GET"])
@require_auth(roles={"Patient", "PlatformAdmin", "ComplianceOfficer"})
def list_c():
    limit, offset = get_pagination()
    stage = request.args.get("stage")
    rows, total = svc.list_complaints_scoped(g.user_role, g.user_id, limit, offset, stage)
    return success_list([public(r) for r in rows], limit, offset, total)


@bp.route("/complaints/<complaint_id>/triage", methods=["POST"])
@require_auth(roles={"ComplianceOfficer"})
def triage(complaint_id):
    body = get_json_body()
    c = svc.triage(complaint_id, body)
    return success(public(c))


@bp.route("/complaints/<complaint_id>/escalate-mediation", methods=["POST"])
@require_auth(roles={"ComplianceOfficer"})
def escalate(complaint_id):
    body = get_json_body()
    c = svc.escalate(complaint_id, body)
    return success(public(c))


@bp.route("/complaints/<complaint_id>/resolve", methods=["POST"])
@require_auth(roles={"ComplianceOfficer"})
def resolve(complaint_id):
    body = get_json_body()
    c = svc.resolve(complaint_id, body)
    return success(public(c))
