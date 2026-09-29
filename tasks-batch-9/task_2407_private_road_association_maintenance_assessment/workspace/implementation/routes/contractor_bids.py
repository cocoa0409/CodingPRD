"""Bid reads and withdrawal, including the award reversion (PRD 3.7)."""

from flask import Blueprint

import response as R
import validation as V
from db import by_seq, db, touch
from errors import ApiError
from middleware import actor_id, auth
from services import constants as C
from services import state as S

bp = Blueprint("contractor_bids", __name__)

READERS = ("AssociationSecretary", "BoardTreasurer", "RoadCommissioner", "Contractor")


@bp.get("/contractor-bids/<bid_id>")
@auth(*READERS)
def read_bid(bid_id):
    return R.ok(S.require("bid", bid_id))


@bp.get("/contractor-bids")
@auth(*READERS)
def list_bids():
    limit, offset = V.pagination()
    project_id = V.query_str("project_id")
    status = V.query_enum("status", C.BID_STATUSES)

    rows = by_seq(list(db.contractor_bids.values()))
    if project_id is not None:
        rows = [r for r in rows if r["project_id"] == project_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = V.paginate(rows, limit, offset)
    return R.ok_list(page, limit, offset, total)


@bp.post("/contractor-bids/<bid_id>/withdraw")
@auth("Contractor")
def withdraw_bid(bid_id):
    body = V.get_body()
    V.req_str(body, "withdrawal_reason")

    bid = S.require("bid", bid_id)

    if bid["contractor_user_id"] != actor_id():
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "A firm may only withdraw its own bid.")
    if bid["status"] not in ("SUBMITTED", "AWARDED"):
        raise ApiError("ERR_BID_NOT_ACTIVE", "Only a SUBMITTED or AWARDED bid may be withdrawn.")

    was_awarded = bid["status"] == "AWARDED"
    bid["status"] = "WITHDRAWN"
    touch(bid)

    project = db.projects.get(bid["project_id"])
    if was_awarded and project is not None and project["awarded_bid_id"] == bid["id"]:
        S.revert_award(project)
        S.recompute_reserve(S.association_of_project(project))
    return R.ok(bid)
