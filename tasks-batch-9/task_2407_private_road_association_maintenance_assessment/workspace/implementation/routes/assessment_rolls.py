"""The annual assessment roll: draft, certify, recall, levy (PRD 3.4)."""

from fractions import Fraction

from flask import Blueprint

import response as R
import validation as V
from db import (add_days, clock_date, date_str, db, new_row, now_iso,
                parse_date, touch)
from errors import ApiError
from middleware import READ_ALL, auth
from services import calc
from services import constants as C
from services import state as S

bp = Blueprint("assessment_rolls", __name__)


@bp.post("/assessment-rolls")
@auth("AssessmentClerk")
def create_roll():
    body = V.get_body()
    association_id = V.req_str(body, "association_id")
    fiscal_year = V.req_int(body, "fiscal_year", minimum=2020, maximum=2100)
    fy_start = V.req_date(body, "fy_start_date")
    fy_end = V.req_date(body, "fy_end_date")
    budget = V.req_int(body, "budget_requirement_cents", minimum=1)
    method_variant = V.req_enum(body, "method_variant", C.METHOD_VARIANTS)

    S.require("association", association_id)

    existing = S.rolls_of(association_id)
    for roll in existing:
        if int(roll["fiscal_year"]) == fiscal_year:
            raise ApiError("ERR_FISCAL_YEAR_ROLL_EXISTS",
                           "The association already carries a roll for fiscal year %d." % fiscal_year)
    for roll in existing:
        other_start = parse_date(roll["fy_start_date"])
        other_end = parse_date(roll["fy_end_date"])
        if fy_start <= other_end and other_start <= fy_end:
            raise ApiError("ERR_FISCAL_INTERVAL_OVERLAP",
                           "The fiscal interval overlaps an existing roll of this association.")

    if not fy_start < fy_end:
        raise ApiError("ERR_INVALID_DATE_RANGE",
                       "fy_start_date must fall strictly before fy_end_date.")

    row = new_row({
        "association_id": association_id,
        "fiscal_year": fiscal_year,
        "fy_start_date": date_str(fy_start),
        "fy_end_date": date_str(fy_end),
        "budget_requirement_cents": budget,
        "method_variant": method_variant,
        "status": "DRAFT",
        "total_share_units": Fraction(0),
        "total_levied_cents": 0,
        "unallocated_residual_cents": 0,
        "reserve_contribution_cents": 0,
        "recall_count": 0,
        "certified_at": None,
        "levied_at": None,
        "due_date": None,
    })
    db.assessment_rolls[row["id"]] = row
    return R.ok(row, 201)


@bp.get("/assessment-rolls/<roll_id>")
@auth(*READ_ALL)
def read_roll(roll_id):
    return R.ok(S.require("roll", roll_id))


@bp.get("/assessment-rolls")
@auth(*READ_ALL)
def list_rolls():
    limit, offset = V.pagination()
    association_id = V.query_str("association_id")
    fiscal_year = V.query_int("fiscal_year")
    status = V.query_enum("status", C.ROLL_STATUSES)

    rows = list(db.assessment_rolls.values())
    if association_id is not None:
        rows = [r for r in rows if r["association_id"] == association_id]
    if fiscal_year is not None:
        rows = [r for r in rows if int(r["fiscal_year"]) == fiscal_year]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    # the single ordering exception: fiscal_year ASC, then created_at ASC
    rows.sort(key=lambda r: (int(r["fiscal_year"]), r["_seq"]))
    page, total = V.paginate(rows, limit, offset)
    return R.ok_list(page, limit, offset, total)


def _allocation_for(roll, variant):
    pairs = S.assessable_parcels(roll["association_id"])
    units = [S.units_for_variant(parcel, variant) for parcel, _ in pairs]
    amounts, total_units, total_levied, residual = calc.allocate(
        roll["budget_requirement_cents"], units)
    if amounts is None:
        return pairs, units, None, Fraction(0), 0, roll["budget_requirement_cents"]
    return pairs, units, amounts, total_units, total_levied, residual


@bp.get("/assessment-rolls/<roll_id>/method-comparison")
@auth("AssociationSecretary", "AssessmentClerk", "BoardTreasurer")
def method_comparison(roll_id):
    roll = S.require("roll", roll_id)

    _, _, frontage_amounts, _, frontage_total, frontage_residual = _allocation_for(
        roll, "FRONTAGE_WEIGHTED")
    _, _, trip_amounts, _, trip_total, trip_residual = _allocation_for(
        roll, "TRIP_GENERATION_WEIGHTED")

    divergent = 0
    max_divergence = 0
    if frontage_amounts is not None and trip_amounts is not None:
        for left, right in zip(frontage_amounts, trip_amounts):
            difference = abs(left - right)
            if difference != 0:
                divergent += 1
            if difference > max_divergence:
                max_divergence = difference

    return R.ok({
        "roll_id": roll["id"],
        "method_variant": roll["method_variant"],
        "frontage_weighted_total_cents": frontage_total,
        "trip_generation_weighted_total_cents": trip_total,
        "frontage_weighted_unallocated_residual_cents": frontage_residual,
        "trip_generation_weighted_unallocated_residual_cents": trip_residual,
        "divergent_parcel_count": divergent,
        "max_absolute_divergence_cents": max_divergence,
    })


@bp.post("/assessment-rolls/<roll_id>/certify")
@auth("AssessmentClerk")
def certify_roll(roll_id):
    roll = S.require("roll", roll_id)

    if roll["status"] != "DRAFT":
        raise ApiError("ERR_ROLL_NOT_DRAFT", "Only a DRAFT roll may be certified.")
    if not S.membership_roll_complete(roll["association_id"]):
        raise ApiError("ERR_MEMBERSHIP_ROLL_INCOMPLETE",
                       "Every ACTIVE covenant-recorded parcel must carry a verified member.")

    pairs, units, amounts, total_units, total_levied, residual = _allocation_for(
        roll, roll["method_variant"])
    if amounts is None:
        raise ApiError("ERR_NO_ASSESSABLE_PARCELS",
                       "The assessable parcel set is empty; total_share_units would be zero.")

    for index, (parcel, member) in enumerate(pairs):
        S.create_charge(
            roll_id=roll["id"],
            parcel_id=parcel["id"],
            member_id=member["id"],
            charge_type="ANNUAL",
            share_units=units[index],
            amount_cents=amounts[index],
            status="PENDING",
            due_date=None,
        )

    roll["total_share_units"] = total_units
    roll["total_levied_cents"] = total_levied
    roll["unallocated_residual_cents"] = residual
    roll["certified_at"] = now_iso()
    roll["status"] = "CERTIFIED"
    touch(roll)
    return R.ok(roll)


@bp.post("/assessment-rolls/<roll_id>/recall")
@auth("AssessmentClerk")
def recall_roll(roll_id):
    body = V.get_body()
    V.req_str(body, "recall_reason")

    roll = S.require("roll", roll_id)
    if roll["status"] != "CERTIFIED":
        raise ApiError("ERR_ROLL_NOT_CERTIFIED", "Only a CERTIFIED roll may be recalled.")

    affected = []
    for charge in db.assessment_charges.values():
        if charge["roll_id"] != roll["id"]:
            continue
        if charge["charge_type"] != "ANNUAL" or charge["status"] != "PENDING":
            continue
        charge["status"] = "VOIDED"
        touch(charge)
        affected.append(charge["member_id"])

    roll["total_levied_cents"] = 0
    roll["total_share_units"] = Fraction(0)
    roll["unallocated_residual_cents"] = 0
    roll["certified_at"] = None
    roll["recall_count"] = int(roll["recall_count"]) + 1
    roll["status"] = "DRAFT"
    touch(roll)

    S.reconcile_members(affected)
    return R.ok(roll)


@bp.post("/assessment-rolls/<roll_id>/levy")
@auth("BoardTreasurer")
def levy_roll(roll_id):
    roll = S.require("roll", roll_id)
    if roll["status"] != "CERTIFIED":
        raise ApiError("ERR_ROLL_NOT_CERTIFIED", "Only a CERTIFIED roll may be levied.")

    due = date_str(add_days(clock_date(), C.NET_DAYS))
    affected = []
    for charge in db.assessment_charges.values():
        if charge["roll_id"] != roll["id"]:
            continue
        if charge["charge_type"] != "ANNUAL" or charge["status"] != "PENDING":
            continue
        charge["status"] = "OPEN"
        charge["due_date"] = due
        touch(charge)
        affected.append(charge["member_id"])

    roll["levied_at"] = now_iso()
    roll["due_date"] = due
    roll["reserve_contribution_cents"] = calc.round_half_up(
        Fraction(roll["budget_requirement_cents"]) * C.RESERVE_CONTRIBUTION_PCT)
    roll["status"] = "LEVIED"
    touch(roll)

    S.recompute_reserve(db.associations.get(roll["association_id"]))
    S.reconcile_members(affected)
    return R.ok(roll)
