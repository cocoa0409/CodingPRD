"""Packaging lines (PRD 3.7)."""
from flask import Blueprint

import store
from auth import ALL_ROLES, authenticate, authorize
from errors import ERR_INVALID_STATE, raise_err
from services import PACK_FORMATS, line_out
from util import body_json, bump, get_or_404, new_record, req_enum, req_str, success_object

bp = Blueprint("packaging_lines", __name__)


@bp.route("/tea-ops/packaging-lines", methods=["POST"])
def create_line():
    _, role = authenticate()
    authorize(role, ["ProductionPlanner"])
    body = body_json()
    name = req_str(body, "name")
    line_type = req_enum(body, "line_type", PACK_FORMATS)

    rec = new_record()
    rec.update({"name": name, "line_type": line_type, "status": "ACTIVE"})
    store.packaging_lines[rec["id"]] = rec
    return success_object(line_out(rec), 201)


@bp.route("/tea-ops/packaging-lines/<lid>", methods=["GET"])
def get_line(lid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    rec = get_or_404(store.packaging_lines, lid, "PackagingLine")
    return success_object(line_out(rec))


@bp.route("/tea-ops/packaging-lines/<lid>/enter-maintenance", methods=["POST"])
def enter_maintenance(lid):
    _, role = authenticate()
    authorize(role, ["ProductionPlanner"])
    rec = get_or_404(store.packaging_lines, lid, "PackagingLine")
    if rec["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "Packaging line is not ACTIVE")
    rec["status"] = "MAINTENANCE"
    bump(rec)
    return success_object(line_out(rec))


@bp.route("/tea-ops/packaging-lines/<lid>/exit-maintenance", methods=["POST"])
def exit_maintenance(lid):
    _, role = authenticate()
    authorize(role, ["ProductionPlanner"])
    rec = get_or_404(store.packaging_lines, lid, "PackagingLine")
    if rec["status"] != "MAINTENANCE":
        raise_err(ERR_INVALID_STATE, "Packaging line is not in MAINTENANCE")
    rec["status"] = "ACTIVE"
    bump(rec)
    return success_object(line_out(rec))
