"""Routes for /nurses + /nurses/{id}/certification-records."""
from flask import Blueprint, g, request

import db
from db import public
from middleware import require_auth, get_pagination, get_json_body
from response import success, success_list
from errors import err
from services import nurse as nurse_svc


bp = Blueprint("nurses", __name__)


@bp.route("/nurses", methods=["POST"])
@require_auth(roles={"PlatformAdmin"})
def create_nurse():
    body = get_json_body()
    n = nurse_svc.create_nurse(body)
    return success(public(n), status=201)


@bp.route("/nurses", methods=["GET"])
@require_auth(roles={"PlatformAdmin", "ComplianceOfficer"})
def list_nurses():
    limit, offset = get_pagination()
    cs = request.args.get("certification_status")
    sp = request.args.get("specialty")
    rows, total = nurse_svc.list_nurses(limit, offset, cs, sp)
    return success_list([public(r) for r in rows], limit, offset, total)


@bp.route("/nurses/<nurse_id>", methods=["GET"])
@require_auth(roles={"PlatformAdmin", "ComplianceOfficer", "Nurse"})
def get_nurse(nurse_id):
    n = nurse_svc.get_nurse(nurse_id)
    if g.user_role == "Nurse" and g.user_id != n["id"]:
        raise err("ERR_INSUFFICIENT_PERMISSIONS", "nurses can only fetch their own profile")
    return success(public(n))


@bp.route("/nurses/<nurse_id>/certification-records", methods=["POST"])
@require_auth(roles={"ComplianceOfficer"})
def post_cert(nurse_id):
    body = get_json_body()
    rec = nurse_svc.create_certification_record(nurse_id, body)
    return success(public(rec), status=201)


@bp.route("/nurses/<nurse_id>/certification-records", methods=["GET"])
@require_auth(roles={"PlatformAdmin", "ComplianceOfficer", "Nurse"})
def list_certs(nurse_id):
    n = nurse_svc.get_nurse(nurse_id)
    if g.user_role == "Nurse" and g.user_id != n["id"]:
        raise err("ERR_INSUFFICIENT_PERMISSIONS", "nurses can only see their own records")
    limit, offset = get_pagination()
    rows, total = nurse_svc.list_certification_records(nurse_id, limit, offset)
    return success_list([public(r) for r in rows], limit, offset, total)
