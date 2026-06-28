"""Claims: submit, screen, approve, route, deny, withdraw."""
from datetime import timedelta

from flask import Blueprint, request

import errors
import calculations as calc
from clock import clock, parse_iso
from db import db, new_id
from helpers import (serialize, base_system_fields, touch, get_or_404,
                     parse_pagination, paginate, sorted_by_created,
                     body, require_str, require_int)
from middleware import require_auth, require_role
from response import ok, ok_list

bp = Blueprint("claims", __name__)

VALID_PERILS = {"CRACKED", "LOST", "THEFT"}
VALID_DENIAL = {"FRAUD", "INELIGIBLE", "LIMIT_EXCEEDED", "NO_COVERAGE"}
TERMINAL_CLAIM = {"FULFILLED", "DENIED", "WITHDRAWN"}


def _owner_check_claim(role, user_id, claim):
    if role == "Subscriber":
        enr = db.enrollments.get(claim["enrollment_id"])
        if enr is None or enr["customer_id"] != user_id:
            errors.fail(errors.ERR_NOT_RESOURCE_OWNER, "Subscriber does not own this claim")


def _approved_or_beyond_count_12mo(enrollment_id):
    """Count claims for this enrollment in APPROVED-or-beyond state within trailing 12 months."""
    beyond = {"APPROVED", "ROUTED_REPAIR", "ROUTED_REPLACE", "FULFILLED"}
    cutoff = clock.now() - timedelta(days=365)
    count = 0
    for c in db.claims.values():
        if c["enrollment_id"] != enrollment_id:
            continue
        if c["status"] not in beyond:
            continue
        if c["incident_at"] is not None and c["incident_at"] >= cutoff:
            count += 1
    return count


# ---------------- Submit ----------------
@bp.route("/claims", methods=["POST"])
def submit_claim():
    user_id, role = require_auth()
    require_role(role, {"Subscriber", "PlatformAdmin"})
    b = body()
    enrollment_id = require_str(b, "enrollment_id")
    peril = b.get("peril")
    incident_at_raw = b.get("incident_at")
    if peril not in VALID_PERILS:
        errors.fail(errors.ERR_VALIDATION, "peril invalid")
    if incident_at_raw is None or not isinstance(incident_at_raw, str):
        errors.fail(errors.ERR_VALIDATION, "incident_at required")

    enr = get_or_404(db.enrollments, enrollment_id)

    if role == "Subscriber" and enr["customer_id"] != user_id:
        errors.fail(errors.ERR_NOT_RESOURCE_OWNER, "Subscriber does not own this enrollment")

    # state: enrollment must be ACTIVE
    if enr["status"] != "ACTIVE":
        errors.fail(errors.ERR_ENROLLMENT_NOT_ACTIVE, "Enrollment not ACTIVE")

    try:
        incident_at = parse_iso(incident_at_raw)
    except ValueError:
        errors.fail(errors.ERR_VALIDATION, "incident_at invalid")

    # incident window: strictly after enrolled_at, at or before current clock
    if enr["enrolled_at"] is None or incident_at <= enr["enrolled_at"] or incident_at > clock.now():
        errors.fail(errors.ERR_INCIDENT_OUT_OF_WINDOW, "incident_at out of window")

    police_report = b.get("police_report_number")
    if peril == "THEFT":
        if not police_report or not isinstance(police_report, str) or police_report == "":
            errors.fail(errors.ERR_POLICE_REPORT_REQUIRED, "police_report_number required for THEFT")
    else:
        police_report = None

    if enr["open_claim_id"] is not None:
        errors.fail(errors.ERR_OPEN_CLAIM_EXISTS, "Enrollment already has an open claim")

    cid = new_id()
    claim = {
        "id": cid,
        "enrollment_id": enrollment_id,
        "peril": peril,
        "incident_at": incident_at,
        "police_report_number": police_report,
        "status": "SUBMITTED",
        "routing": None,
        "deductible_cents": 0,
        "replacement_value_cents": 0,
        "net_payout_cents": 0,
        "denial_reason": None,
        "_seq": db.next_seq(),
    }
    claim.update(base_system_fields(versioned=True))
    db.claims[cid] = claim
    enr["open_claim_id"] = cid
    touch(enr)
    return ok(serialize(claim), 201)


@bp.route("/claims/<cid>", methods=["GET"])
def get_claim(cid):
    user_id, role = require_auth()
    require_role(role, {"PlatformAdmin", "Subscriber", "ClaimsAdjuster", "LogisticsAgent"})
    claim = get_or_404(db.claims, cid)
    _owner_check_claim(role, user_id, claim)
    return ok(serialize(claim), 200)


@bp.route("/claims", methods=["GET"])
def list_claims():
    user_id, role = require_auth()
    require_role(role, {"PlatformAdmin", "Subscriber", "ClaimsAdjuster"})
    limit, offset = parse_pagination()
    vals = list(db.claims.values())
    if role == "Subscriber":
        owned = {e["id"] for e in db.enrollments.values() if e["customer_id"] == user_id}
        vals = [c for c in vals if c["enrollment_id"] in owned]
    enr_f = request.args.get("enrollment_id")
    if enr_f is not None:
        vals = [c for c in vals if c["enrollment_id"] == enr_f]
    vals = sorted_by_created(vals)
    total = len(vals)
    page = paginate(vals, limit, offset)
    return ok_list([serialize(c) for c in page], limit, offset, total)


# ---------------- Screen ----------------
@bp.route("/claims/<cid>/screen", methods=["POST"])
def screen_claim(cid):
    _, role = require_auth()
    require_role(role, {"ClaimsAdjuster"})
    claim = get_or_404(db.claims, cid)
    if claim["status"] != "SUBMITTED":
        errors.fail(errors.ERR_INVALID_STATE, "Claim not SUBMITTED")
    enr = db.enrollments[claim["enrollment_id"]]
    if enr["status"] != "ACTIVE":
        errors.fail(errors.ERR_ENROLLMENT_NOT_ACTIVE, "Enrollment not ACTIVE")
    if enr["open_claim_id"] != claim["id"]:
        errors.fail(errors.ERR_INVALID_STATE, "Claim is not the enrollment's open claim")

    customer = db.customers[enr["customer_id"]]
    # velocity: customer's claims (any status != WITHDRAWN) with incident_at in closed window
    window_start = claim["incident_at"] - timedelta(days=calc.VELOCITY_WINDOW_DAYS)
    customer_enr_ids = {e["id"] for e in db.enrollments.values() if e["customer_id"] == customer["id"]}
    velocity_count = 0
    for c in db.claims.values():
        if c["enrollment_id"] not in customer_enr_ids:
            continue
        if c["status"] == "WITHDRAWN":
            continue
        if c["incident_at"] is None:
            continue
        if window_start <= c["incident_at"] <= claim["incident_at"]:
            velocity_count += 1

    outcome = calc.fraud_outcome(velocity_count)

    fs_id = new_id()
    fs = {
        "id": fs_id,
        "claim_id": claim["id"],
        "customer_id": customer["id"],
        "velocity_count": velocity_count,
        "outcome": outcome,
        "_seq": db.next_seq(),
    }
    fs.update(base_system_fields(versioned=False))
    db.fraud_screens[fs_id] = fs

    if outcome == "BLOCK":
        customer["risk_flag"] = "BLOCKED"
        touch(customer)
    elif outcome == "REVIEW" and customer["risk_flag"] == "GREEN":
        customer["risk_flag"] = "WATCH"
        touch(customer)

    claim["status"] = "UNDER_REVIEW"
    touch(claim)
    return ok(serialize(claim), 200)


def _latest_fraud_screen(claim_id):
    screens = [f for f in db.fraud_screens.values() if f["claim_id"] == claim_id]
    if not screens:
        return None
    return max(screens, key=lambda f: (f["created_at"], f["_seq"]))


# ---------------- Approve ----------------
@bp.route("/claims/<cid>/approve", methods=["POST"])
def approve_claim(cid):
    _, role = require_auth()
    require_role(role, {"ClaimsAdjuster"})
    claim = get_or_404(db.claims, cid)
    if claim["status"] != "UNDER_REVIEW":
        errors.fail(errors.ERR_INVALID_STATE, "Claim not UNDER_REVIEW")
    enr = db.enrollments[claim["enrollment_id"]]
    customer = db.customers[enr["customer_id"]]
    plan = db.plans[enr["plan_id"]]
    b = body()
    expected = require_int(b, "expected_enrollment_version")

    # order: fraud/risk gate -> annual-limit gate -> stale-version gate
    fs = _latest_fraud_screen(claim["id"])
    if customer["risk_flag"] == "BLOCKED" or (fs is not None and fs["outcome"] == "BLOCK"):
        errors.fail(errors.ERR_FRAUD_BLOCKED, "Approval blocked by fraud/risk")

    if _approved_or_beyond_count_12mo(enr["id"]) >= plan["annual_claim_limit"]:
        errors.fail(errors.ERR_CLAIM_LIMIT_EXCEEDED, "Annual claim limit exceeded")

    if expected != enr["version"]:
        errors.fail(errors.ERR_STALE_ENROLLMENT_VERSION, "Stale enrollment version")

    claim["deductible_cents"] = calc.quote_deductible(claim["peril"], plan, customer["risk_flag"])
    claim["status"] = "APPROVED"
    customer["lifetime_approved_claim_count"] += 1
    touch(customer)
    touch(enr)
    touch(claim)
    return ok(serialize(claim), 200)


# ---------------- Route ----------------
@bp.route("/claims/<cid>/route", methods=["POST"])
def route_claim(cid):
    _, role = require_auth()
    require_role(role, {"ClaimsAdjuster"})
    claim = get_or_404(db.claims, cid)
    if claim["status"] != "APPROVED":
        errors.fail(errors.ERR_INVALID_STATE, "Claim not APPROVED")
    enr = db.enrollments[claim["enrollment_id"]]
    plan = db.plans[enr["plan_id"]]
    sku = db.replacement_skus[enr["replacement_sku_id"]]
    b = body()

    # depreciated replacement value (capped) for routing decision
    rep_value = calc.replacement_value(sku, plan, enr["device_purchase_date"], clock.now())

    repair_cost = b.get("repair_cost_cents")
    if claim["peril"] == "CRACKED":
        if repair_cost is None or isinstance(repair_cost, bool) or not isinstance(repair_cost, int):
            errors.fail(errors.ERR_ROUTE_INPUT_MISSING, "repair_cost_cents required for CRACKED route")
        if repair_cost < 0:
            errors.fail(errors.ERR_VALIDATION, "repair_cost_cents must be >= 0")

    go_replace = False
    if claim["peril"] in ("LOST", "THEFT"):
        go_replace = True
    else:  # CRACKED
        if repair_cost > rep_value:
            go_replace = True

    if not go_replace:
        # REPAIR branch
        ro_id = new_id()
        ro = {
            "id": ro_id,
            "claim_id": claim["id"],
            "repair_cost_cents": repair_cost,
            "status": "OPEN",
            "_seq": db.next_seq(),
        }
        ro.update(base_system_fields(versioned=True))
        db.repair_orders[ro_id] = ro
        claim["routing"] = "REPAIR"
        claim["status"] = "ROUTED_REPAIR"
        touch(claim)
        return ok(serialize(claim), 200)
    else:
        # REPLACE branch
        if sku["stock_on_hand"] < 1:
            errors.fail(errors.ERR_NO_STOCK, "No replacement stock available")
        claim["replacement_value_cents"] = rep_value
        claim["net_payout_cents"] = calc.net_payout(rep_value, claim["deductible_cents"])
        ax_id = new_id()
        ax = {
            "id": ax_id,
            "claim_id": claim["id"],
            "replacement_sku_id": enr["replacement_sku_id"],
            "status": "RESERVED",
            "return_due_at": None,
            "nonreturn_fee_cents": 0,
            "_seq": db.next_seq(),
        }
        ax.update(base_system_fields(versioned=True))
        db.advanced_exchanges[ax_id] = ax
        sku["stock_on_hand"] -= 1
        claim["routing"] = "REPLACE"
        claim["status"] = "ROUTED_REPLACE"
        touch(claim)
        return ok(serialize(claim), 200)


# ---------------- Deny ----------------
@bp.route("/claims/<cid>/deny", methods=["POST"])
def deny_claim(cid):
    _, role = require_auth()
    require_role(role, {"ClaimsAdjuster"})
    claim = get_or_404(db.claims, cid)
    if claim["status"] != "UNDER_REVIEW":
        errors.fail(errors.ERR_INVALID_STATE, "Claim not UNDER_REVIEW")
    b = body()
    denial_reason = b.get("denial_reason")
    if denial_reason is None or denial_reason not in VALID_DENIAL:
        errors.fail(errors.ERR_VALIDATION, "denial_reason required and must be valid")
    enr = db.enrollments[claim["enrollment_id"]]
    claim["status"] = "DENIED"
    claim["denial_reason"] = denial_reason
    if denial_reason == "FRAUD":
        customer = db.customers[enr["customer_id"]]
        customer["risk_flag"] = "BLOCKED"
        touch(customer)
    if enr["open_claim_id"] == claim["id"]:
        enr["open_claim_id"] = None
        touch(enr)
    touch(claim)
    return ok(serialize(claim), 200)


# ---------------- Withdraw ----------------
@bp.route("/claims/<cid>/withdraw", methods=["POST"])
def withdraw_claim(cid):
    user_id, role = require_auth()
    require_role(role, {"Subscriber"})
    claim = get_or_404(db.claims, cid)
    enr = db.enrollments[claim["enrollment_id"]]
    if enr["customer_id"] != user_id:
        errors.fail(errors.ERR_NOT_RESOURCE_OWNER, "Subscriber does not own this claim")
    if claim["status"] != "SUBMITTED":
        errors.fail(errors.ERR_INVALID_STATE, "Claim not SUBMITTED")
    claim["status"] = "WITHDRAWN"
    if enr["open_claim_id"] == claim["id"]:
        enr["open_claim_id"] = None
        touch(enr)
    touch(claim)
    return ok(serialize(claim), 200)
