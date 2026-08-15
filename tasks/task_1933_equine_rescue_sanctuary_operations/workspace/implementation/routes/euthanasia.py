from datetime import timedelta

from flask import Blueprint

import clock
import db
import services
from auth import authenticate, ROLE_SANCTUARY_DIRECTOR, ROLE_VETERINARIAN
from errors import (
    raise_err,
    ERR_HORSE_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_FORBIDDEN,
    ERR_DUTY_SEGREGATION,
    ERR_COOLING_OFF_ACTIVE,
)
from response import ok_object, ok_list
from serializers import serialize, serialize_many
from util import (
    as_bool,
    as_enum,
    as_int,
    as_str,
    body,
    get_path_or_404,
    minute_floor,
    pagination_args,
    query_str,
    require_present,
    sorted_page,
)

bp = Blueprint("euthanasia", __name__)

EOL_ELIGIBLE = {"REHABILITATION", "ADOPTABLE", "ADOPTION_PENDING", "SANCTUARY"}
READ_ROLES = [ROLE_SANCTUARY_DIRECTOR, ROLE_VETERINARIAN]


def _require_active_vet(user_id):
    pract = db.practitioners.get(user_id)
    if pract is None or pract["specialty"] != "VETERINARIAN" or not pract["active"]:
        raise_err(ERR_FORBIDDEN, "Caller must be an active VETERINARIAN practitioner")


@bp.post("/rescue-ops/euthanasia-cases")
def create_case():
    user_id, _ = authenticate([ROLE_VETERINARIAN])
    data = body()
    horse_id = data.get("horse_id")
    if horse_id is not None and horse_id not in db.horses:
        raise_err(ERR_HORSE_NOT_FOUND, "horse_id does not reference an existing horse")
    horse_id = require_present(data, "horse_id")
    summary = as_str(require_present(data, "clinical_summary"), "clinical_summary")
    score = as_int(require_present(data, "suffering_score"), "suffering_score")
    if score < 1 or score > 10:
        raise_err(ERR_INVALID_REQUEST, "suffering_score must be in 1..10")
    horse = db.horses[horse_id]
    if horse["status"] not in EOL_ELIGIBLE:
        raise_err(ERR_INVALID_STATE, "Horse posture does not allow an end-of-life case")
    rec = services.new_entity(
        {
            "horse_id": horse_id,
            "clinical_summary": summary,
            "suffering_score": score,
            "status": "PROPOSED",
            "proposing_practitioner_id": user_id,
            "certifying_practitioner_id": None,
            "emergency_certified": False,
            "authorized_at": None,
            "executed_at": None,
            "prior_horse_status": horse["status"],
            "overturn_reason": None,
        }
    )
    db.euthanasia_cases[rec["id"]] = rec
    horse["prior_status"] = horse["status"]
    horse["status"] = "END_OF_LIFE_REVIEW"
    services.touch(horse)
    return ok_object(serialize(rec), 201)


@bp.get("/rescue-ops/euthanasia-cases")
def list_cases():
    authenticate(READ_ROLES)
    limit, offset = pagination_args()
    filters = []
    for param in ("horse_id", "status", "proposing_practitioner_id", "certifying_practitioner_id"):
        value = query_str(param)
        if value is not None:
            filters.append((param, value))
    rows, total = sorted_page(db.euthanasia_cases.values(), filters, limit, offset)
    return ok_list(serialize_many(rows), limit, offset, total)


@bp.get("/rescue-ops/euthanasia-cases/<case_id>")
def get_case(case_id):
    authenticate(READ_ROLES)
    return ok_object(serialize(get_path_or_404(db.euthanasia_cases, case_id)))


@bp.post("/rescue-ops/euthanasia-cases/<case_id>/certify")
def certify_case(case_id):
    user_id, _ = authenticate([ROLE_VETERINARIAN])
    rec = get_path_or_404(db.euthanasia_cases, case_id)
    data = body()
    decision = as_enum(require_present(data, "decision"), "decision", {"CONCUR", "DISSENT"})
    attestation = as_bool(require_present(data, "emergency_attestation"), "emergency_attestation")
    if rec["status"] != "PROPOSED":
        raise_err(ERR_INVALID_STATE, "Case is not PROPOSED")
    if user_id == rec["proposing_practitioner_id"]:
        raise_err(ERR_DUTY_SEGREGATION, "Certifier must differ from the proposer")
    _require_active_vet(user_id)
    if decision == "CONCUR":
        rec["status"] = "CERTIFIED"
        rec["certifying_practitioner_id"] = user_id
        if rec["suffering_score"] >= 8 and attestation is True:
            rec["emergency_certified"] = True
        services.touch(rec)
    else:
        rec["status"] = "OVERRIDDEN"
        services.touch(rec)
        services.horse_eol_restore(db.horses[rec["horse_id"]])
    return ok_object(serialize(rec))


@bp.post("/rescue-ops/euthanasia-cases/<case_id>/authorize")
def authorize_case(case_id):
    authenticate([ROLE_SANCTUARY_DIRECTOR])
    rec = get_path_or_404(db.euthanasia_cases, case_id)
    if rec["status"] != "CERTIFIED":
        raise_err(ERR_INVALID_STATE, "Case is not CERTIFIED")
    horse = db.horses[rec["horse_id"]]
    if horse["status"] != "END_OF_LIFE_REVIEW":
        raise_err(ERR_INVALID_STATE, "Horse is not in END_OF_LIFE_REVIEW")
    rec["status"] = "AUTHORIZED"
    rec["authorized_at"] = clock.now()
    services.touch(rec)
    return ok_object(serialize(rec))


@bp.post("/rescue-ops/euthanasia-cases/<case_id>/execute")
def execute_case(case_id):
    user_id, _ = authenticate([ROLE_VETERINARIAN])
    rec = get_path_or_404(db.euthanasia_cases, case_id)
    if rec["status"] != "AUTHORIZED":
        raise_err(ERR_INVALID_STATE, "Case is not AUTHORIZED")
    now = clock.now()
    if not rec["emergency_certified"] and minute_floor(now) < minute_floor(
        rec["authorized_at"] + timedelta(hours=72)
    ):
        raise_err(ERR_COOLING_OFF_ACTIVE, "72-hour cooling-off has not elapsed")
    _require_active_vet(user_id)
    rec["status"] = "EXECUTED"
    rec["executed_at"] = now
    services.touch(rec)
    services.horse_deceased_cascade(db.horses[rec["horse_id"]])
    return ok_object(serialize(rec))


@bp.post("/rescue-ops/euthanasia-cases/<case_id>/overturn")
def overturn_case(case_id):
    authenticate([ROLE_SANCTUARY_DIRECTOR])
    rec = get_path_or_404(db.euthanasia_cases, case_id)
    data = body()
    reason = as_str(require_present(data, "reason"), "reason")
    if rec["status"] not in ("PROPOSED", "CERTIFIED"):
        raise_err(ERR_INVALID_STATE, "Case cannot be overturned from its current state")
    rec["status"] = "OVERRIDDEN"
    rec["overturn_reason"] = reason
    services.touch(rec)
    services.horse_eol_restore(db.horses[rec["horse_id"]])
    return ok_object(serialize(rec))
