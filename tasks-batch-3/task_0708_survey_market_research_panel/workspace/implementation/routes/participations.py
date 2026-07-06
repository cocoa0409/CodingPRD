"""Participation + AttentionCheck endpoints (PRD §2.6, §3.2, §3.3).

Participation tracks two independent axes: screening_status and
completion_status. submit is the bridge: it finalizes completion and drives the
screening axis to its terminal per the derived quality_status.
"""
import clock
import db
import errors
import lookup
import response
import validation
from middleware import get_identity, require_roles, require_owner
from services import calc, core, incentive, lifecycle

from flask import Blueprint, request

bp = Blueprint("participations", __name__)


@bp.post("/participations")
def create_participation():
    user_id, role = get_identity()
    require_roles(role, {"FieldCoordinator"})
    body = validation.get_json_body()
    study_id = validation.require_str(body, "study_id")
    panelist_id = validation.require_str(body, "panelist_id")
    quota_cell_id = validation.require_str(body, "quota_cell_id")

    # Existence left-to-right (PRD §2.5).
    study = lookup.study(study_id)
    panelist = lookup.panelist(panelist_id)
    cell = lookup.quota_cell(quota_cell_id)

    # Recruitment is open only while the study is FIELDING (PRD §3.1 "Launching
    # ... opens recruitment"; §3.4 pausing "freezes recruitment so that no new
    # participations are accepted while paused"). Mirrors the screen precondition
    # in §3.2 which names ERR_STUDY_NOT_FIELDING for a non-fielding study.
    if study["status"] != "FIELDING":
        errors.fail(errors.ERR_STUDY_NOT_FIELDING, "Study is not FIELDING")

    rec = db.base_record(common_fields=True)
    rec.update({
        "study_id": study_id,
        "panelist_id": panelist_id,
        "quota_cell_id": quota_cell_id,
        "screening_status": "SCREENING",
        "completion_status": "NOT_STARTED",
        "completion_seconds": None,
        "straightline_run": None,
        "quality_score": None,
        "quality_status": "PENDING",
        "provisional_points": None,
        "rescreen_count": 0,
    })
    db.participations[rec["id"]] = rec

    # Side effects: panelist last_activity + health recompute (lifetime_invited_n
    # is derived, so it picks up the new participation automatically).
    panelist["last_activity_at"] = clock.now_iso()
    db.touch(panelist)
    core.recompute_panelist_health(panelist)

    return response.object_response(core.serialize_participation(rec), status=201)


@bp.get("/participations")
def list_participations():
    user_id, role = get_identity()
    require_roles(role, {"ResearchManager", "PanelOps", "FieldCoordinator"})
    study_id = request.args.get("study_id")
    panelist_id = request.args.get("panelist_id")
    quota_cell_id = request.args.get("quota_cell_id")
    screening_status = request.args.get("screening_status")
    records = []
    for p in db.participations.values():
        if study_id is not None and p["study_id"] != study_id:
            continue
        if panelist_id is not None and p["panelist_id"] != panelist_id:
            continue
        if quota_cell_id is not None and p["quota_cell_id"] != quota_cell_id:
            continue
        if screening_status is not None and p["screening_status"] != screening_status:
            continue
        records.append(p)
    window, limit, offset, total = validation.paginate(records)
    return response.array_response(
        [core.serialize_participation(p) for p in window], limit, offset, total)


@bp.get("/participations/<pid>")
def get_participation(pid):
    user_id, role = get_identity()
    require_roles(role, {"ResearchManager", "PanelOps", "FieldCoordinator", "Panelist"})
    p = lookup.participation(pid)
    return response.object_response(core.serialize_participation(p))


@bp.post("/participations/<pid>/screen")
def screen(pid):
    user_id, role = get_identity()
    require_roles(role, {"FieldCoordinator"})
    p = lookup.participation(pid)
    body = validation.get_json_body()
    outcome = validation.require_enum(body, "outcome", {"IN", "OUT"})

    # State check (priority 5): only valid from SCREENING.
    if p["screening_status"] != "SCREENING":
        errors.fail(errors.ERR_INVALID_STATE, "Participation is not in SCREENING")

    study = lookup.study(p["study_id"])
    panelist = lookup.panelist(p["panelist_id"])
    cell = lookup.quota_cell(p["quota_cell_id"])

    # Study must be FIELDING for both IN and OUT (PRD §3.2).
    if study["status"] != "FIELDING":
        errors.fail(errors.ERR_STUDY_NOT_FIELDING, "Study is not FIELDING")

    if outcome == "OUT":
        p["screening_status"] = "SCREENED_OUT"
        db.touch(p)
        return response.object_response(core.serialize_participation(p))

    # outcome == IN: gated preconditions in priority order
    # (6) consent, (7) age, (11) quota seat.
    if not _has_valid_consent(panelist["id"], study):
        errors.fail(errors.ERR_CONSENT_REQUIRED, "No accepted consent at required version")
    if panelist["age"] < study["screener_min_age"]:
        errors.fail(errors.ERR_SCREENER_AGE_FAIL, "Panelist below screener_min_age")
    if core.cell_available_for_claim(cell, p["id"]) < 1:
        errors.fail(errors.ERR_QUOTA_CELL_FULL, "No available seat in quota cell")

    p["screening_status"] = "SCREENED_IN"
    incentive.create_provisional(p, study)
    db.touch(p)
    return response.object_response(core.serialize_participation(p))


def _has_valid_consent(panelist_id, study):
    required = study["required_consent_version"]
    for c in db.consents.values():
        if (c["panelist_id"] == panelist_id and c["study_id"] == study["id"]
                and c["decision"] == "ACCEPTED"
                and c["consent_version"] >= required):
            return True
    return False


@bp.post("/participations/<pid>/rescreen")
def rescreen(pid):
    user_id, role = get_identity()
    require_roles(role, {"FieldCoordinator"})
    p = lookup.participation(pid)

    if p["screening_status"] != "SCREENED_OUT":
        errors.fail(errors.ERR_INVALID_STATE, "Participation is not SCREENED_OUT")

    study = lookup.study(p["study_id"])
    cell = lookup.quota_cell(p["quota_cell_id"])

    if study["status"] != "FIELDING":
        errors.fail(errors.ERR_STUDY_NOT_FIELDING, "Study is not FIELDING")
    if core.cell_available_for_claim(cell, p["id"]) < 1:
        errors.fail(errors.ERR_QUOTA_CELL_FULL, "No available seat in quota cell")
    if p["rescreen_count"] >= calc.MAX_RESCREENS:
        errors.fail(errors.ERR_RESCREEN_LIMIT, "Rescreen limit reached")

    p["rescreen_count"] += 1
    p["screening_status"] = "SCREENING"
    db.touch(p)
    return response.object_response(core.serialize_participation(p))


@bp.post("/participations/<pid>/start")
def start(pid):
    user_id, role = get_identity()
    require_roles(role, {"Panelist"})
    p = lookup.participation(pid)
    require_owner(user_id, role, p["panelist_id"])

    if p["completion_status"] != "NOT_STARTED":
        errors.fail(errors.ERR_INVALID_STATE, "completion_status is not NOT_STARTED")
    if p["screening_status"] != "SCREENED_IN":
        errors.fail(errors.ERR_INVALID_STATE, "screening_status is not SCREENED_IN")

    p["completion_status"] = "IN_PROGRESS"
    db.touch(p)
    panelist = lookup.panelist(p["panelist_id"])
    panelist["last_activity_at"] = clock.now_iso()
    db.touch(panelist)
    return response.object_response(core.serialize_participation(p))


@bp.post("/participations/<pid>/submit")
def submit(pid):
    user_id, role = get_identity()
    require_roles(role, {"Panelist"})
    p = lookup.participation(pid)
    require_owner(user_id, role, p["panelist_id"])

    # State (priority 5): completion must be IN_PROGRESS and screening SCREENED_IN.
    if p["completion_status"] != "IN_PROGRESS":
        errors.fail(errors.ERR_INVALID_STATE, "completion_status is not IN_PROGRESS")
    if p["screening_status"] != "SCREENED_IN":
        errors.fail(errors.ERR_INVALID_STATE, "screening_status is not SCREENED_IN")

    body = validation.get_json_body()
    if "completion_seconds" not in body or "straightline_run" not in body:
        errors.fail(errors.ERR_SUBMIT_FIELDS_MISSING,
                    "completion_seconds and straightline_run are required")
    completion_seconds = validation.require_int(body, "completion_seconds")
    straightline_run = validation.require_int(body, "straightline_run")

    study = lookup.study(p["study_id"])
    panelist = lookup.panelist(p["panelist_id"])

    # Aggregate attention checks for this participation.
    passed = total = 0
    for ac in db.attention_checks.values():
        if ac["participation_id"] == p["id"]:
            total += 1
            if ac["passed"]:
                passed += 1

    score = calc.quality_score(passed, total, completion_seconds,
                               straightline_run, study["estimated_minutes"])
    status = calc.quality_status_from_score(score)

    p["completion_status"] = "COMPLETED"
    p["completion_seconds"] = completion_seconds
    p["straightline_run"] = straightline_run
    p["quality_score"] = score
    p["quality_status"] = status

    # Drive screening axis from quality_status (PRD §3.3).
    if status in ("PASS", "FLAGGED"):
        p["screening_status"] = "QUALIFIED"
        incentive.finalize(p, score)
    else:  # FAIL
        p["screening_status"] = "SCREENED_OUT"
        incentive.void_hold(p)

    db.touch(p)

    # Panelist side effects (lifetime_completed_n derived; refresh activity + health).
    panelist["last_activity_at"] = clock.now_iso()
    db.touch(panelist)
    core.recompute_panelist_health(panelist)

    return response.object_response(core.serialize_participation(p))


@bp.post("/participations/<pid>/abandon")
def abandon(pid):
    user_id, role = get_identity()
    require_roles(role, {"Panelist"})
    p = lookup.participation(pid)
    require_owner(user_id, role, p["panelist_id"])

    if p["completion_status"] != "IN_PROGRESS":
        errors.fail(errors.ERR_INVALID_STATE, "completion_status is not IN_PROGRESS")

    p["completion_status"] = "ABANDONED"
    # Cross-axis cascade: SCREENING/SCREENED_IN -> VOIDED (seat released, hold void).
    lifecycle.void_participation(p)
    db.touch(p)
    return response.object_response(core.serialize_participation(p))


# ----- Attention checks -----
@bp.post("/participations/<pid>/attention-checks")
def create_attention_check(pid):
    user_id, role = get_identity()
    require_roles(role, {"FieldCoordinator"})
    p = lookup.participation(pid)
    body = validation.get_json_body()
    check_kind = validation.require_enum(
        body, "check_kind", {"TRAP_QUESTION", "INSTRUCTED_RESPONSE", "TIMING"})
    passed = validation.require_bool(body, "passed")

    rec = db.base_record(common_fields=False)
    rec.update({
        "participation_id": p["id"],
        "check_kind": check_kind,
        "passed": passed,
        "recorded_at": clock.now_iso(),
    })
    db.attention_checks[rec["id"]] = rec
    return response.object_response(core.serialize_attention_check(rec), status=201)


@bp.get("/participations/<pid>/attention-checks")
def list_attention_checks(pid):
    user_id, role = get_identity()
    require_roles(role, {"ResearchManager", "FieldCoordinator"})
    p = lookup.participation(pid)
    records = [ac for ac in db.attention_checks.values()
               if ac["participation_id"] == p["id"]]
    window, limit, offset, total = validation.paginate(records)
    return response.array_response(
        [core.serialize_attention_check(ac) for ac in window], limit, offset, total)
