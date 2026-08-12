"""Compliance record endpoints: list/get and certified destruction (PRD §3.9)."""
from flask import Blueprint, request

from calc import touch
from db import STORE
from errors import (
    ERR_ALREADY_TERMINAL,
    ERR_NOT_FOUND,
    ERR_RECORD_NOT_ELIGIBLE,
    raise_err,
)
from middleware import authenticate, get_body, require_client_scope, require_role
from response import paginate, success_object
from serializers import serialize, sorted_by_creation

bp = Blueprint("records", __name__)

ALL_ROLES = {"FirmAdmin", "Analyst", "LicensedBroker", "ComplianceManager", "ClientContact"}


def get_record_or_404(record_id):
    record = STORE["compliance_records"].get(record_id)
    if record is None:
        raise_err(ERR_NOT_FOUND, f"Compliance record {record_id} not found")
    return record


def _record_client_id(record):
    claim = STORE["claims"].get(record["claim_id"])
    return claim["client_id"] if claim else None


@bp.route("/customs/records/<record_id>", methods=["GET"])
def get_record(record_id):
    user_id, role = authenticate()
    require_role(role, ALL_ROLES)
    record = get_record_or_404(record_id)
    require_client_scope(user_id, role, _record_client_id(record))
    return success_object(serialize(record))


@bp.route("/customs/records", methods=["GET"])
def list_records():
    user_id, role = authenticate()
    require_role(role, ALL_ROLES)
    items = sorted_by_creation(STORE["compliance_records"].values())
    if role == "ClientContact":
        items = [r for r in items if _record_client_id(r) == user_id]
    claim_id = request.args.get("claim_id")
    if claim_id is not None:
        items = [r for r in items if r["claim_id"] == claim_id]
    doc_type = request.args.get("doc_type")
    if doc_type is not None:
        items = [r for r in items if r["doc_type"] == doc_type]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return paginate([serialize(r) for r in items])


@bp.route("/customs/records/<record_id>/destroy", methods=["POST"])
def destroy_record(record_id):
    _, role = authenticate()
    require_role(role, {"ComplianceManager"})
    record = get_record_or_404(record_id)
    get_body()
    if record["status"] == "DESTROYED":
        raise_err(ERR_ALREADY_TERMINAL, "Record is DESTROYED (terminal)")
    if record["status"] != "ELIGIBLE_FOR_DESTRUCTION":
        raise_err(ERR_RECORD_NOT_ELIGIBLE, "Record is not ELIGIBLE_FOR_DESTRUCTION")
    record["status"] = "DESTROYED"
    touch(record)
    return success_object(serialize(record))
