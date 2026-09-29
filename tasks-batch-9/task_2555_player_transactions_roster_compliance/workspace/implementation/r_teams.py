"""Club registration, limits and cap ledger (PRD 3.1)."""
import re

from flask import Blueprint

import calc
import domain
import shape
import views
from auth import (
    ALL_ROLES, LEAGUE_OFFICER, TEAM_CAP_ANALYST, endpoint,
)
from envelope import collection, filter_records, page_params, paginate, single
from errors import fail
from store import base_record, db, touch, values

bp = Blueprint("teams", __name__)

MARKET_CODE_RE = re.compile(r"^[A-Z]{3}$")


def _validate_market_code(code):
    if not MARKET_CODE_RE.match(code):
        fail("ERR_INVALID_REQUEST", "market_code must be exactly three uppercase letters")
    return code


@bp.route("/teams", methods=["POST"])
@endpoint(LEAGUE_OFFICER)
def create_team(actor):
    body = shape.body()
    name = shape.req_str(body, "name", min_len=1, max_len=80)
    market_code = _validate_market_code(shape.req_str(body, "market_code"))
    salary_cap = shape.req_int(body, "salary_cap_limit_cents", minimum=0)
    priority = shape.req_int(body, "waiver_priority_rank", minimum=1)
    active_limit = shape.opt_int(
        body, "active_roster_limit", calc.DEFAULT_ACTIVE_ROSTER_LIMIT, minimum=1
    )
    reserve_limit = shape.opt_int(
        body, "reserve_roster_limit", calc.DEFAULT_RESERVE_ROSTER_LIMIT, minimum=0
    )
    ir_limit = shape.opt_int(
        body, "injured_reserve_limit", calc.DEFAULT_INJURED_RESERVE_LIMIT, minimum=0
    )
    ps_limit = shape.opt_int(
        body, "practice_squad_limit", calc.DEFAULT_PRACTICE_SQUAD_LIMIT, minimum=0
    )
    for existing in db.teams.values():
        if existing["market_code"] == market_code:
            fail("ERR_DUPLICATE_MARKET_CODE", "market_code already registered")
    for existing in db.teams.values():
        if existing["waiver_priority_rank"] == priority:
            fail("ERR_DUPLICATE_WAIVER_PRIORITY", "waiver_priority_rank already taken")
    record = base_record()
    record.update({
        "name": name,
        "market_code": market_code,
        "salary_cap_limit_cents": salary_cap,
        "waiver_priority_rank": priority,
        "active_roster_limit": active_limit,
        "reserve_roster_limit": reserve_limit,
        "injured_reserve_limit": ir_limit,
        "practice_squad_limit": ps_limit,
        "active_roster_count": 0,
        "reserve_roster_count": 0,
        "injured_reserve_count": 0,
        "practice_squad_count": 0,
        "provisional_cap_committed_cents": 0,
        "final_cap_committed_cents": 0,
        "dead_money_cents": 0,
        "cap_space_cents": salary_cap,
        "open_medical_review_count": 0,
        "compliance_status": "COMPLIANT",
        "grace_expires_at": None,
        "consecutive_noncompliant_checks": 0,
    })
    db.teams[record["id"]] = record
    return single(views.team(record), 201)


@bp.route("/teams/<team_id>", methods=["GET"])
@endpoint(*ALL_ROLES)
def read_team(actor, team_id):
    team = domain.get_team(team_id)
    domain.recompute_team(team)
    return single(views.team(team))


@bp.route("/teams", methods=["GET"])
@endpoint(*ALL_ROLES)
def list_teams(actor):
    records = values(db.teams)
    for team in records:
        domain.recompute_team(team)
    records = filter_records(records, {"compliance_status": "compliance_status"})
    return paginate(records, views.team)


@bp.route("/teams/<team_id>/limits", methods=["PATCH"])
@endpoint(LEAGUE_OFFICER)
def patch_limits(actor, team_id):
    team = domain.get_team(team_id)
    body = shape.body()
    active_limit = shape.opt_int(body, "active_roster_limit", None, minimum=1)
    reserve_limit = shape.opt_int(body, "reserve_roster_limit", None, minimum=0)
    ir_limit = shape.opt_int(body, "injured_reserve_limit", None, minimum=0)
    ps_limit = shape.opt_int(body, "practice_squad_limit", None, minimum=0)
    salary_cap = shape.opt_int(body, "salary_cap_limit_cents", None, minimum=0)
    priority = shape.opt_int(body, "waiver_priority_rank", None, minimum=1)
    if priority is not None:
        for existing in db.teams.values():
            if existing["id"] == team["id"]:
                continue
            if existing["waiver_priority_rank"] == priority:
                fail("ERR_DUPLICATE_WAIVER_PRIORITY", "waiver_priority_rank already taken")
    if active_limit is not None:
        team["active_roster_limit"] = active_limit
    if reserve_limit is not None:
        team["reserve_roster_limit"] = reserve_limit
    if ir_limit is not None:
        team["injured_reserve_limit"] = ir_limit
    if ps_limit is not None:
        team["practice_squad_limit"] = ps_limit
    if salary_cap is not None:
        team["salary_cap_limit_cents"] = salary_cap
    if priority is not None:
        team["waiver_priority_rank"] = priority
    # Applies immediately even when it leaves the club over a limit.
    domain.recompute_team(team, event=True)
    touch(team)
    return single(views.team(team))


@bp.route("/teams/<team_id>/cap-ledger", methods=["GET"])
@endpoint(LEAGUE_OFFICER, TEAM_CAP_ANALYST)
def cap_ledger(actor, team_id):
    team = domain.get_team(team_id)
    # Read-only: recomputes both variants; Team.version is NOT incremented.
    domain.recompute_team(team)
    return single(views.team(team))


@bp.route("/teams/<team_id>/compliance-checks", methods=["GET"])
@endpoint(LEAGUE_OFFICER, TEAM_CAP_ANALYST)
def team_compliance_checks(actor, team_id):
    limit, offset = page_params()
    team = domain.get_team(team_id)
    records = values(db.compliance_checks, lambda c: c["team_id"] == team["id"])
    # Club sweep history reads newest first by checked_at.
    records.sort(key=lambda c: (c["checked_at"], c["_seq"]), reverse=True)
    total = len(records)
    window = records[offset:offset + limit]
    return collection(
        [views.compliance_check(item) for item in window], total, limit, offset
    )
