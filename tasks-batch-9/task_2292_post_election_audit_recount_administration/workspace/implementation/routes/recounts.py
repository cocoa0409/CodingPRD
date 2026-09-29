"""Recount endpoints: filing, deposits, settlement and re-canvass."""

from flask import Blueprint, g

from db import clock_now, db, dt_of, insert, sorted_rows, touch
from errors import fail
from middleware import (
    ROLE_AUDIT_MANAGER,
    ROLE_CANDIDATE_REPRESENTATIVE,
    ROLE_CANVASSING_BOARD_MEMBER,
    ROLE_ELECTIONS_DIRECTOR,
    guard,
)
from routes.common import list_endpoint, lookup, single
from services import calc
from services.domain import (
    TERMINAL_AUDIT_STATES,
    audits_of_contest,
    batches_of_contest,
    recompute_contest_counts,
    recompute_contest_margin,
    recompute_election,
    recompute_planned_sample_size,
    recounts_of_contest,
    terminate_audit,
)
from validate import (
    body,
    req_enum,
    req_id_list,
    req_int,
    req_num,
    req_str,
    req_vote_map,
)

bp = Blueprint("recounts", __name__)

TRIGGER_TYPES = ("AUTOMATIC_MARGIN", "CANDIDATE_REQUESTED", "AUDIT_ESCALATION")
SCOPES = ("FULL_CONTEST", "PARTIAL_BATCHES")
RECOUNT_STATUSES = (
    "REQUESTED",
    "DEPOSIT_HELD",
    "IN_PROGRESS",
    "COMPLETED",
    "WITHDRAWN",
    "DENIED",
)
DEPOSIT_STATUSES = (
    "NOT_REQUIRED",
    "PENDING",
    "HELD",
    "REFUNDED_FULL",
    "PARTIALLY_REFUNDED",
    "FORFEITED",
)
LIVE_RECOUNT_STATES = ("REQUESTED", "DEPOSIT_HELD", "IN_PROGRESS")
READ_ROLES = (
    ROLE_ELECTIONS_DIRECTOR,
    ROLE_AUDIT_MANAGER,
    ROLE_CANDIDATE_REPRESENTATIVE,
    ROLE_CANVASSING_BOARD_MEMBER,
)


def _contest_of(recount):
    contest = db.contests.get(recount["contest_id"])
    if contest is None:
        fail("ERR_CONTEST_NOT_FOUND")
    return contest


def _election_of(contest):
    return db.elections.get(contest["election_id"])


def _scope_batches(recount, contest):
    """Batches billed by the recount, ordered by batch_label ascending."""
    if recount["scope"] == "FULL_CONTEST":
        rows = batches_of_contest(contest)
    else:
        rows = []
        for batch_id in recount["scope_batch_ids"] or []:
            batch = db.ballot_batches.get(batch_id)
            if batch is not None:
                rows.append(batch)
    return sorted_rows(rows, ("batch_label",))


def _requesting_party(recount):
    if g.user_id is None or g.user_id != recount["requested_by_user_id"]:
        fail("ERR_NOT_REQUESTING_PARTY")


def _settle(recount, settlement):
    """Apply a settlement dict, honouring the NOT_REQUIRED money dimension."""
    recount["refund_variant"] = settlement["refund_variant"]
    if recount["deposit_status"] == "NOT_REQUIRED":
        return
    recount["refunded_cents"] = settlement["refunded_cents"]
    recount["forfeited_cents"] = settlement["forfeited_cents"]
    recount["admin_retained_cents"] = settlement["admin_retained_cents"]
    recount["deposit_status"] = settlement["deposit_status"]


# ---------------------------------------------------------------------------
# filing
# ---------------------------------------------------------------------------


@bp.post("/recounts")
@guard([ROLE_CANDIDATE_REPRESENTATIVE, ROLE_ELECTIONS_DIRECTOR])
def create_recount():
    data = body()
    contest_id = req_str(data, "contest_id", 1, None)
    expected_contest_version = req_int(data, "expected_contest_version", 0, None)
    trigger_type = req_enum(data, "trigger_type", TRIGGER_TYPES)
    scope = req_enum(data, "scope", SCOPES)

    if scope == "PARTIAL_BATCHES":
        scope_batch_ids = req_id_list(data, "scope_batch_ids", 1)
    else:
        if data.get("scope_batch_ids") is not None:
            fail(
                "ERR_VALIDATION",
                "Field 'scope_batch_ids' must be null for a FULL_CONTEST recount.",
            )
        scope_batch_ids = None

    if trigger_type == "CANDIDATE_REQUESTED":
        requested_by_candidate_name = req_str(
            data, "requested_by_candidate_name", 1, None
        )
    else:
        requested_by_candidate_name = None

    if trigger_type == "AUDIT_ESCALATION":
        audit_id = req_str(data, "audit_id", 1, None)
    else:
        audit_id = None

    contest = lookup("contests", contest_id)
    if audit_id is not None:
        lookup("audits", audit_id)
    named_batches = []
    if scope_batch_ids:
        for batch_id in scope_batch_ids:
            named_batches.append(lookup("ballot_batches", batch_id))

    if contest["version"] != expected_contest_version:
        fail("ERR_STALE_CONTEST_VERSION")

    if contest["status"] != "CANVASSED":
        fail("ERR_CONTEST_NOT_CANVASSED")

    election = _election_of(contest)
    if election is not None and election["status"] == "CERTIFIED":
        fail("ERR_ELECTION_ALREADY_CERTIFIED")

    for batch in named_batches:
        if batch["custody_status"] == "QUARANTINED":
            fail("ERR_BATCH_QUARANTINED")
    for batch in named_batches:
        if batch["contest_id"] != contest_id:
            fail("ERR_BATCH_NOT_IN_CONTEST")

    if trigger_type == "CANDIDATE_REQUESTED":
        deadline = contest.get("recount_request_deadline_at")
        if deadline is not None and clock_now() > dt_of(deadline):
            fail("ERR_RECOUNT_REQUEST_WINDOW_CLOSED")
        if not calc.margin_recount_eligible(contest.get("margin_pct")):
            fail("ERR_MARGIN_NOT_RECOUNT_ELIGIBLE")

    requested = set(scope_batch_ids or [])
    for other in recounts_of_contest(contest):
        if other["status"] not in LIVE_RECOUNT_STATES:
            continue
        if scope == "FULL_CONTEST" or other["scope"] == "FULL_CONTEST":
            fail("ERR_RECOUNT_SCOPE_OVERLAP")
        if requested & set(other["scope_batch_ids"] or []):
            fail("ERR_RECOUNT_SCOPE_OVERLAP")

    if scope == "FULL_CONTEST":
        ballots_in_scope = sum(b["ballot_count"] for b in batches_of_contest(contest))
    else:
        ballots_in_scope = sum(b["ballot_count"] for b in named_batches)

    required, deposit_status = calc.deposit_assessment(
        trigger_type, scope, ballots_in_scope
    )

    row = insert(
        "recounts",
        {
            "contest_id": contest_id,
            "audit_id": audit_id,
            "trigger_type": trigger_type,
            "requested_by_candidate_name": requested_by_candidate_name,
            "requested_by_user_id": g.user_id,
            "scope": scope,
            "scope_batch_ids": list(scope_batch_ids) if scope_batch_ids else None,
            "ballots_in_scope": ballots_in_scope,
            "required_deposit_cents": required,
            "deposit_paid_cents": 0,
            "refunded_cents": 0,
            "forfeited_cents": 0,
            "admin_retained_cents": 0,
            "actual_cost_cents": 0,
            "team_hours": None,
            "refund_variant": "NONE",
            "deposit_status": deposit_status,
            "status": "REQUESTED",
            "final_votes": None,
            "final_margin_votes": None,
            "margin_change_votes": None,
            "outcome_changed": False,
            "denial_reason": None,
        },
    )

    recompute_contest_counts(contest)
    recompute_election(election)
    return single(row, 201)


@bp.get("/recounts")
@guard(READ_ROLES)
def list_recounts():
    return list_endpoint(
        "recounts",
        {
            "contest_id": ("contest_id", None),
            "audit_id": ("audit_id", None),
            "status": ("status", RECOUNT_STATUSES),
            "deposit_status": ("deposit_status", DEPOSIT_STATUSES),
        },
    )


@bp.get("/recounts/<recount_id>")
@guard(READ_ROLES)
def get_recount(recount_id):
    return single(lookup("recounts", recount_id))


# ---------------------------------------------------------------------------
# money and workflow transitions
# ---------------------------------------------------------------------------


@bp.post("/recounts/<recount_id>/deposit")
@guard([ROLE_CANDIDATE_REPRESENTATIVE])
def fund_recount(recount_id):
    data = body()
    amount_cents = req_int(data, "amount_cents", 0, None)

    recount = lookup("recounts", recount_id)
    _requesting_party(recount)

    if recount["status"] != "REQUESTED":
        fail("ERR_INVALID_RECOUNT_STATE")
    if recount["deposit_status"] == "NOT_REQUIRED":
        fail("ERR_DEPOSIT_NOT_REQUIRED")
    if recount["deposit_status"] != "PENDING":
        fail("ERR_INVALID_RECOUNT_STATE")
    if amount_cents != recount["required_deposit_cents"]:
        fail("ERR_DEPOSIT_INSUFFICIENT")

    recount["deposit_paid_cents"] = amount_cents
    recount["deposit_status"] = "HELD"
    recount["status"] = "DEPOSIT_HELD"
    touch(recount)
    return single(recount)


@bp.post("/recounts/<recount_id>/start")
@guard([ROLE_ELECTIONS_DIRECTOR])
def start_recount(recount_id):
    recount = lookup("recounts", recount_id)

    startable = recount["status"] == "DEPOSIT_HELD" or (
        recount["status"] == "REQUESTED"
        and recount["deposit_status"] == "NOT_REQUIRED"
    )
    if not startable:
        fail("ERR_INVALID_RECOUNT_STATE")

    contest = _contest_of(recount)
    election = _election_of(contest)
    if election is None or election["status"] != "CANVASSED":
        fail("ERR_ELECTION_NOT_CANVASSED")

    for audit in audits_of_contest(contest):
        if audit["status"] not in TERMINAL_AUDIT_STATES:
            fail("ERR_AUDIT_NOT_TERMINAL")

    recount["status"] = "IN_PROGRESS"
    touch(recount)
    return single(recount)


@bp.post("/recounts/<recount_id>/complete")
@guard([ROLE_ELECTIONS_DIRECTOR])
def complete_recount(recount_id):
    data = body()
    final_votes = req_vote_map(data, "final_votes")
    team_hours = req_num(data, "team_hours", 0, None, max_dp=2)

    recount = lookup("recounts", recount_id)
    if recount["status"] != "IN_PROGRESS":
        fail("ERR_INVALID_RECOUNT_STATE")

    contest = _contest_of(recount)
    election = _election_of(contest)

    if set(final_votes.keys()) != set(contest["candidate_names"]):
        fail("ERR_CANDIDATE_NAME_UNKNOWN")
    if sum(final_votes.values()) > recount["ballots_in_scope"]:
        fail("ERR_BALLOT_ACCOUNTING_EXCEEDED")

    scope_batches = _scope_batches(recount, contest)
    actual_cost = calc.recount_actual_cost(scope_batches, team_hours)

    previous_margin = contest.get("margin_votes") or 0
    previous_winner = contest.get("winner_name")
    ranked = calc.rank_candidates(contest["candidate_names"], final_votes)
    leader = ranked[0] if ranked else None
    runner_up = ranked[1] if len(ranked) > 1 else None
    final_margin = int(final_votes.get(leader, 0)) - int(final_votes.get(runner_up, 0))
    margin_change = final_margin - int(previous_margin)
    outcome_changed = leader != previous_winner

    settlement = calc.completion_settlement(
        recount["deposit_paid_cents"], actual_cost, outcome_changed, margin_change
    )

    recount["team_hours"] = calc.fnum(team_hours)
    recount["final_votes"] = dict(final_votes)
    recount["actual_cost_cents"] = actual_cost
    recount["final_margin_votes"] = final_margin
    recount["margin_change_votes"] = margin_change
    recount["outcome_changed"] = outcome_changed
    _settle(recount, settlement)
    recount["status"] = "COMPLETED"
    touch(recount)

    # the contest re-canvasses itself in place
    contest["reported_votes"] = dict(final_votes)
    recompute_contest_margin(contest)
    recompute_contest_counts(contest)
    touch(contest)

    for audit in audits_of_contest(contest):
        if audit["status"] in ("PLANNED", "SEEDED"):
            if recompute_planned_sample_size(audit, contest):
                audit["sample_size_stale"] = True
                touch(audit)

    if recount["scope"] == "FULL_CONTEST":
        for audit in audits_of_contest(contest):
            if audit["status"] not in TERMINAL_AUDIT_STATES:
                terminate_audit(audit, "Superseded by a full-contest recount")

    recompute_election(election)
    return single(recount)


@bp.post("/recounts/<recount_id>/withdraw")
@guard([ROLE_CANDIDATE_REPRESENTATIVE])
def withdraw_recount(recount_id):
    data = body()
    reason = req_str(data, "reason", 1, None)

    recount = lookup("recounts", recount_id)
    _requesting_party(recount)

    if recount["status"] not in ("REQUESTED", "DEPOSIT_HELD"):
        fail("ERR_INVALID_RECOUNT_STATE")

    if recount["deposit_status"] == "HELD":
        _settle(recount, calc.withdrawal_settlement(recount["deposit_paid_cents"]))
    recount["status"] = "WITHDRAWN"
    touch(recount)

    contest = _contest_of(recount)
    recompute_contest_counts(contest)
    recompute_election(_election_of(contest))
    return single(recount)


@bp.post("/recounts/<recount_id>/deny")
@guard([ROLE_ELECTIONS_DIRECTOR])
def deny_recount(recount_id):
    data = body()
    denial_reason = req_str(data, "denial_reason", 1, None)

    recount = lookup("recounts", recount_id)
    if recount["status"] not in ("REQUESTED", "DEPOSIT_HELD"):
        fail("ERR_INVALID_RECOUNT_STATE")

    if recount["deposit_status"] == "HELD":
        _settle(recount, calc.denial_settlement(recount["deposit_paid_cents"]))
    recount["denial_reason"] = denial_reason
    recount["status"] = "DENIED"
    touch(recount)

    contest = _contest_of(recount)
    recompute_contest_counts(contest)
    recompute_election(_election_of(contest))
    return single(recount)
