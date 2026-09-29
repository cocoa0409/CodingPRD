"""Withdrawal requests, ballots and execution."""

from datetime import timedelta

from flask import Blueprint, g

from db import db, make_record, now_dt, now_iso, ordered, touch
from errors import fail
from middleware import authorize, body, req_date, req_enum, req_int, validation
from response import object_response
from routes.helpers import cycle_or_404, fund_or_404, listing, request_or_404, vote_or_404
from services import calc, cascade
from util import fmt_dt, parse_date_str, parse_dt

bp = Blueprint("withdrawals", __name__)

ROLES = ("ForecastDirector", "ReserveTreasurer", "LegislativeVoter", "RatingAnalyst")
JUSTIFICATIONS = ("SHORTFALL_TRIGGER", "SUPERMAJORITY_VOTE")
VOTES = ("YES", "NO", "ABSTAIN")


# ------------------------------------------------------------------ reads ----
@bp.get("/withdrawal-requests")
@authorize(*ROLES)
def list_requests():
    return listing(
        ordered(db.requests),
        {
            "fund_id": ("fund_id", str),
            "cycle_id": ("cycle_id", str),
            "status": ("status", str),
            "justification_type": ("justification_type", str),
            "executed_transaction_id": ("executed_transaction_id", str),
        },
    )


@bp.get("/withdrawal-requests/<request_id>")
@authorize(*ROLES)
def get_request(request_id):
    return object_response(request_or_404(request_id))


@bp.get("/withdrawal-requests/<request_id>/votes")
@authorize(*ROLES)
def list_request_votes(request_id):
    req = request_or_404(request_id)
    return listing(calc.votes_of(req["id"]), {"vote": ("vote", str)})


@bp.get("/withdrawal-votes/<vote_id>")
@authorize(*ROLES)
def get_vote(vote_id):
    return object_response(vote_or_404(vote_id))


# ----------------------------------------------------------------- writes ----
@bp.post("/withdrawal-requests")
@authorize("ReserveTreasurer", "ForecastDirector")
def create_request():
    data = body()

    fund = None
    cycle = None
    if data.get("fund_id") is not None:
        if not isinstance(data["fund_id"], str):
            validation("fund_id must be a string")
        fund = fund_or_404(data["fund_id"])
    if data.get("cycle_id") is not None:
        if not isinstance(data["cycle_id"], str):
            validation("cycle_id must be a string")
        cycle = cycle_or_404(data["cycle_id"])
    if fund is None:
        validation("fund_id is required")
    if cycle is None:
        validation("cycle_id is required")

    amount = req_int(data, "requested_amount_cents", minimum=1)
    justification = req_enum(data, "justification_type", JUSTIFICATIONS)
    deadline = req_date(data, "deadline_date")
    expected = req_int(data, "expected_fund_version", minimum=0)

    if expected != fund["version"]:
        fail("ERR_STALE_FUND_VERSION",
             "expected_fund_version %d does not match the fund's current version %d"
             % (expected, fund["version"]))
    if cycle["status"] != "CERTIFIED":
        fail("ERR_CYCLE_NOT_CERTIFIED", "a withdrawal must be justified by a CERTIFIED cycle")

    for other in ordered(db.requests):
        if other["fund_id"] == fund["id"] and other["status"] == "DRAFT":
            other["status"] = "REJECTED"
            other["authorized_amount_cents"] = 0
            touch(other)

    rec = make_record(
        {
            "fund_id": fund["id"],
            "cycle_id": cycle["id"],
            "requested_amount_cents": amount,
            "justification_type": justification,
            "requested_by_user_id": g.user_id,
            "deadline_date": deadline,
            "status": "DRAFT",
            "approval_basis": None,
            "votes_required": 0,
            "quorum_required": 0,
            "yes_votes": 0,
            "no_votes": 0,
            "abstain_votes": 0,
            "vote_closes_at": None,
            "authorized_amount_cents": 0,
            "executed_transaction_id": None,
            "executed_at": None,
        }
    )
    db.requests[rec["id"]] = rec
    touch(fund)
    return object_response(rec, 201)


@bp.post("/withdrawal-requests/<request_id>/verify-shortfall")
@authorize("ReserveTreasurer")
def verify_shortfall(request_id):
    req = request_or_404(request_id)
    if req["status"] != "DRAFT":
        fail("ERR_REQUEST_NOT_DRAFT", "only a DRAFT request may be approved")
    if req["justification_type"] != "SHORTFALL_TRIGGER":
        fail("ERR_JUSTIFICATION_MISMATCH",
             "this request declared %s" % req["justification_type"])

    cycle = db.cycles.get(req["cycle_id"])
    pct = cycle.get("shortfall_pct_bps") if cycle else None
    if pct is None or pct < calc.SHORTFALL_TRIGGER_BPS:
        fail("ERR_SHORTFALL_NOT_TRIGGERED",
             "the certified shortfall does not reach %d bps" % calc.SHORTFALL_TRIGGER_BPS)
    if cycle["status"] != "CERTIFIED":
        fail("ERR_CYCLE_NOT_CERTIFIED", "the justifying cycle is not CERTIFIED")

    req["status"] = "APPROVED"
    req["approval_basis"] = "SHORTFALL_TRIGGER"
    req["authorized_amount_cents"] = min(req["requested_amount_cents"],
                                         cycle["shortfall_gap_cents"])
    touch(req)
    return object_response(req)


@bp.post("/withdrawal-requests/<request_id>/open-vote")
@authorize("ForecastDirector")
def open_vote(request_id):
    req = request_or_404(request_id)
    if req["status"] != "DRAFT":
        fail("ERR_REQUEST_NOT_DRAFT", "only a DRAFT request may open a ballot")
    if req["justification_type"] != "SUPERMAJORITY_VOTE":
        fail("ERR_JUSTIFICATION_MISMATCH",
             "this request declared %s" % req["justification_type"])

    fund = db.funds.get(req["fund_id"])
    req["status"] = "VOTE_OPEN"
    req["votes_required"] = calc.votes_required_for(fund["eligible_seats"])
    req["quorum_required"] = calc.quorum_required_for(fund["eligible_seats"])
    req["vote_closes_at"] = fmt_dt(now_dt() + timedelta(days=calc.VOTE_WINDOW_DAYS))
    touch(req)
    return object_response(req)


@bp.post("/withdrawal-requests/<request_id>/votes")
@authorize("LegislativeVoter")
def cast_vote(request_id):
    req = request_or_404(request_id)
    data = body()
    choice = req_enum(data, "vote", VOTES)

    if req["status"] != "VOTE_OPEN":
        fail("ERR_VOTE_NOT_OPEN", "the ballot is not open")
    for existing in calc.votes_of(req["id"]):
        if existing["voter_user_id"] == g.user_id:
            fail("ERR_DUPLICATE_VOTE", "this voter has already cast a ballot")

    rec = make_record(
        {
            "request_id": req["id"],
            "voter_user_id": g.user_id,
            "vote": choice,
            "cast_at": now_iso(),
        },
        versioned=False,
    )
    db.votes[rec["id"]] = rec
    key = {"YES": "yes_votes", "NO": "no_votes", "ABSTAIN": "abstain_votes"}[choice]
    req[key] = req[key] + 1
    touch(req)
    return object_response(rec, 201)


@bp.post("/withdrawal-requests/<request_id>/close-vote")
@authorize("ForecastDirector")
def close_vote(request_id):
    req = request_or_404(request_id)
    if req["status"] != "VOTE_OPEN":
        fail("ERR_VOTE_NOT_OPEN", "the ballot is not open")

    fund = db.funds.get(req["fund_id"])
    cast = req["yes_votes"] + req["no_votes"] + req["abstain_votes"]
    closes_at = parse_dt(req["vote_closes_at"]) if req.get("vote_closes_at") else None
    reached = closes_at is not None and now_dt() >= closes_at
    if not reached and cast != fund["eligible_seats"]:
        fail("ERR_VOTE_STILL_OPEN", "the ballot has neither run its course nor filled every seat")
    if cast < req["quorum_required"]:
        fail("ERR_QUORUM_NOT_MET",
             "%d ballots cast, %d required for quorum" % (cast, req["quorum_required"]))
    if req["yes_votes"] < req["votes_required"]:
        fail("ERR_SUPERMAJORITY_NOT_MET",
             "%d yes votes, %d required" % (req["yes_votes"], req["votes_required"]))

    req["status"] = "APPROVED"
    req["approval_basis"] = "SUPERMAJORITY_VOTE"
    req["authorized_amount_cents"] = min(req["requested_amount_cents"],
                                         calc.cap_headroom_cents(fund))
    touch(req)
    return object_response(req)


@bp.post("/withdrawal-requests/<request_id>/execute")
@authorize("ReserveTreasurer")
def execute_request(request_id):
    req = request_or_404(request_id)
    if req["status"] not in ("APPROVED", "LAPSED"):
        fail("ERR_REQUEST_NOT_APPROVED", "only an APPROVED request may be executed")
    if req["status"] == "LAPSED" or now_dt().date() > parse_date_str(req["deadline_date"]):
        fail("ERR_AUTHORIZATION_LAPSED", "the authorization has lapsed")

    fund = db.funds.get(req["fund_id"])
    if fund["cooling_off_until"] is not None and now_dt() <= parse_dt(fund["cooling_off_until"]):
        fail("ERR_COOLING_OFF_ACTIVE", "the fund is inside its cooling-off window")
    if req["requested_by_user_id"] == g.user_id:
        fail("ERR_EXECUTOR_IS_REQUESTER", "the executor may not be the requester")

    amount = req["authorized_amount_cents"] or 0
    cap = calc.annual_withdrawal_cap_cents(fund)
    if fund["fy_withdrawn_cents"] + amount > cap:
        fail("ERR_ANNUAL_CAP_EXCEEDED",
             "the fiscal-year withdrawal cap of %d would be exceeded" % cap)
    if amount > fund["balance_cents"]:
        fail("ERR_INSUFFICIENT_RESERVE_BALANCE", "the fund balance is insufficient")

    cascade.execute_cascade(req, fund)
    return object_response(req)
