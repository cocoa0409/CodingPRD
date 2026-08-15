"""CapitalProject transitions and majority-in-interest voting."""
from flask import Blueprint

import errors
import helpers
import services
from db import store
from helpers import (authenticate, get_path, json_body, paginate, resolve_fk,
                     req_string, req_enum, require_ownership, READ_ROLES, BALLOTS)
from response import success_object, success_list
from services import (ser_capital_project, ser_mii_vote, touch, stamp, now_dt,
                      check_fy_open_guard, snapshot_mii_weights,
                      recompute_mii_tally, mii_denominators)
from util import new_id

bp = Blueprint("capital_projects", __name__)


def _get_project(project_id):
    return get_path(store.capital_projects, project_id, "CapitalProject")


@bp.get("/airport/capital_projects/<project_id>")
def get_capital_project(project_id):
    authenticate(READ_ROLES)
    project = _get_project(project_id)
    return success_object(ser_capital_project(project))


@bp.post("/airport/capital_projects/<project_id>/open-voting")
def open_voting(project_id):
    authenticate(("AirportFinance",))
    project = _get_project(project_id)
    if project["status"] != "PROPOSED":
        raise errors.invalid_state("Only a PROPOSED project can open for voting")
    fy = store.fiscal_years[project["fiscal_year_id"]]
    if fy["status"] == "DRAFT":
        raise errors.invalid_state("The parent fiscal year must be OPEN")
    check_fy_open_guard(fy)
    project["status"] = "MII_VOTING"
    project["votes_for_count"] = 0
    project["votes_for_weight_kg"] = 0
    project["votes_against_weight_kg"] = 0
    touch(project)
    # freeze each eligible signatory carrier's voting weight from rolling
    # twelve-month activity
    snapshot_mii_weights(fy["id"])
    return success_object(ser_capital_project(project))


@bp.post("/airport/capital_projects/<project_id>/close-voting")
def close_voting(project_id):
    authenticate(("AirportFinance",))
    project = _get_project(project_id)
    if project["status"] != "MII_VOTING":
        raise errors.invalid_state("Only a project in MII_VOTING can be closed")
    fy = store.fiscal_years[project["fiscal_year_id"]]
    check_fy_open_guard(fy)
    project["status"] = "REJECTED"
    touch(project)
    return success_object(ser_capital_project(project))


@bp.post("/airport/capital_projects/<project_id>/cancel")
def cancel_project(project_id):
    authenticate(("AirportFinance",))
    project = _get_project(project_id)
    if project["status"] != "PROPOSED":
        raise errors.invalid_state("Only a PROPOSED project can be cancelled")
    fy = store.fiscal_years[project["fiscal_year_id"]]
    check_fy_open_guard(fy)
    project["status"] = "CANCELLED"
    touch(project)
    return success_object(ser_capital_project(project))


@bp.post("/airport/capital_projects/<project_id>/mii_votes")
def cast_vote(project_id):
    uid, _ = authenticate(("SignatoryAirline",))
    project = _get_project(project_id)
    body = json_body()
    airline = resolve_fk(body, "airline_id", store.airlines)  # priority 4
    airline_id = req_string(body, "airline_id")               # priority 5
    ballot = req_enum(body, "ballot", BALLOTS)
    require_ownership(uid, airline_id)
    fy = store.fiscal_years[project["fiscal_year_id"]]
    # priority 6: state — a PROPOSED project has not opened for voting, so the
    # transition is not admitted (ERR_INVALID_STATE). The four decided states
    # are reported at the business-rule stage as ERR_PROJECT_ALREADY_DECIDED,
    # after eligibility and uniqueness, per the §3.4 ordering.
    if project["status"] == "PROPOSED":
        raise errors.invalid_state("The project has not opened for voting")
    check_fy_open_guard(fy)  # priority 9
    # priority 11: eligibility — active + SIGNATORY agreement on this year
    ag = services.active_agreement(fy["id"], airline_id)
    if ag is None or ag["signature_status"] != "SIGNATORY":
        raise errors.not_signatory()
    # priority 12: one ballot per carrier per project (reported before a
    # decided project, per §3.4 ordering)
    for v in store.mii_votes.values():
        if v["capital_project_id"] == project["id"] and v["airline_id"] == airline_id:
            raise errors.duplicate_vote()
    # priority 13: ballot box sealed once decided
    if project["status"] != "MII_VOTING":
        raise errors.project_already_decided()
    ts = stamp()
    vote = {
        "id": new_id(),
        "capital_project_id": project["id"],
        "airline_id": airline["id"],
        "ballot": ballot,
        "cast_at": ts,
        "created_at": ts,
        "_created_dt": now_dt(),
        "_seq": next(store.seq),
    }
    store.mii_votes[vote["id"]] = vote
    # mii_tally: recompute and auto-decide on insert (one modification event)
    changed, for_count, for_weight, against_weight = recompute_mii_tally(project)
    total_count, total_weight = mii_denominators(fy["id"])
    thr = project["mii_threshold_pct"]
    if (for_count * 100 >= thr * total_count
            and for_weight * 100 >= thr * total_weight):
        project["status"] = "APPROVED"
        touch(project)
    elif against_weight * 100 > (100 - thr) * total_weight:
        project["status"] = "VETOED"
        touch(project)
    elif changed:
        touch(project)
    return success_object(ser_mii_vote(vote), status=201)


@bp.get("/airport/capital_projects/<project_id>/mii_votes")
def list_votes(project_id):
    authenticate(READ_ROLES)
    project = _get_project(project_id)
    items = [v for v in store.mii_votes.values() if v["capital_project_id"] == project["id"]]
    ballot = helpers.request.args.get("ballot")
    if ballot is not None:
        items = [v for v in items if v["ballot"] == ballot]
    data, meta = paginate(items, ser_mii_vote)
    return success_list(data, meta)


@bp.get("/airport/mii_votes/<vote_id>")
def get_vote(vote_id):
    authenticate(READ_ROLES)
    vote = get_path(store.mii_votes, vote_id, "MIIVote")
    return success_object(ser_mii_vote(vote))
