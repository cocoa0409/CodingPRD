"""Routes: match records, team training classes, enrollments, public access tests."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, jsonify, request

from core import (
    STORE,
    ApiError,
    _meta,
    base_fields,
    body,
    check_terminal,
    err_invalid_state,
    err_ownership,
    err_ref_not_found,
    err_validation,
    get_or_404,
    list_all,
    now,
    paginate,
    require_roles,
    respond,
    round_half_up_1dp,
    today,
    touch,
    v_date,
    v_datetime,
    v_int,
    v_str,
)
from services import (
    dissolve_match,
    effective_requirement,
    enrollment_for_match,
    latest_accepted_assessment,
    ser_class,
    ser_enrollment,
    ser_match,
    ser_partnership,
    ser_pat,
    withdraw_enrollment,
)

bp = Blueprint("match", __name__)


def _q(name):
    v = request.args.get(name)
    return v if v not in (None, "") else None


def _array(data):
    return jsonify({"meta": _meta(), "response_type": "array", "data": data}), 200


# ---------------------------------------------------------------------------
# Match records
# ---------------------------------------------------------------------------
@bp.route("/api/dogs/<rid>/match-proposals", methods=["POST"])
def propose_match(rid):
    b = body()
    expected_dog_version = v_int(b, "expected_dog_version")
    entry_id = b.get("waitlist_entry_id")
    if entry_id is not None and not isinstance(entry_id, str):
        raise err_validation("waitlist_entry_id must be a string")
    role, uid = require_roles("IntakeCoordinator")
    d = get_or_404("dogs", rid)
    entry = None
    if entry_id is not None:
        entry = STORE["waitlist_entries"].get(entry_id)
        if entry is None:
            raise err_ref_not_found("waitlist_entry_id does not resolve")
    # OCC on dog version
    if expected_dog_version != d["version"]:
        raise ApiError(
            "ERR_STALE_DOG_VERSION", 412, "expected_dog_version does not match"
        )
    check_terminal("dogs", d)
    if d["status"] != "MATCH_READY":
        raise err_invalid_state("Dog is not MATCH_READY")
    certified = set(d["certified_tasks"])
    if entry is not None:
        # explicit pick
        if entry["status"] != "ELIGIBLE":
            raise err_invalid_state("Waitlist entry is not ELIGIBLE")
        assessment = latest_accepted_assessment(entry["applicant_id"])
        required = set(assessment["required_tasks"]) if assessment else set()
        if not required.issubset(certified):
            raise ApiError(
                "ERR_TASK_COVERAGE_INSUFFICIENT",
                422,
                "Dog certified_tasks do not cover required tasks",
            )
    else:
        # selector mode
        pool = []
        for e in STORE["waitlist_entries"].values():
            if e["status"] != "ELIGIBLE":
                continue
            assessment = latest_accepted_assessment(e["applicant_id"])
            if assessment is None:
                continue
            if not set(assessment["required_tasks"]).issubset(certified):
                continue
            pool.append(e)
        if not pool:
            raise ApiError(
                "ERR_NO_ELIGIBLE_MATCH", 409, "No eligible waitlist entry"
            )

        def _rank_key(e):
            applicant = STORE["applicants"].get(e["applicant_id"])
            a_seq = applicant["_seq"] if applicant else 0
            return (-e["rank_score"], e["listed_at"], a_seq)

        pool.sort(key=_rank_key)
        entry = pool[0]

    m = base_fields()
    m.update(
        {
            "dog_id": d["id"],
            "waitlist_entry_id": entry["id"],
            "status": "PROPOSED",
            "proposed_by_user_id": uid,
            "rank_score_at_match": entry["rank_score"],
        }
    )
    STORE["matches"][m["id"]] = m
    touch(d)
    return respond(ser_match(m), 201)


@bp.route("/api/matches/<rid>", methods=["GET"])
def get_match(rid):
    role, uid = require_roles("IntakeCoordinator", "ProgramAdmin", "TrainingDirector")
    m = get_or_404("matches", rid)
    return respond(ser_match(m))


@bp.route("/api/matches/<rid>/accept", methods=["POST"])
def accept_match(rid):
    role, uid = require_roles("IntakeCoordinator")
    m = get_or_404("matches", rid)
    check_terminal("matches", m)
    if m["status"] != "PROPOSED":
        raise err_invalid_state("Match is not PROPOSED")
    d = get_or_404("dogs", m["dog_id"])
    if d["status"] != "MATCH_READY":
        raise err_invalid_state("Dog is not MATCH_READY")
    entry = get_or_404("waitlist_entries", m["waitlist_entry_id"])
    if entry["status"] != "ELIGIBLE":
        raise err_invalid_state("Waitlist entry is not ELIGIBLE")
    m["status"] = "ACCEPTED"
    touch(m)
    d["status"] = "MATCHED"
    touch(d)
    entry["status"] = "MATCHED"
    touch(entry)
    applicant = get_or_404("applicants", entry["applicant_id"])
    if applicant["application_status"] == "MATCH_ELIGIBLE":
        applicant["application_status"] = "MATCHED"
        touch(applicant)
    return respond(ser_match(m))


@bp.route("/api/matches/<rid>/reject", methods=["POST"])
def reject_match(rid):
    role, uid = require_roles("IntakeCoordinator")
    m = get_or_404("matches", rid)
    check_terminal("matches", m)
    if m["status"] != "PROPOSED":
        raise err_invalid_state("Match is not PROPOSED")
    m["status"] = "REJECTED"
    touch(m)
    return respond(ser_match(m))


@bp.route("/api/matches/<rid>/dissolve", methods=["POST"])
def dissolve_match_route(rid):
    role, uid = require_roles("IntakeCoordinator")
    m = get_or_404("matches", rid)
    check_terminal("matches", m)
    if m["status"] != "ACCEPTED":
        raise err_invalid_state("Match is not ACCEPTED")
    dissolve_match(m)
    return respond(ser_match(m))


@bp.route("/api/matches/<rid>/enrollments", methods=["GET"])
def match_enrollments(rid):
    role, uid = require_roles("IntakeCoordinator", "ProgramAdmin", "TrainingDirector")
    m = get_or_404("matches", rid)
    items = [e for e in STORE["enrollments"].values() if e["match_id"] == m["id"]]
    return list_all(items, ser_enrollment)


# ---------------------------------------------------------------------------
# Team training classes
# ---------------------------------------------------------------------------
@bp.route("/api/classes", methods=["POST"])
def create_class():
    b = body()
    name = v_str(b, "name")
    lead_trainer_id = v_str(b, "lead_trainer_id")
    starts_on = v_date(b, "starts_on")
    ends_on = v_date(b, "ends_on")
    capacity = v_int(b, "capacity", min_v=2, max_v=6)
    total_sessions = v_int(b, "total_sessions", min_v=1)
    if ends_on <= starts_on:
        raise err_validation("ends_on must be strictly later than starts_on")
    role, uid = require_roles("TrainingDirector")
    trainer = STORE["trainers"].get(lead_trainer_id)
    if trainer is None:
        raise err_ref_not_found("lead_trainer_id does not resolve")
    # half-open [starts_on, ends_on) overlap vs other non-CANCELLED classes
    for c in STORE["classes"].values():
        if c["lead_trainer_id"] != lead_trainer_id:
            continue
        if c["status"] == "CANCELLED":
            continue
        if starts_on < c["ends_on"] and ends_on > c["starts_on"]:
            raise ApiError(
                "ERR_TRAINER_SCHEDULE_CONFLICT",
                409,
                "Lead trainer has an overlapping class",
            )
    c = base_fields()
    c.update(
        {
            "name": name,
            "lead_trainer_id": lead_trainer_id,
            "starts_on": starts_on,
            "ends_on": ends_on,
            "capacity": capacity,
            "total_sessions": total_sessions,
            "status": "PLANNED",
            "enrolled_count": 0,
        }
    )
    STORE["classes"][c["id"]] = c
    return respond(ser_class(c), 201)


@bp.route("/api/classes/<rid>", methods=["GET"])
def get_class(rid):
    role, uid = require_roles(
        "ProgramAdmin", "TrainingDirector", "Trainer", "IntakeCoordinator"
    )
    c = get_or_404("classes", rid)
    return respond(ser_class(c))


@bp.route("/api/classes", methods=["GET"])
def list_classes():
    role, uid = require_roles("ProgramAdmin", "TrainingDirector", "IntakeCoordinator")
    items = list(STORE["classes"].values())
    status = _q("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    lead = _q("lead_trainer_id")
    if lead is not None:
        items = [c for c in items if c["lead_trainer_id"] == lead]
    return paginate(items, ser_class)


def _class_action(rid, allowed_from):
    role, uid = require_roles("TrainingDirector")
    c = get_or_404("classes", rid)
    check_terminal("classes", c)
    if c["status"] not in allowed_from:
        raise err_invalid_state("Class status %s not permitted" % c["status"])
    return c


@bp.route("/api/classes/<rid>/open-enrollment", methods=["POST"])
def open_enrollment(rid):
    c = _class_action(rid, {"PLANNED"})
    trainer = STORE["trainers"].get(c["lead_trainer_id"])
    if trainer is None or trainer["status"] != "CERTIFIED":
        raise err_invalid_state("Lead trainer must be CERTIFIED")
    c["status"] = "ENROLLING"
    touch(c)
    return respond(ser_class(c))


@bp.route("/api/classes/<rid>/start", methods=["POST"])
def start_class(rid):
    c = _class_action(rid, {"ENROLLING"})
    if c["enrolled_count"] < 1:
        raise ApiError(
            "ERR_CLASS_TOO_SMALL", 409, "Class requires at least one enrolled pair"
        )
    if today() < c["starts_on"]:
        raise ApiError(
            "ERR_ENROLLMENT_WINDOW",
            409,
            "Class cannot start before its starts_on date",
        )
    c["status"] = "IN_SESSION"
    touch(c)
    return respond(ser_class(c))


@bp.route("/api/classes/<rid>/begin-graduation-review", methods=["POST"])
def begin_graduation_review(rid):
    c = _class_action(rid, {"IN_SESSION"})
    if today() <= c["ends_on"]:
        raise ApiError(
            "ERR_ENROLLMENT_WINDOW",
            409,
            "Graduation review requires the logical date after ends_on",
        )
    c["status"] = "GRADUATION_REVIEW"
    touch(c)
    return respond(ser_class(c))


@bp.route("/api/classes/<rid>/complete", methods=["POST"])
def complete_class(rid):
    c = _class_action(rid, {"GRADUATION_REVIEW"})
    for e in STORE["enrollments"].values():
        if e["class_id"] == c["id"] and e["status"] not in (
            "GRADUATED",
            "FAILED",
            "WITHDRAWN",
        ):
            raise err_invalid_state("All enrollments must be terminal")
    c["status"] = "COMPLETED"
    touch(c)
    return respond(ser_class(c))


@bp.route("/api/classes/<rid>/cancel", methods=["POST"])
def cancel_class(rid):
    c = _class_action(rid, {"PLANNED", "ENROLLING", "IN_SESSION"})
    enrolled = [
        e
        for e in STORE["enrollments"].values()
        if e["class_id"] == c["id"] and e["status"] == "ENROLLED"
    ]
    enrolled.sort(key=lambda e: e["_seq"])
    c["status"] = "CANCELLED"
    for e in enrolled:
        withdraw_enrollment(e, mode="class_cancel")
    c["enrolled_count"] = 0
    touch(c)
    return respond(ser_class(c))


@bp.route("/api/classes/<rid>/enrollments", methods=["GET"])
def class_enrollments(rid):
    role, uid = require_roles("ProgramAdmin", "TrainingDirector", "IntakeCoordinator")
    c = get_or_404("classes", rid)
    items = [e for e in STORE["enrollments"].values() if e["class_id"] == c["id"]]
    return list_all(items, ser_enrollment)


# ---------------------------------------------------------------------------
# Enrollments
# ---------------------------------------------------------------------------
@bp.route("/api/classes/<rid>/enrollments", methods=["POST"])
def create_enrollment(rid):
    b = body()
    match_id = v_str(b, "match_id")
    expected_class_version = v_int(b, "expected_class_version")
    role, uid = require_roles("TrainingDirector")
    c = get_or_404("classes", rid)
    m = STORE["matches"].get(match_id)
    if m is None:
        raise err_ref_not_found("match_id does not resolve")
    if expected_class_version != c["version"]:
        raise ApiError(
            "ERR_STALE_VERSION", 412, "expected_class_version does not match"
        )
    check_terminal("classes", c)
    if c["status"] != "ENROLLING":
        raise err_invalid_state("Class is not ENROLLING")
    if m["status"] != "ACCEPTED":
        raise err_invalid_state("Match is not ACCEPTED")
    if enrollment_for_match(m["id"], statuses={"ENROLLED"}):
        raise err_invalid_state("Match already has an active enrollment")
    if c["enrolled_count"] >= c["capacity"]:
        raise ApiError("ERR_CLASS_FULL", 409, "Class is at capacity")
    e = base_fields()
    e.update(
        {
            "class_id": c["id"],
            "match_id": m["id"],
            "status": "ENROLLED",
            "sessions_attended": 0,
            "attendance_pct": 0.0,
        }
    )
    STORE["enrollments"][e["id"]] = e
    c["enrolled_count"] += 1
    touch(c)
    d = STORE["dogs"].get(m["dog_id"])
    if d is not None and d["status"] == "MATCHED":
        d["status"] = "TEAM_TRAINING"
        touch(d)
    entry = STORE["waitlist_entries"].get(m["waitlist_entry_id"])
    if entry is not None:
        applicant = STORE["applicants"].get(entry["applicant_id"])
        if applicant is not None and applicant["application_status"] == "MATCHED":
            applicant["application_status"] = "TEAM_TRAINING"
            touch(applicant)
    return respond(ser_enrollment(e), 201)


@bp.route("/api/enrollments/<rid>", methods=["GET"])
def get_enrollment(rid):
    role, uid = require_roles(
        "ProgramAdmin", "TrainingDirector", "IntakeCoordinator", "Trainer"
    )
    e = get_or_404("enrollments", rid)
    return respond(ser_enrollment(e))


@bp.route("/api/enrollments/<rid>/record-attendance", methods=["POST"])
def record_attendance(rid):
    b = body()
    sessions = v_int(b, "sessions_attended", min_v=0)
    role, uid = require_roles("TrainingDirector", "Trainer")
    e = get_or_404("enrollments", rid)
    check_terminal("enrollments", e)
    c = get_or_404("classes", e["class_id"])
    if c["status"] != "IN_SESSION":
        raise err_invalid_state("Class is not IN_SESSION")
    e["sessions_attended"] = sessions
    e["attendance_pct"] = round_half_up_1dp(
        Decimal(100) * Decimal(sessions) / Decimal(c["total_sessions"])
    )
    touch(e)
    return respond(ser_enrollment(e))


@bp.route("/api/enrollments/<rid>/withdraw", methods=["POST"])
def withdraw_enrollment_route(rid):
    role, uid = require_roles("TrainingDirector")
    e = get_or_404("enrollments", rid)
    check_terminal("enrollments", e)
    if e["status"] != "ENROLLED":
        raise err_invalid_state("Enrollment is not ENROLLED")
    withdraw_enrollment(e, mode="direct")
    return respond(ser_enrollment(e))


@bp.route("/api/enrollments/<rid>/graduate", methods=["POST"])
def graduate_enrollment(rid):
    role, uid = require_roles("TrainingDirector")
    e = get_or_404("enrollments", rid)
    check_terminal("enrollments", e)
    if e["status"] != "ENROLLED":
        raise err_invalid_state("Enrollment is not ENROLLED")
    c = get_or_404("classes", e["class_id"])
    if c["status"] != "GRADUATION_REVIEW":
        raise err_invalid_state("Class is not in GRADUATION_REVIEW")
    if e["attendance_pct"] < 85.0:
        raise ApiError(
            "ERR_ATTENDANCE_BELOW_THRESHOLD",
            409,
            "attendance_pct is below 85.0",
        )
    passed = any(
        p["enrollment_id"] == e["id"] and p["status"] == "SCORED_PASS"
        for p in STORE["pats"].values()
    )
    if not passed:
        raise ApiError(
            "ERR_GRADUATION_REQUIREMENTS",
            409,
            "A SCORED_PASS public access test is required",
        )
    # cascade
    e["status"] = "GRADUATED"
    touch(e)
    m = get_or_404("matches", e["match_id"])
    d = get_or_404("dogs", m["dog_id"])
    entry = get_or_404("waitlist_entries", m["waitlist_entry_id"])
    applicant = get_or_404("applicants", entry["applicant_id"])
    m["status"] = "COMPLETED"
    touch(m)
    if d["status"] == "TEAM_TRAINING":
        d["status"] = "PLACED"
        touch(d)
    if applicant["application_status"] == "TEAM_TRAINING":
        applicant["application_status"] = "PLACED"
        touch(applicant)
    if entry["status"] == "MATCHED":
        entry["status"] = "CLOSED"
        touch(entry)
    # partnership + auto follow-ups
    activated = now()
    p = base_fields()
    p.update(
        {
            "applicant_id": applicant["id"],
            "dog_id": d["id"],
            "enrollment_id": e["id"],
            "status": "ACTIVE",
            "activated_at": activated,
            "recert_due_at": activated + timedelta(days=365),
            "followups_completed": 0,
            "last_recert_passed_at": None,
        }
    )
    STORE["partnerships"][p["id"]] = p
    act_date = activated.date()
    for offset in (90, 180, 270):
        f = base_fields()
        f.update(
            {
                "partnership_id": p["id"],
                "due_on": act_date + timedelta(days=offset),
                "auto_generated": True,
                "status": "SCHEDULED",
                "outcome": None,
                "completed_on": None,
            }
        )
        STORE["followups"][f["id"]] = f
    return respond(ser_partnership(p), 201)


@bp.route("/api/enrollments/<rid>/public-access-tests", methods=["GET"])
def enrollment_pats(rid):
    role, uid = require_roles(
        "ProgramAdmin", "TrainingDirector", "Evaluator", "IntakeCoordinator"
    )
    e = get_or_404("enrollments", rid)
    items = [p for p in STORE["pats"].values() if p["enrollment_id"] == e["id"]]
    return list_all(items, ser_pat)


@bp.route("/api/enrollments/<rid>/partnerships", methods=["GET"])
def enrollment_partnerships(rid):
    role, uid = require_roles(
        "ProgramAdmin", "TrainingDirector", "IntakeCoordinator", "Applicant"
    )
    e = get_or_404("enrollments", rid)
    items = [
        p for p in STORE["partnerships"].values() if p["enrollment_id"] == e["id"]
    ]
    if role == "Applicant":
        m = STORE["matches"].get(e["match_id"])
        entry = (
            STORE["waitlist_entries"].get(m["waitlist_entry_id"]) if m else None
        )
        if entry is None or entry["applicant_id"] != uid:
            raise err_ownership("Applicant may only view its own partnerships")
    return _array([ser_partnership(p) for p in sorted(items, key=lambda x: x["_seq"])])


# ---------------------------------------------------------------------------
# Public access tests
# ---------------------------------------------------------------------------
PAT_CODES_CONTROL = ["C1", "C2", "C3", "C4", "C5", "C6"]
PAT_CODES_PM = ["P1", "P2", "P3", "P4"]
PAT_CODES_SAFETY = ["S1", "S2"]
PAT_ALL_CODES = set(PAT_CODES_CONTROL + PAT_CODES_PM + PAT_CODES_SAFETY)


@bp.route("/api/enrollments/<rid>/public-access-tests", methods=["POST"])
def schedule_pat(rid):
    b = body()
    scheduled_at = v_datetime(b, "scheduled_at")
    location = v_str(b, "location", required=False)
    role, uid = require_roles("Evaluator")
    e = get_or_404("enrollments", rid)
    check_terminal("enrollments", e)
    if e["status"] != "ENROLLED":
        raise err_invalid_state("Enrollment is not ENROLLED")
    # evaluator qualification
    evaluator = STORE["trainers"].get(uid)
    if (
        evaluator is None
        or not evaluator["pat_certified"]
        or evaluator["status"] != "CERTIFIED"
    ):
        raise ApiError(
            "ERR_EVALUATOR_NOT_CERTIFIED",
            409,
            "Evaluator must be a pat_certified CERTIFIED trainer",
        )
    # segregation of duties vs dog's primary trainer
    m = get_or_404("matches", e["match_id"])
    d = get_or_404("dogs", m["dog_id"])
    if d["primary_trainer_id"] is not None and d["primary_trainer_id"] == uid:
        raise ApiError(
            "ERR_EVALUATOR_CONFLICT",
            409,
            "Evaluator must differ from the dog's primary trainer",
        )
    # attempt cap
    prior = [
        p
        for p in STORE["pats"].values()
        if p["enrollment_id"] == e["id"] and p["status"] != "INVALIDATED"
    ]
    if len(prior) >= 2:
        raise ApiError(
            "ERR_PAT_ATTEMPTS_EXHAUSTED",
            409,
            "Two non-INVALIDATED attempts already exist",
        )
    # evaluator calendar buffer: conflict iff |delta| < 90 minutes
    for p in STORE["pats"].values():
        if p["evaluator_id"] != uid:
            continue
        if p["status"] not in ("SCHEDULED", "SCORED_PASS", "SCORED_FAIL"):
            continue
        delta = abs((scheduled_at - p["scheduled_at"]).total_seconds())
        if delta < 90 * 60:
            raise ApiError(
                "ERR_EVALUATOR_SCHEDULE_CONFLICT",
                409,
                "Evaluator calendar conflict within the buffered window",
            )
    pat = base_fields()
    pat.update(
        {
            "enrollment_id": e["id"],
            "evaluator_id": uid,
            "scheduled_at": scheduled_at,
            "location": location,
            "attempt_number": len(prior) + 1,
            "status": "SCHEDULED",
            "exercise_scores": [],
            "section_percents": None,
            "official_score": None,
            "passed_gates": None,
        }
    )
    STORE["pats"][pat["id"]] = pat
    return respond(ser_pat(pat), 201)


@bp.route("/api/public-access-tests/<rid>", methods=["GET"])
def get_pat(rid):
    role, uid = require_roles("ProgramAdmin", "TrainingDirector", "Evaluator")
    p = get_or_404("pats", rid)
    return respond(ser_pat(p))


@bp.route("/api/public-access-tests/<rid>/score", methods=["POST"])
def score_pat(rid):
    b = body()
    scores = b.get("exercise_scores")
    if not isinstance(scores, list) or len(scores) != 12:
        raise err_validation("exercise_scores must contain exactly 12 entries")
    seen = {}
    for item in scores:
        if not isinstance(item, dict):
            raise err_validation("exercise_scores entries must be objects")
        code = item.get("exercise_code")
        raw = item.get("raw_score")
        if code not in PAT_ALL_CODES:
            raise err_validation("invalid exercise_code")
        if not isinstance(raw, int) or isinstance(raw, bool) or raw < 0 or raw > 3:
            raise err_validation("raw_score must be an integer in 0..3")
        if code in seen:
            raise err_validation("duplicate exercise_code")
        seen[code] = raw
    if set(seen.keys()) != PAT_ALL_CODES:
        raise err_validation("exercise_scores must cover all 12 exercise codes")
    role, uid = require_roles("Evaluator")
    p = get_or_404("pats", rid)
    if p["evaluator_id"] != uid:
        raise err_ownership("Evaluator may only score its own tests")
    check_terminal("pats", p)
    if p["status"] != "SCHEDULED":
        raise err_invalid_state("Test is not SCHEDULED")

    control_sum = sum(seen[c] for c in PAT_CODES_CONTROL)
    pm_sum = sum(seen[c] for c in PAT_CODES_PM)
    safety_sum = sum(seen[c] for c in PAT_CODES_SAFETY)
    control_pct = round_half_up_1dp(Decimal(100 * control_sum) / Decimal(18))
    pm_pct = round_half_up_1dp(Decimal(100 * pm_sum) / Decimal(12))
    safety_pct = round_half_up_1dp(Decimal(100 * safety_sum) / Decimal(6))
    official = round_half_up_1dp(
        (Decimal(str(control_pct)) + Decimal(str(pm_pct)) + Decimal(str(safety_pct)))
        / Decimal(3)
    )
    passed_gates = (
        official >= 80.0
        and all(v >= 1 for v in seen.values())
        and seen["S1"] >= 2
        and seen["S2"] >= 2
    )
    p["exercise_scores"] = [
        {"exercise_code": item["exercise_code"], "raw_score": item["raw_score"]}
        for item in scores
    ]
    p["section_percents"] = {
        "control": control_pct,
        "public_manners": pm_pct,
        "safety": safety_pct,
    }
    p["official_score"] = official
    p["passed_gates"] = passed_gates
    p["status"] = "SCORED_PASS" if passed_gates else "SCORED_FAIL"
    touch(p)

    if p["status"] == "SCORED_FAIL" and p["attempt_number"] == 2:
        e = get_or_404("enrollments", p["enrollment_id"])
        if e["status"] == "ENROLLED":
            e["status"] = "FAILED"
            touch(e)
            c = STORE["classes"].get(e["class_id"])
            if c is not None and c["enrolled_count"] > 0:
                c["enrolled_count"] -= 1
                touch(c)
            m = get_or_404("matches", e["match_id"])
            dissolve_match(m)
    return respond(ser_pat(p))


@bp.route("/api/public-access-tests/<rid>/invalidate", methods=["POST"])
def invalidate_pat(rid):
    b = body()
    reason = v_str(b, "reason")
    role, uid = require_roles("TrainingDirector")
    p = get_or_404("pats", rid)
    check_terminal("pats", p)
    if p["status"] != "SCHEDULED":
        raise err_invalid_state("Test is not SCHEDULED")
    p["status"] = "INVALIDATED"
    touch(p)
    return respond(ser_pat(p))
