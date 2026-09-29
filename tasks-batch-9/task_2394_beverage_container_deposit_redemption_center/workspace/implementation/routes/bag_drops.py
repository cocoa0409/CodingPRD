from datetime import timedelta

from flask import Blueprint, request

import calculations as calc
import clock
import db
import response
import validation as v
from db import touch
from errors import fail
from middleware import authenticate, narrow, own, own_bag_drop
from routes.common import (check_version, filter_eq, fk, listing, lookup,
                           require_operational, unique)
from services import projections as proj

bp = Blueprint("bag_drops", __name__)

SETTLEMENT_ACTIONS = ("CREDIT", "DISPUTE", "VOID")
SETTLEMENT_ORIGINS = {
    "CREDIT": ("COUNTED",),
    "DISPUTE": ("COUNTED",),
    "VOID": ("DROPPED", "DISPUTED"),
}
DISPUTE_WINDOW = timedelta(hours=72)


@bp.post("/bag-drops")
def create_bag_drop():
    authenticate("CenterOperator", "ProgramAdmin")
    body = v.body()
    raw_center = body.get("center_id")
    if isinstance(raw_center, str):
        own(center_id=raw_center)
    account = fk("account", body, "account_id")
    center = fk("center", body, "center_id")
    v.req_str(body, "account_id")
    v.req_str(body, "center_id")
    tag_code = v.req_str(body, "tag_code")
    declared = v.req_int(body, "declared_count", minimum=1)

    require_operational(center)

    if account["status"] == "CLOSED":
        fail("ERR_ACCOUNT_CLOSED", "The redeemer account is closed.")
    if account["status"] == "FLAGGED":
        fail("ERR_ACCOUNT_FLAGGED", "The redeemer account is flagged.")
    if not account["bag_drop_enrolled"]:
        fail("ERR_ACCOUNT_NOT_ENROLLED", "The holder is not enrolled in the bag-drop programme.")

    unique(db.bag_drops, "tag_code", tag_code, "ERR_DUPLICATE_TAG_CODE")

    units, credit = calc.provisional_credit(declared)
    rec = db.new_record({
        "account_id": account["id"],
        "center_id": center["id"],
        "tag_code": tag_code,
        "declared_count": declared,
        "dropped_at": clock.now_iso(),
        "status": "DROPPED",
        "provisional_units": units,
        "provisional_credit_cents": credit,
        "counted_lines": 0,
        "counted_total": 0,
        "gross_final_cents": 0,
        "final_credit_cents": 0,
        "adjustment_cents": 0,
        "variance_pct": 0,
        "variance_flag": False,
        "recount_count": 0,
        "settled_at": None,
    })
    db.bag_drops[rec["id"]] = rec
    proj.append_credit_entry(account, "PROVISIONAL", credit, "BAG_DROP", rec["id"])
    return response.obj(db.public(rec), 201)


@bp.get("/bag-drops/<rid>")
def get_bag_drop(rid):
    authenticate("ProgramAdmin", "CenterOperator", "PlantCounter", "AccountHolder")
    rec = db.bag_drops.get(rid)
    if rec is not None:
        own_bag_drop(rec)
    rec = lookup("bag_drop", rid)
    return response.obj(db.public(rec))


@bp.get("/bag-drops")
def list_bag_drops():
    authenticate("ProgramAdmin", "CenterOperator", "PlantCounter", "AccountHolder")
    rows = db.ordered(db.bag_drops)
    for field in ("account_id", "center_id", "status"):
        rows = filter_eq(rows, field, request.args.get(field))
    return listing(rows)


@bp.post("/bag-drops/<rid>/count-results")
def count_results(rid):
    authenticate("PlantCounter", "ProgramAdmin")
    bag = lookup("bag_drop", rid)
    body = v.body()
    quantities = v.req_int_list(body, "counted_quantities", minimum=0)
    expected = v.req_int(body, "expected_bag_drop_version")

    check_version(expected, bag, "ERR_STALE_BAG_DROP_VERSION")

    center = db.centers.get(bag["center_id"])
    require_operational(center)

    if bag["status"] not in ("DROPPED", "DISPUTED"):
        fail("ERR_INVALID_BAG_DROP_STATE",
             "A plant count is not available from %s." % bag["status"])

    result = calc.bag_final(quantities, bag["declared_count"],
                            bag["provisional_credit_cents"])
    bag.update(result)
    bag["status"] = "COUNTED"
    touch(bag)

    if result["variance_flag"]:
        account = db.accounts.get(bag["account_id"])
        if account is not None:
            proj.record_strike(account, "BAG_DROP_VARIANCE")
    return response.obj(db.public(bag))


@bp.post("/bag-drops/<rid>/settlement-actions")
def settlement_action(rid):
    authenticate("CenterOperator", "AccountHolder", "ProgramAdmin")
    bag = db.bag_drops.get(rid)
    if bag is not None:
        own_bag_drop(bag)
    body = v.body()
    raw_action = body.get("action")
    if isinstance(raw_action, str):
        narrow(raw_action, program_admin_only=("VOID",),
               role_actions={"AccountHolder": ("DISPUTE",)})
    bag = lookup("bag_drop", rid)
    action = v.req_enum(body, "action", SETTLEMENT_ACTIONS)
    v.opt_str(body, "reason")

    if bag["status"] not in SETTLEMENT_ORIGINS[action]:
        fail("ERR_INVALID_BAG_DROP_STATE",
             "Action %s is not available from %s." % (action, bag["status"]))

    account = db.accounts.get(bag["account_id"])
    if account is not None:
        if account["status"] == "CLOSED":
            fail("ERR_ACCOUNT_CLOSED", "The redeemer account is closed.")
        if action == "CREDIT" and account["status"] != "ACTIVE":
            fail("ERR_ACCOUNT_FLAGGED", "The redeemer account is not ACTIVE.")

    if action == "DISPUTE":
        dropped = clock.parse_stamp(bag["dropped_at"])
        if dropped is not None and clock.now() >= dropped + DISPUTE_WINDOW:
            fail("ERR_DISPUTE_WINDOW_CLOSED", "The 72-hour dispute window has closed.")
        bag["status"] = "DISPUTED"
        bag["recount_count"] = int(bag["recount_count"]) + 1
        touch(bag)
        return response.obj(db.public(bag))

    if action == "VOID":
        bag["status"] = "VOIDED"
        touch(bag)
        if account is not None:
            proj.append_credit_entry(account, "CLAWBACK",
                                     -bag["provisional_credit_cents"],
                                     "BAG_DROP", bag["id"])
        return response.obj(db.public(bag))

    # CREDIT
    settle_date = clock.today()
    containing = proj.periods_containing(settle_date)
    open_periods = [p for p in containing if p["status"] == "OPEN"]
    if not open_periods:
        fail("ERR_NO_OPEN_PERIOD", "No OPEN reporting quarter covers the settlement date.")
    period = open_periods[0]

    bag["status"] = "CREDITED"
    bag["settled_at"] = clock.now_iso()
    touch(bag)
    if account is not None:
        proj.append_credit_entry(account, "ADJUSTMENT", bag["adjustment_cents"],
                                 "BAG_DROP", bag["id"])
    proj.append_ledger_entry(period, "BAG_DROP_CREDIT", -bag["final_credit_cents"],
                             bag["counted_total"], "BAG_DROP", bag["id"])
    proj.replay_period(period)
    return response.obj(db.public(bag))
