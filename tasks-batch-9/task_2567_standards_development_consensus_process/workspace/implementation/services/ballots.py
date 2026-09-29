"""Ballot derivation, evaluation and the close / adjudication cascades.

PRD 3.3 derives effective_ballot_kind and the frozen eligible voter set, PRD 3.5
evaluates a closed ballot in four ordered steps and re-reads it after every
adjudication. Ballot windows are half-open [opens_at, closes_at).
"""

from core.store import db, newest, now, now_iso, touch
from core.util import add_pct, day_span, gte, lt, min_pct, pct1, round1

from . import balance, gate, graph, ip

MIN_WINDOW_DAYS = {
    "SUBCOMMITTEE": 14,
    "RECIRCULATION": 14,
    "CONSENSUS_BODY": 30,
    "REAFFIRMATION": 30,
}

REQUIRED_RETURN_RATE = {
    "SUBCOMMITTEE": "50.0",
    "CONSENSUS_BODY": "66.7",
    "RECIRCULATION": "66.7",
    "REAFFIRMATION": "66.7",
}

BASE_APPROVAL = {
    "SUBCOMMITTEE": "50.1",
    "CONSENSUS_BODY": "66.7",
    "RECIRCULATION": "75.0",
    "REAFFIRMATION": "66.7",
}

CARRYOVER_ESCALATION = "5.0"
APPROVAL_CEILING = "90.0"
RECIRCULATION_RATIO_TRIGGER = "0.1000"

FAILED_RESULTS = ("FAILED_QUORUM", "FAILED_THRESHOLD")
ADJUDICABLE_PENDING = ("NOT_APPLICABLE", "PENDING")


# --- window helpers -----------------------------------------------------------

def overlaps(a_opens, a_closes, b_opens, b_closes):
    """Half-open overlap: each start strictly before the other's end. Adjacency
    (one window's closes_at exactly equal to the next window's opens_at) does not
    overlap."""
    return a_opens < b_closes and b_opens < a_closes


def occupied_slots(committee, opens_at, closes_at):
    """Ballots of the committee in OPEN or CLOSED whose window overlaps."""
    slots = []
    for ballot in graph.ballots_of_committee(committee):
        if ballot["status"] not in ("OPEN", "CLOSED"):
            continue
        if overlaps(opens_at, closes_at, ballot["_opens_at"], ballot["_closes_at"]):
            slots.append(ballot)
    return slots


def day_span_days(opens_at, closes_at):
    """The whole-day span of a candidate ballot window."""
    return day_span(opens_at, closes_at)


def in_voting_window(ballot, instant):
    return ballot["_opens_at"] <= instant < ballot["_closes_at"]


# --- effective kind and eligibility ------------------------------------------

def predecessor_ballot_of(draft):
    """The most recently created ballot on the predecessor draft whose status is
    EVALUATED or VACATED, taken in descending order of creation."""
    prior_id = draft.get("prior_draft_id")
    if prior_id is None:
        return None
    prior = db.drafts.get(prior_id)
    if prior is None:
        return None
    return newest([b for b in graph.ballots_of_draft(prior)
                   if b["status"] in ("EVALUATED", "VACATED")])


def derive_effective_kind(draft, submitted_kind, fallback_predecessor=None):
    """Strictly ordered derivation: ratio, then kind, then the eligible set."""
    predecessor = predecessor_ballot_of(draft)
    if predecessor is None:
        predecessor = fallback_predecessor
    if draft.get("prior_draft_id") is None:
        return submitted_kind, predecessor
    if gte(draft["substantive_change_ratio"], RECIRCULATION_RATIO_TRIGGER):
        return "RECIRCULATION", predecessor
    if draft.get("recirculation_required") is True:
        return "RECIRCULATION", predecessor
    if predecessor is not None:
        return predecessor["effective_ballot_kind"], predecessor
    return submitted_kind, predecessor


def eligible_seats(committee, effective_kind, predecessor_ballot):
    """Non-recirculation ballots take every ACTIVE seat carrying voting rights.
    A recirculation ballot narrows to the union of the seats that returned a vote
    on the predecessor ballot and the seats appointed after it closed."""
    active_voting = graph.voting_seats(committee)
    if effective_kind != "RECIRCULATION" or predecessor_ballot is None:
        return active_voting
    picked = {}
    for vote in graph.votes_of_ballot(predecessor_ballot):
        if vote["status"] != "CAST":
            continue
        seat = db.memberships.get(vote["membership_id"])
        if seat is not None:
            picked[seat["id"]] = seat
    closed_boundary = predecessor_ballot["_closes_at"]
    for seat in active_voting:
        if seat["id"] in picked:
            continue
        if seat["_appointed_at"] > closed_boundary:
            picked[seat["id"]] = seat
    out = list(picked.values())
    out.sort(key=lambda r: r["_seq"])
    return out


def thresholds(effective_kind, draft):
    """Required return rate and required approval, escalated by 5.0 points to a
    90.0 ceiling when the draft carries unresolved negatives forward."""
    required_return = round1(REQUIRED_RETURN_RATE[effective_kind])
    base = BASE_APPROVAL[effective_kind]
    if draft is not None and draft.get("carryover_unresolved_negative_count", 0) > 0:
        required_approval = min_pct(add_pct(base, CARRYOVER_ESCALATION), APPROVAL_CEILING)
    else:
        required_approval = round1(base)
    return required_return, required_approval


# --- tallies and evaluation ---------------------------------------------------

def cast_votes(ballot):
    return [v for v in graph.votes_of_ballot(ballot) if v["status"] == "CAST"]


def recompute_tallies(ballot):
    """Conserved quantity 1: the three position buckets sum to returned_count and
    returned_count + not_returned_count equals the frozen eligible_voter_count."""
    votes = cast_votes(ballot)
    affirmative = len([v for v in votes if v["position"] == "AFFIRMATIVE"])
    negative = len([v for v in votes if v["position"] == "NEGATIVE"])
    abstain = len([v for v in votes if v["position"] == "ABSTAIN"])
    returned = len(votes)
    ballot["affirmative_count"] = affirmative
    ballot["negative_count"] = negative
    ballot["abstain_count"] = abstain
    ballot["returned_count"] = returned
    ballot["not_returned_count"] = ballot["eligible_voter_count"] - returned
    return ballot


def pending_negatives(ballot):
    return len([v for v in graph.votes_of_ballot(ballot)
                if v["status"] == "CAST" and v["position"] == "NEGATIVE"
                and v["adjudication_status"] in ADJUDICABLE_PENDING])


def evaluate(ballot, draft, phase):
    """The four ordered evaluation steps. phase is 'provisional' at close and
    'final' on every adjudication re-reading."""
    recompute_tallies(ballot)
    eligible = ballot["eligible_voter_count"]
    return_rate = 0.0 if eligible == 0 else pct1(ballot["returned_count"], eligible)
    approval_base = ballot["affirmative_count"] + ballot["negative_count"]
    approval = 0.0 if approval_base == 0 else pct1(ballot["affirmative_count"], approval_base)

    required_return, required_approval = thresholds(ballot["effective_ballot_kind"], draft)
    ballot["required_return_rate_pct"] = required_return
    ballot["required_approval_pct"] = required_approval
    ballot["return_rate_pct"] = return_rate

    pending = pending_negatives(ballot)
    ballot["pending_negative_count"] = pending

    if lt(return_rate, required_return):
        verdict = "FAILED_QUORUM"
    elif lt(approval, required_approval):
        verdict = "FAILED_THRESHOLD"
    elif pending > 0:
        verdict = "APPROVED_PENDING_NEGATIVES"
    else:
        verdict = "APPROVED"
    ballot["consensus_result"] = verdict

    if phase == "provisional":
        ballot["provisional_approval_pct"] = approval
        ballot["final_approval_pct"] = None
    else:
        ballot["final_approval_pct"] = approval
    return verdict


# --- draft / work item movement ----------------------------------------------

def draft_pending_negatives(draft):
    total = 0
    for vote in graph.votes_of_draft(draft):
        if vote["status"] == "CAST" and vote["adjudication_status"] == "PENDING":
            total += 1
    return total


def latest_review_approved(draft):
    review = graph.latest_review_of_draft(draft)
    return review is not None and review["status"] == "DISPOSITION_APPROVED"


def any_review_disposition_approved(draft):
    for review in graph.reviews_of_draft(draft):
        if review["status"] == "DISPOSITION_APPROVED":
            return True
    return False


def refresh_ballot_round_count(draft):
    draft["ballot_round_count"] = len(graph.ballots_of_draft(draft))


def advance_to_consensus_approved(draft, work_item, ballot):
    """IN_DEVELOPMENT -> CONSENSUS_APPROVED. progress_status is written first and
    patent clearance is re-evaluated afterwards, so the now-closed call for
    patents can clear an otherwise clean work item."""
    if work_item["progress_status"] != "IN_DEVELOPMENT":
        return False
    if draft["status"] != "APPROVED":
        return False
    if ballot is None or ballot["consensus_result"] != "APPROVED":
        return False
    if ballot["pending_negative_count"] != 0:
        return False
    if not latest_review_approved(draft):
        return False
    if work_item["consensus_gate"] != "OPEN":
        return False
    work_item["progress_status"] = "CONSENSUS_APPROVED"
    touch(work_item)
    ip.recompute(work_item)
    return True


def draft_edge_after_close(ballot, draft):
    """Hop 3 of the close cascade."""
    draft["unresolved_negative_count"] = draft_pending_negatives(draft)
    origin = draft["status"]
    if draft["unresolved_negative_count"] >= 1:
        if origin in ("SUBCOMMITTEE_BALLOT", "CONSENSUS_BALLOT"):
            draft["status"] = "COMMENT_RESOLUTION"
    else:
        result = ballot["consensus_result"]
        if origin == "SUBCOMMITTEE_BALLOT":
            if result == "APPROVED":
                draft["status"] = "PUBLIC_REVIEW_READY"
            elif result in FAILED_RESULTS:
                draft["status"] = "DRAFTING"
        elif origin == "CONSENSUS_BALLOT":
            if result == "APPROVED" and latest_review_approved(draft):
                draft["status"] = "APPROVED"
            elif result in FAILED_RESULTS:
                draft["status"] = "PUBLIC_REVIEW_CLOSED"
    touch(draft)
    return draft["status"]


def attendance_sweep(ballot):
    """Every eligible seat that returned no vote takes a missed-ballot increment;
    a streak reaching two suspends the seat, never touching this ballot's frozen
    eligible_voter_count."""
    eligible_ids = ballot.get("_eligible_membership_ids") or []
    returned_ids = set(v["membership_id"] for v in cast_votes(ballot))
    suspended_any = False
    for seat_id in eligible_ids:
        seat = db.memberships.get(seat_id)
        if seat is None or seat_id in returned_ids:
            continue
        seat["missed_ballot_streak"] = seat.get("missed_ballot_streak", 0) + 1
        if seat["missed_ballot_streak"] >= 2 and seat["status"] == "ACTIVE":
            seat["status"] = "SUSPENDED"
            suspended_any = True
        touch(seat)
    if suspended_any:
        committee = db.committees.get(ballot["committee_id"])
        if committee is not None:
            balance.seat_change_cascade(committee)
    return suspended_any


def latest_evaluated_ballot(draft):
    return newest([b for b in graph.ballots_of_draft(draft) if b["status"] == "EVALUATED"])


def close(ballot):
    """The close cascade: freeze and evaluate, promote negatives to PENDING, move
    the draft, sweep attendance, then re-derive the work item."""
    draft = graph.draft_of_ballot(ballot)
    work_item = graph.work_item_of_draft(draft) if draft is not None else None

    # hop 1 -- tallies frozen, CLOSED is traversed and never externally observable
    ballot["closed_at"] = now_iso()
    ballot["_closed_at"] = now()
    ballot["status"] = "EVALUATED"
    evaluate(ballot, draft, "provisional")
    touch(ballot)

    # hop 2 -- every cast negative becomes an unresolved objection
    for vote in graph.votes_of_ballot(ballot):
        if (vote["status"] == "CAST" and vote["position"] == "NEGATIVE"
                and vote["adjudication_status"] == "NOT_APPLICABLE"):
            vote["adjudication_status"] = "PENDING"
            touch(vote)
    ballot["pending_negative_count"] = pending_negatives(ballot)

    # hop 3 -- the draft moves
    if draft is not None:
        draft_edge_after_close(ballot, draft)

    # attendance, which may suspend a seat and cascade onto the committee
    attendance_sweep(ballot)

    committee = db.committees.get(ballot["committee_id"])
    if committee is not None:
        balance.refresh_open_ballot_count(committee)

    # hop 4 -- the work item's gate and, where earned, consensus approval
    if work_item is not None:
        gate.recompute(work_item)
        if draft is not None:
            advance_to_consensus_approved(draft, work_item, ballot)
        touch(work_item)
    return ballot


def after_adjudication(vote, ballot, draft, work_item):
    """The final reading plus the edge out of COMMENT_RESOLUTION once the last
    pending negative has been cleared."""
    evaluate(ballot, draft, "final")
    touch(ballot)

    if draft is None:
        return
    draft["unresolved_negative_count"] = draft_pending_negatives(draft)
    if draft["status"] == "COMMENT_RESOLUTION" and draft["unresolved_negative_count"] == 0:
        latest = latest_evaluated_ballot(draft)
        result = latest["consensus_result"] if latest is not None else None
        persuasive = any(v["adjudication_status"] == "PERSUASIVE"
                         for v in graph.votes_of_draft(draft))
        if persuasive:
            draft["status"] = "DRAFTING"
            draft["recirculation_required"] = True
        elif result in FAILED_RESULTS:
            draft["status"] = "DRAFTING"
        elif (result in ("APPROVED", "APPROVED_PENDING_NEGATIVES")
                and not any_review_disposition_approved(draft)):
            draft["status"] = "PUBLIC_REVIEW_READY"
        elif latest_review_approved(draft) and result == "APPROVED":
            draft["status"] = "APPROVED"
    touch(draft)

    if work_item is not None:
        gate.recompute(work_item)
        advance_to_consensus_approved(draft, work_item, latest_evaluated_ballot(draft))
        touch(work_item)
