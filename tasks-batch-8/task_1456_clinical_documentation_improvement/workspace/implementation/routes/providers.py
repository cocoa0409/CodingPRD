"""Provider registry endpoints."""
from flask import Blueprint, request

import db
from errors import raise_error
from helpers import (
    body_ref,
    get_or_404,
    list_page,
    make_record,
    require_program_active,
)
from middleware import (
    check_known_fields,
    get_json_body,
    require_fields,
    require_roles,
    validate_string,
)
from response import success_list, success_object
from serializers import education_event_out, provider_out

bp = Blueprint("providers", __name__)

LIST_ROLES = {"CDIManager", "CDISpecialist", "HIMCoder", "ComplianceAuditor"}
GET_ROLES = LIST_ROLES | {"Provider"}
EDU_ROLES = {"CDIManager", "CDISpecialist", "ComplianceAuditor"}


@bp.route("/api/providers", methods=["POST"])
def create_provider():
    require_roles({"CDIManager"})
    body = get_json_body()
    check_known_fields(body, {"cdi_program_id", "npi", "full_name", "specialty"})
    require_fields(body, ["cdi_program_id", "npi", "full_name", "specialty"])
    program = body_ref(body, "cdi_program_id", db.programs, "program")
    npi = validate_string(body["npi"], "npi")
    full_name = validate_string(body["full_name"], "full_name")
    specialty = validate_string(body["specialty"], "specialty")
    require_program_active(program)
    for p in db.providers.values():
        if p["cdi_program_id"] == program["id"] and p["npi"] == npi:
            raise_error(
                "ERR_INVALID_REQUEST",
                f"npi {npi!r} already registered in this program",
            )
    provider = make_record(db.providers, {
        "cdi_program_id": program["id"],
        "npi": npi,
        "full_name": full_name,
        "specialty": specialty,
        "education_score": 100,
        "pattern_tally_json": {},
        "education_flag": "NONE",
    })
    return success_object(provider_out(provider), status=201)


@bp.route("/api/providers", methods=["GET"])
def list_providers():
    require_roles(LIST_ROLES)
    program_id = request.args.get("cdi_program_id")
    flag = request.args.get("education_flag")
    specialty = request.args.get("specialty")
    items = list(db.providers.values())
    if program_id is not None:
        items = [p for p in items if p["cdi_program_id"] == program_id]
    if flag is not None:
        items = [p for p in items if p["education_flag"] == flag]
    if specialty is not None:
        items = [p for p in items if p["specialty"] == specialty]
    page, limit, offset, total = list_page(items)
    return success_list([provider_out(p) for p in page], limit, offset, total)


@bp.route("/api/providers/<providerId>", methods=["GET"])
def get_provider(providerId):
    require_roles(GET_ROLES)
    provider = get_or_404(db.providers, providerId, "provider")
    return success_object(provider_out(provider))


@bp.route("/api/providers/<providerId>/education-events", methods=["GET"])
def list_provider_education_events(providerId):
    require_roles(EDU_ROLES)
    get_or_404(db.providers, providerId, "provider")
    pattern_tag = request.args.get("pattern_tag")
    items = [e for e in db.education_events.values() if e["provider_id"] == providerId]
    if pattern_tag is not None:
        items = [e for e in items if e["pattern_tag"] == pattern_tag]
    page, limit, offset, total = list_page(items)
    return success_list([education_event_out(e) for e in page], limit, offset, total)
