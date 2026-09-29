"""Body-composition assessments, the hydration fork, and appeals."""

from datetime import timedelta

from flask import Blueprint

import calc
import cascade
import lookups
import serialize
import validate as V
from auth import endpoint, require_team_owner, user_id
from envelope import ok, ok_list
from errors import ApiError
from routes.core import require_open
from routes.people import METHODS
from store import DB, clock_date, clock_dt, clock_iso, new_row, parse_date, touch

bp = Blueprint("assess", __name__)

ASSESSMENT_STATUSES = ("DRAFT", "VALIDATED", "HYDRATION_FAILED", "VOIDED", "SUPERSEDED")
APPEAL_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "RETEST_ORDERED", "RETEST_COMPLETED",
                   "UPHELD", "DENIED", "WITHDRAWN")


# --------------------------------------------------------------------------
# assessments
# --------------------------------------------------------------------------

@bp.post("/wrestlers/<wrestler_id>/assessments")
@endpoint("Assessor")
def create_assessment(wrestler_id):
    wrestler = lookups.wrestler(wrestler_id)
    body = V.get_body()

    # body foreign keys, resolved in the order the fields are listed
    assessor = lookups.assessor(V.req_id_ref(body, "assessor_id"))
    appeal_id = V.opt_id_ref(body, "appeal_id")
    appeal = lookups.appeal(appeal_id) if appeal_id is not None else None
    retest_of_id = V.opt_id_ref(body, "retest_of_assessment_id")
    retest_of = lookups.assessment(retest_of_id) if retest_of_id is not None else None

    # ownership
    if assessor["id"] != user_id():
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "assessor_id must equal the acting assessor's X-User-ID.")

    # shape
    method = V.req_enum(body, "method", METHODS)
    assessed_raw, assessed_dt = V.req_datetime(body, "assessed_at")
    measured_weight_lbs = V.req_num(body, "measured_weight_lbs", minimum=60.0, maximum=400.0)
    body_fat_pct = V.req_num(body, "body_fat_pct", minimum=1.0, maximum=50.0)
    urine_specific_gravity = V.req_num(body, "urine_specific_gravity",
                                       minimum=1.000, maximum=1.060)

    # disqualified-wrestler freeze, then the season-open requirement
    if wrestler.get("certification_status") == "DISQUALIFIED":
        raise ApiError("ERR_WRESTLER_DISQUALIFIED",
                       "A disqualified wrestler cannot be assessed.")
    season = lookups.season_of_wrestler(wrestler)
    if season is None:
        raise ApiError("ERR_SEASON_NOT_FOUND")
    require_open(season)

    # domain guards
    if assessor.get("status") != "CERTIFIED":
        raise ApiError("ERR_ASSESSOR_NOT_CERTIFIED",
                       "The acting assessor's credential is not in force.")
    if method not in (assessor.get("certified_methods") or []):
        raise ApiError("ERR_METHOD_NOT_CERTIFIED",
                       "The method is not among the assessor's certified_methods.")

    contested = None
    if appeal is not None:
        contested = DB.assessments.get(appeal.get("assessment_id"))
    if ((contested is not None and contested.get("assessor_id") == assessor["id"])
            or (retest_of is not None and retest_of.get("assessor_id") == assessor["id"])):
        raise ApiError("ERR_SAME_ASSESSOR_CONFLICT",
                       "The assessor who produced the contested result may not retest it.")
    if retest_of is not None and retest_of.get("wrestler_id") != wrestler["id"]:
        raise ApiError("ERR_ASSESSMENT_WRESTLER_MISMATCH",
                       "retest_of_assessment_id belongs to a different wrestler.")

    assessed_date = assessed_dt.date()
    same_day = [
        a for a in lookups.assessments_of_assessor(assessor["id"])
        if a.get("status") != "VOIDED" and a.get("_assessed_date") == assessed_date
    ]
    if len(same_day) >= int(season.get("assessor_daily_assessment_capacity")):
        raise ApiError("ERR_ASSESSOR_DAY_CAPACITY_EXCEEDED",
                       "The assessor's daily assessment capacity is exhausted.")

    row = new_row()
    row.update({
        "wrestler_id": wrestler["id"],
        "assessor_id": assessor["id"],
        "retest_of_assessment_id": retest_of_id,
        "appeal_id": appeal_id,
        "method": method,
        "assessed_at": assessed_raw,
        "_assessed_date": assessed_date,
        "_assessed_dt": assessed_dt,
        "measured_weight_lbs": measured_weight_lbs,
        "body_fat_pct": body_fat_pct,
        "urine_specific_gravity": urine_specific_gravity,
        "status": "DRAFT",
        "hydration_passed": None,
        "lean_body_weight_lbs": None,
        "minimum_certified_weight_lbs": None,
        "min_weight_class_lbs": None,
        "alpha_weight_lbs": None,
        "void_reason": None,
    })
    DB.assessments[row["id"]] = row
    return ok(serialize.assessment(row), 201)


@bp.post("/assessments/<assessment_id>/finalize")
@endpoint("Assessor")
def finalize_assessment(assessment_id):
    assessment = lookups.assessment(assessment_id)
    if assessment.get("assessor_id") != user_id():
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "Only the assessment's own assessor may finalize it.")
    wrestler = DB.wrestlers.get(assessment.get("wrestler_id"))
    season = lookups.season_of_wrestler(wrestler) if wrestler else None
    if season is None:
        raise ApiError("ERR_SEASON_NOT_FOUND")
    require_open(season)
    if assessment.get("status") != "DRAFT":
        raise ApiError("ERR_ASSESSMENT_INVALID_STATE",
                       "Only a DRAFT assessment may be finalized.")

    assessor = DB.assessors.get(assessment.get("assessor_id"))
    if assessor is None:
        raise ApiError("ERR_ASSESSOR_NOT_FOUND")
    # Credential lapse is discovered lazily, here, and is persisted before the
    # finalize is refused.
    expires_on = parse_date(assessor.get("certification_expires_on"))
    if (assessor.get("status") == "CERTIFIED" and expires_on is not None
            and clock_date() >= expires_on):
        assessor["status"] = "EXPIRED"
        touch(assessor)
    if assessor.get("status") != "CERTIFIED":
        raise ApiError("ERR_ASSESSOR_NOT_CERTIFIED",
                       "The assessor's credential is not in force.")
    if assessment.get("method") not in (assessor.get("certified_methods") or []):
        raise ApiError("ERR_METHOD_NOT_CERTIFIED",
                       "The method is no longer among the assessor's certified_methods.")

    hydration_passed = calc.D(assessment.get("urine_specific_gravity")) <= calc.D(
        season.get("hydration_max_specific_gravity"))

    if hydration_passed:
        lean, min_cert, min_class = calc.minimum_certified_weight(
            season, wrestler.get("sex"),
            assessment.get("measured_weight_lbs"), assessment.get("body_fat_pct"))
        if min_class is None:
            raise ApiError("ERR_NO_ELIGIBLE_WEIGHT_CLASS",
                           "No weight class is greater than or equal to the computed minimum.")
        assessment["hydration_passed"] = True
        assessment["lean_body_weight_lbs"] = lean
        assessment["minimum_certified_weight_lbs"] = min_cert
        assessment["min_weight_class_lbs"] = min_class
        assessment["alpha_weight_lbs"] = assessment.get("measured_weight_lbs")
        assessment["status"] = "VALIDATED"
        touch(assessment)

        protected = None
        appeal = DB.appeals.get(assessment.get("appeal_id"))
        if appeal is not None:
            protected = appeal.get("assessment_id")
        siblings = sorted(lookups.assessments_of_wrestler(wrestler["id"]),
                          key=lambda r: (r.get("created_at") or "", r.get("_seq") or 0))
        for other in siblings:
            if other["id"] == assessment["id"] or other.get("status") != "VALIDATED":
                continue
            if protected is not None and other["id"] == protected:
                continue
            other["status"] = "SUPERSEDED"
            touch(other)

        previous = wrestler.get("certification_status")
        cascade.repoint_wrestler_figures(wrestler, assessment, season)
        if previous in ("UNCERTIFIED", "SUSPENDED"):
            wrestler["certification_status"] = "PROVISIONAL"
            wrestler["certification_hold_reason"] = None
        touch(wrestler)
    else:
        assessment["hydration_passed"] = False
        assessment["lean_body_weight_lbs"] = None
        assessment["minimum_certified_weight_lbs"] = None
        assessment["min_weight_class_lbs"] = None
        assessment["alpha_weight_lbs"] = None
        assessment["status"] = "HYDRATION_FAILED"
        touch(assessment)
        cascade.raise_flag(wrestler, "HYDRATION_FAIL")

    # shared appeal bookkeeping, taken on either arm
    appeal = DB.appeals.get(assessment.get("appeal_id"))
    if appeal is not None:
        appeal["retest_assessment_id"] = assessment["id"]
        if appeal.get("status") == "RETEST_ORDERED":
            appeal["status"] = "RETEST_COMPLETED"
        touch(appeal)

    return ok(serialize.assessment(assessment))


@bp.get("/assessments/<assessment_id>")
@endpoint("StateOffice", "Assessor", "TeamCoach", "MedicalReviewer")
def read_assessment(assessment_id):
    return ok(serialize.assessment(lookups.assessment(assessment_id)))


@bp.get("/assessments")
@endpoint("StateOffice", "Assessor", "TeamCoach", "MedicalReviewer")
def list_assessments():
    wrestler_id = V.q_str("wrestler_id")
    assessor_id = V.q_str("assessor_id")
    retest_of = V.q_str("retest_of_assessment_id")
    appeal_id = V.q_str("appeal_id")
    status = V.q_enum("status", ASSESSMENT_STATUSES)
    limit, offset = V.pagination()
    rows = list(DB.assessments.values())
    if wrestler_id is not None:
        rows = [r for r in rows if r.get("wrestler_id") == wrestler_id]
    if assessor_id is not None:
        rows = [r for r in rows if r.get("assessor_id") == assessor_id]
    if retest_of is not None:
        rows = [r for r in rows if r.get("retest_of_assessment_id") == retest_of]
    if appeal_id is not None:
        rows = [r for r in rows if r.get("appeal_id") == appeal_id]
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]
    rows = sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_seq") or 0))
    total = len(rows)
    return ok_list([serialize.assessment(r) for r in V.window(rows, limit, offset)],
                   limit, offset, total)


# --------------------------------------------------------------------------
# appeals
# --------------------------------------------------------------------------

@bp.post("/assessments/<assessment_id>/appeals")
@endpoint("TeamCoach")
def file_appeal(assessment_id):
    assessment = lookups.assessment(assessment_id)
    body = V.get_body()
    team = lookups.team(V.req_id_ref(body, "team_id"))
    wrestler = DB.wrestlers.get(assessment.get("wrestler_id"))
    require_team_owner(team["id"])
    if wrestler is None or wrestler.get("team_id") != team["id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "The filing team does not own the contested assessment's wrestler.")
    reason = V.req_str(body, "reason", max_len=500, allow_empty=False)

    season = lookups.season_of_wrestler(wrestler)
    if season is None:
        raise ApiError("ERR_SEASON_NOT_FOUND")

    assessed_dt = assessment.get("_assessed_dt")
    if assessed_dt is not None:
        deadline = assessed_dt + timedelta(days=int(season.get("appeal_filing_window_days")))
        if clock_dt() > deadline:
            raise ApiError("ERR_APPEAL_WINDOW_EXPIRED",
                           "The appeal filing window for that assessment has closed.")

    rounds = sum(int(a.get("retest_round_count") or 0)
                 for a in lookups.appeals_of_assessment(assessment["id"]))
    if rounds >= int(season.get("max_appeal_retest_rounds")):
        raise ApiError("ERR_APPEAL_ROUND_LIMIT",
                       "That assessment has exhausted its retest rounds.")

    row = new_row()
    row.update({
        "assessment_id": assessment["id"],
        "team_id": team["id"],
        "reviewing_assessor_id": None,
        "retest_assessment_id": None,
        "reason": reason,
        "filed_at": clock_iso(),
        "status": "SUBMITTED",
        "retest_round_count": 0,
        "decision_note": None,
    })
    DB.appeals[row["id"]] = row
    return ok(serialize.appeal(row), 201)


@bp.get("/appeals/<appeal_id>")
@endpoint("StateOffice", "Assessor", "TeamCoach")
def read_appeal(appeal_id):
    return ok(serialize.appeal(lookups.appeal(appeal_id)))


@bp.get("/appeals")
@endpoint("StateOffice", "Assessor", "TeamCoach")
def list_appeals():
    assessment_id = V.q_str("assessment_id")
    team_id = V.q_str("team_id")
    reviewing_assessor_id = V.q_str("reviewing_assessor_id")
    retest_assessment_id = V.q_str("retest_assessment_id")
    status = V.q_enum("status", APPEAL_STATUSES)
    limit, offset = V.pagination()
    rows = list(DB.appeals.values())
    if assessment_id is not None:
        rows = [r for r in rows if r.get("assessment_id") == assessment_id]
    if team_id is not None:
        rows = [r for r in rows if r.get("team_id") == team_id]
    if reviewing_assessor_id is not None:
        rows = [r for r in rows if r.get("reviewing_assessor_id") == reviewing_assessor_id]
    if retest_assessment_id is not None:
        rows = [r for r in rows if r.get("retest_assessment_id") == retest_assessment_id]
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]
    rows = sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_seq") or 0))
    total = len(rows)
    return ok_list([serialize.appeal(r) for r in V.window(rows, limit, offset)],
                   limit, offset, total)


@bp.post("/appeals/<appeal_id>/assign-reviewer")
@endpoint("StateOffice")
def assign_reviewer(appeal_id):
    appeal = lookups.appeal(appeal_id)
    body = V.get_body()
    reviewer = lookups.assessor(V.req_id_ref(body, "reviewing_assessor_id"))
    if appeal.get("status") != "SUBMITTED":
        raise ApiError("ERR_APPEAL_INVALID_STATE",
                       "A reviewer may only be assigned to a SUBMITTED appeal.")
    contested = DB.assessments.get(appeal.get("assessment_id"))
    if contested is not None and contested.get("assessor_id") == reviewer["id"]:
        raise ApiError("ERR_SAME_ASSESSOR_CONFLICT",
                       "The reviewing assessor may not be the assessor under appeal.")
    if reviewer.get("status") != "CERTIFIED":
        raise ApiError("ERR_ASSESSOR_NOT_CERTIFIED",
                       "The reviewing assessor's credential is not in force.")
    appeal["reviewing_assessor_id"] = reviewer["id"]
    appeal["status"] = "UNDER_REVIEW"
    touch(appeal)
    return ok(serialize.appeal(appeal))


def _require_reviewer(appeal):
    reviewer_id = appeal.get("reviewing_assessor_id")
    if reviewer_id is not None and user_id() != reviewer_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "Only the appeal's reviewing assessor may act on it.")


@bp.post("/appeals/<appeal_id>/order-retest")
@endpoint("Assessor")
def order_retest(appeal_id):
    appeal = lookups.appeal(appeal_id)
    _require_reviewer(appeal)
    if appeal.get("status") not in ("UNDER_REVIEW", "RETEST_COMPLETED"):
        raise ApiError("ERR_APPEAL_INVALID_STATE",
                       "A retest may only be ordered out of UNDER_REVIEW or RETEST_COMPLETED.")
    season = _season_of_appeal(appeal)
    if int(appeal.get("retest_round_count") or 0) >= int(season.get("max_appeal_retest_rounds")):
        raise ApiError("ERR_APPEAL_INVALID_STATE",
                       "The appeal has exhausted its permitted retest rounds.")
    appeal["retest_round_count"] = int(appeal.get("retest_round_count") or 0) + 1
    appeal["status"] = "RETEST_ORDERED"
    touch(appeal)
    return ok(serialize.appeal(appeal))


def _season_of_appeal(appeal):
    assessment = DB.assessments.get(appeal.get("assessment_id"))
    wrestler = DB.wrestlers.get(assessment.get("wrestler_id")) if assessment else None
    season = lookups.season_of_wrestler(wrestler) if wrestler else None
    if season is None:
        season = DB.seasons.get(DB.teams.get(appeal.get("team_id"), {}).get("season_id"))
    if season is None:
        raise ApiError("ERR_SEASON_NOT_FOUND")
    return season


@bp.post("/appeals/<appeal_id>/decide")
@endpoint("Assessor")
def decide_appeal(appeal_id):
    appeal = lookups.appeal(appeal_id)
    _require_reviewer(appeal)
    body = V.get_body()
    outcome = V.req_enum(body, "outcome", ("UPHELD", "DENIED"))
    decision_note = V.req_str(body, "decision_note", max_len=500)

    status = appeal.get("status")
    if outcome == "DENIED":
        if status not in ("UNDER_REVIEW", "RETEST_COMPLETED"):
            raise ApiError("ERR_APPEAL_INVALID_STATE",
                           "DENIED is accepted out of UNDER_REVIEW or RETEST_COMPLETED only.")
        appeal["status"] = "DENIED"
        appeal["decision_note"] = decision_note
        touch(appeal)
        return ok(serialize.appeal(appeal))

    if status != "RETEST_COMPLETED":
        raise ApiError("ERR_APPEAL_INVALID_STATE",
                       "UPHELD is accepted out of RETEST_COMPLETED only.")
    retest = DB.assessments.get(appeal.get("retest_assessment_id"))
    if retest is None or retest.get("status") != "VALIDATED":
        raise ApiError("ERR_APPEAL_INVALID_STATE",
                       "An upheld appeal requires a VALIDATED retest assessment.")

    contested = DB.assessments.get(appeal.get("assessment_id"))
    wrestler = DB.wrestlers.get(contested.get("wrestler_id")) if contested else None
    season = lookups.season_of_wrestler(wrestler) if wrestler else None

    # hop 1 -- the contested assessment is voided
    if contested is not None and contested.get("status") == "VALIDATED":
        contested["status"] = "VOIDED"
        contested["void_reason"] = "APPEAL_UPHELD:%s" % appeal["id"]
        touch(contested)

    # hop 2 -- the wrestler is repointed at the retest
    if wrestler is not None:
        cascade.repoint_wrestler_figures(wrestler, retest, season)
        touch(wrestler)

        # hop 3 -- a plan whose target now sits below the raised floor is cancelled
        new_floor = wrestler.get("min_weight_class_lbs")
        cancelled = []
        for plan in sorted(lookups.plans_of_wrestler(wrestler["id"]),
                           key=lambda r: (r.get("created_at") or "", r.get("_seq") or 0)):
            if plan.get("status") not in ("CERTIFIED", "BREACHED"):
                continue
            if new_floor is None or int(plan.get("target_class_lbs")) >= int(new_floor):
                continue
            plan["status"] = "CANCELLED"
            plan["cancel_reason"] = "MINIMUM_RAISED"
            touch(plan)
            cancelled.append(plan)

        # hop 4 -- because a plan was cancelled, live entries are scratched
        if cancelled:
            cascade.scratch_entries(wrestler["id"], ("ENTERED", "WEIGHED_IN"),
                                    "PLAN_CANCELLED")

    appeal["status"] = "UPHELD"
    appeal["decision_note"] = decision_note
    touch(appeal)
    return ok(serialize.appeal(appeal))
