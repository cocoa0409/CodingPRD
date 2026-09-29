"""Conduct cases and college-recruiting access grants."""
from datetime import timedelta

from flask import Blueprint

import calc
import listing
import services
import validate
from auth import guard
from envelope import object_response
from errors import ApiError
from store import (
    db, bump, clock, clock_iso, dt_of, find, insert, iso, new_row, public,
)

bp = Blueprint("cases", __name__)

INCIDENT_CODES = (
    "SPECTATOR_INTERFERENCE",
    "COACHING_VIOLATION",
    "ABUSIVE_LANGUAGE",
    "CADDIE_ADVICE_BREACH",
    "PHYSICAL_ALTERCATION",
    "SCORE_TAMPERING",
)


@bp.route("/conduct-cases", methods=["POST"])
def create_conduct_case():
    caller = guard(("RulesOfficial", "ChiefReferee", "TourAdmin"))
    body = validate.body()
    member_id = validate.req_id(body, "member_id")
    tournament_id = validate.req_id(body, "tournament_id")
    subject_type = validate.req_enum(body, "subject_type", ("PARENT", "CADDIE"))
    subject_name = validate.req_str(body, "subject_name", 1, 120)
    incident_code = validate.req_enum(body, "incident_code", INCIDENT_CODES)
    narrative = validate.req_str(body, "narrative", 1, 4000)

    member = find("members", member_id, "ERR_MEMBER_NOT_FOUND")
    tournament = find("tournaments", tournament_id, "ERR_TOURNAMENT_NOT_FOUND")

    row = new_row()
    row.update(
        {
            "member_id": member["id"],
            "tournament_id": tournament["id"],
            "subject_type": subject_type,
            "subject_name": subject_name,
            "incident_code": incident_code,
            "narrative": narrative,
            "filed_by_user_id": caller.user_id,
            "decided_by_user_id": None,
            "status": "UNDER_REVIEW",
            "points_assessed": 0,
            "cumulative_points_at_decision": None,
            "sanction_tier": None,
            "appeal_count": 0,
            "decided_at": None,
        }
    )
    insert("conduct_cases", row)
    return object_response(public(row), 201)


@bp.route("/conduct-cases", methods=["GET"])
def list_conduct_cases():
    guard(("TourAdmin", "ChiefReferee", "ConductCommittee"))
    return listing.listing(
        "conduct_cases",
        ("member_id", "tournament_id", "subject_type", "incident_code", "status",
         "sanction_tier", "filed_by_user_id"),
    )


@bp.route("/conduct-cases/<case_id>", methods=["GET"])
def get_conduct_case(case_id):
    guard(("TourAdmin", "ChiefReferee", "ConductCommittee"))
    case = find("conduct_cases", case_id, "ERR_CASE_NOT_FOUND")
    return object_response(public(case))


@bp.route("/conduct-cases/<case_id>/decide", methods=["POST"])
def decide_conduct_case(case_id):
    caller = guard(("ConductCommittee",))
    body = validate.body()
    decision = validate.req_enum(body, "decision", ("SANCTIONED", "CLEARED"))
    case = find("conduct_cases", case_id, "ERR_CASE_NOT_FOUND")
    if caller.user_id == case["filed_by_user_id"]:
        raise ApiError("ERR_SELF_ADJUDICATION")
    if case["status"] not in ("UNDER_REVIEW", "APPEAL_OPEN"):
        raise ApiError("ERR_INVALID_CONDUCT_STATE")
    member = db.members.get(case["member_id"])
    from_appeal = case["status"] == "APPEAL_OPEN"

    if decision == "CLEARED":
        case["status"] = "CLEARED"
        case["points_assessed"] = 0
        case["sanction_tier"] = None
        case["decided_by_user_id"] = caller.user_id
        case["decided_at"] = clock_iso()
        bump(case)
        if from_appeal and member is not None:
            # granting the appeal compensates: recompute the decayed total
            total = services.conduct_prior_points(member, None)
            member["conduct_points"] = total
            if (
                total < calc.SUSPENSION_POINTS_THRESHOLD
                and member["eligibility_status"] == "SUSPENDED"
            ):
                member["eligibility_status"] = "VERIFIED"
            bump(member)
        return object_response(public(case))

    if from_appeal:
        # denying the appeal re-stamps the decision and fires no new cascade
        case["status"] = "SANCTIONED"
        case["decided_by_user_id"] = caller.user_id
        case["decided_at"] = clock_iso()
        bump(case)
        return object_response(public(case))

    points = calc.CONDUCT_POINTS_BY_CODE[case["incident_code"]]
    prior = 0
    if member is not None:
        prior = services.conduct_prior_points(member, case["id"])
    cumulative = prior + points
    tier = calc.sanction_tier(cumulative)
    case["status"] = "SANCTIONED"
    case["points_assessed"] = points
    case["cumulative_points_at_decision"] = cumulative
    case["sanction_tier"] = tier
    case["decided_by_user_id"] = caller.user_id
    case["decided_at"] = clock_iso()
    bump(case)

    if member is not None:
        if tier == "MEMBER_SUSPENSION":
            services.suspend_member(member, cumulative)
        else:
            member["conduct_points"] = cumulative
            bump(member)
            if tier == "VENUE_BAN_ONE_EVENT":
                services.venue_ban(member, case)
    return object_response(public(case))


@bp.route("/conduct-cases/<case_id>/appeal", methods=["POST"])
def appeal_conduct_case(case_id):
    caller = guard(("Member", "TourAdmin"))
    body = validate.body()
    validate.req_str(body, "grounds", 1, 2000)
    case = find("conduct_cases", case_id, "ERR_CASE_NOT_FOUND")
    if caller.is_member and caller.user_id != case["member_id"]:
        raise ApiError("ERR_FORBIDDEN_RESOURCE")
    if case["status"] not in ("SANCTIONED", "CLEARED"):
        raise ApiError("ERR_INVALID_CONDUCT_STATE")
    decided = dt_of(case["decided_at"])
    if decided is None or clock() > decided + timedelta(
        days=calc.CONDUCT_APPEAL_WINDOW_DAYS
    ):
        raise ApiError("ERR_APPEAL_WINDOW_EXPIRED")
    case["status"] = "APPEAL_OPEN"
    case["appeal_count"] += 1
    bump(case)
    return object_response(public(case))


# ---------------------------------------------------------------------------
# recruiting access grants
# ---------------------------------------------------------------------------
def _require_grant_access(caller, grant):
    if caller.is_member and caller.user_id != grant["member_id"]:
        raise ApiError("ERR_FORBIDDEN_RESOURCE")
    if caller.is_coach and caller.user_id != grant["coach_user_id"]:
        raise ApiError("ERR_FORBIDDEN_RESOURCE")


@bp.route("/coach-access-grants", methods=["POST"])
def create_coach_access_grant():
    caller = guard(("Coach",))
    body = validate.body()
    member_id = validate.req_id(body, "member_id")
    coach_school = validate.req_str(body, "coach_school", 1, 120)
    scope = validate.req_enum(body, "scope", ("RESULTS_ONLY", "FULL_PROFILE"))
    expected_version = validate.req_int(body, "expected_member_version")

    member = find("members", member_id, "ERR_MEMBER_NOT_FOUND")
    if expected_version != member["version"]:
        raise ApiError("ERR_STALE_MEMBER_VERSION")
    if member["eligibility_status"] == "SUSPENDED":
        raise ApiError("ERR_MEMBER_SUSPENDED")
    if not member["publication_opt_in"]:
        raise ApiError("ERR_PUBLICATION_NOT_CONSENTED")

    for prior in list(db.coach_access_grants.values()):
        if (
            prior["member_id"] == member["id"]
            and prior["coach_user_id"] == caller.user_id
            and prior["status"] in ("REQUESTED", "GRANTED")
        ):
            prior["status"] = "SUPERSEDED"
            bump(prior)

    row = new_row()
    row.update(
        {
            "member_id": member["id"],
            "coach_user_id": caller.user_id,
            "coach_school": coach_school,
            "scope": scope,
            "status": "REQUESTED",
            "requested_at": clock_iso(),
            "decided_at": None,
            "expires_at": None,
        }
    )
    insert("coach_access_grants", row)
    bump(member)
    return object_response(public(row), 201)


@bp.route("/coach-access-grants", methods=["GET"])
def list_coach_access_grants():
    guard(("TourAdmin", "Coach"))
    return listing.listing(
        "coach_access_grants",
        ("member_id", "coach_user_id", "coach_school", "scope", "status"),
    )


@bp.route("/coach-access-grants/<grant_id>", methods=["GET"])
def get_coach_access_grant(grant_id):
    caller = guard(("TourAdmin", "Member", "Coach"))
    grant = find("coach_access_grants", grant_id, "ERR_GRANT_NOT_FOUND")
    _require_grant_access(caller, grant)
    return object_response(public(grant))


@bp.route("/coach-access-grants/<grant_id>/decide", methods=["POST"])
def decide_coach_access_grant(grant_id):
    caller = guard(("Member", "TourAdmin"))
    body = validate.body()
    decision = validate.req_enum(body, "decision", ("GRANTED", "DENIED"))
    grant = find("coach_access_grants", grant_id, "ERR_GRANT_NOT_FOUND")
    if caller.is_member and caller.user_id != grant["member_id"]:
        raise ApiError("ERR_FORBIDDEN_RESOURCE")
    if grant["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_GRANT_STATE")
    member = db.members.get(grant["member_id"])
    if decision == "GRANTED":
        if member is not None and not member["publication_opt_in"]:
            raise ApiError("ERR_PUBLICATION_NOT_CONSENTED")
        now = clock()
        grant["status"] = "GRANTED"
        grant["decided_at"] = iso(now)
        grant["expires_at"] = iso(now + timedelta(days=calc.COACH_GRANT_TERM_DAYS))
    else:
        grant["status"] = "DENIED"
        grant["decided_at"] = clock_iso()
    bump(grant)
    return object_response(public(grant))


@bp.route("/coach-access-grants/<grant_id>/revoke", methods=["POST"])
def revoke_coach_access_grant(grant_id):
    caller = guard(("Member", "TourAdmin"))
    body = validate.body()
    validate.opt_str(body, "reason", 1, 2000)
    grant = find("coach_access_grants", grant_id, "ERR_GRANT_NOT_FOUND")
    if caller.is_member and caller.user_id != grant["member_id"]:
        raise ApiError("ERR_FORBIDDEN_RESOURCE")
    if grant["status"] != "GRANTED":
        raise ApiError("ERR_INVALID_GRANT_STATE")
    grant["status"] = "REVOKED"
    grant["expires_at"] = None
    bump(grant)
    return object_response(public(grant))
