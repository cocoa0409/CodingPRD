"""Mobile Carrier Plan & Device Management API — Flask entry point.

In-memory only. No seeding at startup; tests build all state via the API.
Every endpoint, field, and side effect traces to a PRD §3 sentence.
"""
import os

from flask import Flask, request

import db
import domain
import ledger
from auth import authenticate, authorize
from common import (get_body, require, require_str, require_int, require_enum,
                    opt_int, parse_dt, public, stamp_create, touch,
                    whole_utc_days, is_whole_days, round_half_up, clock_iso)
from errors import (ApiError, err,
                    ERR_NOT_FOUND, ERR_FK_NOT_FOUND, ERR_VALIDATION,
                    ERR_STALE_ACCOUNT_VERSION, ERR_INVALID_STATE,
                    ERR_PLAN_RETIRED, ERR_SIM_NOT_ISSUED,
                    ERR_ACCOUNT_NOT_ACTIVE, ERR_NUMBER_IN_USE,
                    ERR_PORT_IN_PROGRESS, ERR_PORT_NOT_REVERTABLE,
                    ERR_INVALID_WINDOW, ERR_ADDON_OVERLAP,
                    ERR_ADDON_WINDOW_NOT_STARTED, ERR_USAGE_OUTSIDE_CYCLE,
                    ERR_DEVICE_UNAVAILABLE, ERR_RECONNECT_BLOCKED,
                    ERR_CYCLE_NOT_ENDED, ERR_NOT_ACCOUNT_OWNER)
from listing import filter_sort_paginate
from response import success, success_list, error_response

app = Flask(__name__)

# Ensure a clean store on each boot (in-memory only, no seeding).
db.reset()


# ===========================================================================
# Error handling — every error returns the standard envelope (PRD §2.2).
# ===========================================================================
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", "resource not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", "method not allowed", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.message, e.http_status)
    return error_response("ERR_VALIDATION", str(e), 422)


# ===========================================================================
# Lookup helpers (existence validated left-to-right, PRD §2.4).
# ===========================================================================
def get_account(account_id):
    a = db.accounts.get(account_id)
    if a is None:
        err(ERR_NOT_FOUND, "account not found")
    return a


def get_plan(plan_id):
    p = db.plans.get(plan_id)
    if p is None:
        err(ERR_NOT_FOUND, "plan not found")
    return p


def get_device(device_id):
    d = db.devices.get(device_id)
    if d is None:
        err(ERR_NOT_FOUND, "device not found")
    return d


def get_line(line_id):
    l = db.lines.get(line_id)
    if l is None:
        err(ERR_NOT_FOUND, "line not found")
    return l


def get_sim(sim_id):
    s = db.sim_assignments.get(sim_id)
    if s is None:
        err(ERR_NOT_FOUND, "sim assignment not found")
    return s


def get_eip(eip_id):
    ip = db.installment_plans.get(eip_id)
    if ip is None:
        err(ERR_NOT_FOUND, "installment plan not found")
    return ip


def get_addon(addon_id):
    a = db.addons.get(addon_id)
    if a is None:
        err(ERR_NOT_FOUND, "add-on not found")
    return a


def get_port(port_id):
    p = db.port_requests.get(port_id)
    if p is None:
        err(ERR_NOT_FOUND, "port request not found")
    return p


def get_upgrade(up_id):
    u = db.upgrade_orders.get(up_id)
    if u is None:
        err(ERR_NOT_FOUND, "upgrade order not found")
    return u


def get_cycle(cycle_id):
    c = db.billing_cycles.get(cycle_id)
    if c is None:
        err(ERR_NOT_FOUND, "billing cycle not found")
    return c


def get_charge(charge_id):
    c = db.charges.get(charge_id)
    if c is None:
        err(ERR_NOT_FOUND, "charge not found")
    return c


def get_usage(usage_id):
    u = db.usage_records.get(usage_id)
    if u is None:
        err(ERR_NOT_FOUND, "usage record not found")
    return u


def require_owner(user_id, role, account_id):
    """Subscriber acting on a resource must own the account (PRD §2.1, §1.4)."""
    if role == "Subscriber" and user_id != account_id:
        err(ERR_NOT_ACCOUNT_OWNER, "subscriber does not own this account")


# ===========================================================================
# Accounts (PRD §3.1)
# ===========================================================================
@app.route("/accounts", methods=["POST"])
def create_account():
    _, role = authenticate()
    authorize(role, {"CarrierAgent"})
    body = get_body()
    holder_name = require_str(body, "holder_name")
    holder_email = require_str(body, "holder_email")
    billing_day = require_int(body, "billing_day_of_month")
    if billing_day < 1 or billing_day > 28:
        err(ERR_VALIDATION, "billing_day_of_month must be 1..28")
    account = {
        "holder_name": holder_name,
        "holder_email": holder_email,
        "billing_day_of_month": billing_day,
        "status": "ACTIVE",
        "active_line_count": 0,
        "group_discount_pct": 0.00,
        "total_eip_outstanding_cents": 0,
        "wallet_credit_cents": 0,
    }
    stamp_create(account, common=True)
    db.accounts[account["id"]] = account
    return success(public(account), 201)


@app.route("/accounts/<account_id>", methods=["GET"])
def fetch_account(account_id):
    user_id, role = authenticate()
    authorize(role, {"CarrierAgent", "Subscriber", "BillingSystem"})
    account = get_account(account_id)
    require_owner(user_id, role, account_id)
    return success(public(account), 200)


@app.route("/accounts/<account_id>/mark-delinquent", methods=["POST"])
def mark_delinquent(account_id):
    _, role = authenticate()
    authorize(role, {"BillingSystem"})
    account = get_account(account_id)
    body = get_body()
    delinquent = require(body, "delinquent")
    if not isinstance(delinquent, bool):
        err(ERR_VALIDATION, "delinquent must be a boolean")
    account["status"] = "DELINQUENT" if delinquent else "ACTIVE"
    touch(account)
    return success(public(account), 200)


# ===========================================================================
# Plans (PRD §3.1)
# ===========================================================================
@app.route("/plans", methods=["POST"])
def create_plan():
    _, role = authenticate()
    authorize(role, {"CarrierAgent"})
    body = get_body()
    code = require_str(body, "code")
    name = require_str(body, "name")
    monthly_fee = require_int(body, "monthly_fee_cents")
    included_data = require_int(body, "included_data_mb")
    tier1_cap = opt_int(body, "overage_tier1_cap_mb", 5120)
    tier1_rate = require_int(body, "overage_tier1_rate_milli_cents")
    tier2_rate = require_int(body, "overage_tier2_rate_milli_cents")
    if any(p["code"] == code for p in db.plans.values()):
        err(ERR_VALIDATION, "plan code must be unique")
    plan = {
        "code": code,
        "name": name,
        "monthly_fee_cents": monthly_fee,
        "included_data_mb": included_data,
        "overage_tier1_cap_mb": tier1_cap,
        "overage_tier1_rate_milli_cents": tier1_rate,
        "overage_tier2_rate_milli_cents": tier2_rate,
        "status": "ACTIVE",
    }
    stamp_create(plan, common=True)
    db.plans[plan["id"]] = plan
    return success(public(plan), 201)


@app.route("/plans/<plan_id>", methods=["GET"])
def fetch_plan(plan_id):
    _, role = authenticate()
    authorize(role, {"CarrierAgent", "Subscriber", "BillingSystem"})
    return success(public(get_plan(plan_id)), 200)


@app.route("/plans/<plan_id>/retire", methods=["POST"])
def retire_plan(plan_id):
    _, role = authenticate()
    authorize(role, {"CarrierAgent"})
    plan = get_plan(plan_id)
    plan["status"] = "RETIRED"
    touch(plan)
    return success(public(plan), 200)


# ===========================================================================
# Devices (PRD §3.1)
# ===========================================================================
@app.route("/devices", methods=["POST"])
def create_device():
    _, role = authenticate()
    authorize(role, {"CarrierAgent"})
    body = get_body()
    model = require_str(body, "model")
    sku = require_str(body, "sku")
    retail = require_int(body, "retail_price_cents")
    stock = require_int(body, "stock_count")
    if any(d["sku"] == sku for d in db.devices.values()):
        err(ERR_VALIDATION, "device sku must be unique")
    device = {
        "model": model,
        "sku": sku,
        "retail_price_cents": retail,
        "stock_count": stock,
        "status": "AVAILABLE",
    }
    stamp_create(device, common=True)
    db.devices[device["id"]] = device
    return success(public(device), 201)


@app.route("/devices/<device_id>", methods=["GET"])
def fetch_device(device_id):
    _, role = authenticate()
    authorize(role, {"CarrierAgent", "Subscriber", "BillingSystem"})
    return success(public(get_device(device_id)), 200)


# ===========================================================================
# Lines (PRD §3.2)
# ===========================================================================
@app.route("/lines", methods=["POST"])
def provision_line():
    _, role = authenticate()
    authorize(role, {"CarrierAgent"})
    body = get_body()
    account_id = require_str(body, "account_id")
    plan_id = require_str(body, "plan_id")
    sim_type = require_enum(body, "sim_type", {"PHYSICAL", "ESIM"})
    expected_version = require_int(body, "expected_account_version")

    # Existence (account is a body FK here; PRD §2.4 treats unresolved body FKs
    # distinctly, but account_id resolution is required before OCC). Account not
    # found -> ERR_FK_NOT_FOUND per the body-FK category.
    account = db.accounts.get(account_id)
    if account is None:
        err(ERR_FK_NOT_FOUND, "account_id does not resolve")
    plan = db.plans.get(plan_id)
    if plan is None:
        err(ERR_FK_NOT_FOUND, "plan_id does not resolve")

    # OCC (priority 6) before state/business checks per validation ordering.
    if expected_version != account["version"]:
        err(ERR_STALE_ACCOUNT_VERSION, "expected_account_version is stale")

    # Plan must be ACTIVE (priority 8).
    if plan["status"] == "RETIRED":
        err(ERR_PLAN_RETIRED, "plan is retired")

    line = {
        "account_id": account_id,
        "plan_id": plan_id,
        "phone_number": None,
        "sim_type": sim_type,
        "status": "PENDING_ACTIVATION",
        "suspend_reason": None,
        "cycle_data_used_mb": 0,
        "activated_at": None,
    }
    stamp_create(line, common=True)
    db.lines[line["id"]] = line

    # Provisioning increments the owning account's version by one (PRD §3.2).
    touch(account)
    return success(public(line), 201)


@app.route("/lines", methods=["GET"])
def list_lines():
    _, role = authenticate()
    authorize(role, {"CarrierAgent", "Subscriber", "BillingSystem"})
    items, limit, offset, total = filter_sort_paginate(db.lines, {
        "account_id": request.args.get("account_id"),
        "plan_id": request.args.get("plan_id"),
        "status": request.args.get("status"),
    })
    return success_list(items, limit, offset, total)


@app.route("/lines/<line_id>", methods=["GET"])
def fetch_line(line_id):
    _, role = authenticate()
    authorize(role, {"CarrierAgent", "Subscriber", "BillingSystem"})
    return success(public(get_line(line_id)), 200)


@app.route("/lines/<line_id>/activate", methods=["POST"])
def activate_line(line_id):
    _, role = authenticate()
    authorize(role, {"CarrierAgent"})
    line = get_line(line_id)
    # State: only PENDING_ACTIVATION can activate (transition definedness).
    if line["status"] != "PENDING_ACTIVATION":
        err(ERR_INVALID_STATE, "line is not PENDING_ACTIVATION")
    # Precondition 1: a SimAssignment in ISSUED for this line.
    sim = next((s for s in db.sim_assignments.values()
                if s["line_id"] == line_id and s["status"] == "ISSUED"), None)
    if sim is None:
        err(ERR_SIM_NOT_ISSUED, "no ISSUED SIM assignment for this line")
    # Precondition 2: plan ACTIVE.
    plan = db.plans.get(line["plan_id"])
    if plan is None or plan["status"] == "RETIRED":
        err(ERR_PLAN_RETIRED, "plan is retired")
    # Precondition 3: account ACTIVE.
    account = db.accounts.get(line["account_id"])
    if account["status"] != "ACTIVE":
        err(ERR_ACCOUNT_NOT_ACTIVE, "account is not ACTIVE")

    # Side effects.
    if not line.get("phone_number"):
        # Assign from pool unless a prior PORT_IN already placed a number.
        line["phone_number"] = _assign_pool_number()
    line["activated_at"] = clock_iso()
    line["status"] = "ACTIVE"
    touch(line)

    sim["status"] = "ACTIVATED"
    if sim["sim_type"] == "ESIM":
        sim["esim_activation_code"] = "LPA:1$carrier.example.com$" + db.new_id()
    touch(sim)

    # Recompute account derived; increments account version by one (PRD §3.2).
    domain.recompute_account_derived(account, bump_version=True)
    return success(public(line), 200)


_pool_counter = {"n": 0}


def _assign_pool_number():
    _pool_counter["n"] += 1
    return "+1555{:07d}".format(_pool_counter["n"])


@app.route("/lines/<line_id>/suspend", methods=["POST"])
def suspend_line(line_id):
    _, role = authenticate()
    authorize(role, {"CarrierAgent"})
    line = get_line(line_id)
    if line["status"] != "ACTIVE":
        err(ERR_INVALID_STATE, "line is not ACTIVE")
    body = get_body()
    reason = require_enum(body, "suspend_reason",
                          {"VOLUNTARY", "NONPAYMENT", "LOST_STOLEN"})
    line["suspend_reason"] = reason
    line["status"] = "SUSPENDED"
    touch(line)
    # SIM ACTIVATED -> DEACTIVATED.
    for sim in db.sim_assignments.values():
        if sim["line_id"] == line_id and sim["status"] == "ACTIVATED":
            sim["status"] = "DEACTIVATED"
            touch(sim)
    # active_line_count NOT changed (SUSPENDED still counts), so no recompute
    # needed — but updated_at on account is untouched per PRD §3.4.
    return success(public(line), 200)


@app.route("/lines/<line_id>/reconnect", methods=["POST"])
def reconnect_line(line_id):
    _, role = authenticate()
    authorize(role, {"CarrierAgent"})
    line = get_line(line_id)
    if line["status"] != "SUSPENDED":
        err(ERR_INVALID_STATE, "line is not SUSPENDED")
    account = db.accounts.get(line["account_id"])
    # NONPAYMENT reconnect guard checked before generic account-active so the
    # more specific ERR_RECONNECT_BLOCKED surfaces for delinquent nonpayment.
    if line.get("suspend_reason") == "NONPAYMENT":
        if account["status"] == "DELINQUENT" or account.get("wallet_credit_cents", 0) < 0:
            err(ERR_RECONNECT_BLOCKED, "reconnect blocked: account delinquent")
    if account["status"] != "ACTIVE":
        err(ERR_ACCOUNT_NOT_ACTIVE, "account is not ACTIVE")
    line["suspend_reason"] = None
    line["status"] = "ACTIVE"
    touch(line)
    for sim in db.sim_assignments.values():
        if sim["line_id"] == line_id and sim["status"] == "DEACTIVATED":
            sim["status"] = "ACTIVATED"
            touch(sim)
    return success(public(line), 200)


@app.route("/lines/<line_id>/cancel", methods=["POST"])
def cancel_line(line_id):
    user_id, role = authenticate()
    authorize(role, {"Subscriber"})
    line = get_line(line_id)
    require_owner(user_id, role, line["account_id"])
    if line["status"] not in ("ACTIVE", "SUSPENDED"):
        err(ERR_INVALID_STATE, "line is not ACTIVE or SUSPENDED")
    # No in-flight port request.
    for p in db.port_requests.values():
        if p["line_id"] == line_id and p["status"] in ("REQUESTED", "VALIDATED"):
            err(ERR_PORT_IN_PROGRESS, "line has an in-flight port request")
    account = db.accounts.get(line["account_id"])
    ledger.cancel_line_cascade(line, account)
    return success(public(line), 200)


@app.route("/lines/<line_id>/usage-summary", methods=["GET"])
def usage_summary(line_id):
    _, role = authenticate()
    authorize(role, {"CarrierAgent", "Subscriber", "BillingSystem"})
    line = get_line(line_id)
    plan = db.plans.get(line["plan_id"])
    account = db.accounts.get(line["account_id"])
    cycle = domain.open_cycle_for_account(line["account_id"])

    cycle_data = line.get("cycle_data_used_mb", 0)
    overage = domain.line_overage_cents(line, plan) if plan else 0

    prorated = 0
    if cycle is not None and plan is not None and line.get("activated_at"):
        disc_base = domain.discounted_base_cents(plan, account["group_discount_pct"])
        active_days = domain.line_active_days(line, cycle)
        prorated = domain.prorated_base_cents(disc_base, active_days,
                                              cycle["days_in_cycle"])

    eip = domain.line_eip_installment_cents(line)
    addon = domain.line_addon_cents(line, cycle, until=db.now()) if cycle else 0
    projected = prorated + overage + eip + addon

    return success({
        "cycle_data_used_mb": cycle_data,
        "overage_cents": overage,
        "prorated_base_cents": prorated,
        "projected_line_total_cents": projected,
    }, 200)


# ===========================================================================
# SIM Assignments (PRD §3.3)
# ===========================================================================
@app.route("/sim-assignments", methods=["POST"])
def create_sim():
    _, role = authenticate()
    authorize(role, {"CarrierAgent"})
    body = get_body()
    line_id = require_str(body, "line_id")
    sim_type = require_enum(body, "sim_type", {"PHYSICAL", "ESIM"})
    line = db.lines.get(line_id)
    if line is None:
        err(ERR_FK_NOT_FOUND, "line_id does not resolve")
    iccid = None
    if sim_type == "PHYSICAL":
        iccid = require_str(body, "iccid")
    sim = {
        "line_id": line_id,
        "sim_type": sim_type,
        "iccid": iccid,
        "esim_activation_code": None,
        "status": "ISSUED",
    }
    stamp_create(sim, common=True)
    db.sim_assignments[sim["id"]] = sim
    return success(public(sim), 201)


@app.route("/sim-assignments/<sim_id>", methods=["GET"])
def fetch_sim(sim_id):
    _, role = authenticate()
    authorize(role, {"CarrierAgent", "Subscriber", "BillingSystem"})
    return success(public(get_sim(sim_id)), 200)


@app.route("/sim-assignments", methods=["GET"])
def list_sims():
    _, role = authenticate()
    authorize(role, {"CarrierAgent", "Subscriber", "BillingSystem"})
    items, limit, offset, total = filter_sort_paginate(db.sim_assignments, {
        "line_id": request.args.get("line_id"),
        "status": request.args.get("status"),
    })
    return success_list(items, limit, offset, total)


# ===========================================================================
# Installment Plans / EIP (PRD §3.6)
# ===========================================================================
@app.route("/installment-plans", methods=["POST"])
def create_eip():
    _, role = authenticate()
    authorize(role, {"CarrierAgent"})
    body = get_body()
    line_id = require_str(body, "line_id")
    device_id = require_str(body, "device_id")
    term = require_int(body, "term_months")
    down = require_int(body, "down_payment_cents")

    line = db.lines.get(line_id)
    if line is None:
        err(ERR_FK_NOT_FOUND, "line_id does not resolve")
    device = db.devices.get(device_id)
    if device is None:
        err(ERR_FK_NOT_FOUND, "device_id does not resolve")
    if term not in (12, 24, 36):
        err(ERR_VALIDATION, "term_months must be 12, 24, or 36")
    # Device availability precondition.
    if device["stock_count"] <= 0 or down >= device["retail_price_cents"]:
        err(ERR_DEVICE_UNAVAILABLE, "device unavailable or down payment too high")

    financed = domain.eip_financed(device["retail_price_cents"], down)
    monthly = domain.eip_monthly_installment(financed, term)
    eip = {
        "line_id": line_id,
        "device_id": device_id,
        "term_months": term,
        "down_payment_cents": down,
        "financed_cents": financed,
        "monthly_installment_cents": monthly,
        "remaining_balance_cents": financed,
        "installments_paid": 0,
        "status": "ACTIVE",
    }
    stamp_create(eip, common=True)
    db.installment_plans[eip["id"]] = eip

    device["stock_count"] -= 1
    touch(device)
    account = db.accounts.get(line["account_id"])
    domain.recompute_eip_outstanding(account)
    return success(public(eip), 201)


@app.route("/installment-plans/<eip_id>", methods=["GET"])
def fetch_eip(eip_id):
    _, role = authenticate()
    authorize(role, {"CarrierAgent", "Subscriber", "BillingSystem"})
    return success(public(get_eip(eip_id)), 200)


@app.route("/installment-plans", methods=["GET"])
def list_eips():
    _, role = authenticate()
    authorize(role, {"CarrierAgent", "Subscriber", "BillingSystem"})
    items, limit, offset, total = filter_sort_paginate(db.installment_plans, {
        "line_id": request.args.get("line_id"),
        "device_id": request.args.get("device_id"),
        "status": request.args.get("status"),
    })
    return success_list(items, limit, offset, total)


# ===========================================================================
# Upgrades (PRD §3.6)
# ===========================================================================
@app.route("/upgrades", methods=["POST"])
def create_upgrade():
    _, role = authenticate()
    authorize(role, {"CarrierAgent"})
    body = get_body()
    line_id = require_str(body, "line_id")
    old_eip_id = require_str(body, "old_installment_plan_id")
    new_device_id = require_str(body, "new_device_id")
    new_term = require_int(body, "new_term_months")
    new_down = require_int(body, "new_down_payment_cents")
    trade_in = require_int(body, "trade_in_credit_cents")

    line = db.lines.get(line_id)
    if line is None:
        err(ERR_FK_NOT_FOUND, "line_id does not resolve")
    # old_installment_plan_id must name an ACTIVE EIP on this line.
    old_eip = db.installment_plans.get(old_eip_id)
    if (old_eip is None or old_eip["line_id"] != line_id
            or old_eip["status"] != "ACTIVE"):
        err(ERR_FK_NOT_FOUND, "old_installment_plan_id does not resolve to an "
                              "ACTIVE plan on this line")
    new_device = db.devices.get(new_device_id)
    if new_device is None:
        err(ERR_FK_NOT_FOUND, "new_device_id does not resolve")
    if new_term not in (12, 24, 36):
        err(ERR_VALIDATION, "new_term_months must be 12, 24, or 36")
    if new_device["stock_count"] <= 0 or new_down >= new_device["retail_price_cents"]:
        err(ERR_DEVICE_UNAVAILABLE, "new device unavailable or down payment too high")

    account = db.accounts.get(line["account_id"])
    cycle = domain.open_cycle_for_account(line["account_id"])

    # payoff = max(0, old remaining - trade_in)
    payoff = max(0, old_eip["remaining_balance_cents"] - trade_in)
    if cycle is not None and payoff > 0:
        ledger.post_charge(cycle["id"], line_id, "EIP_PAYOFF", payoff,
                           "Upgrade device payoff")

    # Old EIP -> CANCELLED, settled to 0.
    old_eip["remaining_balance_cents"] = 0
    old_eip["status"] = "CANCELLED"
    touch(old_eip)

    # New EIP created ACTIVE.
    new_financed = domain.eip_financed(new_device["retail_price_cents"], new_down)
    new_monthly = domain.eip_monthly_installment(new_financed, new_term)
    new_eip = {
        "line_id": line_id,
        "device_id": new_device_id,
        "term_months": new_term,
        "down_payment_cents": new_down,
        "financed_cents": new_financed,
        "monthly_installment_cents": new_monthly,
        "remaining_balance_cents": new_financed,
        "installments_paid": 0,
        "status": "ACTIVE",
    }
    stamp_create(new_eip, common=True)
    db.installment_plans[new_eip["id"]] = new_eip

    new_device["stock_count"] -= 1
    touch(new_device)

    upgrade = {
        "line_id": line_id,
        "old_installment_plan_id": old_eip_id,
        "new_device_id": new_device_id,
        "new_term_months": new_term,
        "new_down_payment_cents": new_down,
        "trade_in_credit_cents": trade_in,
        "payoff_charge_cents": payoff,
        "new_installment_plan_id": new_eip["id"],
        "status": "COMPLETED",
    }
    stamp_create(upgrade, common=True)
    db.upgrade_orders[upgrade["id"]] = upgrade

    domain.recompute_eip_outstanding(account)
    return success(public(upgrade), 201)


@app.route("/upgrades/<up_id>", methods=["GET"])
def fetch_upgrade(up_id):
    _, role = authenticate()
    authorize(role, {"CarrierAgent", "Subscriber", "BillingSystem"})
    return success(public(get_upgrade(up_id)), 200)


@app.route("/upgrades", methods=["GET"])
def list_upgrades():
    _, role = authenticate()
    authorize(role, {"CarrierAgent", "Subscriber", "BillingSystem"})
    items, limit, offset, total = filter_sort_paginate(db.upgrade_orders, {
        "line_id": request.args.get("line_id"),
        "old_installment_plan_id": request.args.get("old_installment_plan_id"),
        "new_installment_plan_id": request.args.get("new_installment_plan_id"),
        "new_device_id": request.args.get("new_device_id"),
    })
    return success_list(items, limit, offset, total)


# ===========================================================================
# Port Requests (PRD §3.7)
# ===========================================================================
@app.route("/port-requests", methods=["POST"])
def create_port():
    user_id, role = authenticate()
    authorize(role, {"Subscriber", "CarrierAgent"})
    body = get_body()
    line_id = require_str(body, "line_id")
    direction = require_enum(body, "direction", {"PORT_IN", "PORT_OUT"})
    external_number = require_str(body, "external_number")
    donor_carrier = require_str(body, "donor_carrier")
    account_pin = require_str(body, "account_pin")

    line = db.lines.get(line_id)
    if line is None:
        err(ERR_FK_NOT_FOUND, "line_id does not resolve")
    require_owner(user_id, role, line["account_id"])

    # PORT_IN uniqueness: external_number not already live on another line.
    if direction == "PORT_IN":
        if any(l.get("phone_number") == external_number for l in db.lines.values()):
            err(ERR_NUMBER_IN_USE, "external_number already in use")

    port = {
        "line_id": line_id,
        "direction": direction,
        "external_number": external_number,
        "donor_carrier": donor_carrier,
        "account_pin": account_pin,
        "status": "REQUESTED",
        "reject_reason": None,
    }
    stamp_create(port, common=True)
    db.port_requests[port["id"]] = port
    return success(public(port), 201)


@app.route("/port-requests/<port_id>", methods=["GET"])
def fetch_port(port_id):
    _, role = authenticate()
    authorize(role, {"CarrierAgent", "Subscriber", "PortingOps", "BillingSystem"})
    return success(public(get_port(port_id)), 200)


@app.route("/port-requests", methods=["GET"])
def list_ports():
    _, role = authenticate()
    authorize(role, {"CarrierAgent", "Subscriber", "PortingOps", "BillingSystem"})
    items, limit, offset, total = filter_sort_paginate(db.port_requests, {
        "line_id": request.args.get("line_id"),
        "status": request.args.get("status"),
    })
    return success_list(items, limit, offset, total)


@app.route("/port-requests/<port_id>/validate", methods=["POST"])
def validate_port(port_id):
    _, role = authenticate()
    authorize(role, {"PortingOps"})
    port = get_port(port_id)
    if port["status"] != "REQUESTED":
        err(ERR_INVALID_STATE, "port is not REQUESTED")
    body = get_body()
    pin = require_str(body, "account_pin")
    if pin != port["account_pin"]:
        # PIN mismatch -> REJECTED with reject_reason=PIN_MISMATCH.
        port["status"] = "REJECTED"
        port["reject_reason"] = "PIN_MISMATCH"
        touch(port)
        return success(public(port), 200)
    # For PORT_OUT the targeted line must be ACTIVE at validation.
    if port["direction"] == "PORT_OUT":
        line = db.lines.get(port["line_id"])
        if line is None or line["status"] != "ACTIVE":
            err(ERR_INVALID_STATE, "port-out line is not ACTIVE")
    port["status"] = "VALIDATED"
    touch(port)
    return success(public(port), 200)


@app.route("/port-requests/<port_id>/complete", methods=["POST"])
def complete_port(port_id):
    _, role = authenticate()
    authorize(role, {"PortingOps"})
    port = get_port(port_id)
    if port["status"] != "VALIDATED":
        err(ERR_INVALID_STATE, "port is not VALIDATED")
    line = db.lines.get(port["line_id"])
    if port["direction"] == "PORT_IN":
        # Re-check uniqueness at completion.
        if any(l.get("phone_number") == port["external_number"]
               and l["id"] != line["id"] for l in db.lines.values()):
            err(ERR_NUMBER_IN_USE, "external_number already in use")
        line["phone_number"] = port["external_number"]
        touch(line)
    else:  # PORT_OUT
        account = db.accounts.get(line["account_id"])
        # Number released, line cancelled via the cancel cascade.
        ledger.cancel_line_cascade(line, account)
    port["status"] = "COMPLETED"
    touch(port)
    return success(public(port), 200)


@app.route("/port-requests/<port_id>/reject", methods=["POST"])
def reject_port(port_id):
    _, role = authenticate()
    authorize(role, {"PortingOps"})
    port = get_port(port_id)
    if port["status"] not in ("REQUESTED", "VALIDATED"):
        err(ERR_INVALID_STATE, "port is not REQUESTED or VALIDATED")
    body = get_body()
    reason = require_enum(body, "reject_reason",
                          {"PIN_MISMATCH", "NUMBER_NOT_PORTABLE", "DONOR_REFUSED"})
    port["reject_reason"] = reason
    port["status"] = "REJECTED"
    touch(port)
    return success(public(port), 200)


@app.route("/port-requests/<port_id>/revert", methods=["POST"])
def revert_port(port_id):
    _, role = authenticate()
    authorize(role, {"PortingOps"})
    port = get_port(port_id)
    # Only a completed PORT_IN may be reverted.
    if port["status"] != "COMPLETED":
        if port["direction"] != "PORT_IN":
            err(ERR_PORT_NOT_REVERTABLE, "only a PORT_IN may be reverted")
        err(ERR_INVALID_STATE, "port is not COMPLETED")
    if port["direction"] != "PORT_IN":
        err(ERR_PORT_NOT_REVERTABLE, "only a PORT_IN may be reverted")
    line = db.lines.get(port["line_id"])
    line["phone_number"] = None
    touch(line)
    port["status"] = "REVERTED"
    touch(port)
    return success(public(port), 200)


# ===========================================================================
# Add-ons (PRD §3.8)
# ===========================================================================
@app.route("/addons", methods=["POST"])
def create_addon():
    user_id, role = authenticate()
    authorize(role, {"Subscriber", "CarrierAgent"})
    body = get_body()
    line_id = require_str(body, "line_id")
    addon_type = require_enum(body, "addon_type",
                              {"ROAMING_DAYPASS", "INTL_MONTHLY"})
    window_start_raw = require_str(body, "window_start")
    window_end_raw = require_str(body, "window_end")
    window_start = parse_dt(window_start_raw, "window_start")
    window_end = parse_dt(window_end_raw, "window_end")

    line = db.lines.get(line_id)
    if line is None:
        err(ERR_FK_NOT_FOUND, "line_id does not resolve")
    require_owner(user_id, role, line["account_id"])

    daily_fee = None
    monthly_fee = None
    if addon_type == "ROAMING_DAYPASS":
        daily_fee = require_int(body, "daily_fee_cents")
    else:
        monthly_fee = require_int(body, "monthly_fee_cents")

    # Window must be well-formed (priority 10).
    if window_end <= window_start:
        err(ERR_INVALID_WINDOW, "window_end must be after window_start")
    if addon_type == "ROAMING_DAYPASS" and not is_whole_days(window_start, window_end):
        err(ERR_INVALID_WINDOW, "daypass window must span whole UTC days")

    # Overlap with another daypass on the same line (priority 11).
    if addon_type == "ROAMING_DAYPASS":
        for a in db.addons.values():
            if (a["line_id"] == line_id and a["addon_type"] == "ROAMING_DAYPASS"
                    and a["status"] in ("SCHEDULED", "ACTIVE", "EXPIRED")):
                a_start = parse_dt(a["window_start"], "window_start")
                a_end = parse_dt(a["window_end"], "window_end")
                # Half-open overlap; adjacency allowed.
                if window_start < a_end and a_start < window_end:
                    err(ERR_ADDON_OVERLAP, "daypass windows overlap")

    addon = {
        "line_id": line_id,
        "addon_type": addon_type,
        "daily_fee_cents": daily_fee,
        "monthly_fee_cents": monthly_fee,
        "window_start": window_start_raw,
        "window_end": window_end_raw,
        "status": "SCHEDULED",
    }
    stamp_create(addon, common=True)
    db.addons[addon["id"]] = addon
    return success(public(addon), 201)


@app.route("/addons/<addon_id>", methods=["GET"])
def fetch_addon(addon_id):
    _, role = authenticate()
    authorize(role, {"CarrierAgent", "Subscriber", "BillingSystem"})
    addon = get_addon(addon_id)
    domain.reconcile_addon(addon)
    return success(public(addon), 200)


@app.route("/addons", methods=["GET"])
def list_addons():
    _, role = authenticate()
    authorize(role, {"CarrierAgent", "Subscriber", "BillingSystem"})
    domain.reconcile_all_addons()
    items, limit, offset, total = filter_sort_paginate(db.addons, {
        "line_id": request.args.get("line_id"),
        "status": request.args.get("status"),
    })
    return success_list(items, limit, offset, total)


@app.route("/addons/<addon_id>/activate", methods=["POST"])
def activate_addon(addon_id):
    _, role = authenticate()
    authorize(role, {"CarrierAgent", "Subscriber"})
    addon = get_addon(addon_id)
    if addon["status"] != "SCHEDULED":
        err(ERR_INVALID_STATE, "add-on is not SCHEDULED")
    w_start = parse_dt(addon["window_start"], "window_start")
    if db.now() < w_start:
        err(ERR_ADDON_WINDOW_NOT_STARTED, "window has not started")
    line = db.lines.get(addon["line_id"])
    if line is None or line["status"] != "ACTIVE":
        err(ERR_INVALID_STATE, "parent line is not ACTIVE")
    addon["status"] = "ACTIVE"
    touch(addon)
    return success(public(addon), 200)


@app.route("/addons/<addon_id>/cancel", methods=["POST"])
def cancel_addon(addon_id):
    user_id, role = authenticate()
    authorize(role, {"Subscriber", "CarrierAgent"})
    addon = get_addon(addon_id)
    line = db.lines.get(addon["line_id"])
    if line is not None:
        require_owner(user_id, role, line["account_id"])
    if addon["status"] not in ("SCHEDULED", "ACTIVE"):
        err(ERR_INVALID_STATE, "add-on is not SCHEDULED or ACTIVE")
    addon["status"] = "CANCELLED"
    touch(addon)
    return success(public(addon), 200)


# ===========================================================================
# Usage Records (PRD §3.9)
# ===========================================================================
@app.route("/usage-records", methods=["POST"])
def create_usage():
    _, role = authenticate()
    authorize(role, {"CarrierAgent", "BillingSystem"})
    body = get_body()
    line_id = require_str(body, "line_id")
    usage_type = require_enum(body, "usage_type", {"DATA", "VOICE", "TEXT"})
    data_mb = opt_int(body, "data_mb", 0)
    occurred_at_raw = require_str(body, "occurred_at")
    occurred_at = parse_dt(occurred_at_raw, "occurred_at")

    line = db.lines.get(line_id)
    if line is None:
        err(ERR_FK_NOT_FOUND, "line_id does not resolve")

    # occurred_at must fall inside an OPEN cycle for the line's account.
    cycle = _open_cycle_containing(line["account_id"], occurred_at)
    if cycle is None:
        err(ERR_USAGE_OUTSIDE_CYCLE, "occurred_at not inside an OPEN cycle")

    usage = {
        "line_id": line_id,
        "usage_type": usage_type,
        "data_mb": data_mb if usage_type == "DATA" else 0,
        "occurred_at": occurred_at_raw,
    }
    stamp_create(usage, common=False)
    db.usage_records[usage["id"]] = usage

    # Recompute cycle_data_used_mb for DATA records inside the open cycle.
    if usage_type == "DATA":
        _recompute_cycle_data(line, cycle)
    return success(public(usage), 201)


def _open_cycle_containing(account_id, instant):
    for c in db.billing_cycles.values():
        if c["account_id"] != account_id or c["status"] != "OPEN":
            continue
        start = parse_dt(c["cycle_start"], "cycle_start")
        end = parse_dt(c["cycle_end"], "cycle_end")
        if start <= instant < end:
            return c
    return None


def _recompute_cycle_data(line, cycle):
    start = parse_dt(cycle["cycle_start"], "cycle_start")
    end = parse_dt(cycle["cycle_end"], "cycle_end")
    total = 0
    for u in db.usage_records.values():
        if u["line_id"] != line["id"] or u["usage_type"] != "DATA":
            continue
        occ = parse_dt(u["occurred_at"], "occurred_at")
        if start <= occ < end:
            total += u.get("data_mb", 0)
    line["cycle_data_used_mb"] = total
    touch(line)


@app.route("/usage-records/<usage_id>", methods=["GET"])
def fetch_usage(usage_id):
    _, role = authenticate()
    authorize(role, {"CarrierAgent", "Subscriber", "BillingSystem"})
    return success(public(get_usage(usage_id)), 200)


@app.route("/usage-records", methods=["GET"])
def list_usage():
    _, role = authenticate()
    authorize(role, {"CarrierAgent", "Subscriber", "BillingSystem"})
    items, limit, offset, total = filter_sort_paginate(db.usage_records, {
        "line_id": request.args.get("line_id"),
        "usage_type": request.args.get("usage_type"),
    })
    return success_list(items, limit, offset, total)


# ===========================================================================
# Billing Cycles (PRD §3.10)
# ===========================================================================
@app.route("/billing-cycles", methods=["POST"])
def open_cycle():
    _, role = authenticate()
    authorize(role, {"BillingSystem"})
    body = get_body()
    account_id = require_str(body, "account_id")
    cycle_start_raw = require_str(body, "cycle_start")
    cycle_end_raw = require_str(body, "cycle_end")
    cycle_start = parse_dt(cycle_start_raw, "cycle_start")
    cycle_end = parse_dt(cycle_end_raw, "cycle_end")

    account = db.accounts.get(account_id)
    if account is None:
        err(ERR_FK_NOT_FOUND, "account_id does not resolve")
    if cycle_end <= cycle_start:
        err(ERR_VALIDATION, "cycle_end must be after cycle_start")
    # Only one OPEN cycle per account.
    if domain.open_cycle_for_account(account_id) is not None:
        err(ERR_INVALID_STATE, "account already has an OPEN cycle")

    days = whole_utc_days(cycle_start, cycle_end)
    cycle = {
        "account_id": account_id,
        "cycle_start": cycle_start_raw,
        "cycle_end": cycle_end_raw,
        "days_in_cycle": days,
        "total_charges_cents": 0,
        "status": "OPEN",
    }
    stamp_create(cycle, common=True)
    db.billing_cycles[cycle["id"]] = cycle
    return success(public(cycle), 201)


@app.route("/billing-cycles/<cycle_id>", methods=["GET"])
def fetch_cycle(cycle_id):
    _, role = authenticate()
    authorize(role, {"CarrierAgent", "Subscriber", "BillingSystem"})
    return success(public(get_cycle(cycle_id)), 200)


@app.route("/billing-cycles", methods=["GET"])
def list_cycles():
    _, role = authenticate()
    authorize(role, {"CarrierAgent", "Subscriber", "BillingSystem"})
    items, limit, offset, total = filter_sort_paginate(db.billing_cycles, {
        "account_id": request.args.get("account_id"),
        "status": request.args.get("status"),
    })
    return success_list(items, limit, offset, total)


@app.route("/billing-cycles/<cycle_id>/close", methods=["POST"])
def close_billing_cycle(cycle_id):
    _, role = authenticate()
    authorize(role, {"BillingSystem"})
    cycle = get_cycle(cycle_id)
    if cycle["status"] != "OPEN":
        err(ERR_INVALID_STATE, "cycle is not OPEN")
    cycle_end = parse_dt(cycle["cycle_end"], "cycle_end")
    if db.now() < cycle_end:
        err(ERR_CYCLE_NOT_ENDED, "current UTC is before cycle_end")
    account = db.accounts.get(cycle["account_id"])
    ledger.close_cycle(cycle, account)
    return success(public(cycle), 200)


# ===========================================================================
# Charges (PRD §3.10)
# ===========================================================================
@app.route("/charges/<charge_id>", methods=["GET"])
def fetch_charge(charge_id):
    _, role = authenticate()
    authorize(role, {"CarrierAgent", "Subscriber", "BillingSystem"})
    return success(public(get_charge(charge_id)), 200)


@app.route("/charges", methods=["GET"])
def list_charges():
    _, role = authenticate()
    authorize(role, {"CarrierAgent", "Subscriber", "BillingSystem"})
    items, limit, offset, total = filter_sort_paginate(db.charges, {
        "billing_cycle_id": request.args.get("billing_cycle_id"),
        "line_id": request.args.get("line_id"),
        "charge_type": request.args.get("charge_type"),
    })
    return success_list(items, limit, offset, total)


# ===========================================================================
# Operator clock (PRD §3.11)
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = authenticate()
    authorize(role, {"BillingSystem"})
    body = get_body()
    to_iso = require_str(body, "to_iso8601")
    dt = parse_dt(to_iso, "to_iso8601")
    db.set_clock(dt)
    # Advancing the clock may expire ACTIVE add-ons past window_end.
    domain.reconcile_all_addons()
    current = dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    return success({"current_utc": current}, 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
