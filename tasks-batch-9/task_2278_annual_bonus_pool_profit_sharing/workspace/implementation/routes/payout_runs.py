"""PayoutRun routes: execution of the payout variant and the settlement true-up."""

from flask import Blueprint

import db
from errors import ApiError
from middleware import (COMPENSATION_COMMITTEE, FINANCE_CONTROLLER, PLAN_ADMIN,
                        authenticate, get_body, opt_string, query_param, req_id)
from response import object_response
from routes.common import paginated
from serialize import payout_run_out
from services import calc, lookup, payout, rollup

bp = Blueprint("payout_runs", __name__)

READ_ROLES = [PLAN_ADMIN, FINANCE_CONTROLLER, COMPENSATION_COMMITTEE]
LIST_ROLES = [PLAN_ADMIN, FINANCE_CONTROLLER]


@bp.route("/payout-runs", methods=["POST"])
def create_payout_run():
    authenticate([FINANCE_CONTROLLER])
    body = get_body()
    plan_id = req_id(body, "plan_id")
    run_note = opt_string(body, "run_note")

    lookup.plan(plan_id)

    if db.plan_payout_runs(plan_id):
        raise ApiError("ERR_PAYOUT_ALREADY_EXECUTED",
                       "This plan already has a payout run")

    run = db.base_record()
    run.update({
        "plan_id": plan_id,
        "run_note": run_note,
        "status": "DRAFT",
        "payment_date_used": None,
        "paid_award_count": 0,
        "deferred_award_count": 0,
        "forfeited_award_count": 0,
        "total_paid_cents": 0,
        "total_forfeited_cents": 0,
        "settlement_burden_cents": 0,
        "true_up_cents": 0,
        "settlement_note": None,
    })
    db.payout_runs[run["id"]] = run
    return object_response(payout_run_out(run), 201)


@bp.route("/payout-runs/<run_id>/execute", methods=["POST"])
def execute_payout_run(run_id):
    authenticate([FINANCE_CONTROLLER])
    run = lookup.payout_run(run_id)
    get_body()

    plan = lookup.plan(run["plan_id"])

    if run["status"] != "DRAFT":
        raise ApiError("ERR_PAYOUT_ALREADY_EXECUTED",
                       "Execution requires a run in DRAFT")
    if plan["status"] != "LOCKED":
        raise ApiError("ERR_PLAN_NOT_LOCKED")
    today = db.logical_today()
    if today < db.as_date(plan["payment_date"]):
        raise ApiError("ERR_PAYMENT_DATE_NOT_REACHED")

    paid_count = deferred_count = forfeited_count = 0
    total_paid = total_forfeited = 0

    for award in db.plan_awards(plan["id"]):
        if award["allocation_status"] != "LOCKED":
            continue
        participant = db.participants.get(award["participant_id"])
        if participant is None:
            continue
        status, amount = payout.payment_outcome(plan, participant, award)
        award["payment_status"] = status
        award["payout_amount_cents"] = amount
        db.touch(award)
        if status == "PAID":
            paid_count += 1
            total_paid += amount
        elif status == "DEFERRED":
            deferred_count += 1
        else:
            forfeited_count += 1
            total_forfeited += award["final_award_cents"]

    run["payment_date_used"] = today.isoformat()
    run["paid_award_count"] = paid_count
    run["deferred_award_count"] = deferred_count
    run["forfeited_award_count"] = forfeited_count
    run["total_paid_cents"] = total_paid
    run["total_forfeited_cents"] = total_forfeited
    run["status"] = "EXECUTED"
    db.touch(run)

    rollup.refresh_payout_totals(plan)
    plan["status"] = "PAID_OUT"
    db.touch(plan)
    return object_response(payout_run_out(run))


@bp.route("/payout-runs/<run_id>/settle-true-up", methods=["POST"])
def settle_true_up(run_id):
    authenticate([FINANCE_CONTROLLER])
    run = lookup.payout_run(run_id)
    body = get_body()
    settlement_note = opt_string(body, "settlement_note")

    plan = lookup.plan(run["plan_id"])

    if run["status"] != "EXECUTED":
        raise ApiError("ERR_PAYOUT_ALREADY_EXECUTED",
                       "Settlement requires a run in EXECUTED")
    if plan["status"] != "PAID_OUT":
        raise ApiError("ERR_PLAN_NOT_LOCKED",
                       "Settlement requires a plan in PAID_OUT")
    if any(a["payment_status"] == "DEFERRED" for a in db.plan_awards(plan["id"])):
        raise ApiError("ERR_DEFERRED_AWARDS_PENDING")

    paid = plan["paid_total_cents"]
    burden = calc.burden_cents(paid, calc.burden_rate_pct(paid))
    true_up = (paid + burden) - plan["accrued_total_cents"]

    run["settlement_burden_cents"] = burden
    run["true_up_cents"] = true_up
    if settlement_note is not None:
        run["settlement_note"] = settlement_note
    run["status"] = "SETTLED"
    db.touch(run)

    plan["settlement_burden_cents"] = burden
    plan["true_up_cents"] = true_up
    plan["status"] = "SETTLED"
    db.touch(plan)
    return object_response(payout_run_out(run))


@bp.route("/payout-runs/<run_id>", methods=["GET"])
def get_payout_run(run_id):
    authenticate(READ_ROLES)
    return object_response(payout_run_out(lookup.payout_run(run_id)))


@bp.route("/payout-runs", methods=["GET"])
def list_payout_runs():
    authenticate(LIST_ROLES)
    records = db.ordered(db.payout_runs)
    for param in ("plan_id", "status"):
        value = query_param(param)
        if value is not None:
            records = [r for r in records if r[param] == value]
    return paginated(records, payout_run_out)
