"""Committee ballot endpoints (confidential reads, OCC-guarded decisions)."""
from flask import Blueprint

from db import now_iso, store, touch
from errors import ApiError
from middleware import authorize
from response import listing, ok
from routes.common import by_created, filtered, find_ballot
from services import calculations as calc
from services.engine import commit
from validation import (bad, field_decimal, field_enum, field_int, field_str, get_body,
                        pagination, query_enum, query_str)

bp = Blueprint("ballots", __name__)

READ_ROLES = ["CycleAdmin", "CommitteeMember"]
ACTIONS = ["CAST", "ABSTAIN", "RECUSE"]


def _locked(ballot):
    cycle = store.cycles.get(ballot["cycle_id"])
    return bool(cycle and cycle["confidentiality_locked"])


@bp.get("/comp/ballots/<ballot_id>")
def read_ballot(ballot_id):
    user_id, role = authorize(READ_ROLES)
    ballot = find_ballot(ballot_id)
    if role == "CommitteeMember":
        if _locked(ballot) or ballot["committee_member_id"] != user_id:
            raise ApiError("ERR_BALLOT_CONFIDENTIAL")
    return ok(ballot)


@bp.get("/comp/ballots")
def list_ballots():
    user_id, role = authorize(READ_ROLES)
    limit, offset = pagination()
    filters = {
        "cycle_id": query_str("cycle_id"),
        "subject_partner_id": query_str("subject_partner_id"),
        "committee_member_id": query_str("committee_member_id"),
        "state": query_enum("state", calc.BALLOT_STATES),
    }
    rows = list(store.ballots.values())
    if role == "CommitteeMember":
        if filters["committee_member_id"] != user_id:
            raise ApiError("ERR_BALLOT_CONFIDENTIAL")
        cycle_id = filters["cycle_id"]
        if cycle_id is not None:
            cycle = store.cycles.get(cycle_id)
            if cycle is not None and cycle["confidentiality_locked"]:
                raise ApiError("ERR_BALLOT_CONFIDENTIAL")
        rows = [b for b in rows if not _locked(b)]
    rows = by_created(filtered(rows, filters))
    return listing(rows, limit, offset)


@bp.post("/comp/ballots/<ballot_id>/cast")
def cast_ballot(ballot_id):
    user_id, _ = authorize(["CommitteeMember"])
    body = get_body()
    action = field_enum(body, "action", ACTIONS)
    points = field_decimal(body, "points_proposed", 2, required=False,
                           low="0.00", high="100000.00")
    rationale = field_str(body, "rationale", required=False)
    recusal_reason = field_str(body, "recusal_reason", required=False)
    expected = field_int(body, "expected_cycle_version")
    if action == "CAST" and points is None:
        bad()
    if action == "RECUSE" and not recusal_reason:
        bad()

    ballot = find_ballot(ballot_id)
    if user_id != ballot["committee_member_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if ballot["state"] != "PENDING":
        raise ApiError("ERR_BALLOT_ALREADY_DECIDED")
    cycle = store.cycles[ballot["cycle_id"]]
    if cycle["state"] != "DELIBERATION":
        raise ApiError("ERR_INVALID_CYCLE_TRANSITION")

    if action == "CAST":
        accepted = [a for a in store.assessments.values()
                    if a["cycle_id"] == ballot["cycle_id"]
                    and a["partner_id"] == ballot["subject_partner_id"]
                    and a["state"] == "ACCEPTED"]
        if not accepted:
            raise ApiError("ERR_ASSESSMENT_NOT_ACCEPTED")

    if expected != cycle["version"]:
        raise ApiError("ERR_STALE_VERSION")

    if action == "CAST":
        if ballot["committee_member_id"] == ballot["subject_partner_id"]:
            raise ApiError("ERR_SELF_VOTE_FORBIDDEN")
        if points > calc.POINTS_CAP_PER_BALLOT:
            raise ApiError("ERR_POINTS_CAP_EXCEEDED")
        ballot["points_proposed"] = points
        ballot["rationale"] = rationale
        ballot["state"] = "CAST"
    elif action == "ABSTAIN":
        ballot["recusal_reason"] = recusal_reason
        ballot["state"] = "ABSTAINED"
    else:
        ballot["recusal_reason"] = recusal_reason
        ballot["state"] = "RECUSED"

    ballot["decided_at"] = now_iso()
    touch(ballot)
    touch(cycle)
    return ok(commit(ballot))
