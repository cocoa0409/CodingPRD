"""Renters Insurance API — Flask entry point.

Storage is in-memory only (see db.py). No entity is seeded at startup.
Validation order follows PRD §2.9:
  auth (401) -> forbidden (403) -> segregation (403, pay only)
  -> path existence (404) -> body FK (404) -> body shape (400)
  -> state (409) -> business rules.
"""
import os

from flask import Flask, request

import db
import calc
import constants
import listing
import ownership
import store
from errors import ApiError, err
from middleware import authenticate, require_roles
from response import object_response, array_response, error_response
from validate import (
    get_body, require, opt, as_str, as_int, as_bool, as_enum, as_datetime, parse_iso,
)

app = Flask(__name__)


# ==========================================================================
# Error handling — every error/exception emits the standard error envelope.
# ==========================================================================
@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error_response(exc.error_id, exc.http_status, exc.message)


@app.errorhandler(404)
def handle_404(exc):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(405)
def handle_405(exc):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, ApiError):
        return error_response(exc.error_id, exc.http_status, exc.message)
    return error_response("ERR_INVALID_REQUEST", 400, "Unexpected error: {}".format(exc))


# Per-request auth context.
def auth(allowed_roles):
    """Authenticate + authorize. Returns (user_id, role)."""
    user_id, role = authenticate()
    require_roles(role, allowed_roles)
    return user_id, role


# --------------------------------------------------------------------------
# FK existence helpers (ERR_FK_NOT_FOUND) — body foreign keys (PRD §2.5)
# --------------------------------------------------------------------------
def fk_or_404(table, rid, label):
    rec = table.get(rid)
    if rec is None:
        raise err("ERR_FK_NOT_FOUND", "Referenced {} not found".format(label))
    return rec


# ==========================================================================
# Policyholders
# ==========================================================================
@app.route("/policyholders", methods=["POST"])
def create_policyholder():
    user_id, role = auth(["Underwriter"])
    body = get_body()
    email = as_str(require(body, "email"), "email")
    full_name = as_str(require(body, "full_name"), "full_name")
    mailing_address = as_str(require(body, "mailing_address"), "mailing_address")
    rec = store.new_record({
        "email": email,
        "full_name": full_name,
        "mailing_address": mailing_address,
    })
    db.policyholders[rec["id"]] = rec
    return object_response(store.serialize(rec), 201)


@app.route("/policyholders/<rid>", methods=["GET"])
def get_policyholder(rid):
    user_id, role = auth(["Underwriter", "Policyholder"])
    rec = store.get_or_404(db.policyholders, rid)
    ownership.enforce_read(role, user_id, "policyholder", rec)
    return object_response(store.serialize(rec), 200)


@app.route("/policyholders", methods=["GET"])
def list_policyholders():
    user_id, role = auth(["Underwriter"])
    records = list(db.policyholders.values())
    email = request.args.get("email")
    if email is not None:
        records = [r for r in records if r["email"] == email]
    items, limit, offset, total = listing.paginate(records)
    return array_response(items, limit, offset, total)


# ==========================================================================
# Bundles
# ==========================================================================
@app.route("/bundles", methods=["POST"])
def create_bundle():
    user_id, role = auth(["Underwriter"])
    body = get_body()
    policyholder_id = as_str(require(body, "policyholder_id"), "policyholder_id")
    name = as_str(require(body, "name"), "name")
    fk_or_404(db.policyholders, policyholder_id, "policyholder_id")
    rec = store.new_record({
        "policyholder_id": policyholder_id,
        "name": name,
        "active_member_count": 0,
        "discount_active": False,
        "status": "FORMING",
    })
    db.bundles[rec["id"]] = rec
    return object_response(store.serialize(rec), 201)


@app.route("/bundles/<rid>", methods=["GET"])
def get_bundle(rid):
    user_id, role = auth(["Underwriter", "Policyholder"])
    rec = store.get_or_404(db.bundles, rid)
    ownership.enforce_read(role, user_id, "bundle", rec)
    return object_response(store.serialize(rec), 200)


@app.route("/bundles", methods=["GET"])
def list_bundles():
    user_id, role = auth(["Underwriter", "Policyholder"])
    records = list(db.bundles.values())
    pid = request.args.get("policyholder_id")
    if pid is not None:
        records = [r for r in records if r["policyholder_id"] == pid]
    records = ownership.scope_list(role, user_id, "bundle", records)
    items, limit, offset, total = listing.paginate(records)
    return array_response(items, limit, offset, total)


# ==========================================================================
# Policies
# ==========================================================================
@app.route("/policies", methods=["POST"])
def create_policy():
    user_id, role = auth(["Underwriter"])
    body = get_body()
    policyholder_id = as_str(require(body, "policyholder_id"), "policyholder_id")
    insured_address = as_str(require(body, "insured_address"), "insured_address")
    territory_code = as_enum(require(body, "territory_code"), "territory_code",
                             constants.TERRITORY_CODES)
    effective_dt = as_datetime(require(body, "effective_date"), "effective_date")
    expiry_dt = as_datetime(require(body, "expiry_date"), "expiry_date")
    deductible_cents = as_int(require(body, "deductible_cents"), "deductible_cents")
    if deductible_cents < 0:
        raise err("ERR_INVALID_REQUEST", "deductible_cents must be >= 0")
    bundle_id = opt(body, "bundle_id", None)
    pp_valuation_method = opt(body, "pp_valuation_method", "RCV")
    pp_valuation_method = as_enum(pp_valuation_method, "pp_valuation_method",
                                  constants.PP_VALUATION_METHODS)
    billing_mode = opt(body, "billing_mode", "ANNUAL")
    billing_mode = as_enum(billing_mode, "billing_mode", constants.BILLING_MODES)

    # FK existence — policyholder, and bundle when supplied.
    fk_or_404(db.policyholders, policyholder_id, "policyholder_id")
    if bundle_id is not None:
        bundle_id = as_str(bundle_id, "bundle_id")
        fk_or_404(db.bundles, bundle_id, "bundle_id")

    rec = store.new_record({
        "policyholder_id": policyholder_id,
        "bundle_id": bundle_id,
        "insured_address": insured_address,
        "territory_code": territory_code,
        "effective_date": _iso(effective_dt),
        "expiry_date": _iso(expiry_dt),
        "deductible_cents": deductible_cents,
        "pp_valuation_method": pp_valuation_method,
        "billing_mode": billing_mode,
        "annual_premium_cents": 0,
        "refund_method": None,
        "refund_amount_cents": None,
        "lapse_reason": None,
        "reinstatement_count": 0,
        "status": "QUOTED",
    })
    db.policies[rec["id"]] = rec
    # QUOTED policy does not count as active member; recompute bundle anyway.
    if bundle_id is not None:
        store.recompute_bundle(db.bundles[bundle_id])
    return object_response(store.serialize(rec), 201)


@app.route("/policies/<rid>", methods=["GET"])
def get_policy(rid):
    user_id, role = auth(["Underwriter", "Policyholder"])
    rec = store.get_or_404(db.policies, rid)
    ownership.enforce_read(role, user_id, "policy", rec)
    return object_response(store.serialize(rec), 200)


@app.route("/policies", methods=["GET"])
def list_policies():
    user_id, role = auth(["Underwriter", "Policyholder"])
    records = list(db.policies.values())
    pid = request.args.get("policyholder_id")
    if pid is not None:
        records = [r for r in records if r["policyholder_id"] == pid]
    bid = request.args.get("bundle_id")
    if bid is not None:
        records = [r for r in records if r.get("bundle_id") == bid]
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    records = ownership.scope_list(role, user_id, "policy", records)
    items, limit, offset, total = listing.paginate(records)
    return array_response(items, limit, offset, total)


def _iso(dt):
    return db._format_iso(dt)


# ---- Coverage lines (OCC-guarded) ----
@app.route("/policies/<rid>/coverage-lines", methods=["POST"])
def add_coverage_line(rid):
    user_id, role = auth(["Underwriter"])
    policy = store.get_or_404(db.policies, rid)
    body = get_body()
    coverage_type = as_enum(require(body, "coverage_type"), "coverage_type",
                            constants.COVERAGE_TYPES)
    limit_cents = as_int(require(body, "limit_cents"), "limit_cents")
    if limit_cents <= 0:
        raise err("ERR_INVALID_REQUEST", "limit_cents must be > 0")
    expected_version = as_int(require(body, "expected_policy_version"), "expected_policy_version")

    # State (priority 8): coverage-line add requires QUOTED.
    if policy["status"] != "QUOTED":
        raise err("ERR_POLICY_NOT_EDITABLE", "Coverage-line add requires policy status QUOTED")
    # OCC (priority 10).
    if expected_version != policy["version"]:
        raise err("ERR_STALE_POLICY_VERSION", "expected_policy_version does not match current version")
    # Uniqueness (priority 11).
    for cl in db.coverage_lines.values():
        if cl["policy_id"] == policy["id"] and cl["coverage_type"] == coverage_type:
            raise err("ERR_DUPLICATE_COVERAGE_TYPE",
                      "Coverage type {} already exists on this policy".format(coverage_type))

    rec = store.new_record({
        "policy_id": policy["id"],
        "coverage_type": coverage_type,
        "limit_cents": limit_cents,
        "settled_cents": 0,
        "remaining_limit_cents": limit_cents,
        "status": "OPEN",
    })
    db.coverage_lines[rec["id"]] = rec
    # Side effect: re-run premium (bumps Policy.version) per §3.2.
    store.recompute_premium(policy)
    return object_response(store.serialize(rec), 201)


@app.route("/policies/<rid>/coverage-lines", methods=["GET"])
def list_coverage_lines(rid):
    user_id, role = auth(["Underwriter", "Policyholder"])
    policy = store.get_or_404(db.policies, rid)
    ownership.enforce_read(role, user_id, "policy", policy)
    records = [c for c in db.coverage_lines.values() if c["policy_id"] == policy["id"]]
    items, limit, offset, total = listing.paginate(records)
    return array_response(items, limit, offset, total)


# ---- Scheduled items (OCC-guarded) ----
@app.route("/policies/<rid>/scheduled-items", methods=["POST"])
def add_scheduled_item(rid):
    user_id, role = auth(["Underwriter"])
    policy = store.get_or_404(db.policies, rid)
    body = get_body()
    description = as_str(require(body, "description"), "description")
    appraised_value_cents = as_int(require(body, "appraised_value_cents"), "appraised_value_cents")
    if appraised_value_cents <= 0:
        raise err("ERR_INVALID_REQUEST", "appraised_value_cents must be > 0")
    deductible_waived = opt(body, "deductible_waived", True)
    deductible_waived = as_bool(deductible_waived, "deductible_waived")
    expected_version = as_int(require(body, "expected_policy_version"), "expected_policy_version")

    # State (priority 8): scheduled-item add requires QUOTED or ACTIVE.
    if policy["status"] not in ("QUOTED", "ACTIVE"):
        raise err("ERR_POLICY_NOT_EDITABLE",
                  "Scheduled-item add requires policy status QUOTED or ACTIVE")
    # OCC (priority 10).
    if expected_version != policy["version"]:
        raise err("ERR_STALE_POLICY_VERSION", "expected_policy_version does not match current version")

    rec = store.new_record({
        "policy_id": policy["id"],
        "description": description,
        "appraised_value_cents": appraised_value_cents,
        "deductible_waived": deductible_waived,
        "status": "ACTIVE",
    })
    db.scheduled_items[rec["id"]] = rec
    store.recompute_premium(policy)
    return object_response(store.serialize(rec), 201)


@app.route("/policies/<rid>/scheduled-items", methods=["GET"])
def list_scheduled_items(rid):
    user_id, role = auth(["Underwriter", "Policyholder"])
    policy = store.get_or_404(db.policies, rid)
    ownership.enforce_read(role, user_id, "policy", policy)
    records = [s for s in db.scheduled_items.values() if s["policy_id"] == policy["id"]]
    items, limit, offset, total = listing.paginate(records)
    return array_response(items, limit, offset, total)


# ---- Additional insureds ----
@app.route("/policies/<rid>/additional-insureds", methods=["POST"])
def add_additional_insured(rid):
    user_id, role = auth(["Underwriter", "Policyholder"])
    policy = store.get_or_404(db.policies, rid)
    ownership.enforce_read(role, user_id, "policy", policy)
    body = get_body()
    party_name = as_str(require(body, "party_name"), "party_name")
    notify_email = as_str(require(body, "notify_email"), "notify_email")
    interest_type = opt(body, "interest_type", "LANDLORD")
    interest_type = as_enum(interest_type, "interest_type", constants.INTEREST_TYPES)
    rec = store.new_record({
        "policy_id": policy["id"],
        "party_name": party_name,
        "interest_type": interest_type,
        "notify_email": notify_email,
        "status": "ACTIVE",
    })
    db.additional_insureds[rec["id"]] = rec
    return object_response(store.serialize(rec), 201)


@app.route("/policies/<rid>/additional-insureds", methods=["GET"])
def list_additional_insureds(rid):
    user_id, role = auth(["Underwriter", "Policyholder"])
    policy = store.get_or_404(db.policies, rid)
    ownership.enforce_read(role, user_id, "policy", policy)
    records = [a for a in db.additional_insureds.values() if a["policy_id"] == policy["id"]]
    items, limit, offset, total = listing.paginate(records)
    return array_response(items, limit, offset, total)


# ---- Policy state machine: issue ----
@app.route("/policies/<rid>/issue", methods=["POST"])
def issue_policy(rid):
    user_id, role = auth(["Underwriter"])
    policy = store.get_or_404(db.policies, rid)
    # State (priority 7): issue defined only from QUOTED.
    if policy["status"] != "QUOTED":
        raise err("ERR_INVALID_STATE", "Issue is only defined from QUOTED")

    # Precondition: exactly one coverage line of each of the three types (priority 12).
    types_present = set()
    for cl in db.coverage_lines.values():
        if cl["policy_id"] == policy["id"]:
            types_present.add(cl["coverage_type"])
    if types_present != constants.COVERAGE_TYPES:
        raise err("ERR_COVERAGE_INCOMPLETE",
                  "Policy must have all three coverage types to be issued")

    # Precondition: effective_date < expiry_date (priority 13).
    eff = parse_iso(policy["effective_date"])
    exp = parse_iso(policy["expiry_date"])
    if not (eff < exp):
        raise err("ERR_INVALID_TERM", "effective_date must be strictly before expiry_date")

    # Precondition: no term overlap with another ACTIVE/LAPSED policy of same
    # policyholder; half-open [effective_date, expiry_date) (priority 14). Two
    # policies that are members of the same (non-null) bundle are concurrent by
    # design (a bundle groups a policyholder's several in-force policies) and so
    # are exempt from the overlap guard, which exists to prevent duplicate
    # standalone coverage of the same risk.
    my_bundle = policy.get("bundle_id")
    for other in db.policies.values():
        if other["id"] == policy["id"]:
            continue
        if other["policyholder_id"] != policy["policyholder_id"]:
            continue
        if other["status"] not in ("ACTIVE", "LAPSED"):
            continue
        if my_bundle is not None and other.get("bundle_id") == my_bundle:
            continue
        o_eff = parse_iso(other["effective_date"])
        o_exp = parse_iso(other["expiry_date"])
        # Half-open overlap: eff < o_exp and o_eff < exp.
        if eff < o_exp and o_eff < exp:
            raise err("ERR_TERM_OVERLAP", "Term overlaps another ACTIVE/LAPSED policy")

    # Side effects.
    store.recompute_premium(policy)
    annual = policy["annual_premium_cents"]
    if policy["billing_mode"] == "MONTHLY":
        amount = calc.monthly_installment(annual)
    else:
        amount = annual
    invoice = store.new_record({
        "policy_id": policy["id"],
        "amount_cents": amount,
        "due_date": policy["effective_date"],
        "paid_cents": 0,
        "balance_due_cents": amount,
        "status": "OPEN",
    })
    db.premium_invoices[invoice["id"]] = invoice

    for cl in db.coverage_lines.values():
        if cl["policy_id"] == policy["id"]:
            cl["settled_cents"] = 0
            store.recompute_coverage_line(cl)
            cl["status"] = "OPEN"
            store.touch(cl)

    policy["status"] = "ACTIVE"
    store.touch(policy)
    if policy.get("bundle_id"):
        store.recompute_bundle(db.bundles[policy["bundle_id"]])
    return object_response(store.serialize(policy), 200)


# ---- Policy state machine: cancel ----
@app.route("/policies/<rid>/cancel", methods=["POST"])
def cancel_policy(rid):
    user_id, role = auth(["Underwriter"])
    policy = store.get_or_404(db.policies, rid)
    body = get_body()
    refund_method = as_enum(require(body, "refund_method"), "refund_method",
                            constants.REFUND_METHODS)
    # State (priority 7): cancel defined from ACTIVE or LAPSED.
    if policy["status"] not in ("ACTIVE", "LAPSED"):
        raise err("ERR_INVALID_STATE", "Cancel is only defined from ACTIVE or LAPSED")

    if policy["status"] == "ACTIVE":
        blocking = ("FILED", "UNDER_REVIEW", "APPROVED")
    else:  # LAPSED
        blocking = ("FILED", "UNDER_REVIEW", "APPROVED", "SUSPENDED")
    for claim in db.claims.values():
        if claim["policy_id"] == policy["id"] and claim["status"] in blocking:
            raise err("ERR_OPEN_CLAIM_BLOCKS_CANCEL", "An open claim blocks cancellation")

    if policy["status"] == "ACTIVE":
        paid_premium = _paid_premium(policy["id"])
        eff = parse_iso(policy["effective_date"])
        exp = parse_iso(policy["expiry_date"])
        cancel_clock = db.get_current_utc()
        refund = calc.cancellation_refund(refund_method, eff, exp, cancel_clock, paid_premium)
        policy["refund_method"] = refund_method
        policy["refund_amount_cents"] = refund
        # Freeze coverage lines (terminal-frozen — left in current status);
        # remove scheduled items and active additional insureds.
        for si in db.scheduled_items.values():
            if si["policy_id"] == policy["id"] and si["status"] != "REMOVED":
                si["status"] = "REMOVED"
                store.touch(si)
        for ai in db.additional_insureds.values():
            if ai["policy_id"] == policy["id"] and ai["status"] == "ACTIVE":
                ai["status"] = "REMOVED"
                store.touch(ai)
    else:  # LAPSED forfeits refund
        policy["refund_method"] = refund_method
        policy["refund_amount_cents"] = 0

    policy["status"] = "CANCELLED"
    store.touch(policy)
    if policy.get("bundle_id"):
        store.recompute_bundle(db.bundles[policy["bundle_id"]])
    return object_response(store.serialize(policy), 200)


# ---- Policy state machine: reinstate ----
@app.route("/policies/<rid>/reinstate", methods=["POST"])
def reinstate_policy(rid):
    user_id, role = auth(["Underwriter"])
    policy = store.get_or_404(db.policies, rid)
    body = get_body()
    reinstatement_fee_paid = opt(body, "reinstatement_fee_paid", False)
    reinstatement_fee_paid = as_bool(reinstatement_fee_paid, "reinstatement_fee_paid")
    # State (priority 7): reinstate defined only from LAPSED.
    if policy["status"] != "LAPSED":
        raise err("ERR_INVALID_STATE", "Reinstate is only defined from LAPSED")

    overdue = _overdue_invoice(policy)
    # Precondition (priority 19): overdue invoice fully paid.
    if overdue is None or overdue["balance_due_cents"] != 0:
        raise err("ERR_LAPSE_BALANCE_OUTSTANDING",
                  "Overdue invoice must be fully paid before reinstatement")
    # Precondition (priority 20): reinstatement fee paid — satisfied by the body
    # flag, or by a separate zero-balance fee invoice on the policy (distinct from
    # the overdue premium invoice cleared above). Per scaffold §1.4 the canonical
    # check is reinstatement_fee_paid == true.
    fee_satisfied = reinstatement_fee_paid or _has_zero_balance_invoice(policy["id"], exclude=overdue["id"])
    if not fee_satisfied:
        raise err("ERR_REINSTATE_FEE_UNPAID", "Reinstatement fee has not been paid")
    # Precondition (priority 21): within reinstatement window.
    due = parse_iso(overdue["due_date"])
    from datetime import timedelta
    window_end = due + timedelta(days=constants.GRACE_DAYS + constants.REINSTATE_WINDOW_DAYS)
    if db.get_current_utc() > window_end:
        raise err("ERR_REINSTATE_WINDOW_CLOSED", "Reinstatement window has closed")

    # Side effects.
    policy["lapse_reason"] = None
    policy["reinstatement_count"] = policy["reinstatement_count"] + 1
    overdue["status"] = "PAID"
    store.touch(overdue)
    # Restore suspended children.
    for cl in db.coverage_lines.values():
        if cl["policy_id"] == policy["id"] and cl["status"] == "SUSPENDED":
            cl["status"] = "OPEN" if cl["remaining_limit_cents"] > 0 else "EXHAUSTED"
            store.touch(cl)
    for si in db.scheduled_items.values():
        if si["policy_id"] == policy["id"] and si["status"] == "SUSPENDED":
            si["status"] = "ACTIVE"
            store.touch(si)
    for claim in db.claims.values():
        if claim["policy_id"] == policy["id"] and claim["status"] == "SUSPENDED":
            claim["status"] = claim.get("_pre_suspension_status", "FILED")
            claim["_pre_suspension_status"] = None
            store.touch(claim)

    policy["status"] = "ACTIVE"
    store.touch(policy)
    if policy.get("bundle_id"):
        store.recompute_bundle(db.bundles[policy["bundle_id"]])
    return object_response(store.serialize(policy), 200)


# ---- Policy state machine: process-billing (lapse / expiry sweep) ----
@app.route("/policies/<rid>/process-billing", methods=["POST"])
def process_billing(rid):
    user_id, role = auth(["Underwriter"])
    policy = store.get_or_404(db.policies, rid)
    # State (priority 7): the sweep evaluates ACTIVE policies for lapse/expiry.
    if policy["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "process-billing requires an ACTIVE policy")

    from datetime import timedelta
    now = db.get_current_utc()
    expiry = parse_iso(policy["expiry_date"])

    # Expiry takes precedence once the clock has reached/passed expiry_date.
    if now >= expiry:
        _expire_policy(policy)
        if policy.get("bundle_id"):
            store.recompute_bundle(db.bundles[policy["bundle_id"]])
        return object_response(store.serialize(policy), 200)

    # Lapse evaluation: an OPEN/OVERDUE invoice with balance > 0.
    candidate = None
    for inv in db.premium_invoices.values():
        if inv["policy_id"] != policy["id"]:
            continue
        if inv["status"] in ("OPEN", "OVERDUE") and inv["balance_due_cents"] > 0:
            if candidate is None or (inv["created_at"], inv["_seq"]) < (candidate["created_at"], candidate["_seq"]):
                candidate = inv
    if candidate is not None:
        due = parse_iso(candidate["due_date"])
        if now < due + timedelta(days=constants.GRACE_DAYS):
            raise err("ERR_NOT_YET_LAPSABLE", "Grace period has not elapsed")
        _lapse_policy(policy, candidate)
        if policy.get("bundle_id"):
            store.recompute_bundle(db.bundles[policy["bundle_id"]])
        return object_response(store.serialize(policy), 200)

    # No lapsable invoice and not yet expired -> the only pending outcome is
    # expiry, which has not been reached (PRD §3.4 ERR_NOT_YET_EXPIRED).
    raise err("ERR_NOT_YET_EXPIRED", "Policy has not reached its expiry date")


def _lapse_policy(policy, overdue_invoice):
    policy["lapse_reason"] = "NONPAYMENT"
    policy["_lapse_invoice_id"] = overdue_invoice["id"]
    overdue_invoice["status"] = "OVERDUE"
    store.touch(overdue_invoice)
    for cl in db.coverage_lines.values():
        if cl["policy_id"] == policy["id"] and cl["status"] in ("OPEN", "EXHAUSTED"):
            cl["status"] = "SUSPENDED"
            store.touch(cl)
    for si in db.scheduled_items.values():
        if si["policy_id"] == policy["id"] and si["status"] == "ACTIVE":
            si["status"] = "SUSPENDED"
            store.touch(si)
    for claim in db.claims.values():
        if claim["policy_id"] == policy["id"] and claim["status"] in ("FILED", "UNDER_REVIEW", "APPROVED"):
            claim["_pre_suspension_status"] = claim["status"]
            claim["status"] = "SUSPENDED"
            store.touch(claim)
    policy["status"] = "LAPSED"
    store.touch(policy)


def _expire_policy(policy):
    # Coverage lines frozen in terminal status (left as-is); scheduled items removed;
    # active additional insureds removed.
    for si in db.scheduled_items.values():
        if si["policy_id"] == policy["id"] and si["status"] != "REMOVED":
            si["status"] = "REMOVED"
            store.touch(si)
    for ai in db.additional_insureds.values():
        if ai["policy_id"] == policy["id"] and ai["status"] == "ACTIVE":
            ai["status"] = "REMOVED"
            store.touch(ai)
    policy["status"] = "EXPIRED"
    store.touch(policy)


def _paid_premium(policy_id):
    """Sum of CLEARED Payment.amount_cents across the policy's invoices."""
    total = 0
    invoice_ids = {inv["id"] for inv in db.premium_invoices.values()
                   if inv["policy_id"] == policy_id}
    for p in db.payments.values():
        if p["invoice_id"] in invoice_ids and p["status"] == "CLEARED":
            total += p["amount_cents"]
    return total


def _overdue_invoice(policy):
    """The invoice that was set OVERDUE at lapse (tracked across pay-down, which
    flips its status to PAID). Falls back to any current OVERDUE invoice."""
    lapse_id = policy.get("_lapse_invoice_id")
    if lapse_id is not None:
        inv = db.premium_invoices.get(lapse_id)
        if inv is not None:
            return inv
    for inv in db.premium_invoices.values():
        if inv["policy_id"] == policy["id"] and inv["status"] == "OVERDUE":
            return inv
    return None


def _has_zero_balance_invoice(policy_id, exclude=None):
    for inv in db.premium_invoices.values():
        if inv["id"] == exclude:
            continue
        if inv["policy_id"] == policy_id and inv["balance_due_cents"] == 0:
            return True
    return False


# ==========================================================================
# Claims
# ==========================================================================
@app.route("/policies/<rid>/claims", methods=["POST"])
def file_claim(rid):
    user_id, role = auth(["Underwriter", "Policyholder"])
    policy = store.get_or_404(db.policies, rid)
    ownership.enforce_read(role, user_id, "policy", policy)
    body = get_body()
    loss_type = as_enum(require(body, "loss_type"), "loss_type", constants.LOSS_TYPES)
    loss_dt = as_datetime(require(body, "loss_date"), "loss_date")
    disp_start = opt(body, "displacement_start", None)
    disp_end = opt(body, "displacement_end", None)
    disp_start_dt = as_datetime(disp_start, "displacement_start") if disp_start is not None else None
    disp_end_dt = as_datetime(disp_end, "displacement_end") if disp_end is not None else None

    # State (priority 9): filing requires owning policy ACTIVE.
    if policy["status"] != "ACTIVE":
        raise err("ERR_POLICY_NOT_ACTIVE", "Claim filing requires an ACTIVE policy")

    # loss_date within half-open term [effective_date, expiry_date) (priority 15).
    eff = parse_iso(policy["effective_date"])
    exp = parse_iso(policy["expiry_date"])
    if not (eff <= loss_dt < exp):
        raise err("ERR_LOSS_OUTSIDE_TERM", "loss_date falls outside the policy term")

    # LOSS_OF_USE displacement non-overlap with non-terminal LOU claims (priority 16).
    if loss_type == "LOSS_OF_USE" and disp_start_dt is not None and disp_end_dt is not None:
        for other in db.claims.values():
            if other["policy_id"] != policy["id"]:
                continue
            if other["loss_type"] != "LOSS_OF_USE":
                continue
            if other["status"] == "SETTLED":  # terminal claim does not block
                continue
            if other.get("displacement_start") is None or other.get("displacement_end") is None:
                continue
            o_start = parse_iso(other["displacement_start"])
            o_end = parse_iso(other["displacement_end"])
            # Closed intervals: collision if start <= o_end and o_start <= end
            # (shared boundary counts as collision).
            if disp_start_dt <= o_end and o_start <= disp_end_dt:
                raise err("ERR_DISPLACEMENT_OVERLAP",
                          "Displacement interval overlaps an existing LOSS_OF_USE claim")

    valuation_method = None
    if loss_type == "PERSONAL_PROPERTY":
        valuation_method = policy["pp_valuation_method"]

    rec = store.new_record({
        "policy_id": policy["id"],
        "loss_type": loss_type,
        "loss_date": _iso(loss_dt),
        "displacement_start": _iso(disp_start_dt) if disp_start_dt else None,
        "displacement_end": _iso(disp_end_dt) if disp_end_dt else None,
        "valuation_method": valuation_method,
        "covered_loss_cents": 0,
        "deductible_applied_cents": 0,
        "settlement_cents": 0,
        "denial_reason": None,
        "appeal_count": 0,
        "status": "FILED",
        "_pre_suspension_status": None,
        "_reviewer_user_id": None,
    })
    db.claims[rec["id"]] = rec
    return object_response(store.serialize(rec), 201)


@app.route("/claims/<rid>", methods=["GET"])
def get_claim(rid):
    user_id, role = auth(["Underwriter", "Policyholder", "ClaimsAdjuster"])
    rec = store.get_or_404(db.claims, rid)
    ownership.enforce_read(role, user_id, "claim", rec)
    return object_response(store.serialize(rec), 200)


@app.route("/claims", methods=["GET"])
def list_claims():
    user_id, role = auth(["Underwriter", "Policyholder", "ClaimsAdjuster"])
    records = list(db.claims.values())
    policy_id = request.args.get("policy_id")
    if policy_id is not None:
        records = [c for c in records if c["policy_id"] == policy_id]
    status = request.args.get("status")
    if status is not None:
        records = [c for c in records if c["status"] == status]
    records = ownership.scope_list(role, user_id, "claim", records)
    items, limit, offset, total = listing.paginate(records)
    return array_response(items, limit, offset, total)


@app.route("/claims/<rid>/items", methods=["POST"])
def add_claim_item(rid):
    user_id, role = auth(["Underwriter", "Policyholder"])
    claim = store.get_or_404(db.claims, rid)
    ownership.enforce_read(role, user_id, "claim", claim)
    body = get_body()
    coverage_line_id = as_str(require(body, "coverage_line_id"), "coverage_line_id")
    scheduled_item_id = opt(body, "scheduled_item_id", None)
    replacement_cost_cents = as_int(require(body, "replacement_cost_cents"), "replacement_cost_cents")
    if replacement_cost_cents <= 0:
        raise err("ERR_INVALID_REQUEST", "replacement_cost_cents must be > 0")
    age_months = opt(body, "age_months", 0)
    age_months = as_int(age_months, "age_months")
    useful_life_months = opt(body, "useful_life_months", 60)
    useful_life_months = as_int(useful_life_months, "useful_life_months")
    if useful_life_months <= 0:
        raise err("ERR_INVALID_REQUEST", "useful_life_months must be > 0")

    # FK existence (priority 5).
    cl = fk_or_404(db.coverage_lines, coverage_line_id, "coverage_line_id")
    if scheduled_item_id is not None:
        scheduled_item_id = as_str(scheduled_item_id, "scheduled_item_id")
        fk_or_404(db.scheduled_items, scheduled_item_id, "scheduled_item_id")

    # State (priority 7): items added only while FILED.
    if claim["status"] != "FILED":
        raise err("ERR_INVALID_STATE", "Claim items may be added only while FILED")

    # Referential (priority 17): coverage line type must match claim loss_type.
    if cl["coverage_type"] != claim["loss_type"]:
        raise err("ERR_COVERAGE_TYPE_MISMATCH",
                  "coverage_line coverage_type does not match claim loss_type")

    rec = store.new_record({
        "claim_id": claim["id"],
        "coverage_line_id": coverage_line_id,
        "scheduled_item_id": scheduled_item_id,
        "replacement_cost_cents": replacement_cost_cents,
        "age_months": age_months,
        "useful_life_months": useful_life_months,
        "covered_item_cents": 0,
    })
    db.claim_items[rec["id"]] = rec
    return object_response(store.serialize(rec), 201)


@app.route("/claim-items/<rid>", methods=["GET"])
def get_claim_item(rid):
    user_id, role = auth(["Underwriter", "Policyholder", "ClaimsAdjuster"])
    rec = store.get_or_404(db.claim_items, rid)
    ownership.enforce_read(role, user_id, "claim_item", rec)
    return object_response(store.serialize(rec), 200)


@app.route("/claim-items", methods=["GET"])
def list_claim_items():
    user_id, role = auth(["Underwriter", "Policyholder", "ClaimsAdjuster"])
    records = list(db.claim_items.values())
    claim_id = request.args.get("claim_id")
    if claim_id is not None:
        records = [c for c in records if c["claim_id"] == claim_id]
    coverage_line_id = request.args.get("coverage_line_id")
    if coverage_line_id is not None:
        records = [c for c in records if c["coverage_line_id"] == coverage_line_id]
    scheduled_item_id = request.args.get("scheduled_item_id")
    if scheduled_item_id is not None:
        records = [c for c in records if c.get("scheduled_item_id") == scheduled_item_id]
    records = ownership.scope_list(role, user_id, "claim_item", records)
    items, limit, offset, total = listing.paginate(records)
    return array_response(items, limit, offset, total)


# ---- Claim settlement helpers (PRD §3.8 claim_settlement) ----
def _claim_items_of(claim_id):
    items = [ci for ci in db.claim_items.values() if ci["claim_id"] == claim_id]
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))


def _referenced_lines_sorted(claim):
    """CoverageLines referenced by the claim's items, deduped, sorted by created_at ASC."""
    seen = []
    seen_ids = set()
    for ci in _claim_items_of(claim["id"]):
        lid = ci["coverage_line_id"]
        if lid in seen_ids:
            continue
        cl = db.coverage_lines.get(lid)
        if cl is None:
            continue
        seen_ids.add(lid)
        seen.append(cl)
    return sorted(seen, key=lambda r: (r["created_at"], r["_seq"]))


def _compute_settlement(claim):
    """Provisional/final settlement (PRD §3.8). Returns (covered_loss, deductible_applied,
    settlement) and stamps each item's covered_item_cents."""
    policy = db.policies[claim["policy_id"]]
    valuation_method = claim["valuation_method"]
    loss_type = claim["loss_type"]

    items = _claim_items_of(claim["id"])
    covered_loss = 0
    waived_portion = 0
    for ci in items:
        amount = calc.covered_item_cents(
            valuation_method, loss_type,
            ci["replacement_cost_cents"], ci["age_months"], ci["useful_life_months"],
        )
        if ci["covered_item_cents"] != amount:
            ci["covered_item_cents"] = amount
            store.touch(ci)
        covered_loss += amount
        sid = ci.get("scheduled_item_id")
        if sid is not None:
            si = db.scheduled_items.get(sid)
            if si is not None and si.get("deductible_waived"):
                waived_portion += amount

    dedctbl_eligible = covered_loss - waived_portion
    deductible_applied = min(policy["deductible_cents"], dedctbl_eligible)
    if deductible_applied < 0:
        deductible_applied = 0

    remaining_sum = sum(cl["remaining_limit_cents"] for cl in _referenced_lines_sorted(claim))
    capped_loss = min(covered_loss, remaining_sum)
    settlement = max(0, capped_loss - deductible_applied)
    return covered_loss, deductible_applied, settlement


def _set_settlement(claim, covered_loss, deductible_applied, settlement):
    claim["covered_loss_cents"] = covered_loss
    claim["deductible_applied_cents"] = deductible_applied
    claim["settlement_cents"] = settlement


def _ledger_apply(claim, sign):
    """Waterfall allocation across referenced lines in created_at ASC order (PRD §3.6).
    sign=+1 debit (approve), sign=-1 credit (reverse)."""
    settlement = claim["settlement_cents"]
    unallocated = settlement
    for cl in _referenced_lines_sorted(claim):
        if unallocated <= 0:
            share = 0
        else:
            share = min(unallocated, cl["remaining_limit_cents"]) if sign > 0 else min(unallocated, cl["settled_cents"])
        if sign > 0:
            cl["settled_cents"] += share
        else:
            cl["settled_cents"] -= share
        store.recompute_coverage_line(cl)
        cl["status"] = "EXHAUSTED" if cl["remaining_limit_cents"] == 0 else "OPEN"
        store.touch(cl)
        unallocated -= share


# ---- Claim state machine ----
@app.route("/claims/<rid>/start-review", methods=["POST"])
def start_review(rid):
    user_id, role = auth(["ClaimsAdjuster"])
    claim = store.get_or_404(db.claims, rid)
    # Cross-entity policy-state precondition takes precedence over the claim's
    # own state error for claim-path transitions (PRD §3.8): a claim suspended
    # by a lapse surfaces ERR_POLICY_NOT_ACTIVE, not ERR_INVALID_STATE.
    policy = db.policies[claim["policy_id"]]
    if policy["status"] != "ACTIVE":
        raise err("ERR_POLICY_NOT_ACTIVE", "Owning policy must be ACTIVE")
    if claim["status"] != "FILED":
        raise err("ERR_INVALID_STATE", "start-review is only defined from FILED")
    if not _claim_items_of(claim["id"]):
        raise err("ERR_CLAIM_EMPTY", "Claim has no items")
    covered, ded, settle = _compute_settlement(claim)
    _set_settlement(claim, covered, ded, settle)
    claim["status"] = "UNDER_REVIEW"
    claim["_reviewer_user_id"] = user_id
    store.touch(claim)
    return object_response(store.serialize(claim), 200)


@app.route("/claims/<rid>/approve", methods=["POST"])
def approve_claim(rid):
    user_id, role = auth(["ClaimsAdjuster"])
    claim = store.get_or_404(db.claims, rid)
    policy = db.policies[claim["policy_id"]]
    if policy["status"] != "ACTIVE":
        raise err("ERR_POLICY_NOT_ACTIVE", "Owning policy must be ACTIVE")
    if claim["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "approve is only defined from UNDER_REVIEW")
    # Limit check (priority 18, PRD §3.8): the claim's settlement must not exceed
    # the sum of remaining_limit_cents across the referenced coverage lines. The
    # settlement is the limit-capped figure from §3.8, so this rejects only when
    # the stored settlement was computed against a higher remaining limit that
    # has since eroded (e.g. another claim approved in between).
    covered, ded, settle = _compute_settlement(claim)
    remaining_sum = sum(cl["remaining_limit_cents"] for cl in _referenced_lines_sorted(claim))
    if settle > remaining_sum:
        raise err("ERR_LIMIT_EXCEEDED", "settlement exceeds referenced lines remaining limit")
    _set_settlement(claim, covered, ded, settle)
    _ledger_apply(claim, +1)
    claim["status"] = "APPROVED"
    store.touch(claim)
    return object_response(store.serialize(claim), 200)


@app.route("/claims/<rid>/deny", methods=["POST"])
def deny_claim(rid):
    user_id, role = auth(["ClaimsAdjuster"])
    claim = store.get_or_404(db.claims, rid)
    body = get_body()
    if claim["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "deny is only defined from UNDER_REVIEW")
    denial_reason = opt(body, "denial_reason", None)
    if denial_reason is None or not isinstance(denial_reason, str) or denial_reason == "":
        raise err("ERR_DENIAL_REASON_REQUIRED", "denial_reason is required")
    claim["denial_reason"] = denial_reason
    claim["settlement_cents"] = 0
    claim["status"] = "DENIED"
    store.touch(claim)
    return object_response(store.serialize(claim), 200)


@app.route("/claims/<rid>/appeal", methods=["POST"])
def appeal_claim(rid):
    user_id, role = auth(["ClaimsAdjuster"])
    claim = store.get_or_404(db.claims, rid)
    policy = db.policies[claim["policy_id"]]
    if policy["status"] != "ACTIVE":
        raise err("ERR_POLICY_NOT_ACTIVE", "Owning policy must be ACTIVE")
    if claim["status"] != "DENIED":
        raise err("ERR_INVALID_STATE", "appeal is only defined from DENIED")
    if claim["appeal_count"] >= constants.MAX_APPEALS:
        raise err("ERR_APPEAL_LIMIT_REACHED", "Appeal limit reached")
    claim["appeal_count"] += 1
    claim["denial_reason"] = None
    covered, ded, settle = _compute_settlement(claim)
    _set_settlement(claim, covered, ded, settle)
    claim["status"] = "UNDER_REVIEW"
    store.touch(claim)
    return object_response(store.serialize(claim), 200)


@app.route("/claims/<rid>/reverse-approval", methods=["POST"])
def reverse_approval(rid):
    user_id, role = auth(["ClaimsAdjuster"])
    claim = store.get_or_404(db.claims, rid)
    body = get_body()
    if claim["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "reverse-approval is only defined from APPROVED")
    denial_reason = opt(body, "denial_reason", None)
    if denial_reason is None or not isinstance(denial_reason, str) or denial_reason == "":
        raise err("ERR_DENIAL_REASON_REQUIRED", "denial_reason is required")
    # Credit back each referenced line by its prior share, then zero settlement.
    _ledger_apply(claim, -1)
    claim["denial_reason"] = denial_reason
    claim["settlement_cents"] = 0
    claim["status"] = "DENIED"
    store.touch(claim)
    return object_response(store.serialize(claim), 200)


@app.route("/claims/<rid>/pay", methods=["POST"])
def pay_claim(rid):
    user_id, role = auth(["ClaimsAdjuster"])
    claim = store.get_or_404(db.claims, rid)
    # Segregation of duties (priority 3): same X-User-ID that reviewed may not pay.
    if claim.get("_reviewer_user_id") is not None and claim["_reviewer_user_id"] == user_id:
        raise err("ERR_SEGREGATION_OF_DUTIES",
                  "The reviewer of a claim may not also pay it")
    # Cross-entity policy-state precondition precedes the claim's own state error
    # (PRD §3.8): a claim suspended by a lapse surfaces ERR_POLICY_NOT_ACTIVE.
    policy = db.policies[claim["policy_id"]]
    if policy["status"] != "ACTIVE":
        raise err("ERR_POLICY_NOT_ACTIVE", "Owning policy must be ACTIVE")
    if claim["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "pay is only defined from APPROVED")
    claim["status"] = "SETTLED"
    store.touch(claim)
    return object_response(store.serialize(claim), 200)


# ==========================================================================
# Billing: invoices, payments, voids
# ==========================================================================
@app.route("/premium-invoices/<rid>", methods=["GET"])
def get_invoice(rid):
    user_id, role = auth(["Underwriter", "Policyholder"])
    rec = store.get_or_404(db.premium_invoices, rid)
    ownership.enforce_read(role, user_id, "premium_invoice", rec)
    return object_response(store.serialize(rec), 200)


@app.route("/premium-invoices", methods=["GET"])
def list_invoices():
    user_id, role = auth(["Underwriter", "Policyholder"])
    records = list(db.premium_invoices.values())
    policy_id = request.args.get("policy_id")
    if policy_id is not None:
        records = [i for i in records if i["policy_id"] == policy_id]
    status = request.args.get("status")
    if status is not None:
        records = [i for i in records if i["status"] == status]
    records = ownership.scope_list(role, user_id, "premium_invoice", records)
    items, limit, offset, total = listing.paginate(records)
    return array_response(items, limit, offset, total)


@app.route("/premium-invoices/<rid>/payments", methods=["POST"])
def record_payment(rid):
    user_id, role = auth(["Policyholder", "Underwriter"])
    invoice = store.get_or_404(db.premium_invoices, rid)
    ownership.enforce_read(role, user_id, "premium_invoice", invoice)
    body = get_body()
    amount_cents = as_int(require(body, "amount_cents"), "amount_cents")
    if amount_cents <= 0:
        raise err("ERR_INVALID_REQUEST", "amount_cents must be > 0")
    method = opt(body, "method", "CARD")
    method = as_enum(method, "method", constants.PAYMENT_METHODS)

    policy = db.policies[invoice["policy_id"]]
    # Payment requires owning policy ACTIVE or LAPSED.
    if policy["status"] not in ("ACTIVE", "LAPSED"):
        raise err("ERR_POLICY_NOT_BILLABLE", "Owning policy is not billable")
    # OVERDUE-payment path requires policy LAPSED.
    if invoice["status"] == "OVERDUE" and policy["status"] != "LAPSED":
        raise err("ERR_POLICY_NOT_BILLABLE", "Overdue payment requires a LAPSED policy")

    payment = store.new_record({
        "invoice_id": invoice["id"],
        "amount_cents": amount_cents,
        "method": method,
        "status": "CLEARED",
    })
    db.payments[payment["id"]] = payment
    store.recompute_invoice(invoice)
    if invoice["balance_due_cents"] == 0:
        invoice["status"] = "PAID"
    store.touch(invoice)
    return object_response(store.serialize(payment), 201)


@app.route("/premium-invoices/<rid>/payments", methods=["GET"])
def list_invoice_payments(rid):
    user_id, role = auth(["Underwriter", "Policyholder"])
    invoice = store.get_or_404(db.premium_invoices, rid)
    ownership.enforce_read(role, user_id, "premium_invoice", invoice)
    records = [p for p in db.payments.values() if p["invoice_id"] == invoice["id"]]
    items, limit, offset, total = listing.paginate(records)
    return array_response(items, limit, offset, total)


@app.route("/payments", methods=["GET"])
def list_payments():
    user_id, role = auth(["Underwriter", "Policyholder"])
    records = list(db.payments.values())
    invoice_id = request.args.get("invoice_id")
    if invoice_id is not None:
        records = [p for p in records if p["invoice_id"] == invoice_id]
    records = ownership.scope_list(role, user_id, "payment", records)
    items, limit, offset, total = listing.paginate(records)
    return array_response(items, limit, offset, total)


@app.route("/payments/<rid>/void", methods=["POST"])
def void_payment(rid):
    user_id, role = auth(["Underwriter"])
    payment = store.get_or_404(db.payments, rid)
    # State (priority 7): only a CLEARED payment is voidable.
    if payment["status"] != "CLEARED":
        raise err("ERR_PAYMENT_NOT_VOIDABLE", "Only a CLEARED payment may be voided")
    payment["status"] = "VOIDED"
    store.touch(payment)
    invoice = db.premium_invoices[payment["invoice_id"]]
    store.recompute_invoice(invoice)
    if invoice["balance_due_cents"] > 0:
        invoice["status"] = "OPEN"
    store.touch(invoice)
    return object_response(store.serialize(payment), 200)


# ==========================================================================
# Test-driving clock hook
# ==========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    user_id, role = auth(["Underwriter"])
    body = get_body()
    to_iso = as_datetime(require(body, "to_iso8601"), "to_iso8601")
    db.set_current_utc(to_iso)
    return object_response({"current_utc": db.now_iso_clock()}, 200)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
