"""LostFoundReport endpoints (PRD §3.8, §4)."""
from flask import Blueprint, request

from db import db
from errors import err
from middleware import authenticate, require_role
from response import array_response, object_response
from services import lostfound as lf_svc
from services.core import stamp_create
from services.reqs import (body, paginate, parse_pagination, require_enum,
                          require_fields)
from services.views import report_view

bp = Blueprint("lostfound", __name__)

ALL_ROLES = {"Owner", "LicensingClerk", "AnimalControlOfficer"}
REPORT_TYPES = {"LOST", "FOUND"}
SPECIES = {"DOG", "CAT"}


@bp.route("/lost-found-reports", methods=["POST"])
def create_report():
    _, role = authenticate()
    require_role(role, {"Owner", "AnimalControlOfficer", "LicensingClerk"})
    data = body()
    require_fields(data, ["report_type", "species", "zip_seen", "reported_at"])
    require_enum(data["report_type"], REPORT_TYPES, "report_type")
    require_enum(data["species"], SPECIES, "species")
    pet_id = data.get("pet_id")
    if pet_id is not None and db.pets.get(pet_id) is None:
        raise err("ERR_NOT_FOUND", "Pet not found.")
    report = {
        "report_type": data["report_type"],
        "pet_id": pet_id,
        "tag_serial_seen": data.get("tag_serial_seen"),
        "species": data["species"],
        "zip_seen": data["zip_seen"],
        "reported_at": data["reported_at"],
        "status": "OPEN",
        "matched_report_id": None,
        "match_score": 0,
    }
    stamp_create(report)
    db.lost_found_reports[report["id"]] = report
    return object_response(report_view(report), status=201)


@bp.route("/lost-found-reports/<report_id>", methods=["GET"])
def get_report(report_id):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    report = db.lost_found_reports.get(report_id)
    if report is None:
        raise err("ERR_NOT_FOUND", "Report not found.")
    return object_response(report_view(report))


@bp.route("/lost-found-reports", methods=["GET"])
def list_reports():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.lost_found_reports.values())
    for field in ("report_type", "status", "species", "pet_id", "matched_report_id"):
        val = request.args.get(field)
        if val is not None:
            items = [r for r in items if r.get(field) == val]
    page, total = paginate(items, limit, offset)
    return array_response([report_view(r) for r in page], limit, offset, total)


def _load(report_id):
    report = db.lost_found_reports.get(report_id)
    if report is None:
        raise err("ERR_NOT_FOUND", "Report not found.")
    return report


@bp.route("/lost-found-reports/<report_id>/match", methods=["POST"])
def match(report_id):
    _, role = authenticate()
    require_role(role, {"AnimalControlOfficer"})
    report = _load(report_id)
    lf_svc.match(report)
    return object_response(report_view(report))


@bp.route("/lost-found-reports/<report_id>/resolve", methods=["POST"])
def resolve(report_id):
    _, role = authenticate()
    require_role(role, {"AnimalControlOfficer"})
    report = _load(report_id)
    lf_svc.resolve(report)
    return object_response(report_view(report))


@bp.route("/lost-found-reports/<report_id>/unmatch", methods=["POST"])
def unmatch(report_id):
    _, role = authenticate()
    require_role(role, {"AnimalControlOfficer"})
    report = _load(report_id)
    lf_svc.unmatch(report)
    return object_response(report_view(report))


@bp.route("/lost-found-reports/<report_id>/close", methods=["POST"])
def close(report_id):
    _, role = authenticate()
    require_role(role, {"AnimalControlOfficer"})
    report = _load(report_id)
    lf_svc.close(report)
    return object_response(report_view(report))
