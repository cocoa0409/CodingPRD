"""Credit submissions, provisional shares and guild arbitration (PRD 3.9)."""
from flask import Blueprint

from db import base_row, db, touch
from errors import ApiError
from middleware import (GUILD_ADMINISTRATOR, SHOWRUNNER, STUDIO_EXECUTIVE, WRITER,
                        fetch, require)
from response import created, ok
from routes.common import list_out, match, out
from services import calc, domain
from validation import (body_json, filter_value, is_int, raw, v_bool, v_id_list,
                        v_enum, v_int)

bp = Blueprint("credits", __name__)

READ_ROLES = (GUILD_ADMINISTRATOR, SHOWRUNNER, STUDIO_EXECUTIVE, WRITER)


def _threshold(episode):
    season = domain.season_of_episode(episode)
    return domain.agreement_of(season)


@bp.post("/episodes/<episode_id>/credit-submissions")
def submit_claim(episode_id):
    actor = require(WRITER)
    episode = fetch(db.episodes, episode_id, "ERR_EPISODE_NOT_FOUND")
    body = body_json()
    writer_ref = raw(body, "writer_id")
    writer = None
    if writer_ref is not None:
        writer = fetch(db.writers, writer_ref, "ERR_WRITER_NOT_FOUND")
    row = base_row()
    if writer is None:
        raise ApiError("ERR_INVALID_REQUEST")
    row["claim_basis"] = v_enum(body, "claim_basis", calc.CLAIM_BASES)
    row["claimed_contribution_pct"] = v_int(body, "claimed_contribution_pct", lo=1, hi=100)
    # 11. ownership
    if writer["id"] != actor.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    # 14. state
    if episode["credit_status"] != "SUBMISSIONS_OPEN":
        raise ApiError("ERR_SUBMISSION_WINDOW_CLOSED")
    # 18. structural uniqueness
    for existing in domain.submissions_of(episode["id"]):
        if existing["writer_id"] == writer["id"]:
            raise ApiError("ERR_DUPLICATE_SUBMISSION")
    row["episode_id"] = episode["id"]
    row["writer_id"] = writer["id"]
    row["status"] = "SUBMITTED"
    row["provisional_share_pct"] = 0
    row["arbitrated_share_pct"] = None
    row["receives_credit"] = False
    db.submissions[row["id"]] = row
    touch(episode)
    return created(out(row))


@bp.post("/episodes/<episode_id>/credit-submissions/close")
def close_submissions(episode_id):
    actor = require(SHOWRUNNER, GUILD_ADMINISTRATOR)
    episode = fetch(db.episodes, episode_id, "ERR_EPISODE_NOT_FOUND")
    season = domain.season_of_episode(episode)
    agreement = domain.agreement_of(season)
    # 12. season showrunner scope
    if actor.role == SHOWRUNNER and season["showrunner_writer_id"] != actor.user_id:
        raise ApiError("ERR_NOT_SEASON_SHOWRUNNER")
    if episode["credit_status"] != "SUBMISSIONS_OPEN":
        raise ApiError("ERR_SUBMISSION_WINDOW_CLOSED")
    submissions = domain.submissions_of(episode["id"])
    if not submissions:
        raise ApiError("ERR_NO_ELIGIBLE_SUBMISSIONS")
    eligible = [s for s in submissions
                if domain.writer_has_approved_assignment(episode["id"], s["writer_id"])]
    if not eligible:
        raise ApiError("ERR_NO_ELIGIBLE_SUBMISSIONS")
    shares = calc.normalize_shares(
        [(s["writer_id"], s["claimed_contribution_pct"], (s["created_at"], s["_seq"]))
         for s in eligible])
    threshold = agreement["credit_share_threshold_pct"]
    eligible_ids = {s["id"] for s in eligible}
    for sub in submissions:
        if sub["id"] in eligible_ids:
            sub["status"] = "ELIGIBLE"
            sub["provisional_share_pct"] = shares[sub["writer_id"]]
            sub["receives_credit"] = sub["provisional_share_pct"] >= threshold
        else:
            sub["status"] = "INELIGIBLE"
            sub["provisional_share_pct"] = 0
            sub["receives_credit"] = False
        touch(sub)
    episode["provisional_credit_shares"] = dict(shares)
    episode["credit_status"] = "SUBMISSIONS_CLOSED"
    touch(episode)
    return ok(out(episode))


@bp.post("/episodes/<episode_id>/credit-arbitration")
def convene_panel(episode_id):
    require(GUILD_ADMINISTRATOR)
    episode = fetch(db.episodes, episode_id, "ERR_EPISODE_NOT_FOUND")
    body = body_json()
    ids = raw(body, "arbiter_writer_ids")
    if isinstance(ids, list):
        for candidate in ids:
            if isinstance(candidate, str) and candidate:
                fetch(db.writers, candidate, "ERR_WRITER_NOT_FOUND")
    arbiters = v_id_list(body, "arbiter_writer_ids", size=3)
    # 14. state
    if episode["credit_status"] != "SUBMISSIONS_CLOSED":
        raise ApiError("ERR_ARBITRATION_NOT_AVAILABLE")
    for existing in db.arbitrations.values():
        if existing["episode_id"] == episode["id"]:
            raise ApiError("ERR_ARBITRATION_ALREADY_EXISTS")
    # 15. segregation of duties
    if len(set(arbiters)) != 3:
        raise ApiError("ERR_ARBITER_IS_PARTICIPANT")
    interested = set()
    for assignment in domain.assignments_of(episode["id"]):
        if assignment["status"] != "VOID":
            interested.add(assignment["writer_id"])
    for sub in domain.submissions_of(episode["id"]):
        interested.add(sub["writer_id"])
    for arbiter in arbiters:
        if arbiter in interested:
            raise ApiError("ERR_ARBITER_IS_PARTICIPANT")
    eligible = domain.eligible_submissions(episode["id"])
    if not eligible:
        raise ApiError("ERR_NO_ELIGIBLE_SUBMISSIONS")
    row = base_row()
    row["episode_id"] = episode["id"]
    row["arbiter_writer_ids"] = list(arbiters)
    row["participant_writer_ids"] = [s["writer_id"] for s in eligible]
    row["status"] = "STATEMENTS_OPEN"
    row["votes_cast_count"] = 0
    row["vote_ledger"] = {}
    row["leading_writer_id"] = None
    row["concurrence_pct"] = 0
    row["outcome"] = "NONE"
    row["determined_credit_string"] = None
    db.arbitrations[row["id"]] = row
    episode["credit_status"] = "IN_ARBITRATION"
    touch(episode)
    return created(out(row))


@bp.post("/credit-arbitrations/<arbitration_id>/votes")
def cast_ballot(arbitration_id):
    actor = require(WRITER)
    arbitration = fetch(db.arbitrations, arbitration_id, "ERR_ARBITRATION_NOT_FOUND")
    episode = db.episodes[arbitration["episode_id"]]
    season = domain.season_of_episode(episode)
    agreement = domain.agreement_of(season)
    body = body_json()
    shares = raw(body, "vote_shares")
    if not isinstance(shares, dict):
        raise ApiError("ERR_INVALID_REQUEST")
    # 10. vote share map structure
    participants = list(arbitration["participant_writer_ids"])
    if set(shares.keys()) != set(participants):
        raise ApiError("ERR_VOTE_SHARES_INVALID")
    total = 0
    for key in participants:
        value = shares[key]
        if not is_int(value):
            raise ApiError("ERR_VOTE_SHARES_INVALID")
        total += value
    if total != 100:
        raise ApiError("ERR_VOTE_SHARES_INVALID")
    # 11. panel membership
    if actor.user_id not in arbitration["arbiter_writer_ids"]:
        raise ApiError("ERR_ARBITER_NOT_ON_PANEL")
    # 14. state
    if arbitration["status"] not in ("STATEMENTS_OPEN", "PANEL_VOTING"):
        raise ApiError("ERR_ARBITRATION_CLOSED")
    if actor.user_id in arbitration["vote_ledger"]:
        raise ApiError("ERR_BALLOT_ALREADY_CAST")
    arbitration["vote_ledger"][actor.user_id] = {k: shares[k] for k in participants}
    arbitration["votes_cast_count"] += 1
    arbitration["status"] = "PANEL_VOTING"
    domain.recompute_panel(arbitration, agreement)
    touch(arbitration)
    return ok(out(arbitration))


def _finalize(arbitration, episode, agreement, eligible, shares, outcome):
    threshold = agreement["credit_share_threshold_pct"]
    for sub in eligible:
        share = shares.get(sub["writer_id"], 0)
        earned = share >= threshold
        if earned and not sub["receives_credit"]:
            writer = db.writers.get(sub["writer_id"])
            if writer is not None:
                writer["on_screen_credit_count"] += 1
        sub["receives_credit"] = earned
        touch(sub)
    string = domain.credit_string(eligible, shares)
    arbitration["outcome"] = outcome
    arbitration["determined_credit_string"] = string
    episode["determined_credit_string"] = string
    episode["credit_status"] = "DETERMINED"
    touch(arbitration)
    touch(episode)


@bp.post("/credit-arbitrations/<arbitration_id>/determine")
def determine(arbitration_id):
    require(GUILD_ADMINISTRATOR)
    arbitration = fetch(db.arbitrations, arbitration_id, "ERR_ARBITRATION_NOT_FOUND")
    episode = db.episodes[arbitration["episode_id"]]
    season = domain.season_of_episode(episode)
    agreement = domain.agreement_of(season)
    body = body_json()
    override = v_bool(body, "policy_override", required=False, default=False)
    if arbitration["status"] == "DETERMINED":
        raise ApiError("ERR_ARBITRATION_CLOSED")
    eligible = domain.eligible_submissions(episode["id"])
    if override:
        if arbitration["status"] != "DEADLOCKED":
            raise ApiError("ERR_POLICY_OVERRIDE_NOT_APPLICABLE")
        arbitration["status"] = "POLICY_REVIEW"
        shares = {}
        for sub in eligible:
            sub["arbitrated_share_pct"] = sub["provisional_share_pct"]
            shares[sub["writer_id"]] = sub["provisional_share_pct"]
        episode["final_credit_shares"] = dict(episode["provisional_credit_shares"])
        _finalize(arbitration, episode, agreement, eligible, shares,
                  "DEADLOCK_RESOLVED_BY_POLICY")
        return ok(out(arbitration))
    if arbitration["status"] == "DEADLOCKED":
        raise ApiError("ERR_POLICY_OVERRIDE_NOT_APPLICABLE")
    if arbitration["status"] == "POLICY_REVIEW":
        raise ApiError("ERR_ARBITRATION_CLOSED")
    if arbitration["votes_cast_count"] < 3:
        raise ApiError("ERR_PANEL_INCOMPLETE")
    if calc.D(arbitration["concurrence_pct"]) < calc.D(agreement["arbitration_concurrence_pct"]):
        arbitration["status"] = "DEADLOCKED"
        touch(arbitration)
        return ok(out(arbitration))
    keys = domain.submission_order_key(episode["id"])
    means = domain.panel_means(arbitration)
    shares = calc.normalize_shares(
        [(writer_id, means[writer_id], keys.get(writer_id, (0, 0)))
         for writer_id in arbitration["participant_writer_ids"]])
    arbitration["status"] = "DETERMINED"
    for sub in eligible:
        sub["arbitrated_share_pct"] = shares.get(sub["writer_id"], 0)
    episode["final_credit_shares"] = dict(shares)
    outcome = "UPHELD" if shares == episode["provisional_credit_shares"] else "REVISED"
    _finalize(arbitration, episode, agreement, eligible, shares, outcome)
    return ok(out(arbitration))


@bp.get("/credit-submissions/<submission_id>")
def get_submission(submission_id):
    require(*READ_ROLES)
    return ok(out(fetch(db.submissions, submission_id, "ERR_SUBMISSION_NOT_FOUND")))


@bp.get("/credit-submissions")
def list_submissions():
    require(*READ_ROLES)
    rows = list(db.submissions.values())
    rows = match(rows, "episode_id", filter_value("episode_id"))
    rows = match(rows, "writer_id", filter_value("writer_id"))
    rows = match(rows, "status", filter_value("status"))
    return list_out(rows)


@bp.get("/credit-arbitrations/<arbitration_id>")
def get_arbitration(arbitration_id):
    require(*READ_ROLES)
    return ok(out(fetch(db.arbitrations, arbitration_id, "ERR_ARBITRATION_NOT_FOUND")))


@bp.get("/credit-arbitrations")
def list_arbitrations():
    require(*READ_ROLES)
    rows = list(db.arbitrations.values())
    rows = match(rows, "episode_id", filter_value("episode_id"))
    rows = match(rows, "status", filter_value("status"))
    return list_out(rows)
