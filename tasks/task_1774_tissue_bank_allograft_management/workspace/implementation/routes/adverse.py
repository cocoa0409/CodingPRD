"""Adverse reaction cases: investigation, resolution, reopening (PRD §3.7)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_ADVERSE_REACTION_NOT_FOUND,
    ERR_ADVERSE_INVALID_STATE,
    ERR_SEGREGATION_OF_DUTIES,
)
from middleware import require_roles, ALL_ROLES
from response import success_object
from services import domain
from validate import get_body, req_enum, req_str

bp = Blueprint("adverse", __name__)

ANY = ALL_ROLES


def get_adverse_or_404(adverse_id: str) -> dict:
    adverse = db["adverse_reactions"].get(adverse_id)
    if adverse is None:
        raise_error(ERR_ADVERSE_REACTION_NOT_FOUND, f"adverse reaction case {adverse_id} does not exist")
    return adverse


def _supplier_of(adverse: dict):
    unit = db["units"].get(adverse["tissue_unit_id"])
    if unit is None:
        return None
    return db["suppliers"].get(unit["supplier_id"])


@bp.route("/tissue-bank/adverse-reactions/<adverse_id>", methods=["GET"])
def get_adverse(adverse_id):
    require_roles(ANY)
    return success_object(domain.adverse_json(get_adverse_or_404(adverse_id)))


@bp.route("/tissue-bank/adverse-reactions/<adverse_id>/investigate", methods=["POST"])
def investigate_adverse(adverse_id):
    require_roles({"ComplianceOfficer"})
    adverse = get_adverse_or_404(adverse_id)
    if adverse["status"] not in ("REPORTED", "REOPENED"):
        raise_error(ERR_ADVERSE_INVALID_STATE, f"case status is {adverse['status']}, not REPORTED or REOPENED")
    adverse["status"] = "UNDER_INVESTIGATION"
    domain.touch(adverse)
    return success_object(domain.adverse_json(adverse))


@bp.route("/tissue-bank/adverse-reactions/<adverse_id>/resolve", methods=["POST"])
def resolve_adverse(adverse_id):
    caller = require_roles({"ComplianceOfficer"})
    adverse = get_adverse_or_404(adverse_id)
    # request shape (rung 3.4) pinned before state (rung 4)
    body = get_body()
    outcome = req_enum(body, "outcome", domain.ADVERSE_OUTCOMES)
    req_str(body, "outcome_notes", min_len=10)
    if adverse["status"] != "UNDER_INVESTIGATION":
        raise_error(ERR_ADVERSE_INVALID_STATE, f"case status is {adverse['status']}, not UNDER_INVESTIGATION")
    # structural rung: segregation of duties against the reporting surgeon
    if adverse["reporter_user_id"] == caller.user_id:
        raise_error(ERR_SEGREGATION_OF_DUTIES, "resolver must differ from the case's reporter")
    adverse["status"] = "CLOSED_CONFIRMED" if outcome == "CONFIRMED" else "CLOSED_UNCONFIRMED"
    adverse["investigator_user_id"] = caller.user_id
    domain.touch(adverse)
    supplier = _supplier_of(adverse)
    if supplier is not None:
        domain.maybe_auto_suspend(supplier)
    return success_object(domain.adverse_json(adverse))


@bp.route("/tissue-bank/adverse-reactions/<adverse_id>/reopen", methods=["POST"])
def reopen_adverse(adverse_id):
    require_roles({"ComplianceOfficer"})
    adverse = get_adverse_or_404(adverse_id)
    body = get_body()
    req_str(body, "reopen_reason", min_len=10)
    if adverse["status"] not in ("CLOSED_CONFIRMED", "CLOSED_UNCONFIRMED"):
        raise_error(ERR_ADVERSE_INVALID_STATE, f"case status is {adverse['status']}, not CLOSED_*")
    adverse["status"] = "REOPENED"
    adverse["reopened_count"] += 1
    domain.touch(adverse)
    supplier = _supplier_of(adverse)
    if supplier is not None:
        domain.maybe_auto_suspend(supplier)
    return success_object(domain.adverse_json(adverse))
