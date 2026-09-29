"""Maintenance projects: solicitation, bids, award, completion, cancellation
(PRD 3.7)."""

from flask import Blueprint

import response as R
import validation as V
from db import (add_days, by_seq, date_str, db, iso, new_row, now_iso,
                parse_date, touch)
from errors import ApiError
from middleware import actor_id, auth
from services import calc
from services import constants as C
from services import state as S

bp = Blueprint("projects", __name__)

PROJECT_READERS = ("AssociationSecretary", "AssessmentClerk", "BoardTreasurer",
                   "RoadCommissioner", "MemberOwner", "Contractor")
BID_READERS = ("AssociationSecretary", "BoardTreasurer", "RoadCommissioner", "Contractor")


@bp.post("/maintenance-projects")
@auth("RoadCommissioner")
def create_project():
    body = V.get_body()
    road_segment_id = V.req_str(body, "road_segment_id")
    category = V.req_enum(body, "category", C.PROJECT_CATEGORIES)
    window_start = V.req_date(body, "window_start_date")
    window_end = V.req_date(body, "window_end_date")
    proposal_id = V.opt_str(body, "proposal_id")

    segment = S.require("segment", road_segment_id)
    proposal = None
    if proposal_id is not None:
        proposal = S.require("proposal", proposal_id)

    if proposal is not None:
        if proposal["status"] != "ADOPTED":
            raise ApiError("ERR_PROPOSAL_NOT_ADOPTED",
                           "The cited proposal is not ADOPTED.")
        if (proposal["road_segment_id"] != road_segment_id
                or proposal["project_type"] != category):
            raise ApiError("ERR_PROPOSAL_SEGMENT_MISMATCH",
                           "The cited proposal does not match this project's segment and category.")

    for other in by_seq(list(db.projects.values())):
        if other["road_segment_id"] != road_segment_id:
            continue
        if other["status"] not in ("BID_SOLICITATION", "AWARDED"):
            continue
        other_start = parse_date(other["window_start_date"])
        other_end = parse_date(other["window_end_date"])
        if window_start < other_end and other_start < window_end:
            raise ApiError("ERR_WORK_WINDOW_CONFLICT",
                           "The work window intersects another non-terminal window on this segment.")

    for other in by_seq(list(db.projects.values())):
        if other["road_segment_id"] != road_segment_id:
            continue
        if other["category"] != "PAVING" or other["status"] not in ("AWARDED", "COMPLETE"):
            continue
        buffer_end = add_days(parse_date(other["window_end_date"]), C.PAVING_CURE_BUFFER_DAYS)
        if window_start < buffer_end:
            raise ApiError("ERR_PAVING_CURE_BUFFER_VIOLATION",
                           "The window starts inside the three-day paving cure buffer.")

    if not window_start < window_end:
        raise ApiError("ERR_INVALID_DATE_RANGE",
                       "window_start_date must fall strictly before window_end_date.")

    row = new_row({
        "road_segment_id": road_segment_id,
        "proposal_id": proposal_id,
        "awarded_bid_id": None,
        "category": category,
        "window_start_date": date_str(window_start),
        "window_end_date": date_str(window_end),
        "status": "BID_SOLICITATION",
        "awarded_amount_cents": 0,
        "reserve_draw_cents": 0,
        "created_by_user_id": actor_id(),
        "awarded_by_user_id": None,
        "completed_at": None,
        "actual_cost_cents": None,
        "cancellation_reason": None,
    })
    db.projects[row["id"]] = row
    return R.ok(row, 201)


@bp.get("/maintenance-projects/<project_id>")
@auth(*PROJECT_READERS)
def read_project(project_id):
    return R.ok(S.require("project", project_id))


@bp.get("/maintenance-projects")
@auth(*PROJECT_READERS)
def list_projects():
    limit, offset = V.pagination()
    road_segment_id = V.query_str("road_segment_id")
    proposal_id = V.query_str("proposal_id")
    awarded_bid_id = V.query_str("awarded_bid_id")
    status = V.query_enum("status", C.PROJECT_STATUSES)
    category = V.query_enum("category", C.PROJECT_CATEGORIES)

    rows = by_seq(list(db.projects.values()))
    if road_segment_id is not None:
        rows = [r for r in rows if r["road_segment_id"] == road_segment_id]
    if proposal_id is not None:
        rows = [r for r in rows if r["proposal_id"] == proposal_id]
    if awarded_bid_id is not None:
        rows = [r for r in rows if r["awarded_bid_id"] == awarded_bid_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if category is not None:
        rows = [r for r in rows if r["category"] == category]
    page, total = V.paginate(rows, limit, offset)
    return R.ok_list(page, limit, offset, total)


@bp.get("/maintenance-projects/<project_id>/contractor-bids")
@auth(*BID_READERS)
def list_project_bids(project_id):
    limit, offset = V.pagination()
    status = V.query_enum("status", C.BID_STATUSES)

    S.require("project", project_id)
    rows = S.bids_of_project(project_id)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = V.paginate(rows, limit, offset)
    return R.ok_list(page, limit, offset, total)


@bp.post("/maintenance-projects/<project_id>/contractor-bids")
@auth("Contractor")
def submit_bid(project_id):
    body = V.get_body()
    contractor_name = V.req_str(body, "contractor_name")
    amount_cents = V.req_int(body, "amount_cents", minimum=1)
    bond_on_file = V.req_bool(body, "bond_on_file")
    expected_version = V.req_int(body, "expected_project_version", minimum=0)

    project = S.require("project", project_id)

    if expected_version != project["version"]:
        raise ApiError("ERR_STALE_PROJECT_VERSION",
                       "expected_project_version does not match the project's current version.")
    if project["status"] != "BID_SOLICITATION":
        raise ApiError("ERR_PROJECT_NOT_IN_SOLICITATION",
                       "The project is not soliciting bids.")

    for prior in S.bids_of_project(project["id"]):
        if prior["contractor_user_id"] == actor_id() and prior["status"] == "SUBMITTED":
            prior["status"] = "SUPERSEDED"
            touch(prior)

    row = new_row({
        "project_id": project["id"],
        "contractor_name": contractor_name,
        "contractor_user_id": actor_id(),
        "amount_cents": amount_cents,
        "bond_on_file": bond_on_file,
        "status": "SUBMITTED",
        "submitted_at": now_iso(),
    })
    db.contractor_bids[row["id"]] = row

    touch(project)
    return R.ok(row, 201)


def responsive_candidates(project_id):
    candidates = [
        bid for bid in S.bids_of_project(project_id)
        if bid["status"] == "SUBMITTED" and bid["bond_on_file"] is True
    ]
    candidates.sort(key=lambda bid: (bid["amount_cents"], bid["_seq"]))
    return candidates


@bp.post("/maintenance-projects/<project_id>/award")
@auth("RoadCommissioner")
def award_project(project_id):
    body = V.get_body()
    bid_id = V.req_str(body, "bid_id")

    project = S.require("project", project_id)
    bid = S.require("bid", bid_id)

    if actor_id() == project["created_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "A project must be awarded by a different user than its creator.")
    if project["status"] != "BID_SOLICITATION":
        raise ApiError("ERR_PROJECT_NOT_IN_SOLICITATION",
                       "The project is not soliciting bids.")
    if bid["status"] != "SUBMITTED":
        raise ApiError("ERR_BID_NOT_ACTIVE", "Only a SUBMITTED bid may be awarded.")

    segment = db.road_segments.get(project["road_segment_id"])
    if project["category"] == "PAVING":
        if segment is None or segment["emergency_access_grade"] != "COMPLIANT":
            raise ApiError("ERR_EMERGENCY_ACCESS_DEFICIENT",
                           "A PAVING award requires a COMPLIANT segment.")
    if bid["bond_on_file"] is not True:
        raise ApiError("ERR_BOND_NOT_ON_FILE", "The bid carries no performance bond.")
    if bid["project_id"] != project["id"]:
        raise ApiError("ERR_BID_PROJECT_MISMATCH", "The bid belongs to a different project.")

    candidates = responsive_candidates(project["id"])
    if not candidates or candidates[0]["id"] != bid["id"]:
        raise ApiError("ERR_NOT_LOWEST_RESPONSIVE_BID",
                       "The nominated bid is not the lowest responsive bid.")
    if (bid["amount_cents"] >= C.COMPETITIVE_BID_THRESHOLD_CENTS
            and len(candidates) < C.MIN_RESPONSIVE_BIDS):
        raise ApiError("ERR_INSUFFICIENT_BIDS",
                       "A bid at or above one million cents requires three responsive bids.")

    association = S.association_of_project(project)
    proposal = db.proposals.get(project["proposal_id"]) if project["proposal_id"] else None
    funded = proposal is not None and proposal["status"] == "ADOPTED"

    if project["category"] in ("CULVERT", "BRIDGE"):
        posture = association["reserve_posture"] if association else "UNDERFUNDED"
        if posture == "UNDERFUNDED" and not funded:
            raise ApiError("ERR_RESERVE_UNDERFUNDED",
                           "An UNDERFUNDED reserve requires an ADOPTED funding proposal.")

    proposal_funding = proposal["approved_amount_cents"] if funded else 0
    draw = calc.project_reserve_draw(project["category"], bid["amount_cents"], proposal_funding)
    balance = association["reserve_balance_cents"] if association else 0
    if draw > balance:
        raise ApiError("ERR_INSUFFICIENT_RESERVE",
                       "The computed reserve draw exceeds the association's reserve balance.")

    for other in S.bids_of_project(project["id"]):
        if other["id"] != bid["id"] and other["status"] == "SUBMITTED":
            other["status"] = "REJECTED"
            touch(other)

    bid["status"] = "AWARDED"
    touch(bid)

    project["status"] = "AWARDED"
    project["awarded_bid_id"] = bid["id"]
    project["awarded_amount_cents"] = bid["amount_cents"]
    project["awarded_by_user_id"] = actor_id()
    project["reserve_draw_cents"] = draw
    touch(project)

    S.recompute_reserve(association)
    return R.ok(project)


@bp.post("/maintenance-projects/<project_id>/complete")
@auth("RoadCommissioner")
def complete_project(project_id):
    body = V.get_body()
    completed_at = V.req_dt(body, "completed_at")
    actual_cost_cents = V.req_int(body, "actual_cost_cents", minimum=0)

    project = S.require("project", project_id)
    if project["status"] != "AWARDED":
        raise ApiError("ERR_PROJECT_NOT_AWARDED", "Only an AWARDED project may be completed.")

    window_start = parse_date(project["window_start_date"])
    if completed_at.date() < window_start:
        raise ApiError("ERR_INVALID_DATE_RANGE",
                       "completed_at may not precede the project's window_start_date.")

    project["status"] = "COMPLETE"
    project["completed_at"] = iso(completed_at)
    project["actual_cost_cents"] = actual_cost_cents
    touch(project)

    if project["category"] == "PAVING":
        segment = db.road_segments.get(project["road_segment_id"])
        if segment is not None:
            segment["surface_type"] = "PAVED"
            segment["emergency_access_grade"] = "UNKNOWN"
            touch(segment)
    return R.ok(project)


@bp.post("/maintenance-projects/<project_id>/cancel")
@auth("RoadCommissioner")
def cancel_project_endpoint(project_id):
    body = V.get_body()
    cancellation_reason = V.req_str(body, "cancellation_reason")

    project = S.require("project", project_id)
    if project["status"] not in ("BID_SOLICITATION", "AWARDED"):
        raise ApiError("ERR_PROJECT_NOT_IN_SOLICITATION",
                       "Only a soliciting or awarded project may be cancelled.")

    S.cancel_project(project, cancellation_reason)
    S.recompute_reserve(S.association_of_project(project))
    return R.ok(project)
