"""Appraisal routes — includes the LTV-recompute cascade."""
from __future__ import annotations

from decimal import Decimal

from flask import Blueprint, request

import db
import response
from errors import ApiError, ERR_APPLICANT_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE
from middleware import require_auth
from services import calculations
from services.common import (
    bump,
    get_json_body,
    new_common_fields,
    paginate,
    parse_pagination,
    require_int,
    require_str,
    sorted_by_created_at,
)
from services.lookup import get_subresource_or_404
from routes.loan_applications import cascade_appraisal_ltv

bp = Blueprint("appraisals", __name__)


def appraisal_to_dict(ap: dict) -> dict:
    return {
        "id": ap["id"],
        "application_id": ap["application_id"],
        "appraised_value_cents": ap.get("appraised_value_cents"),
        "status": ap["status"],
        "reconsideration_note": ap.get("reconsideration_note"),
        "created_at": ap["created_at"],
        "updated_at": ap["updated_at"],
        "version": ap["version"],
    }


@bp.post("/appraisals")
@require_auth(roles=["LoanOfficer"])
def create_appraisal():
    body = get_json_body()
    application_id = require_str(body, "application_id")
    if application_id not in db.loan_applications:
        raise ApiError(ERR_APPLICANT_NOT_FOUND, "application_id does not refer to a known loan application.")
    with db.lock:
        ap = {
            **new_common_fields(),
            "application_id": application_id,
            "appraised_value_cents": None,
            "status": "ORDERED",
            "reconsideration_note": None,
        }
        db.appraisals[ap["id"]] = ap
    return response.ok(appraisal_to_dict(ap), status=201)


@bp.get("/appraisals/<ap_id>")
@require_auth(roles=["LoanOfficer", "Underwriter", "Appraiser"])
def read_appraisal(ap_id: str):
    ap = get_subresource_or_404(db.appraisals, ap_id)
    return response.ok(appraisal_to_dict(ap))


@bp.get("/appraisals")
@require_auth(roles=["LoanOfficer", "Underwriter", "Appraiser"])
def list_appraisals():
    limit, offset = parse_pagination()
    application_id = request.args.get("application_id")
    status = request.args.get("status")
    items = list(db.appraisals.values())
    if application_id is not None:
        items = [x for x in items if x["application_id"] == application_id]
    if status is not None:
        items = [x for x in items if x["status"] == status]
    items = sorted_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return response.list_ok([appraisal_to_dict(x) for x in page], limit, offset, total)


def _parent_app_non_terminal(app_id: str) -> dict:
    la = db.loan_applications.get(app_id)
    if la is None:
        raise ApiError(ERR_INVALID_STATE, "Parent application no longer exists.")
    if la["status"] not in ("PREQUALIFIED", "UNDER_REVIEW"):
        raise ApiError(ERR_INVALID_STATE, "Parent application not in PREQUALIFIED/UNDER_REVIEW.")
    return la


@bp.post("/appraisals/<ap_id>/complete")
@require_auth(roles=["Appraiser"])
def complete_appraisal(ap_id: str):
    ap = get_subresource_or_404(db.appraisals, ap_id)
    body = get_json_body()
    appraised_value_cents = body.get("appraised_value_cents")
    if not isinstance(appraised_value_cents, int) or isinstance(appraised_value_cents, bool) or appraised_value_cents <= 0:
        raise ApiError(ERR_INVALID_REQUEST, "appraised_value_cents must be a positive integer.")
    with db.lock:
        if ap["status"] != "ORDERED":
            raise ApiError(ERR_INVALID_STATE, "Appraisal is not in ORDERED.")
        la = _parent_app_non_terminal(ap["application_id"])
        ap["appraised_value_cents"] = appraised_value_cents
        ap["status"] = "COMPLETED"
        bump(ap)
        # Recompute LTV (variant_final).
        new_ltv = calculations.compute_ltv_final(la, appraised_value_cents)
        bump(la)  # +1 for the recomputation
        cascade_appraisal_ltv(la, new_ltv)  # may add another +1 + cancel lock
    return response.ok(appraisal_to_dict(ap))


@bp.post("/appraisals/<ap_id>/reconsider")
@require_auth(roles=["LoanOfficer"])
def reconsider_appraisal(ap_id: str):
    ap = get_subresource_or_404(db.appraisals, ap_id)
    body = get_json_body()
    reconsideration_note = require_str(body, "reconsideration_note")
    new_av = body.get("new_appraised_value_cents")
    if not isinstance(new_av, int) or isinstance(new_av, bool) or new_av <= 0:
        raise ApiError(ERR_INVALID_REQUEST, "new_appraised_value_cents must be a positive integer.")
    with db.lock:
        if ap["status"] != "COMPLETED":
            raise ApiError(ERR_INVALID_STATE, "Appraisal is not in COMPLETED.")
        la = _parent_app_non_terminal(ap["application_id"])
        ap["appraised_value_cents"] = new_av
        ap["reconsideration_note"] = reconsideration_note
        ap["status"] = "RECONSIDERED"
        bump(ap)
        new_ltv = calculations.compute_ltv_final(la, new_av)
        bump(la)
        cascade_appraisal_ltv(la, new_ltv)
    return response.ok(appraisal_to_dict(ap))


@bp.post("/appraisals/<ap_id>/confirm-reconsideration")
@require_auth(roles=["Appraiser"])
def confirm_reconsideration(ap_id: str):
    ap = get_subresource_or_404(db.appraisals, ap_id)
    with db.lock:
        if ap["status"] != "RECONSIDERED":
            raise ApiError(ERR_INVALID_STATE, "Appraisal is not in RECONSIDERED.")
        ap["status"] = "COMPLETED"
        bump(ap)
    return response.ok(appraisal_to_dict(ap))
