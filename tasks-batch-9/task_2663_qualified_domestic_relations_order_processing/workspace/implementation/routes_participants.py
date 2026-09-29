"""Participants, plan accounts, money sources and valuation snapshots."""
from flask import Blueprint

import auth
import enums
import errors
import services
import validation as v
from auth import endpoint
from envelope import object_response, paginate
from store import db, order_by, public, public_list
from timeutil import fmt_date

bp = Blueprint("participants", __name__)


def find_participant(participant_id):
    participant = db.participants.get(participant_id)
    if participant is None:
        errors.fail(errors.ERR_PARTICIPANT_NOT_FOUND, "No participant with that id.")
    return participant


def find_plan_account(account_id):
    account = db.plan_accounts.get(account_id)
    if account is None:
        errors.fail(errors.ERR_PLAN_ACCOUNT_NOT_FOUND, "No plan account with that id.")
    return account


@bp.route("/participants", methods=["POST"])
@endpoint("PlanAdministrator")
def enrol_participant(caller):
    data = v.body()
    plan_id = v.req_string(data, "plan_id", 1, 200)
    fields = {
        "plan_id": plan_id,
        "full_name": v.req_string(data, "full_name", 1, 120),
        "ssn_last4": v.req_string(data, "ssn_last4", 4, 4),
        "date_of_birth": v.req_date(data, "date_of_birth"),
        "participation_start_date": v.req_date(data, "participation_start_date"),
        "employment_status": v.opt_enum(
            data, "employment_status", enums.EMPLOYMENT_STATUSES, "ACTIVE"),
        "benefit_commenced": v.opt_bool(data, "benefit_commenced", False),
    }
    if not (len(fields["ssn_last4"]) == 4 and fields["ssn_last4"].isdigit()
            and fields["ssn_last4"].isascii()):
        errors.bad_request("Field 'ssn_last4' must be exactly four ASCII digits.")
    if fields["participation_start_date"] > db.today():
        errors.bad_request("Field 'participation_start_date' may not be later than today.")
    fields["date_of_birth"] = fmt_date(fields["date_of_birth"])
    fields["participation_start_date"] = fmt_date(fields["participation_start_date"])
    plan = db.plans.get(plan_id)
    if plan is None:
        errors.fail(errors.ERR_PLAN_NOT_FOUND, "No plan with that id.")
    participant = db.new_row("Participant", fields)
    db.participants[participant["id"]] = participant
    plan["participant_count"] = len(
        [r for r in db.participants.values() if r["plan_id"] == plan["id"]])
    db.touch(plan)
    return object_response(public(participant), 201)


@bp.route("/participants/<id>", methods=["GET"])
@endpoint("PlanAdministrator", "QdroAnalyst", "Participant")
def read_participant(caller, id):
    participant = find_participant(id)
    auth.own_participant(caller, participant["id"])
    return object_response(public(participant))


@bp.route("/participants/<id>/plan-accounts", methods=["POST"])
@endpoint("PlanAdministrator")
def open_plan_account(caller, id):
    data = v.body()
    monthly_payment_cents = v.opt_int(data, "monthly_payment_cents", 0, None, 0)
    participant = find_participant(id)
    if services.plan_account_of_participant(participant["id"]) is not None:
        errors.fail(errors.ERR_PLAN_ACCOUNT_ALREADY_EXISTS,
                    "This participant already holds a plan account.")
    account = db.new_row("PlanAccount", {
        "participant_id": participant["id"],
        "monthly_payment_cents": monthly_payment_cents,
        "vested_balance_cents": 0,
        "assignable_base_cents": 0,
        "after_tax_basis_cents": 0,
        "held_amount_cents": 0,
        "available_balance_cents": 0,
    })
    db.plan_accounts[account["id"]] = account
    services.recompute_plan_account(account)
    return object_response(public(account), 201)


@bp.route("/participants/<id>/plan-accounts", methods=["GET"])
@endpoint("PlanAdministrator", "QdroAnalyst", "Participant")
def list_plan_accounts(caller, id):
    participant = find_participant(id)
    auth.own_participant(caller, participant["id"])
    rows = [r for r in db.plan_accounts.values() if r["participant_id"] == participant["id"]]
    return paginate(public_list(order_by(rows, "created_at")))


@bp.route("/plan-accounts/<id>", methods=["GET"])
@endpoint("PlanAdministrator", "QdroAnalyst", "Participant")
def read_plan_account(caller, id):
    account = find_plan_account(id)
    auth.own_plan_account(caller, account)
    return object_response(public(account))


@bp.route("/plan-accounts/<id>/money-sources", methods=["POST"])
@endpoint("PlanAdministrator")
def add_money_source(caller, id):
    data = v.body()
    source_code = v.req_enum(data, "source_code", enums.SOURCE_CODES)
    balance_cents = v.req_int(data, "balance_cents", 0, None)
    basis_cents = v.opt_int(data, "basis_cents", 0, None, 0)
    is_assignable = v.opt_bool(data, "is_assignable", True)
    if basis_cents > balance_cents:
        errors.bad_request("Field 'basis_cents' may not exceed 'balance_cents'.")
    account = find_plan_account(id)
    for existing in services.money_sources_of(account["id"]):
        if existing["source_code"] == source_code:
            errors.fail(errors.ERR_MONEY_SOURCE_DUPLICATE,
                        "This account already holds a %s source." % source_code)
    source = db.new_row("MoneySource", {
        "plan_account_id": account["id"],
        "source_code": source_code,
        "balance_cents": balance_cents,
        "basis_cents": basis_cents,
        "is_assignable": is_assignable,
    })
    db.money_sources[source["id"]] = source
    services.recompute_plan_account(account, force=True)
    return object_response(public(source), 201)


@bp.route("/plan-accounts/<id>/money-sources", methods=["GET"])
@endpoint("PlanAdministrator", "QdroAnalyst", "Participant")
def list_money_sources(caller, id):
    account = find_plan_account(id)
    auth.own_plan_account(caller, account)
    return paginate(public_list(services.money_sources_of(account["id"])))


@bp.route("/plan-accounts/<id>/valuation-snapshots", methods=["POST"])
@endpoint("PlanAdministrator")
def add_valuation_snapshot(caller, id):
    data = v.body()
    as_of_date = v.req_date(data, "as_of_date")
    balance_cents = v.req_int(data, "balance_cents", 0, None)
    source = v.req_enum(data, "source", enums.SNAPSHOT_SOURCES)
    account = find_plan_account(id)
    as_of_text = fmt_date(as_of_date)
    for existing in services.snapshots_of(account["id"]):
        if existing["as_of_date"] == as_of_text:
            errors.fail(errors.ERR_SNAPSHOT_DUPLICATE,
                        "This account already holds a snapshot as of %s." % as_of_text)
    snapshot = db.new_row("ValuationSnapshot", {
        "plan_account_id": account["id"],
        "as_of_date": as_of_text,
        "balance_cents": balance_cents,
        "source": source,
    })
    db.valuation_snapshots[snapshot["id"]] = snapshot
    return object_response(public(snapshot), 201)


@bp.route("/plan-accounts/<id>/valuation-snapshots", methods=["GET"])
@endpoint("PlanAdministrator", "QdroAnalyst")
def list_valuation_snapshots(caller, id):
    as_of_date = v.query_date("as_of_date")
    account = find_plan_account(id)
    rows = services.snapshots_of(account["id"])
    if as_of_date is not None:
        rows = [r for r in rows if r["as_of_date"] == as_of_date]
    return paginate(public_list(rows))
