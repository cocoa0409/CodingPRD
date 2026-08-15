"""DisbursementRequest and LienWaiver endpoints."""

from flask import Blueprint, request

from db import store
from middleware import (
    require_roles, check_contractor_ownership, check_tenant_ownership,
    get_project_tenant_ownership,
)
from response import success_object, success_created, success_list
from errors import (
    not_found, invalid_request, invalid_state, stale_version, APIError,
    ERR_DISBURSEMENT_PERIOD_IN_FUTURE, ERR_NO_ACTIVE_ENGAGEMENT,
    ERR_PROJECT_NOT_OPEN, ERR_LIEN_WAIVER_MISSING,
    ERR_LIEN_WAIVER_AMOUNT_MISMATCH, ERR_SEGREGATION_OF_DUTIES,
    ERR_APPROVAL_EXCEEDS_REQUEST, ERR_DRAW_EXCEEDS_REMAINING,
)
from services.util import (
    make_common_fields, bump_version, get_pagination_params, paginate,
    require_fields, is_int, is_str, is_bool, parse_iso8601, to_iso_z,
    logical_clock_dt,
)
from services import calc

bp = Blueprint("disbursements", __name__)


def _get_draw_or_404(did):
    d = store.disbursement_requests.get(did)
    if not d:
        raise not_found("DisbursementRequest not found")
    return d


def _next_draw_number(project_id):
    existing = [
        d for d in store.disbursement_requests.values() if d["project_id"] == project_id
    ]
    return len(existing) + 1


# ---------------------------------------------------------------------------
# DisbursementRequest CRUD + lifecycle
# ---------------------------------------------------------------------------

@bp.route("/api/ti-projects/<id>/disbursement-requests", methods=["POST"])
def create_disbursement(id):
    user_id, role = require_roles("ContractorRep")
    proj = store.ti_projects.get(id)
    if not proj:
        raise not_found("TIProject not found")

    body = request.get_json(silent=True) or {}
    require_fields(body, [
        "period_end_date", "requested_amount_cents", "expected_ti_project_version",
    ])
    try:
        ped = parse_iso8601(body["period_end_date"])
    except Exception:
        raise invalid_request("period_end_date must be valid ISO8601")
    if not is_int(body["requested_amount_cents"]) or body["requested_amount_cents"] <= 0:
        raise invalid_request("requested_amount_cents must be integer > 0")
    if not is_int(body["expected_ti_project_version"]):
        raise invalid_request("expected_ti_project_version must be an integer")
    is_final = body.get("is_final_draw", False)
    if not is_bool(is_final):
        raise invalid_request("is_final_draw must be a boolean")

    # OCC check (last in funnel)
    if body["expected_ti_project_version"] != proj["version"]:
        raise stale_version("TIProject version has advanced")

    rec = make_common_fields()
    rec.update({
        "project_id": id,
        "draw_number": _next_draw_number(id),
        "period_end_date": to_iso_z(ped),
        "requested_amount_cents": body["requested_amount_cents"],
        "is_final_draw": is_final,
        "approved_amount_cents": 0,
        "retainage_held_cents": 0,
        "net_payment_cents": 0,
        "approved_by_user_id": None,
        "status": "DRAFT",
    })
    store.disbursement_requests[rec["id"]] = rec

    # Creating the draft advances the project's version
    bump_version(proj)
    return success_created(rec)


@bp.route("/api/ti-projects/<id>/disbursement-requests", methods=["GET"])
def list_disbursements(id):
    user_id, role = require_roles(
        "LandlordPM", "LandlordApprover", "TenantRep", "ContractorRep"
    )
    proj = store.ti_projects.get(id)
    if not proj:
        raise not_found("TIProject not found")
    if role == "TenantRep":
        check_tenant_ownership(user_id, proj["lease_id"])
    limit, offset = get_pagination_params()
    items = [d for d in store.disbursement_requests.values() if d["project_id"] == id]
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/api/disbursement-requests/<id>", methods=["GET"])
def get_disbursement(id):
    user_id, role = require_roles(
        "LandlordPM", "LandlordApprover", "TenantRep", "ContractorRep"
    )
    d = _get_draw_or_404(id)
    if role == "TenantRep":
        get_project_tenant_ownership(user_id, d["project_id"])
    return success_object(d)


@bp.route("/api/disbursement-requests/<id>/submit", methods=["POST"])
def submit_disbursement(id):
    user_id, role = require_roles("ContractorRep")
    d = _get_draw_or_404(id)
    if d["status"] != "DRAFT":
        raise invalid_state("DisbursementRequest must be in DRAFT to submit")

    proj = store.ti_projects.get(d["project_id"])
    if not proj:
        raise not_found("TIProject not found")

    # §2.7 order: state gate -> temporal -> engagement -> posture
    if proj["status"] not in ("CONSTRUCTION", "PUNCH"):
        raise invalid_state("Project must be in CONSTRUCTION or PUNCH")

    clock = logical_clock_dt()
    ped = parse_iso8601(d["period_end_date"])
    if ped > clock:
        raise APIError(ERR_DISBURSEMENT_PERIOD_IN_FUTURE, 422,
                       "period_end_date must not be after the current logical clock")

    has_active = any(
        e for e in store.contractor_engagements.values()
        if e["project_id"] == d["project_id"] and e["status"] == "ACTIVE"
    )
    if not has_active:
        raise APIError(ERR_NO_ACTIVE_ENGAGEMENT, 422,
                       "At least one ACTIVE ContractorEngagement is required")

    if proj["posture"] != "OPEN":
        raise APIError(ERR_PROJECT_NOT_OPEN, 422,
                       "Project posture is not OPEN")

    d["status"] = "SUBMITTED"
    bump_version(d)

    # Refresh provisional consumption
    calc.recompute_allowance(proj)
    calc.recompute_posture(proj)

    return success_object(d)


@bp.route("/api/disbursement-requests/<id>/approve", methods=["POST"])
def approve_disbursement(id):
    user_id, role = require_roles("LandlordApprover")
    d = _get_draw_or_404(id)
    if d["status"] != "SUBMITTED":
        raise invalid_state("DisbursementRequest must be in SUBMITTED to approve")

    proj = store.ti_projects.get(d["project_id"])
    if not proj:
        raise not_found("TIProject not found")

    body = request.get_json(silent=True) or {}
    require_fields(body, ["approved_amount_cents"])
    if not is_int(body["approved_amount_cents"]) or body["approved_amount_cents"] < 0:
        raise invalid_request("approved_amount_cents must be integer >= 0")
    approved_amount = body["approved_amount_cents"]

    # §2.7 ladder: waiver exists -> waiver amount -> SoD -> posture -> exceeds request -> exceeds remaining

    # 1. At least one VERIFIED waiver
    waivers = [
        w for w in store.lien_waivers.values()
        if w["disbursement_id"] == id
    ]
    verified = [w for w in waivers if w["status"] == "VERIFIED"]
    if not verified:
        raise APIError(ERR_LIEN_WAIVER_MISSING, 422,
                       "No VERIFIED lien waiver attached to this draw")

    # 2. Verified waiver amount matches requested amount
    if not any(w["amount_cents"] == d["requested_amount_cents"] for w in verified):
        raise APIError(ERR_LIEN_WAIVER_AMOUNT_MISMATCH, 422,
                       "VERIFIED lien waiver amount does not equal requested_amount_cents")

    # 3. Segregation of duties
    for co in store.change_orders.values():
        if (co["project_id"] == d["project_id"]
                and co["status"] == "APPROVED"
                and co.get("approved_by_user_id") == user_id):
            raise APIError(ERR_SEGREGATION_OF_DUTIES, 422,
                           "Approver previously approved a ChangeOrder on this project")

    # 4. Posture must be OPEN
    if proj["posture"] != "OPEN":
        raise APIError(ERR_PROJECT_NOT_OPEN, 422,
                       "Project posture is not OPEN")

    # 5. approved <= requested
    if approved_amount > d["requested_amount_cents"]:
        raise APIError(ERR_APPROVAL_EXCEEDS_REQUEST, 422,
                       "approved_amount_cents exceeds requested_amount_cents")

    # 6. approved <= allowance_remaining
    if approved_amount > proj["allowance_remaining_cents"]:
        raise APIError(ERR_DRAW_EXCEEDS_REMAINING, 422,
                       "approved_amount_cents exceeds allowance_remaining_cents")

    # Success — set fields and run retainage calc
    d["approved_amount_cents"] = approved_amount
    d["approved_by_user_id"] = user_id
    calc.compute_retainage(d, proj)
    d["status"] = "APPROVED"
    bump_version(d)

    # Recompute project aggregates
    calc.recompute_allowance(proj)
    calc.recompute_retainage(proj)
    calc.recompute_posture(proj)
    bump_version(proj)

    return success_object(d)


@bp.route("/api/disbursement-requests/<id>/pay", methods=["POST"])
def pay_disbursement(id):
    require_roles("LandlordPM")
    d = _get_draw_or_404(id)
    if d["status"] != "APPROVED":
        raise invalid_state("DisbursementRequest must be in APPROVED to pay")

    proj = store.ti_projects.get(d["project_id"])
    if not proj:
        raise not_found("TIProject not found")

    d["status"] = "PAID"

    if d["is_final_draw"]:
        # PRD 3.6: paying the final draw releases everything still held — the
        # project's entire retainage_held_cents moves to retainage_released_cents
        # and the held balance is zeroed. The escrow is the sum of the per-draw
        # withholdings, so each contributing draw's held amount is released with
        # it; otherwise the recompute below would re-derive the stale balance.
        proj["retainage_released_cents"] += proj["retainage_held_cents"]
        proj["retainage_held_cents"] = 0
        for other in store.disbursement_requests.values():
            if (
                other["project_id"] == proj["id"]
                and other["status"] in ("APPROVED", "PAID")
                and other["retainage_held_cents"]
            ):
                other["retainage_held_cents"] = 0

    bump_version(d)

    # Recompute project aggregates
    calc.recompute_allowance(proj)
    calc.recompute_retainage(proj)
    calc.recompute_posture(proj)
    bump_version(proj)

    return success_object(d)


@bp.route("/api/disbursement-requests/<id>/reject", methods=["POST"])
def reject_disbursement(id):
    require_roles("LandlordApprover")
    d = _get_draw_or_404(id)
    if d["status"] != "SUBMITTED":
        raise invalid_state("DisbursementRequest must be in SUBMITTED to reject")
    d["status"] = "REJECTED"
    bump_version(d)

    proj = store.ti_projects.get(d["project_id"])
    if proj:
        calc.recompute_allowance(proj)
        calc.recompute_posture(proj)

    return success_object(d)


@bp.route("/api/disbursement-requests/<id>/void", methods=["POST"])
def void_disbursement(id):
    user_id, role = require_roles("ContractorRep", "LandlordApprover")
    d = _get_draw_or_404(id)

    if role == "ContractorRep":
        # Contractor can only void DRAFT
        if d["status"] != "DRAFT":
            raise invalid_state("ContractorRep can only void DRAFT draws")
        d["status"] = "VOIDED"
        bump_version(d)
    else:
        # LandlordApprover can void APPROVED (compensation path)
        if d["status"] != "APPROVED":
            raise invalid_state("LandlordApprover can only void APPROVED draws")
        d["status"] = "VOIDED"
        bump_version(d)

        proj = store.ti_projects.get(d["project_id"])
        if proj:
            calc.recompute_allowance(proj)
            calc.recompute_retainage(proj)
            calc.recompute_posture(proj)
            bump_version(proj)

    return success_object(d)


# ---------------------------------------------------------------------------
# LienWaiver endpoints
# ---------------------------------------------------------------------------

@bp.route("/api/disbursement-requests/<id>/lien-waivers", methods=["POST"])
def create_lien_waiver(id):
    user_id, role = require_roles("ContractorRep")
    d = _get_draw_or_404(id)

    body = request.get_json(silent=True) or {}
    require_fields(body, ["contractor_id", "waiver_type", "amount_cents"])
    if not is_str(body["contractor_id"]):
        raise invalid_request("contractor_id must be a string")
    if body["waiver_type"] not in (
        "CONDITIONAL_PROGRESS", "UNCONDITIONAL_PROGRESS",
        "CONDITIONAL_FINAL", "UNCONDITIONAL_FINAL",
    ):
        raise invalid_request("Invalid waiver_type")
    if not is_int(body["amount_cents"]) or body["amount_cents"] <= 0:
        raise invalid_request("amount_cents must be integer > 0")

    # Contractor must exist
    contractor = store.contractors.get(body["contractor_id"])
    if not contractor:
        raise not_found("Contractor not found")

    # ContractorRep scope: the waiving contractor must match X-User-ID
    if body["contractor_id"] != user_id:
        from errors import ERR_FORBIDDEN_SCOPE
        raise APIError(ERR_FORBIDDEN_SCOPE, 403,
                       "ContractorRep may only file waivers for own contractor")

    rec = make_common_fields()
    rec.update({
        "disbursement_id": id,
        "contractor_id": body["contractor_id"],
        "waiver_type": body["waiver_type"],
        "amount_cents": body["amount_cents"],
        "status": "PENDING",
    })
    store.lien_waivers[rec["id"]] = rec
    return success_created(rec)


@bp.route("/api/disbursement-requests/<id>/lien-waivers", methods=["GET"])
def list_draw_waivers(id):
    user_id, role = require_roles(
        "LandlordPM", "LandlordApprover", "TenantRep", "ContractorRep"
    )
    d = _get_draw_or_404(id)
    if role == "TenantRep":
        get_project_tenant_ownership(user_id, d["project_id"])
    if role == "ContractorRep":
        # Scope: only show waivers from own contractor
        limit, offset = get_pagination_params()
        items = [
            w for w in store.lien_waivers.values()
            if w["disbursement_id"] == id and w["contractor_id"] == user_id
        ]
        page, total = paginate(items, limit, offset)
        return success_list(page, limit, offset, total)
    limit, offset = get_pagination_params()
    items = [w for w in store.lien_waivers.values() if w["disbursement_id"] == id]
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/api/lien-waivers/<id>", methods=["GET"])
def get_lien_waiver(id):
    user_id, role = require_roles("LandlordPM", "LandlordApprover", "ContractorRep")
    w = store.lien_waivers.get(id)
    if not w:
        raise not_found("LienWaiver not found")
    if role == "ContractorRep" and w["contractor_id"] != user_id:
        from errors import ERR_FORBIDDEN_SCOPE
        raise APIError(ERR_FORBIDDEN_SCOPE, 403,
                       "ContractorRep may only view own waivers")
    return success_object(w)


@bp.route("/api/lien-waivers/<id>/verify", methods=["POST"])
def verify_waiver(id):
    require_roles("LandlordPM")
    w = store.lien_waivers.get(id)
    if not w:
        raise not_found("LienWaiver not found")
    if w["status"] != "PENDING":
        raise invalid_state("LienWaiver must be in PENDING to verify")
    d = store.disbursement_requests.get(w["disbursement_id"])
    if not d or d["status"] not in ("SUBMITTED", "ON_HOLD"):
        raise invalid_state("Draw must be in SUBMITTED or ON_HOLD for waiver verification")
    w["status"] = "VERIFIED"
    bump_version(w)
    return success_object(w)


@bp.route("/api/lien-waivers/<id>/reject", methods=["POST"])
def reject_waiver(id):
    require_roles("LandlordPM")
    w = store.lien_waivers.get(id)
    if not w:
        raise not_found("LienWaiver not found")
    if w["status"] != "PENDING":
        raise invalid_state("LienWaiver must be in PENDING to reject")
    d = store.disbursement_requests.get(w["disbursement_id"])
    if not d or d["status"] not in ("SUBMITTED", "ON_HOLD"):
        raise invalid_state("Draw must be in SUBMITTED or ON_HOLD for waiver rejection")
    w["status"] = "REJECTED"
    bump_version(w)
    return success_object(w)
