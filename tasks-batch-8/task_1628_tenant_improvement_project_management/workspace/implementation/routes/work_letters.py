"""WorkLetter negotiation endpoints."""

from flask import Blueprint, request

from db import store
from middleware import require_roles, check_tenant_ownership, get_project_tenant_ownership
from response import success_object, success_created, success_list
from errors import (
    not_found, invalid_request, invalid_state, stale_version, APIError,
    ERR_WORK_LETTER_ALREADY_EXECUTED,
)
from services.util import (
    make_common_fields, bump_version, get_pagination_params, paginate,
    require_fields, is_int, is_str,
)

bp = Blueprint("work_letters", __name__)


def _get_wl_or_404(wid):
    wl = store.work_letters.get(wid)
    if not wl:
        raise not_found("WorkLetter not found")
    return wl


def _next_version_no(project_id):
    existing = [
        wl for wl in store.work_letters.values() if wl["project_id"] == project_id
    ]
    return len(existing) + 1


@bp.route("/api/ti-projects/<id>/work-letters", methods=["POST"])
def create_work_letter(id):
    require_roles("LandlordPM")
    proj = store.ti_projects.get(id)
    if not proj:
        raise not_found("TIProject not found")
    if proj["status"] not in ("INITIATED", "WORK_LETTER_NEGOTIATION"):
        raise invalid_state("Project must be in INITIATED or WORK_LETTER_NEGOTIATION")

    body = request.get_json(silent=True) or {}
    require_fields(body, ["scope_description", "allowance_offer_cents", "work_delineation"])
    if not is_str(body["scope_description"]):
        raise invalid_request("scope_description must be a string")
    if not is_int(body["allowance_offer_cents"]) or body["allowance_offer_cents"] < 0:
        raise invalid_request("allowance_offer_cents must be integer >= 0")
    if body["work_delineation"] not in ("LANDLORD", "TENANT", "SPLIT"):
        raise invalid_request("work_delineation must be LANDLORD, TENANT, or SPLIT")

    rec = make_common_fields()
    rec.update({
        "project_id": id,
        "version_no": _next_version_no(id),
        "scope_description": body["scope_description"],
        "allowance_offer_cents": body["allowance_offer_cents"],
        "work_delineation": body["work_delineation"],
        "proposed_by": None,
        "round_number": 0,
        "status": "DRAFT",
    })
    store.work_letters[rec["id"]] = rec

    # First creation advances project INITIATED -> WORK_LETTER_NEGOTIATION
    if proj["status"] == "INITIATED":
        proj["status"] = "WORK_LETTER_NEGOTIATION"
        bump_version(proj)

    return success_created(rec)


@bp.route("/api/ti-projects/<id>/work-letters", methods=["GET"])
def list_work_letters(id):
    user_id, role = require_roles("LandlordPM", "LandlordApprover", "TenantRep")
    proj = store.ti_projects.get(id)
    if not proj:
        raise not_found("TIProject not found")
    if role == "TenantRep":
        check_tenant_ownership(user_id, proj["lease_id"])
    limit, offset = get_pagination_params()
    items = [wl for wl in store.work_letters.values() if wl["project_id"] == id]
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/api/work-letters/<id>", methods=["GET"])
def get_work_letter(id):
    user_id, role = require_roles("LandlordPM", "LandlordApprover", "TenantRep")
    wl = _get_wl_or_404(id)
    if role == "TenantRep":
        get_project_tenant_ownership(user_id, wl["project_id"])
    return success_object(wl)


@bp.route("/api/work-letters/<id>/propose", methods=["POST"])
def propose_work_letter(id):
    require_roles("LandlordPM")
    wl = _get_wl_or_404(id)
    proj = store.ti_projects.get(wl["project_id"])
    if not proj:
        raise not_found("TIProject not found")
    if proj["status"] != "WORK_LETTER_NEGOTIATION":
        raise invalid_state("Project must be in WORK_LETTER_NEGOTIATION")
    if wl["status"] not in ("DRAFT", "COUNTERED"):
        raise invalid_state("WorkLetter must be in DRAFT or COUNTERED to propose")

    wl["status"] = "PROPOSED"
    wl["proposed_by"] = "LANDLORD"
    bump_version(wl)
    return success_object(wl)


@bp.route("/api/work-letters/<id>/counter", methods=["POST"])
def counter_work_letter(id):
    user_id, role = require_roles("TenantRep")
    wl = _get_wl_or_404(id)
    proj = store.ti_projects.get(wl["project_id"])
    if not proj:
        raise not_found("TIProject not found")
    if proj["status"] != "WORK_LETTER_NEGOTIATION":
        raise invalid_state("Project must be in WORK_LETTER_NEGOTIATION")

    # TenantRep ownership
    lease = store.leases.get(proj["lease_id"])
    if lease:
        check_tenant_ownership(user_id, lease["id"])

    if wl["status"] != "PROPOSED":
        raise invalid_state("WorkLetter must be in PROPOSED to counter")

    body = request.get_json(silent=True) or {}
    require_fields(body, [
        "scope_description", "allowance_offer_cents", "work_delineation",
        "expected_work_letter_version",
    ])
    if not is_str(body["scope_description"]):
        raise invalid_request("scope_description must be a string")
    if not is_int(body["allowance_offer_cents"]) or body["allowance_offer_cents"] < 0:
        raise invalid_request("allowance_offer_cents must be integer >= 0")
    if body["work_delineation"] not in ("LANDLORD", "TENANT", "SPLIT"):
        raise invalid_request("work_delineation must be LANDLORD, TENANT, or SPLIT")
    if not is_int(body["expected_work_letter_version"]):
        raise invalid_request("expected_work_letter_version must be an integer")

    # OCC check (last in funnel)
    if body["expected_work_letter_version"] != wl["version"]:
        raise stale_version("WorkLetter version has advanced")

    wl["scope_description"] = body["scope_description"]
    wl["allowance_offer_cents"] = body["allowance_offer_cents"]
    wl["work_delineation"] = body["work_delineation"]
    wl["status"] = "COUNTERED"
    wl["round_number"] += 1
    bump_version(wl)
    return success_object(wl)


@bp.route("/api/work-letters/<id>/accept", methods=["POST"])
def accept_work_letter(id):
    user_id, role = require_roles("TenantRep")
    wl = _get_wl_or_404(id)
    proj = store.ti_projects.get(wl["project_id"])
    if not proj:
        raise not_found("TIProject not found")
    if proj["status"] != "WORK_LETTER_NEGOTIATION":
        raise invalid_state("Project must be in WORK_LETTER_NEGOTIATION")

    lease = store.leases.get(proj["lease_id"])
    if lease:
        check_tenant_ownership(user_id, lease["id"])

    if wl["status"] != "PROPOSED":
        raise invalid_state("WorkLetter must be in PROPOSED to accept")

    wl["status"] = "ACCEPTED"
    bump_version(wl)
    return success_object(wl)


@bp.route("/api/work-letters/<id>/execute", methods=["POST"])
def execute_work_letter(id):
    require_roles("LandlordPM")
    wl = _get_wl_or_404(id)
    if wl["status"] != "ACCEPTED":
        raise invalid_state("WorkLetter must be in ACCEPTED to execute")

    proj = store.ti_projects.get(wl["project_id"])
    if not proj:
        raise not_found("TIProject not found")

    # Only one EXECUTED per project
    for other in store.work_letters.values():
        if (other["project_id"] == wl["project_id"]
                and other["id"] != wl["id"]
                and other["status"] == "EXECUTED"):
            raise APIError(ERR_WORK_LETTER_ALREADY_EXECUTED, 409,
                           "Another WorkLetter of this project is already EXECUTED")

    wl["status"] = "EXECUTED"
    bump_version(wl)

    # Set allowance pool on project
    proj["allowance_total_cents"] = wl["allowance_offer_cents"]
    proj["allowance_remaining_cents"] = (
        proj["allowance_total_cents"] - proj["allowance_consumed_cents"]
    )
    bump_version(proj)

    return success_object(wl)


@bp.route("/api/work-letters/<id>/withdraw", methods=["POST"])
def withdraw_work_letter(id):
    require_roles("LandlordPM")
    wl = _get_wl_or_404(id)
    if wl["status"] not in ("DRAFT", "PROPOSED", "COUNTERED"):
        raise invalid_state("WorkLetter cannot be withdrawn from current state")
    wl["status"] = "WITHDRAWN"
    bump_version(wl)
    return success_object(wl)
