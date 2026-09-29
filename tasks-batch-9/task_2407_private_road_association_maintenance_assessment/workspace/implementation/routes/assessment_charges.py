"""Charge reads and payment posting (PRD 3.6)."""

from flask import Blueprint

import response as R
import validation as V
from db import by_seq, db, touch
from errors import ApiError
from middleware import actor_role, actor_id, auth
from services import constants as C
from services import state as S

bp = Blueprint("assessment_charges", __name__)

READERS = ("AssociationSecretary", "AssessmentClerk", "BoardTreasurer", "MemberOwner")


@bp.get("/assessment-charges/<charge_id>")
@auth(*READERS)
def read_charge(charge_id):
    return R.ok(S.require("charge", charge_id))


@bp.get("/assessment-charges")
@auth(*READERS)
def list_charges():
    limit, offset = V.pagination()
    roll_id = V.query_str("roll_id")
    proposal_id = V.query_str("proposal_id")
    parcel_id = V.query_str("parcel_id")
    member_id = V.query_str("member_id")
    charge_type = V.query_enum("charge_type", C.CHARGE_TYPES)
    status = V.query_enum("status", C.CHARGE_STATUSES)

    rows = by_seq(list(db.assessment_charges.values()))
    if roll_id is not None:
        rows = [r for r in rows if r["roll_id"] == roll_id]
    if proposal_id is not None:
        rows = [r for r in rows if r["proposal_id"] == proposal_id]
    if parcel_id is not None:
        rows = [r for r in rows if r["parcel_id"] == parcel_id]
    if member_id is not None:
        rows = [r for r in rows if r["member_id"] == member_id]
    if charge_type is not None:
        rows = [r for r in rows if r["charge_type"] == charge_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = V.paginate(rows, limit, offset)
    return R.ok_list(page, limit, offset, total)


@bp.post("/assessment-charges/<charge_id>/payments")
@auth("MemberOwner", "AssessmentClerk")
def post_payment(charge_id):
    body = V.get_body()
    amount = V.req_int(body, "amount_cents", minimum=0)

    charge = S.require("charge", charge_id)

    if actor_role() == "MemberOwner" and charge["member_id"] != actor_id():
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "This charge belongs to another membership.")

    if (charge["status"] not in ("OPEN", "DELINQUENT", "LIEN_ENCUMBERED")
            or charge["balance_cents"] <= 0):
        raise ApiError("ERR_CHARGE_NOT_COLLECTIBLE", "The charge is not collectible.")

    if amount > charge["balance_cents"]:
        raise ApiError("ERR_OVERPAYMENT", "The payment exceeds the charge's remaining balance.")

    charge["paid_cents"] = charge["paid_cents"] + amount
    charge["balance_cents"] = charge["amount_cents"] - charge["paid_cents"]
    cleared = charge["balance_cents"] == 0
    if cleared:
        charge["status"] = "PAID"
    touch(charge)

    if cleared:
        affected = S.release_effective_actions_for_charge(charge)
        affected.append(charge["member_id"])
        S.reconcile_members(affected)
    return R.ok(charge)


@bp.get("/assessment-charges/<charge_id>/delinquency-actions")
@auth(*READERS)
def list_charge_actions(charge_id):
    limit, offset = V.pagination()
    status = V.query_enum("status", C.ACTION_STATUSES)

    S.require("charge", charge_id)
    rows = S.actions_of_charge(charge_id)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = V.paginate(rows, limit, offset)
    return R.ok_list(page, limit, offset, total)
