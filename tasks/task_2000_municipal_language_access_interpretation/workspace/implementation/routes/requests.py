"""InterpretationRequest endpoints (PRD §3.6): dispatch, completion, cancel."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_DEPARTMENT_BUDGET_EXCEEDED,
    ERR_DEPARTMENT_NONCOMPLIANT,
    ERR_DEPARTMENT_NOT_FOUND,
    ERR_FORBIDDEN_ROLE,
    ERR_INVALID_TRANSITION,
    ERR_LEAD_TIME_INSUFFICIENT,
    ERR_REQUEST_NOT_FOUND,
    ERR_SCHEDULE_IN_PAST,
    ERR_SETTING_REQUIRES_IN_PERSON,
    ERR_VALIDATION,
)
from middleware import authorized, check_liaison_owns_department
from response import success_object
from routes.helpers import get_one, list_endpoint
from services.core import (
    IN_PERSON_LEAD,
    department_posture,
    department_spent,
    dispatch_candidates,
    interpretation_cost_cents,
    is_after_hours,
    maybe_exhaust_contract,
    recompute_interpreter_rating,
    touch,
)
from services.serializers import serialize_request
from util import CLOCK, new_id, next_seq, parse_iso
from validate import (
    get_body,
    opt_datetime_str,
    reject_unknown_fields,
    req_enum,
    req_int,
    req_str,
    require_path,
)

bp = Blueprint("interpretation_requests", __name__)

MODALITIES = {"PHONE", "VIDEO", "IN_PERSON"}
SETTINGS = {"GENERAL", "MEDICAL", "COURT"}


@bp.post("/interpretation-requests")
def create_request():
    caller = authorized(["DepartmentLiaison"])
    body = get_body()
    # Priority 2 ownership: the liaison acts on its own department only.
    check_liaison_owns_department(caller, body.get("department_id"))
    reject_unknown_fields(
        body,
        {"department_id", "language_code", "modality", "encounter_setting",
         "scheduled_start", "scheduled_duration_minutes"})
    department_id = req_str(body, "department_id")
    language_code = req_str(body, "language_code")
    modality = req_enum(body, "modality", MODALITIES)
    encounter_setting = req_enum(body, "encounter_setting", SETTINGS)
    scheduled_duration_minutes = req_int(body, "scheduled_duration_minutes", positive=True)
    scheduled_start = opt_datetime_str(body, "scheduled_start")
    if modality == "IN_PERSON" and scheduled_start is None:
        raise_error(ERR_VALIDATION, "scheduled_start is required for IN_PERSON requests")

    dept = require_path("departments", department_id, ERR_DEPARTMENT_NOT_FOUND)

    # Priority 6 safety gates, in order: posture, then COURT modality rule.
    if department_posture(department_id) == "NONCOMPLIANT":
        raise_error(ERR_DEPARTMENT_NONCOMPLIANT, "department posture is NONCOMPLIANT")
    if encounter_setting == "COURT" and modality != "IN_PERSON":
        raise_error(ERR_SETTING_REQUIRES_IN_PERSON, "COURT encounters require IN_PERSON modality")

    # Priority 7 temporal rules.
    now = CLOCK.now()
    start_explicit = scheduled_start is not None
    if scheduled_start is None:
        effective_start = CLOCK.now_iso()
    else:
        effective_start = scheduled_start
        if parse_iso(scheduled_start) < now:
            raise_error(ERR_SCHEDULE_IN_PAST, "scheduled_start is before the current logical time")
        if modality == "IN_PERSON" and parse_iso(scheduled_start) < now + IN_PERSON_LEAD:
            raise_error(ERR_LEAD_TIME_INSUFFICIENT, "IN_PERSON sessions require at least 2 hours of lead time")

    # Dispatch selector runs synchronously at creation.
    req_draft = {
        "language_code": language_code,
        "modality": modality,
        "encounter_setting": encounter_setting,
        "scheduled_start": effective_start,
        "scheduled_duration_minutes": scheduled_duration_minutes,
        "_after_hours": is_after_hours(scheduled_start) if start_explicit else False,
    }
    candidates = dispatch_candidates(req_draft)

    now_iso = CLOCK.now_iso()
    rec = {
        "id": new_id(),
        "department_id": department_id,
        "language_code": language_code,
        "modality": modality,
        "encounter_setting": encounter_setting,
        "scheduled_start": effective_start,
        "scheduled_duration_minutes": scheduled_duration_minutes,
        "interpreter_id": None,
        "estimated_cost_cents": None,
        "actual_minutes": None,
        "final_cost_cents": None,
        "completed_at": None,
        "refund_clawed_back": False,
        "created_at": now_iso,
        "updated_at": now_iso,
        "version": 1,
        "_seq": next_seq(),
        "_after_hours": req_draft["_after_hours"],
        "_contract_id": None,
        "_rate_card": None,
        "_tier": None,
    }

    if not candidates:
        # Empty pool: born UNFULFILLED (still 201); department takes a -50 event.
        rec["status"] = "UNFULFILLED"
        db["interpretation_requests"][rec["id"]] = rec
        touch(dept)  # compliance_score moved derivationally
        return success_object(serialize_request(rec), status=201)

    interp, est = candidates[0]
    # Priority 9 (fiscal, last): department must afford the estimate, equality allowed.
    remaining = dept["annual_budget_cents"] - department_spent(department_id)
    if remaining < est:
        raise_error(ERR_DEPARTMENT_BUDGET_EXCEEDED, "estimated cost exceeds department remaining_cents")

    rec["status"] = "ASSIGNED"
    rec["interpreter_id"] = interp["id"]
    rec["estimated_cost_cents"] = est
    # Pricing context snapshot: the selected interpreter's contract rate card and
    # tier at dispatch; the final variant replays the same five steps over
    # actual_minutes against this snapshot.
    contract = db["vendor_contracts"][interp["vendor_contract_id"]]
    rec["_contract_id"] = contract["id"]
    rec["_rate_card"] = {
        "phone_per_minute_cents": contract["phone_per_minute_cents"],
        "video_per_minute_cents": contract["video_per_minute_cents"],
        "in_person_per_minute_cents": contract["in_person_per_minute_cents"],
        "in_person_travel_flat_cents": contract["in_person_travel_flat_cents"],
    }
    rec["_tier"] = interp["tier"]
    db["interpretation_requests"][rec["id"]] = rec
    touch(contract)  # committed_cents rose derivationally
    return success_object(serialize_request(rec), status=201)


@bp.get("/interpretation-requests")
def list_requests():
    filters = {
        "department_id": request.args.get("department_id"),
        "interpreter_id": request.args.get("interpreter_id"),
        "status": request.args.get("status"),
    }
    return list_endpoint("interpretation_requests", serialize_request, filters)


@bp.get("/interpretation-requests/<rid>")
def get_request(rid):
    return get_one("interpretation_requests", rid, ERR_REQUEST_NOT_FOUND, serialize_request)


@bp.post("/interpretation-requests/<rid>/complete")
def complete_request(rid):
    caller = authorized(["Interpreter"])
    body = get_body()
    reject_unknown_fields(body, {"actual_minutes"})
    actual_minutes = req_int(body, "actual_minutes", positive=True)

    rec = require_path("interpretation_requests", rid, ERR_REQUEST_NOT_FOUND)
    if rec["status"] != "ASSIGNED":
        raise_error(ERR_INVALID_TRANSITION, "only an ASSIGNED request may be completed")
    if caller.user_id != rec["interpreter_id"]:
        raise_error(ERR_FORBIDDEN_ROLE, "only the assigned interpreter may complete this request")

    rec["status"] = "COMPLETED"
    rec["actual_minutes"] = actual_minutes
    rec["completed_at"] = CLOCK.now_iso()
    rec["final_cost_cents"] = interpretation_cost_cents(
        rec["modality"], actual_minutes, rec["_tier"], rec["_rate_card"], rec["_after_hours"])
    touch(rec)

    contract = db["vendor_contracts"].get(rec["_contract_id"])
    if contract is not None:
        # committed -= estimated, spent += final (derivational); the spend move
        # may push the contract past the 90% exhaustion threshold.
        maybe_exhaust_contract(contract)
        touch(contract)
    dept = db["departments"].get(rec["department_id"])
    if dept is not None:
        touch(dept)  # spent_cents rose derivationally
    interp = db["interpreters"].get(rec["interpreter_id"])
    if interp is not None:
        recompute_interpreter_rating(interp)  # +5 completion event
        touch(interp)
    return success_object(serialize_request(rec))


@bp.post("/interpretation-requests/<rid>/cancel")
def cancel_request(rid):
    caller = authorized(["DepartmentLiaison", "LanguageAccessCoordinator"])
    body = get_body()
    reject_unknown_fields(body, set())
    rec = require_path("interpretation_requests", rid, ERR_REQUEST_NOT_FOUND)
    if rec["status"] != "ASSIGNED":
        raise_error(ERR_INVALID_TRANSITION, "only an ASSIGNED request may be cancelled")
    if caller.role == "DepartmentLiaison" and caller.user_id != rec["department_id"]:
        raise_error(ERR_FORBIDDEN_ROLE, "liaison may cancel only its own department's requests")

    rec["status"] = "CANCELLED"
    touch(rec)
    contract = db["vendor_contracts"].get(rec["_contract_id"])
    if contract is not None:
        touch(contract)  # estimated commitment released derivationally
    return success_object(serialize_request(rec))
