"""Cases (service_status + privacy_posture), needs assessments, case plans."""
from flask import Blueprint, request

import db
import services
from auth import require, get_or_404
from calc import recompute_acuity_submit, recompute_acuity_verify
from envelope import ok, ok_list, paginate
from errors import ApiError, bad_request, forbidden, invalid_state
from util import body_json, req_str, opt_str, req_int, req_enum, req_present

bp = Blueprint("cases", __name__)

SERVICE_STATUSES = {"INTAKE", "ASSESSED", "PLANNING", "ACTIVE", "SUSPENDED",
                    "OUTCOME_REVIEW", "CLOSED"}
PRIVACY_POSTURES = {"STANDARD", "RESTRICTED", "SEALED"}

# allowed service_status transitions: from -> {to: precondition-fn(case, data)}
OPEN_REFERRAL_STATES = ("DRAFT", "SENT", "ACCEPTED", "SUSPENDED")


def _has_verified_assessment(case):
    return any(a for a in db.all_of("assessments")
               if a["case_id"] == case["id"] and a["status"] == "VERIFIED")


def _has_active_plan(case):
    return any(p for p in db.all_of("plans")
               if p["case_id"] == case["id"] and p["status"] == "ACTIVE")


def _no_open_referrals(case):
    return not any(r for r in db.all_of("referrals")
                   if r["case_id"] == case["id"]
                   and r["status"] in OPEN_REFERRAL_STATES)


def _plans_settled(case):
    return all(p["status"] in ("COMPLETED", "SUPERSEDED")
               for p in db.all_of("plans") if p["case_id"] == case["id"])


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------

@bp.route("/cases", methods=["POST"])
def create_case():
    require("IntakeSpecialist", "CaseManager", "CenterAdmin")
    data = body_json()

    # rung 3: body-referenced ids, fixed order: client_id, assigned_manager_id
    client_id = data.get("client_id")
    manager_id = data.get("assigned_manager_id")
    if client_id is not None:
        if not isinstance(client_id, str):
            raise bad_request("client_id must be a string")
        client = get_or_404("clients", client_id, "client")
    else:
        client = None
    if manager_id is not None:
        if not isinstance(manager_id, str):
            raise bad_request("assigned_manager_id must be a string")
        get_or_404("staff", manager_id, "staff")

    # rung 7: structural
    req_present(data, "client_id")
    req_present(data, "assigned_manager_id")
    intake_summary = opt_str(data, "intake_summary", None)

    # rung 9: client must not be EXITED
    if client["status"] == "EXITED":
        raise ApiError("ERR_CLIENT_EXITED", 409,
                       "client has exited services")

    case = db.new_entity("cases", {
        "client_id": client_id,
        "assigned_manager_id": manager_id,
        "service_status": "INTAKE",
        "privacy_posture": "STANDARD",
        "intake_summary": intake_summary,
        "acuity_rapid": None,
        "acuity_verified": None,
        "closed_reason": None,
    })
    # welcome side effect: first case flips REGISTERED -> ACTIVE
    if client["status"] == "REGISTERED":
        client["status"] = "ACTIVE"
        db.touch(client)
    return ok(db.pub(case), status=201)


def _client_owns(case, user_id):
    return case["client_id"] == user_id


@bp.route("/cases/<case_id>", methods=["GET"])
def get_case(case_id):
    user_id, role = require("CenterAdmin", "CaseManager", "IntakeSpecialist",
                            "Client")
    case = get_or_404("cases", case_id, "case")
    if role == "Client" and not _client_owns(case, user_id):
        raise forbidden("clients may read only their own cases")
    return ok(db.pub(case))


@bp.route("/cases", methods=["GET"])
def list_cases():
    user_id, role = require("CenterAdmin", "CaseManager", "IntakeSpecialist",
                            "Client")
    items = db.all_of("cases")
    if role == "Client":
        items = [c for c in items if c["client_id"] == user_id]
    for param, field in (("client_id", "client_id"),
                         ("assigned_manager_id", "assigned_manager_id"),
                         ("status", "service_status")):
        v = request.args.get(param)
        if v is not None:
            items = [c for c in items if c.get(field) == v]
    page, meta = paginate(items)
    return ok_list([db.pub(c) for c in page], meta)


@bp.route("/cases/<case_id>/transition", methods=["POST"])
def transition_case(case_id):
    require("CaseManager", "CenterAdmin")
    case = get_or_404("cases", case_id, "case")
    data = body_json()
    to_status = data.get("to_status")
    if not isinstance(to_status, str) or to_status not in SERVICE_STATUSES:
        raise bad_request("to_status must be a valid service_status")

    frm = case["service_status"]
    allowed = {
        ("INTAKE", "ASSESSED"),
        ("ASSESSED", "PLANNING"),
        ("PLANNING", "ACTIVE"),
        ("ACTIVE", "SUSPENDED"),
        ("SUSPENDED", "ACTIVE"),
        ("ACTIVE", "OUTCOME_REVIEW"),
        ("SUSPENDED", "OUTCOME_REVIEW"),
        ("OUTCOME_REVIEW", "CLOSED"),
    }
    if (frm, to_status) not in allowed:
        raise invalid_state(f"cannot transition case {frm} -> {to_status}")

    # per-transition preconditions (rung 4 state checks)
    if (frm, to_status) == ("INTAKE", "ASSESSED"):
        if not _has_verified_assessment(case):
            raise invalid_state("no VERIFIED assessment exists for the case")
    elif (frm, to_status) in (("PLANNING", "ACTIVE"), ("SUSPENDED", "ACTIVE")):
        if not _has_active_plan(case):
            raise invalid_state("an ACTIVE case plan is required")
    elif to_status == "OUTCOME_REVIEW":
        if not _no_open_referrals(case):
            raise invalid_state("referrals still in flight")
    elif (frm, to_status) == ("OUTCOME_REVIEW", "CLOSED"):
        # rung 4 (plans settled) before rung 7 (closed_reason required)
        if not _plans_settled(case):
            raise invalid_state("all case plans must be COMPLETED or "
                                "SUPERSEDED before closing")
        closed_reason = data.get("closed_reason")
        if not isinstance(closed_reason, str) or not closed_reason:
            raise bad_request("closed_reason is required when closing")
        case["closed_reason"] = closed_reason
        # m1: force any lingering ACTIVE/SUSPENDED plan to COMPLETED
        for plan in db.all_of("plans"):
            if (plan["case_id"] == case["id"]
                    and plan["status"] in ("ACTIVE", "SUSPENDED")):
                plan["status"] = "COMPLETED"
                db.touch(plan)

    case["service_status"] = to_status
    db.touch(case)
    return ok(db.pub(case))


@bp.route("/cases/<case_id>/privacy", methods=["POST"])
def privacy_case(case_id):
    user_id, role = require("CaseManager", "CenterAdmin")
    case = get_or_404("cases", case_id, "case")
    data = body_json()
    to_posture = data.get("to_posture")
    if not isinstance(to_posture, str) or to_posture not in PRIVACY_POSTURES:
        raise bad_request("to_posture must be STANDARD, RESTRICTED or SEALED")
    reason = data.get("reason")
    if not isinstance(reason, str):
        raise bad_request("reason is required")

    frm = case["privacy_posture"]
    # sealing / unsealing are CenterAdmin-only operations
    if (to_posture == "SEALED" or frm == "SEALED") and role != "CenterAdmin":
        raise forbidden("only a CenterAdmin may seal or unseal a case")

    allowed = {("STANDARD", "RESTRICTED"), ("RESTRICTED", "STANDARD"),
               ("STANDARD", "SEALED"), ("RESTRICTED", "SEALED"),
               ("SEALED", "RESTRICTED")}
    if (frm, to_posture) not in allowed:
        raise invalid_state(f"cannot move privacy {frm} -> {to_posture}")

    case["privacy_posture"] = to_posture
    db.touch(case)
    if to_posture == "SEALED":
        services.seal_case_cascade(case)
    # unsealing deliberately resurrects nothing
    return ok(db.pub(case))


# ---------------------------------------------------------------------------
# Needs assessments
# ---------------------------------------------------------------------------

SCORE_FIELDS = ("housing_score", "employment_score", "education_score",
                "language_score", "health_score")


@bp.route("/assessments", methods=["POST"])
def create_assessment():
    user_id, _ = require("IntakeSpecialist", "CaseManager")
    data = body_json()

    case_id = data.get("case_id")
    case = None
    if case_id is not None:
        if not isinstance(case_id, str):
            raise bad_request("case_id must be a string")
        case = get_or_404("cases", case_id, "case")

    # rung 4: CLOSED cases reject new child-service writes
    if case is not None and case["service_status"] == "CLOSED":
        raise invalid_state("case is CLOSED")

    # rung 7: structural
    req_present(data, "case_id")
    scores = {}
    for f in SCORE_FIELDS:
        v = req_int(data, f)
        if v < 0 or v > 4:
            raise bad_request(f"{f} must be in 0..4")
        scores[f] = v
    # one DRAFT per case
    if any(a for a in db.all_of("assessments")
           if a["case_id"] == case_id and a["status"] == "DRAFT"):
        raise ApiError("ERR_DRAFT_ASSESSMENT_EXISTS", 409,
                       "the case already has a DRAFT assessment")

    fields = {"case_id": case_id, "status": "DRAFT",
              "created_by_id": user_id, "verified_by_id": None}
    fields.update(scores)
    assessment = db.new_entity("assessments", fields)
    return ok(db.pub(assessment), status=201)


@bp.route("/assessments/<assessment_id>", methods=["GET"])
def get_assessment(assessment_id):
    require("CenterAdmin", "CaseManager", "IntakeSpecialist")
    a = get_or_404("assessments", assessment_id, "assessment")
    return ok(db.pub(a))


@bp.route("/assessments", methods=["GET"])
def list_assessments():
    require("CenterAdmin", "CaseManager", "IntakeSpecialist")
    items = db.all_of("assessments")
    case_id = request.args.get("case_id")
    if case_id is not None:
        items = [a for a in items if a["case_id"] == case_id]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    page, meta = paginate(items)
    return ok_list([db.pub(a) for a in page], meta)


@bp.route("/assessments/<assessment_id>/submit", methods=["POST"])
def submit_assessment(assessment_id):
    require("IntakeSpecialist", "CaseManager")
    a = get_or_404("assessments", assessment_id, "assessment")
    if a["status"] != "DRAFT":
        raise invalid_state("assessment is not DRAFT")
    a["status"] = "SUBMITTED"
    db.touch(a)
    recompute_acuity_submit(a)
    return ok(db.pub(a))


@bp.route("/assessments/<assessment_id>/verify", methods=["POST"])
def verify_assessment(assessment_id):
    user_id, _ = require("CaseManager", "CenterAdmin")
    a = get_or_404("assessments", assessment_id, "assessment")
    if a["status"] != "SUBMITTED":
        raise invalid_state("assessment is not SUBMITTED")
    # rung 6: segregation of duties
    if user_id == a["created_by_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 409,
                       "verifier must differ from the assessment creator")

    a["status"] = "VERIFIED"
    a["verified_by_id"] = user_id
    db.touch(a)

    # m2: supersede the previously VERIFIED assessment of the same case
    superseded = None
    for other in db.all_of("assessments"):
        if (other["case_id"] == a["case_id"] and other["id"] != a["id"]
                and other["status"] == "VERIFIED"):
            other["status"] = "SUPERSEDED"
            db.touch(other)
            superseded = other

    # m3: auto-revise plans whose basis was just superseded
    if superseded is not None:
        for plan in db.all_of("plans"):
            if (plan["case_id"] == a["case_id"]
                    and plan["status"] in ("ACTIVE", "SUSPENDED")
                    and plan.get("basis_assessment_id") == superseded["id"]):
                plan["status"] = "DRAFT"
                plan["plan_revision"] = plan.get("plan_revision", 1) + 1
                db.touch(plan)

    recompute_acuity_verify(a)
    return ok(db.pub(a))


# ---------------------------------------------------------------------------
# Case plans (OCC-guarded creation under the case)
# ---------------------------------------------------------------------------

PLAN_STATUSES = {"DRAFT", "ACTIVE", "SUSPENDED", "COMPLETED", "SUPERSEDED"}


def _current_verified_assessment(case_id):
    """The case's VERIFIED assessment (latest updated_at; at most one can
    be VERIFIED at a time because verification supersedes the previous)."""
    cands = [a for a in db.all_of("assessments")
             if a["case_id"] == case_id and a["status"] == "VERIFIED"]
    if not cands:
        return None
    return max(cands, key=lambda x: (x["updated_at"], x["_seq"]))


@bp.route("/cases/<case_id>/plans", methods=["POST"])
def create_plan(case_id):
    require("CaseManager", "CenterAdmin")
    case = get_or_404("cases", case_id, "case")
    data = body_json()

    # structural: required fields first
    title = req_str(data, "title")
    budgeted_hours = req_int(data, "budgeted_hours", minimum=1)
    expected = data.get("expected_case_version")
    if expected is None or not isinstance(expected, int) \
            or isinstance(expected, bool):
        raise bad_request("expected_case_version is required")

    # rung 4: CLOSED cases reject new child-service writes
    if case["service_status"] == "CLOSED":
        raise invalid_state("case is CLOSED")

    # OCC: the one guarded write in the API
    if case["version"] != expected:
        raise ApiError("ERR_STALE_CASE_VERSION", 412,
                       "case version has advanced; re-read before planning")

    # supersede the case's current DRAFT/ACTIVE/SUSPENDED plan
    for plan in db.all_of("plans"):
        if (plan["case_id"] == case_id
                and plan["status"] in ("DRAFT", "ACTIVE", "SUSPENDED")):
            plan["status"] = "SUPERSEDED"
            db.touch(plan)

    plan = db.new_entity("plans", {
        "case_id": case_id,
        "title": title,
        "budgeted_hours": budgeted_hours,
        "status": "DRAFT",
        "plan_revision": 1,
        "basis_assessment_id": None,
    })
    db.touch(case)  # plan creation increments the parent case version
    return ok(db.pub(plan), status=201)


@bp.route("/plans/<plan_id>", methods=["GET"])
def get_plan(plan_id):
    require("CenterAdmin", "CaseManager", "IntakeSpecialist")
    plan = get_or_404("plans", plan_id, "plan")
    return ok(db.pub(plan))


@bp.route("/plans", methods=["GET"])
def list_plans():
    require("CenterAdmin", "CaseManager", "IntakeSpecialist")
    items = db.all_of("plans")
    for param in ("case_id", "status", "basis_assessment_id"):
        v = request.args.get(param)
        if v is not None:
            items = [p for p in items if str(p.get(param)) == v]
    page, meta = paginate(items)
    return ok_list([db.pub(p) for p in page], meta)


@bp.route("/plans/<plan_id>/transition", methods=["POST"])
def transition_plan(plan_id):
    require("CaseManager", "CenterAdmin")
    plan = get_or_404("plans", plan_id, "plan")
    data = body_json()
    to_status = data.get("to_status")
    if not isinstance(to_status, str) or to_status not in PLAN_STATUSES:
        raise bad_request("to_status must be a valid plan status")

    frm = plan["status"]
    case = db.get("cases", plan["case_id"])

    if (frm, to_status) == ("DRAFT", "ACTIVE"):
        if case["service_status"] not in ("PLANNING", "ACTIVE", "SUSPENDED"):
            raise invalid_state(
                "parent case must be PLANNING, ACTIVE or SUSPENDED")
        basis = _current_verified_assessment(case["id"])
        if basis is None:
            raise invalid_state("a VERIFIED assessment is required")
        plan["basis_assessment_id"] = basis["id"]
    elif (frm, to_status) == ("ACTIVE", "DRAFT"):
        plan["plan_revision"] = plan.get("plan_revision", 1) + 1
    elif (frm, to_status) == ("ACTIVE", "SUSPENDED"):
        pass
    elif (frm, to_status) == ("SUSPENDED", "ACTIVE"):
        if case["service_status"] == "CLOSED":
            raise invalid_state("parent case is CLOSED")
        basis = _current_verified_assessment(case["id"])
        if basis is not None:
            plan["basis_assessment_id"] = basis["id"]
    elif (frm, to_status) in (("ACTIVE", "COMPLETED"),
                              ("SUSPENDED", "COMPLETED")):
        pass
    else:
        raise invalid_state(f"cannot transition plan {frm} -> {to_status}")

    plan["status"] = to_status
    db.touch(plan)
    return ok(db.pub(plan))
