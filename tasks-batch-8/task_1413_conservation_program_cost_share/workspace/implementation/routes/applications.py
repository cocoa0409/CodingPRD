"""Application lifecycle: create (DRAFT), submit, withdraw, screen."""
from flask import Blueprint

import serializers
from db import STORE, new_id
from errors import ApiError
from helpers import (
    apply_filters, as_enum, as_list, as_str, body, get_applicant, get_application,
    get_program, paginate, req_field, sorted_created, stamp_new, touch,
)
from middleware import ANY_ROLE, check_owner, require_roles
from response import ok, ok_list
from routes.programs import PRACTICE_CODES
from services.calc import estimated_obligation_cents, ranking_score, rate_for_code
from util import dec, is_num

bp = Blueprint("applications", __name__)


def _clamp_answers(program_id, answers, field_name):
    """Validate answer keys against the program's criteria and clamp each value
    to [0, max_points]."""
    if answers is None:
        return {}
    if not isinstance(answers, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field_name} must be an object")
    criteria = {c["criterion_code"]: c for c in STORE.criteria.values()
                if c["program_id"] == program_id}
    out = {}
    for code, pts in answers.items():
        if code not in criteria:
            raise ApiError(
                "ERR_INVALID_REQUEST", 400,
                f"Unknown criterion_code for this program: {code}",
            )
        if not is_num(pts):
            raise ApiError("ERR_INVALID_REQUEST", 400, f"Answer points for {code} must be a number")
        cap = criteria[code]["max_points"]
        clamped = dec(pts)
        if clamped < 0:
            clamped = dec(0)
        if clamped > dec(cap):
            clamped = dec(cap)
        # Preserve integer shape when the input was integral.
        out[code] = int(clamped) if clamped == clamped.to_integral_value() else float(clamped)
    return out


@bp.post("/eqip/applications")
@require_roles("Applicant")
def create_application(_uid, _role):
    data = body()
    program_id = req_field(data, "program_id")
    applicant_id = req_field(data, "applicant_id")
    get_program(program_id)
    applicant = get_applicant(applicant_id)
    check_owner(applicant["id"], _uid)

    parcel_id = as_str(req_field(data, "parcel_id"), "parcel_id")
    planned = as_list(req_field(data, "planned_practices"), "planned_practices")
    if len(planned) == 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "planned_practices must be non-empty")
    norm_practices = []
    for entry in planned:
        if not isinstance(entry, dict):
            raise ApiError("ERR_INVALID_REQUEST", 400, "planned_practices entries must be objects")
        code = as_enum(req_field(entry, "practice_code"), "practice_code", PRACTICE_CODES)
        qty = req_field(entry, "quantity")
        if not is_num(qty) or dec(qty) <= 0:
            raise ApiError("ERR_INVALID_REQUEST", 400, "quantity must be a number > 0")
        norm_practices.append({"practice_code": code, "quantity": qty})
    answers = _clamp_answers(program_id, data.get("self_reported_answers", {}),
                             "self_reported_answers")

    a = {
        "id": new_id(),
        "program_id": program_id,
        "applicant_id": applicant_id,
        "parcel_id": parcel_id,
        "planned_practices": norm_practices,
        "self_reported_answers": answers,
        "verified_answers": None,
        "provisional_score": None,
        "ranking_score": None,
        "estimated_obligation_cents": None,
        "funded_pool_id": None,
        "status": "DRAFT",
    }
    stamp_new(a)
    STORE.applications[a["id"]] = a
    return ok(serializers.application(a), 201)


@bp.get("/eqip/applications/<aid>")
@require_roles(*ANY_ROLE)
def get_one_application(aid, _uid, _role):
    return ok(serializers.application(get_application(aid)))


@bp.get("/eqip/applications")
@require_roles(*ANY_ROLE)
def list_applications(_uid, _role):
    items = apply_filters(
        sorted_created(STORE.applications.values()),
        [("program_id", "program_id"), ("applicant_id", "applicant_id"),
         ("funded_pool_id", "funded_pool_id"), ("status", "status")],
    )
    page, meta = paginate(items)
    return ok_list([serializers.application(a) for a in page], meta)


@bp.post("/eqip/applications/<aid>/submit")
@require_roles("Applicant")
def submit_application(aid, _uid, _role):
    a = get_application(aid)
    check_owner(a["applicant_id"], _uid)
    if a["status"] != "DRAFT":
        raise ApiError("ERR_APPLICATION_NOT_DRAFT", 409, "submit requires status DRAFT")
    program = get_program(a["program_id"])
    if program["status"] != "OPEN" or STORE.clock > program["window_end"]:
        raise ApiError("ERR_PROGRAM_NOT_OPEN", 409, "The program's application window is not open")
    for pp in a["planned_practices"]:
        if rate_for_code(a["program_id"], pp["practice_code"]) is None:
            raise ApiError(
                "ERR_RATE_NOT_FOUND", 422,
                f"No payment schedule rate for {pp['practice_code']} in this program",
            )
    applicant = get_applicant(a["applicant_id"])
    if a["parcel_id"] not in applicant["parcel_ids"]:
        raise ApiError(
            "ERR_PARCEL_NOT_REGISTERED", 422,
            "parcel_id is not registered to the applicant",
        )
    a["provisional_score"] = ranking_score(a["program_id"], a["self_reported_answers"])
    a["status"] = "SUBMITTED"
    touch(a)
    return ok(serializers.application(a))


@bp.post("/eqip/applications/<aid>/withdraw")
@require_roles("Applicant")
def withdraw_application(aid, _uid, _role):
    a = get_application(aid)
    check_owner(a["applicant_id"], _uid)
    if a["status"] not in ("DRAFT", "SUBMITTED", "SCREENED_IN"):
        raise ApiError(
            "ERR_APPLICATION_NOT_WITHDRAWABLE", 409,
            "withdraw requires DRAFT, SUBMITTED or SCREENED_IN",
        )
    a["status"] = "WITHDRAWN"
    touch(a)
    return ok(serializers.application(a))


@bp.post("/eqip/applications/<aid>/screen")
@require_roles("ConservationPlanner")
def screen_application(aid, _uid, _role):
    a = get_application(aid)
    if a["status"] != "SUBMITTED":
        raise ApiError("ERR_APPLICATION_NOT_SUBMITTED", 409, "screen requires status SUBMITTED")
    data = body()
    decision = as_enum(req_field(data, "decision"), "decision", {"SCREENED_IN", "SCREENED_OUT"})
    if decision == "SCREENED_OUT":
        a["status"] = "SCREENED_OUT"
        touch(a)
        return ok(serializers.application(a))
    # SCREENED_IN requires the planner's verified answers.
    verified = req_field(data, "verified_answers")
    verified = _clamp_answers(a["program_id"], verified, "verified_answers")
    applicant = get_applicant(a["applicant_id"])
    a["verified_answers"] = verified
    a["ranking_score"] = ranking_score(a["program_id"], verified)
    a["estimated_obligation_cents"] = estimated_obligation_cents(a, applicant)
    a["status"] = "SCREENED_IN"
    touch(a)
    return ok(serializers.application(a))
