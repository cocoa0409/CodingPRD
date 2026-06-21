"""Medical-lien routes (PRD §3.7)."""
from __future__ import annotations

from flask import Blueprint, request

from db import (
    medical_liens, cases, medical_providers,
    stamp_common, bump,
)
from errors import (
    APIError, ERR_INVALID_STATE, ERR_LIEN_OVERPAYMENT, ERR_INVALID_REQUEST,
)
from middleware import require_auth, get_json_body
from response import ok_object, ok_array, paginate_params, slice_page
from services.validation import (
    require_str, require_int,
    get_or_404_path, get_or_fk_404,
)


bp = Blueprint("medical_liens", __name__)


def _view(l: dict) -> dict:
    return {
        "id": l["id"],
        "case_id": l["case_id"],
        "provider_id": l["provider_id"],
        "asserted_amount_cents": l["asserted_amount_cents"],
        "negotiated_amount_cents": l["negotiated_amount_cents"],
        "status": l["status"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


@bp.post("/medical-liens")
def create_lien():
    require_auth({"Paralegal"})()
    body = get_json_body()
    case_id = require_str(body, "case_id")
    provider_id = require_str(body, "provider_id")
    asserted = require_int(body, "asserted_amount_cents", min_value=0)

    get_or_fk_404(cases, case_id, "Case")
    get_or_fk_404(medical_providers, provider_id, "MedicalProvider")

    l = {
        "case_id": case_id,
        "provider_id": provider_id,
        "asserted_amount_cents": asserted,
        "negotiated_amount_cents": asserted,
        "status": "ASSERTED",
    }
    stamp_common(l)
    medical_liens[l["id"]] = l
    return ok_object(_view(l), 201)


@bp.get("/medical-liens/<lid>")
def get_lien(lid):
    require_auth({"Paralegal", "Attorney", "ManagingPartner"})()
    l = get_or_404_path(medical_liens, lid, "MedicalLien")
    return ok_object(_view(l), 200)


@bp.get("/medical-liens")
def list_liens():
    require_auth({"Paralegal", "Attorney", "ManagingPartner"})()
    limit, offset = paginate_params(request.args)
    case_id = request.args.get("case_id")
    provider_id = request.args.get("provider_id")
    status = request.args.get("status")
    items = list(medical_liens.values())
    if case_id is not None:
        items = [l for l in items if l["case_id"] == case_id]
    if provider_id is not None:
        items = [l for l in items if l["provider_id"] == provider_id]
    if status is not None:
        items = [l for l in items if l["status"] == status]
    items.sort(key=lambda l: l["created_at"])
    page, total = slice_page(items, limit, offset)
    return ok_array([_view(l) for l in page], limit, offset, total, 200)


@bp.post("/medical-liens/<lid>/negotiate")
def negotiate(lid):
    require_auth({"Paralegal"})()
    l = get_or_404_path(medical_liens, lid, "MedicalLien")
    if l["status"] != "ASSERTED":
        raise APIError(ERR_INVALID_STATE, 409, "Lien must be ASSERTED to negotiate")
    l["status"] = "NEGOTIATING"
    bump(l)
    return ok_object(_view(l), 200)


@bp.post("/medical-liens/<lid>/agree")
def agree(lid):
    require_auth({"Paralegal"})()
    l = get_or_404_path(medical_liens, lid, "MedicalLien")
    body = get_json_body()
    negotiated = require_int(body, "negotiated_amount_cents", min_value=0)
    if l["status"] != "NEGOTIATING":
        raise APIError(ERR_INVALID_STATE, 409, "Lien must be NEGOTIATING to agree")
    if negotiated > int(l["asserted_amount_cents"]):
        raise APIError(
            ERR_LIEN_OVERPAYMENT, 422,
            "negotiated_amount_cents cannot exceed asserted_amount_cents",
        )
    l["negotiated_amount_cents"] = negotiated
    l["status"] = "AGREED"
    bump(l)
    return ok_object(_view(l), 200)


@bp.post("/medical-liens/<lid>/dispute")
def dispute(lid):
    require_auth({"Attorney"})()
    l = get_or_404_path(medical_liens, lid, "MedicalLien")
    if l["status"] != "NEGOTIATING":
        raise APIError(ERR_INVALID_STATE, 409, "Lien must be NEGOTIATING to dispute")
    l["status"] = "DISPUTED"
    bump(l)
    return ok_object(_view(l), 200)


@bp.post("/medical-liens/<lid>/resume-negotiation")
def resume_negotiation(lid):
    require_auth({"Attorney"})()
    l = get_or_404_path(medical_liens, lid, "MedicalLien")
    if l["status"] != "DISPUTED":
        raise APIError(ERR_INVALID_STATE, 409, "Lien must be DISPUTED to resume negotiation")
    l["status"] = "NEGOTIATING"
    bump(l)
    return ok_object(_view(l), 200)
