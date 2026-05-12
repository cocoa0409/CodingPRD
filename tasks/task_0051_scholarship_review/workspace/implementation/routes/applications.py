"""Application CRUD and lifecycle endpoints."""
from flask import Blueprint, g

import db
from clock import parse_iso, now
from errors import err
from middleware import require_auth, get_pagination
from response import success, success_list
from services import calculations
from services.audit import emit_audit
from services.lookup import (
    get_scholarship_or_404, get_application_or_404, get_reviewer_or_404,
    check_version,
)
from services.scholarship_lifecycle import transition_application
from services.validation import get_body


# PRD §3.4 requires comparing the DeptOfficer's department code to the
# Application.student_department_code. PRD §2.1 declares DeptOfficer's
# X-User-ID is an opaque operator id, leaving the binding mechanism
# implementation-defined. The convention adopted here: a DeptOfficer's
# X-User-ID either literally equals their department code, or follows
# one of the patterns
#   "dept-officer-<DEPT_CODE>"
#   "dept-officer-<DEPT_CODE>-<suffix>"
# where the DEPT_CODE may itself contain dashes (e.g., "STU-COI-DEPT").
# Membership in {dept_code, "dept-officer-<dept_code>",
# "dept-officer-<dept_code>-<suffix>"} is decided by string prefix match
# against the target dept_code so dash-heavy dept codes work uniformly.
def _officer_matches_department(user_id: str, dept_code: str) -> bool:
    if user_id == dept_code:
        return True
    prefix = f"dept-officer-{dept_code}"
    if user_id == prefix:
        return True
    if user_id.startswith(prefix + "-"):
        return True
    return False


bp = Blueprint("applications", __name__)


# PRD §3.3 lists non-terminal as "anything other than WITHDRAWN, REVOKED,
# DISBURSED, or NOT_AWARDED". PRD §2.9 narrows the duplicate-same race to
# (scholarship_id, student_id) uniqueness in SUBMITTED status: two
# concurrent submits on DRAFT siblings must serialise such that exactly
# one reaches SUBMITTED and the loser gets ERR_DUPLICATE_APPLICATION_SAME.
# Reconciling the two, the duplicate-same check is over post-DRAFT
# non-terminal statuses — a sibling still in DRAFT does not by itself
# block the current submit (the §2.9 race rule needs this), while a
# sibling that has already advanced past DRAFT does block.
NON_TERMINAL_STATUSES_FOR_SAME = {
    "SUBMITTED", "DEPT_PRELIM_PASSED", "DEPT_PRELIM_REJECTED",
    "UNDER_REVIEW", "REVIEW_COMPLETE", "AWARDED",
}

NON_TERMINAL_FOR_CROSS = {
    "DRAFT", "SUBMITTED", "DEPT_PRELIM_PASSED", "DEPT_PRELIM_REJECTED",
    "UNDER_REVIEW", "REVIEW_COMPLETE", "AWARDED",
}


VALID_SPECIAL_GROUPS = {"NONE", "GENDER_FEMALE", "GENDER_MALE", "ETHNIC_MINORITY", "DISABILITY"}


# ---- Application CRUD -----------------------------------------------------

@bp.route("/scholarships/<scholarship_id>/applications", methods=["POST"])
@require_auth(roles={"Student"})
def create_application(scholarship_id):
    s = get_scholarship_or_404(scholarship_id)
    body = get_body()

    required = [
        "student_department_code", "student_advisor_id",
        "student_major", "student_grade", "student_gpa_x100", "uploaded_materials",
    ]
    for f in required:
        if f not in body:
            raise err("ERR_BAD_REQUEST", f"Missing required field: {f}")

    if not isinstance(body["uploaded_materials"], list):
        raise err("ERR_BAD_REQUEST", "uploaded_materials must be array")
    if not isinstance(body["student_grade"], int):
        raise err("ERR_BAD_REQUEST", "student_grade must be integer")
    if not isinstance(body["student_gpa_x100"], int):
        raise err("ERR_BAD_REQUEST", "student_gpa_x100 must be integer")

    sg = body.get("student_special_group", "NONE")
    if sg not in VALID_SPECIAL_GROUPS:
        raise err("ERR_BAD_REQUEST", f"unknown student_special_group: {sg}")

    income = body.get("student_family_income_cents")
    if income is not None and not isinstance(income, int):
        raise err("ERR_BAD_REQUEST", "student_family_income_cents must be integer or null")

    entity = {
        "scholarship_id": s["id"],
        "student_id": g.user_id,
        "student_department_code": body["student_department_code"],
        "student_advisor_id": body["student_advisor_id"],
        "student_major": body["student_major"],
        "student_grade": body["student_grade"],
        "student_gpa_x100": body["student_gpa_x100"],
        "student_family_income_cents": income,
        "student_special_group": sg,
        "uploaded_materials": list(body["uploaded_materials"]),
        "advisor_recommendation_id": body.get("advisor_recommendation_id"),
        "status": "DRAFT",
        "dept_review_comment": None,
        "aggregated_score_x100": None,
        "final_rank": None,
        "revocation_reason": None,
    }
    db.stamp_create(entity, common_fields=True)
    db.applications[entity["id"]] = entity
    return success(db.public(entity), 201)


@bp.route("/scholarships/<scholarship_id>/applications/<application_id>", methods=["GET"])
@require_auth(roles={"SchoolAdmin", "DeptOfficer", "Reviewer", "Student"})
def get_application(scholarship_id, application_id):
    get_scholarship_or_404(scholarship_id)
    a = get_application_or_404(scholarship_id, application_id)
    return success(db.public(a), 200)


@bp.route("/scholarships/<scholarship_id>/applications/<application_id>", methods=["PATCH"])
@require_auth(roles={"Student"})
def update_application(scholarship_id, application_id):
    get_scholarship_or_404(scholarship_id)
    a = get_application_or_404(scholarship_id, application_id)
    body = get_body()
    check_version(a, body)
    # Ownership
    if a["student_id"] != g.user_id:
        raise err("ERR_FORBIDDEN", "Student does not own this application")
    if a["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Application must be DRAFT to update")

    for k in ("student_major", "student_grade", "student_gpa_x100",
              "student_family_income_cents", "uploaded_materials",
              "advisor_recommendation_id"):
        if k in body:
            a[k] = body[k]
    db.stamp_update(a)
    return success(db.public(a), 200)


# ---- Lifecycle: submit / withdraw / modify / dept-review / correct ----------

def _ensure_owner(a, role, user_id):
    if role == "Student" and a["student_id"] != user_id:
        raise err("ERR_FORBIDDEN", "Student does not own this application")


@bp.route("/scholarships/<scholarship_id>/applications/<application_id>/submit", methods=["POST"])
@require_auth(roles={"Student"})
def submit_application(scholarship_id, application_id):
    s = get_scholarship_or_404(scholarship_id)
    a = get_application_or_404(scholarship_id, application_id)
    body = get_body()
    check_version(a, body)
    _ensure_owner(a, g.user_role, g.user_id)

    # PRD §2.9 requires concurrent submits by the same student to serialise
    # on (scholarship_id, student_id) uniqueness in SUBMITTED status; the
    # duplicate-same check and the DRAFT→SUBMITTED transition therefore
    # must run as one atomic critical section.
    with db.lock():
        # Order: parent scholarship state → app state → window → duplicate-same → duplicate-cross → materials → advisor → eligibility
        if s["status"] != "OPEN":
            raise err("ERR_WINDOW_NOT_OPEN", "Scholarship not OPEN")
        if a["status"] != "DRAFT":
            raise err("ERR_INVALID_STATE", "Application must be DRAFT to submit")
        if now() >= parse_iso(s["application_window_end"]):
            raise err("ERR_WINDOW_CLOSED", "Application window closed")

        # Materials → advisor → eligibility (per §2.6 priority and §3.3)
        # Per §2.6: duplicate (same/cross) comes before materials/advisor/eligibility.
        _check_duplicate_same(a, s)
        _check_duplicate_cross(a, s)
        _check_materials(a, s)
        _check_advisor_rec(a, s)
        if not calculations.eligibility_check(a, s):
            raise err("ERR_ELIGIBILITY_FAIL", "Application fails eligibility check")

        transition_application(a, "SUBMITTED",
                               actor_role=g.user_role, actor_id=g.user_id,
                               event_type="APPLICATION_SUBMITTED",
                               payload={"from": "DRAFT", "to": "SUBMITTED"})
    return success(db.public(a), 200)


def _check_duplicate_same(a, s):
    for other in db.applications.values():
        if other["id"] == a["id"]:
            continue
        if other["scholarship_id"] != s["id"]:
            continue
        if other["student_id"] != a["student_id"]:
            continue
        if other["status"] in NON_TERMINAL_STATUSES_FOR_SAME:
            raise err("ERR_DUPLICATE_APPLICATION_SAME",
                      "Student already has non-terminal application against this scholarship")


def _check_duplicate_cross(a, s):
    for peer in db.scholarships.values():
        if peer["id"] == s["id"]:
            continue
        if peer["category"] != s["category"]:
            continue
        if not calculations.windows_3day_buffered_overlap(
                s["application_window_start"], s["application_window_end"],
                peer["application_window_start"], peer["application_window_end"]):
            continue
        for other in db.applications.values():
            if other["scholarship_id"] != peer["id"]:
                continue
            if other["student_id"] != a["student_id"]:
                continue
            if other["status"] in NON_TERMINAL_FOR_CROSS:
                raise err("ERR_DUPLICATE_APPLICATION_CROSS",
                          "Student has overlapping application against same-category scholarship")


def _check_materials(a, s):
    required = set(s.get("required_materials") or [])
    uploaded = set(a.get("uploaded_materials") or [])
    if not required.issubset(uploaded):
        raise err("ERR_MATERIAL_MISSING", "uploaded_materials missing entries from required_materials")


def _check_advisor_rec(a, s):
    if "ADVISOR_REC" not in (s.get("required_materials") or []):
        return
    aid = a.get("advisor_recommendation_id")
    if not aid:
        raise err("ERR_ADVISOR_REC_MISSING", "advisor_recommendation_id is required")
    rev = db.reviewers.get(aid)
    if rev is None or rev.get("status") != "ACTIVE":
        raise err("ERR_ADVISOR_REC_MISSING", "advisor recommendation reviewer not ACTIVE")


@bp.route("/scholarships/<scholarship_id>/applications/<application_id>/withdraw", methods=["POST"])
@require_auth(roles={"Student"})
def withdraw_application(scholarship_id, application_id):
    s = get_scholarship_or_404(scholarship_id)
    a = get_application_or_404(scholarship_id, application_id)
    body = get_body()
    check_version(a, body)
    _ensure_owner(a, g.user_role, g.user_id)
    if a["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Application must be SUBMITTED to withdraw")
    if now() >= parse_iso(s["application_window_end"]):
        raise err("ERR_WINDOW_CLOSED", "Application window closed")
    transition_application(a, "WITHDRAWN",
                           actor_role=g.user_role, actor_id=g.user_id,
                           event_type="APPLICATION_WITHDRAWN",
                           payload={"from": "SUBMITTED", "to": "WITHDRAWN"})
    return success(db.public(a), 200)


@bp.route("/scholarships/<scholarship_id>/applications/<application_id>/modify", methods=["POST"])
@require_auth(roles={"Student"})
def modify_application(scholarship_id, application_id):
    s = get_scholarship_or_404(scholarship_id)
    a = get_application_or_404(scholarship_id, application_id)
    body = get_body()
    check_version(a, body)
    _ensure_owner(a, g.user_role, g.user_id)
    if a["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Application must be SUBMITTED to modify")
    if now() >= parse_iso(s["application_window_end"]):
        raise err("ERR_WINDOW_CLOSED", "Application window closed")
    a["status"] = "DRAFT"
    db.stamp_update(a)
    return success(db.public(a), 200)


@bp.route("/scholarships/<scholarship_id>/applications/<application_id>/dept-review", methods=["POST"])
@require_auth(roles={"DeptOfficer"})
def dept_review(scholarship_id, application_id):
    s = get_scholarship_or_404(scholarship_id)
    a = get_application_or_404(scholarship_id, application_id)
    body = get_body()
    check_version(a, body)

    if s["status"] != "REVIEWING":
        raise err("ERR_INVALID_STATE", "Scholarship must be REVIEWING for dept-review")
    if a["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Application must be SUBMITTED for dept-review")

    # PRD §3.4: 'only when the officer's own department code matches the
    # application's student_department_code'. PRD §2.1 leaves the binding
    # from X-User-ID to department implementation-defined; see
    # _officer_matches_department above for the matching convention.
    if not _officer_matches_department(g.user_id, a["student_department_code"]):
        raise err("ERR_DEPT_SCOPE_MISMATCH",
                  "DeptOfficer department does not match applicant department")

    decision = body.get("decision")
    if decision not in ("PASS", "REJECT"):
        raise err("ERR_BAD_REQUEST", "decision must be PASS or REJECT")
    comment = body.get("comment", "")
    if decision == "REJECT" and (not isinstance(comment, str) or comment.strip() == ""):
        raise err("ERR_COMMENT_REQUIRED", "Comment required for REJECT decision")

    if decision == "PASS":
        required = set(s.get("required_materials") or [])
        uploaded = set(a.get("uploaded_materials") or [])
        if not required.issubset(uploaded):
            raise err("ERR_MATERIAL_INCOMPLETE", "uploaded_materials incomplete")
        flags = body.get("is_authentic_flags") or {}
        if not isinstance(flags, dict):
            raise err("ERR_BAD_REQUEST", "is_authentic_flags must be object")
        for m in required:
            if not flags.get(m, False):
                raise err("ERR_MATERIAL_INCOMPLETE",
                          f"Material {m} not flagged authentic")
        a["dept_review_comment"] = comment or ""
        transition_application(a, "DEPT_PRELIM_PASSED",
                               actor_role=g.user_role, actor_id=g.user_id,
                               event_type="DEPT_REVIEW",
                               payload={"decision": "PASS",
                                         "from": "SUBMITTED", "to": "DEPT_PRELIM_PASSED",
                                         "comment": comment or ""})
    else:
        a["dept_review_comment"] = comment
        transition_application(a, "DEPT_PRELIM_REJECTED",
                               actor_role=g.user_role, actor_id=g.user_id,
                               event_type="DEPT_REVIEW",
                               payload={"decision": "REJECT",
                                         "from": "SUBMITTED", "to": "DEPT_PRELIM_REJECTED",
                                         "comment": comment})
    return success(db.public(a), 200)


@bp.route("/scholarships/<scholarship_id>/applications/<application_id>/correct", methods=["POST"])
@require_auth(roles={"Student"})
def correct_application(scholarship_id, application_id):
    s = get_scholarship_or_404(scholarship_id)
    a = get_application_or_404(scholarship_id, application_id)
    body = get_body()
    check_version(a, body)
    _ensure_owner(a, g.user_role, g.user_id)

    if s["status"] != "REVIEWING":
        raise err("ERR_INVALID_STATE", "Scholarship must be REVIEWING for correct")
    if a["status"] != "DEPT_PRELIM_REJECTED":
        raise err("ERR_INVALID_STATE", "Application must be DEPT_PRELIM_REJECTED to correct")

    replaced = body.get("replaced_materials") or []
    if not isinstance(replaced, list):
        raise err("ERR_BAD_REQUEST", "replaced_materials must be array")
    uploaded = set(a.get("uploaded_materials") or [])
    for m in replaced:
        if m not in uploaded:
            raise err("ERR_MATERIAL_MISSING",
                      f"replaced material {m} not present in uploaded_materials")

    a["dept_review_comment"] = None
    a["status"] = "SUBMITTED"
    db.stamp_update(a)
    return success(db.public(a), 200)


@bp.route("/scholarships/<scholarship_id>/applications/<application_id>/assign-reviewers", methods=["POST"])
@require_auth(roles={"SchoolAdmin"})
def assign_reviewers(scholarship_id, application_id):
    s = get_scholarship_or_404(scholarship_id)
    a = get_application_or_404(scholarship_id, application_id)
    body = get_body()
    check_version(a, body)

    # PRD §2.9 requires concurrent assign-reviewers calls on the same
    # application to serialise on the existence of any ReviewerAssignment
    # for the application. The already-assigned check, the application
    # state check, and the creation of the three ReviewerAssignment rows
    # must therefore run atomically.
    with db.lock():
        if s["status"] != "REVIEWING":
            raise err("ERR_INVALID_STATE", "Scholarship must be REVIEWING for assign-reviewers")

        # PRD §2.9: 'Two concurrent assign-reviewers calls for the same
        # application serialise on the existence of any ReviewerAssignment
        # for the application; exactly one set of three assignments is
        # created, and the loser receives ERR_REVIEWERS_ALREADY_ASSIGNED.'
        # The winner has already advanced the application out of
        # DEPT_PRELIM_PASSED, so this check must precede the application
        # state check to surface the PRD-mandated error code.
        for ra in db.reviewer_assignments.values():
            if ra["application_id"] == a["id"]:
                raise err("ERR_REVIEWERS_ALREADY_ASSIGNED", "Reviewers already assigned")

        if a["status"] != "DEPT_PRELIM_PASSED":
            raise err("ERR_INVALID_STATE", "Application must be DEPT_PRELIM_PASSED for assign-reviewers")

        reviewer_ids = body.get("reviewer_ids")
        if not isinstance(reviewer_ids, list) or len(reviewer_ids) != 3:
            raise err("ERR_REVIEWER_COUNT_INVALID", "reviewer_ids must contain exactly 3 ids")
        if len(set(reviewer_ids)) != 3:
            raise err("ERR_REVIEWER_DUPLICATE", "reviewer_ids contains duplicates")

        reviewers = []
        for rid in reviewer_ids:
            rv = db.reviewers.get(rid)
            if rv is None:
                raise err("ERR_NOT_FOUND", f"Reviewer {rid} not found")
            reviewers.append(rv)

        # COI validation order: priority 9 in §2.6 — COI before department scope. SoD before COI.
        # But scaffold lists active before COI? Let's follow scaffold §1.4: state precedes COI; then
        # active-status check is part of business_constraint after COI per error order. The PRD
        # implies COI is detected first (priority 9 < REVIEWER_NOT_ACTIVE which is not even listed
        # in priority but is a state-409). Implement COI first since the priority table puts it earlier.
        for rv in reviewers:
            if calculations.coi_violation(rv, a):
                raise err("ERR_COI_VIOLATION", f"Reviewer {rv['id']} fails COI check")

        for rv in reviewers:
            if rv.get("status") != "ACTIVE":
                raise err("ERR_REVIEWER_NOT_ACTIVE", f"Reviewer {rv['id']} not ACTIVE")

        for rid in reviewer_ids:
            from clock import now_iso
            ra = {
                "application_id": a["id"],
                "reviewer_id": rid,
                "assigned_at": now_iso(),
            }
            db.stamp_create(ra, common_fields=False)
            db.reviewer_assignments[ra["id"]] = ra

        transition_application(a, "UNDER_REVIEW",
                               actor_role=g.user_role, actor_id=g.user_id,
                               event_type=None,
                               payload={"from": "DEPT_PRELIM_PASSED", "to": "UNDER_REVIEW"})
    return success(db.public(a), 200)


# ---- Scores: submit + list ------------------------------------------------

@bp.route("/scholarships/<scholarship_id>/applications/<application_id>/scores", methods=["POST"])
@require_auth(roles={"Reviewer"})
def submit_score(scholarship_id, application_id):
    s = get_scholarship_or_404(scholarship_id)
    a = get_application_or_404(scholarship_id, application_id)
    body = get_body()

    # PRD §2.9 requires concurrent third-score submits to serialise on the
    # count of Score rows so exactly one is recorded as the third and the
    # loser sees ERR_SCORE_OVER_QUOTA. The count check, score-row write,
    # and the AGGREGATION_DONE transition therefore must run atomically.
    with db.lock():
        # Ownership: reviewer must have a ReviewerAssignment for this application.
        rid = g.user_id
        has_assignment = any(
            ra for ra in db.reviewer_assignments.values()
            if ra["application_id"] == a["id"] and ra["reviewer_id"] == rid
        )
        if not has_assignment:
            raise err("ERR_FORBIDDEN", "Reviewer is not assigned to this application")

        cs = body.get("criterion_scores")
        if not isinstance(cs, dict):
            raise err("ERR_BAD_REQUEST", "criterion_scores must be object")

        rw_keys = set(s.get("rubric_weights", {}).keys())
        cs_keys = set(cs.keys())
        if rw_keys != cs_keys:
            raise err("ERR_SCORE_RUBRIC_MISMATCH",
                      "criterion_scores keys must exactly match rubric_weights keys")
        for k, v in cs.items():
            if not isinstance(v, int) or v < 0 or v > 100:
                raise err("ERR_BAD_REQUEST", f"criterion score for {k} must be 0..100 integer")

        # PRD §3.5: 'If a fourth score submission is attempted for an
        # application that already has three scores, or a reviewer attempts
        # to submit two scores for the same application, the request is
        # rejected with ERR_SCORE_OVER_QUOTA.' This rule fires regardless of
        # the application's transitioned state — the 3rd score auto-advances
        # the application to REVIEW_COMPLETE (PRD §3.6), and the 4th submit
        # must still see ERR_SCORE_OVER_QUOTA rather than ERR_INVALID_STATE.
        existing = [sc for sc in db.scores.values() if sc["application_id"] == a["id"]]
        if len(existing) >= 3:
            raise err("ERR_SCORE_OVER_QUOTA", "Already 3 scores for this application")
        for sc in existing:
            if sc["reviewer_id"] == rid:
                raise err("ERR_SCORE_OVER_QUOTA", "Reviewer already submitted a score for this application")

        if a["status"] != "UNDER_REVIEW":
            raise err("ERR_INVALID_STATE", "Application must be UNDER_REVIEW to submit score")

        raw_total = sum(int(cs[k]) * int(s["rubric_weights"][k]) for k in rw_keys)
        new_score = {
            "application_id": a["id"],
            "reviewer_id": rid,
            "criterion_scores": dict(cs),
            "raw_total_x100": raw_total,
            "is_outlier": False,
            "comment": body.get("comment"),
        }
        db.stamp_create(new_score, common_fields=False)
        db.scores[new_score["id"]] = new_score

        # Emit SCORE_SUBMITTED audit
        emit_audit("SCORE_SUBMITTED", "Score", new_score["id"],
                   {"application_id": a["id"], "reviewer_id": rid, "raw_total_x100": raw_total})

        # Auto-aggregate when the 3rd score arrives.
        after = [sc for sc in db.scores.values() if sc["application_id"] == a["id"]]
        if len(after) == 3:
            agg = calculations.aggregate_application_score(a["id"], s)
            a["aggregated_score_x100"] = agg
            transition_application(a, "REVIEW_COMPLETE",
                                   actor_role="system", actor_id="system",
                                   event_type="AGGREGATION_DONE",
                                   payload={"from": "UNDER_REVIEW", "to": "REVIEW_COMPLETE",
                                             "aggregated_score_x100": agg})

    return success(db.public(new_score), 201)


@bp.route("/scholarships/<scholarship_id>/applications/<application_id>/scores", methods=["GET"])
@require_auth(roles={"SchoolAdmin", "DeptOfficer"})
def list_scores(scholarship_id, application_id):
    get_scholarship_or_404(scholarship_id)
    get_application_or_404(scholarship_id, application_id)
    limit, offset = get_pagination()
    rows = [sc for sc in db.scores.values() if sc["application_id"] == application_id]
    rows.sort(key=lambda r: r["_seq"])
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([db.public(r) for r in page], limit, offset, total)
