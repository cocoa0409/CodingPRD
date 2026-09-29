"""Health flags, medical review and program audits."""

from flask import Blueprint

import calc
import cascade
import lookups
import serialize
import validate as V
from auth import endpoint, user_id
from envelope import ok, ok_list
from errors import ApiError
from routes.core import require_open
from store import DB, fmt_date, new_row, touch

bp = Blueprint("safety", __name__)

FLAG_SOURCES = ("HYDRATION_FAIL", "RAPID_LOSS", "PLAN_BREACH", "WEIGH_IN_DEFICIT")
FLAG_STATUSES = ("OPEN", "REVIEWED", "DISMISSED", "ESCALATED")
REVIEW_OUTCOMES = ("REVIEWED", "DISMISSED", "ESCALATED")
AUDIT_TYPES = ("ASSESSOR_SAMPLE", "TEAM_COMPLIANCE")
SCORING_VARIANTS = ("WORST_CASE", "SAMPLE_MEAN")
AUDIT_OUTCOMES = ("PASS", "FAIL", "INCONCLUSIVE")
AUDIT_STATUSES = ("OPEN", "FINALIZED")


# --------------------------------------------------------------------------
# health flags
# --------------------------------------------------------------------------

@bp.get("/health-flags/<flag_id>")
@endpoint("StateOffice", "TeamCoach", "MedicalReviewer")
def read_flag(flag_id):
    return ok(serialize.health_flag(lookups.flag(flag_id)))


@bp.get("/health-flags")
@endpoint("StateOffice", "TeamCoach", "MedicalReviewer", "WeighInOfficial")
def list_flags():
    wrestler_id = V.q_str("wrestler_id")
    weigh_in_id = V.q_str("weigh_in_id")
    source = V.q_enum("source", FLAG_SOURCES)
    status = V.q_enum("status", FLAG_STATUSES)
    limit, offset = V.pagination()
    rows = list(DB.flags.values())
    if wrestler_id is not None:
        rows = [r for r in rows if r.get("wrestler_id") == wrestler_id]
    if weigh_in_id is not None:
        rows = [r for r in rows if r.get("weigh_in_id") == weigh_in_id]
    if source is not None:
        rows = [r for r in rows if r.get("source") == source]
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]
    rows = sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_seq") or 0))
    total = len(rows)
    return ok_list([serialize.health_flag(r) for r in V.window(rows, limit, offset)],
                   limit, offset, total)


@bp.post("/health-flags/<flag_id>/review")
@endpoint("MedicalReviewer")
def review_flag(flag_id):
    flag = lookups.flag(flag_id)
    body = V.get_body()
    outcome = V.req_enum(body, "outcome", REVIEW_OUTCOMES)
    review_note = V.req_str(body, "review_note", max_len=500)

    current = flag.get("status")
    if current not in ("OPEN", "ESCALATED"):
        raise ApiError("ERR_HEALTH_FLAG_INVALID_STATE",
                       "A flag already in %s is not reviewable." % current)
    if current == "ESCALATED" and outcome != "DISMISSED":
        raise ApiError("ERR_HEALTH_FLAG_INVALID_STATE",
                       "An ESCALATED flag has exactly one exit: DISMISSED.")

    wrestler = DB.wrestlers.get(flag.get("wrestler_id"))
    team_id = wrestler.get("team_id") if wrestler else None
    was_probation = serialize.team_posture(team_id) == "PROBATION" if team_id else False

    flag["status"] = outcome
    flag["review_note"] = review_note
    flag["reviewer_user_id"] = user_id()
    touch(flag)

    # The severity ledger is derived from the flag rows, so REVIEWED and
    # DISMISSED withdraw the severity automatically while ESCALATED keeps it.
    if outcome in ("REVIEWED", "DISMISSED"):
        cascade.restore_from_probation(team_id, was_probation)
    return ok(serialize.health_flag(flag))


# --------------------------------------------------------------------------
# program audits
# --------------------------------------------------------------------------

def _samples(body, audit_type, assessor):
    if "samples" not in body or body["samples"] is None:
        raw = []
    else:
        raw = body["samples"]
        if not isinstance(raw, list):
            V.bad("Field 'samples' must be an array.")
    if audit_type == "TEAM_COMPLIANCE" and raw:
        V.bad("Field 'samples' must be empty or omitted for a TEAM_COMPLIANCE audit.")

    parsed = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            V.bad("Field 'samples[%d]' must be an object." % index)
        assessment_id = V.req_id_ref(item, "assessment_id")
        remeasured = V.req_num(item, "remeasured_body_fat_pct",
                               minimum=1.0, maximum=50.0)
        parsed.append({
            "assessment_id": assessment_id,
            "remeasured_body_fat_pct": remeasured,
        })

    # Body foreign keys of the samples resolve after the audit's own assessor_id.
    for sample in parsed:
        lookups.assessment(sample["assessment_id"])
    for sample in parsed:
        assessment = DB.assessments.get(sample["assessment_id"])
        if assessor is None or assessment.get("assessor_id") != assessor["id"]:
            raise ApiError("ERR_AUDIT_SAMPLE_MISMATCH",
                           "A sampled assessment was not produced by the audit's assessor.")
    return parsed


@bp.post("/seasons/<season_id>/audits")
@endpoint("StateOffice")
def create_audit(season_id):
    season = lookups.season(season_id)
    body = V.get_body()
    assessor_id = V.opt_id_ref(body, "assessor_id")
    assessor = lookups.assessor(assessor_id) if assessor_id is not None else None

    audit_type = V.req_enum(body, "audit_type", AUDIT_TYPES)
    scoring_variant = V.req_enum(body, "scoring_variant", SCORING_VARIANTS)
    window_start = V.req_date(body, "sample_window_start")
    if audit_type == "ASSESSOR_SAMPLE" and assessor is None:
        V.bad("Field 'assessor_id' is required for an ASSESSOR_SAMPLE audit.")
    if audit_type == "TEAM_COMPLIANCE" and assessor is not None:
        V.bad("Field 'assessor_id' must be null for a TEAM_COMPLIANCE audit.")
    samples = _samples(body, audit_type, assessor)

    require_open(season)

    if assessor is not None and assessor.get("status") != "CERTIFIED":
        raise ApiError("ERR_ASSESSOR_NOT_CERTIFIED",
                       "The referenced assessor's credential is not in force.")

    row = new_row()
    row.update({
        "season_id": season["id"],
        "assessor_id": assessor["id"] if assessor is not None else None,
        "audit_type": audit_type,
        "scoring_variant": scoring_variant,
        "sample_window_start": fmt_date(window_start),
        "samples": samples,
        "sample_count": len(samples),
        "discrepancy_score": None,
        "outcome": None,
        "voided_assessment_count": 0,
        "status": "OPEN",
    })
    DB.audits[row["id"]] = row
    return ok(serialize.audit(row), 201)


@bp.get("/audits/<audit_id>")
@endpoint("StateOffice", "Assessor")
def read_audit(audit_id):
    return ok(serialize.audit(lookups.audit(audit_id)))


@bp.get("/audits")
@endpoint("StateOffice", "Assessor")
def list_audits():
    season_id = V.q_str("season_id")
    assessor_id = V.q_str("assessor_id")
    audit_type = V.q_enum("audit_type", AUDIT_TYPES)
    outcome = V.q_enum("outcome", AUDIT_OUTCOMES)
    limit, offset = V.pagination()
    rows = list(DB.audits.values())
    if season_id is not None:
        rows = [r for r in rows if r.get("season_id") == season_id]
    if assessor_id is not None:
        rows = [r for r in rows if r.get("assessor_id") == assessor_id]
    if audit_type is not None:
        rows = [r for r in rows if r.get("audit_type") == audit_type]
    if outcome is not None:
        rows = [r for r in rows if r.get("outcome") == outcome]
    rows = sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_seq") or 0))
    total = len(rows)
    return ok_list([serialize.audit(r) for r in V.window(rows, limit, offset)],
                   limit, offset, total)


@bp.post("/audits/<audit_id>/finalize")
@endpoint("StateOffice")
def finalize_audit(audit_id):
    audit = lookups.audit(audit_id)
    season = DB.seasons.get(audit.get("season_id"))
    if season is None:
        raise ApiError("ERR_SEASON_NOT_FOUND")
    if audit.get("status") != "OPEN":
        raise ApiError("ERR_AUDIT_INVALID_STATE",
                       "Only an OPEN audit may be finalized.")

    score, outcome = calc.audit_discrepancy_score(season, audit)
    audit["discrepancy_score"] = score
    audit["outcome"] = outcome
    audit["status"] = "FINALIZED"
    touch(audit)

    if outcome == "FAIL" and audit.get("audit_type") == "ASSESSOR_SAMPLE":
        cascade.audit_fail_cascade(audit, season)
    return ok(serialize.audit(audit))
