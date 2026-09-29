"""Prospectus review rounds and the mitigation work plan (PRD 3.3, 3.4)."""
from decimal import Decimal

import auth
import calc
import ledger
import lookup
import serialize
import store
from errors import ApiError
from flask import Blueprint
from response import list_response, object_response
from routes.banks import require_open_bank
from util import dec, now
from validation import (bad_request, coerce_decimal, json_body, pagination, paginate,
                        v_decimal, v_enum, v_string)

bp = Blueprint("review", __name__)

POSITIONS = ("CONCUR", "OBJECT", "ABSTAIN")
PROTOCOLS = ("MECHANICAL", "HERBICIDE", "INTEGRATED")
COMPARATORS = ("GTE", "LTE")
DECISIONS = ("APPROVE", "RETURN")


# ----------------------------------------------------------------- prospectus
@bp.post("/mitigation/prospectuses")
def create_prospectus():
    actor = auth.authenticate("Sponsor")
    body = json_body()
    bank_id = v_string(body, "bank_id")
    summary = v_string(body, "objective_summary", max_len=2000)
    proposed = v_decimal(body, "proposed_credits", places=2, min_exclusive=0)
    bank = lookup.bank(bank_id)
    auth.require_bank_sponsor(actor, bank)
    require_open_bank(bank)
    row = store.new_row({
        "bank_id": bank["id"],
        "objective_summary": summary,
        "proposed_credits": proposed,
        "status": "DRAFT",
        "revision_round": 1,
        "submitted_at": None,
        "review_opened_at": None,
        "decision_recorded_by": None,
        "decided_at": None,
    })
    store.prospectuses[row["id"]] = row
    return object_response(serialize.prospectus(row), 201)


@bp.post("/mitigation/prospectuses/<row_id>/submit")
def submit_prospectus(row_id):
    actor = auth.authenticate("Sponsor")
    prospectus = lookup.prospectus(row_id)
    bank = lookup.bank(prospectus["bank_id"])
    auth.require_bank_sponsor(actor, bank)
    if prospectus["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        raise ApiError("ERR_PROSPECTUS_STATE_INVALID",
                       "Only a DRAFT or REVISION_REQUESTED prospectus may be submitted.")
    first_submission = prospectus["status"] == "DRAFT"
    if first_submission:
        if bank["status"] != "DRAFT":
            raise ApiError("ERR_BANK_STATE_INVALID",
                           "The first prospectus submission requires the bank to be in DRAFT.")
        if bank["site_huc8_code"] not in bank["service_area_huc8_codes"]:
            raise ApiError("ERR_SERVICE_AREA_MISSING_SITE_HUC",
                           "The service area must contain the site's own watershed code.")
    elif prospectus["revision_round"] > calc.MAX_REVISION_ROUNDS:
        raise ApiError("ERR_PROSPECTUS_STATE_INVALID",
                       "The prospectus has passed the second-round ceiling.")
    prospectus["status"] = "SUBMITTED"
    prospectus["submitted_at"] = now()
    if not first_submission:
        prospectus["review_opened_at"] = None
    store.touch(prospectus)
    if first_submission:
        bank["status"] = "PROSPECTUS_REVIEW"
        store.touch(bank)
    return object_response(serialize.prospectus(prospectus))


@bp.post("/mitigation/prospectuses/<row_id>/votes")
def cast_vote(row_id):
    actor = auth.authenticate("IRTMember")
    body = json_body()
    position = v_enum(body, "position", POSITIONS)
    comment = v_string(body, "comment", required=False, max_len=1000, allow_empty=True)
    prospectus = lookup.prospectus(row_id)
    member = auth.acting_member(actor)
    auth.check_not_recused(member)
    if prospectus["status"] not in ("SUBMITTED", "UNDER_REVIEW"):
        raise ApiError("ERR_PROSPECTUS_STATE_INVALID",
                       "Votes may only be cast on a submitted or under-review prospectus.")
    round_number = prospectus["revision_round"]
    for vote in store.prospectus_votes.values():
        if (vote["prospectus_id"] == prospectus["id"]
                and vote["irt_member_id"] == member["id"]
                and vote["revision_round"] == round_number):
            raise ApiError("ERR_DUPLICATE_VOTE",
                           "This member has already voted in the current revision round.")
    row = store.new_row({
        "prospectus_id": prospectus["id"],
        "irt_member_id": member["id"],
        "revision_round": round_number,
        "position": position,
        "comment": comment,
        "is_veto": position == "OBJECT" and member["agency"] == "USACE",
    }, common=False)
    store.prospectus_votes[row["id"]] = row
    if prospectus["status"] == "SUBMITTED":
        prospectus["status"] = "UNDER_REVIEW"
        prospectus["review_opened_at"] = now()
        store.touch(prospectus)
    return object_response(serialize.prospectus_vote(row), 201)


@bp.post("/mitigation/prospectuses/<row_id>/finalize-review")
def finalize_review(row_id):
    actor = auth.authenticate("IRTChair")
    prospectus = lookup.prospectus(row_id)
    if prospectus["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_PROSPECTUS_STATE_INVALID",
                       "Only an UNDER_REVIEW prospectus may be finalized.")
    votes = serialize.round_votes(prospectus["id"], prospectus["revision_round"])
    votes_cast = len(votes)
    if votes_cast < calc.IRT_QUORUM_MIN:
        raise ApiError("ERR_IRT_QUORUM_NOT_MET",
                       "At least %d votes must be cast in the current round."
                       % calc.IRT_QUORUM_MIN)
    veto = any(v["is_veto"] for v in votes)
    concur = sum(1 for v in votes if v["position"] == "CONCUR")
    threshold = -((-2 * votes_cast) // 3)          # ceil(2/3 * votes_cast)
    if veto:
        outcome = "REJECTED"
    elif concur >= threshold:
        plans = [w for w in store.work_plans.values()
                 if w["bank_id"] == prospectus["bank_id"]
                 and w["status"] in ("SUBMITTED", "APPROVED")]
        if not plans:
            raise ApiError("ERR_WORK_PLAN_MISSING",
                           "Approval requires a work plan in SUBMITTED or APPROVED status.")
        outcome = "APPROVED"
    elif prospectus["revision_round"] < calc.MAX_REVISION_ROUNDS:
        outcome = "REVISION_REQUESTED"
    else:
        outcome = "REJECTED"
    prospectus["status"] = outcome
    prospectus["decision_recorded_by"] = actor.user_id
    prospectus["decided_at"] = now()
    if outcome == "REVISION_REQUESTED":
        prospectus["revision_round"] += 1
    store.touch(prospectus)
    return object_response(serialize.prospectus(prospectus))


@bp.get("/mitigation/prospectuses/<row_id>")
def read_prospectus(row_id):
    auth.authenticate("ProgramAdmin", "Sponsor", "IRTChair", "IRTMember")
    return object_response(serialize.prospectus(lookup.prospectus(row_id)))


@bp.get("/mitigation/prospectuses/<row_id>/votes")
def list_prospectus_votes(row_id):
    auth.authenticate("ProgramAdmin", "Sponsor", "IRTChair", "IRTMember")
    limit, offset = pagination()
    prospectus = lookup.prospectus(row_id)
    rows = store.ordered([v for v in store.prospectus_votes.values()
                          if v["prospectus_id"] == prospectus["id"]])
    page, total = paginate(rows, limit, offset)
    return list_response([serialize.prospectus_vote(v) for v in page], limit, offset, total)


# ------------------------------------------------------------------ work plan
def _parse_strata(body):
    raw = body.get("credit_strata")
    if not isinstance(raw, list) or not 1 <= len(raw) <= 6:
        raise bad_request("credit_strata must be an array of 1 through 6 objects.")
    seen = set()
    strata = []
    for item in raw:
        if not isinstance(item, dict):
            raise bad_request("Every credit_strata entry must be an object.")
        code = v_enum(item, "stratum_code", calc.STRATUM_CODES)
        if code in seen:
            raise bad_request("credit_strata may not repeat a stratum code.")
        seen.add(code)
        strata.append({
            "stratum_code": code,
            "acres": v_decimal(item, "acres", places=2, min_exclusive=0),
            "lift_factor": v_decimal(item, "lift_factor", places=3, min_exclusive=0, maximum=1),
        })
    return strata


def _parse_standards(body):
    raw = body.get("performance_standards")
    if not isinstance(raw, list) or not 1 <= len(raw) <= 6:
        raise bad_request("performance_standards must be an array of 1 through 6 objects.")
    seen = set()
    standards = []
    for item in raw:
        if not isinstance(item, dict):
            raise bad_request("Every performance_standards entry must be an object.")
        code = v_enum(item, "standard_code", calc.STANDARD_CODES)
        if code in seen:
            raise bad_request("performance_standards may not repeat a standard code.")
        seen.add(code)
        year = item.get("effective_from_year")
        if isinstance(year, bool) or not isinstance(year, int) or year < 1:
            raise bad_request("effective_from_year must be an integer of at least 1.")
        standards.append({
            "standard_code": code,
            "comparator": v_enum(item, "comparator", COMPARATORS),
            "threshold_value": v_decimal(item, "threshold_value", places=None, min_exclusive=0),
            "weight": v_decimal(item, "weight", places=3, min_exclusive=0),
            "effective_from_year": year,
        })
    return standards


@bp.post("/mitigation/work-plans")
def create_work_plan():
    actor = auth.authenticate("Sponsor")
    body = json_body()
    bank_id = v_string(body, "bank_id")
    hydrology = v_decimal(body, "hydrology_restoration_acres", places=2, minimum=0)
    planting = v_decimal(body, "planting_acres", places=2, minimum=0)
    invasive = v_decimal(body, "invasive_control_acres", places=2, minimum=0)
    protocol = v_enum(body, "invasive_control_protocol", PROTOCOLS)
    strata = _parse_strata(body)
    standards = _parse_standards(body)
    bank = lookup.bank(bank_id)
    auth.require_bank_sponsor(actor, bank)
    require_open_bank(bank)
    if any(w["bank_id"] == bank["id"] and w["status"] == "APPROVED"
           for w in store.work_plans.values()):
        raise ApiError("ERR_WORK_PLAN_ALREADY_APPROVED",
                       "This bank already has an approved work plan.")
    if sum((s["weight"] for s in standards), Decimal("0")) != Decimal("1.000"):
        raise ApiError("ERR_STANDARD_WEIGHTS_INVALID",
                       "The performance standard weights must sum to exactly 1.000.")
    row = store.new_row({
        "bank_id": bank["id"],
        "hydrology_restoration_acres": hydrology,
        "planting_acres": planting,
        "invasive_control_acres": invasive,
        "invasive_control_protocol": protocol,
        "credit_strata": strata,
        "performance_standards": standards,
        "total_planned_credits": calc.work_plan_credit_yield(strata),
        "status": "DRAFT",
        "submitted_at": None,
        "decided_at": None,
        "return_reason": None,
    })
    store.work_plans[row["id"]] = row
    return object_response(serialize.work_plan(row), 201)


@bp.post("/mitigation/work-plans/<row_id>/submit")
def submit_work_plan(row_id):
    actor = auth.authenticate("Sponsor")
    plan = lookup.work_plan(row_id)
    bank = lookup.bank(plan["bank_id"])
    auth.require_bank_sponsor(actor, bank)
    if plan["status"] not in ("DRAFT", "RETURNED"):
        raise ApiError("ERR_WORK_PLAN_STATE_INVALID",
                       "Only a DRAFT or RETURNED work plan may be submitted.")
    require_open_bank(bank)
    if plan["hydrology_restoration_acres"] + plan["planting_acres"] <= 0:
        raise ApiError("ERR_WORK_PLAN_STATE_INVALID",
                       "A plan that restores nothing has nothing to submit.")
    was_returned = plan["status"] == "RETURNED"
    plan["status"] = "SUBMITTED"
    plan["submitted_at"] = now()
    plan["total_planned_credits"] = calc.work_plan_credit_yield(plan["credit_strata"])
    if was_returned:
        plan["return_reason"] = None
    store.touch(plan)
    return object_response(serialize.work_plan(plan))


@bp.post("/mitigation/work-plans/<row_id>/decide")
def decide_work_plan(row_id):
    auth.authenticate("IRTChair")
    body = json_body()
    decision = v_enum(body, "decision", DECISIONS)
    return_reason = v_string(body, "return_reason", required=decision == "RETURN", max_len=1000)
    plan = lookup.work_plan(row_id)
    if plan["status"] != "SUBMITTED":
        raise ApiError("ERR_WORK_PLAN_STATE_INVALID",
                       "Only a SUBMITTED work plan may be decided.")
    bank = store.banks.get(plan["bank_id"])
    if bank is not None:
        require_open_bank(bank)
    if decision == "RETURN":
        plan["status"] = "RETURNED"
        plan["decided_at"] = now()
        plan["return_reason"] = return_reason
        store.touch(plan)
        return object_response(serialize.work_plan(plan))
    if any(w["bank_id"] == plan["bank_id"] and w["status"] == "APPROVED"
           for w in store.work_plans.values()):
        raise ApiError("ERR_WORK_PLAN_ALREADY_APPROVED",
                       "This bank already has an approved work plan.")
    if not any(p["bank_id"] == plan["bank_id"] and p["status"] == "APPROVED"
               for p in store.prospectuses.values()):
        raise ApiError("ERR_WORK_PLAN_MISSING",
                       "Work plan approval requires an approved prospectus for the same bank.")
    plan["status"] = "APPROVED"
    plan["decided_at"] = now()
    store.touch(plan)
    for standard in plan["performance_standards"]:
        row = store.new_row({
            "bank_id": plan["bank_id"],
            "standard_code": standard["standard_code"],
            "comparator": standard["comparator"],
            "threshold_value": standard["threshold_value"],
            "weight": standard["weight"],
            "effective_from_year": standard["effective_from_year"],
        })
        store.performance_standards[row["id"]] = row
    if bank is not None:
        store.touch(bank)
    return object_response(serialize.work_plan(plan))
