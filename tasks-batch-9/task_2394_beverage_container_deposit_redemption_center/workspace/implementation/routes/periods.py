from flask import Blueprint, g, request

import calculations as calc
import clock
import db
import response
import validation as v
from db import touch
from errors import fail
from middleware import authenticate
from routes.common import filter_eq, listing, lookup, unique
from services import projections as proj

bp = Blueprint("periods", __name__)

PERIOD_ACTIONS = ("RECONCILE", "REOPEN", "CLOSE")
PERIOD_TRANSITIONS = {
    "RECONCILE": (("OPEN",), "RECONCILING"),
    "REOPEN": (("RECONCILING",), "OPEN"),
    "CLOSE": (("RECONCILING",), "CLOSED"),
}


@bp.post("/program-periods")
def create_period():
    authenticate("ProgramAdmin")
    body = v.body()
    quarter_code = v.req_str(body, "quarter_code", pattern=v.QUARTER_RE)
    start_date = v.req_str(body, "start_date", pattern=v.DATE_RE)
    end_date = v.req_str(body, "end_date", pattern=v.DATE_RE)
    operating_cost = v.opt_int(body, "operating_cost_cents", 0, minimum=0)
    if not (end_date > start_date):
        v.bad("Field 'end_date' must fall strictly after 'start_date'.")

    if proj.periods_overlapping(start_date, end_date):
        fail("ERR_PERIOD_OVERLAP",
             "The requested interval overlaps an existing reporting quarter.")
    unique(db.periods, "quarter_code", quarter_code, "ERR_DUPLICATE_QUARTER_CODE")

    rec = db.new_record({
        "quarter_code": quarter_code,
        "start_date": start_date,
        "end_date": end_date,
        "operating_cost_cents": operating_cost,
        "status": "OPEN",
        "deposits_initiated_cents": 0,
        "containers_initiated_count": 0,
        "redemptions_paid_cents": 0,
        "containers_redeemed_count": 0,
        "material_revenue_cents": 0,
        "handling_fee_cents": 0,
        "gross_unredeemed_cents": 0,
        "admin_shortfall_cents": 0,
        "sweep_to_funding_cents": 0,
        "unredeemed_deposit_cents": 0,
        "funding_balance_cents": 0,
        "outstanding_liability_cents": 0,
        "funding_status": "UNSETTLED",
        "reconciled_at": None,
    })
    db.periods[rec["id"]] = rec
    return response.obj(db.public(rec), 201)


@bp.get("/program-periods/<rid>")
def get_period(rid):
    authenticate("ProgramAdmin")
    rec = lookup("period", rid)
    return response.obj(db.public(rec))


@bp.get("/program-periods")
def list_periods():
    authenticate("ProgramAdmin")
    rows = db.ordered(db.periods)
    rows = filter_eq(rows, "status", request.args.get("status"))
    return listing(rows)


@bp.post("/program-periods/<rid>/period-actions")
def period_action(rid):
    authenticate("ProgramAdmin")
    period = lookup("period", rid)
    body = v.body()
    action = v.req_enum(body, "action", PERIOD_ACTIONS)
    v.opt_str(body, "reason")

    froms, target = PERIOD_TRANSITIONS[action]
    if period["status"] not in froms:
        fail("ERR_INVALID_PERIOD_STATE",
             "Action %s is not available from %s." % (action, period["status"]))

    if action == "RECONCILE":
        for visit in db.ordered(db.visits):
            if (proj.period_contains(period, visit["visit_date"])
                    and visit["count_status"] in proj.OPEN_COUNT_STATES):
                fail("ERR_PERIOD_HAS_OPEN_VISITS",
                     "The quarter still has visits with unfinished counting.")
        period["reconciled_at"] = clock.now_iso()
        proj.replay_period(period)
        settlement = calc.funding_settlement(
            period["deposits_initiated_cents"],
            period["redemptions_paid_cents"],
            period["material_revenue_cents"],
            period["containers_redeemed_count"],
            period["operating_cost_cents"],
        )
        period.update(settlement)
        period["status"] = target
        touch(period)
        proj.append_ledger_entry(period, "HANDLING_FEE",
                                 settlement["handling_fee_cents"], 0,
                                 "PROGRAM_ACTION", g.user_id)
        proj.append_ledger_entry(period, "UNREDEEMED_SWEEP",
                                 -settlement["sweep_to_funding_cents"], 0,
                                 "PROGRAM_ACTION", g.user_id)
        proj.replay_period(period)
        return response.obj(db.public(period))

    if action == "REOPEN":
        proj.append_ledger_entry(period, "HANDLING_FEE",
                                 -period["handling_fee_cents"], 0,
                                 "PROGRAM_ACTION", g.user_id)
        proj.append_ledger_entry(period, "UNREDEEMED_SWEEP",
                                 period["sweep_to_funding_cents"], 0,
                                 "PROGRAM_ACTION", g.user_id)
        period["handling_fee_cents"] = 0
        period["gross_unredeemed_cents"] = 0
        period["admin_shortfall_cents"] = 0
        period["sweep_to_funding_cents"] = 0
        period["unredeemed_deposit_cents"] = 0
        period["funding_balance_cents"] = 0
        period["funding_status"] = "UNSETTLED"
        period["reconciled_at"] = None
        period["status"] = target
        touch(period)
        proj.replay_period(period)
        return response.obj(db.public(period))

    period["status"] = target
    touch(period)
    return response.obj(db.public(period))


@bp.get("/program-periods/<rid>/ledger-entries")
def list_ledger_entries(rid):
    authenticate("ProgramAdmin")
    period = lookup("period", rid)
    rows = proj.period_entries(period["id"])
    rows = filter_eq(rows, "entry_type", request.args.get("entry_type"))
    return listing(rows)
