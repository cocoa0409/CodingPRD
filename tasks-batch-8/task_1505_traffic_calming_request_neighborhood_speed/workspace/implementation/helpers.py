"""Shared lookups, list plumbing, and the clock sweeps (PRD §2.4, §2.9, §3.6)."""
from errors import (
    ApiError, ERR_SEGMENT_NOT_FOUND, ERR_RESIDENT_NOT_FOUND, ERR_REQUEST_NOT_FOUND,
    ERR_SIGNATURE_NOT_FOUND, ERR_STUDY_NOT_FOUND, ERR_PLAN_NOT_FOUND,
    ERR_CYCLE_NOT_FOUND, ERR_BALLOT_NOT_FOUND, ERR_WORK_ORDER_NOT_FOUND,
    ERR_REMOVAL_REQUEST_NOT_FOUND,
)
from store import store, touch
from envelope import sort_by_created, list_response
from validate import pagination
from calc import ballot_outcome

TERMINAL_REQUEST_STATUSES = ("PETITION_FAILED", "SCORE_INELIGIBLE", "CONSENT_DENIED", "REMOVED")


def get_or_404(mapping, key, error_id, label):
    entity = mapping.get(key)
    if entity is None:
        raise ApiError(404, error_id, "%s %s does not exist" % (label, key))
    return entity


def get_segment(sid):
    return get_or_404(store.segments, sid, ERR_SEGMENT_NOT_FOUND, "Street segment")


def get_resident(rid):
    return get_or_404(store.residents, rid, ERR_RESIDENT_NOT_FOUND, "Resident")


def get_request(rid):
    return get_or_404(store.requests, rid, ERR_REQUEST_NOT_FOUND, "Request")


def get_signature(sid):
    return get_or_404(store.signatures, sid, ERR_SIGNATURE_NOT_FOUND, "Petition signature")


def get_study(sid):
    return get_or_404(store.studies, sid, ERR_STUDY_NOT_FOUND, "Speed study")


def get_plan(pid):
    return get_or_404(store.plans, pid, ERR_PLAN_NOT_FOUND, "Treatment plan")


def get_cycle(cid):
    return get_or_404(store.cycles, cid, ERR_CYCLE_NOT_FOUND, "Funding cycle")


def get_ballot(bid):
    return get_or_404(store.ballots, bid, ERR_BALLOT_NOT_FOUND, "Ballot")


def get_work_order(wid):
    return get_or_404(store.work_orders, wid, ERR_WORK_ORDER_NOT_FOUND, "Installation work order")


def get_removal(rid):
    return get_or_404(store.removals, rid, ERR_REMOVAL_REQUEST_NOT_FOUND, "Removal request")


def paginated(items, filters=None):
    """Filter (exact match on serialized field values), sort by created_at ASC,
    paginate, and wrap in the list envelope (PRD §2.3)."""
    if filters:
        for key, value in filters.items():
            if value is not None:
                items = [e for e in items if e.get(key) == value]
    limit, offset = pagination()
    return list_response(sort_by_created(items), limit, offset)


def recompute_signature_count(req):
    req["signature_count"] = sum(
        1 for s in store.signatures.values() if s["request_id"] == req["id"])


def recompute_observation_counts(study):
    obs = [o for o in store.observations.values() if o["study_id"] == study["id"]]
    study["observation_count"] = len(obs)
    study["valid_observation_count"] = sum(1 for o in obs if o["is_valid"])


def recompute_vote_counts(ballot):
    votes = [v for v in store.votes.values() if v["ballot_id"] == ballot["id"]]
    ballot["votes_received"] = len(votes)
    ballot["votes_for"] = sum(1 for v in votes if v["choice"] == "FOR")
    ballot["votes_against"] = sum(1 for v in votes if v["choice"] == "AGAINST")


def tally_ballot(ballot):
    """PRD §3.6: tally an OPEN ballot and fork the parent request."""
    recompute_vote_counts(ballot)
    granted = ballot_outcome(ballot["votes_received"], ballot["votes_for"], ballot["quorum_required"])
    ballot["outcome"] = "CONSENT_GRANTED" if granted else "CONSENT_DENIED"
    ballot["status"] = "TALLIED"
    touch(ballot)
    req = store.requests[ballot["request_id"]]
    if granted:
        # Branch A: request BALLOT_OPEN -> CONSENT_GRANTED
        req["status"] = "CONSENT_GRANTED"
    else:
        # Branch B: request BALLOT_OPEN -> CONSENT_DENIED with compensating release
        if req["funding_cycle_id"] is not None:
            cycle = store.cycles[req["funding_cycle_id"]]
            cycle["budget_committed_cents"] -= req["allocated_cents"]
            cycle["budget_available_cents"] = (
                cycle["budget_total_cents"] - cycle["budget_committed_cents"])
            touch(cycle)
        req["allocated_cents"] = 0
        req["funding_cycle_id"] = None
        req["citywide_rank"] = None
        req["status"] = "CONSENT_DENIED"
    touch(req)


def run_clock_sweeps():
    """PRD §2.4: every clock advance runs the petition-deadline sweep and the
    ballot-tally sweep inside the same operation."""
    now = store.now
    # (1) petition-deadline sweep (PRD §3.2)
    for req in list(store.requests.values()):
        if req["status"] == "PETITION_OPEN" \
                and now > req["petition_deadline_at"] \
                and req["signature_count"] < req["required_signatures"]:
            req["status"] = "PETITION_FAILED"
            touch(req)
    # (2) ballot-tally sweep (PRD §3.6)
    for ballot in list(store.ballots.values()):
        if ballot["status"] == "OPEN" and now > ballot["close_date"]:
            tally_ballot(ballot)
