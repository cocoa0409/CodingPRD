"""Assessor credentialing, team rosters and wrestler disqualification."""

from flask import Blueprint

import cascade
import lookups
import serialize
import validate as V
from auth import endpoint, require_team_owner, user_id
from envelope import ok, ok_list
from errors import ApiError
from routes.core import require_open
from store import DB, clock_iso, fmt_date, new_row, touch

bp = Blueprint("people", __name__)

METHODS = ("SKINFOLD", "BIA", "HYDROSTATIC", "ADP")
CERTIFICATION_STATUSES = ("UNCERTIFIED", "PROVISIONAL", "CERTIFIED",
                          "SUSPENDED", "DISQUALIFIED")
ELIGIBILITY_STATUSES = ("INELIGIBLE", "ELIGIBLE", "RESTRICTED")


# --------------------------------------------------------------------------
# assessors
# --------------------------------------------------------------------------

def _certified_methods(body):
    if "certified_methods" not in body or body["certified_methods"] is None:
        V.bad("Field 'certified_methods' is required.")
    value = body["certified_methods"]
    if not isinstance(value, list) or len(value) == 0:
        V.bad("Field 'certified_methods' must be a non-empty array.")
    for item in value:
        if item not in METHODS:
            V.bad("Field 'certified_methods' must contain only %s." % (list(METHODS),))
    return [str(item) for item in value]


@bp.post("/assessors")
@endpoint("StateOffice")
def create_assessor():
    body = V.get_body()
    full_name = V.req_str(body, "full_name", max_len=120, allow_empty=False)
    credential_number = V.req_str(body, "credential_number", max_len=40, allow_empty=False)
    methods = _certified_methods(body)
    expires_on = V.req_date(body, "certification_expires_on")
    for row in DB.assessors.values():
        if row.get("credential_number") == credential_number:
            raise ApiError("ERR_DUPLICATE_CREDENTIAL",
                           "credential_number must be globally unique.")
    row = new_row()
    row.update({
        "full_name": full_name,
        "credential_number": credential_number,
        "certified_methods": methods,
        "certification_expires_on": fmt_date(expires_on),
        "training_hours_completed": 0,
        "status": "PROVISIONAL",
        "suspension_reason": None,
    })
    DB.assessors[row["id"]] = row
    return ok(serialize.assessor(row), 201)


@bp.get("/assessors/<assessor_id>")
@endpoint("StateOffice", "Assessor", "TeamCoach", "MedicalReviewer")
def read_assessor(assessor_id):
    return ok(serialize.assessor(lookups.assessor(assessor_id)))


@bp.post("/assessors/<assessor_id>/training-records")
@endpoint("StateOffice")
def add_training_record(assessor_id):
    assessor = lookups.assessor(assessor_id)
    body = V.get_body()
    V.req_str(body, "credential_code", max_len=120, allow_empty=False)
    hours = V.req_num(body, "hours", minimum=0)

    total = float(assessor.get("training_hours_completed") or 0) + float(hours)
    if float(total).is_integer():
        total = int(total)
    assessor["training_hours_completed"] = total

    season = lookups.latest_season()
    if (assessor.get("status") == "PROVISIONAL" and season is not None
            and float(total) >= float(season.get("assessor_min_training_hours"))):
        assessor["status"] = "CERTIFIED"
    touch(assessor)
    return ok(serialize.assessor(assessor))


@bp.post("/assessors/<assessor_id>/suspension")
@endpoint("StateOffice")
def suspend_assessor(assessor_id):
    assessor = lookups.assessor(assessor_id)
    body = V.get_body()
    reason = V.req_str(body, "reason", max_len=500, allow_empty=False)
    if assessor.get("status") != "CERTIFIED":
        raise ApiError("ERR_ASSESSOR_INVALID_STATE",
                       "Only a CERTIFIED assessor may be suspended.")
    assessor["status"] = "SUSPENDED"
    assessor["suspension_reason"] = reason
    touch(assessor)
    drafts = [a for a in lookups.assessments_of_assessor(assessor["id"])
              if a.get("status") == "DRAFT"]
    for assessment in sorted(drafts, key=lambda r: (r.get("created_at") or "", r.get("_seq") or 0)):
        assessment["status"] = "VOIDED"
        assessment["void_reason"] = "ASSESSOR_SUSPENDED"
        touch(assessment)
    return ok(serialize.assessor(assessor))


# --------------------------------------------------------------------------
# wrestlers
# --------------------------------------------------------------------------

@bp.post("/teams/<team_id>/wrestlers")
@endpoint("TeamCoach", "StateOffice")
def create_wrestler(team_id):
    team = lookups.team(team_id)
    require_team_owner(team["id"])
    body = V.get_body()
    full_name = V.req_str(body, "full_name", max_len=120, allow_empty=False)
    sex = V.req_enum(body, "sex", ("M", "F"))
    grade = V.req_int(body, "grade", minimum=9, maximum=12)
    season = lookups.season_of_team(team)
    if season is None:
        raise ApiError("ERR_SEASON_NOT_FOUND")
    require_open(season)
    row = new_row()
    row.update({
        "team_id": team["id"],
        "source_assessment_id": None,
        "full_name": full_name,
        "sex": sex,
        "grade": grade,
        "certification_status": "UNCERTIFIED",
        "eligibility_status": "INELIGIBLE",
        "alpha_weight_lbs": None,
        "body_fat_pct": None,
        "minimum_certified_weight_lbs": None,
        "min_weight_class_lbs": None,
        "lowest_eligible_class_lbs": None,
        "disqualified_at": None,
        "certification_hold_reason": None,
    })
    DB.wrestlers[row["id"]] = row
    return ok(serialize.wrestler(row), 201)


@bp.get("/wrestlers/<wrestler_id>")
@endpoint("StateOffice", "Assessor", "TeamCoach", "WeighInOfficial", "MedicalReviewer")
def read_wrestler(wrestler_id):
    return ok(serialize.wrestler(lookups.wrestler(wrestler_id)))


@bp.get("/wrestlers")
@endpoint("StateOffice", "Assessor", "TeamCoach", "WeighInOfficial", "MedicalReviewer")
def list_wrestlers():
    team_id = V.q_str("team_id")
    source_assessment_id = V.q_str("source_assessment_id")
    certification_status = V.q_enum("certification_status", CERTIFICATION_STATUSES)
    eligibility_status = V.q_enum("eligibility_status", ELIGIBILITY_STATUSES)
    limit, offset = V.pagination()
    rows = list(DB.wrestlers.values())
    if team_id is not None:
        rows = [r for r in rows if r.get("team_id") == team_id]
    if source_assessment_id is not None:
        rows = [r for r in rows if r.get("source_assessment_id") == source_assessment_id]
    if certification_status is not None:
        rows = [r for r in rows if r.get("certification_status") == certification_status]
    if eligibility_status is not None:
        rows = [r for r in rows if r.get("eligibility_status") == eligibility_status]
    rows = sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_seq") or 0))
    total = len(rows)
    return ok_list([serialize.wrestler(r) for r in V.window(rows, limit, offset)],
                   limit, offset, total)


@bp.post("/wrestlers/<wrestler_id>/disqualification")
@endpoint("StateOffice")
def disqualify_wrestler(wrestler_id):
    wrestler = lookups.wrestler(wrestler_id)
    body = V.get_body()
    flag = lookups.flag(V.req_id_ref(body, "health_flag_id"))
    reason = V.req_str(body, "reason", max_len=500, allow_empty=False)

    status = wrestler.get("certification_status")
    if status == "DISQUALIFIED":
        raise ApiError("ERR_WRESTLER_DISQUALIFIED",
                       "The wrestler is already disqualified.")
    if status not in ("PROVISIONAL", "CERTIFIED"):
        raise ApiError("ERR_WRESTLER_NOT_CERTIFIED",
                       "Only a PROVISIONAL or CERTIFIED wrestler may be disqualified.")
    if flag.get("status") != "ESCALATED" or flag.get("wrestler_id") != wrestler["id"]:
        raise ApiError("ERR_ESCALATED_FLAG_REQUIRED",
                       "Disqualification requires an ESCALATED flag on this wrestler.")

    wrestler["certification_status"] = "DISQUALIFIED"
    wrestler["disqualified_at"] = clock_iso()
    wrestler["certification_hold_reason"] = reason
    wrestler["eligibility_status"] = "INELIGIBLE"
    touch(wrestler)

    cascade.cancel_plans(wrestler["id"], ("DRAFT", "CERTIFIED", "BREACHED"), "DISQUALIFIED")

    entries = sorted(lookups.entries_of_wrestler(wrestler["id"]),
                     key=lambda r: (r.get("created_at") or "", r.get("_seq") or 0))
    for entry in entries:
        if entry.get("status") not in ("ENTERED", "WEIGHED_IN", "SEEDED"):
            continue
        held_seed = entry.get("seed_number") is not None
        entry["status"] = "DISQUALIFIED"
        entry["scratch_reason"] = "UNHEALTHY_WEIGHT_MANAGEMENT"
        if held_seed:
            entry["seed_number"] = None
        touch(entry)
        if held_seed:
            event = DB.events.get(entry.get("event_id"))
            if event is not None:
                event["reseed_required"] = True
                touch(event)
    return ok(serialize.wrestler(wrestler))
