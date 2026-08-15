"""DomesticWorker endpoints (PRD 3.4)."""

from __future__ import annotations

from datetime import datetime, timedelta

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_STATE_RULES_MISSING,
    ERR_CONTRACTOR_NOT_PAYABLE,
    ERR_NO_ACTIVE_AGREEMENT,
    ERR_REGISTRATION_INACTIVE,
    ERR_NEW_HIRE_REPORT_LATE,
)
from middleware import require_roles, check_employer_ownership, check_worker_ownership
from response import success_object, success_list
from routes.employers import get_employer_or_404
from services.payroll import agreement_covering
from services.posture import pack_for_state
from services.serializers import serialize_worker
from util import (
    apply_filters,
    get_json_body,
    optional_string,
    paginate,
    parse_pagination,
    require_date,
    require_enum,
    require_field,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("workers", __name__)

WORK_ARRANGEMENTS = {"LIVE_IN", "LIVE_OUT"}
REQUIRED_QUESTION_KEYS = {"controls_schedule", "supplies_own_tools", "hires_own_substitutes", "paid_by"}
CONTRACTOR_SCORE_MIN = 3


def get_worker_or_404(worker_id: str) -> dict:
    worker = db.workers.get(worker_id)
    if worker is None:
        raise_err(ERR_NOT_FOUND, "DomesticWorker id does not exist")
    return worker


def _check_access(worker: dict, user_id: str, role: str) -> None:
    check_employer_ownership(user_id, role, worker["employer_id"])
    check_worker_ownership(user_id, role, worker["id"])


@bp.route("/household-payroll/employers/<employer_id>/workers", methods=["POST"])
@require_roles("HouseholdClient")
def create_worker(employer_id: str, _user_id: str, _role: str):
    get_employer_or_404(employer_id)
    check_employer_ownership(_user_id, _role, employer_id)

    body = get_json_body()
    full_name = require_string(body, "full_name")
    ssn = optional_string(body, "ssn")
    work_state_code = require_string(body, "work_state_code")
    hire_date = require_date(body, "hire_date")
    work_arrangement = require_enum(body, "work_arrangement", WORK_ARRANGEMENTS)

    if pack_for_state(work_state_code) is None:
        raise_err(ERR_STATE_RULES_MISSING, "No StateRulePack exists for the work state")

    worker = {
        "employer_id": employer_id,
        "full_name": full_name,
        "ssn": ssn,
        "work_state_code": work_state_code,
        "hire_date": hire_date,
        "work_arrangement": work_arrangement,
        "classification": "UNDETERMINED",
        "classification_answers": [],
        "status": "ONBOARDING",
        "new_hire_report_date": None,
        "termination_date": None,
    }
    db.stamp_new(worker)
    db.workers[worker["id"]] = worker
    return success_object(serialize_worker(worker), 201)


@bp.route("/household-payroll/workers/<worker_id>", methods=["GET"])
@require_roles("PayrollAdmin", "ComplianceOfficer", "HouseholdClient", "Worker")
def get_worker(worker_id: str, _user_id: str, _role: str):
    worker = get_worker_or_404(worker_id)
    _check_access(worker, _user_id, _role)
    return success_object(serialize_worker(worker))


@bp.route("/household-payroll/employers/<employer_id>/workers", methods=["GET"])
@require_roles("PayrollAdmin", "ComplianceOfficer", "HouseholdClient")
def list_workers(employer_id: str, _user_id: str, _role: str):
    get_employer_or_404(employer_id)
    check_employer_ownership(_user_id, _role, employer_id)
    limit, offset = parse_pagination()
    items = [w for w in db.workers.values() if w["employer_id"] == employer_id]
    items = sort_by_created_at(items)
    items = apply_filters(items, ["status"])
    page, total = paginate(items, limit, offset)
    return success_list([serialize_worker(w) for w in page], limit, offset, total)


@bp.route("/household-payroll/workers/<worker_id>/classify", methods=["POST"])
@require_roles("HouseholdClient")
def classify_worker(worker_id: str, _user_id: str, _role: str):
    worker = get_worker_or_404(worker_id)
    check_employer_ownership(_user_id, _role, worker["employer_id"])

    body = get_json_body()
    answers = require_field(body, "classification_answers")
    if not isinstance(answers, list):
        raise_err(ERR_INVALID_REQUEST, "classification_answers must be an array")
    answer_map: dict[str, str] = {}
    for item in answers:
        if not isinstance(item, dict):
            raise_err(ERR_INVALID_REQUEST, "classification_answers entries must be objects")
        key = item.get("question_key")
        if not isinstance(key, str) or "answer" not in item:
            raise_err(ERR_INVALID_REQUEST, "each answer needs question_key and answer")
        answer_map[key] = item.get("answer")
    missing = REQUIRED_QUESTION_KEYS - set(answer_map)
    if missing:
        raise_err(ERR_INVALID_REQUEST, f"Missing classification answers: {sorted(missing)}")

    if worker["status"] not in ("ONBOARDING", "CLASSIFIED"):
        raise_err(ERR_INVALID_STATE, "Worker must be ONBOARDING or CLASSIFIED to classify")

    score = 0
    if answer_map["controls_schedule"] == "WORKER":
        score += 1
    if answer_map["supplies_own_tools"] == "WORKER":
        score += 1
    if answer_map["hires_own_substitutes"] == "ALLOWED":
        score += 1
    if answer_map["paid_by"] == "PROJECT_NOT_HOURS":
        score += 1

    worker["classification"] = "CONTRACTOR" if score >= CONTRACTOR_SCORE_MIN else "EMPLOYEE"
    worker["classification_answers"] = answers
    if worker["status"] == "ONBOARDING":
        worker["status"] = "CLASSIFIED"
    db.touch(worker)
    return success_object(serialize_worker(worker))


@bp.route("/household-payroll/workers/<worker_id>/activate", methods=["POST"])
@require_roles("HouseholdClient")
def activate_worker(worker_id: str, _user_id: str, _role: str):
    worker = get_worker_or_404(worker_id)
    check_employer_ownership(_user_id, _role, worker["employer_id"])

    body = get_json_body()
    report_date = require_date(body, "new_hire_report_date")

    # Preconditions in PRD 3.4 order.
    if worker["status"] != "CLASSIFIED":
        raise_err(ERR_INVALID_STATE, "Worker must be CLASSIFIED to activate")
    if worker["classification"] != "EMPLOYEE":
        raise_err(ERR_CONTRACTOR_NOT_PAYABLE, "A CONTRACTOR may not be put on payroll")
    if agreement_covering(worker_id, worker["hire_date"]) is None:
        raise_err(ERR_NO_ACTIVE_AGREEMENT, "No ACTIVE agreement covers hire_date")

    nh_active = any(
        reg["employer_id"] == worker["employer_id"]
        and reg["state_code"] == worker["work_state_code"]
        and reg["agency"] == "NEW_HIRE_DIRECTORY"
        and reg["status"] == "ACTIVE"
        for reg in db.registrations.values()
    )
    if not nh_active:
        raise_err(ERR_REGISTRATION_INACTIVE, "NEW_HIRE_DIRECTORY registration is not ACTIVE")

    pack = pack_for_state(worker["work_state_code"])
    hire_dt = datetime.strptime(worker["hire_date"], "%Y-%m-%d")
    window_end = (hire_dt + timedelta(days=pack["new_hire_report_days"])).strftime("%Y-%m-%d")
    today = db.clock_today()
    if not (worker["hire_date"] <= report_date <= window_end) or report_date > today:
        raise_err(
            ERR_NEW_HIRE_REPORT_LATE,
            "new_hire_report_date outside the statutory window or in the future",
        )

    worker["status"] = "ACTIVE"
    worker["new_hire_report_date"] = report_date
    db.touch(worker)
    return success_object(serialize_worker(worker))


@bp.route("/household-payroll/workers/<worker_id>/terminate", methods=["POST"])
@require_roles("HouseholdClient")
def terminate_worker(worker_id: str, _user_id: str, _role: str):
    worker = get_worker_or_404(worker_id)
    check_employer_ownership(_user_id, _role, worker["employer_id"])
    if worker["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "Only an ACTIVE worker can be terminated")
    worker["status"] = "TERMINATED"
    worker["termination_date"] = db.clock_today()
    db.touch(worker)
    for ag in db.agreements.values():
        if ag["worker_id"] == worker_id and ag["status"] == "ACTIVE":
            ag["status"] = "TERMINATED"
            db.touch(ag)
    return success_object(serialize_worker(worker))
