"""ProcedureType endpoints (PRD 3.1)."""
from flask import Blueprint

from db import db
from errors import raise_error, ERR_PROCEDURE_TYPE_CODE_EXISTS, ERR_PROCEDURE_TYPE_NOT_FOUND
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response
from services.core import new_record, public
from validate import get_body, req_bool, req_enum, req_int, req_str

bp = Blueprint("procedure_types", __name__)

PREP_PROTOCOLS = {"NONE", "CLEAR_LIQUIDS", "SPLIT_DOSE"}
SCOPE_TYPES = {"COLONOSCOPE", "GASTROSCOPE", "SIGMOIDOSCOPE"}


@bp.post("/endoscopy/procedure-types")
def create_procedure_type():
    authorized(["UnitAdmin"])
    body = get_body()
    code = req_str(body, "code")
    display_name = req_str(body, "display_name")
    base_duration_minutes = req_int(body, "base_duration_minutes", minimum=1)
    prep_protocol = req_enum(body, "prep_protocol", PREP_PROTOCOLS)
    colonoscopy_family = req_bool(body, "colonoscopy_family")
    adr_relevant = req_bool(body, "adr_relevant")
    required_scope_type = req_enum(body, "required_scope_type", SCOPE_TYPES)
    # Rung 10 (uniqueness): code unique
    for t in db["procedure_types"].values():
        if t["code"] == code:
            raise_error(ERR_PROCEDURE_TYPE_CODE_EXISTS, f"duplicate procedure type code: {code}")
    rec = new_record("procedure_types", {
        "code": code,
        "display_name": display_name,
        "base_duration_minutes": base_duration_minutes,
        "prep_protocol": prep_protocol,
        "colonoscopy_family": colonoscopy_family,
        "adr_relevant": adr_relevant,
        "required_scope_type": required_scope_type,
    })
    return success_object(public(rec), status=201)


@bp.get("/endoscopy/procedure-types")
def list_procedure_types():
    return list_response("procedure_types")


@bp.get("/endoscopy/procedure-types/<rid>")
def get_procedure_type(rid):
    return get_one("procedure_types", rid, ERR_PROCEDURE_TYPE_NOT_FOUND)
