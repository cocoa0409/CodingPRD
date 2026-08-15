"""AidOffer endpoints."""
from flask import Blueprint, request

from db import store, new_id, now_iso
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_INVALID_STATE,
    ERR_NOT_RESOURCE_OWNER, ERR_STALE_VERSION, ERR_AID_ALREADY_ACCEPTED,
    ERR_NO_AID_ELIGIBILITY, ERR_SCHOLARSHIP_BUDGET_EXCEEDED, ERR_FORBIDDEN,
)
from middleware import require_roles, get_auth
from response import success_object, success_list
from services.derived import (
    compute_aid_award, recompute_program, recompute_application_aid_fields,
    recompute_melt_risk,
)
from services.serializers import serialize_aid_offer, touch

bp = Blueprint("aid_offers", __name__, url_prefix="/enrollment/aid-offers")


def _get_offer_or_404(oid):
    o = store.aid_offers.get(oid)
    if not o:
        raise ApiError(ERR_NOT_FOUND, 404, "Aid offer not found")
    return o


@bp.route("", methods=["POST"])
def create_aid_offer():
    require_roles("FinancialAidOfficer")
    body = request.get_json(silent=True) or {}
    application_id = body.get("application_id")
    fund_type = body.get("fund_type")
    expected_version = body.get("expected_application_version")

    if application_id is None or application_id not in store.applications:
        raise ApiError(ERR_NOT_FOUND, 404, "application_id not found")
    if fund_type is None or fund_type not in ("MERIT", "NEED_BASED"):
        raise ApiError(ERR_INVALID_REQUEST, 400, "fund_type required (MERIT | NEED_BASED)")
    if expected_version is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "expected_application_version required")

    app = store.applications[application_id]
    if expected_version != app["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       f"expected_application_version {expected_version} != current {app['version']}")

    program = store.programs.get(app["program_id"])

    # Exclusivity: no ACCEPTED offer on the application
    for o in store.aid_offers.values():
        if o["application_id"] == application_id and o["status"] == "ACCEPTED":
            raise ApiError(ERR_AID_ALREADY_ACCEPTED, 409,
                           "Application already has an ACCEPTED offer")

    # Compute award
    recompute_program(program)
    base, award = compute_aid_award(app, program, fund_type)
    if base == 0:
        raise ApiError(ERR_NO_AID_ELIGIBILITY, 422, "Aid eligibility base is zero")
    if program["scholarship_available_cents"] == 0:
        raise ApiError(ERR_SCHOLARSHIP_BUDGET_EXCEEDED, 409,
                       "scholarship_available_cents is zero")

    # Supersede any OFFERED offer on the same application
    for o in store.aid_offers.values():
        if o["application_id"] == application_id and o["status"] == "OFFERED":
            o["status"] = "SUPERSEDED"
            touch(o)

    now = now_iso()
    offer = {
        "id": new_id(),
        "application_id": application_id,
        "fund_type": fund_type,
        "amount_cents": award,
        "status": "OFFERED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.aid_offers[offer["id"]] = offer

    recompute_program(program)
    recompute_application_aid_fields(app)
    recompute_melt_risk(app)
    touch(app)
    touch(program)
    return success_object(serialize_aid_offer(offer), status=201)


@bp.route("/<aidOfferId>", methods=["GET"])
def get_aid_offer(aidOfferId):
    user_id, role = get_auth()
    if role not in ("SystemAdmin", "EnrollmentManager", "AdmissionsOfficer",
                    "FinancialAidOfficer", "Applicant"):
        raise ApiError(ERR_FORBIDDEN, 403, "Role not permitted")
    o = _get_offer_or_404(aidOfferId)
    if role == "Applicant":
        app = store.applications.get(o["application_id"])
        if not app or user_id != app["applicant_id"]:
            raise ApiError(ERR_NOT_RESOURCE_OWNER, 403, "Not resource owner")
    return success_object(serialize_aid_offer(o))


@bp.route("", methods=["GET"])
def list_aid_offers():
    require_roles("SystemAdmin", "EnrollmentManager", "AdmissionsOfficer", "FinancialAidOfficer")
    application_id = request.args.get("application_id")
    status = request.args.get("status")
    try:
        limit = int(request.args.get("limit", 10))
        offset = int(request.args.get("offset", 0))
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, 400, "limit/offset must be integers")
    limit = max(1, min(100, limit))
    offset = max(0, offset)

    items = list(store.aid_offers.values())
    if application_id:
        items = [o for o in items if o["application_id"] == application_id]
    if status:
        items = [o for o in items if o["status"] == status]
    items.sort(key=lambda o: (o["created_at"], o["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_aid_offer(o) for o in page], limit, offset, total)


ALLOWED = {
    "OFFERED": {"ACCEPTED", "DECLINED", "REVISION_REQUESTED", "REVOKED", "SUPERSEDED"},
    "REVISION_REQUESTED": {"OFFERED", "REVOKED"},
    "ACCEPTED": {"REVOKED"},
    "DECLINED": set(),
    "REVOKED": set(),
    "SUPERSEDED": set(),
}


@bp.route("/<aidOfferId>/transition", methods=["POST"])
def transition_aid_offer(aidOfferId):
    user_id, role = get_auth()
    if role not in ("FinancialAidOfficer", "Applicant"):
        raise ApiError(ERR_FORBIDDEN, 403, "Role not permitted")
    o = _get_offer_or_404(aidOfferId)
    body = request.get_json(silent=True) or {}
    to_status = body.get("to_status")
    if not to_status:
        raise ApiError(ERR_INVALID_REQUEST, 400, "to_status required")

    app = store.applications.get(o["application_id"])
    program = store.programs.get(app["program_id"]) if app else None

    # Role gating
    if to_status in ("ACCEPTED", "DECLINED", "REVISION_REQUESTED"):
        if role != "Applicant":
            raise ApiError(ERR_FORBIDDEN, 403,
                           "Only Applicant may accept/decline/request revision")
        if not app or user_id != app["applicant_id"]:
            raise ApiError(ERR_NOT_RESOURCE_OWNER, 403, "Not resource owner")
    elif to_status in ("OFFERED", "REVOKED"):
        if role != "FinancialAidOfficer":
            raise ApiError(ERR_FORBIDDEN, 403,
                           "Only FinancialAidOfficer may re-offer or revoke")

    if to_status not in ALLOWED.get(o["status"], set()):
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"Cannot transition aid offer {o['status']} -> {to_status}")

    # Re-offer flow: recompute against current available
    if o["status"] == "REVISION_REQUESTED" and to_status == "OFFERED":
        recompute_program(program)
        base, award = compute_aid_award(app, program, o["fund_type"])
        if base == 0:
            raise ApiError(ERR_NO_AID_ELIGIBILITY, 422, "Aid eligibility base is zero")
        if program["scholarship_available_cents"] == 0:
            raise ApiError(ERR_SCHOLARSHIP_BUDGET_EXCEEDED, 409,
                           "scholarship_available_cents is zero")
        o["amount_cents"] = award

    o["status"] = to_status
    touch(o)

    if program:
        recompute_program(program)
        touch(program)
    if app:
        recompute_application_aid_fields(app)
        recompute_melt_risk(app)
        touch(app)
    return success_object(serialize_aid_offer(o))
