"""Routes: design review applications, design violations."""
from datetime import timedelta

from flask import Blueprint

from core import (
    DB, actor, require_roles, body, check_no_undeclared, req_string, req_int,
    req_enum, opt_id, req_datetime, validation, err, invalid_state, new_entity,
    touch, get_or_404, check_body_fk, ok_object, filter_args, calendar_days,
    MAX_REVIEW_ROUNDS, REVIEW_ROUND_FEES, CONSTRUCTION_START_WINDOW_DAYS,
    VIOLATION_CURE_DAYS, APPEAL_WINDOW_DAYS, FINE_CAP_CENTS, TIER1_DAILY_CENTS,
    TIER2_DAILY_CENTS, TIER3_DAILY_CENTS,
)
from serializers import application_out, violation_out
from routes_core import paginate_pairs

bp = Blueprint("design", __name__)

REVIEWER = ["DesignReviewer"]
APPLICANT_ROLES = ["BuilderRep", "HomeownerResident"]

PROJECT_TYPES = {"NEW_CONSTRUCTION", "EXTERIOR_MODIFICATION", "LANDSCAPE",
                 "ADDITION"}
VIOLATION_TYPES = {"UNAPPROVED_MODIFICATION", "NONCONFORMING_MATERIALS",
                   "SETBACK", "LANDSCAPE_DEADLINE"}


def _check_applicant_identity(user_id, role, application):
    """Entity-actor ownership: the actor must match the applicant."""
    if role == "BuilderRep":
        if application["applicant_builder_id"] is None or \
                application["applicant_builder_id"] != user_id:
            err("ERR_FORBIDDEN_ROLE", 403, "Actor does not match the applicant")
    elif role == "HomeownerResident":
        if application["applicant_resident_id"] is None or \
                application["applicant_resident_id"] != user_id:
            err("ERR_FORBIDDEN_ROLE", 403, "Actor does not match the applicant")


# ---------------------------------------------------------------------------
# Design review applications
# ---------------------------------------------------------------------------
@bp.route("/mpc/applications", methods=["POST"])
def create_application():
    user_id, role = actor()
    require_roles(role, APPLICANT_ROLES)
    data = body()
    community = check_body_fk("community", DB.communities, data.get("community_id"))
    lot = check_body_fk("lot", DB.lots, data.get("lot_id"))
    builder = check_body_fk("builder", DB.builders, data.get("applicant_builder_id"))
    resident = check_body_fk("resident", DB.residents, data.get("applicant_resident_id"))
    check_no_undeclared(data, {"community_id", "lot_id", "project_type",
                               "applicant_builder_id", "applicant_resident_id"})
    req_string(data, "community_id")
    req_string(data, "lot_id")
    ptype = req_enum(data, "project_type", PROJECT_TYPES)
    ab = opt_id(data, "applicant_builder_id")
    ar = opt_id(data, "applicant_resident_id")
    # Exactly one applicant identifier (precedes the ownership comparison so a
    # missing pair surfaces as ERR_APPLICANT_IDENTITY_INVALID, not 403).
    if (ab is None) == (ar is None):
        err("ERR_APPLICANT_IDENTITY_INVALID", 422,
            "Exactly one of applicant_builder_id / applicant_resident_id is required")
    # Ownership: the applicant acts on their own behalf.
    if role == "BuilderRep" and (ab is None or ab != user_id):
        err("ERR_FORBIDDEN_ROLE", 403,
            "BuilderRep X-User-ID must equal applicant_builder_id")
    if role == "HomeownerResident" and (ar is None or ar != user_id):
        err("ERR_FORBIDDEN_ROLE", 403,
            "HomeownerResident X-User-ID must equal applicant_resident_id")
    a = new_entity()
    a.update({
        "community_id": community["id"],
        "lot_id": lot["id"],
        "applicant_builder_id": ab,
        "applicant_resident_id": ar,
        "project_type": ptype,
        "submission_round": 1,
        "review_fee_cents": 0,
        "reviewer_user_id": None,
        "denied_by_user_id": None,
        "conditions_text": None,
        "construction_start_by": None,
        "status": "SUBMITTED",
        "_construction_started": False,
    })
    DB.applications[a["id"]] = a
    return ok_object(application_out(a), 201)


@bp.route("/mpc/applications", methods=["GET"])
def list_applications():
    actor()
    f = filter_args(["community_id", "lot_id", "applicant_builder_id",
                     "applicant_resident_id"])
    raw = [a for a in DB.applications.values()
           if f.get("community_id") in (None, a["community_id"])
           and f.get("lot_id") in (None, a["lot_id"])
           and f.get("applicant_builder_id") in (None, a["applicant_builder_id"])
           and f.get("applicant_resident_id") in (None, a["applicant_resident_id"])]
    return paginate_pairs(raw, application_out)


@bp.route("/mpc/applications/<aid>", methods=["GET"])
def get_application(aid):
    actor()
    a = get_or_404("application", DB.applications, aid)
    return ok_object(application_out(a))


@bp.route("/mpc/applications/<aid>/begin-review", methods=["POST"])
def begin_review(aid):
    user_id, role = actor()
    require_roles(role, REVIEWER)
    a = get_or_404("application", DB.applications, aid)
    data = body()
    check_no_undeclared(data, set())
    if a["status"] not in ("SUBMITTED", "RESUBMITTED"):
        invalid_state("Application is not SUBMITTED or RESUBMITTED")
    if a["status"] == "SUBMITTED":
        applicant_ids = {x for x in (a["applicant_builder_id"],
                                     a["applicant_resident_id"]) if x}
        if user_id in applicant_ids:
            err("ERR_REVIEWER_CONFLICT", 403,
                "Reviewer must not be the applicant")
    else:  # RESUBMITTED
        if a["denied_by_user_id"] is not None and user_id == a["denied_by_user_id"]:
            err("ERR_REVIEWER_CONFLICT", 403,
                "Reviewer must not be the latest denier")
    a["status"] = "UNDER_REVIEW"
    a["reviewer_user_id"] = user_id
    touch(a)
    return ok_object(application_out(a))


def _require_reviewer(user_id, application):
    if application["reviewer_user_id"] != user_id:
        err("ERR_REVIEWER_CONFLICT", 403,
            "Decision requires the recorded reviewer_user_id")


@bp.route("/mpc/applications/<aid>/approve", methods=["POST"])
def approve_application(aid):
    user_id, role = actor()
    require_roles(role, REVIEWER)
    a = get_or_404("application", DB.applications, aid)
    data = body()
    check_no_undeclared(data, set())
    if a["status"] != "UNDER_REVIEW":
        invalid_state("Application is not UNDER_REVIEW")
    _require_reviewer(user_id, a)
    a["status"] = "APPROVED"
    a["construction_start_by"] = DB.now() + timedelta(days=CONSTRUCTION_START_WINDOW_DAYS)
    touch(a)
    return ok_object(application_out(a))


@bp.route("/mpc/applications/<aid>/approve-with-conditions", methods=["POST"])
def approve_with_conditions(aid):
    user_id, role = actor()
    require_roles(role, REVIEWER)
    a = get_or_404("application", DB.applications, aid)
    data = body()
    check_no_undeclared(data, {"conditions_text"})
    conditions = req_string(data, "conditions_text")
    if a["status"] != "UNDER_REVIEW":
        invalid_state("Application is not UNDER_REVIEW")
    _require_reviewer(user_id, a)
    a["status"] = "CONDITIONALLY_APPROVED"
    a["conditions_text"] = conditions
    touch(a)
    return ok_object(application_out(a))


@bp.route("/mpc/applications/<aid>/deny", methods=["POST"])
def deny_application(aid):
    user_id, role = actor()
    require_roles(role, REVIEWER)
    a = get_or_404("application", DB.applications, aid)
    data = body()
    check_no_undeclared(data, {"denial_reason"})
    req_string(data, "denial_reason")
    if a["status"] != "UNDER_REVIEW":
        invalid_state("Application is not UNDER_REVIEW")
    _require_reviewer(user_id, a)
    a["status"] = "DENIED"
    a["denied_by_user_id"] = user_id
    touch(a)
    return ok_object(application_out(a))


@bp.route("/mpc/applications/<aid>/resubmit", methods=["POST"])
def resubmit_application(aid):
    user_id, role = actor()
    require_roles(role, APPLICANT_ROLES)
    a = get_or_404("application", DB.applications, aid)
    _check_applicant_identity(user_id, role, a)
    data = body()
    check_no_undeclared(data, set())
    if a["status"] != "DENIED":
        invalid_state("Application is not DENIED")
    if a["submission_round"] >= MAX_REVIEW_ROUNDS:
        err("ERR_REVIEW_ROUNDS_EXHAUSTED", 409,
            "Resubmission beyond MAX_REVIEW_ROUNDS")
    a["submission_round"] += 1
    a["review_fee_cents"] = REVIEW_ROUND_FEES[a["submission_round"]]
    a["status"] = "RESUBMITTED"
    touch(a)
    return ok_object(application_out(a))


@bp.route("/mpc/applications/<aid>/verify-conditions", methods=["POST"])
def verify_conditions(aid):
    user_id, role = actor()
    require_roles(role, REVIEWER)
    a = get_or_404("application", DB.applications, aid)
    data = body()
    check_no_undeclared(data, set())
    if a["status"] != "CONDITIONALLY_APPROVED":
        invalid_state("Application is not CONDITIONALLY_APPROVED")
    a["status"] = "APPROVED"
    a["construction_start_by"] = DB.now() + timedelta(days=CONSTRUCTION_START_WINDOW_DAYS)
    touch(a)
    return ok_object(application_out(a))


@bp.route("/mpc/applications/<aid>/record-construction-start", methods=["POST"])
def record_construction_start(aid):
    user_id, role = actor()
    require_roles(role, APPLICANT_ROLES)
    a = get_or_404("application", DB.applications, aid)
    _check_applicant_identity(user_id, role, a)
    data = body()
    check_no_undeclared(data, set())
    if a["status"] != "APPROVED":
        invalid_state("Application is not APPROVED")
    a["_construction_started"] = True
    touch(a)
    return ok_object(application_out(a))


@bp.route("/mpc/applications/<aid>/withdraw", methods=["POST"])
def withdraw_application(aid):
    user_id, role = actor()
    require_roles(role, APPLICANT_ROLES)
    a = get_or_404("application", DB.applications, aid)
    _check_applicant_identity(user_id, role, a)
    data = body()
    check_no_undeclared(data, set())
    if a["status"] not in ("SUBMITTED", "DENIED"):
        invalid_state("Application is not SUBMITTED or DENIED")
    a["status"] = "WITHDRAWN"
    touch(a)
    return ok_object(application_out(a))


# ---------------------------------------------------------------------------
# Design violations
# ---------------------------------------------------------------------------
def _tiered_fine(days_late):
    if days_late <= 0:
        return 0
    fine = (min(days_late, 30) * TIER1_DAILY_CENTS
            + min(max(days_late - 30, 0), 30) * TIER2_DAILY_CENTS
            + max(days_late - 60, 0) * TIER3_DAILY_CENTS)
    return min(FINE_CAP_CENTS, fine)


@bp.route("/mpc/violations", methods=["POST"])
def create_violation():
    _, role = actor()
    require_roles(role, ["DesignReviewer", "AssociationDirector"])
    data = body()
    community = check_body_fk("community", DB.communities, data.get("community_id"))
    lot = check_body_fk("lot", DB.lots, data.get("lot_id"))
    check_body_fk("resident", DB.residents, data.get("respondent_resident_id"))
    check_body_fk("builder", DB.builders, data.get("respondent_builder_id"))
    check_no_undeclared(data, {"community_id", "lot_id", "violation_type",
                               "respondent_resident_id", "respondent_builder_id"})
    req_string(data, "community_id")
    req_string(data, "lot_id")
    vtype = req_enum(data, "violation_type", VIOLATION_TYPES)
    rr = opt_id(data, "respondent_resident_id")
    rb = opt_id(data, "respondent_builder_id")
    if (rr is None) == (rb is None):
        err("ERR_RESPONDENT_IDENTITY_INVALID", 422,
            "Exactly one respondent identifier is required")
    v = new_entity()
    v.update({
        "community_id": community["id"],
        "lot_id": lot["id"],
        "respondent_resident_id": rr,
        "respondent_builder_id": rb,
        "violation_type": vtype,
        "cure_deadline": None,
        "fine_cents": 0,
        "cured_at": None,
        "fined_by_user_id": None,
        "status": "REPORTED",
        "_fined_at": None,
    })
    DB.violations[v["id"]] = v
    return ok_object(violation_out(v), 201)


@bp.route("/mpc/violations", methods=["GET"])
def list_violations():
    actor()
    f = filter_args(["community_id", "lot_id", "respondent_resident_id",
                     "respondent_builder_id"])
    raw = [v for v in DB.violations.values()
           if f.get("community_id") in (None, v["community_id"])
           and f.get("lot_id") in (None, v["lot_id"])
           and f.get("respondent_resident_id") in (None, v["respondent_resident_id"])
           and f.get("respondent_builder_id") in (None, v["respondent_builder_id"])]
    return paginate_pairs(raw, violation_out)


@bp.route("/mpc/violations/<vid>", methods=["GET"])
def get_violation(vid):
    actor()
    v = get_or_404("violation", DB.violations, vid)
    return ok_object(violation_out(v))


@bp.route("/mpc/violations/<vid>/send-notice", methods=["POST"])
def send_violation_notice(vid):
    _, role = actor()
    require_roles(role, REVIEWER)
    v = get_or_404("violation", DB.violations, vid)
    data = body()
    check_no_undeclared(data, set())
    if v["status"] != "REPORTED":
        invalid_state("Violation is not REPORTED")
    v["status"] = "NOTICE_SENT"
    v["cure_deadline"] = DB.now() + timedelta(days=VIOLATION_CURE_DAYS)
    touch(v)
    return ok_object(violation_out(v))


@bp.route("/mpc/violations/<vid>/record-cure", methods=["POST"])
def record_cure(vid):
    _, role = actor()
    require_roles(role, REVIEWER)
    v = get_or_404("violation", DB.violations, vid)
    data = body()
    check_no_undeclared(data, set())
    if v["status"] != "NOTICE_SENT":
        invalid_state("Violation is not NOTICE_SENT")
    now = DB.now()
    v["status"] = "CURED"
    v["cured_at"] = now
    touch(v)
    return ok_object(violation_out(v))


@bp.route("/mpc/violations/<vid>/escalate", methods=["POST"])
def escalate_violation(vid):
    _, role = actor()
    require_roles(role, REVIEWER)
    v = get_or_404("violation", DB.violations, vid)
    data = body()
    check_no_undeclared(data, set())
    if v["status"] != "NOTICE_SENT":
        invalid_state("Violation is not NOTICE_SENT")
    if DB.now() <= v["cure_deadline"]:
        err("ERR_CURE_WINDOW_OPEN", 409, "Cure window is still open")
    v["status"] = "ESCALATED"
    touch(v)
    return ok_object(violation_out(v))


@bp.route("/mpc/violations/<vid>/schedule-hearing", methods=["POST"])
def schedule_hearing(vid):
    _, role = actor()
    require_roles(role, ["AssociationDirector"])
    v = get_or_404("violation", DB.violations, vid)
    data = body()
    check_no_undeclared(data, {"hearing_date"})
    hearing = req_datetime(data, "hearing_date")
    if v["status"] != "ESCALATED":
        invalid_state("Violation is not ESCALATED")
    if hearing <= DB.now():
        err("ERR_SEND_AT_IN_PAST", 422,
            "hearing_date must be strictly after the logical clock")
    v["status"] = "HEARING_SCHEDULED"
    touch(v)
    return ok_object(violation_out(v))


@bp.route("/mpc/violations/<vid>/levy-fine", methods=["POST"])
def levy_fine(vid):
    user_id, role = actor()
    require_roles(role, ["AssociationDirector"])
    v = get_or_404("violation", DB.violations, vid)
    data = body()
    check_no_undeclared(data, set())
    if v["status"] != "HEARING_SCHEDULED":
        invalid_state("Violation is not HEARING_SCHEDULED")
    now = DB.now()
    days = calendar_days(v["cure_deadline"], now)
    v["fine_cents"] = _tiered_fine(days)
    v["fined_by_user_id"] = user_id
    v["_fined_at"] = now
    v["status"] = "FINED"
    touch(v)
    return ok_object(violation_out(v))


@bp.route("/mpc/violations/<vid>/record-payment", methods=["POST"])
def record_violation_payment(vid):
    _, role = actor()
    require_roles(role, ["DeclarantController"])
    v = get_or_404("violation", DB.violations, vid)
    data = body()
    check_no_undeclared(data, {"payment_cents"})
    payment = req_int(data, "payment_cents")
    if v["status"] != "FINED":
        invalid_state("Violation is not FINED")
    if payment != v["fine_cents"]:
        err("ERR_PENALTY_AMOUNT_MISMATCH", 402,
            "payment_cents must equal fine_cents exactly")
    v["status"] = "PAID"
    touch(v)
    return ok_object(violation_out(v))


@bp.route("/mpc/violations/<vid>/appeal", methods=["POST"])
def appeal_violation(vid):
    user_id, role = actor()
    require_roles(role, ["HomeownerResident", "BuilderRep"])
    v = get_or_404("violation", DB.violations, vid)
    if role == "HomeownerResident":
        if v["respondent_resident_id"] is None or v["respondent_resident_id"] != user_id:
            err("ERR_FORBIDDEN_ROLE", 403, "Actor does not match the respondent")
    else:
        if v["respondent_builder_id"] is None or v["respondent_builder_id"] != user_id:
            err("ERR_FORBIDDEN_ROLE", 403, "Actor does not match the respondent")
    data = body()
    check_no_undeclared(data, {"appeal_reason"})
    req_string(data, "appeal_reason")
    if v["status"] != "FINED":
        invalid_state("Violation is not FINED")
    now = DB.now()
    if now > v["_fined_at"] + timedelta(days=APPEAL_WINDOW_DAYS):
        err("ERR_APPEAL_WINDOW_EXPIRED", 422, "Appeal window has expired")
    v["status"] = "APPEALED"
    touch(v)
    return ok_object(violation_out(v))


@bp.route("/mpc/violations/<vid>/resolve-appeal", methods=["POST"])
def resolve_appeal(vid):
    user_id, role = actor()
    require_roles(role, ["AssociationDirector"])
    v = get_or_404("violation", DB.violations, vid)
    data = body()
    check_no_undeclared(data, {"outcome"})
    outcome = data.get("outcome")
    if outcome not in ("APPEAL_UPHELD", "APPEAL_DENIED"):
        validation("outcome must be APPEAL_UPHELD or APPEAL_DENIED")
    if v["status"] != "APPEALED":
        invalid_state("Violation is not APPEALED")
    if user_id == v["fined_by_user_id"]:
        err("ERR_HEARING_OFFICER_CONFLICT", 403,
            "The director who levied the fine may not resolve its appeal")
    now = DB.now()
    if outcome == "APPEAL_UPHELD":
        v["status"] = "DISMISSED"
        v["fine_cents"] = 0
    else:
        days = calendar_days(v["cure_deadline"], now)
        v["fine_cents"] = _tiered_fine(days)
        v["_fined_at"] = now
        v["status"] = "FINED"
    touch(v)
    return ok_object(violation_out(v))
