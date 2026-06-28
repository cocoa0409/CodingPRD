"""Bill Negotiation & Subscription Manager API. Python + Flask, in-memory."""
import os

from flask import Flask

from errors import ApiError, err
from response import success, error_response
from db import db, new_id, now_iso
from middleware import require_auth, require_role
from helpers import (
    get_body, require_fields, require_string, require_int, require_enum,
    optional_bool, parse_pagination, paginate, sort_by_created,
)
import calculations as calc
import serializers as ser

app = Flask(__name__)
app.url_map.strict_slashes = False


# --------------------------------------------------------------------------
# Error handling
# --------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(e):
    resp = error_response(e.error_id, e.message)
    resp.status_code = e.http_status
    return resp


@app.errorhandler(404)
def handle_404(e):
    resp = error_response("ERR_NOT_FOUND", "Resource not found")
    resp.status_code = 404
    return resp


@app.errorhandler(405)
def handle_405(e):
    resp = error_response("ERR_NOT_FOUND", "Method not allowed")
    resp.status_code = 404
    return resp


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    resp = error_response("ERR_INVALID_REQUEST", f"Unexpected error: {e}")
    resp.status_code = 400
    return resp


# --------------------------------------------------------------------------
# Auth + ownership helpers
# --------------------------------------------------------------------------
def auth_and_role(allowed_roles):
    user_id, role = require_auth()
    require_role(role, allowed_roles)
    return user_id, role


def check_owner(role, user_id, member_id):
    """Member acting on a member-owned resource must own it."""
    if role == "Member" and member_id != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Member does not own this resource")


def get_or_404(coll, rid):
    obj = coll.get(rid)
    if obj is None:
        raise err("ERR_NOT_FOUND", "Resource not found")
    return obj


def fk_or_404(coll, rid):
    obj = coll.get(rid)
    if obj is None:
        raise err("ERR_FK_NOT_FOUND", "Referenced resource not found")
    return obj


def touch(obj):
    obj["updated_at"] = now_iso()
    obj["version"] = obj["version"] + 1


# --------------------------------------------------------------------------
# Lifetime rollup
# --------------------------------------------------------------------------
def recompute_member_lifetime(member_id):
    m = db.members.get(member_id)
    if not m:
        return
    gross = 0
    net = 0
    for n in db.negotiation_cases.values():
        if n["member_id"] == member_id and n["status"] == "WON":
            gross += n["gross_annual_savings_cents"]
            net += n["member_net_savings_cents"]
    for r in db.refund_claims.values():
        if r["member_id"] == member_id and r["status"] == "REFUNDED":
            gross += (r["approved_refund_cents"] or 0)
            net += r["member_net_savings_cents"]
    m["lifetime_gross_savings_cents"] = gross
    m["lifetime_member_savings_cents"] = net


def book_ledger_entry(member_id, source_type, gross, fee, net,
                      negotiation_case_id=None, refund_claim_id=None):
    eid = new_id()
    entry = {
        "id": eid,
        "created_at": now_iso(),
        "member_id": member_id,
        "source_type": source_type,
        "negotiation_case_id": negotiation_case_id,
        "refund_claim_id": refund_claim_id,
        "gross_savings_cents": gross,
        "success_fee_cents": fee,
        "member_net_cents": net,
        "transfer_status": "PENDING",
        "transferred_utc": None,
    }
    db.ledger_entries[eid] = entry
    return entry


# ==========================================================================
# MEMBERS
# ==========================================================================
@app.route("/members", methods=["POST"])
def create_member():
    # Anonymous endpoint: no auth required.
    body = get_body()
    require_fields(body, ["email", "full_name"])
    email = require_string(body, "email")
    full_name = require_string(body, "full_name")
    success_fee_pct = body.get("success_fee_pct")
    if success_fee_pct is None:
        success_fee_pct = 0.40
    else:
        if isinstance(success_fee_pct, bool) or not isinstance(success_fee_pct, (int, float)):
            raise err("ERR_INVALID_REQUEST", "success_fee_pct must be a number")
        if not (0 < success_fee_pct < 1):
            raise err("ERR_VALUE_OUT_OF_RANGE", "success_fee_pct must be in (0,1)")
    # Unique email
    for m in db.members.values():
        if m["email"] == email:
            raise err("ERR_INVALID_REQUEST", "email must be unique among members")
    mid = new_id()
    ts = now_iso()
    member = {
        "id": mid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "email": email,
        "full_name": full_name,
        "success_fee_pct": success_fee_pct,
        "savings_account_id": None,
        "status": "ACTIVE",
        "lifetime_gross_savings_cents": 0,
        "lifetime_member_savings_cents": 0,
    }
    db.members[mid] = member
    return success(ser.ser_member(member), 201)


@app.route("/members/<mid>", methods=["GET"])
def get_member(mid):
    auth_and_role(["Member", "ConciergeAgent", "PlatformAdmin"])
    m = get_or_404(db.members, mid)
    return success(ser.ser_member(m), 200)


@app.route("/members", methods=["GET"])
def list_members():
    auth_and_role(["PlatformAdmin"])
    limit, offset = parse_pagination()
    from flask import request
    sa = request.args.get("savings_account_id")
    rows = list(db.members.values())
    if sa is not None:
        rows = [m for m in rows if m["savings_account_id"] == sa]
    rows = sort_by_created(rows)
    page, pmeta = paginate(rows, limit, offset)
    return success([ser.ser_member(m) for m in page], 200, is_array=True, pagination=pmeta)


@app.route("/members/<mid>/suspend", methods=["POST"])
def suspend_member(mid):
    auth_and_role(["PlatformAdmin"])
    m = get_or_404(db.members, mid)
    if m["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Member is not ACTIVE")
    m["status"] = "SUSPENDED"
    touch(m)
    return success(ser.ser_member(m), 200)


@app.route("/members/<mid>/reinstate", methods=["POST"])
def reinstate_member(mid):
    auth_and_role(["PlatformAdmin"])
    m = get_or_404(db.members, mid)
    if m["status"] != "SUSPENDED":
        raise err("ERR_INVALID_STATE", "Member is not SUSPENDED")
    m["status"] = "ACTIVE"
    touch(m)
    return success(ser.ser_member(m), 200)


@app.route("/members/<mid>", methods=["PATCH"])
def patch_member(mid):
    user_id, role = auth_and_role(["Member"])
    m = get_or_404(db.members, mid)
    check_owner(role, user_id, m["id"])
    body = get_body()
    require_fields(body, ["savings_account_id"])
    sa_id = body.get("savings_account_id")
    if not isinstance(sa_id, str) or sa_id == "":
        raise err("ERR_INVALID_REQUEST", "savings_account_id must be a string")
    sa = fk_or_404(db.savings_accounts, sa_id)
    if sa["member_id"] != m["id"]:
        raise err("ERR_NOT_RESOURCE_OWNER", "Savings account does not belong to member")
    m["savings_account_id"] = sa_id
    touch(m)
    return success(ser.ser_member(m), 200)


@app.route("/members/<mid>/savings-report", methods=["GET"])
def savings_report(mid):
    auth_and_role(["Member", "ConciergeAgent", "PlatformAdmin"])
    user_id, role = require_auth()
    m = get_or_404(db.members, mid)
    check_owner(role, user_id, m["id"])
    realized_gross = m["lifetime_gross_savings_cents"]
    realized_net = m["lifetime_member_savings_cents"]
    total_fees = realized_gross - realized_net
    pending = 0
    transferred = 0
    for e in db.ledger_entries.values():
        if e["member_id"] != m["id"]:
            continue
        if e["transfer_status"] == "PENDING":
            pending += e["member_net_cents"]
        elif e["transfer_status"] == "TRANSFERRED":
            transferred += e["member_net_cents"]
    report = {
        "member_id": m["id"],
        "realized_gross_cents": realized_gross,
        "realized_net_cents": realized_net,
        "total_fees_cents": total_fees,
        "pending_transfer_cents": pending,
        "transferred_cents": transferred,
    }
    return success(report, 200)


# ==========================================================================
# SAVINGS ACCOUNTS
# ==========================================================================
@app.route("/savings-accounts", methods=["POST"])
def create_savings_account():
    user_id, role = auth_and_role(["Member"])
    body = get_body()
    require_fields(body, ["member_id", "nickname"])
    member_id = require_string(body, "member_id")
    nickname = require_string(body, "nickname")
    check_owner(role, user_id, member_id)
    fk_or_404(db.members, member_id)
    sid = new_id()
    ts = now_iso()
    sa = {
        "id": sid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "member_id": member_id,
        "nickname": nickname,
        "balance_cents": 0,
        "status": "OPEN",
    }
    db.savings_accounts[sid] = sa
    return success(ser.ser_savings_account(sa), 201)


@app.route("/savings-accounts/<sid>", methods=["GET"])
def get_savings_account(sid):
    user_id, role = auth_and_role(["Member", "ConciergeAgent", "PlatformAdmin"])
    sa = get_or_404(db.savings_accounts, sid)
    check_owner(role, user_id, sa["member_id"])
    return success(ser.ser_savings_account(sa), 200)


@app.route("/savings-accounts", methods=["GET"])
def list_savings_accounts():
    user_id, role = auth_and_role(["Member", "PlatformAdmin"])
    limit, offset = parse_pagination()
    from flask import request
    member_id = request.args.get("member_id")
    rows = list(db.savings_accounts.values())
    if role == "Member":
        rows = [s for s in rows if s["member_id"] == user_id]
    if member_id is not None:
        rows = [s for s in rows if s["member_id"] == member_id]
    rows = sort_by_created(rows)
    page, pmeta = paginate(rows, limit, offset)
    return success([ser.ser_savings_account(s) for s in page], 200, is_array=True, pagination=pmeta)


@app.route("/savings-accounts/<sid>/close", methods=["POST"])
def close_savings_account(sid):
    user_id, role = auth_and_role(["Member"])
    sa = get_or_404(db.savings_accounts, sid)
    check_owner(role, user_id, sa["member_id"])
    if sa["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Savings account is not OPEN")
    sa["status"] = "CLOSED"
    touch(sa)
    return success(ser.ser_savings_account(sa), 200)


# ==========================================================================
# LINKED ACCOUNTS
# ==========================================================================
@app.route("/linked-accounts", methods=["POST"])
def create_linked_account():
    user_id, role = auth_and_role(["Member"])
    body = get_body()
    require_fields(body, ["member_id", "institution_name", "account_type"])
    member_id = require_string(body, "member_id")
    institution_name = require_string(body, "institution_name")
    account_type = require_enum(body, "account_type", {"CHECKING", "CREDIT_CARD"})
    check_owner(role, user_id, member_id)
    fk_or_404(db.members, member_id)
    lid = new_id()
    ts = now_iso()
    la = {
        "id": lid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "member_id": member_id,
        "institution_name": institution_name,
        "account_type": account_type,
        "status": "LINKED",
        "detected_charge_count": 0,
    }
    db.linked_accounts[lid] = la
    return success(ser.ser_linked_account(la), 201)


@app.route("/linked-accounts/<lid>", methods=["GET"])
def get_linked_account(lid):
    user_id, role = auth_and_role(["Member", "ConciergeAgent", "PlatformAdmin"])
    la = get_or_404(db.linked_accounts, lid)
    check_owner(role, user_id, la["member_id"])
    return success(ser.ser_linked_account(la), 200)


@app.route("/linked-accounts", methods=["GET"])
def list_linked_accounts():
    user_id, role = auth_and_role(["Member", "PlatformAdmin"])
    limit, offset = parse_pagination()
    from flask import request
    member_id = request.args.get("member_id")
    rows = list(db.linked_accounts.values())
    if role == "Member":
        rows = [l for l in rows if l["member_id"] == user_id]
    if member_id is not None:
        rows = [l for l in rows if l["member_id"] == member_id]
    rows = sort_by_created(rows)
    page, pmeta = paginate(rows, limit, offset)
    return success([ser.ser_linked_account(l) for l in page], 200, is_array=True, pagination=pmeta)


@app.route("/linked-accounts/<lid>/unlink", methods=["POST"])
def unlink_account(lid):
    user_id, role = auth_and_role(["Member"])
    la = get_or_404(db.linked_accounts, lid)
    check_owner(role, user_id, la["member_id"])
    if la["status"] != "LINKED":
        raise err("ERR_INVALID_STATE", "Linked account is not LINKED")
    la["status"] = "UNLINKED"
    touch(la)
    return success(ser.ser_linked_account(la), 200)


# ==========================================================================
# RECURRING CHARGES
# ==========================================================================
@app.route("/recurring-charges", methods=["POST"])
def create_recurring_charge():
    user_id, role = auth_and_role(["Member", "PlatformAdmin"])
    body = get_body()
    require_fields(body, ["linked_account_id", "merchant_name", "amount_cents",
                          "cadence", "first_seen_utc"])
    linked_account_id = require_string(body, "linked_account_id")
    merchant_name = require_string(body, "merchant_name")
    amount_cents = require_int(body, "amount_cents")
    cadence = require_enum(body, "cadence", {"MONTHLY", "ANNUAL", "WEEKLY"})
    category = body.get("category")
    if category is None:
        category = "OTHER"
    else:
        category = require_enum(body, "category",
                               {"STREAMING", "TELECOM", "INSURANCE", "UTILITY", "SOFTWARE", "OTHER"})
    first_seen_utc = require_string(body, "first_seen_utc")
    # FK
    la = fk_or_404(db.linked_accounts, linked_account_id)
    if role == "Member":
        check_owner(role, user_id, la["member_id"])
    if amount_cents < 1:
        raise err("ERR_VALUE_OUT_OF_RANGE", "amount_cents must be >= 1")
    cid = new_id()
    ts = now_iso()
    annualized = calc.annualize_charge_cost(amount_cents, cadence)
    charge = {
        "id": cid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "linked_account_id": linked_account_id,
        "merchant_name": merchant_name,
        "amount_cents": amount_cents,
        "cadence": cadence,
        "category": category,
        "first_seen_utc": first_seen_utc,
        "annualized_cost_cents": annualized,
        "status": "DETECTED",
    }
    db.recurring_charges[cid] = charge
    la["detected_charge_count"] = la["detected_charge_count"] + 1
    touch(la)
    return success(ser.ser_recurring_charge(charge), 201)


@app.route("/recurring-charges/<cid>", methods=["GET"])
def get_recurring_charge(cid):
    user_id, role = auth_and_role(["Member", "ConciergeAgent", "PlatformAdmin"])
    c = get_or_404(db.recurring_charges, cid)
    if role == "Member":
        la = db.linked_accounts.get(c["linked_account_id"])
        if la and la["member_id"] != user_id:
            raise err("ERR_NOT_RESOURCE_OWNER", "Member does not own this charge")
    return success(ser.ser_recurring_charge(c), 200)


@app.route("/recurring-charges", methods=["GET"])
def list_recurring_charges():
    user_id, role = auth_and_role(["Member", "ConciergeAgent", "PlatformAdmin"])
    limit, offset = parse_pagination()
    from flask import request
    linked_account_id = request.args.get("linked_account_id")
    status = request.args.get("status")
    rows = list(db.recurring_charges.values())
    if role == "Member":
        owned = {l["id"] for l in db.linked_accounts.values() if l["member_id"] == user_id}
        rows = [c for c in rows if c["linked_account_id"] in owned]
    if linked_account_id is not None:
        rows = [c for c in rows if c["linked_account_id"] == linked_account_id]
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    rows = sort_by_created(rows)
    page, pmeta = paginate(rows, limit, offset)
    return success([ser.ser_recurring_charge(c) for c in page], 200, is_array=True, pagination=pmeta)


@app.route("/recurring-charges/<cid>/confirm", methods=["POST"])
def confirm_charge(cid):
    user_id, role = auth_and_role(["Member"])
    c = get_or_404(db.recurring_charges, cid)
    la = db.linked_accounts.get(c["linked_account_id"])
    if la is not None:
        check_owner(role, user_id, la["member_id"])
    if c["status"] != "DETECTED":
        raise err("ERR_INVALID_STATE", "Charge is not DETECTED")
    if la is None or la["status"] != "LINKED":
        raise err("ERR_LINKED_RESOURCE_STATE", "Linked account is not LINKED")
    c["status"] = "CONFIRMED"
    c["annualized_cost_cents"] = calc.annualize_charge_cost(c["amount_cents"], c["cadence"])
    touch(c)
    return success(ser.ser_recurring_charge(c), 200)


def _charge_in_use(charge_id):
    NON_TERMINAL_SUB = {"ACTIVE", "CANCEL_REQUESTED", "CANCEL_FAILED"}
    NON_TERMINAL_CASE = {"OPEN", "PROPOSED", "COUNTERED"}
    NON_TERMINAL_CLAIM = {"FILED", "UNDER_REVIEW", "DISPUTED"}
    for s in db.subscriptions.values():
        if s["recurring_charge_id"] == charge_id and s["status"] in NON_TERMINAL_SUB:
            return True
    for n in db.negotiation_cases.values():
        if n["recurring_charge_id"] == charge_id and n["status"] in NON_TERMINAL_CASE:
            return True
    for r in db.refund_claims.values():
        if r["recurring_charge_id"] == charge_id and r["status"] in NON_TERMINAL_CLAIM:
            return True
    return False


@app.route("/recurring-charges/<cid>/dismiss", methods=["POST"])
def dismiss_charge(cid):
    user_id, role = auth_and_role(["Member"])
    c = get_or_404(db.recurring_charges, cid)
    la = db.linked_accounts.get(c["linked_account_id"])
    if la is not None:
        check_owner(role, user_id, la["member_id"])
    if c["status"] not in ("DETECTED", "CONFIRMED"):
        raise err("ERR_INVALID_STATE", "Charge cannot be dismissed from its current state")
    if c["status"] == "CONFIRMED" and _charge_in_use(cid):
        raise err("ERR_CHARGE_IN_USE", "Charge is in use by a non-terminal resource")
    c["status"] = "DISMISSED"
    touch(c)
    if la is not None:
        la["detected_charge_count"] = max(0, la["detected_charge_count"] - 1)
        touch(la)
    return success(ser.ser_recurring_charge(c), 200)


# ==========================================================================
# SUBSCRIPTIONS
# ==========================================================================
@app.route("/subscriptions", methods=["POST"])
def create_subscription():
    user_id, role = auth_and_role(["Member"])
    body = get_body()
    require_fields(body, ["member_id", "recurring_charge_id", "plan_name", "monthly_cost_cents"])
    member_id = require_string(body, "member_id")
    recurring_charge_id = require_string(body, "recurring_charge_id")
    plan_name = require_string(body, "plan_name")
    monthly_cost_cents = require_int(body, "monthly_cost_cents")
    is_free_trial = optional_bool(body, "is_free_trial", False)
    trial_end_utc = body.get("trial_end_utc")
    trial_reminder_lead_days = body.get("trial_reminder_lead_days")
    if trial_reminder_lead_days is None:
        trial_reminder_lead_days = 3
    else:
        trial_reminder_lead_days = require_int(body, "trial_reminder_lead_days")
    check_owner(role, user_id, member_id)
    fk_or_404(db.members, member_id)
    charge = fk_or_404(db.recurring_charges, recurring_charge_id)
    # range checks
    if monthly_cost_cents < 0:
        raise err("ERR_VALUE_OUT_OF_RANGE", "monthly_cost_cents must be >= 0")
    if trial_reminder_lead_days < 0:
        raise err("ERR_VALUE_OUT_OF_RANGE", "trial_reminder_lead_days must be >= 0")
    # linked resource state: charge must be CONFIRMED
    if charge["status"] != "CONFIRMED":
        raise err("ERR_LINKED_RESOURCE_STATE", "Charge is not CONFIRMED")
    # trial required
    if is_free_trial and not trial_end_utc:
        raise err("ERR_TRIAL_END_REQUIRED", "trial_end_utc required when is_free_trial=true")
    sid = new_id()
    ts = now_iso()
    sub = {
        "id": sid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "member_id": member_id,
        "recurring_charge_id": recurring_charge_id,
        "plan_name": plan_name,
        "monthly_cost_cents": monthly_cost_cents,
        "is_free_trial": is_free_trial,
        "trial_end_utc": trial_end_utc,
        "trial_reminder_lead_days": trial_reminder_lead_days,
        "status": "ACTIVE",
        "cancelled_utc": None,
    }
    db.subscriptions[sid] = sub
    return success(ser.ser_subscription(sub), 201)


@app.route("/subscriptions/<sid>", methods=["GET"])
def get_subscription(sid):
    user_id, role = auth_and_role(["Member", "ConciergeAgent", "PlatformAdmin"])
    s = get_or_404(db.subscriptions, sid)
    check_owner(role, user_id, s["member_id"])
    return success(ser.ser_subscription(s), 200)


@app.route("/subscriptions", methods=["GET"])
def list_subscriptions():
    user_id, role = auth_and_role(["Member", "ConciergeAgent", "PlatformAdmin"])
    limit, offset = parse_pagination()
    from flask import request
    member_id = request.args.get("member_id")
    recurring_charge_id = request.args.get("recurring_charge_id")
    reminder_due = request.args.get("reminder_due")
    rows = list(db.subscriptions.values())
    if role == "Member":
        rows = [s for s in rows if s["member_id"] == user_id]
    if member_id is not None:
        rows = [s for s in rows if s["member_id"] == member_id]
    if recurring_charge_id is not None:
        rows = [s for s in rows if s["recurring_charge_id"] == recurring_charge_id]
    if reminder_due is not None:
        want = reminder_due.lower() == "true"
        rows = [s for s in rows if ser.compute_reminder_due(s) == want]
    rows = sort_by_created(rows)
    page, pmeta = paginate(rows, limit, offset)
    return success([ser.ser_subscription(s) for s in page], 200, is_array=True, pagination=pmeta)


@app.route("/subscriptions/<sid>/request-cancel", methods=["POST"])
def request_cancel_subscription(sid):
    user_id, role = auth_and_role(["Member"])
    s = get_or_404(db.subscriptions, sid)
    check_owner(role, user_id, s["member_id"])
    body = get_body()
    require_fields(body, ["expected_subscription_version"])
    expected = require_int(body, "expected_subscription_version")
    if s["status"] not in ("ACTIVE", "CANCEL_FAILED"):
        raise err("ERR_INVALID_STATE", "Subscription cannot be cancel-requested")
    # OCC then member suspension? PRD: member must be ACTIVE to request cancel.
    # Order per workflow: requires member ACTIVE and matching version.
    # Priority table: OCC (18) before member suspension (19).
    if expected != s["version"]:
        raise err("ERR_STALE_VERSION", "expected_subscription_version is stale")
    m = db.members.get(s["member_id"])
    if m is None or m["status"] != "ACTIVE":
        raise err("ERR_MEMBER_SUSPENDED", "Member is suspended")
    s["status"] = "CANCEL_REQUESTED"
    touch(s)
    return success(ser.ser_subscription(s), 200)


@app.route("/subscriptions/<sid>/confirm-cancel", methods=["POST"])
def confirm_cancel_subscription(sid):
    auth_and_role(["ConciergeAgent"])
    s = get_or_404(db.subscriptions, sid)
    if s["status"] != "CANCEL_REQUESTED":
        raise err("ERR_INVALID_STATE", "Subscription is not CANCEL_REQUESTED")
    s["status"] = "CANCELLED"
    s["cancelled_utc"] = db.clock_current_utc
    touch(s)
    return success(ser.ser_subscription(s), 200)


@app.route("/subscriptions/<sid>/fail-cancel", methods=["POST"])
def fail_cancel_subscription(sid):
    auth_and_role(["ConciergeAgent"])
    s = get_or_404(db.subscriptions, sid)
    if s["status"] != "CANCEL_REQUESTED":
        raise err("ERR_INVALID_STATE", "Subscription is not CANCEL_REQUESTED")
    s["status"] = "CANCEL_FAILED"
    touch(s)
    return success(ser.ser_subscription(s), 200)


# ==========================================================================
# CONCIERGE AGENTS
# ==========================================================================
@app.route("/concierge-agents", methods=["POST"])
def create_concierge_agent():
    auth_and_role(["PlatformAdmin"])
    body = get_body()
    require_fields(body, ["display_name"])
    display_name = require_string(body, "display_name")
    max_open_cases = body.get("max_open_cases")
    if max_open_cases is None:
        max_open_cases = 5
    else:
        max_open_cases = require_int(body, "max_open_cases")
        if max_open_cases < 1:
            raise err("ERR_VALUE_OUT_OF_RANGE", "max_open_cases must be >= 1")
    aid = new_id()
    ts = now_iso()
    agent = {
        "id": aid,
        "created_at": ts,
        "display_name": display_name,
        "max_open_cases": max_open_cases,
        "open_case_count": 0,
    }
    db.concierge_agents[aid] = agent
    return success(ser.ser_concierge_agent(agent), 201)


@app.route("/concierge-agents/<aid>", methods=["GET"])
def get_concierge_agent(aid):
    auth_and_role(["ConciergeAgent", "PlatformAdmin"])
    a = get_or_404(db.concierge_agents, aid)
    return success(ser.ser_concierge_agent(a), 200)


@app.route("/concierge-agents", methods=["GET"])
def list_concierge_agents():
    auth_and_role(["PlatformAdmin"])
    limit, offset = parse_pagination()
    rows = sort_by_created(list(db.concierge_agents.values()))
    page, pmeta = paginate(rows, limit, offset)
    return success([ser.ser_concierge_agent(a) for a in page], 200, is_array=True, pagination=pmeta)


# ==========================================================================
# NEGOTIATION CASES
# ==========================================================================
@app.route("/negotiation-cases", methods=["POST"])
def create_negotiation_case():
    user_id, role = auth_and_role(["Member"])
    body = get_body()
    require_fields(body, ["member_id", "recurring_charge_id", "assigned_agent_id"])
    member_id = require_string(body, "member_id")
    recurring_charge_id = require_string(body, "recurring_charge_id")
    assigned_agent_id = require_string(body, "assigned_agent_id")
    check_owner(role, user_id, member_id)
    m = fk_or_404(db.members, member_id)
    charge = fk_or_404(db.recurring_charges, recurring_charge_id)
    agent = fk_or_404(db.concierge_agents, assigned_agent_id)
    if charge["status"] != "CONFIRMED":
        raise err("ERR_LINKED_RESOURCE_STATE", "Charge is not CONFIRMED")
    # agent capacity
    if agent["open_case_count"] >= agent["max_open_cases"]:
        raise err("ERR_AGENT_CAPACITY_EXCEEDED", "Agent is at capacity")
    # member must be ACTIVE
    if m["status"] != "ACTIVE":
        raise err("ERR_MEMBER_SUSPENDED", "Member is suspended")
    nid = new_id()
    ts = now_iso()
    case = {
        "id": nid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "member_id": member_id,
        "recurring_charge_id": recurring_charge_id,
        "assigned_agent_id": assigned_agent_id,
        "baseline_annual_cost_cents": charge["annualized_cost_cents"],
        "current_offer_annual_cost_cents": None,
        "agreed_annual_cost_cents": None,
        "round_count": 0,
        "gross_annual_savings_cents": 0,
        "success_fee_cents": 0,
        "member_net_savings_cents": 0,
        "status": "OPEN",
    }
    db.negotiation_cases[nid] = case
    agent["open_case_count"] = agent["open_case_count"] + 1
    return success(ser.ser_negotiation_case(case), 201)


@app.route("/negotiation-cases/<nid>", methods=["GET"])
def get_negotiation_case(nid):
    user_id, role = auth_and_role(["Member", "ConciergeAgent", "PlatformAdmin"])
    n = get_or_404(db.negotiation_cases, nid)
    check_owner(role, user_id, n["member_id"])
    return success(ser.ser_negotiation_case(n), 200)


@app.route("/negotiation-cases", methods=["GET"])
def list_negotiation_cases():
    user_id, role = auth_and_role(["Member", "ConciergeAgent", "PlatformAdmin"])
    limit, offset = parse_pagination()
    from flask import request
    member_id = request.args.get("member_id")
    recurring_charge_id = request.args.get("recurring_charge_id")
    assigned_agent_id = request.args.get("assigned_agent_id")
    status = request.args.get("status")
    rows = list(db.negotiation_cases.values())
    if role == "Member":
        rows = [n for n in rows if n["member_id"] == user_id]
    if member_id is not None:
        rows = [n for n in rows if n["member_id"] == member_id]
    if recurring_charge_id is not None:
        rows = [n for n in rows if n["recurring_charge_id"] == recurring_charge_id]
    if assigned_agent_id is not None:
        rows = [n for n in rows if n["assigned_agent_id"] == assigned_agent_id]
    if status is not None:
        rows = [n for n in rows if n["status"] == status]
    rows = sort_by_created(rows)
    page, pmeta = paginate(rows, limit, offset)
    return success([ser.ser_negotiation_case(n) for n in page], 200, is_array=True, pagination=pmeta)


def _decrement_agent(agent_id):
    agent = db.concierge_agents.get(agent_id)
    if agent is not None:
        agent["open_case_count"] = max(0, agent["open_case_count"] - 1)


@app.route("/negotiation-cases/<nid>/propose", methods=["POST"])
def propose_case(nid):
    auth_and_role(["ConciergeAgent"])
    n = get_or_404(db.negotiation_cases, nid)
    body = get_body()
    require_fields(body, ["offered_annual_cost_cents"])
    offered = require_int(body, "offered_annual_cost_cents")
    if n["status"] not in ("OPEN", "COUNTERED"):
        raise err("ERR_INVALID_STATE", "Cannot propose from current state")
    if offered < 0:
        raise err("ERR_VALUE_OUT_OF_RANGE", "offered_annual_cost_cents must be >= 0")
    if n["round_count"] >= calc.MAX_ROUNDS:
        raise err("ERR_MAX_ROUNDS_REACHED", "Max negotiation rounds reached")
    n["status"] = "PROPOSED"
    n["current_offer_annual_cost_cents"] = offered
    n["round_count"] = n["round_count"] + 1
    touch(n)
    return success(ser.ser_negotiation_case(n), 200)


@app.route("/negotiation-cases/<nid>/counter", methods=["POST"])
def counter_case(nid):
    auth_and_role(["ConciergeAgent"])
    n = get_or_404(db.negotiation_cases, nid)
    body = get_body()
    require_fields(body, ["counter_annual_cost_cents"])
    countered = require_int(body, "counter_annual_cost_cents")
    if n["status"] != "PROPOSED":
        raise err("ERR_INVALID_STATE", "Cannot counter from current state")
    if countered < 0:
        raise err("ERR_VALUE_OUT_OF_RANGE", "counter_annual_cost_cents must be >= 0")
    if n["round_count"] >= calc.MAX_ROUNDS:
        raise err("ERR_MAX_ROUNDS_REACHED", "Max negotiation rounds reached")
    n["status"] = "COUNTERED"
    n["current_offer_annual_cost_cents"] = countered
    touch(n)
    return success(ser.ser_negotiation_case(n), 200)


@app.route("/negotiation-cases/<nid>/accept", methods=["POST"])
def accept_case(nid):
    auth_and_role(["ConciergeAgent"])
    n = get_or_404(db.negotiation_cases, nid)
    if n["status"] not in ("PROPOSED", "COUNTERED"):
        raise err("ERR_INVALID_STATE", "Cannot accept from current state")
    if n["current_offer_annual_cost_cents"] is None or \
            n["current_offer_annual_cost_cents"] > n["baseline_annual_cost_cents"]:
        raise err("ERR_OFFER_ABOVE_BASELINE", "Offer exceeds baseline")
    n["agreed_annual_cost_cents"] = n["current_offer_annual_cost_cents"]
    gross = max(0, n["baseline_annual_cost_cents"] - n["agreed_annual_cost_cents"])
    fee = calc.success_fee_split(gross)
    net = gross - fee
    n["gross_annual_savings_cents"] = gross
    n["success_fee_cents"] = fee
    n["member_net_savings_cents"] = net
    n["status"] = "WON"
    book_ledger_entry(n["member_id"], "NEGOTIATION", gross, fee, net,
                      negotiation_case_id=n["id"])
    recompute_member_lifetime(n["member_id"])
    _decrement_agent(n["assigned_agent_id"])
    touch(n)
    return success(ser.ser_negotiation_case(n), 200)


@app.route("/negotiation-cases/<nid>/abandon", methods=["POST"])
def abandon_case(nid):
    auth_and_role(["ConciergeAgent"])
    n = get_or_404(db.negotiation_cases, nid)
    if n["status"] not in ("OPEN", "PROPOSED", "COUNTERED"):
        raise err("ERR_INVALID_STATE", "Cannot abandon from current state")
    n["status"] = "LOST"
    _decrement_agent(n["assigned_agent_id"])
    touch(n)
    return success(ser.ser_negotiation_case(n), 200)


@app.route("/negotiation-cases/<nid>/cancel", methods=["POST"])
def cancel_case(nid):
    user_id, role = auth_and_role(["Member"])
    n = get_or_404(db.negotiation_cases, nid)
    check_owner(role, user_id, n["member_id"])
    if n["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Cannot cancel from current state")
    n["status"] = "CANCELLED"
    _decrement_agent(n["assigned_agent_id"])
    touch(n)
    return success(ser.ser_negotiation_case(n), 200)


# ==========================================================================
# REFUND CLAIMS
# ==========================================================================
@app.route("/refund-claims", methods=["POST"])
def create_refund_claim():
    user_id, role = auth_and_role(["Member"])
    body = get_body()
    require_fields(body, ["member_id", "recurring_charge_id", "claim_type",
                          "observed_old_amount_cents", "observed_new_amount_cents"])
    member_id = require_string(body, "member_id")
    recurring_charge_id = require_string(body, "recurring_charge_id")
    claim_type = require_enum(body, "claim_type", {"PRICE_DROP", "DOUBLE_BILL", "SERVICE_OUTAGE"})
    observed_old = require_int(body, "observed_old_amount_cents")
    observed_new = require_int(body, "observed_new_amount_cents")
    check_owner(role, user_id, member_id)
    fk_or_404(db.members, member_id)
    charge = fk_or_404(db.recurring_charges, recurring_charge_id)
    if observed_old < 1:
        raise err("ERR_VALUE_OUT_OF_RANGE", "observed_old_amount_cents must be >= 1")
    if observed_new < 0:
        raise err("ERR_VALUE_OUT_OF_RANGE", "observed_new_amount_cents must be >= 0")
    if charge["status"] != "CONFIRMED":
        raise err("ERR_LINKED_RESOURCE_STATE", "Charge is not CONFIRMED")
    claimed = calc.refund_pursuit_amount(claim_type, observed_old, observed_new)
    rid = new_id()
    ts = now_iso()
    claim = {
        "id": rid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "member_id": member_id,
        "recurring_charge_id": recurring_charge_id,
        "claim_type": claim_type,
        "observed_old_amount_cents": observed_old,
        "observed_new_amount_cents": observed_new,
        "claimed_refund_cents": claimed,
        "approved_refund_cents": None,
        "success_fee_cents": 0,
        "member_net_savings_cents": 0,
        "dispute_round": 0,
        "status": "FILED",
    }
    db.refund_claims[rid] = claim
    return success(ser.ser_refund_claim(claim), 201)


@app.route("/refund-claims/<rid>", methods=["GET"])
def get_refund_claim(rid):
    user_id, role = auth_and_role(["Member", "ConciergeAgent", "PlatformAdmin"])
    r = get_or_404(db.refund_claims, rid)
    check_owner(role, user_id, r["member_id"])
    return success(ser.ser_refund_claim(r), 200)


@app.route("/refund-claims", methods=["GET"])
def list_refund_claims():
    user_id, role = auth_and_role(["Member", "ConciergeAgent", "PlatformAdmin"])
    limit, offset = parse_pagination()
    from flask import request
    member_id = request.args.get("member_id")
    recurring_charge_id = request.args.get("recurring_charge_id")
    status = request.args.get("status")
    rows = list(db.refund_claims.values())
    if role == "Member":
        rows = [r for r in rows if r["member_id"] == user_id]
    if member_id is not None:
        rows = [r for r in rows if r["member_id"] == member_id]
    if recurring_charge_id is not None:
        rows = [r for r in rows if r["recurring_charge_id"] == recurring_charge_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sort_by_created(rows)
    page, pmeta = paginate(rows, limit, offset)
    return success([ser.ser_refund_claim(r) for r in page], 200, is_array=True, pagination=pmeta)


@app.route("/refund-claims/<rid>/start-review", methods=["POST"])
def start_review_claim(rid):
    auth_and_role(["ConciergeAgent"])
    r = get_or_404(db.refund_claims, rid)
    if r["status"] not in ("FILED", "DISPUTED"):
        raise err("ERR_INVALID_STATE", "Claim cannot start review from current state")
    r["status"] = "UNDER_REVIEW"
    touch(r)
    return success(ser.ser_refund_claim(r), 200)


@app.route("/refund-claims/<rid>/approve", methods=["POST"])
def approve_claim(rid):
    auth_and_role(["ConciergeAgent"])
    r = get_or_404(db.refund_claims, rid)
    body = get_body()
    require_fields(body, ["approved_refund_cents"])
    approved = require_int(body, "approved_refund_cents")
    if r["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "Claim is not UNDER_REVIEW")
    if approved < 0:
        raise err("ERR_VALUE_OUT_OF_RANGE", "approved_refund_cents must be >= 0")
    if approved > r["claimed_refund_cents"]:
        raise err("ERR_REFUND_ABOVE_CLAIM", "Approved refund exceeds claimed amount")
    r["approved_refund_cents"] = approved
    fee = calc.success_fee_split(approved)
    net = approved - fee
    r["success_fee_cents"] = fee
    r["member_net_savings_cents"] = net
    r["status"] = "REFUNDED"
    book_ledger_entry(r["member_id"], "REFUND", approved, fee, net, refund_claim_id=r["id"])
    recompute_member_lifetime(r["member_id"])
    touch(r)
    return success(ser.ser_refund_claim(r), 200)


@app.route("/refund-claims/<rid>/deny", methods=["POST"])
def deny_claim(rid):
    auth_and_role(["ConciergeAgent"])
    r = get_or_404(db.refund_claims, rid)
    if r["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "Claim is not UNDER_REVIEW")
    r["status"] = "DENIED"
    touch(r)
    return success(ser.ser_refund_claim(r), 200)


@app.route("/refund-claims/<rid>/dispute", methods=["POST"])
def dispute_claim(rid):
    user_id, role = auth_and_role(["Member"])
    r = get_or_404(db.refund_claims, rid)
    check_owner(role, user_id, r["member_id"])
    body = get_body()
    require_fields(body, ["expected_refund_claim_version"])
    expected = require_int(body, "expected_refund_claim_version")
    if r["status"] != "DENIED":
        raise err("ERR_INVALID_STATE", "Claim is not DENIED")
    if r["dispute_round"] >= calc.MAX_DISPUTE_ROUNDS:
        raise err("ERR_MAX_DISPUTE_ROUNDS_REACHED", "Max dispute rounds reached")
    # OCC (priority 18) before member suspension (priority 19)
    if expected != r["version"]:
        raise err("ERR_STALE_VERSION", "expected_refund_claim_version is stale")
    m = db.members.get(r["member_id"])
    if m is None or m["status"] != "ACTIVE":
        raise err("ERR_MEMBER_SUSPENDED", "Member is suspended")
    r["status"] = "DISPUTED"
    r["dispute_round"] = r["dispute_round"] + 1
    touch(r)
    return success(ser.ser_refund_claim(r), 200)


# ==========================================================================
# SAVINGS LEDGER ENTRIES
# ==========================================================================
@app.route("/savings-ledger-entries/<eid>", methods=["GET"])
def get_ledger_entry(eid):
    user_id, role = auth_and_role(["Member", "ConciergeAgent", "PlatformAdmin"])
    e = get_or_404(db.ledger_entries, eid)
    check_owner(role, user_id, e["member_id"])
    return success(ser.ser_ledger_entry(e), 200)


@app.route("/savings-ledger-entries", methods=["GET"])
def list_ledger_entries():
    user_id, role = auth_and_role(["Member", "ConciergeAgent", "PlatformAdmin"])
    limit, offset = parse_pagination()
    from flask import request
    member_id = request.args.get("member_id")
    negotiation_case_id = request.args.get("negotiation_case_id")
    refund_claim_id = request.args.get("refund_claim_id")
    transfer_status = request.args.get("transfer_status")
    rows = list(db.ledger_entries.values())
    if role == "Member":
        rows = [e for e in rows if e["member_id"] == user_id]
    if member_id is not None:
        rows = [e for e in rows if e["member_id"] == member_id]
    if negotiation_case_id is not None:
        rows = [e for e in rows if e["negotiation_case_id"] == negotiation_case_id]
    if refund_claim_id is not None:
        rows = [e for e in rows if e["refund_claim_id"] == refund_claim_id]
    if transfer_status is not None:
        rows = [e for e in rows if e["transfer_status"] == transfer_status]
    rows = sort_by_created(rows)
    page, pmeta = paginate(rows, limit, offset)
    return success([ser.ser_ledger_entry(e) for e in page], 200, is_array=True, pagination=pmeta)


@app.route("/savings-ledger-entries/<eid>/transfer", methods=["POST"])
def transfer_ledger_entry(eid):
    user_id, role = auth_and_role(["Member"])
    e = get_or_404(db.ledger_entries, eid)
    check_owner(role, user_id, e["member_id"])
    if e["transfer_status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Ledger entry is not PENDING")
    m = db.members.get(e["member_id"])
    if m is None or m["status"] != "ACTIVE":
        raise err("ERR_MEMBER_SUSPENDED", "Member is suspended")
    sa_id = m.get("savings_account_id")
    sa = db.savings_accounts.get(sa_id) if sa_id else None
    if sa is None or sa["status"] != "OPEN":
        raise err("ERR_NO_SAVINGS_DESTINATION", "No open savings destination")
    e["transfer_status"] = "TRANSFERRED"
    e["transferred_utc"] = db.clock_current_utc
    sa["balance_cents"] = sa["balance_cents"] + e["member_net_cents"]
    touch(sa)
    return success(ser.ser_ledger_entry(e), 200)


@app.route("/savings-ledger-entries/<eid>/reverse", methods=["POST"])
def reverse_ledger_entry(eid):
    auth_and_role(["ConciergeAgent"])
    e = get_or_404(db.ledger_entries, eid)
    if e["transfer_status"] != "TRANSFERRED":
        raise err("ERR_INVALID_STATE", "Ledger entry is not TRANSFERRED")
    m = db.members.get(e["member_id"])
    sa_id = m.get("savings_account_id") if m else None
    sa = db.savings_accounts.get(sa_id) if sa_id else None
    if sa is None or sa["status"] != "OPEN":
        raise err("ERR_NO_SAVINGS_DESTINATION", "Savings account is not OPEN")
    e["transfer_status"] = "REVERSED"
    e["transferred_utc"] = None
    sa["balance_cents"] = sa["balance_cents"] - e["member_net_cents"]
    touch(sa)
    return success(ser.ser_ledger_entry(e), 200)


# ==========================================================================
# CLOCK
# ==========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    # Per validations priority 1, this endpoint is exempt from the auth-header
    # requirement (like POST /members). It is unauthenticated test-driving.
    body = get_body()
    require_fields(body, ["to_iso8601"])
    to_iso = require_string(body, "to_iso8601")
    db.clock_current_utc = to_iso
    return success(ser.ser_clock(), 200)


if __name__ == "__main__":
    import logging

    # Quiet the Werkzeug dev server: under the 8-round parallel sweep the server
    # is rebooted before every test, and per-request access logging adds boot /
    # response overhead. Silence the access log and the startup banner. Do NOT
    # touch WERKZEUG_RUN_MAIN (that makes Werkzeug expect a reloader FD).
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    try:
        from flask import cli as _flask_cli
        _flask_cli.show_server_banner = lambda *a, **k: None
    except Exception:
        pass

    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
