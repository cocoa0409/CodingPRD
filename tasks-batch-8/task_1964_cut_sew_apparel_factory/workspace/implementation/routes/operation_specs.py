"""OperationSpec endpoints (PRD §3.1)."""

from flask import Blueprint, request

from db import store
from middleware import require_roles, ALL_ROLES, ROLE_MERCHANDISER
from response import success_object
from util import get_body, req_str, req_int, req_enum, fk_exists
from errors import tech_pack_not_editable, duplicate_operation_sequence
from services.core import base_record, public, get_operation_spec, get_tech_pack
from routes.common import list_response, active_filters

bp = Blueprint("operation_specs", __name__)

MACHINE_TYPES = {"SINGLE_NEEDLE", "OVERLOCK", "COVERSTITCH", "BUTTONHOLE", "MANUAL"}


@bp.route("/operation-specs", methods=["POST"])
def create_operation_spec():
    require_roles([ROLE_MERCHANDISER])
    body = get_body()
    fk_exists(body, "tech_pack_id", store.tech_packs, "TechPack")
    tech_pack_id = req_str(body, "tech_pack_id")
    sequence_no = req_int(body, "sequence_no", min_v=1)
    name = req_str(body, "name")
    machine_type = req_enum(body, "machine_type", MACHINE_TYPES)
    sam_seconds = req_int(body, "sam_seconds", min_v=1)
    piece_rate_cents = req_int(body, "piece_rate_cents", min_v=0)
    pack = get_tech_pack(tech_pack_id)
    # Editability (state) is evaluated before sequence uniqueness (PRD §3.1).
    if pack["status"] != "DRAFT":
        raise tech_pack_not_editable(
            "operation specs may only be added while the tech pack is DRAFT")
    if any(o["tech_pack_id"] == pack["id"] and o["sequence_no"] == sequence_no
           for o in store.operation_specs.values()):
        raise duplicate_operation_sequence(
            f"sequence_no {sequence_no} is already used in this tech pack")

    rec = base_record()
    rec.update({
        "tech_pack_id": tech_pack_id,
        "sequence_no": sequence_no,
        "name": name,
        "machine_type": machine_type,
        "sam_seconds": sam_seconds,
        "piece_rate_cents": piece_rate_cents,
    })
    store.operation_specs[rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.route("/operation-specs", methods=["GET"])
def list_operation_specs():
    require_roles(ALL_ROLES)
    filters = active_filters([("tech_pack_id", request.args.get("tech_pack_id"))])
    return list_response(store.operation_specs.values(), filters)


@bp.route("/operation-specs/<spec_id>", methods=["GET"])
def get_operation_spec_endpoint(spec_id):
    require_roles(ALL_ROLES)
    return success_object(public(get_operation_spec(spec_id)))
