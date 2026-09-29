"""Valuation endpoints (PRD 3.3)."""

from flask import Blueprint

import calc
import responses
import services
import validation as v
from auth import APPRAISER, READ_ROLES, TRUSTEE, caller_id, endpoint
from db import DB, insert, serialize, sorted_rows, touch
from errors import fail

bp = Blueprint("valuations", __name__)

OPEN_STATUSES = ("SUBMITTED", "CHALLENGED")


def _price_inputs(body, required=True):
    return {
        "enterprise_value_cents": v.req_integer(body, "enterprise_value_cents",
                                                required=required, minimum=0),
        "debt_outstanding_cents": v.req_integer(body, "debt_outstanding_cents",
                                                required=required, minimum=0),
        "non_operating_assets_cents": v.req_integer(body, "non_operating_assets_cents",
                                                    required=required, minimum=0),
        "control_premium_bps": v.req_integer(body, "control_premium_bps",
                                             required=required, minimum=0, maximum=10000),
        "marketability_discount_bps": v.req_integer(body, "marketability_discount_bps",
                                                    required=required, minimum=0, maximum=9999),
    }


def _recompute_price(valuation, plan):
    result = calc.valuation_share_price(
        valuation["enterprise_value_cents"],
        valuation["debt_outstanding_cents"],
        valuation["non_operating_assets_cents"],
        valuation["control_premium_bps"],
        valuation["marketability_discount_bps"],
        plan["total_plan_shares"],
        plan["total_shares_outstanding"],
    )
    valuation.update(result)


@bp.post("/valuations")
@endpoint([APPRAISER])
def create_valuation():
    body = v.body()
    plan_id = v.req_string(body, "plan_id")
    plan_year = v.req_integer(body, "plan_year")
    inputs = _price_inputs(body)
    effective_from_date = v.req_date(body, "effective_from_date")
    effective_to_date = v.req_date(body, "effective_to_date")
    expected_plan_version = v.req_integer(body, "expected_plan_version")
    supersedes_valuation_id = v.req_string(body, "supersedes_valuation_id",
                                           required=False, default=None)

    if calc.iso_to_date(effective_to_date) <= calc.iso_to_date(effective_from_date):
        fail("ERR_INVALID_REQUEST", "effective_to_date must be strictly after effective_from_date.")

    plan = services.get_plan(plan_id)
    superseded = None
    if supersedes_valuation_id is not None:
        superseded = services.get_valuation(supersedes_valuation_id)

    services.check_not_frozen(plan)

    if expected_plan_version != plan["version"]:
        fail("ERR_STALE_PLAN_VERSION")

    new_from = calc.iso_to_date(effective_from_date)
    new_to = calc.iso_to_date(effective_to_date)
    for other in DB.valuations.values():
        if other["plan_id"] != plan_id:
            continue
        if superseded is not None and other["id"] == superseded["id"]:
            continue
        if other["status"] not in ("SUBMITTED", "CHALLENGED", "APPROVED"):
            continue
        other_from = calc.iso_to_date(other["effective_from_date"])
        other_to = calc.iso_to_date(other["effective_to_date"])
        if new_from < other_to and other_from < new_to:
            fail("ERR_VALUATION_PERIOD_OVERLAP")

    record = {
        "plan_id": plan_id,
        "plan_year": plan_year,
        "appraiser_user_id": caller_id(),
        "enterprise_value_cents": inputs["enterprise_value_cents"],
        "debt_outstanding_cents": inputs["debt_outstanding_cents"],
        "non_operating_assets_cents": inputs["non_operating_assets_cents"],
        "control_premium_bps": inputs["control_premium_bps"],
        "marketability_discount_bps": inputs["marketability_discount_bps"],
        "effective_from_date": effective_from_date,
        "effective_to_date": effective_to_date,
        "share_price_cents": 0,
        "equity_value_cents": 0,
        "control_premium_applied_cents": 0,
        "ownership_bps_at_valuation": 0,
        "status": "SUBMITTED",
        "challenge_round": 0,
        "challenge_note": None,
        "supersedes_valuation_id": supersedes_valuation_id,
        "approved_by_user_id": None,
        "rejected_reason": None,
    }
    valuation = insert(DB.valuations, record)
    _recompute_price(valuation, plan)

    if superseded is not None and superseded["status"] in OPEN_STATUSES:
        superseded["status"] = "SUPERSEDED"
        touch(superseded)
        plan["open_valuation_count"] -= 1

    plan["open_valuation_count"] += 1
    touch(plan)
    return responses.ok(serialize(valuation), 201)


@bp.get("/valuations/<valuation_id>")
@endpoint(READ_ROLES)
def read_valuation(valuation_id):
    return responses.ok(serialize(services.get_valuation(valuation_id)))


@bp.get("/valuations")
@endpoint(READ_ROLES)
def list_valuations():
    limit, offset = v.pagination()
    plan_id = v.query_str("plan_id")
    plan_year = v.query_int("plan_year")
    status = v.query_str("status")
    supersedes_valuation_id = v.query_str("supersedes_valuation_id")
    rows = sorted_rows(DB.valuations)
    if plan_id is not None:
        rows = [r for r in rows if r["plan_id"] == plan_id]
    if plan_year is not None:
        rows = [] if plan_year is v.MISSING else [r for r in rows if r["plan_year"] == plan_year]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if supersedes_valuation_id is not None:
        rows = [r for r in rows if r["supersedes_valuation_id"] == supersedes_valuation_id]
    return services.paged(rows, limit, offset)


@bp.post("/valuations/<valuation_id>/challenge")
@endpoint([TRUSTEE])
def challenge_valuation(valuation_id):
    body = v.body()
    challenge_note = v.req_string(body, "challenge_note")

    valuation = services.get_valuation(valuation_id)
    plan = services.get_plan(valuation["plan_id"])
    services.check_not_frozen(plan)

    if valuation["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE")
    if valuation["challenge_round"] >= calc.MAX_CHALLENGE_ROUNDS:
        fail("ERR_CHALLENGE_ROUNDS_EXHAUSTED")

    valuation["status"] = "CHALLENGED"
    valuation["challenge_round"] += 1
    valuation["challenge_note"] = challenge_note
    touch(valuation)
    return responses.ok(serialize(valuation))


@bp.post("/valuations/<valuation_id>/resubmit")
@endpoint([APPRAISER])
def resubmit_valuation(valuation_id):
    body = v.body()
    inputs = _price_inputs(body)

    valuation = services.get_valuation(valuation_id)
    plan = services.get_plan(valuation["plan_id"])
    services.check_not_frozen(plan)

    if valuation["status"] != "CHALLENGED":
        fail("ERR_INVALID_STATE")
    if caller_id() != valuation["appraiser_user_id"]:
        fail("ERR_INVALID_STATE", "Only the submitting appraiser may revise this appraisal.")

    valuation.update(inputs)
    valuation["status"] = "SUBMITTED"
    _recompute_price(valuation, plan)
    touch(valuation)
    return responses.ok(serialize(valuation))


@bp.post("/valuations/<valuation_id>/approve")
@endpoint([TRUSTEE])
def approve_valuation(valuation_id):
    valuation = services.get_valuation(valuation_id)
    plan = services.get_plan(valuation["plan_id"])
    services.check_not_frozen(plan)
    services.require_plan_status(plan, "VALUATION_PENDING")

    if valuation["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE")
    if valuation["plan_year"] != plan["plan_year"]:
        fail("ERR_INVALID_STATE", "The appraisal's plan year does not match the plan's.")
    if caller_id() == valuation["appraiser_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES")
    for other in DB.valuations.values():
        if (other["id"] != valuation["id"] and other["plan_id"] == plan["id"]
                and other["plan_year"] == valuation["plan_year"]
                and other["status"] == "APPROVED"):
            fail("ERR_NO_APPROVED_VALUATION",
                 "This plan year already carries an approved appraisal.")

    valuation["status"] = "APPROVED"
    valuation["approved_by_user_id"] = caller_id()
    touch(valuation)
    plan["current_share_price_cents"] = valuation["share_price_cents"]

    left_open = 1
    for other in sorted_rows(DB.valuations):
        if (other["id"] != valuation["id"] and other["plan_id"] == plan["id"]
                and other["plan_year"] == valuation["plan_year"]
                and other["status"] in OPEN_STATUSES):
            other["status"] = "SUPERSEDED"
            touch(other)
            left_open += 1
    plan["open_valuation_count"] -= left_open
    touch(plan)
    return responses.ok(serialize(valuation))


@bp.post("/valuations/<valuation_id>/reject")
@endpoint([TRUSTEE])
def reject_valuation(valuation_id):
    body = v.body()
    reason = v.req_string(body, "reason")

    valuation = services.get_valuation(valuation_id)
    plan = services.get_plan(valuation["plan_id"])
    services.check_not_frozen(plan)

    if valuation["status"] not in OPEN_STATUSES:
        fail("ERR_INVALID_STATE")

    valuation["status"] = "REJECTED"
    valuation["rejected_reason"] = reason
    touch(valuation)
    plan["open_valuation_count"] -= 1
    touch(plan)
    return responses.ok(serialize(valuation))
