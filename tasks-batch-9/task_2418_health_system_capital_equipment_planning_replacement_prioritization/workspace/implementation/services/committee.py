"""committee_tally — quorum, approval and veto arithmetic (PRD section 3.7)."""

from db import db, ordered
from errors import ApiError

QUORUM_NUMERATOR = 3
QUORUM_DENOMINATOR = 5
APPROVAL_NUMERATOR = 2
APPROVAL_DENOMINATOR = 3
DEFER_NUMERATOR = 1
DEFER_DENOMINATOR = 2


def eligible_members(request, facility_id):
    """Step 1 — the structurally eligible voter set."""
    eligible = []
    for member in ordered(db.members.values()):
        if not member["active"]:
            continue
        if member["facility_id"] is not None and member["facility_id"] != facility_id:
            continue
        if request["sponsor_member_id"] is not None and \
                member["id"] == request["sponsor_member_id"]:
            continue
        if member["department_id"] is not None and \
                member["department_id"] == request["department_id"]:
            continue
        eligible.append(member)
    return eligible


def is_eligible(member, request, facility_id):
    if not member["active"]:
        return False
    if member["facility_id"] is not None and member["facility_id"] != facility_id:
        return False
    if request["sponsor_member_id"] is not None and \
            member["id"] == request["sponsor_member_id"]:
        return False
    if member["department_id"] is not None and \
            member["department_id"] == request["department_id"]:
        return False
    return True


def counted_ballots(request_id, eligible_ids):
    return [v for v in ordered(db.votes.values())
            if v["request_id"] == request_id and not v["superseded"]
            and v["member_id"] in eligible_ids]


def tally(request, facility_id):
    """Steps 1-4. Returns the resulting request status; raises on a fault."""
    eligible = eligible_members(request, facility_id)
    eligible_ids = set(m["id"] for m in eligible)
    quorum_weight = sum(m["voting_weight"] for m in eligible)

    ballots = counted_ballots(request["id"], eligible_ids)
    cast_weight = sum(b["counted_weight"] for b in ballots)
    approve_weight = sum(b["counted_weight"] for b in ballots
                         if b["vote"] == "APPROVE")

    veto_present = False
    for ballot in ballots:
        if ballot["vote"] != "VETO":
            continue
        member = db.members.get(ballot["member_id"])
        if member is not None and member["seat"] == "SAFETY_OFFICER":
            veto_present = True
            break

    # Step 4a — a veto ends the matter without consulting quorum.
    if veto_present:
        return "REJECTED"
    # Step 4b
    if not eligible:
        raise ApiError("ERR_NO_ELIGIBLE_VOTERS")
    # Step 4c — integer cross-multiplication, no division.
    if cast_weight * QUORUM_DENOMINATOR < quorum_weight * QUORUM_NUMERATOR:
        raise ApiError("ERR_QUORUM_NOT_MET")
    # Step 4d
    if approve_weight * APPROVAL_DENOMINATOR >= cast_weight * APPROVAL_NUMERATOR:
        return "APPROVED"
    # Step 4e
    if approve_weight * DEFER_DENOMINATOR >= cast_weight * DEFER_NUMERATOR:
        return "DEFERRED"
    # Step 4f
    return "REJECTED"
