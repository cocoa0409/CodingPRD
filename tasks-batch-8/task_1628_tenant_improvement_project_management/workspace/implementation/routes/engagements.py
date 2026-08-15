"""ContractorEngagement endpoints."""

from flask import Blueprint, request

from db import store
from middleware import require_roles, check_contractor_ownership, check_tenant_ownership, get_project_tenant_ownership
from response import success_object, success_created, success_list
from errors import (
    not_found, invalid_request, invalid_state, APIError,
    ERR_BUILDING_RULES_NOT_ACKNOWLEDGED, ERR_INSURANCE_EXPIRED,
    ERR_CONTRACTOR_NOT_QUALIFIED, ERR_INVALID_STATE,
)
from services.util import (
    make_common_fields, bump_version, get_pagination_params, paginate,
    require_fields, is_str, parse_iso8601, logical_clock_dt,
)

bp = Blueprint("engagements", __name__)


def _get_eng_or_404(eid):
    e = store.contractor_engagements.get(eid)
    if not e:
        raise not_found("ContractorEngagement not found")
    return e


@bp.route("/api/ti-projects/<id>/contractor-engagements", methods=["POST"])
def create_engagement(id):
    require_roles("LandlordPM")
    proj = store.ti_projects.get(id)
    if not proj:
        raise not_found("TIProject not found")

    body = request.get_json(silent=True) or {}
    require_fields(body, ["contractor_id", "scope_note"])
    if not is_str(body["contractor_id"]):
        raise invalid_request("contractor_id must be a string")
    if not is_str(body["scope_note"]):
        raise invalid_request("scope_note must be a string")

    contractor = store.contractors.get(body["contractor_id"])
    if not contractor:
        raise not_found("Contractor not found")

    rec = make_common_fields()
    rec.update({
        "project_id": id,
        "contractor_id": body["contractor_id"],
        "building_rules_acknowledged": False,
        "scope_note": body["scope_note"],
        "status": "PROPOSED",
    })
    store.contractor_engagements[rec["id"]] = rec
    return success_created(rec)


@bp.route("/api/ti-projects/<id>/contractor-engagements", methods=["GET"])
def list_project_engagements(id):
    user_id, role = require_roles("LandlordPM", "LandlordApprover", "TenantRep", "ContractorRep")
    proj = store.ti_projects.get(id)
    if not proj:
        raise not_found("TIProject not found")
    if role == "TenantRep":
        check_tenant_ownership(user_id, proj["lease_id"])
    limit, offset = get_pagination_params()
    items = [e for e in store.contractor_engagements.values() if e["project_id"] == id]
    if role == "ContractorRep":
        items = [e for e in items if e["contractor_id"] == user_id]
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/api/contractor-engagements/<id>", methods=["GET"])
def get_engagement(id):
    user_id, role = require_roles("LandlordPM", "LandlordApprover", "ContractorRep")
    eng = _get_eng_or_404(id)
    if role == "ContractorRep":
        check_contractor_ownership(user_id, eng["id"])
    return success_object(eng)


@bp.route("/api/contractor-engagements/<id>/acknowledge-rules", methods=["POST"])
def acknowledge_rules(id):
    user_id, role = require_roles("ContractorRep")
    eng = _get_eng_or_404(id)
    check_contractor_ownership(user_id, eng["id"])
    eng["building_rules_acknowledged"] = True
    bump_version(eng)
    return success_object(eng)


@bp.route("/api/contractor-engagements/<id>/approve", methods=["POST"])
def approve_engagement(id):
    require_roles("LandlordPM")
    eng = _get_eng_or_404(id)
    if eng["status"] != "PROPOSED":
        raise invalid_state("Engagement must be in PROPOSED")

    contractor = store.contractors.get(eng["contractor_id"])
    if not contractor:
        raise not_found("Contractor not found")

    # §2.7 order: building rules -> insurance -> qualification
    if not eng["building_rules_acknowledged"]:
        raise APIError(ERR_BUILDING_RULES_NOT_ACKNOWLEDGED, 422,
                       "Building rules not yet acknowledged")
    exp = parse_iso8601(contractor["insurance_expiry_date"])
    if exp <= logical_clock_dt():
        raise APIError(ERR_INSURANCE_EXPIRED, 422, "Contractor insurance is expired")
    if contractor["qualification_status"] != "QUALIFIED":
        raise APIError(ERR_CONTRACTOR_NOT_QUALIFIED, 422,
                       "Contractor is not QUALIFIED")

    eng["status"] = "APPROVED"
    bump_version(eng)
    return success_object(eng)


@bp.route("/api/contractor-engagements/<id>/activate", methods=["POST"])
def activate_engagement(id):
    require_roles("LandlordPM")
    eng = _get_eng_or_404(id)
    if eng["status"] != "APPROVED":
        raise invalid_state("Engagement must be in APPROVED")
    proj = store.ti_projects.get(eng["project_id"])
    if not proj:
        raise not_found("TIProject not found")
    if proj["status"] not in ("PRE_CONSTRUCTION", "CONSTRUCTION"):
        raise invalid_state("Project must be in PRE_CONSTRUCTION or CONSTRUCTION")
    eng["status"] = "ACTIVE"
    bump_version(eng)
    return success_object(eng)


@bp.route("/api/contractor-engagements/<id>/suspend", methods=["POST"])
def suspend_engagement(id):
    require_roles("LandlordPM")
    eng = _get_eng_or_404(id)
    if eng["status"] != "ACTIVE":
        raise invalid_state("Engagement must be in ACTIVE")
    eng["status"] = "SUSPENDED"
    bump_version(eng)
    return success_object(eng)


@bp.route("/api/contractor-engagements/<id>/reinstate", methods=["POST"])
def reinstate_engagement(id):
    require_roles("LandlordPM")
    eng = _get_eng_or_404(id)
    if eng["status"] != "SUSPENDED":
        raise invalid_state("Engagement must be in SUSPENDED")
    contractor = store.contractors.get(eng["contractor_id"])
    if not contractor:
        raise not_found("Contractor not found")
    if contractor["qualification_status"] != "QUALIFIED":
        raise APIError(ERR_CONTRACTOR_NOT_QUALIFIED, 422,
                       "Contractor is not QUALIFIED")
    eng["status"] = "ACTIVE"
    bump_version(eng)
    return success_object(eng)


@bp.route("/api/contractor-engagements/<id>/terminate", methods=["POST"])
def terminate_engagement(id):
    require_roles("LandlordPM")
    eng = _get_eng_or_404(id)
    if eng["status"] not in ("PROPOSED", "APPROVED", "ACTIVE"):
        raise invalid_state("Engagement cannot be terminated from current state")

    # Blocked while any CONFIRMED milestone exists
    for m in store.schedule_milestones.values():
        if m["engagement_id"] == id and m["status"] == "CONFIRMED":
            raise APIError(ERR_INVALID_STATE, 409,
                           "Cannot terminate engagement with CONFIRMED milestones")

    # Terminating ACTIVE cancels PLANNED milestones
    if eng["status"] == "ACTIVE":
        for m in store.schedule_milestones.values():
            if m["engagement_id"] == id and m["status"] == "PLANNED":
                m["status"] = "CANCELLED"
                bump_version(m)

    eng["status"] = "TERMINATED"
    bump_version(eng)
    return success_object(eng)


@bp.route("/api/contractor-engagements/<id>/complete", methods=["POST"])
def complete_engagement(id):
    require_roles("LandlordPM")
    eng = _get_eng_or_404(id)
    if eng["status"] != "ACTIVE":
        raise invalid_state("Engagement must be in ACTIVE")
    proj = store.ti_projects.get(eng["project_id"])
    if not proj:
        raise not_found("TIProject not found")
    if proj["status"] not in ("PUNCH", "CLOSEOUT"):
        raise invalid_state("Project must be in PUNCH or CLOSEOUT")

    # All milestones terminal
    for m in store.schedule_milestones.values():
        if m["engagement_id"] == id and m["status"] not in ("COMPLETED", "CANCELLED"):
            raise invalid_state("All milestones must be terminal")

    # All assigned punch items VERIFIED
    for p in store.punch_items.values():
        if p["assigned_engagement_id"] == id and p["status"] != "VERIFIED":
            raise invalid_state("All assigned punch items must be VERIFIED")

    eng["status"] = "COMPLETED"
    bump_version(eng)
    return success_object(eng)
