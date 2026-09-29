from flask import Blueprint, request

import calculations as calc
import clock
import db
import response
import validation as v
from db import touch
from errors import fail
from middleware import authenticate, narrow, own, own_visit
from routes.common import (check_version, filter_eq, fk, listing, lookup,
                           require_obligated, require_operational)
from services import projections as proj

bp = Blueprint("visits", __name__)

PAYOUT_ACTIONS = ("APPROVE", "PAY", "REVERSE", "RELEASE_HOLD", "WITHHOLD")
PAYOUT_ADMIN_ONLY = ("RELEASE_HOLD", "REVERSE")
PAYOUT_ORIGINS = {
    "APPROVE": ("PENDING",),
    "PAY": ("APPROVED",),
    "REVERSE": ("PAID",),
    "RELEASE_HOLD": ("WITHHELD",),
    "WITHHOLD": ("PENDING",),
}


@bp.post("/redemption-visits")
def create_visit():
    authenticate("CenterOperator", "RetailClerk", "ProgramAdmin")
    body = v.body()
    own(center_id=body.get("center_id") if isinstance(body.get("center_id"), str) else None,
        retailer_id=body.get("retailer_id") if isinstance(body.get("retailer_id"), str) else None,
        account_id=None)
    center = fk("center", body, "center_id")
    retailer = fk("retailer", body, "retailer_id")
    account = fk("account", body, "account_id")
    machine = fk("machine", body, "machine_id")

    site_type = v.req_enum(body, "site_type", ("CENTER", "RETAILER"))
    channel = v.req_enum(body, "channel", ("MACHINE_COUNT", "HAND_COUNT"))
    if site_type == "CENTER":
        v.req_str(body, "center_id")
        v.absent(body, "retailer_id", "on a CENTER visit")
    else:
        v.req_str(body, "retailer_id")
        v.absent(body, "center_id", "on a RETAILER visit")
        if channel != "HAND_COUNT":
            v.bad("A RETAILER visit is always hand-counted.")
    if channel == "MACHINE_COUNT":
        v.req_str(body, "machine_id")
    else:
        v.absent(body, "machine_id", "on a HAND_COUNT visit")
    if "account_id" in body and body["account_id"] is not None:
        v.req_str(body, "account_id")

    if site_type == "CENTER":
        require_operational(center)
    else:
        require_obligated(retailer)

    if account is not None:
        if account["status"] == "CLOSED":
            fail("ERR_ACCOUNT_CLOSED", "The redeemer account is closed.")
        if account["status"] == "FLAGGED":
            fail("ERR_ACCOUNT_FLAGGED", "The redeemer account is flagged.")

    if machine is not None and machine["center_id"] != (center["id"] if center else None):
        fail("ERR_MACHINE_CENTER_MISMATCH",
             "The named machine does not belong to the visit's centre.")

    rec = db.new_record({
        "site_type": site_type,
        "center_id": center["id"] if center else None,
        "retailer_id": retailer["id"] if retailer else None,
        "account_id": account["id"] if account else None,
        "machine_id": machine["id"] if machine else None,
        "channel": channel,
        "visit_date": clock.today(),
        "count_status": "OPEN",
        "payout_status": "PENDING",
        "presented_total": 0,
        "out_of_state_marked_total": 0,
        "raw_accepted_count": 0,
        "out_of_state_ratio": 0,
        "visit_limit_applied": 0,
        "capped_count": 0,
        "shrink_adjustment_count": 0,
        "payable_count": 0,
        "refused_over_limit_count": 0,
        "payout_cents": 0,
        "fraud_hold": False,
        "withhold_reason": None,
        "requires_manual_recount": False,
        "jam_events_count": 0,
        "counted_at": None,
        "paid_at": None,
    })
    db.visits[rec["id"]] = rec
    return response.obj(db.public(rec), 201)


@bp.get("/redemption-visits/<rid>")
def get_visit(rid):
    authenticate("ProgramAdmin", "CenterOperator", "RetailClerk", "AccountHolder")
    rec = db.visits.get(rid)
    if rec is not None:
        own_visit(rec)
    rec = lookup("visit", rid)
    return response.obj(db.public(rec))


@bp.get("/redemption-visits")
def list_visits():
    authenticate("ProgramAdmin", "CenterOperator", "RetailClerk", "AccountHolder")
    rows = db.ordered(db.visits)
    for field in ("center_id", "retailer_id", "account_id", "machine_id",
                  "count_status", "payout_status", "visit_date"):
        rows = filter_eq(rows, field, request.args.get(field))
    return listing(rows)


def _refresh_visit_rollups(visit):
    lots = proj.visit_lots(visit["id"])
    presented = sum(l["presented_quantity"] for l in lots)
    out_of_state = sum(l["out_of_state_marked_quantity"] for l in lots)
    accepted = sum(l["accepted_quantity"] for l in lots)
    visit["presented_total"] = presented
    visit["out_of_state_marked_total"] = out_of_state
    visit["raw_accepted_count"] = accepted
    visit["out_of_state_ratio"] = float(calc.ratio_4dp(out_of_state, presented))


@bp.post("/redemption-visits/<rid>/lots")
def add_lot(rid):
    authenticate("CenterOperator", "RetailClerk", "ProgramAdmin")
    visit = db.visits.get(rid)
    if visit is not None:
        own_visit(visit)
    visit = lookup("visit", rid)
    body = v.body()
    product = fk("product", body, "product_id")
    if product is not None:
        own(distributor_id=product.get("distributor_id"))

    v.req_str(body, "product_id")
    presented = v.req_int(body, "presented_quantity", minimum=1)
    out_of_state = v.opt_int(body, "out_of_state_marked_quantity", 0,
                             minimum=0, maximum=presented)
    contaminated = v.opt_int(body, "contaminated_quantity", 0,
                             minimum=0, maximum=presented)
    expected = v.req_int(body, "expected_visit_version")

    if out_of_state + contaminated > presented:
        fail("ERR_LOT_QUANTITY_INCONSISTENT",
             "The disqualified quantities exceed the presented quantity.")

    check_version(expected, visit, "ERR_STALE_VISIT_VERSION")

    center = db.centers.get(visit["center_id"]) if visit["center_id"] else None
    retailer = db.retailers.get(visit["retailer_id"]) if visit["retailer_id"] else None
    if visit["site_type"] == "CENTER":
        require_operational(center)
    else:
        require_obligated(retailer)

    if visit["count_status"] not in ("OPEN", "COUNTING"):
        fail("ERR_INVALID_COUNT_STATE",
             "The visit's count_status is %s." % visit["count_status"])

    if product["registration_state"] != "REGISTERED":
        fail("ERR_PRODUCT_NOT_REGISTERED", "The label is not REGISTERED.")

    if visit["site_type"] == "CENTER":
        if product["container_material"] not in (center.get("accepted_materials") or []):
            fail("ERR_MATERIAL_NOT_ACCEPTED",
                 "The centre does not accept this container material.")
        if visit["channel"] == "MACHINE_COUNT":
            machine = db.machines.get(visit["machine_id"])
            if machine is None or product["container_material"] != machine["accepted_material"]:
                fail("ERR_MATERIAL_NOT_ACCEPTED",
                     "The serving machine does not accept this container material.")

    account = db.accounts.get(visit["account_id"]) if visit["account_id"] else None
    if (account is not None and account.get("cap_reached_today")
            and account.get("redemption_day") == visit["visit_date"]):
        fail("ERR_DAILY_CAP_EXHAUSTED",
             "The account has exhausted its daily allowance for this date.")

    deposit = product["deposit_cents"]
    if product["coverage_status"] == "NOT_COVERED":
        accepted = 0
        reject_reason = "NOT_COVERED"
    else:
        accepted = presented - out_of_state - contaminated
        if out_of_state > 0 and contaminated > 0:
            reject_reason = "MIXED"
        elif out_of_state > 0:
            reject_reason = "OUT_OF_STATE"
        elif contaminated > 0:
            reject_reason = "CONTAMINATED"
        else:
            reject_reason = None

    lot = db.new_record({
        "visit_id": visit["id"],
        "product_id": product["id"],
        "presented_quantity": presented,
        "out_of_state_marked_quantity": out_of_state,
        "contaminated_quantity": contaminated,
        "accepted_quantity": accepted,
        "rejected_quantity": presented - accepted,
        "reject_reason": reject_reason,
        "deposit_cents_per_container": deposit,
        "deposit_value_cents": accepted * deposit,
        "paid_quantity": 0,
        "reconciliation_flag": "UNSETTLED",
    })
    db.lots[lot["id"]] = lot

    if visit["count_status"] == "OPEN":
        visit["count_status"] = "COUNTING"
    _refresh_visit_rollups(visit)
    touch(visit)
    return response.obj(db.public(lot), 201)


@bp.get("/redemption-visits/<rid>/lots")
def list_lots(rid):
    authenticate("ProgramAdmin", "CenterOperator", "RetailClerk")
    visit = db.visits.get(rid)
    if visit is not None:
        own_visit(visit)
    visit = lookup("visit", rid)
    return listing(proj.visit_lots(visit["id"]))


def _applicable_cap(visit, center):
    if visit["site_type"] == "CENTER" and center is not None:
        return int(center["daily_account_cap_containers"])
    return calc.DEFAULT_RETAILER_CAP


@bp.post("/redemption-visits/<rid>/close-count")
def close_count(rid):
    authenticate("CenterOperator", "RetailClerk", "ProgramAdmin")
    visit = db.visits.get(rid)
    if visit is not None:
        own_visit(visit)
    visit = lookup("visit", rid)
    v.body()

    center = db.centers.get(visit["center_id"]) if visit["center_id"] else None
    retailer = db.retailers.get(visit["retailer_id"]) if visit["retailer_id"] else None
    if visit["site_type"] == "CENTER":
        require_operational(center)

    if visit["count_status"] not in ("OPEN", "COUNTING"):
        fail("ERR_INVALID_COUNT_STATE",
             "The visit's count_status is %s." % visit["count_status"])

    account = db.accounts.get(visit["account_id"]) if visit["account_id"] else None
    raw = int(visit["raw_accepted_count"])

    # Stage one -- the per-visit ceiling.
    base = calc.visit_base_ceiling(
        visit["site_type"], visit["channel"],
        retailer["daily_limit_containers"] if retailer else 0)
    limit = calc.visit_limit(base, account is not None)
    visit["visit_limit_applied"] = limit

    # Stage two -- the remaining daily allowance.
    cap = _applicable_cap(visit, center)
    if account is None:
        allowance = raw
    else:
        used = (int(account["containers_redeemed_today"])
                if account.get("redemption_day") == visit["visit_date"] else 0)
        allowance = max(0, cap - used)

    # Stage three -- the three-way minimum and the shrink deduction.
    capped = min(raw, limit, allowance)
    shrink = calc.shrink_adjustment(capped, visit["channel"])
    payable = capped - shrink
    visit["capped_count"] = capped
    visit["shrink_adjustment_count"] = shrink
    visit["payable_count"] = payable
    visit["refused_over_limit_count"] = raw - capped

    # Stage four -- the payout waterfall.
    remaining = payable
    payout = 0
    for lot in proj.visit_lots(visit["id"]):
        paid = min(lot["accepted_quantity"], remaining)
        remaining -= paid
        lot["paid_quantity"] = paid
        if paid == lot["accepted_quantity"] and lot["accepted_quantity"] > 0:
            lot["reconciliation_flag"] = "PAID_FULL"
        elif paid == 0:
            lot["reconciliation_flag"] = "UNPAID"
        else:
            lot["reconciliation_flag"] = "PAID_PARTIAL"
        payout += paid * lot["deposit_cents_per_container"]
        touch(lot)
    visit["payout_cents"] = payout

    visit["count_status"] = "COUNTED"
    visit["counted_at"] = clock.now_iso()

    # Stage five -- the fraud posture.
    ratio = calc.ratio_4dp(visit["out_of_state_marked_total"], visit["presented_total"])
    fraud = False
    reason = None
    flagged_now = False
    if ratio > calc.OUT_OF_STATE_THRESHOLD:
        fraud = True
        reason = "OUT_OF_STATE_RATIO"
        if account is not None:
            flagged_now = proj.record_strike(account, "OUT_OF_STATE_RATIO") or flagged_now
    if account is not None and raw > allowance:
        fraud = True
        reason = "DAILY_CAP_EXCEEDED"
        flagged_now = proj.record_strike(account, "DAILY_CAP_EXCEEDED") or flagged_now
    if fraud:
        visit["fraud_hold"] = True
        visit["payout_status"] = "WITHHELD"
        visit["withhold_reason"] = "ACCOUNT_FLAGGED" if flagged_now else reason

    # The daily bucket.
    if account is not None:
        if account.get("redemption_day") != visit["visit_date"]:
            account["redemption_day"] = visit["visit_date"]
            account["containers_redeemed_today"] = 0
        account["containers_redeemed_today"] = int(account["containers_redeemed_today"]) + payable
        account["cap_reached_today"] = account["containers_redeemed_today"] >= cap
        touch(account)

    if visit["channel"] == "MACHINE_COUNT" and visit["machine_id"]:
        machine = db.machines.get(visit["machine_id"])
        if machine is not None:
            machine["bin_filled_count"] = int(machine["bin_filled_count"]) + raw
            touch(machine)

    touch(visit)
    if center is not None:
        proj.recompute_center_containers(center)
        if fraud:
            proj.recompute_center_withheld(center)
    return response.obj(db.public(visit))


@bp.post("/redemption-visits/<rid>/payout-actions")
def payout_action(rid):
    authenticate("CenterOperator", "RetailClerk", "ProgramAdmin")
    visit = db.visits.get(rid)
    if visit is not None:
        own_visit(visit)
    body = v.body()
    raw_action = body.get("action")
    if isinstance(raw_action, str):
        narrow(raw_action, program_admin_only=PAYOUT_ADMIN_ONLY)
    visit = lookup("visit", rid)
    action = v.req_enum(body, "action", PAYOUT_ACTIONS)
    v.opt_str(body, "reason")

    center = db.centers.get(visit["center_id"]) if visit["center_id"] else None
    account = db.accounts.get(visit["account_id"]) if visit["account_id"] else None

    if visit["payout_status"] not in PAYOUT_ORIGINS[action]:
        fail("ERR_INVALID_PAYOUT_STATE",
             "Action %s is not available from %s." % (action, visit["payout_status"]))

    if action == "APPROVE":
        if visit["count_status"] != "COUNTED" or visit["fraud_hold"]:
            fail("ERR_INVALID_PAYOUT_STATE",
                 "The visit is not ready for approval.")
        if visit["requires_manual_recount"]:
            fail("ERR_MANUAL_RECOUNT_REQUIRED",
                 "The visit was jammed during counting and needs a manual recount.")
        visit["payout_status"] = "APPROVED"
        touch(visit)
        return response.obj(db.public(visit))

    if action == "WITHHOLD":
        visit["payout_status"] = "WITHHELD"
        visit["withhold_reason"] = "MANUAL_REVIEW"
        touch(visit)
        if center is not None:
            proj.recompute_center_withheld(center)
        return response.obj(db.public(visit))

    if action == "RELEASE_HOLD":
        if account is not None:
            if account["status"] == "CLOSED":
                fail("ERR_ACCOUNT_CLOSED", "The redeemer account is closed.")
            if account["status"] != "ACTIVE":
                fail("ERR_ACCOUNT_FLAGGED", "The redeemer account is not ACTIVE.")
        visit["payout_status"] = "PENDING"
        visit["fraud_hold"] = False
        visit["withhold_reason"] = None
        touch(visit)
        if center is not None:
            proj.recompute_center_withheld(center)
        return response.obj(db.public(visit))

    # PAY and REVERSE both need the quarter that contains the visit date.
    containing = proj.periods_containing(visit["visit_date"])
    open_periods = [p for p in containing if p["status"] == "OPEN"]
    if containing and not open_periods:
        fail("ERR_INVALID_PERIOD_STATE",
             "The reporting quarter covering the visit date is not OPEN.")
    if not open_periods:
        fail("ERR_NO_OPEN_PERIOD",
             "No OPEN reporting quarter covers the visit date.")
    period = open_periods[0]

    if action == "PAY":
        if visit["site_type"] == "CENTER" and center is not None:
            if center["cash_drawer_balance_cents"] < visit["payout_cents"]:
                fail("ERR_INSUFFICIENT_CASH_DRAWER",
                     "The payout drawer does not hold enough cash.")
        visit["payout_status"] = "PAID"
        visit["paid_at"] = clock.now_iso()
        touch(visit)
        if visit["site_type"] == "CENTER" and center is not None:
            center["cash_drawer_balance_cents"] -= visit["payout_cents"]
            touch(center)
        proj.append_ledger_entry(period, "REDEMPTION_PAID", -visit["payout_cents"],
                                 visit["payable_count"], "REDEMPTION_VISIT", visit["id"])
        proj.replay_period(period)
        return response.obj(db.public(visit))

    # REVERSE
    visit["payout_status"] = "REVERSED"
    touch(visit)
    if visit["site_type"] == "CENTER" and center is not None:
        center["cash_drawer_balance_cents"] += visit["payout_cents"]
        touch(center)
    proj.append_ledger_entry(period, "REDEMPTION_REVERSED", visit["payout_cents"],
                             visit["payable_count"], "REDEMPTION_VISIT", visit["id"])
    proj.replay_period(period)
    for lot in proj.visit_lots(visit["id"]):
        lot["paid_quantity"] = 0
        lot["reconciliation_flag"] = "UNPAID"
        touch(lot)
    if account is not None and account.get("redemption_day") == visit["visit_date"]:
        account["containers_redeemed_today"] = max(
            0, int(account["containers_redeemed_today"]) - int(visit["payable_count"]))
        cap = _applicable_cap(visit, center)
        account["cap_reached_today"] = account["containers_redeemed_today"] >= cap
        touch(account)
    return response.obj(db.public(visit))
