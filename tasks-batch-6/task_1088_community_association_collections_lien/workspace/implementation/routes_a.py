"""Routes: clock, associations, accounts, assessments, payments, notices, plans."""
from datetime import timedelta

from flask import Blueprint

import store as S
import services as SV
import lookups as L
from web import (
    ApiError, authenticate, require_role, body, parse_pagination, paginate,
    success, list_response, require_str, require_int, require_datetime,
    require_enum, require_present,
)

bp_a = Blueprint("bp_a", __name__)

ALL_ROLES = {"CollectionsAgent", "ComplianceOfficer", "TrustAccountant", "AssociationManager"}
ACCOUNT_STATUSES = {"CURRENT", "DELINQUENT", "PAYMENT_PLAN", "LIEN", "FORECLOSURE",
                    "BANKRUPTCY", "CHARGED_OFF", "CLOSED"}
NOTICE_STATUSES = {"DRAFT", "SENT", "DISPUTED", "EXPIRED", "VOID"}
PLAN_STATUSES = {"DRAFT", "ACTIVE", "BREACHED", "SUSPENDED", "COMPLETED", "CANCELLED"}


def _child_list(all_items, role, uid, account_id, status, extra_filter=None):
    items = list(all_items)
    if account_id is not None:
        L.scope_child_by_account(role, uid, account_id)
        items = [x for x in items if x["account_id"] == account_id]
    if status is not None:
        items = [x for x in items if x["status"] == status]
    if extra_filter is not None:
        items = [x for x in items if extra_filter(x)]
    if role == "AssociationManager":
        items = [x for x in items if S.association_of_account(x["account_id"]) == uid]
    return items


# ==========================================================================
# logical clock
# ==========================================================================
@bp_a.route("/collections/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _uid, role = authenticate()
    require_role(role, {"CollectionsAgent", "ComplianceOfficer", "TrustAccountant"})
    data = body()
    to_iso = require_datetime(data, "to_iso8601")
    S.clock.set(to_iso)
    return success({}, 200)


# ==========================================================================
# associations
# ==========================================================================
@bp_a.route("/collections/associations", methods=["POST"])
def create_association():
    _uid, role = authenticate()
    require_role(role, {"CollectionsAgent"})
    data = body()
    name = require_str(data, "name")
    state_code = require_str(data, "state_code")
    a = {
        "name": name,
        "state_code": state_code,
        "interest_rate_annual_pct": _num(data, "interest_rate_annual_pct", 12.0),
        "late_fee_cents": _int_default(data, "late_fee_cents", 2500),
        "management_fee_pct": _num(data, "management_fee_pct", 20.0),
        "status": "ACTIVE",
    }
    S.stamp_new(a)
    S.associations[a["id"]] = a
    return success(S.ser_association(a), 201)


def _num(data, field, default):
    if data.get(field) is None:
        return default
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_VALIDATION", 422, f"Field {field} must be a number")
    return v


def _int_default(data, field, default):
    if data.get(field) is None:
        return default
    return require_int(data, field)


@bp_a.route("/collections/associations/<association_id>", methods=["GET"])
def get_association_ep(association_id):
    _uid, role = authenticate()
    require_role(role, ALL_ROLES)
    a = L.get_association(association_id)
    uid = _uid
    L.scope_association(role, uid, a["id"])
    return success(S.ser_association(a), 200)


@bp_a.route("/collections/associations/<association_id>/aging-report", methods=["GET"])
def aging_report_ep(association_id):
    uid, role = authenticate()
    require_role(role, ALL_ROLES)
    a = L.get_association(association_id)
    L.scope_association(role, uid, a["id"])
    return success(SV.association_aging_report(a), 200)


# ==========================================================================
# accounts
# ==========================================================================
@bp_a.route("/collections/accounts", methods=["POST"])
def create_account():
    _uid, role = authenticate()
    require_role(role, {"CollectionsAgent"})
    data = body()
    association_id = require_str(data, "association_id")
    L.get_association(association_id)
    unit_number = require_str(data, "unit_number")
    owner_name = require_str(data, "owner_name")
    acc = {
        "association_id": association_id,
        "unit_number": unit_number,
        "owner_name": owner_name,
        "status": "CURRENT",
    }
    S.stamp_new(acc)
    S.accounts[acc["id"]] = acc
    return success(S.ser_account(acc), 201)


@bp_a.route("/collections/accounts/<account_id>", methods=["GET"])
def get_account_ep(account_id):
    uid, role = authenticate()
    require_role(role, ALL_ROLES)
    acc = L.get_account(account_id)
    L.scope_account(role, uid, acc)
    return success(S.ser_account(acc), 200)


@bp_a.route("/collections/accounts", methods=["GET"])
def list_accounts():
    uid, role = authenticate()
    require_role(role, ALL_ROLES)
    from flask import request
    association_id = request.args.get("association_id")
    status = request.args.get("status")
    limit, offset = parse_pagination()
    items = list(S.accounts.values())
    if role == "AssociationManager":
        if association_id is not None and association_id != uid:
            raise ApiError("ERR_UNAUTHORIZED", 403, "AssociationManager scope violation")
        items = [x for x in items if x["association_id"] == uid]
    elif association_id is not None:
        items = [x for x in items if x["association_id"] == association_id]
    if status is not None:
        items = [x for x in items if x["status"] == status]
    page, total = paginate(items, limit, offset)
    return list_response([S.ser_account(x) for x in page], total, limit, offset)


@bp_a.route("/collections/accounts/<account_id>/transition", methods=["POST"])
def account_transition(account_id):
    uid, role = authenticate()
    require_role(role, {"CollectionsAgent", "ComplianceOfficer"})
    acc = L.get_account(account_id)
    data = body()
    to_status = require_enum(data, "to_status", ACCOUNT_STATUSES)

    if to_status == "DELINQUENT":
        require_role(role, {"CollectionsAgent"})
        if acc["status"] != "CURRENT":
            raise ApiError("ERR_INVALID_STATE", 409, "Account not CURRENT")
        if S.account_total_balance(acc["id"]) <= 0:
            raise ApiError("ERR_INVALID_AMOUNT", 422, "No outstanding balance")
        now = S.now_dt()
        overdue = any(
            a["status"] in ("OPEN", "PARTIAL") and S.parse_iso(a["due_date"]) <= now
            for a in S.account_assessments(acc["id"])
        )
        if not overdue:
            raise ApiError("ERR_NOT_DELINQUENT", 409, "No overdue assessment")
        SV.set_account_status(acc, "DELINQUENT")
    elif to_status == "CLOSED":
        if acc["status"] == "CURRENT":
            require_role(role, {"CollectionsAgent"})
            if S.account_total_balance(acc["id"]) != 0:
                raise ApiError("ERR_INVALID_STATE", 409, "Balance not zero")
            if any(l["status"] in ("RECORDED", "STAYED", "FORECLOSING")
                   for l in S.account_liens(acc["id"])):
                raise ApiError("ERR_INVALID_STATE", 409, "Active lien present")
            if any(r["status"] not in ("SALE_COMPLETED", "WITHDRAWN")
                   for r in S.account_referrals(acc["id"])):
                raise ApiError("ERR_INVALID_STATE", 409, "Non-terminal referral present")
            SV.set_account_status(acc, "CLOSED")
        elif acc["status"] == "CHARGED_OFF":
            require_role(role, {"ComplianceOfficer"})
            if any(b["status"] == "FILED" for b in S.account_bankruptcies(acc["id"])):
                raise ApiError("ERR_INVALID_STATE", 409, "Bankruptcy still FILED")
            SV.set_account_status(acc, "CLOSED")
        else:
            raise ApiError("ERR_INVALID_STATE", 409, "Cannot close from this state")
    else:
        raise ApiError("ERR_INVALID_STATE", 409, "Status is system-managed")
    return success(S.ser_account(acc), 200)


@bp_a.route("/collections/accounts/<account_id>/payoff-quote", methods=["GET"])
def payoff_quote(account_id):
    uid, role = authenticate()
    require_role(role, {"CollectionsAgent", "ComplianceOfficer", "AssociationManager"})
    acc = L.get_account(account_id)
    L.scope_account(role, uid, acc)
    from flask import request
    variant = request.args.get("variant")
    if variant is None:
        variant = "PROVISIONAL"
    if variant not in ("PROVISIONAL", "BINDING"):
        raise ApiError("ERR_INVALID_ENUM", 422, "Invalid variant")
    assoc = S.associations[acc["association_id"]]
    return success(SV.compute_payoff(acc, assoc, variant), 200)


# ==========================================================================
# assessments
# ==========================================================================
@bp_a.route("/collections/assessments", methods=["POST"])
def create_assessment():
    _uid, role = authenticate()
    require_role(role, {"CollectionsAgent"})
    data = body()
    account_id = require_str(data, "account_id")
    L.get_account(account_id)
    amt = data.get("amount_cents")
    if isinstance(amt, int) and not isinstance(amt, bool) and amt <= 0:
        raise ApiError("ERR_INVALID_AMOUNT", 422, "amount_cents must be > 0")
    if "charge_type" in data and data.get("charge_type") not in S.CHARGE_TYPES:
        raise ApiError("ERR_INVALID_ENUM", 422, "Invalid charge_type")
    charge_type = require_enum(data, "charge_type", set(S.CHARGE_TYPES))
    amount_cents = require_int(data, "amount_cents")
    if amount_cents <= 0:
        raise ApiError("ERR_INVALID_AMOUNT", 422, "amount_cents must be > 0")
    due_date = require_datetime(data, "due_date")
    a = {
        "account_id": account_id,
        "charge_type": charge_type,
        "amount_cents": amount_cents,
        "due_date": due_date,
        "balance_cents": amount_cents,
        "status": "OPEN",
    }
    S.stamp_new(a)
    S.assessments[a["id"]] = a
    return success(S.ser_assessment(a), 201)


@bp_a.route("/collections/assessments/<assessment_id>", methods=["GET"])
def get_assessment_ep(assessment_id):
    uid, role = authenticate()
    require_role(role, ALL_ROLES)
    a = L.get_assessment(assessment_id)
    L.scope_child_by_account(role, uid, a["account_id"])
    return success(S.ser_assessment(a), 200)


@bp_a.route("/collections/assessments", methods=["GET"])
def list_assessments():
    uid, role = authenticate()
    require_role(role, ALL_ROLES)
    from flask import request
    account_id = request.args.get("account_id")
    status = request.args.get("status")
    limit, offset = parse_pagination()
    items = _child_list(S.assessments.values(), role, uid, account_id, status)
    page, total = paginate(items, limit, offset)
    return list_response([S.ser_assessment(x) for x in page], total, limit, offset)


@bp_a.route("/collections/assessments/<assessment_id>/waive", methods=["POST"])
def waive_assessment(assessment_id):
    _uid, role = authenticate()
    require_role(role, {"CollectionsAgent"})
    a = L.get_assessment(assessment_id)
    if a["status"] not in ("OPEN", "PARTIAL"):
        raise ApiError("ERR_INVALID_STATE", 409, "Assessment not OPEN/PARTIAL")
    a["balance_cents"] = 0
    a["status"] = "WAIVED"
    S.touch(a)
    return success(S.ser_assessment(a), 200)


# ==========================================================================
# payments
# ==========================================================================
@bp_a.route("/collections/payments", methods=["POST"])
def create_payment():
    _uid, role = authenticate()
    require_role(role, {"CollectionsAgent"})
    data = body()
    account_id = require_str(data, "account_id")
    acc = L.get_account(account_id)
    amt = data.get("amount_cents")
    if isinstance(amt, int) and not isinstance(amt, bool) and amt <= 0:
        raise ApiError("ERR_INVALID_AMOUNT", 422, "amount_cents must be > 0")
    amount_cents = require_int(data, "amount_cents")
    if amount_cents <= 0:
        raise ApiError("ERR_INVALID_AMOUNT", 422, "amount_cents must be > 0")
    received_date = require_datetime(data, "received_date")
    p = {
        "account_id": account_id,
        "amount_cents": amount_cents,
        "received_date": received_date,
        "allocations": [],
        "unapplied_cents": 0,
        "status": "POSTED",
        "reversal_reason": None,
        "_caused_current": False,
    }
    S.stamp_new(p)
    S.payments[p["id"]] = p
    SV.run_allocation(p)
    S.touch(acc)  # payment posted advances the account
    S.touch(S.associations[acc["association_id"]])  # trust position changed
    SV.on_balance_maybe_current(acc, p)
    return success(S.ser_payment(p), 201)


@bp_a.route("/collections/payments/<payment_id>", methods=["GET"])
def get_payment_ep(payment_id):
    uid, role = authenticate()
    require_role(role, ALL_ROLES)
    p = L.get_payment(payment_id)
    L.scope_child_by_account(role, uid, p["account_id"])
    return success(S.ser_payment(p), 200)


@bp_a.route("/collections/payments", methods=["GET"])
def list_payments():
    uid, role = authenticate()
    require_role(role, ALL_ROLES)
    from flask import request
    account_id = request.args.get("account_id")
    status = request.args.get("status")
    limit, offset = parse_pagination()
    items = _child_list(S.payments.values(), role, uid, account_id, status)
    page, total = paginate(items, limit, offset)
    return list_response([S.ser_payment(x) for x in page], total, limit, offset)


@bp_a.route("/collections/payments/<payment_id>/reverse", methods=["POST"])
def reverse_payment(payment_id):
    _uid, role = authenticate()
    require_role(role, {"CollectionsAgent"})
    p = L.get_payment(payment_id)
    if p["status"] != "POSTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Payment not POSTED")
    data = body()
    if "reversal_reason" in data and data.get("reversal_reason") not in S.REVERSAL_REASONS:
        raise ApiError("ERR_INVALID_ENUM", 422, "Invalid reversal_reason")
    reason = require_enum(data, "reversal_reason", set(S.REVERSAL_REASONS))
    acc = S.accounts[p["account_id"]]
    p["status"] = "REVERSED"
    p["reversal_reason"] = reason
    S.touch(p)
    SV.unapply_allocations(p)
    S.touch(acc)
    S.touch(S.associations[acc["association_id"]])  # trust position changed
    if S.account_total_balance(acc["id"]) > 0 and acc["status"] == "CURRENT" and p.get("_caused_current"):
        SV.set_account_status(acc, "DELINQUENT")
    return success(S.ser_payment(p), 200)


# ==========================================================================
# notices
# ==========================================================================
@bp_a.route("/collections/notices", methods=["POST"])
def create_notice():
    _uid, role = authenticate()
    require_role(role, {"CollectionsAgent"})
    data = body()
    account_id = require_str(data, "account_id")
    L.get_account(account_id)
    notice_type = require_enum(data, "notice_type", set(S.NOTICE_TYPES))
    n = {
        "account_id": account_id,
        "notice_type": notice_type,
        "status": "DRAFT",
        "sent_date": None,
        "dispute_date": None,
    }
    S.stamp_new(n)
    S.notices[n["id"]] = n
    return success(S.ser_notice(n), 201)


@bp_a.route("/collections/notices/<notice_id>", methods=["GET"])
def get_notice_ep(notice_id):
    uid, role = authenticate()
    require_role(role, ALL_ROLES)
    n = L.get_notice(notice_id)
    L.scope_child_by_account(role, uid, n["account_id"])
    return success(S.ser_notice(n), 200)


@bp_a.route("/collections/notices", methods=["GET"])
def list_notices():
    uid, role = authenticate()
    require_role(role, ALL_ROLES)
    from flask import request
    account_id = request.args.get("account_id")
    status = request.args.get("status")
    notice_type = request.args.get("notice_type")
    limit, offset = parse_pagination()
    extra = (lambda x: x["notice_type"] == notice_type) if notice_type is not None else None
    items = _child_list(S.notices.values(), role, uid, account_id, status, extra)
    page, total = paginate(items, limit, offset)
    return list_response([S.ser_notice(x) for x in page], total, limit, offset)


@bp_a.route("/collections/notices/<notice_id>/transition", methods=["POST"])
def notice_transition(notice_id):
    _uid, role = authenticate()
    require_role(role, {"CollectionsAgent"})
    n = L.get_notice(notice_id)
    data = body()
    to_status = require_enum(data, "to_status", NOTICE_STATUSES)
    acc = S.accounts[n["account_id"]]
    now = S.now_dt()

    if to_status == "SENT":
        if n["status"] not in ("DRAFT", "DISPUTED"):
            raise ApiError("ERR_INVALID_STATE", 409, "Cannot send from this state")
        if acc["status"] == "BANKRUPTCY":
            raise ApiError("ERR_AUTOMATIC_STAY", 403, "Account under automatic stay")
        if n["status"] == "DRAFT":
            # cooldown: prior SENT/DISPUTED same-type notice window contains now
            for other in S.account_notices(acc["id"]):
                if other["id"] == n["id"]:
                    continue
                if other["notice_type"] != n["notice_type"]:
                    continue
                if other["status"] in ("SENT", "DISPUTED") and other["sent_date"]:
                    sd = S.parse_iso(other["sent_date"])
                    if sd <= now < sd + timedelta(days=S.NOTICE_COOLDOWN_DAYS):
                        raise ApiError("ERR_NOTICE_COOLDOWN", 409, "Notice cooldown active")
            n["status"] = "SENT"
            n["sent_date"] = S.now_date()
        else:  # DISPUTED -> SENT (re-send / verification)
            n["status"] = "SENT"
            n["sent_date"] = S.now_date()
            n["dispute_date"] = None
    elif to_status == "DISPUTED":
        if n["status"] != "SENT":
            raise ApiError("ERR_INVALID_STATE", 409, "Cannot dispute from this state")
        sd = S.parse_iso(n["sent_date"])
        if (now - sd) >= timedelta(days=S.VALIDATION_PERIOD_DAYS):
            raise ApiError("ERR_INVALID_STATE", 409, "Dispute outside validation window")
        n["status"] = "DISPUTED"
        n["dispute_date"] = S.now_date()
    elif to_status == "EXPIRED":
        if n["status"] != "SENT":
            raise ApiError("ERR_INVALID_STATE", 409, "Cannot expire from this state")
        sd = S.parse_iso(n["sent_date"])
        if (now - sd) < timedelta(days=S.VALIDATION_PERIOD_DAYS):
            raise ApiError("ERR_INVALID_STATE", 409, "Validation period not elapsed")
        n["status"] = "EXPIRED"
    elif to_status == "VOID":
        if n["status"] not in ("DRAFT", "SENT"):
            raise ApiError("ERR_INVALID_STATE", 409, "Cannot void from this state")
        n["status"] = "VOID"
    else:
        raise ApiError("ERR_INVALID_STATE", 409, "Unsupported transition")
    S.touch(n)
    return success(S.ser_notice(n), 200)


# ==========================================================================
# payment plans
# ==========================================================================
@bp_a.route("/collections/payment-plans", methods=["POST"])
def create_plan():
    _uid, role = authenticate()
    require_role(role, {"CollectionsAgent"})
    data = body()
    account_id = require_str(data, "account_id")
    acc = L.get_account(account_id)
    # OCC
    eav = data.get("expected_account_version")
    if eav is not None:
        if isinstance(eav, bool) or not isinstance(eav, int):
            raise ApiError("ERR_VALIDATION", 422, "expected_account_version must be an integer")
        if eav != acc["version"]:
            raise ApiError("ERR_STALE_VERSION", 412, "Stale account version")
    # presence/typing
    total_amount_cents = require_int(data, "total_amount_cents")
    installment_cents = require_int(data, "installment_cents")
    num_installments = require_int(data, "num_installments")
    first_due_date = require_datetime(data, "first_due_date")
    require_present(data, ["expected_account_version"])
    # fiscal
    if num_installments < 1:
        raise ApiError("ERR_INVALID_AMOUNT", 422, "num_installments must be >= 1")
    # overlap
    final_due_date = SV.compute_final_due_date(first_due_date, num_installments)
    new_start = S.parse_iso(first_due_date)
    new_end = S.parse_iso(final_due_date)
    for other in S.account_plans(account_id):
        if other["status"] in ("COMPLETED", "CANCELLED"):
            continue
        os_ = S.parse_iso(other["first_due_date"])
        oe = S.parse_iso(other["final_due_date"])
        # Two-sided strict overlap of closed intervals: reject when they share
        # any interior region; touching only at a shared endpoint (adjacency) is
        # allowed. Handles zero-length (num_installments==1) point intervals.
        if new_start < oe and os_ < new_end:
            raise ApiError("ERR_PLAN_OVERLAP", 409, "Plan interval overlaps a live plan")
    if total_amount_cents <= 0:
        raise ApiError("ERR_INVALID_AMOUNT", 422, "total_amount_cents must be > 0")
    p = {
        "account_id": account_id,
        "total_amount_cents": total_amount_cents,
        "installment_cents": installment_cents,
        "num_installments": num_installments,
        "first_due_date": first_due_date,
        "final_due_date": final_due_date,
        "status": "DRAFT",
        "_activated_dt": None,
    }
    S.stamp_new(p)
    S.plans[p["id"]] = p
    S.touch(acc)  # OCC-guarded create advances account version by 1
    return success(S.ser_plan(p), 201)


@bp_a.route("/collections/payment-plans/<plan_id>", methods=["GET"])
def get_plan_ep(plan_id):
    uid, role = authenticate()
    require_role(role, ALL_ROLES)
    p = L.get_plan(plan_id)
    L.scope_child_by_account(role, uid, p["account_id"])
    return success(S.ser_plan(p), 200)


@bp_a.route("/collections/payment-plans", methods=["GET"])
def list_plans():
    uid, role = authenticate()
    require_role(role, ALL_ROLES)
    from flask import request
    account_id = request.args.get("account_id")
    status = request.args.get("status")
    limit, offset = parse_pagination()
    items = _child_list(S.plans.values(), role, uid, account_id, status)
    page, total = paginate(items, limit, offset)
    return list_response([S.ser_plan(x) for x in page], total, limit, offset)


@bp_a.route("/collections/payment-plans/<plan_id>/transition", methods=["POST"])
def plan_transition(plan_id):
    _uid, role = authenticate()
    require_role(role, {"CollectionsAgent"})
    p = L.get_plan(plan_id)
    data = body()
    to_status = require_enum(data, "to_status", PLAN_STATUSES)
    acc = S.accounts[p["account_id"]]

    if to_status == "ACTIVE":
        if p["status"] not in ("DRAFT", "BREACHED"):
            raise ApiError("ERR_INVALID_STATE", 409, "Cannot activate from this state")
        if acc["status"] not in ("DELINQUENT", "PAYMENT_PLAN"):
            raise ApiError("ERR_INVALID_STATE", 409, "Account not eligible for plan")
        if p["status"] == "BREACHED" and S.plan_missed_count(p) >= S.PLAN_MISSED_BREACH_THRESHOLD:
            raise ApiError("ERR_INVALID_STATE", 409, "Plan not caught up")
        p["status"] = "ACTIVE"
        if p["_activated_dt"] is None:
            p["_activated_dt"] = S.now_dt()
        if acc["status"] == "DELINQUENT":
            SV.set_account_status(acc, "PAYMENT_PLAN")
    elif to_status == "BREACHED":
        if p["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", 409, "Only ACTIVE plans can breach")
        if S.plan_missed_count(p) < S.PLAN_MISSED_BREACH_THRESHOLD:
            raise ApiError("ERR_PLAN_NOT_BREACHABLE", 409, "Below breach threshold")
        p["status"] = "BREACHED"
        if acc["status"] == "PAYMENT_PLAN":
            SV.set_account_status(acc, "DELINQUENT")
    elif to_status == "COMPLETED":
        if p["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", 409, "Only ACTIVE plans can complete")
        if S.plan_amount_paid(p) < p["total_amount_cents"]:
            raise ApiError("ERR_INVALID_STATE", 409, "Plan not fully paid")
        p["status"] = "COMPLETED"
    elif to_status == "CANCELLED":
        if p["status"] == "DRAFT":
            p["status"] = "CANCELLED"
        elif p["status"] == "ACTIVE":
            p["status"] = "CANCELLED"
            if acc["status"] == "PAYMENT_PLAN":
                SV.set_account_status(acc, "DELINQUENT")
        else:
            raise ApiError("ERR_INVALID_STATE", 409, "Cannot cancel from this state")
    else:
        raise ApiError("ERR_INVALID_STATE", 409, "Status is system-managed")
    S.touch(p)
    return success(S.ser_plan(p), 200)
