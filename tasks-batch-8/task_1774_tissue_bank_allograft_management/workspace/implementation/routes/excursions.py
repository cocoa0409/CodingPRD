"""Temperature excursions: retrieval, investigation, resolution (PRD §3.3)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_EXCURSION_NOT_FOUND,
    ERR_EXCURSION_INVALID_STATE,
    ERR_SEVERITY_REQUIRES_DESTROY,
    ERR_SEGREGATION_OF_DUTIES,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from services import domain
from validate import get_body, req_enum, req_str, paginate

bp = Blueprint("excursions", __name__)

ANY = ALL_ROLES


def get_excursion_or_404(excursion_id: str) -> dict:
    excursion = db["excursions"].get(excursion_id)
    if excursion is None:
        raise_error(ERR_EXCURSION_NOT_FOUND, f"temperature excursion {excursion_id} does not exist")
    return excursion


@bp.route("/tissue-bank/excursions/<excursion_id>", methods=["GET"])
def get_excursion(excursion_id):
    require_roles(ANY)
    return success_object(domain.excursion_json(get_excursion_or_404(excursion_id)))


@bp.route("/tissue-bank/excursions/<excursion_id>/investigate", methods=["POST"])
def investigate_excursion(excursion_id):
    require_roles({"QualityManager"})
    excursion = get_excursion_or_404(excursion_id)
    if excursion["status"] != "OPEN":
        raise_error(ERR_EXCURSION_INVALID_STATE, f"excursion status is {excursion['status']}, not OPEN")
    excursion["status"] = "UNDER_INVESTIGATION"
    domain.touch(excursion)
    return success_object(domain.excursion_json(excursion))


@bp.route("/tissue-bank/excursions/<excursion_id>/resolve", methods=["POST"])
def resolve_excursion(excursion_id):
    caller = require_roles({"QualityManager"})
    excursion = get_excursion_or_404(excursion_id)
    # request shape (rung 3.4) is pinned before state (rung 4)
    body = get_body()
    disposition = req_enum(body, "disposition", domain.EXCURSION_DISPOSITIONS)
    resolution_notes = req_str(body, "resolution_notes", min_len=10)
    if excursion["status"] != "UNDER_INVESTIGATION":
        raise_error(ERR_EXCURSION_INVALID_STATE, f"excursion status is {excursion['status']}, not UNDER_INVESTIGATION")
    # compliance rung: HIGH severity forbids RELEASE
    _score, severity_class, _affected = domain.excursion_severity(excursion)
    if disposition == "RELEASE" and severity_class == "HIGH":
        raise_error(ERR_SEVERITY_REQUIRES_DESTROY, "severity_class HIGH may only resolve as DESTROY")
    # structural rung: segregation of duties against a manual reporter
    if excursion["origin"] == "MANUAL_REPORT" and excursion["reported_by_user_id"] == caller.user_id:
        raise_error(ERR_SEGREGATION_OF_DUTIES, "resolver must differ from the excursion's manual reporter")
    domain.resolve_excursion_cascade(excursion, disposition, caller.user_id, resolution_notes)
    return success_object(domain.excursion_json(excursion))


@bp.route("/tissue-bank/excursions/<excursion_id>/readings", methods=["GET"])
def list_excursion_readings(excursion_id):
    require_roles(ANY)
    excursion = get_excursion_or_404(excursion_id)
    items = [r for r in db["readings"].values() if r["excursion_id"] == excursion["id"]]
    items.sort(key=lambda r: (r["_created_dt"], r["_seq"]))
    page, total, limit, offset = paginate(items)
    return success_list([domain.reading_json(r) for r in page], total, limit, offset)
