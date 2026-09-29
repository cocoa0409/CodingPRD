"""Delinquency remedies: initiation, effectuation and release (PRD 3.6)."""

from flask import Blueprint

import response as R
import validation as V
from db import (add_days, by_seq, clock_date, date_str, db, day_diff, new_row,
                now_iso, parse_date, touch)
from errors import ApiError
from middleware import actor_id, auth
from services import calc
from services import constants as C
from services import state as S

bp = Blueprint("delinquency_actions", __name__)

READERS = ("AssociationSecretary", "AssessmentClerk", "BoardTreasurer", "MemberOwner")


@bp.post("/assessment-charges/<charge_id>/delinquency-actions")
@auth("BoardTreasurer")
def initiate_action(charge_id):
    body = V.get_body()
    action_type = V.req_enum(body, "action_type", C.ACTION_TYPES)
    start_supplied = "restriction_start_date" in body and body["restriction_start_date"] is not None
    end_supplied = "restriction_end_date" in body and body["restriction_end_date"] is not None
    start_date = V.opt_date(body, "restriction_start_date")
    end_date = V.opt_date(body, "restriction_end_date")

    charge = S.require("charge", charge_id)

    if (charge["status"] not in ("OPEN", "DELINQUENT", "LIEN_ENCUMBERED")
            or charge["balance_cents"] <= 0):
        raise ApiError("ERR_CHARGE_NOT_COLLECTIBLE", "The charge is not collectible.")

    due = parse_date(charge["due_date"]) if charge["due_date"] else None
    if due is None or clock_date() < add_days(due, C.GRACE_DAYS):
        raise ApiError("ERR_CHARGE_NOT_YET_DELINQUENT",
                       "The charge has not reached its due date plus the thirty grace days.")

    restriction_days = 0
    if action_type == "ACCESS_RESTRICTION":
        if not start_supplied or not end_supplied:
            raise ApiError("ERR_INVALID_DATE_RANGE",
                           "An ACCESS_RESTRICTION requires restriction_start_date and restriction_end_date.")
        if not start_date < end_date:
            raise ApiError("ERR_INVALID_DATE_RANGE",
                           "restriction_start_date must fall strictly before restriction_end_date.")
        roll = db.assessment_rolls.get(charge["roll_id"])
        if roll is not None:
            fy_start = parse_date(roll["fy_start_date"])
            fy_end = parse_date(roll["fy_end_date"])
            if start_date < fy_start or end_date > fy_end:
                raise ApiError("ERR_INVALID_DATE_RANGE",
                               "The restriction interval must lie inside the charge's fiscal interval.")
        restriction_days = day_diff(end_date, start_date)

    row = new_row({
        "charge_id": charge["id"],
        "member_id": charge["member_id"],
        "action_type": action_type,
        "status": "INITIATED",
        "lien_amount_cents": 0,
        "payoff_amount_cents": 0,
        "restriction_start_date": date_str(start_date) if action_type == "ACCESS_RESTRICTION" else None,
        "restriction_end_date": date_str(end_date) if action_type == "ACCESS_RESTRICTION" else None,
        "restriction_days": restriction_days,
        "initiated_by_user_id": actor_id(),
        "effectuated_by_user_id": None,
        "effective_at": None,
        "released_at": None,
        "release_reason": None,
    })
    db.delinquency_actions[row["id"]] = row

    if charge["status"] == "OPEN":
        charge["status"] = "DELINQUENT"
        charge["delinquent_since"] = date_str(clock_date())
        touch(charge)

    S.reconcile_members([charge["member_id"]])
    return R.ok(row, 201)


@bp.get("/delinquency-actions")
@auth(*READERS)
def list_actions():
    limit, offset = V.pagination()
    charge_id = V.query_str("charge_id")
    member_id = V.query_str("member_id")
    action_type = V.query_enum("action_type", C.ACTION_TYPES)
    status = V.query_enum("status", C.ACTION_STATUSES)

    rows = by_seq(list(db.delinquency_actions.values()))
    if charge_id is not None:
        rows = [r for r in rows if r["charge_id"] == charge_id]
    if member_id is not None:
        rows = [r for r in rows if r["member_id"] == member_id]
    if action_type is not None:
        rows = [r for r in rows if r["action_type"] == action_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = V.paginate(rows, limit, offset)
    return R.ok_list(page, limit, offset, total)


@bp.get("/delinquency-actions/<action_id>")
@auth(*READERS)
def read_action(action_id):
    return R.ok(S.require("action", action_id))


@bp.post("/delinquency-actions/<action_id>/effectuate")
@auth("BoardTreasurer")
def effectuate_action(action_id):
    action = S.require("action", action_id)

    if actor_id() == action["initiated_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "A remedy must be effectuated by a different user than the initiator.")

    charge = db.assessment_charges.get(action["charge_id"])
    if (charge is None or charge["status"] not in ("OPEN", "DELINQUENT", "LIEN_ENCUMBERED")
            or charge["balance_cents"] <= 0):
        raise ApiError("ERR_CHARGE_NOT_COLLECTIBLE", "The charge is not collectible.")

    if action["status"] != "INITIATED":
        raise ApiError("ERR_ACTION_NOT_INITIATED", "Only an INITIATED remedy may be effectuated.")

    member = db.members.get(action["member_id"])

    if action["action_type"] == "ACCESS_RESTRICTION":
        segment = S.segment_of_charge(charge)
        if segment is None or segment["emergency_access_grade"] != "COMPLIANT":
            raise ApiError("ERR_EMERGENCY_ACCESS_DEFICIENT",
                           "The segment must be COMPLIANT before a gate may be closed.")
        fiscal_year = S.fiscal_year_of_charge(charge)
        used = S.restricted_days_in_fiscal_year(action["member_id"], fiscal_year)
        if used + action["restriction_days"] > C.MAX_RESTRICTION_DAYS_PER_FY:
            raise ApiError("ERR_RESTRICTION_DAYS_EXCEEDED",
                           "The remedy would exceed forty-five restriction days in the fiscal year.")
        if charge["balance_cents"] < C.RESTRICTION_MINIMUM_BALANCE_CENTS:
            raise ApiError("ERR_BALANCE_BELOW_RESTRICTION_MINIMUM",
                           "The arrears is below the fifty-thousand-cent restriction minimum.")

    association = S.association_of_charge(charge)
    basis = association["delinquency_interest_basis"] if association else "STATUTORY"

    action["status"] = "EFFECTIVE"
    action["effective_at"] = now_iso()
    action["effectuated_by_user_id"] = actor_id()
    if action["action_type"] in ("LIEN_FILING", "ACCESS_RESTRICTION"):
        principal = charge["balance_cents"]
        due = parse_date(charge["due_date"]) if charge["due_date"] else None
        days = day_diff(clock_date(), due) if due is not None else 0
        action["lien_amount_cents"] = principal
        action["payoff_amount_cents"] = calc.lien_payoff(principal, days, basis)
    touch(action)

    if action["action_type"] in ("LIEN_FILING", "ACCESS_RESTRICTION"):
        if charge["status"] == "DELINQUENT":
            charge["status"] = "LIEN_ENCUMBERED"
            touch(charge)

    if member is not None:
        S.reconcile_member(member)
        if member["standing_status"] == "LIEN_FILED":
            S.void_ballots_for_lien(member)
    return R.ok(action)


@bp.post("/delinquency-actions/<action_id>/release")
@auth("BoardTreasurer")
def release_action(action_id):
    body = V.get_body()
    release_reason = V.req_str(body, "release_reason")

    action = S.require("action", action_id)
    if action["status"] not in ("INITIATED", "EFFECTIVE"):
        raise ApiError("ERR_ACTION_ALREADY_CLOSED", "The remedy is already closed.")

    charge = db.assessment_charges.get(action["charge_id"])
    was_effective = action["status"] == "EFFECTIVE"

    action["status"] = "RELEASED" if was_effective else "VOIDED"
    action["released_at"] = now_iso()
    action["release_reason"] = release_reason
    action["lien_amount_cents"] = 0
    touch(action)

    if was_effective and charge is not None and charge["status"] == "LIEN_ENCUMBERED":
        remaining = [
            other for other in S.actions_of_charge(charge["id"])
            if other["status"] == "EFFECTIVE"
            and other["action_type"] in ("LIEN_FILING", "ACCESS_RESTRICTION")
        ]
        if not remaining:
            charge["status"] = "PAID" if charge["balance_cents"] == 0 else "DELINQUENT"
            touch(charge)

    member = db.members.get(action["member_id"])
    if member is not None:
        S.reconcile_member(member)
    return R.ok(action)
