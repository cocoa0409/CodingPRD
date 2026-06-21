"""NEDSS exports: generate, list, get, transmit, void."""
from flask import Blueprint, request

from db import db, new_id
from errors import err
from helpers import (base_entity, touch, parse_pagination, sorted_by_creation,
                     get_or_404, get_in_program_or_404, require_string)
from middleware import get_user_context, require_role
from response import success, success_list
from serializers import ser_export

bp = Blueprint("exports", __name__)

EXPORT_READ_ROLES = {"JurisdictionAdmin", "EpiAnalyst"}


def _mint_message_id():
    return "nedss_" + new_id().replace("-", "")[:24]


@bp.route("/surveillance/nedss-exports", methods=["POST"])
def generate_export():
    _, role = get_user_context()
    require_role(role, {"EpiAnalyst"})
    body = request.get_json(silent=True) or {}
    program_id = require_string(body, "program_id")
    case_id = require_string(body, "case_id")
    with db.lock:
        get_or_404(db.programs, program_id, "ERR_PROGRAM_NOT_FOUND")
        case = get_in_program_or_404(db.cases, case_id, program_id, "ERR_CASE_NOT_FOUND")
        if case["classification"] not in ("CONFIRMED", "PROBABLE"):
            raise err("ERR_EXPORT_CASE_NOT_REPORTABLE",
                      "NEDSS export requires case classification CONFIRMED or PROBABLE")
        ent = base_entity(common_fields=True)
        ent.update({
            "program_id": program_id,
            "case_id": case_id,
            "snapshot_classification": case["classification"],
            "snapshot_completeness_score": case["completeness_score"],
            "nedss_message_id": _mint_message_id(),
            "status": "GENERATED",
        })
        db.exports[ent["id"]] = ent
        return success(ser_export(ent), 201)


@bp.route("/surveillance/nedss-exports", methods=["GET"])
def list_exports():
    _, role = get_user_context()
    require_role(role, EXPORT_READ_ROLES)
    with db.lock:
        filters = ["program_id", "case_id", "status"]
        items = []
        for e in db.exports.values():
            ok = True
            for f in filters:
                v = request.args.get(f)
                if v is not None and e.get(f) != v:
                    ok = False
                    break
            if ok:
                items.append(e)
        items = sorted_by_creation(items)
        total = len(items)
        limit, offset = parse_pagination(request.args)
        page = items[offset:offset + limit]
        return success_list([ser_export(e) for e in page], limit, offset, total)


@bp.route("/surveillance/nedss-exports/<export_id>", methods=["GET"])
def get_export(export_id):
    _, role = get_user_context()
    require_role(role, EXPORT_READ_ROLES)
    with db.lock:
        e = get_or_404(db.exports, export_id, "ERR_EXPORT_NOT_FOUND")
        return success(ser_export(e), 200)


@bp.route("/surveillance/nedss-exports/<export_id>/transmit", methods=["POST"])
def transmit_export(export_id):
    _, role = get_user_context()
    require_role(role, {"EpiAnalyst"})
    with db.lock:
        e = get_or_404(db.exports, export_id, "ERR_EXPORT_NOT_FOUND")
        if e["status"] != "GENERATED":
            raise err("ERR_EXPORT_NOT_TRANSMITTABLE", "Export not in GENERATED for transmit")
        case = db.cases.get(e["case_id"])
        if case is None or case["classification"] != e["snapshot_classification"]:
            raise err("ERR_EXPORT_SNAPSHOT_STALE", "Case classification changed since export snapshot")
        e["status"] = "TRANSMITTED"
        touch(e)
        return success(ser_export(e), 200)


@bp.route("/surveillance/nedss-exports/<export_id>/void", methods=["POST"])
def void_export(export_id):
    _, role = get_user_context()
    require_role(role, {"EpiAnalyst"})
    with db.lock:
        e = get_or_404(db.exports, export_id, "ERR_EXPORT_NOT_FOUND")
        if e["status"] != "GENERATED":
            raise err("ERR_EXPORT_NOT_VOIDABLE", "Export not in GENERATED for void")
        e["status"] = "VOIDED"
        touch(e)
        return success(ser_export(e), 200)
