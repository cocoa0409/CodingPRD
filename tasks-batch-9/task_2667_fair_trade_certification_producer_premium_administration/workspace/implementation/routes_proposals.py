"""Premium use proposals, ballots and the tally fork."""
from decimal import Decimal

from flask import Blueprint

import calc
import common as C
import domain as D
import store as S
import validators as V
from common import dec, new_id, now_iso, parse_date_str, pct
from errors import ApiError
from response import created, listing, ok
from store import ordered, touch_once

bp = Blueprint("proposals", __name__)


def _committee_of(proposal):
    return S.committees[proposal["committee_id"]]


def _fund_of(committee):
    return S.fund_of(committee["holder_id"])


def _chair_binding(user_id, committee):
    if user_id != committee["chair_user_id"]:
        raise ApiError("ERR_HOLDER_OWNERSHIP_MISMATCH",
                       "X-User-ID is not this committee's chair")


def _counted_ballots(proposal):
    return ordered([v for v in S.votes.values()
                    if v["proposal_id"] == proposal["id"]
                    and v["round_number"] == proposal["current_round"]])


def _restamp_tally(proposal, committee):
    tally = calc.proposal_vote_tally(_counted_ballots(proposal),
                                    committee["member_count"])
    proposal["turnout_pct"] = tally["turnout_pct"]
    proposal["approval_pct"] = tally["approval_pct"]
    return tally


@bp.post("/premium-use-proposals")
def draft_proposal():
    from auth import authorize
    user_id, role = authorize("CommitteeChair")
    data = V.body()
    committee_id = V.req_id(data, "committee_id")
    title = V.req_str(data, "title", 200)
    use_category = V.req_enum(data, "use_category", C.USE_CATEGORIES)
    requested_amount_cents = V.req_int(data, "requested_amount_cents", minimum=1)
    use_period_start = V.req_date(data, "use_period_start")
    use_period_end = V.req_date(data, "use_period_end")
    expected_fund_version = V.req_int(data, "expected_fund_version")
    if not use_period_end > use_period_start:
        V.fail("use_period_end must fall strictly after use_period_start")

    committee = S.committee_or_404(committee_id)
    _chair_binding(user_id, committee)
    fund = _fund_of(committee)
    if fund is None or expected_fund_version != fund["version"]:
        raise ApiError("ERR_STALE_FUND_VERSION",
                       "expected_fund_version does not match the fund's version")

    holder = S.holders[committee["holder_id"]]
    if holder["certificate_status"] in ("SUSPENDED", "TRANSITIONING", "DECERTIFIED"):
        raise ApiError("ERR_PREMIUM_USE_BLOCKED_BY_SUSPENSION",
                       "holder is %s" % holder["certificate_status"])
    if use_category not in committee["approved_use_categories"]:
        raise ApiError("ERR_USE_CATEGORY_NOT_APPROVED",
                       "%s is not an approved use category" % use_category)
    if fund["balance_cents"] < requested_amount_cents:
        raise ApiError("ERR_FUND_BALANCE_INSUFFICIENT",
                       "balance_cents %d is below the requested amount"
                       % fund["balance_cents"])

    proposal = {
        "id": new_id(),
        "committee_id": committee_id,
        "title": title,
        "use_category": use_category,
        "requested_amount_cents": requested_amount_cents,
        "use_period_start": use_period_start.isoformat(),
        "use_period_end": use_period_end.isoformat(),
        "status": "DRAFT",
        "current_round": 0,
        "turnout_pct": pct(0),
        "approval_pct": pct(0),
        "approved_at": None,
        "disbursed_at": None,
        "cancelled_at": None,
    }
    S.stamp_new(proposal)
    S.proposals[proposal["id"]] = proposal
    D.adjust_proposal_counters(committee, fund, 1, 1)
    return created(proposal)


@bp.post("/premium-use-proposals/<proposal_id>/open-vote")
def open_vote(proposal_id):
    from auth import authorize
    user_id, role = authorize("CommitteeChair")
    V.body()
    proposal = S.proposal_or_404(proposal_id)
    committee = _committee_of(proposal)
    _chair_binding(user_id, committee)
    if proposal["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "proposal status is %s" % proposal["status"])
    holder = S.holders[committee["holder_id"]]
    if holder["certificate_status"] not in ("CERTIFIED", "TRANSITIONING"):
        raise ApiError("ERR_HOLDER_NOT_CERTIFIED",
                       "holder is %s" % holder["certificate_status"])
    if committee["status"] != "ACTIVE":
        raise ApiError("ERR_COMMITTEE_NOT_ACTIVE",
                       "committee is %s" % committee["status"])

    proposal["status"] = "UNDER_VOTE"
    proposal["current_round"] = proposal["current_round"] + 1
    touch_once(proposal)
    return ok(proposal)


@bp.post("/premium-use-proposals/<proposal_id>/votes")
def cast_ballot(proposal_id):
    from auth import authorize
    user_id, role = authorize("CommitteeMember")
    data = V.body()
    ballot = V.req_enum(data, "ballot", C.BALLOTS)
    rationale = V.opt_str(data, "rationale", 1000)
    proposal = S.proposal_or_404(proposal_id)
    committee = _committee_of(proposal)
    if proposal["status"] != "UNDER_VOTE":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "proposal status is %s" % proposal["status"])
    for existing in S.votes.values():
        if (existing["proposal_id"] == proposal["id"]
                and existing["voter_user_id"] == user_id
                and existing["round_number"] == proposal["current_round"]):
            raise ApiError("ERR_DUPLICATE_VOTE",
                           "this member already voted in round %d"
                           % proposal["current_round"])

    vote = {
        "id": new_id(),
        "proposal_id": proposal["id"],
        "voter_user_id": user_id,
        "ballot": ballot,
        "round_number": proposal["current_round"],
        "rationale": rationale,
    }
    S.stamp_event(vote)
    vote["cast_at"] = vote["created_at"]
    S.votes[vote["id"]] = vote

    _restamp_tally(proposal, committee)
    touch_once(proposal)
    return created(vote)


def _window_capacity_ok(proposal, committee, fund):
    """80 percent ceiling over the overlapping APPROVED window set (PRD 3.5)."""
    start = parse_date_str(proposal["use_period_start"])
    end = parse_date_str(proposal["use_period_end"])
    total = dec(proposal["requested_amount_cents"])
    for other in ordered(list(S.proposals.values())):
        if other["id"] == proposal["id"]:
            continue
        if other["committee_id"] != committee["id"]:
            continue
        if other["status"] != "APPROVED":
            continue
        other_start = parse_date_str(other["use_period_start"])
        other_end = parse_date_str(other["use_period_end"])
        if start < other_end and other_start < end:
            total += dec(other["requested_amount_cents"])
    ceiling = dec(fund["total_accrued_cents"]) * C.FUND_WINDOW_CAPACITY_PCT / dec(100)
    return total <= ceiling


@bp.post("/premium-use-proposals/<proposal_id>/close-vote")
def close_vote(proposal_id):
    from auth import authorize
    user_id, role = authorize("CommitteeChair")
    V.body()
    proposal = S.proposal_or_404(proposal_id)
    committee = _committee_of(proposal)
    _chair_binding(user_id, committee)
    for vote in _counted_ballots(proposal):
        if vote["voter_user_id"] == user_id:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                           "the closing chair voted in this round")
    if proposal["status"] != "UNDER_VOTE":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "proposal status is %s" % proposal["status"])

    fund = _fund_of(committee)
    tally = calc.proposal_vote_tally(_counted_ballots(proposal),
                                     committee["member_count"])
    outcome = calc.tally_outcome(tally["turnout_pct"], tally["approval_pct"],
                                 committee["quorum_pct"])
    amount = proposal["requested_amount_cents"]

    if outcome == "APPROVED":
        if fund is None or not _window_capacity_ok(proposal, committee, fund):
            raise ApiError("ERR_FUND_PERIOD_CAPACITY_EXCEEDED",
                           "the overlapping approved window set exceeds the ceiling")
        if fund["balance_cents"] < amount:
            raise ApiError("ERR_FUND_BALANCE_INSUFFICIENT",
                           "balance_cents %d is below the requested amount"
                           % fund["balance_cents"])

    proposal["turnout_pct"] = tally["turnout_pct"]
    proposal["approval_pct"] = tally["approval_pct"]

    if outcome == "APPROVED":
        proposal["status"] = "APPROVED"
        proposal["approved_at"] = now_iso()
        touch_once(proposal)
        D.write_entry(fund, "COMMITMENT", amount,
                      "commitment for approved proposal %s" % proposal["id"],
                      proposal_id=proposal["id"])
        D.adjust_proposal_counters(committee, fund, -1, -1)
        D.committee_on_balance_fall(committee, fund)
    elif outcome == "REJECTED":
        proposal["status"] = "REJECTED"
        touch_once(proposal)
        D.adjust_proposal_counters(committee, fund, -1, -1)
    else:
        proposal["status"] = "REVISION_REQUESTED"
        proposal["current_round"] = proposal["current_round"] + 1
        touch_once(proposal)
    return ok(proposal)


@bp.post("/premium-use-proposals/<proposal_id>/revise")
def revise_proposal(proposal_id):
    from auth import authorize
    user_id, role = authorize("CommitteeChair")
    data = V.body()
    title = V.req_str(data, "title", 200)
    use_category = V.req_enum(data, "use_category", C.USE_CATEGORIES)
    requested_amount_cents = V.req_int(data, "requested_amount_cents", minimum=1)
    proposal = S.proposal_or_404(proposal_id)
    committee = _committee_of(proposal)
    _chair_binding(user_id, committee)
    if proposal["status"] != "REVISION_REQUESTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "proposal status is %s" % proposal["status"])
    if use_category not in committee["approved_use_categories"]:
        raise ApiError("ERR_USE_CATEGORY_NOT_APPROVED",
                       "%s is not an approved use category" % use_category)

    proposal["status"] = "DRAFT"
    proposal["title"] = title
    proposal["use_category"] = use_category
    proposal["requested_amount_cents"] = requested_amount_cents
    proposal["turnout_pct"] = None
    proposal["approval_pct"] = None
    touch_once(proposal)
    return ok(proposal)


@bp.post("/premium-use-proposals/<proposal_id>/disburse")
def disburse_proposal(proposal_id):
    from auth import authorize
    authorize("CertificationOfficer")
    V.body()
    proposal = S.proposal_or_404(proposal_id)
    committee = _committee_of(proposal)
    if proposal["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "proposal status is %s" % proposal["status"])
    holder = S.holders[committee["holder_id"]]
    if holder["certificate_status"] == "SUSPENDED":
        raise ApiError("ERR_PREMIUM_USE_BLOCKED_BY_SUSPENSION",
                       "holder is SUSPENDED")
    fund = _fund_of(committee)
    amount = proposal["requested_amount_cents"]
    if fund is None or fund["committed_cents"] < amount:
        raise ApiError("ERR_FUND_BALANCE_INSUFFICIENT",
                       "committed_cents is below the requested amount")

    proposal["status"] = "DISBURSED"
    proposal["disbursed_at"] = now_iso()
    touch_once(proposal)
    D.write_entry(fund, "DISBURSEMENT", amount,
                  "disbursement of proposal %s" % proposal["id"],
                  proposal_id=proposal["id"])
    D.committee_on_balance_rise(committee, fund)
    return ok(proposal)


@bp.post("/premium-use-proposals/<proposal_id>/cancel")
def cancel_proposal(proposal_id):
    from auth import authorize
    user_id, role = authorize("CommitteeChair")
    data = V.body()
    V.opt_str(data, "reason", 1000)
    proposal = S.proposal_or_404(proposal_id)
    committee = _committee_of(proposal)
    _chair_binding(user_id, committee)
    previous = proposal["status"]
    if previous not in ("DRAFT", "REVISION_REQUESTED", "APPROVED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "proposal status is %s" % previous)
    fund = _fund_of(committee)

    proposal["status"] = "CANCELLED"
    proposal["cancelled_at"] = now_iso()
    touch_once(proposal)

    if previous == "APPROVED":
        if fund is not None:
            D.write_entry(fund, "RELEASE", proposal["requested_amount_cents"],
                          "release of cancelled proposal %s" % proposal["id"],
                          proposal_id=proposal["id"])
            D.committee_on_balance_rise(committee, fund)
    else:
        D.adjust_proposal_counters(committee, fund, -1, -1)
    return ok(proposal)


@bp.get("/premium-use-proposals/<proposal_id>")
def read_proposal(proposal_id):
    from auth import authorize
    authorize("CertificationOfficer", "Auditor", "CommitteeChair",
              "CommitteeMember", "ProducerRepresentative")
    return ok(S.proposal_or_404(proposal_id))


@bp.get("/premium-committees/<committee_id>/premium-use-proposals")
def list_committee_proposals(committee_id):
    from auth import authorize
    authorize("CertificationOfficer", "Auditor", "CommitteeChair",
              "CommitteeMember", "ProducerRepresentative")
    status = V.enum_filter("status", C.PROPOSAL_STATUSES)
    use_category = V.enum_filter("use_category", C.USE_CATEGORIES)
    S.committee_or_404(committee_id)
    rows = ordered([p for p in S.proposals.values()
                    if p["committee_id"] == committee_id])
    if status:
        rows = [r for r in rows if r["status"] == status]
    if use_category:
        rows = [r for r in rows if r["use_category"] == use_category]
    page, limit, offset, total = V.paginate(rows)
    return listing(page, limit, offset, total)


@bp.get("/premium-use-proposals/<proposal_id>/votes")
def list_votes(proposal_id):
    from auth import authorize
    authorize("CertificationOfficer", "Auditor", "CommitteeChair",
              "CommitteeMember")
    round_number = V.int_filter("round_number")
    ballot = V.enum_filter("ballot", C.BALLOTS)
    S.proposal_or_404(proposal_id)
    rows = ordered([v for v in S.votes.values() if v["proposal_id"] == proposal_id])
    if round_number is not None:
        rows = [r for r in rows if r["round_number"] == round_number]
    if ballot:
        rows = [r for r in rows if r["ballot"] == ballot]
    page, limit, offset, total = V.paginate(rows)
    return listing(page, limit, offset, total)
