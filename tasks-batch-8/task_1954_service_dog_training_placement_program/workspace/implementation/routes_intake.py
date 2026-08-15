"""Routes: logical clock, applicants, assessments, waitlist entries, contributions."""
from flask import Blueprint

from core import (
    STORE,
    ApiError,
    body,
    check_terminal,
    err_already_terminal,
    err_invalid_state,
    err_not_found,
    err_ownership,
    err_ref_not_found,
    err_validation,
    get_or_404,
    now,
    paginate,
    pagination_params,
    require_roles,
    respond,
    today,
    touch,
    v_datetime,
    v_enum,
    v_int,
    v_str,
    v_str_array,
)
from core import base_fields, CLOCK, parse_datetime_val
from services import (
    compute_rank_score,
    effective_requirement,
    entry_of_applicant,
    fundraising_final,
    fundraising_provisional,
    latest_accepted_assessment,
    run_sweep,
    ser_applicant,
    ser_assessment,
    ser_contribution,
    ser_match,
    ser_partnership,
    ser_waitlist_entry,
    settle_entry,
    withdraw_applicant,
    TASK_CODES,
    PLACEMENT_TRACKS,
)

bp = Blueprint("intake", __name__)

APPLICANT_STATUSES = {
    "SUBMITTED",
    "IN_REVIEW",
    "NEEDS_INFO",
    "WAITLISTED",
    "MATCH_ELIGIBLE",
    "MATCHED",
    "TEAM_TRAINING",
    "PLACED",
    "DENIED",
    "WITHDRAWN",
}

URGENCY_TIERS = {"STANDARD", "HIGH", "CRITICAL"}


def _load_applicant_authorized(rid, role, uid, applicant_read=False):
    """Load applicant; Applicant role may only target its own id."""
    if role == "Applicant" and rid != uid:
        raise err_ownership("Applicant may only access its own record")
    return get_or_404("applicants", rid)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
@bp.route("/api/_clock/set_current_utc", methods=["POST"])
def set_clock():
    b = body()
    to_dt = v_datetime(b, "to_iso8601", required=True)
    role, uid = require_roles("ProgramAdmin")
    CLOCK[0] = to_dt
    missed, due = run_sweep()
    from core import fmt_ts

    return respond(
        {
            "current_utc": fmt_ts(CLOCK[0]),
            "swept_followups_missed": missed,
            "swept_partnerships_recert_due": due,
        }
    )


# ---------------------------------------------------------------------------
# Applicants
# ---------------------------------------------------------------------------
@bp.route("/api/applicants", methods=["POST"])
def create_applicant():
    b = body()
    full_name = v_str(b, "full_name")
    email = v_str(b, "email")
    track = v_enum(b, "placement_track", PLACEMENT_TRACKS)
    income = v_int(b, "household_income_cents", min_v=0)
    region = v_str(b, "region")
    role, uid = require_roles("IntakeCoordinator", "ProgramAdmin")
    # email unique across applicants
    for a in STORE["applicants"].values():
        if a["email"] == email:
            raise err_validation("email must be unique across applicants")
    a = base_fields()
    a.update(
        {
            "full_name": full_name,
            "email": email,
            "placement_track": track,
            "household_income_cents": income,
            "verified_income_cents": None,
            "region": region,
            "application_status": "SUBMITTED",
            "reviewed_by_user_id": None,
            "approved_by_user_id": None,
            "denial_reason": None,
        }
    )
    STORE["applicants"][a["id"]] = a
    return respond(ser_applicant(a), 201)


@bp.route("/api/applicants/<rid>", methods=["GET"])
def get_applicant(rid):
    role, uid = require_roles(
        "IntakeCoordinator", "ProgramAdmin", "TrainingDirector", "Applicant"
    )
    a = _load_applicant_authorized(rid, role, uid)
    return respond(ser_applicant(a))


@bp.route("/api/applicants", methods=["GET"])
def list_applicants():
    role, uid = require_roles("IntakeCoordinator", "ProgramAdmin", "TrainingDirector")
    items = list(STORE["applicants"].values())
    status = _q("application_status")
    if status is not None:
        items = [a for a in items if a["application_status"] == status]
    track = _q("placement_track")
    if track is not None:
        items = [a for a in items if a["placement_track"] == track]
    return paginate(items, ser_applicant)


def _q(name):
    from flask import request

    v = request.args.get(name)
    return v if v not in (None, "") else None


@bp.route("/api/applicants/<rid>/begin-review", methods=["POST"])
def begin_review(rid):
    role, uid = require_roles("IntakeCoordinator")
    a = get_or_404("applicants", rid)
    check_terminal("applicants", a, "application_status")
    if a["application_status"] != "SUBMITTED":
        raise err_invalid_state("Applicant is not SUBMITTED")
    a["application_status"] = "IN_REVIEW"
    a["reviewed_by_user_id"] = uid
    touch(a)
    return respond(ser_applicant(a))


@bp.route("/api/applicants/<rid>/request-info", methods=["POST"])
def request_info(rid):
    b = body()
    note = v_str(b, "info_request_note")
    role, uid = require_roles("IntakeCoordinator")
    a = get_or_404("applicants", rid)
    check_terminal("applicants", a, "application_status")
    if a["application_status"] != "IN_REVIEW":
        raise err_invalid_state("Applicant is not IN_REVIEW")
    a["application_status"] = "NEEDS_INFO"
    touch(a)
    return respond(ser_applicant(a))


@bp.route("/api/applicants/<rid>/resubmit", methods=["POST"])
def resubmit(rid):
    role, uid = require_roles("Applicant")
    if rid != uid:
        raise err_ownership("Applicant may only resubmit its own application")
    a = get_or_404("applicants", rid)
    if a["application_status"] != "NEEDS_INFO":
        raise err_invalid_state("Applicant is not NEEDS_INFO")
    a["application_status"] = "IN_REVIEW"
    touch(a)
    return respond(ser_applicant(a))


@bp.route("/api/applicants/<rid>/approve", methods=["POST"])
def approve(rid):
    role, uid = require_roles("IntakeCoordinator")
    a = get_or_404("applicants", rid)
    check_terminal("applicants", a, "application_status")
    if a["application_status"] != "IN_REVIEW":
        raise err_invalid_state("Applicant is not IN_REVIEW")
    assessment = latest_accepted_assessment(a["id"])
    if assessment is None:
        raise ApiError(
            "ERR_ASSESSMENT_REQUIRED",
            409,
            "Approve requires a FINALIZED_ACCEPTED task assessment",
        )
    a["application_status"] = "WAITLISTED"
    a["approved_by_user_id"] = uid
    touch(a)
    # create waitlist entry with provisional requirement + initial rank;
    # raised_cents honors the ledger invariant (sum of RECEIVED contributions)
    initial_raised = sum(
        c["amount_cents"]
        for c in STORE["contributions"].values()
        if c["applicant_id"] == a["id"] and c["status"] == "RECEIVED"
    )
    e = base_fields()
    e.update(
        {
            "applicant_id": a["id"],
            "status": "PENDING",
            "listed_at": now(),
            "requirement_provisional_cents": fundraising_provisional(
                a["placement_track"], a["household_income_cents"]
            ),
            "requirement_final_cents": None,
            "raised_cents": initial_raised,
            "dissolved_match_count": 0,
            "rank_score": 0.0,
        }
    )
    e["rank_score"] = compute_rank_score(e)
    STORE["waitlist_entries"][e["id"]] = e
    # eligibility evaluated against the ledger at creation
    settle_entry(e)
    return respond(ser_applicant(a))


@bp.route("/api/applicants/<rid>/deny", methods=["POST"])
def deny(rid):
    b = body()
    reason = v_str(b, "denial_reason")
    role, uid = require_roles("IntakeCoordinator")
    a = get_or_404("applicants", rid)
    check_terminal("applicants", a, "application_status")
    if a["application_status"] not in ("IN_REVIEW", "NEEDS_INFO"):
        raise err_invalid_state("Applicant is not IN_REVIEW or NEEDS_INFO")
    a["application_status"] = "DENIED"
    a["denial_reason"] = reason
    touch(a)
    return respond(ser_applicant(a))


@bp.route("/api/applicants/<rid>/withdraw", methods=["POST"])
def withdraw(rid):
    role, uid = require_roles("Applicant", "IntakeCoordinator")
    if role == "Applicant" and rid != uid:
        raise err_ownership("Applicant may only withdraw its own application")
    a = get_or_404("applicants", rid)
    check_terminal("applicants", a, "application_status")
    if a["application_status"] not in (
        "SUBMITTED",
        "IN_REVIEW",
        "NEEDS_INFO",
        "WAITLISTED",
        "MATCH_ELIGIBLE",
        "MATCHED",
        "TEAM_TRAINING",
    ):
        raise err_invalid_state(
            "Withdrawal not permitted from %s" % a["application_status"]
        )
    withdraw_applicant(a)
    return respond(ser_applicant(a))


# --- applicant sub-resource lists ------------------------------------------
@bp.route("/api/applicants/<rid>/assessments", methods=["GET"])
def applicant_assessments(rid):
    role, uid = require_roles(
        "IntakeCoordinator", "ProgramAdmin", "TrainingDirector", "Applicant"
    )
    a = _load_applicant_authorized(rid, role, uid)
    from core import list_all

    items = [
        t for t in STORE["assessments"].values() if t["applicant_id"] == a["id"]
    ]
    return list_all(items, ser_assessment)


@bp.route("/api/applicants/<rid>/waitlist-entries", methods=["GET"])
def applicant_waitlist_entries(rid):
    role, uid = require_roles(
        "IntakeCoordinator", "ProgramAdmin", "TrainingDirector", "Applicant"
    )
    a = _load_applicant_authorized(rid, role, uid)
    from core import list_all

    items = [
        e
        for e in STORE["waitlist_entries"].values()
        if e["applicant_id"] == a["id"]
    ]
    return list_all(items, ser_waitlist_entry)


@bp.route("/api/applicants/<rid>/contributions", methods=["GET"])
def applicant_contributions(rid):
    role, uid = require_roles("IntakeCoordinator", "ProgramAdmin", "Applicant")
    a = _load_applicant_authorized(rid, role, uid)
    from core import list_all

    items = [
        c for c in STORE["contributions"].values() if c["applicant_id"] == a["id"]
    ]
    return list_all(items, ser_contribution)


@bp.route("/api/applicants/<rid>/partnerships", methods=["GET"])
def applicant_partnerships(rid):
    role, uid = require_roles(
        "IntakeCoordinator", "ProgramAdmin", "TrainingDirector", "Applicant"
    )
    a = _load_applicant_authorized(rid, role, uid)
    from core import list_all

    items = [
        p for p in STORE["partnerships"].values() if p["applicant_id"] == a["id"]
    ]
    return list_all(items, ser_partnership)


# ---------------------------------------------------------------------------
# Task assessments
# ---------------------------------------------------------------------------
@bp.route("/api/applicants/<rid>/assessments", methods=["POST"])
def create_assessment(rid):
    b = body()
    tasks = v_str_array(b, "required_tasks", members=TASK_CODES, min_len=1)
    tier = v_enum(b, "task_urgency_tier", URGENCY_TIERS)
    home = v_int(b, "home_environment_score", min_v=0, max_v=10)
    notes = v_str(b, "notes", required=False)
    role, uid = require_roles("IntakeCoordinator")
    a = get_or_404("applicants", rid)
    t = base_fields()
    t.update(
        {
            "applicant_id": a["id"],
            "required_tasks": list(tasks),
            "task_urgency_tier": tier,
            "home_environment_score": home,
            "status": "DRAFT",
            "finalized_by_user_id": None,
            "notes": notes,
        }
    )
    STORE["assessments"][t["id"]] = t
    return respond(ser_assessment(t), 201)


@bp.route("/api/assessments/<rid>", methods=["GET"])
def get_assessment(rid):
    role, uid = require_roles("IntakeCoordinator", "ProgramAdmin", "TrainingDirector")
    t = get_or_404("assessments", rid)
    return respond(ser_assessment(t))


@bp.route("/api/assessments/<rid>/finalize", methods=["POST"])
def finalize_assessment(rid):
    b = body()
    outcome = v_str(b, "outcome")
    if outcome in ("ACCEPT", "ACCEPTED", "FINALIZED_ACCEPTED"):
        new_status = "FINALIZED_ACCEPTED"
    elif outcome in ("REJECT", "REJECTED", "FINALIZED_REJECTED"):
        new_status = "FINALIZED_REJECTED"
    else:
        raise err_validation("outcome must be ACCEPT or REJECT")
    role, uid = require_roles("IntakeCoordinator")
    t = get_or_404("assessments", rid)
    if t["status"] != "DRAFT":
        raise err_invalid_state("Assessment is not DRAFT")
    t["status"] = new_status
    t["finalized_by_user_id"] = uid
    touch(t)
    return respond(ser_assessment(t))


# ---------------------------------------------------------------------------
# Waitlist entries
# ---------------------------------------------------------------------------
@bp.route("/api/waitlist-entries/<rid>", methods=["GET"])
def get_entry(rid):
    role, uid = require_roles(
        "IntakeCoordinator", "ProgramAdmin", "TrainingDirector", "Applicant"
    )
    e = get_or_404("waitlist_entries", rid)
    if role == "Applicant" and e["applicant_id"] != uid:
        raise err_ownership("Applicant may only view its own waitlist entries")
    return respond(ser_waitlist_entry(e))


@bp.route("/api/waitlist-entries", methods=["GET"])
def list_entries():
    role, uid = require_roles("IntakeCoordinator", "ProgramAdmin", "TrainingDirector")
    items = list(STORE["waitlist_entries"].values())
    status = _q("status")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    return paginate(items, ser_waitlist_entry)


@bp.route("/api/waitlist-entries/<rid>/recalculate", methods=["POST"])
def recalculate_entry(rid):
    b = body()
    verified = v_int(b, "verified_income_cents", min_v=0)
    role, uid = require_roles("IntakeCoordinator")
    e = get_or_404("waitlist_entries", rid)
    check_terminal("waitlist_entries", e)
    a = get_or_404("applicants", e["applicant_id"])
    e["requirement_final_cents"] = fundraising_final(
        a["placement_track"], verified
    )
    a["verified_income_cents"] = verified
    touch(a)
    settle_entry(e, mutated=True)
    return respond(ser_waitlist_entry(e))


@bp.route("/api/waitlist-entries/<rid>/suspend", methods=["POST"])
def suspend_entry(rid):
    role, uid = require_roles("IntakeCoordinator")
    e = get_or_404("waitlist_entries", rid)
    check_terminal("waitlist_entries", e)
    if e["status"] not in ("PENDING", "ELIGIBLE"):
        raise err_invalid_state("Entry is not PENDING or ELIGIBLE")
    e["status"] = "SUSPENDED"
    touch(e)
    return respond(ser_waitlist_entry(e))


@bp.route("/api/waitlist-entries/<rid>/reinstate", methods=["POST"])
def reinstate_entry(rid):
    role, uid = require_roles("IntakeCoordinator")
    e = get_or_404("waitlist_entries", rid)
    check_terminal("waitlist_entries", e)
    if e["status"] != "SUSPENDED":
        raise err_invalid_state("Entry is not SUSPENDED")
    req = effective_requirement(e)
    e["status"] = "ELIGIBLE" if e["raised_cents"] >= req else "PENDING"
    settle_entry(e, mutated=True)
    return respond(ser_waitlist_entry(e))


@bp.route("/api/waitlist-entries/<rid>/matches", methods=["GET"])
def entry_matches(rid):
    role, uid = require_roles(
        "IntakeCoordinator", "ProgramAdmin", "TrainingDirector", "Applicant"
    )
    e = get_or_404("waitlist_entries", rid)
    if role == "Applicant" and e["applicant_id"] != uid:
        raise err_ownership("Applicant may only view its own matches")
    from core import list_all

    items = [
        m for m in STORE["matches"].values() if m["waitlist_entry_id"] == e["id"]
    ]
    return list_all(items, ser_match)


# ---------------------------------------------------------------------------
# Contributions
# ---------------------------------------------------------------------------
@bp.route("/api/applicants/<rid>/contributions", methods=["POST"])
def create_contribution(rid):
    b = body()
    donor = v_str(b, "donor_name")
    amount = v_int(b, "amount_cents", min_v=1)
    role, uid = require_roles("IntakeCoordinator")
    a = get_or_404("applicants", rid)
    if a["application_status"] in ("DENIED", "WITHDRAWN", "PLACED"):
        raise ApiError(
            "ERR_APPLICANT_NOT_ACTIVE",
            409,
            "Applicant is not active for fundraising",
        )
    if amount < 100:
        raise ApiError(
            "ERR_CONTRIBUTION_BELOW_MINIMUM",
            422,
            "amount_cents must be at least 100",
        )
    c = base_fields()
    c.update(
        {
            "applicant_id": a["id"],
            "donor_name": donor,
            "amount_cents": amount,
            "status": "PLEDGED",
            "created_by_user_id": uid,
            "received_by_user_id": None,
        }
    )
    STORE["contributions"][c["id"]] = c
    return respond(ser_contribution(c), 201)


@bp.route("/api/contributions/<rid>", methods=["GET"])
def get_contribution(rid):
    role, uid = require_roles("IntakeCoordinator", "ProgramAdmin", "Applicant")
    c = get_or_404("contributions", rid)
    if role == "Applicant" and c["applicant_id"] != uid:
        raise err_ownership("Applicant may only view its own contributions")
    return respond(ser_contribution(c))


@bp.route("/api/contributions/<rid>/receive", methods=["POST"])
def receive_contribution(rid):
    role, uid = require_roles("IntakeCoordinator")
    c = get_or_404("contributions", rid)
    check_terminal("contributions", c)
    if c["status"] != "PLEDGED":
        raise err_invalid_state("Contribution is not PLEDGED")
    if uid == c["created_by_user_id"]:
        raise ApiError(
            "ERR_SOD_CONFLICT",
            409,
            "Receiving operator must differ from the recording operator",
        )
    c["status"] = "RECEIVED"
    c["received_by_user_id"] = uid
    touch(c)
    entry = entry_of_applicant(c["applicant_id"])
    if entry is not None and entry["status"] != "CLOSED":
        entry["raised_cents"] += c["amount_cents"]
        settle_entry(entry, mutated=True)
    return respond(ser_contribution(c))


@bp.route("/api/contributions/<rid>/refund", methods=["POST"])
def refund_contribution(rid):
    role, uid = require_roles("IntakeCoordinator")
    c = get_or_404("contributions", rid)
    check_terminal("contributions", c)
    if c["status"] != "RECEIVED":
        raise err_invalid_state("Contribution is not RECEIVED")
    a = get_or_404("applicants", c["applicant_id"])
    entry = entry_of_applicant(c["applicant_id"])
    entry_matched = entry is not None and entry["status"] == "MATCHED"
    if a["application_status"] == "PLACED" or entry_matched:
        raise ApiError(
            "ERR_REFUND_NOT_ALLOWED",
            409,
            "Refund blocked once the entry is MATCHED or the applicant is PLACED",
        )
    c["status"] = "REFUNDED"
    touch(c)
    if entry is not None and entry["status"] != "CLOSED":
        entry["raised_cents"] -= c["amount_cents"]
        settle_entry(entry, mutated=True)
    return respond(ser_contribution(c))
