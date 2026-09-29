"""Plan root, charter adoption, quarter advance, posture recompute, clock."""
from decimal import Decimal
from flask import Blueprint

import calc
from core import (D, as_bool, as_dec, as_enum, as_int, as_str, authenticate,
                  body, clock, fail, new_row, ok, ok_list, opt_field, paginate,
                  parse_date, parse_dt, public, q_str, req_field, store, touch)
from helpers import filter_rows, get_row

bp = Blueprint("plan", __name__)

DERIVED_PLAN_FIELDS = (
    "menu_posture", "at_risk_slot_ratio", "occupied_menu_slots",
    "reserved_menu_slots", "available_menu_slots", "draft_proposal_count",
    "total_plan_assets_cents", "revenue_credit_accrued_cents",
    "revenue_credit_allocated_cents", "revenue_credit_balance_cents",
    "fee_disclosure_status", "documented_acceptance_count",
)


def plan_snapshot(plan):
    return dict((k, plan.get(k)) for k in DERIVED_PLAN_FIELDS)


def commit_plan(plan, snapshot):
    for key, value in snapshot.items():
        if plan.get(key) != value:
            touch(plan)
            return True
    return False


def refresh_plan(plan):
    """Recompute derived aggregates and posture, bumping version when anything
    actually moved."""
    snapshot = plan_snapshot(plan)
    calc.recompute_posture(plan)
    commit_plan(plan, snapshot)


# --------------------------------------------------------------------------- #
# Logical clock
# --------------------------------------------------------------------------- #

@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    payload = body()
    value = req_field(payload, "current_utc")
    clock.set(parse_dt(value, "current_utc"))
    return ok({"current_utc": clock.iso()})


# --------------------------------------------------------------------------- #
# Plans
# --------------------------------------------------------------------------- #

@bp.route("/governance/plans", methods=["POST"])
def create_plan():
    authenticate(("PlanSponsorAdmin",))
    payload = body()
    sponsor_name = as_str(req_field(payload, "plan_sponsor_name"),
                          "plan_sponsor_name", 1, 120)
    plan_name = as_str(req_field(payload, "plan_name"), "plan_name", 1, 120)
    plan_type = as_enum(req_field(payload, "plan_type"), "plan_type", calc.PLAN_TYPES)
    erisa_covered = payload.get("erisa_covered")
    erisa_covered = True if erisa_covered is None else as_bool(erisa_covered,
                                                              "erisa_covered")
    accounts = as_int(req_field(payload, "participant_account_count"),
                      "participant_account_count", 1)
    capacity = as_int(req_field(payload, "menu_slot_capacity"),
                      "menu_slot_capacity", 3, 40)
    quorum = as_int(opt_field(payload, "quorum_min_voting_members", 3),
                    "quorum_min_voting_members", 2, 9)
    threshold = as_dec(opt_field(payload, "voting_threshold_pct", "0.6000"),
                       "voting_threshold_pct", 4, "0.5000", "1.0000")
    max_seats = as_int(opt_field(payload, "max_voting_seats", 7),
                       "max_voting_seats", 2, 11)
    lead_days = as_int(opt_field(payload, "notice_lead_days_required", 30),
                       "notice_lead_days_required", 0)
    buffer_days = as_int(opt_field(payload, "blackout_buffer_days", 3),
                         "blackout_buffer_days", 0)

    plan = new_row({
        "sponsor_name": sponsor_name,
        "plan_name": plan_name,
        "plan_type": plan_type,
        "erisa_covered": erisa_covered,
        "participant_account_count": accounts,
        "menu_slot_capacity": capacity,
        "fiscal_quarter_index": 0,
        "charter_status": "DRAFT",
        "charter_adopted_quarter_index": None,
        "charter_doc_ref": None,
        "quorum_min_voting_members": quorum,
        "voting_threshold_pct": threshold,
        "max_voting_seats": max_seats,
        "notice_lead_days_required": lead_days,
        "blackout_buffer_days": buffer_days,
        "menu_posture": "FROZEN",
        "at_risk_slot_ratio": Decimal("0.0000"),
        "occupied_menu_slots": 0,
        "reserved_menu_slots": 0,
        "available_menu_slots": capacity,
        "draft_proposal_count": 0,
        "total_plan_assets_cents": 0,
        "revenue_credit_accrued_cents": 0,
        "revenue_credit_allocated_cents": 0,
        "revenue_credit_balance_cents": 0,
        "fee_disclosure_status": "COMPLIANT",
        "documented_acceptance_count": 0,
    })
    store.plans[plan["id"]] = plan
    return ok(public(plan), 201)


@bp.route("/governance/plans", methods=["GET"])
def list_plans():
    authenticate(None)
    rows = filter_rows(list(store.plans.values()),
                       [(q_str("charter_status"), "charter_status"),
                        (q_str("menu_posture"), "menu_posture"),
                        (q_str("plan_type"), "plan_type")])
    data, limit, offset, total = paginate(rows)
    return ok_list(data, limit, offset, total)


@bp.route("/governance/plans/<plan_id>", methods=["GET"])
def get_plan(plan_id):
    authenticate(None)
    plan = get_row("plans", plan_id, "planId")
    return ok(public(plan))


@bp.route("/governance/plans/<plan_id>/charter/adopt", methods=["POST"])
def adopt_charter(plan_id):
    authenticate(("PlanSponsorAdmin",))
    plan = get_row("plans", plan_id, "planId")
    payload = body()

    quorum = as_int(opt_field(payload, "quorum_min_voting_members",
                              plan["quorum_min_voting_members"]),
                    "quorum_min_voting_members", 2, 9)
    threshold = as_dec(opt_field(payload, "voting_threshold_pct",
                                 plan["voting_threshold_pct"]),
                       "voting_threshold_pct", 4, "0.5000", "1.0000")
    max_seats = as_int(opt_field(payload, "max_voting_seats",
                                 plan["max_voting_seats"]),
                       "max_voting_seats", 2, 11)
    doc_ref = payload.get("charter_doc_ref")
    if doc_ref is not None:
        doc_ref = as_str(doc_ref, "charter_doc_ref", 1)
    if quorum > max_seats:
        fail("ERR_INVALID_REQUEST",
             "quorum_min_voting_members may not exceed max_voting_seats")

    if plan["charter_status"] not in ("DRAFT", "ADOPTED"):
        fail("ERR_INVALID_STATE_TRANSITION", "the charter cannot be adopted now")
    readopt = plan["charter_status"] == "ADOPTED"
    if readopt:
        for meeting in calc.plan_meetings(plan["id"]):
            if meeting["status"] == "IN_SESSION":
                fail("ERR_MEETING_IN_SESSION",
                     "a committee meeting is in session")

    seats = calc.plan_seats(plan["id"])
    voting_seats = [s for s in seats if s.get("voting") and s["status"] != "RETIRED"]
    filled_voting = [s for s in voting_seats if s["status"] == "FILLED"]
    if len(voting_seats) < 2:
        fail("ERR_CHARTER_SEATS_INSUFFICIENT",
             "the plan needs at least two non-retired voting seats")
    if len(voting_seats) > max_seats:
        fail("ERR_CHARTER_SEATS_INSUFFICIENT",
             "the plan has more voting seats than max_voting_seats allows")
    if len(filled_voting) < quorum:
        fail("ERR_CHARTER_SEATS_INSUFFICIENT",
             "filled voting seats are below quorum_min_voting_members")

    plan["quorum_min_voting_members"] = quorum
    plan["voting_threshold_pct"] = threshold
    plan["max_voting_seats"] = max_seats
    if doc_ref is not None:
        plan["charter_doc_ref"] = doc_ref
    if readopt:
        plan["charter_status"] = "SUPERSEDED"
        for motion in calc.sort_created(calc.plan_motions(plan["id"])):
            if motion["status"] == "OPEN":
                motion["status"] = "TABLED"
                motion["closed_at"] = clock.iso()
                touch(motion)
    plan["charter_status"] = "ADOPTED"
    plan["charter_adopted_quarter_index"] = plan["fiscal_quarter_index"]
    calc.recompute_posture(plan)
    touch(plan)
    return ok(public(plan))


@bp.route("/governance/plans/<plan_id>/advance-quarter", methods=["POST"])
def advance_quarter(plan_id):
    authenticate(("PlanSponsorAdmin",))
    plan = get_row("plans", plan_id, "planId")
    plan["fiscal_quarter_index"] = plan["fiscal_quarter_index"] + 1
    index = plan["fiscal_quarter_index"]

    # Sweep 1 — stale training records expire.
    touched_members = set()
    for member in calc.plan_members(plan["id"]):
        for record in calc.member_records(member["id"]):
            if record["status"] in ("COMPLETED", "WAIVED") and \
                    record.get("completed_quarter_index") is not None and \
                    index - record["completed_quarter_index"] >= record["validity_quarters"]:
                record["status"] = "EXPIRED"
                touch(record)
                touched_members.add(member["id"])
    for member_id in touched_members:
        member = store.members.get(member_id)
        if member is not None:
            before = member["fiduciary_training_status"]
            calc.refresh_training_status(member)
            if member["fiduciary_training_status"] != before:
                touch(member)

    # Sweep 2 — abandoned scheduled meetings are voided.
    for meeting in calc.plan_meetings(plan["id"]):
        if meeting["status"] == "SCHEDULED" and meeting["quarter_index"] < index:
            meeting["status"] = "VOID"
            touch(meeting)
            for review in calc.plan_reviews(plan["id"]):
                if review.get("meeting_id") == meeting["id"]:
                    review["meeting_id"] = None
                    touch(review)

    # Sweep 3 — abandoned reviews are voided along with their scorecards.
    for review in calc.plan_reviews(plan["id"]):
        if review["status"] in ("DRAFT", "SCORING") and \
                index - review["quarter_index"] > 1:
            review["status"] = "VOID"
            for card in store.scorecards.values():
                if card["review_id"] == review["id"] and card["status"] == "SUBMITTED":
                    card["status"] = "VOID"
                    touch(card)
            review["submitted_scorecard_count"] = 0
            review["scorecard_count"] = 0
            touch(review)

    # Sweep 4 — levelization runs.
    for run in calc.plan_runs(plan["id"]):
        if run["status"] == "APPROVED" and run["quarter_index"] < index:
            run["status"] = "RECALC_REQUIRED"
            touch(run)
        elif run["status"] == "DRAFT" and index - run["quarter_index"] > 1:
            run["status"] = "VOID"
            touch(run)

    # Sweep 5 — expired terms vacate their seats.
    today = clock.date()
    for member in calc.sort_created(calc.plan_members(plan["id"])):
        if member["status"] not in calc.NON_TERMINAL_MEMBER_STATES:
            continue
        end = parse_date(member["term_end_date"], "term_end_date")
        if end >= today:
            continue
        member["status"] = "TERM_EXPIRED"
        member["end_term_reason"] = "TERM_EXPIRY"
        touch(member)
        seat = store.seats.get(member["seat_id"])
        if seat is not None and seat["status"] == "FILLED":
            seat["status"] = "VACANT"
            touch(seat)
    for seat in calc.plan_seats(plan["id"]):
        if seat["status"] == "VACANT":
            seat["consecutive_vacant_quarters"] = \
                seat.get("consecutive_vacant_quarters", 0) + 1
            touch(seat)

    calc.recompute_posture(plan)
    touch(plan)
    return ok(public(plan))


@bp.route("/governance/plans/<plan_id>/menu-posture/recompute", methods=["POST"])
def recompute_posture(plan_id):
    authenticate(("PlanSponsorAdmin", "InvestmentConsultant"))
    plan = get_row("plans", plan_id, "planId")
    calc.recompute_posture(plan)
    touch(plan)
    return ok(public(plan))
