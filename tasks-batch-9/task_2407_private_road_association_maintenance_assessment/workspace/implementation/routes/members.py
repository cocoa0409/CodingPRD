"""The membership roll and deed verification (PRD 3.3)."""

from flask import Blueprint

import response as R
import validation as V
from db import by_seq, date_str, db, new_row, now_iso, touch
from errors import ApiError
from middleware import READ_ALL, auth
from services import constants as C
from services import state as S

bp = Blueprint("members", __name__)


@bp.post("/members")
@auth("AssociationSecretary")
def create_member():
    body = V.get_body()
    parcel_id = V.req_str(body, "parcel_id")
    owner_name = V.req_str(body, "owner_name")
    deed_book_page = V.req_str(body, "deed_book_page")
    deed_recorded_date = V.req_date(body, "deed_recorded_date")

    parcel = S.require("parcel", parcel_id)

    if S.member_for_parcel(parcel_id) is not None:
        raise ApiError("ERR_DUPLICATE_MEMBER_FOR_PARCEL",
                       "The parcel already carries a membership.")
    if parcel["covenant_recorded"] is not True:
        raise ApiError("ERR_COVENANT_NOT_RECORDED",
                       "The road-maintenance covenant is not recorded against this parcel.")

    row = new_row({
        "parcel_id": parcel_id,
        "owner_name": owner_name,
        "deed_book_page": deed_book_page,
        "deed_recorded_date": date_str(deed_recorded_date),
        "standing_status": "PENDING_DEED_VERIFICATION",
        "access_status": "UNRESTRICTED",
        "deed_verified_at": None,
        "encumbered_principal_cents": 0,
        "restricted_days_used": 0,
    })
    db.members[row["id"]] = row
    return R.ok(row, 201)


@bp.get("/members/<member_id>")
@auth(*READ_ALL)
def read_member(member_id):
    return R.ok(S.require("member", member_id))


@bp.get("/members")
@auth(*READ_ALL)
def list_members():
    limit, offset = V.pagination()
    parcel_id = V.query_str("parcel_id")
    standing = V.query_enum("standing_status", C.STANDING_STATUSES)
    access = V.query_enum("access_status", C.ACCESS_STATUSES)

    rows = by_seq(list(db.members.values()))
    if parcel_id is not None:
        rows = [r for r in rows if r["parcel_id"] == parcel_id]
    if standing is not None:
        rows = [r for r in rows if r["standing_status"] == standing]
    if access is not None:
        rows = [r for r in rows if r["access_status"] == access]
    page, total = V.paginate(rows, limit, offset)
    return R.ok_list(page, limit, offset, total)


@bp.post("/members/<member_id>/verify-deed")
@auth("AssociationSecretary")
def verify_deed(member_id):
    body = V.get_body()
    verified = V.req_str(body, "verified_deed_book_page")

    member = S.require("member", member_id)

    if member["standing_status"] != "PENDING_DEED_VERIFICATION":
        raise ApiError("ERR_MEMBER_ALREADY_VERIFIED", "This member's deed is already verified.")

    parcel = db.parcels.get(member["parcel_id"])
    parcel_deed = parcel["deed_book_page"] if parcel else None
    if verified != member["deed_book_page"] or verified != parcel_deed:
        raise ApiError("ERR_DEED_MISMATCH",
                       "verified_deed_book_page must equal both the member's and the parcel's deed.")

    member["standing_status"] = "GOOD_STANDING"
    member["deed_verified_at"] = now_iso()
    touch(member)
    return R.ok(member)


@bp.get("/members/<member_id>/ballots")
@auth("AssociationSecretary", "BoardTreasurer", "MemberOwner")
def list_member_ballots(member_id):
    limit, offset = V.pagination()
    status = V.query_enum("status", C.BALLOT_STATUSES)

    S.require("member", member_id)
    rows = [b for b in by_seq(list(db.ballots.values())) if b["member_id"] == member_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = V.paginate(rows, limit, offset)
    return R.ok_list(page, limit, offset, total)


@bp.get("/members/<member_id>/delinquency-actions")
@auth("AssociationSecretary", "AssessmentClerk", "BoardTreasurer", "MemberOwner")
def list_member_actions(member_id):
    limit, offset = V.pagination()
    status = V.query_enum("status", C.ACTION_STATUSES)
    action_type = V.query_enum("action_type", C.ACTION_TYPES)

    S.require("member", member_id)
    rows = S.actions_of_member(member_id)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if action_type is not None:
        rows = [r for r in rows if r["action_type"] == action_type]
    page, total = V.paginate(rows, limit, offset)
    return R.ok_list(page, limit, offset, total)
