"""New-lot connections and easement disputes (PRD 3.8)."""

from flask import Blueprint

import response as R
import validation as V
from db import add_days, by_seq, clock_date, date_str, db, new_row, now_iso, touch
from errors import ApiError
from middleware import actor_id, actor_role, auth
from services import calc
from services import constants as C
from services import state as S

bp = Blueprint("connection_requests", __name__)

READERS = ("AssociationSecretary", "AssessmentClerk", "BoardTreasurer", "MemberOwner")


def _parent_member(parcel):
    if not parcel.get("parent_parcel_id"):
        return None
    member = S.member_for_parcel(parcel["parent_parcel_id"])
    if member is None or member["standing_status"] == "PENDING_DEED_VERIFICATION":
        return None
    return member


def _require_parent_member(parcel):
    if parcel["covenant_recorded"] is not False or not parcel.get("parent_parcel_id"):
        raise ApiError("ERR_PARENT_MEMBER_NOT_FOUND",
                       "The lot has no subdivision parent to bill the connection fee to.")
    member = _parent_member(parcel)
    if member is None:
        raise ApiError("ERR_PARENT_MEMBER_NOT_FOUND",
                       "The parent parcel carries no verified member to bill.")
    return member


@bp.post("/connection-requests")
@auth("MemberOwner", "AssociationSecretary")
def file_request():
    body = V.get_body()
    parcel_id = V.req_str(body, "parcel_id")
    usage_class = V.req_enum(body, "requested_usage_class", C.USAGE_CLASSES)
    trips_per_day = V.req_num(body, "requested_trips_per_day", minimum=0)
    easement = V.req_bool(body, "easement_grant_recorded")

    parcel = S.require("parcel", parcel_id)

    if actor_role() == "MemberOwner":
        parent = _parent_member(parcel)
        if parent is not None and parent["id"] != actor_id():
            raise ApiError("ERR_NOT_RESOURCE_OWNER",
                           "Only the parent parcel's member may file this request.")

    if parcel["status"] != "PENDING_CONNECTION":
        raise ApiError("ERR_PARCEL_NOT_ACTIVE",
                       "Only a PENDING_CONNECTION lot may file a connection request.")

    _require_parent_member(parcel)

    row = new_row({
        "parcel_id": parcel_id,
        "requested_usage_class": usage_class,
        "requested_trips_per_day": trips_per_day,
        "easement_grant_recorded": easement,
        "status": "SUBMITTED",
        "connection_fee_cents": 0,
        "reserve_buyin_cents": 0,
        "dispute_reason": None,
        "resolution_note": None,
        "decided_at": None,
        "decided_by_user_id": None,
    })
    db.connection_requests[row["id"]] = row
    return R.ok(row, 201)


@bp.get("/connection-requests/<request_id>")
@auth(*READERS)
def read_request(request_id):
    return R.ok(S.require("request", request_id))


@bp.get("/connection-requests")
@auth(*READERS)
def list_requests():
    limit, offset = V.pagination()
    parcel_id = V.query_str("parcel_id")
    status = V.query_enum("status", C.REQUEST_STATUSES)

    rows = by_seq(list(db.connection_requests.values()))
    if parcel_id is not None:
        rows = [r for r in rows if r["parcel_id"] == parcel_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = V.paginate(rows, limit, offset)
    return R.ok_list(page, limit, offset, total)


@bp.get("/parcels/<parcel_id>/connection-requests")
@auth(*READERS)
def list_parcel_requests(parcel_id):
    limit, offset = V.pagination()
    status = V.query_enum("status", C.REQUEST_STATUSES)

    S.require("parcel", parcel_id)
    rows = [r for r in by_seq(list(db.connection_requests.values()))
            if r["parcel_id"] == parcel_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = V.paginate(rows, limit, offset)
    return R.ok_list(page, limit, offset, total)


@bp.post("/connection-requests/<request_id>/decide")
@auth("AssociationSecretary")
def decide_request(request_id):
    body = V.get_body()
    outcome = V.req_enum(body, "outcome", C.DECISION_OUTCOMES)
    dispute_reason = V.opt_str(body, "dispute_reason")
    if outcome == "DISPUTED" and dispute_reason is None:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field 'dispute_reason' is required when deferring into a dispute.")

    request_row = S.require("request", request_id)
    parcel = db.parcels.get(request_row["parcel_id"])

    if parcel is None or parcel["status"] != "PENDING_CONNECTION":
        raise ApiError("ERR_PARCEL_NOT_ACTIVE",
                       "The lot is no longer PENDING_CONNECTION.")

    allowed = ("SUBMITTED", "DISPUTED") if outcome == "DENIED" else ("SUBMITTED",)
    if request_row["status"] not in allowed:
        raise ApiError("ERR_REQUEST_NOT_PENDING",
                       "The connection request is not open to this decision.")

    segment = db.road_segments.get(parcel["road_segment_id"])
    if outcome == "APPROVED":
        if segment is None or segment["emergency_access_grade"] == "DEFICIENT":
            raise ApiError("ERR_EMERGENCY_ACCESS_DEFICIENT",
                           "The lot's segment fails the emergency-vehicle access standard.")

    parent_member = _require_parent_member(parcel)

    if outcome == "DISPUTED":
        request_row["status"] = "DISPUTED"
        request_row["dispute_reason"] = dispute_reason
        touch(request_row)
        return R.ok(request_row)

    if outcome == "DENIED":
        request_row["status"] = "DENIED"
        request_row["decided_at"] = now_iso()
        request_row["decided_by_user_id"] = actor_id()
        touch(request_row)
        parcel["status"] = "WITHDRAWN"
        touch(parcel)
        return R.ok(request_row)

    if request_row["easement_grant_recorded"] is not True:
        raise ApiError("ERR_EASEMENT_NOT_RECORDED",
                       "The access easement is not recorded for this lot.")

    association = S.association_of_segment(segment) if segment else None
    roll = S.latest_levied_roll(association["id"]) if association else None
    if roll is None:
        raise ApiError("ERR_ROLL_NOT_FOUND",
                       "The association has no LEVIED roll to carry the connection fee.")

    deficit = max(0, association["reserve_target_cents"] - association["reserve_balance_cents"])
    total_units = S.association_frontage_units(association["id"])
    fee, buyin = calc.connection_fee(
        parcel["frontage_feet"],
        request_row["requested_usage_class"],
        request_row["requested_trips_per_day"],
        deficit,
        total_units,
    )

    request_row["status"] = "APPROVED"
    request_row["connection_fee_cents"] = fee
    request_row["reserve_buyin_cents"] = buyin
    request_row["decided_at"] = now_iso()
    request_row["decided_by_user_id"] = actor_id()
    touch(request_row)

    parcel["status"] = "ACTIVE"
    parcel["covenant_recorded"] = True
    parcel["usage_class"] = request_row["requested_usage_class"]
    parcel["trips_per_day"] = request_row["requested_trips_per_day"]
    calc.parcel_units(parcel)
    touch(parcel)

    S.create_charge(
        roll_id=roll["id"],
        parcel_id=parcel["id"],
        member_id=parent_member["id"],
        charge_type="CONNECTION_FEE",
        share_units=parcel["frontage_share_units"],
        amount_cents=fee,
        status="OPEN",
        due_date=date_str(add_days(clock_date(), C.NET_DAYS)),
    )

    S.recompute_reserve(association)
    S.reconcile_members([parent_member["id"]])
    return R.ok(request_row)


@bp.post("/connection-requests/<request_id>/resolve-dispute")
@auth("AssociationSecretary")
def resolve_dispute(request_id):
    body = V.get_body()
    easement = V.req_bool(body, "easement_grant_recorded")
    resolution_note = V.req_str(body, "resolution_note")

    request_row = S.require("request", request_id)
    if request_row["status"] != "DISPUTED":
        raise ApiError("ERR_REQUEST_NOT_PENDING",
                       "Only a DISPUTED request may have its dispute resolved.")

    request_row["status"] = "SUBMITTED"
    request_row["easement_grant_recorded"] = easement
    request_row["resolution_note"] = resolution_note
    request_row["dispute_reason"] = None
    touch(request_row)
    return R.ok(request_row)
