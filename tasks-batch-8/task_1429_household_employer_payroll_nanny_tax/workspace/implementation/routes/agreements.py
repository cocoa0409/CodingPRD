"""EmploymentAgreement endpoints (PRD 3.4)."""

from __future__ import annotations

from datetime import datetime, timedelta

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_STALE_VERSION,
    ERR_BELOW_MIN_WAGE,
)
from middleware import require_roles, check_employer_ownership
from response import success_object, success_list
from routes.workers import get_worker_or_404
from services.posture import pack_for_state
from services.serializers import serialize_agreement
from util import (
    apply_filters,
    get_json_body,
    is_int,
    optional_int,
    paginate,
    parse_pagination,
    require_date,
    require_enum,
    require_field,
    require_int,
    sort_by_created_at,
)

bp = Blueprint("agreements", __name__)

PAY_METHODS = {"HOURLY", "GUARANTEED_SALARY_FWW"}


def get_agreement_or_404(agreement_id: str) -> dict:
    ag = db.agreements.get(agreement_id)
    if ag is None:
        raise_err(ERR_NOT_FOUND, "EmploymentAgreement id does not exist")
    return ag


@bp.route("/household-payroll/workers/<worker_id>/agreements", methods=["POST"])
@require_roles("HouseholdClient")
def create_agreement(worker_id: str, _user_id: str, _role: str):
    worker = get_worker_or_404(worker_id)
    check_employer_ownership(_user_id, _role, worker["employer_id"])

    body = get_json_body()
    hourly_rate_cents = require_int(body, "hourly_rate_cents")
    if hourly_rate_cents % 60 != 0:
        raise_err(ERR_INVALID_REQUEST, "hourly_rate_cents must be divisible by 60")
    pay_method = require_enum(body, "pay_method", PAY_METHODS)
    guaranteed_minutes = optional_int(body, "guaranteed_minutes_per_week", 0, 0)
    fit_withholding = optional_int(body, "fit_withholding_cents_per_period", 0, 0)
    effective_from = require_date(body, "effective_from")
    expected = require_field(body, "expected_worker_version")
    if not is_int(expected):
        raise_err(ERR_INVALID_REQUEST, "expected_worker_version must be an integer")

    # OCC on the parent worker version, before any state-machine evaluation.
    if expected != worker["version"]:
        raise_err(ERR_STALE_VERSION, "expected_worker_version does not match the worker version")

    pack = pack_for_state(worker["work_state_code"])
    if pack is not None and hourly_rate_cents < pack["min_wage_cents"]:
        raise_err(ERR_BELOW_MIN_WAGE, "hourly_rate_cents is below the work state's minimum wage")

    agreement = {
        "worker_id": worker_id,
        "hourly_rate_cents": hourly_rate_cents,
        "pay_method": pay_method,
        "guaranteed_minutes_per_week": guaranteed_minutes,
        "fit_withholding_cents_per_period": fit_withholding,
        "effective_from": effective_from,
        "effective_to": None,
        "status": "ACTIVE",
        "superseded_by_id": None,
    }
    db.stamp_new(agreement)
    db.agreements[agreement["id"]] = agreement

    # Supersede the worker's prior ACTIVE agreement, if one exists.
    prior_to = (
        datetime.strptime(effective_from, "%Y-%m-%d") - timedelta(days=1)
    ).strftime("%Y-%m-%d")
    for other in db.agreements.values():
        if other["worker_id"] == worker_id and other["status"] == "ACTIVE" and other["id"] != agreement["id"]:
            other["status"] = "SUPERSEDED"
            other["effective_to"] = prior_to
            other["superseded_by_id"] = agreement["id"]
            db.touch(other)

    db.touch(worker)  # creation increments the parent worker's version
    return success_object(serialize_agreement(agreement), 201)


@bp.route("/household-payroll/workers/<worker_id>/agreements", methods=["GET"])
@require_roles("PayrollAdmin", "ComplianceOfficer", "HouseholdClient", "Worker")
def list_agreements(worker_id: str, _user_id: str, _role: str):
    worker = get_worker_or_404(worker_id)
    check_employer_ownership(_user_id, _role, worker["employer_id"])
    if _role == "Worker" and _user_id != worker_id:
        from middleware import forbid

        forbid("Worker may only list their own agreements")
    limit, offset = parse_pagination()
    items = [a for a in db.agreements.values() if a["worker_id"] == worker_id]
    items = sort_by_created_at(items)
    items = apply_filters(items, ["status"])
    page, total = paginate(items, limit, offset)
    return success_list([serialize_agreement(a) for a in page], limit, offset, total)


@bp.route("/household-payroll/agreements/<agreement_id>", methods=["GET"])
@require_roles("PayrollAdmin", "ComplianceOfficer", "HouseholdClient", "Worker")
def get_agreement(agreement_id: str, _user_id: str, _role: str):
    ag = get_agreement_or_404(agreement_id)
    worker = db.workers.get(ag["worker_id"])
    if worker is not None:
        check_employer_ownership(_user_id, _role, worker["employer_id"])
        if _role == "Worker" and _user_id != ag["worker_id"]:
            from middleware import forbid

            forbid("Worker may only read their own agreements")
    return success_object(serialize_agreement(ag))


@bp.route("/household-payroll/agreements/<agreement_id>/superseded", methods=["GET"])
@require_roles("PayrollAdmin", "ComplianceOfficer", "HouseholdClient", "Worker")
def list_superseded(agreement_id: str, _user_id: str, _role: str):
    ag = get_agreement_or_404(agreement_id)
    worker = db.workers.get(ag["worker_id"])
    if worker is not None:
        check_employer_ownership(_user_id, _role, worker["employer_id"])
        if _role == "Worker" and _user_id != ag["worker_id"]:
            from middleware import forbid

            forbid("Worker may only read their own agreements")
    limit, offset = parse_pagination()
    items = [a for a in db.agreements.values() if a.get("superseded_by_id") == agreement_id]
    items = sort_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return success_list([serialize_agreement(a) for a in page], limit, offset, total)
