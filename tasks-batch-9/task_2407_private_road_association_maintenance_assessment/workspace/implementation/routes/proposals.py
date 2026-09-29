"""Special assessment proposals: drafting, balloting rounds and tally (PRD 3.5)."""

from fractions import Fraction

from flask import Blueprint

import response as R
import validation as V
from db import (add_days, by_seq, clock_date, date_str, db, iso, new_row,
                now_dt, now_iso, parse_datetime, touch)
from errors import ApiError
from middleware import READ_ALL, auth
from services import calc
from services import constants as C
from services import state as S

bp = Blueprint("proposals", __name__)

BALLOT_READERS = ("AssociationSecretary", "BoardTreasurer", "MemberOwner")


@bp.post("/special-assessment-proposals")
@auth("BoardTreasurer")
def create_proposal():
    body = V.get_body()
    road_segment_id = V.req_str(body, "road_segment_id")
    project_type = V.req_enum(body, "project_type", C.PROJECT_TYPES)
    title = V.req_str(body, "title")
    estimated_cost_cents = V.req_int(body, "estimated_cost_cents", minimum=1)
    cost_allocation_method = V.req_enum(body, "cost_allocation_method", C.COST_ALLOCATION_METHODS)
    voting_basis = V.opt_enum(body, "voting_basis", C.VOTING_BASES)

    segment = S.require("segment", road_segment_id)
    association = S.association_of_segment(segment)

    if voting_basis is None:
        voting_basis = association["default_voting_basis"] if association else "PER_PARCEL"
    posture = association["reserve_posture"] if association else "UNDERFUNDED"

    row = new_row({
        "road_segment_id": road_segment_id,
        "project_type": project_type,
        "title": title,
        "estimated_cost_cents": estimated_cost_cents,
        "cost_allocation_method": cost_allocation_method,
        "voting_basis": voting_basis,
        "status": "DRAFT",
        "required_threshold_bps": calc.vote_threshold_bps(
            project_type, estimated_cost_cents, posture),
        "balloting_closes_at": None,
        "balloting_opened_at": None,
        "eligible_weight_total": 0,
        "counted_weight_total": 0,
        "yes_weight_total": 0,
        "no_weight_total": 0,
        "abstain_weight_total": 0,
        "quorum_met": False,
        "failed_tally_count": 0,
        "approved_amount_cents": 0,
    })
    db.proposals[row["id"]] = row
    return R.ok(row, 201)


@bp.get("/special-assessment-proposals/<proposal_id>")
@auth(*READ_ALL)
def read_proposal(proposal_id):
    return R.ok(S.require("proposal", proposal_id))


@bp.get("/special-assessment-proposals")
@auth(*READ_ALL)
def list_proposals():
    limit, offset = V.pagination()
    road_segment_id = V.query_str("road_segment_id")
    status = V.query_enum("status", C.PROPOSAL_STATUSES)
    project_type = V.query_enum("project_type", C.PROJECT_TYPES)

    rows = by_seq(list(db.proposals.values()))
    if road_segment_id is not None:
        rows = [r for r in rows if r["road_segment_id"] == road_segment_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if project_type is not None:
        rows = [r for r in rows if r["project_type"] == project_type]
    page, total = V.paginate(rows, limit, offset)
    return R.ok_list(page, limit, offset, total)


@bp.get("/special-assessment-proposals/<proposal_id>/ballots")
@auth(*BALLOT_READERS)
def list_proposal_ballots(proposal_id):
    limit, offset = V.pagination()
    status = V.query_enum("status", C.BALLOT_STATUSES)

    S.require("proposal", proposal_id)
    rows = S.ballots_of_proposal(proposal_id)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = V.paginate(rows, limit, offset)
    return R.ok_list(page, limit, offset, total)


@bp.post("/special-assessment-proposals/<proposal_id>/open-balloting")
@auth("BoardTreasurer")
def open_balloting(proposal_id):
    body = V.get_body()
    closes_at = V.req_dt(body, "balloting_closes_at")

    proposal = S.require("proposal", proposal_id)
    if proposal["status"] != "DRAFT":
        raise ApiError("ERR_PROPOSAL_NOT_DRAFT", "Only a DRAFT proposal may open a round.")
    if closes_at <= now_dt():
        raise ApiError("ERR_INVALID_DATE_RANGE",
                       "balloting_closes_at must be strictly after the current clock.")

    association = S.association_of_proposal(proposal)
    posture = association["reserve_posture"] if association else "UNDERFUNDED"

    eligible = S.eligible_voters(proposal)
    proposal["eligible_weight_total"] = sum(
        S.voting_weight(member, proposal["voting_basis"]) for member in eligible)
    proposal["counted_weight_total"] = 0
    proposal["yes_weight_total"] = 0
    proposal["no_weight_total"] = 0
    proposal["abstain_weight_total"] = 0
    proposal["quorum_met"] = False
    proposal["required_threshold_bps"] = calc.vote_threshold_bps(
        proposal["project_type"], proposal["estimated_cost_cents"], posture)
    proposal["balloting_opened_at"] = now_iso()
    proposal["balloting_closes_at"] = iso(closes_at)
    proposal["status"] = "BALLOTING"
    touch(proposal)
    return R.ok(proposal)


def _adopt(proposal):
    association = S.association_of_proposal(proposal)
    roll = S.latest_levied_roll(association["id"]) if association else None
    if roll is None:
        raise ApiError("ERR_ROLL_NOT_FOUND",
                       "The association has no LEVIED roll to carry the special charges.")

    pairs = S.assessable_parcels(association["id"], proposal["road_segment_id"])
    units = [S.units_for_variant(parcel, proposal["cost_allocation_method"])
             for parcel, _ in pairs]
    amounts, _, _, _ = calc.allocate(proposal["estimated_cost_cents"], units)

    due = date_str(add_days(clock_date(), C.NET_DAYS))
    affected = []
    if amounts is not None:
        for index, (parcel, member) in enumerate(pairs):
            S.create_charge(
                roll_id=roll["id"],
                parcel_id=parcel["id"],
                member_id=member["id"],
                charge_type="SPECIAL",
                share_units=units[index],
                amount_cents=amounts[index],
                status="OPEN",
                due_date=due,
                proposal_id=proposal["id"],
            )
            affected.append(member["id"])

    proposal["approved_amount_cents"] = proposal["estimated_cost_cents"]
    proposal["status"] = "ADOPTED"
    touch(proposal)
    S.reconcile_members(affected)


@bp.post("/special-assessment-proposals/<proposal_id>/tally")
@auth("BoardTreasurer")
def tally_proposal(proposal_id):
    proposal = S.require("proposal", proposal_id)
    if proposal["status"] != "BALLOTING":
        raise ApiError("ERR_PROPOSAL_NOT_BALLOTING", "Only a BALLOTING proposal may be tallied.")

    closes_at = parse_datetime(proposal["balloting_closes_at"])
    if closes_at is not None and now_dt() < closes_at:
        raise ApiError("ERR_BALLOTING_STILL_OPEN",
                       "The balloting round has not reached balloting_closes_at.")

    quorum = proposal["quorum_met"]
    approved = (proposal["yes_weight_total"] * 10000
                >= proposal["counted_weight_total"] * proposal["required_threshold_bps"])

    if quorum and approved:
        _adopt(proposal)
        return R.ok(proposal)

    if quorum or proposal["failed_tally_count"] >= 2:
        proposal["status"] = "REJECTED"
        touch(proposal)
        return R.ok(proposal)

    for ballot in S.ballots_of_proposal(proposal["id"]):
        if ballot["status"] == "CAST":
            ballot["status"] = "VOIDED"
            touch(ballot)
    proposal["failed_tally_count"] = int(proposal["failed_tally_count"]) + 1
    proposal["counted_weight_total"] = 0
    proposal["yes_weight_total"] = 0
    proposal["no_weight_total"] = 0
    proposal["abstain_weight_total"] = 0
    proposal["quorum_met"] = False
    proposal["balloting_opened_at"] = None
    proposal["balloting_closes_at"] = None
    proposal["status"] = "DRAFT"
    touch(proposal)
    return R.ok(proposal)
