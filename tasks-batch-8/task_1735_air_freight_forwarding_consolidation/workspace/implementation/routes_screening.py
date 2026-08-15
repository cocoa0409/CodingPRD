"""Screening record resolution with segregation of duties (PRD §3.3)."""
from flask import Blueprint, g

import services as svc
from errors import ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_SEGREGATION_OF_DUTIES
from middleware import get_body, opt_str, req_enum, require_roles
from response import ok

bp = Blueprint("screening_records", __name__)


@bp.post("/screening-records/<rid>/resolve")
@require_roles("ComplianceOfficer")
def resolve_screening(rid):
    rec = svc.get_screening(rid)
    # State gate (priority 5): only PENDING records can be resolved.
    if rec.result != "PENDING":
        raise ApiError(
            ERR_INVALID_STATE,
            f"Screening record result is {rec.result}; only PENDING can be resolved.",
            409,
        )
    hwb = svc.get_hwb(rec.hwb_id)
    # Segregation of duties (priority 7): resolver must differ from submitter.
    if hwb.submitted_by_user_id is not None and g.user_id == hwb.submitted_by_user_id:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES,
            "The resolving officer must differ from the submitting user.",
            403,
        )
    body = get_body()
    outcome = req_enum(body, "outcome", ("CLEARED", "REJECTED"))
    rejection_reason = opt_str(body, "rejection_reason", None)
    if outcome == "REJECTED" and (rejection_reason is None or rejection_reason == ""):
        raise ApiError(
            ERR_INVALID_REQUEST,
            "Field 'rejection_reason' is required when outcome is REJECTED.",
            400,
        )
    rec.result = outcome
    rec.rejection_reason = rejection_reason if outcome == "REJECTED" else None
    rec.resolved_by_user_id = g.user_id
    svc.touch(rec)
    # Waybill bubble-up + shipper demerit cascade (PRD §2.10, §3.3).
    svc.bubble_screening(hwb)
    return ok(svc.screening_json(rec), 200)
