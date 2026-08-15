"""ReviewRound endpoints (PRD §3.5/§3.6). Rounds are system-created only."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_ROUND_NOT_FOUND,
    ERR_OWNERSHIP_MISMATCH,
    ERR_INVALID_ROUND_STATE,
    ERR_ROUND_SEALED,
    ERR_SOD_CERTIFIER_VOTED,
    ERR_NO_ELIGIBLE_VOTERS,
    ERR_QUORUM_NOT_MET,
)
from middleware import authorized, ALL_READ_ROLES
from response import success_object
from routes.helpers import public, list_sealed, check_seal_single
from services import calculations as calc
from services.core import touch, case_of_round
from util import CLOCK, parse_dt
from validate import get_body, req_str, req_enum, require_path

bp = Blueprint("rounds", __name__)

RECOMMENDATIONS = {"STRONGLY_SUPPORT", "SUPPORT", "NEUTRAL", "OPPOSE", "STRONGLY_OPPOSE"}

STAGE_FOR_LEVEL = {
    "DEPARTMENT": "DEPT_COMMITTEE",
    "COLLEGE": "COLLEGE_COMMITTEE",
    "UNIVERSITY": "UNIVERSITY_COMMITTEE",
}


def _require_chair(caller, round_rec):
    """Priority 5: acting user is an active CHAIR of the round's committee."""
    for m in db["members"].values():
        if (m["committee_id"] == round_rec["committee_id"]
                and m["id"] == caller.user_id
                and m["role_in_committee"] == "CHAIR"
                and m["is_active"]):
            return m
    raise_error(ERR_OWNERSHIP_MISMATCH,
                "acting user is not an active CHAIR of this round's committee")


def _check_unsealed(round_rec):
    """The owning case's stage must still match the round's level."""
    case = case_of_round(round_rec)
    expected_stage = STAGE_FOR_LEVEL.get(round_rec["level"])
    if case is None or case["stage"] != expected_stage:
        raise_error(ERR_ROUND_SEALED,
                    "the owning case has advanced past this round's level")
    return case


@bp.get("/rounds")
def list_rounds():
    return list_sealed("rounds", {
        "case_id": request.args.get("case_id"),
        "committee_id": request.args.get("committee_id"),
        "level": request.args.get("level"),
        "status": request.args.get("status"),
    }, case_id_of=lambda r: r["case_id"])


@bp.get("/rounds/<rid>")
def get_round(rid):
    from middleware import get_caller, check_role_allowed
    caller = get_caller()
    check_role_allowed(caller, ALL_READ_ROLES)
    rnd = require_path("rounds", rid, ERR_ROUND_NOT_FOUND)
    check_seal_single(caller, case_of_round(rnd))
    return success_object(public(rnd))


@bp.post("/rounds/<rid>/open")
def open_round(rid):
    caller = authorized(["CommitteeChair"])
    rnd = require_path("rounds", rid, ERR_ROUND_NOT_FOUND)
    _require_chair(caller, rnd)
    if rnd["status"] != "SCHEDULED":
        raise_error(ERR_INVALID_ROUND_STATE,
                    f"cannot open a round in status {rnd['status']}")
    _check_unsealed(rnd)
    now = CLOCK.now()
    rnd["opened_at"] = CLOCK.now_iso()
    rnd["status"] = "VOTING_OPEN"
    members = [
        m for m in db["members"].values()
        if m["committee_id"] == rnd["committee_id"] and m["is_active"]
        and parse_dt(m["service_start"]) <= now <= parse_dt(m["service_end"])
    ]
    rnd["active_member_count"] = len(members)
    rnd["recusal_count"] = 0
    calc.recompute_round_tallies(rnd)  # eligible = M, quorum_required, zeros
    touch(rnd)
    return success_object(public(rnd))


@bp.post("/rounds/<rid>/close-voting")
def close_voting(rid):
    caller = authorized(["CommitteeChair"])
    rnd = require_path("rounds", rid, ERR_ROUND_NOT_FOUND)
    _require_chair(caller, rnd)
    if rnd["status"] != "VOTING_OPEN":
        raise_error(ERR_INVALID_ROUND_STATE,
                    f"cannot close voting on a round in status {rnd['status']}")
    rnd["status"] = "TALLYING"
    calc.recompute_round_tallies(rnd)
    touch(rnd)
    return success_object(public(rnd))


@bp.post("/rounds/<rid>/certify")
def certify_round(rid):
    caller = authorized(["CommitteeChair"])
    rnd = require_path("rounds", rid, ERR_ROUND_NOT_FOUND)
    _require_chair(caller, rnd)
    if rnd["status"] != "TALLYING":
        raise_error(ERR_INVALID_ROUND_STATE,
                    f"cannot certify a round in status {rnd['status']}")
    # PRD §3.6 stated gate order for certification: payload shape, then the
    # tally gates (eligible electorate first, then quorum), and finally the
    # certifier segregation-of-duties rule.
    body = get_body()
    recommendation = req_enum(body, "recommendation", RECOMMENDATIONS)
    letter_text = req_str(body, "letter_text")
    if (rnd.get("eligible_voter_count") or 0) < 1:
        raise_error(ERR_NO_ELIGIBLE_VOTERS, "no eligible voters remain in the round")
    if not rnd.get("quorum_met"):
        raise_error(ERR_QUORUM_NOT_MET, "votes_cast is below quorum_required")
    for v in db["votes"].values():
        if (v["round_id"] == rnd["id"] and v["member_id"] == caller.user_id
                and v["status"] == "CAST"):
            raise_error(ERR_SOD_CERTIFIER_VOTED,
                        "the certifying chair holds a ballot in this round")
    calc.recompute_round_tallies(rnd)
    rnd["yes_percentage"] = calc.compute_yes_percentage(rnd)
    rnd["passed"] = calc.compute_passed(rnd)
    rnd["recommendation"] = recommendation
    rnd["letter_text"] = letter_text
    rnd["certified_at"] = CLOCK.now_iso()
    rnd["status"] = "COMPLETED"
    touch(rnd)
    return success_object(public(rnd))


@bp.post("/rounds/<rid>/reopen")
def reopen_round(rid):
    caller = authorized(["CommitteeChair"])
    rnd = require_path("rounds", rid, ERR_ROUND_NOT_FOUND)
    _require_chair(caller, rnd)
    if rnd["status"] != "COMPLETED":
        raise_error(ERR_INVALID_ROUND_STATE,
                    f"cannot reopen a round in status {rnd['status']}")
    case = _check_unsealed(rnd)
    # A newer round at the same level (e.g. from a remand) seals this one.
    latest = calc.latest_round_at_level(case["id"], rnd["level"])
    if latest is None or latest["id"] != rnd["id"]:
        raise_error(ERR_ROUND_SEALED,
                    "a newer round exists at this level")
    rnd["certified_at"] = None
    rnd["passed"] = None
    rnd["yes_percentage"] = None
    rnd["recommendation"] = None
    rnd["letter_text"] = None
    rnd["status"] = "VOTING_OPEN"
    calc.recompute_round_tallies(rnd)
    touch(rnd)
    return success_object(public(rnd))
