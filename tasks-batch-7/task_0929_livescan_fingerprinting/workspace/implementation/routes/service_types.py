from flask import Blueprint, request

import constants as C
import serializers
import validation as V
from envelope import object_response, paginate
from lookups import agency_of_ori, body_row, check_billing_freeze, path_row, unique_or_400
from store import db

bp = Blueprint("service_types", __name__)


@bp.post("/livescan/service-types")
def create_service_type():
    data = V.body()
    ori = body_row("oris", data.get("ori_id")) if data.get("ori_id") else None

    code = V.req_string(data, "code")
    applicant_type = V.req_string(data, "applicant_type")
    slot = V.req_int(data, "slot_duration_minutes")
    required_docs = V.req_array(data, "required_document_codes")
    accepted_ids = V.req_array(data, "accepted_id_document_types")
    state_fee = V.req_int(data, "state_fee_cents", minimum=0, maximum=20000)
    federal_fee = V.req_int(data, "federal_fee_cents", minimum=0, maximum=20000)
    retention_offered = V.opt_bool(data, "retention_offered", default=False)
    if ori is None:
        V.bad_request("ori_id is required")
    if slot not in C.SLOT_DURATIONS:
        V.bad_request("slot_duration_minutes must be 15, 30 or 45")

    unique_or_400("service_types", "code", code, scope_field="ori_id", scope_value=ori["id"])

    V.enum_value("applicant_type", applicant_type, C.APPLICANT_TYPES)
    V.enum_members("required_document_codes", required_docs, C.DOCUMENT_CODES)
    V.enum_members("accepted_id_document_types", accepted_ids, C.ID_DOCUMENT_TYPES)

    check_billing_freeze(agency_of_ori(ori))

    row = db.create(
        "service_types",
        {
            "ori_id": ori["id"],
            "code": code,
            "applicant_type": applicant_type,
            "slot_duration_minutes": slot,
            "required_document_codes": list(required_docs),
            "accepted_id_document_types": list(accepted_ids),
            "state_fee_cents": state_fee,
            "federal_fee_cents": federal_fee,
            "retention_offered": retention_offered,
            "status": "ACTIVE",
        },
    )
    return object_response(serializers.service_type(row), 201)


@bp.get("/livescan/service-types/<id>")
def read_service_type(id):
    return object_response(serializers.service_type(path_row("service_types", id)))


@bp.get("/livescan/service-types")
def list_service_types():
    rows = list(db.service_types.values())
    ori_id = request.args.get("ori_id")
    status = request.args.get("status")
    if ori_id is not None:
        rows = [r for r in rows if r["ori_id"] == ori_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, serializers.service_type)
