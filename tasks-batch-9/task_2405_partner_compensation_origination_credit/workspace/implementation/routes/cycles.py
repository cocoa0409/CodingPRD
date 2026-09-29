"""Compensation cycle endpoints and the cycle stage machine."""
from flask import Blueprint

from db import D, new_entity, store, touch
from errors import ApiError
from middleware import authorize
from response import created, listing, ok
from routes.common import READ_ALL, by_created, filtered, find_cycle
from services import calculations as calc
from services.engine import commit, cycle_assessments, cycle_awards, award_payments
from validation import (field_date, field_decimal, field_enum, field_int, get_body,
                        pagination, query_enum, query_int)

bp = Blueprint("cycles", __name__)

EDGES = {
    ("OPEN_INTAKE", "SELF_ASSESSMENT"),
    ("SELF_ASSESSMENT", "PEER_REVIEW"),
    ("PEER_REVIEW", "DELIBERATION"),
    ("DELIBERATION", "AWARDS_PUBLISHED"),
    ("AWARDS_PUBLISHED", "DELIBERATION"),
    ("AWARDS_PUBLISHED", "TRUE_UP_OPEN"),
    ("TRUE_UP_OPEN", "CLOSED"),
}


@bp.post("/comp/cycles")
def create_cycle():
    authorize(["CycleAdmin"])
    body = get_body()
    fiscal_year = field_int(body, "fiscal_year", low=2000, high=2100)
    distributable = field_int(body, "distributable_pool_cents", low=0)
    lockstep_unit = field_int(body, "lockstep_unit_cents", low=0)
    discretionary_pct = field_decimal(body, "discretionary_pool_pct", 4, required=False,
                                     low=0, high=1, default=D("0.2000"))
    draw_pct = field_decimal(body, "draw_pct", 4, required=False, low=0, high=1,
                             default=D("0.8000"))
    claim_deadline = field_date(body, "claim_deadline_on")
    assessment_deadline = field_date(body, "assessment_deadline_on")

    for existing in store.cycles.values():
        if existing["fiscal_year"] == fiscal_year:
            raise ApiError("ERR_DUPLICATE_CYCLE")

    cycle = new_entity({
        "fiscal_year": fiscal_year,
        "state": "OPEN_INTAKE",
        "distributable_pool_cents": distributable,
        "lockstep_unit_cents": lockstep_unit,
        "discretionary_pool_pct": discretionary_pct,
        "draw_pct": draw_pct,
        "claim_deadline_on": claim_deadline,
        "assessment_deadline_on": assessment_deadline,
        "lockstep_reserved_cents": 0,
        "discretionary_pool_cents": 0,
        "formula_pool_cents": 0,
        "haircut_applied_pct": D("0.0000"),
        "total_formula_score": D("0.0000"),
        "total_committee_points": D("0.00"),
        "undistributed_cash_cents": distributable,
        "unsettled_award_count": 0,
        "reopen_count": 0,
        "confidentiality_locked": False,
    })
    store.cycles[cycle["id"]] = cycle
    return created(commit(cycle))


@bp.get("/comp/cycles/<cycle_id>")
def read_cycle(cycle_id):
    authorize(READ_ALL)
    return ok(find_cycle(cycle_id))


@bp.get("/comp/cycles")
def list_cycles():
    authorize(READ_ALL)
    limit, offset = pagination()
    state = query_enum("state", calc.CYCLE_STATES)
    fiscal_year = query_int("fiscal_year")
    rows = filtered(store.cycles.values(), {"state": state, "fiscal_year": fiscal_year})
    rows.sort(key=lambda c: (-c["fiscal_year"], c["_seq"]))
    return listing(rows, limit, offset)


@bp.post("/comp/cycles/<cycle_id>/advance")
def advance_cycle(cycle_id):
    authorize(["CycleAdmin"])
    body = get_body()
    target = field_enum(body, "target_state", calc.CYCLE_STATES)
    cycle = find_cycle(cycle_id)
    current = cycle["state"]
    if (current, target) not in EDGES:
        raise ApiError("ERR_INVALID_CYCLE_TRANSITION")

    if current == "OPEN_INTAKE":
        _gate_open_intake(cycle)
    elif current == "SELF_ASSESSMENT":
        _gate_self_assessment(cycle)
    elif current == "PEER_REVIEW":
        _gate_peer_review(cycle)
        _enter_deliberation(cycle)
    elif current == "DELIBERATION":
        _publish_awards(cycle)
    elif current == "AWARDS_PUBLISHED" and target == "DELIBERATION":
        _reopen(cycle)
    elif current == "AWARDS_PUBLISHED" and target == "TRUE_UP_OPEN":
        for award in cycle_awards(cycle["id"]):
            if award["award_state"] != "PUBLISHED":
                raise ApiError("ERR_INVALID_CYCLE_TRANSITION")
    elif current == "TRUE_UP_OPEN":
        if cycle["unsettled_award_count"] != 0:
            raise ApiError("ERR_AWARDS_NOT_SETTLED")
        for award in cycle_awards(cycle["id"]):
            if award["award_state"] == "PUBLISHED":
                award["award_state"] = "FINALIZED"
                touch(award)

    cycle["state"] = target
    touch(cycle)
    return ok(commit(cycle))


# --------------------------------------------------------------------------
# per-edge gates and cascades
# --------------------------------------------------------------------------

def _gate_open_intake(cycle):
    for claim in store.claims.values():
        if claim["cycle_id"] == cycle["id"] and claim["state"] in ("SUBMITTED", "DISPUTED"):
            raise ApiError("ERR_UNRESOLVED_CLAIMS")


def _required_partners(cycle):
    return [p for p in by_created(store.partners.values())
            if p["evaluation_required"] and p["status"] in ("ACTIVE", "NOTICE_GIVEN")]


def _gate_self_assessment(cycle):
    for partner in _required_partners(cycle):
        matching = [a for a in cycle_assessments(cycle["id"])
                    if a["partner_id"] == partner["id"]
                    and a["state"] in ("SUBMITTED", "ACCEPTED")]
        if len(matching) != 1:
            raise ApiError("ERR_ASSESSMENTS_INCOMPLETE")


def _gate_peer_review(cycle):
    assessments = cycle_assessments(cycle["id"])
    for assessment in assessments:
        if assessment["state"] not in ("SUBMITTED", "ACCEPTED"):
            raise ApiError("ERR_ASSESSMENTS_INCOMPLETE")
    for assessment in assessments:
        if assessment["scored_review_count"] < calc.MIN_SCORED_PEER_REVIEWS:
            raise ApiError("ERR_PEER_REVIEWS_INCOMPLETE")


def _enter_deliberation(cycle):
    subjects = [p for p in by_created(store.partners.values())
                if p["compensation_model"] == "DISCRETIONARY"
                and p["evaluation_required"]
                and p["status"] in ("ACTIVE", "NOTICE_GIVEN")]
    members = [p for p in by_created(store.partners.values())
               if p["is_committee_member"] and p["status"] == "ACTIVE"]
    for subject in subjects:
        for member in members:
            ballot = new_entity({
                "cycle_id": cycle["id"],
                "subject_partner_id": subject["id"],
                "committee_member_id": member["id"],
                "state": "PENDING",
                "points_proposed": None,
                "rationale": None,
                "recusal_reason": None,
                "decided_at": None,
            })
            store.ballots[ballot["id"]] = ballot

    for partner in _required_partners(cycle):
        award = new_entity({
            "partner_id": partner["id"],
            "cycle_id": cycle["id"],
            "award_state": "PROPOSED",
            "payment_state": "PENDING",
            "basis_model": partner["compensation_model"],
            "target_award_cents": 0,
            "final_award_cents": None,
            "draw_schedule_monthly_cents": 0,
            "draw_paid_cents": 0,
            "true_up_delta_cents": None,
            "capital_call_cents": None,
            "capital_shortfall_cents": 0,
            "reconsideration_count": 0,
        })
        store.awards[award["id"]] = award


def _publish_awards(cycle):
    subjects = {}
    for ballot in store.ballots.values():
        if ballot["cycle_id"] != cycle["id"]:
            continue
        subjects.setdefault(ballot["subject_partner_id"], []).append(ballot)
    for rows in subjects.values():
        cast = [b for b in rows if b["state"] == "CAST"]
        if len(cast) < calc.QUORUM_MIN_CAST_BALLOTS:
            raise ApiError("ERR_QUORUM_NOT_MET")

    pools = calc.cycle_pool_waterfall(cycle)
    for key, value in pools.items():
        cycle[key] = value
    touch(cycle)

    for award in cycle_awards(cycle["id"]):
        amount = calc.award_amount(award, "PROVISIONAL_DELIBERATION")
        award["target_award_cents"] = amount
        award["draw_schedule_monthly_cents"] = calc.draw_schedule(amount, cycle["draw_pct"])
        if award["award_state"] == "PROPOSED":
            award["award_state"] = "PUBLISHED"
        touch(award)


def _reopen(cycle):
    if cycle["reopen_count"] >= calc.MAX_REOPENS:
        raise ApiError("ERR_CYCLE_NOT_REOPENABLE")
    awards = cycle_awards(cycle["id"])
    for award in awards:
        if award["payment_state"] in ("TRUED_UP", "SETTLED"):
            raise ApiError("ERR_CYCLE_NOT_REOPENABLE")

    for award in awards:
        draws = [p for p in award_payments(award["id"])
                 if p["kind"] == "SCHEDULED_DRAW" and not p["reversed"]]
        draws.sort(key=lambda p: (p["period_year"], p["period_month"], p["_seq"]))
        for draw in draws:
            reversal = new_entity({
                "award_id": award["id"],
                "kind": "DRAW_REVERSAL",
                "period_year": draw["period_year"],
                "period_month": draw["period_month"],
                "amount_cents": -draw["amount_cents"],
                "reversed": False,
                "memo": "Reversal of scheduled draw on cycle reopen.",
            }, common=False)
            store.payments[reversal["id"]] = reversal
            draw["reversed"] = True
        if award["award_state"] == "PUBLISHED":
            award["award_state"] = "PROPOSED"
        award["reconsideration_count"] += 1
        award["payment_state"] = "PENDING"
        touch(award)

    cycle["reopen_count"] += 1
