"""Contest endpoints: skill contests, prize insurance and awards (PRD 3.6)."""

from flask import Blueprint

import calc
import derive
import enums
import serial
import store
import validate
from auth import (CHARITY_TREASURER, PARTICIPANT, SPONSORSHIP_MANAGER,
                  TOURNAMENT_DIRECTOR, auth)
from envelope import created, ok, paginate
from errors import fail
from lookup import contest as get_contest
from lookup import outing as get_outing
from lookup import player as get_player
from store import touch

bp = Blueprint("contests", __name__)

READ_ROLES = (TOURNAMENT_DIRECTOR, SPONSORSHIP_MANAGER, CHARITY_TREASURER,
              PARTICIPANT)

CREATE_FIELDS = ("outing_id", "contest_type", "hole_number",
                 "prize_value_cents", "yardage", "prize_form")


@bp.post("/outing-ops/contests")
def create_contest():
    auth((TOURNAMENT_DIRECTOR,))
    body = validate.body()
    validate.only_fields(body, CREATE_FIELDS)
    outing_id = validate.req_ref(body, "outing_id")
    contest_type = validate.req_enum(body, "contest_type", enums.CONTEST_TYPE)
    hole_number = validate.req_int(body, "hole_number", minimum=1, maximum=18)
    prize_value = validate.req_money(body, "prize_value_cents")
    yardage = validate.opt_int(body, "yardage", minimum=0)
    prize_form = validate.opt_enum(body, "prize_form", enums.PRIZE_FORM,
                                   default="MERCHANDISE_CREDIT")
    get_outing(outing_id)
    for other in derive.contests_of(outing_id):
        if other["hole_number"] == hole_number and other["status"] != "VOID":
            fail("ERR_CONTEST_HOLE_CONFLICT",
                 "Hole %d already holds a live contest." % hole_number)
    requires_insurance = (contest_type == "HOLE_IN_ONE"
                          and prize_value >= calc.INSURANCE_REQUIRED_THRESHOLD_CENTS)
    row = store.new_row("Contest", {
        "outing_id": outing_id,
        "contest_type": contest_type,
        "hole_number": hole_number,
        "yardage": yardage,
        "prize_value_cents": prize_value,
        "prize_form": prize_form,
        "requires_insurance": requires_insurance,
        "status": "PLANNED",
        "insurance_status": "NONE",
        "insurance_carrier": None,
        "insurance_premium_cents": 0,
        "insurance_coverage_cap_cents": 0,
        "insurance_min_yardage": calc.DEFAULT_INSURANCE_MIN_YARDAGE,
        "insurance_required_witness_count": calc.DEFAULT_INSURANCE_WITNESS_COUNT,
        "insurance_bound_at": None,
        "winner_player_id": None,
        "witness_count": 0,
        "award_form": None,
        "awarded_value_cents": 0,
        "insurance_recovery_cents": 0,
        "contest_payout_cents": 0,
        "claim_denial_reason": "NONE",
    })
    return created(serial.dump(row))


@bp.get("/outing-ops/contests/<row_id>")
def read_contest(row_id):
    auth(READ_ROLES)
    return ok(serial.dump(get_contest(row_id)))


@bp.get("/outing-ops/contests")
def list_contests():
    auth(READ_ROLES)
    limit, offset = validate.page_params()
    outing_id = validate.q_str("outing_id")
    winner_player_id = validate.q_str("winner_player_id")
    contest_type = validate.q_enum("contest_type", enums.CONTEST_TYPE)
    status = validate.q_enum("status", enums.CONTEST_STATUS)
    insurance_status = validate.q_enum("insurance_status", enums.INSURANCE_STATUS)
    rows = store.sorted_rows(store.contests.values())
    if outing_id is not None:
        rows = [r for r in rows if r["outing_id"] == outing_id]
    if winner_player_id is not None:
        rows = [r for r in rows if r["winner_player_id"] == winner_player_id]
    if contest_type is not None:
        rows = [r for r in rows if r["contest_type"] == contest_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if insurance_status is not None:
        rows = [r for r in rows if r["insurance_status"] == insurance_status]
    return paginate(rows, limit, offset, serial.dump)


@bp.post("/outing-ops/contests/<row_id>/insurance")
def bind_insurance(row_id):
    auth((SPONSORSHIP_MANAGER,))
    body = validate.body()
    validate.only_fields(body, ("insurance_carrier", "insurance_premium_cents",
                                "insurance_coverage_cap_cents",
                                "insurance_min_yardage",
                                "insurance_required_witness_count"))
    carrier = validate.req_str(body, "insurance_carrier")
    premium = validate.req_money(body, "insurance_premium_cents")
    cap = validate.req_money(body, "insurance_coverage_cap_cents")
    min_yardage = validate.opt_int(
        body, "insurance_min_yardage",
        default=calc.DEFAULT_INSURANCE_MIN_YARDAGE, minimum=0)
    witnesses = validate.opt_int(
        body, "insurance_required_witness_count",
        default=calc.DEFAULT_INSURANCE_WITNESS_COUNT, minimum=0)
    contest = get_contest(row_id)
    if contest["insurance_status"] != "NONE":
        fail("ERR_INVALID_STATE_TRANSITION",
             "The insurance dimension has left NONE.")
    if contest["status"] not in ("PLANNED", "OPEN"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "A %s contest cannot be insured." % contest["status"])
    if cap < 1:
        fail("ERR_INVALID_REQUEST", "The coverage cap must be at least 1 cent.")
    contest["insurance_status"] = "BOUND"
    contest["insurance_carrier"] = carrier
    contest["insurance_premium_cents"] = premium
    contest["insurance_coverage_cap_cents"] = cap
    contest["insurance_min_yardage"] = min_yardage
    contest["insurance_required_witness_count"] = witnesses
    contest["insurance_bound_at"] = store.now_iso()
    touch(contest)
    outing = store.outings.get(contest["outing_id"])
    if outing is not None:
        derive.run_rollup(outing)
    return ok(serial.dump(contest))


@bp.post("/outing-ops/contests/<row_id>/status")
def contest_status(row_id):
    auth((TOURNAMENT_DIRECTOR,))
    body = validate.body()
    validate.only_fields(body, ("action",))
    action = validate.req_enum(body, "action", enums.CONTEST_ACTIONS)
    contest = get_contest(row_id)
    outing = store.outings.get(contest["outing_id"])
    play = outing["play_status"] if outing is not None else None
    if action == "OPEN":
        if contest["status"] != "PLANNED":
            fail("ERR_INVALID_STATE_TRANSITION",
                 "OPEN is not an edge out of %s." % contest["status"])
        if play not in ("OPEN", "FIELD_LOCKED"):
            fail("ERR_INVALID_STATE_TRANSITION",
                 "The outing's play dimension is %s." % play)
        if contest["requires_insurance"] and contest["insurance_status"] != "BOUND":
            fail("ERR_INSURANCE_NOT_BOUND",
                 "The advertised ace prize requires a bound policy.")
        contest["status"] = "OPEN"
    elif action == "CLOSE":
        if contest["status"] != "OPEN":
            fail("ERR_INVALID_STATE_TRANSITION",
                 "CLOSE is not an edge out of %s." % contest["status"])
        if play not in ("IN_PLAY", "SCORED"):
            fail("ERR_INVALID_STATE_TRANSITION",
                 "The outing's play dimension is %s." % play)
        contest["status"] = "CLOSED"
    else:
        if contest["status"] not in ("PLANNED", "OPEN", "CLOSED"):
            fail("ERR_INVALID_STATE_TRANSITION",
                 "VOID is not an edge out of %s." % contest["status"])
        contest["status"] = "VOID"
        if contest["insurance_status"] == "BOUND":
            contest["insurance_status"] = "EXPIRED"
    touch(contest)
    return ok(serial.dump(contest))


@bp.post("/outing-ops/contests/<row_id>/award")
def award_contest(row_id):
    auth((TOURNAMENT_DIRECTOR,))
    body = validate.body()
    validate.only_fields(body, ("winner_player_id", "witness_count"))
    winner_id = validate.req_ref(body, "winner_player_id")
    witness_count = validate.opt_int(body, "witness_count", default=0, minimum=0)
    contest = get_contest(row_id)
    winner = get_player(winner_id)
    reg = derive.registration_of_player(winner)
    if reg is None or reg["outing_id"] != contest["outing_id"]:
        fail("ERR_CROSS_OUTING_REFERENCE",
             "The winner plays in another outing.")
    if contest["status"] != "CLOSED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "AWARD is not an edge out of %s." % contest["status"])

    # the amateur rule governs the form, never the amount
    if winner["amateur_status"] == "AMATEUR":
        if contest["prize_form"] == "CASH":
            if contest["prize_value_cents"] > calc.AMATEUR_CASH_CAP_CENTS:
                fail("ERR_AMATEUR_CASH_CAP_EXCEEDED",
                     "An amateur may not take more than %d cents in cash."
                     % calc.AMATEUR_CASH_CAP_CENTS)
            award_form = "CASH"
        else:
            award_form = "MERCHANDISE_CREDIT"
    else:
        award_form = contest["prize_form"]

    contest["status"] = "AWARDED"
    contest["winner_player_id"] = winner_id
    contest["witness_count"] = witness_count
    contest["award_form"] = award_form
    contest["awarded_value_cents"] = contest["prize_value_cents"]

    # the insurance claim, adjudicated only for a hole in one
    recovery = 0
    if contest["contest_type"] == "HOLE_IN_ONE":
        if contest["insurance_status"] == "BOUND":
            yardage = contest["yardage"]
            if yardage is None or yardage < contest["insurance_min_yardage"]:
                contest["insurance_status"] = "CLAIM_DENIED"
                contest["claim_denial_reason"] = "YARDAGE_BELOW_MINIMUM"
            elif witness_count < contest["insurance_required_witness_count"]:
                contest["insurance_status"] = "CLAIM_DENIED"
                contest["claim_denial_reason"] = "INSUFFICIENT_WITNESSES"
            elif contest["awarded_value_cents"] > contest["insurance_coverage_cap_cents"]:
                contest["insurance_status"] = "CLAIM_DENIED"
                contest["claim_denial_reason"] = "COVERAGE_CAP_EXCEEDED"
            else:
                contest["insurance_status"] = "CLAIM_PAID"
                contest["claim_denial_reason"] = "NONE"
                recovery = min(contest["awarded_value_cents"],
                               contest["insurance_coverage_cap_cents"])
        else:
            contest["claim_denial_reason"] = "NO_POLICY"
    contest["insurance_recovery_cents"] = recovery
    contest["contest_payout_cents"] = contest["awarded_value_cents"] - recovery
    touch(contest)
    outing = store.outings.get(contest["outing_id"])
    if outing is not None:
        derive.run_rollup(outing)
    return ok(serial.dump(contest))
