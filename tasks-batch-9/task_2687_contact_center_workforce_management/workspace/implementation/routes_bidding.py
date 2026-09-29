"""Bid rounds, bids and the seniority award waterfall (PRD 3.5)."""
from datetime import timedelta

from flask import Blueprint, g

import calc
from cascade import (
    mint_shift, recompute_slots_awarded, require_not_frozen, set_fields,
    shifts_of_bid, shifts_of_round,
)
from core import (
    D, bad, body, created, fail, get, maybe, new_row, ok, public, q4, rows,
    require_auth, v_array, v_enum, v_id, v_int, v_string,
)
from listing import std_list

bp = Blueprint("bidding", __name__)

BID_READERS = ["CapacityPlanner", "WorkforceAnalyst", "SchedulingManager",
               "IntradayController", "TeamCoach", "Agent"]


def templates_of_cycle(cycle_id):
    return [t for t in rows("shift_templates") if t["planning_cycle_id"] == cycle_id]


def bids_of_round(round_id):
    return [b for b in rows("shift_bids") if b["bid_round_id"] == round_id]


# ---------------------------------------------------------------------------
# Bid rounds
# ---------------------------------------------------------------------------
@bp.post("/bid-rounds")
def create_bid_round():
    require_auth(["SchedulingManager"])
    b = body()
    cycle_id = v_id(b, "planning_cycle_id")
    code = v_string(b, "code", maxlen=40)
    max_reopen = v_int(b, "max_reopen_count", required=False, minimum=0, default=2)
    cycle = get("planning_cycles", cycle_id)
    for other in rows("bid_rounds"):
        if other["planning_cycle_id"] == cycle["id"] and other["code"] == code:
            bad("code", "must be unique within the planning cycle")
    require_not_frozen(cycle)
    row = new_row("bid_rounds", {
        "planning_cycle_id": cycle["id"],
        "code": code,
        "max_reopen_count": max_reopen,
        "status": "DRAFT",
        "reopen_count": 0,
        "preference_honor_rate": None,
        "awarded_bid_count": 0,
        "unfilled_bid_count": 0,
    })
    return created(public(row))


@bp.get("/bid-rounds/<bid_round_id>")
def read_bid_round(bid_round_id):
    require_auth(BID_READERS)
    return ok(public(get("bid_rounds", bid_round_id)))


@bp.get("/bid-rounds")
def list_bid_rounds():
    require_auth(BID_READERS)
    return std_list("bid_rounds", [
        ("planning_cycle_id", "planning_cycle_id"),
        ("status", "status"),
    ])


def recompute_round_counts(rnd):
    awarded = 0
    unfilled = 0
    for bid in bids_of_round(rnd["id"]):
        if bid["status"] == "AWARDED":
            awarded += 1
        elif bid["status"] == "UNFILLED":
            unfilled += 1
    set_fields(rnd, {"awarded_bid_count": awarded, "unfilled_bid_count": unfilled})


@bp.post("/bid-rounds/<bid_round_id>/status")
def drive_bid_round(bid_round_id):
    require_auth(["SchedulingManager"])
    b = body()
    target = v_enum(b, "target_status", ("DRAFT", "OPEN", "SCORING", "AWARDED", "CANCELLED"))
    rnd = get("bid_rounds", bid_round_id)
    cycle = get("planning_cycles", rnd["planning_cycle_id"])
    require_not_frozen(cycle)
    current = rnd["status"]
    if current == "DRAFT" and target == "OPEN":
        if cycle["posture"] not in ("OPEN", "REQUIREMENTS_LOCKED"):
            fail("ERR_INVALID_STATE", "The cycle posture does not admit opening a round")
        if not templates_of_cycle(cycle["id"]):
            fail("ERR_INVALID_STATE", "The cycle holds no shift template to bid on")
        set_fields(rnd, {"status": "OPEN"})
    elif current == "OPEN" and target == "SCORING":
        if not any(x["status"] == "SUBMITTED" for x in bids_of_round(rnd["id"])):
            fail("ERR_INVALID_STATE", "The round holds no submitted bid")
        set_fields(rnd, {"status": "SCORING"})
    elif current == "SCORING" and target == "OPEN":
        if int(rnd["reopen_count"]) >= int(rnd["max_reopen_count"]):
            fail("ERR_REOPEN_LIMIT_REACHED", "The round has exhausted its reopen allowance")
        set_fields(rnd, {"status": "OPEN", "reopen_count": int(rnd["reopen_count"]) + 1})
    elif current == "AWARDED" and target == "OPEN":
        if int(rnd["reopen_count"]) >= int(rnd["max_reopen_count"]):
            fail("ERR_REOPEN_LIMIT_REACHED", "The round has exhausted its reopen allowance")
        for shift in shifts_of_round(rnd["id"]):
            if shift["publication_status"] == "PUBLISHED":
                fail("ERR_INVALID_STATE", "The round already minted a published shift")
        reopen_round(rnd)
    elif target == "CANCELLED" and current in ("DRAFT", "OPEN", "SCORING"):
        set_fields(rnd, {"status": "CANCELLED"})
        if current in ("OPEN", "SCORING"):
            for bid in bids_of_round(rnd["id"]):
                if bid["status"] == "SUBMITTED":
                    set_fields(bid, {"status": "WITHDRAWN"})
    else:
        fail("ERR_INVALID_STATE", "%s is not reachable from %s" % (target, current))
    return ok(public(rnd))


def reopen_round(rnd):
    set_fields(rnd, {"status": "OPEN", "reopen_count": int(rnd["reopen_count"]) + 1})
    templates = {}
    for bid in bids_of_round(rnd["id"]):
        if bid["status"] not in ("AWARDED", "UNFILLED"):
            continue
        if bid["awarded_shift_template_id"] is not None:
            tpl = maybe("shift_templates", bid["awarded_shift_template_id"])
            if tpl is not None:
                templates[tpl["id"]] = tpl
        set_fields(bid, {
            "status": "SUBMITTED",
            "awarded_shift_template_id": None,
            "awarded_preference_index": None,
        })
        for shift in shifts_of_bid(bid["id"]):
            if shift["publication_status"] == "DRAFT":
                set_fields(shift, {"publication_status": "CANCELLED"})
    set_fields(rnd, {
        "preference_honor_rate": None,
        "awarded_bid_count": 0,
        "unfilled_bid_count": 0,
    })
    for tpl in templates.values():
        recompute_slots_awarded(tpl)


# ---------------------------------------------------------------------------
# The award waterfall
# ---------------------------------------------------------------------------
def horizon_dates(cycle):
    out = {}
    day = cycle["_horizon_start"]
    index = 0
    while day <= cycle["_horizon_end"]:
        out[day.weekday()] = day
        day = day + timedelta(days=1)
        index += 1
    return out


@bp.post("/bid-rounds/<bid_round_id>/award")
def award_bid_round(bid_round_id):
    require_auth(["SchedulingManager"])
    rnd = get("bid_rounds", bid_round_id)
    cycle = get("planning_cycles", rnd["planning_cycle_id"])
    require_not_frozen(cycle)
    if rnd["status"] != "SCORING":
        fail("ERR_INVALID_STATE", "An award run is only reachable from SCORING")

    templates = {t["id"]: t for t in templates_of_cycle(cycle["id"])}
    remaining = {
        t_id: int(t["slots_total"]) - int(t["slots_awarded"])
        for t_id, t in templates.items()
    }
    candidates = [b for b in bids_of_round(rnd["id"]) if b["status"] == "SUBMITTED"]
    ordered = sorted(
        candidates,
        key=lambda b: (
            int(get("agents", b["agent_id"])["seniority_rank"]),
            b["created_at"],
            b["_seq"],
        ),
    )
    placements = []   # (bid, template, preference_index)
    losers = []
    for bid in ordered:
        agent = get("agents", bid["agent_id"])
        placed = False
        if agent["status"] == "ACTIVE":
            for index, template_id in enumerate(bid["preference_template_ids"]):
                tpl = templates.get(template_id)
                if tpl is None:
                    continue
                if tpl["skill_code"] not in agent["skills"]:
                    continue
                if remaining.get(template_id, 0) <= 0:
                    continue
                remaining[template_id] -= 1
                placements.append((bid, tpl, index))
                placed = True
                break
        if not placed:
            losers.append(bid)

    if not placements:
        fail("ERR_TEMPLATE_SLOTS_EXHAUSTED",
             "No submitted bid of the round can be placed on a template with a free slot")

    first_choice = sum(1 for _, _, index in placements if index == 0)
    honor_rate = q4(D(first_choice) / D(len(placements)))
    floor = None
    for bid, _, _ in placements:
        agreement = get("labor_agreements", get("agents", bid["agent_id"])["labor_agreement_id"])
        value = D(agreement["preference_honor_floor_pct"])
        floor = value if floor is None else min(floor, value)
    if floor is not None and honor_rate < floor:
        fail("ERR_PREFERENCE_FLOOR_NOT_MET",
             "Preference honor rate %s is below the strictest agreement floor %s"
             % (honor_rate, floor))

    by_weekday = horizon_dates(cycle)
    touched_templates = {}
    for bid, tpl, index in placements:
        set_fields(bid, {
            "status": "AWARDED",
            "awarded_shift_template_id": tpl["id"],
            "awarded_preference_index": index,
        })
        agent = get("agents", bid["agent_id"])
        touched_templates[tpl["id"]] = tpl
        for weekday in tpl["days_of_week"]:
            service_date = by_weekday.get(int(weekday))
            if service_date is None:
                continue
            mint_shift(cycle, agent, tpl, service_date, shift_bid_id=bid["id"])
    for bid in losers:
        set_fields(bid, {"status": "UNFILLED"})
    set_fields(rnd, {"status": "AWARDED", "preference_honor_rate": honor_rate})
    for tpl in touched_templates.values():
        recompute_slots_awarded(tpl)
    recompute_round_counts(rnd)
    return ok(public(rnd))


# ---------------------------------------------------------------------------
# Shift bids
# ---------------------------------------------------------------------------
@bp.post("/shift-bids")
def create_shift_bid():
    require_auth(["Agent"])
    b = body()
    round_id = v_id(b, "bid_round_id")
    agent_id = v_id(b, "agent_id")
    preferences = v_array(b, "preference_template_ids", minlen=1, maxlen=10)
    seen = set()
    for item in preferences:
        if not isinstance(item, str) or item == "":
            bad("preference_template_ids", "must contain shift template identifiers")
        if item in seen:
            bad("preference_template_ids", "must contain distinct shift template identifiers")
        seen.add(item)
    rnd = get("bid_rounds", round_id)
    agent = get("agents", agent_id)
    templates = [get("shift_templates", t_id) for t_id in preferences]
    for tpl in templates:
        if tpl["planning_cycle_id"] != rnd["planning_cycle_id"]:
            bad("preference_template_ids",
                "must reference templates of the round's own planning cycle")
    if agent["id"] != g.user_id:
        fail("ERR_OWNERSHIP_VIOLATION", "An agent may only submit their own bid")
    cycle = get("planning_cycles", rnd["planning_cycle_id"])
    require_not_frozen(cycle)
    if rnd["status"] != "OPEN":
        fail("ERR_BID_ROUND_NOT_OPEN", "The bid round is not open for intake")
    for tpl in templates:
        if tpl["skill_code"] not in agent["skills"]:
            fail("ERR_SKILL_MISMATCH",
                 "The bidder does not hold skill %s" % tpl["skill_code"])
    for other in bids_of_round(rnd["id"]):
        if other["agent_id"] == agent["id"] and other["status"] != "WITHDRAWN":
            fail("ERR_DUPLICATE_BID", "The bidder already holds a live bid in this round")
    row = new_row("shift_bids", {
        "bid_round_id": rnd["id"],
        "agent_id": agent["id"],
        "awarded_shift_template_id": None,
        "preference_template_ids": preferences,
        "awarded_preference_index": None,
        "status": "SUBMITTED",
    })
    return created(public(row))


@bp.get("/shift-bids/<shift_bid_id>")
def read_shift_bid(shift_bid_id):
    require_auth(BID_READERS)
    return ok(public(get("shift_bids", shift_bid_id)))


@bp.get("/shift-bids")
def list_shift_bids():
    require_auth(BID_READERS)
    return std_list("shift_bids", [
        ("bid_round_id", "bid_round_id"),
        ("agent_id", "agent_id"),
        ("awarded_shift_template_id", "awarded_shift_template_id"),
        ("status", "status"),
    ])


@bp.post("/shift-bids/<shift_bid_id>/withdraw")
def withdraw_shift_bid(shift_bid_id):
    require_auth(["Agent"])
    bid = get("shift_bids", shift_bid_id)
    if bid["agent_id"] != g.user_id:
        fail("ERR_OWNERSHIP_VIOLATION", "An agent may only withdraw their own bid")
    rnd = get("bid_rounds", bid["bid_round_id"])
    cycle = get("planning_cycles", rnd["planning_cycle_id"])
    require_not_frozen(cycle)
    if rnd["status"] != "OPEN":
        fail("ERR_BID_ROUND_NOT_OPEN", "The bid round is not open")
    if bid["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", "Only a submitted bid may be withdrawn")
    set_fields(bid, {"status": "WITHDRAWN"})
    return ok(public(bid))
