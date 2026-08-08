"""Coverages and the prior-authorization visit pool."""

from datetime import timedelta

from flask import Blueprint, request

import calc
import config
import lookup
import serialize
from auth import authenticate
from envelope import created, ok, paginate, pagination
from errors import ApiError
from store import base_row, db, now, now_iso, ordered, parse_instant, touch
from validate import filter_enum, json_body, require_date_order

bp = Blueprint("coverages", __name__)
P = config.API_PREFIX


# ------------------------------------------------------------ coverages ----
@bp.post(P + "/coverages")
def create_coverage():
    authenticate([config.ROLE_BILLING, config.ROLE_CLINIC_ADMIN])
    b = json_body()
    patient_id = b.str_req("patient_id")
    payer_id = b.str_req("payer_id")
    member_number = b.str_req("member_number")
    start = b.date_req("effective_start_date")
    end = b.date_req("effective_end_date")
    require_date_order(start, end, "effective_end_date must be on or after effective_start_date.")
    deductible_total = b.num_opt("deductible_total", 0.0)
    deductible_met = b.num_opt("deductible_met", 0.0)
    allowance_total = b.num_opt("vision_allowance_total", 0.0)
    last_therapy = b.date_opt("last_paid_service_date_therapy")
    last_evaluation = b.date_opt("last_paid_service_date_evaluation")

    lookup.patient_or_404(patient_id)                                      # rung 5
    lookup.payer_or_404(payer_id)                                          # rung 11
    # Coverage creation sits OUTSIDE the clinical write gate (PRD §2.8).

    row = base_row()
    row.update({
        "patient_id": patient_id,
        "payer_id": payer_id,
        "member_number": member_number,
        "status": "ACTIVE",
        "effective_start_date": start,
        "effective_end_date": end,
        "deductible_total": calc.f2(deductible_total),
        "deductible_met": calc.f2(deductible_met),
        "vision_allowance_total": calc.f2(allowance_total),
        "vision_allowance_used": 0.0,
        "vision_allowance_remaining": calc.f2(allowance_total),
        "last_paid_service_date_therapy": last_therapy,
        "last_paid_service_date_evaluation": last_evaluation,
    })
    db.coverages[row["id"]] = row
    return created(serialize.coverage(row))


@bp.get(P + "/coverages/<id>")
def get_coverage(id):
    authenticate(config.READ_ROLES)
    return ok(serialize.coverage(lookup.coverage_or_404(id)))


@bp.get(P + "/coverages")
def list_coverages():
    authenticate(config.READ_ROLES)
    limit, offset = pagination(request.args)
    status = filter_enum(request.args, "status", config.COVERAGE_STATUSES)
    patient_id = request.args.get("patient_id")
    payer_id = request.args.get("payer_id")

    def match(row):
        if patient_id and row["patient_id"] != patient_id:
            return False
        if payer_id and row["payer_id"] != payer_id:
            return False
        if status and row["status"] != status:
            return False
        return True

    return paginate(ordered(db.coverages, match), limit, offset, serialize.coverage)


# ------------------------------------------------------- authorizations ----
@bp.post(P + "/authorizations")
def create_authorization():
    authenticate([config.ROLE_BILLING])
    b = json_body()
    patient_id = b.str_req("patient_id")
    coverage_id = b.str_req("coverage_id")
    auth_number = b.str_req("auth_number")
    visits = b.int_req("visits_authorized", non_negative=True)
    start = b.date_req("window_start_date")
    end = b.date_req("window_end_date")
    require_date_order(start, end, "window_end_date must be on or after window_start_date.")

    lookup.patient_or_404(patient_id)                                      # rung 5
    lookup.coverage_or_404(coverage_id)                                    # rung 6
    lookup.gate_for_patient_id(patient_id)                                 # rung 12

    row = base_row()
    row.update({
        "patient_id": patient_id,
        "coverage_id": coverage_id,
        "auth_number": auth_number,
        "visits_authorized": visits,
        "visits_consumed": 0,
        "visits_released": 0,
        "visits_remaining": visits,
        "window_start_date": start,
        "window_end_date": end,
        "status": "ACTIVE",
        "reauthorization_count": 0,
        "last_reauthorized_at": None,
        "close_reason": None,
    })
    db.authorizations[row["id"]] = row
    return created(serialize.authorization(row))


@bp.get(P + "/authorizations/<id>")
def get_authorization(id):
    authenticate(config.READ_ROLES)
    return ok(serialize.authorization(lookup.authorization_or_404(id)))


@bp.get(P + "/authorizations")
def list_authorizations():
    authenticate(config.READ_ROLES)
    limit, offset = pagination(request.args)
    status = filter_enum(request.args, "status", config.AUTHORIZATION_STATUSES)
    patient_id = request.args.get("patient_id")
    coverage_id = request.args.get("coverage_id")

    def match(row):
        if patient_id and row["patient_id"] != patient_id:
            return False
        if coverage_id and row["coverage_id"] != coverage_id:
            return False
        if status and row["status"] != status:
            return False
        return True

    return paginate(ordered(db.authorizations, match), limit, offset, serialize.authorization)


@bp.post(P + "/authorizations/<id>/reauthorize")
def reauthorize(id):
    authenticate([config.ROLE_BILLING])
    b = json_body()
    additional = b.int_req("additional_visits", non_negative=True)
    new_end = b.date_req("new_window_end_date")
    reassessment_id = b.str_req("reassessment_id")

    reassessment = lookup.assessment_or_404(reassessment_id)               # rung 7
    auth_row = lookup.authorization_or_404(id)                             # rung 11
    lookup.gate_for_patient_id(auth_row["patient_id"])                     # rung 12
    if auth_row["status"] not in ("ACTIVE", "EXHAUSTED"):                  # rung 14
        raise ApiError("ERR_INVALID_STATE", "Only an ACTIVE or EXHAUSTED pool may be reauthorized.")

    cutoff = now() - timedelta(days=config.REAUTH_LOOKBACK_DAYS)           # rung 32
    signed_at = parse_instant(reassessment.get("signed_at"))
    if (reassessment["status"] != "SIGNED"
            or reassessment["assessment_type"] != "REASSESSMENT"
            or reassessment["patient_id"] != auth_row["patient_id"]
            or signed_at is None or signed_at < cutoff):
        raise ApiError("ERR_REAUTH_REASSESSMENT_STALE")

    auth_row["visits_authorized"] += additional
    auth_row["visits_remaining"] += additional
    auth_row["window_end_date"] = new_end
    auth_row["reauthorization_count"] += 1
    auth_row["last_reauthorized_at"] = now_iso()
    auth_row["status"] = "ACTIVE"
    touch(auth_row)
    return ok(serialize.authorization(auth_row))


@bp.post(P + "/authorizations/<id>/close")
def close_authorization(id):
    authenticate([config.ROLE_BILLING])
    b = json_body()
    b.enum_shape_req("close_reason")                                       # rung 3
    reason = b.enum_req("close_reason", config.CLOSE_REASONS)              # rung 4
    auth_row = lookup.authorization_or_404(id)                             # rung 11
    # OUTSIDE the clinical write gate (PRD §2.8).
    if auth_row["status"] not in ("ACTIVE", "EXHAUSTED", "EXPIRED"):       # rung 14
        raise ApiError("ERR_INVALID_STATE", "This pool is already closed.")

    auth_row["status"] = "CLOSED"
    auth_row["close_reason"] = reason
    touch(auth_row)
    return ok(serialize.authorization(auth_row))
