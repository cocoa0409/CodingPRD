"""Credit-Builder Loan & Secured-Card API (PRD task_0505).

Python + Flask, in-memory store. Boots empty on every invocation.
"""
import os

from flask import Flask, request

from db import store
from clock import fmt_iso, add_months, parse_iso
from common import stamp_create, touch, get_body, paginate, sort_by_created
from middleware import get_identity, require_role
from errors import ApiError, err
import errors as E
from response import ok_object, ok_array, ok_empty, error_body
import serialize as S
import services as svc
import calculations as calc
import validate as V
from constants import (
    SUPPORTED_STATES, STATE_APR_CAP_BPS, SUPPORTED_TERMS,
    MIN_PRINCIPAL_CENTS, MAX_PRINCIPAL_CENTS, MIN_CARD_DEPOSIT_CENTS,
    MAX_CARD_DEPOSIT_CENTS, GRADUATION_MIN_STREAK, QUOTE_TTL_HOURS,
    DAYS_PER_MONTH,
)
from datetime import timedelta

app = Flask(__name__)


# ===========================================================================
# Error handling -> standard envelope
# ===========================================================================
@app.errorhandler(ApiError)
def _handle_api_error(e):
    return error_body(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def _handle_404(e):
    return error_body(E.ERR_NOT_FOUND, "Resource not found", 404)


@app.errorhandler(405)
def _handle_405(e):
    return error_body(E.ERR_NOT_FOUND, "Method not allowed", 404)


@app.errorhandler(Exception)
def _handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_body(e.error_id, e.message, e.http_status)
    return error_body(E.ERR_INVALID_REQUEST, f"Unexpected error: {e}", 422)


# ===========================================================================
# Helpers
# ===========================================================================
def auth():
    return get_identity()


def list_response(items, serializer):
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return ok_array([serializer(e) for e in page], limit, offset, total)


# ===========================================================================
# Accounts
# ===========================================================================
@app.route("/accounts", methods=["POST"])
def create_account():
    user_id, role = auth()
    require_role(role, ["LoanServicer"])
    body = get_body()
    V.require_fields(body, ["email", "full_name", "state_code"])
    email = body["email"]
    full_name = body["full_name"]
    state_code = body["state_code"]
    if not isinstance(email, str) or not isinstance(full_name, str) or not isinstance(state_code, str):
        raise err(E.ERR_INVALID_REQUEST, "email/full_name/state_code must be strings")
    if state_code not in SUPPORTED_STATES:
        raise err(E.ERR_INVALID_REQUEST, "Unsupported state_code")
    # email unique among non-CLOSED accounts (PRD §3.1)
    for a in store.accounts.values():
        if a["status"] != "CLOSED" and a["email"] == email:
            raise err(E.ERR_INVALID_REQUEST, "Email already in use")
    acct = {
        "id": store.new_id(),
        "email": email,
        "full_name": full_name,
        "state_code": state_code,
        "kyc_status": "PENDING",
        "disclosure_status": "UNACKNOWLEDGED",
        "status": "OPEN",
        "wallet_cents": 0,
    }
    svc.recompute_posture(acct)
    stamp_create(acct)
    store.accounts[acct["id"]] = acct
    return ok_object(S.account(acct), 201)


@app.route("/accounts/<account_id>", methods=["GET"])
def get_account(account_id):
    user_id, role = auth()
    require_role(role, ["Borrower", "LoanServicer", "ComplianceOfficer", "PlatformAdmin"])
    acct = V.get_account_or_404(account_id)
    V.require_ownership(role, user_id, acct["id"])
    return ok_object(S.account(acct))


@app.route("/accounts", methods=["GET"])
def list_accounts():
    user_id, role = auth()
    require_role(role, ["LoanServicer", "ComplianceOfficer", "PlatformAdmin"])
    items = list(store.accounts.values())
    status = request.args.get("status")
    kyc = request.args.get("kyc_status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    if kyc is not None:
        items = [a for a in items if a["kyc_status"] == kyc]
    return list_response(items, S.account)


@app.route("/accounts/<account_id>/kyc-decision", methods=["POST"])
def kyc_decision(account_id):
    user_id, role = auth()
    require_role(role, ["LoanServicer"])
    acct = V.get_account_or_404(account_id)
    body = get_body()
    V.require_fields(body, ["decision"])
    decision = body["decision"]
    if decision not in ("VERIFIED", "REJECTED", "PENDING"):
        raise err(E.ERR_INVALID_REQUEST, "Unknown decision value")
    # VERIFIED only valid while status OPEN and kyc PENDING (PRD §3.1)
    if decision == "VERIFIED":
        if acct["status"] != "OPEN" or acct["kyc_status"] != "PENDING":
            raise err(E.ERR_INVALID_STATE, "KYC verification not valid from current state")
        acct["kyc_status"] = "VERIFIED"
    elif decision == "REJECTED":
        if acct["status"] != "OPEN" or acct["kyc_status"] != "PENDING":
            raise err(E.ERR_INVALID_STATE, "KYC decision not valid from current state")
        acct["kyc_status"] = "REJECTED"
    else:
        raise err(E.ERR_INVALID_STATE, "KYC decision not valid")
    svc.recompute_posture(acct)
    touch(acct)
    return ok_object(S.account(acct))


@app.route("/accounts/<account_id>/freeze", methods=["POST"])
def freeze_account(account_id):
    user_id, role = auth()
    require_role(role, ["ComplianceOfficer"])
    acct = V.get_account_or_404(account_id)
    get_body()  # optional reason ignored
    if acct["status"] != "OPEN":
        raise err(E.ERR_INVALID_STATE, "Freeze only valid from OPEN")
    acct["status"] = "FROZEN"
    svc.recompute_posture(acct)
    touch(acct)
    # cascade: ACTIVE cards -> SUSPENDED (PRD §3.2)
    for card in store.secured_cards.values():
        if card["account_id"] == account_id and card["status"] == "ACTIVE":
            card["status"] = "SUSPENDED"
            card["_suspended_by_freeze"] = True
            touch(card)
    return ok_object(S.account(acct))


@app.route("/accounts/<account_id>/unfreeze", methods=["POST"])
def unfreeze_account(account_id):
    user_id, role = auth()
    require_role(role, ["ComplianceOfficer"])
    acct = V.get_account_or_404(account_id)
    if acct["status"] != "FROZEN":
        raise err(E.ERR_INVALID_STATE, "Unfreeze only valid from FROZEN")
    acct["status"] = "OPEN"
    svc.recompute_posture(acct)
    touch(acct)
    # revert cascade: cards suspended purely by the freeze -> ACTIVE (PRD §3.2)
    for card in store.secured_cards.values():
        if (
            card["account_id"] == account_id
            and card["status"] == "SUSPENDED"
            and card.get("_suspended_by_freeze")
        ):
            card["status"] = "ACTIVE"
            card["_suspended_by_freeze"] = False
            touch(card)
    return ok_object(S.account(acct))


@app.route("/accounts/<account_id>/close", methods=["POST"])
def close_account(account_id):
    user_id, role = auth()
    require_role(role, ["ComplianceOfficer"])
    acct = V.get_account_or_404(account_id)
    if acct["status"] != "OPEN":
        raise err(E.ERR_INVALID_STATE, "Close only valid from OPEN")
    # no ACTIVE loan, no card in FUNDED/ACTIVE/SUSPENDED (PRD §3.2)
    for l in store.loans.values():
        if l["account_id"] == account_id and l["lifecycle_status"] == "ACTIVE":
            raise err(E.ERR_INVALID_STATE, "Account has an ACTIVE loan")
    for c in store.secured_cards.values():
        if c["account_id"] == account_id and c["status"] in ("FUNDED", "ACTIVE", "SUSPENDED"):
            raise err(E.ERR_INVALID_STATE, "Account has an active secured card")
    acct["status"] = "CLOSED"
    svc.recompute_posture(acct)
    touch(acct)
    return ok_object(S.account(acct))


# ===========================================================================
# Score dashboard
# ===========================================================================
@app.route("/accounts/<account_id>/score", methods=["GET"])
def get_score(account_id):
    user_id, role = auth()
    require_role(role, ["Borrower", "LoanServicer"])
    acct = V.get_account_or_404(account_id)
    V.require_ownership(role, user_id, acct["id"])
    projection = request.args.get("projection")
    if projection is not None and projection != "optimistic":
        raise err(E.ERR_INVALID_REQUEST, "Unknown projection value")
    now = store.now()
    score = svc.compute_account_score(account_id, now, projection=projection)
    # prior persisted snapshot delta for context
    prior = sorted(
        [s for s in store.score_snapshots.values() if s["account_id"] == account_id],
        key=lambda s: (s["created_at"], s.get("_seq", 0)),
    )
    prior_score = prior[-1]["simulated_score"] if prior else None
    delta = score - prior_score if prior_score is not None else 0
    # read-only: persist nothing (PRD §3.12)
    data = {
        "account_id": account_id,
        "cycle_label": f"{now.year:04d}-{now.month:02d}",
        "simulated_score": score,
        "score_delta": delta,
    }
    return ok_object(data)


@app.route("/accounts/<account_id>/score-snapshots", methods=["GET"])
def list_score_snapshots(account_id):
    user_id, role = auth()
    require_role(role, ["Borrower", "LoanServicer"])
    acct = V.get_account_or_404(account_id)
    V.require_ownership(role, user_id, acct["id"])
    items = [s for s in store.score_snapshots.values() if s["account_id"] == account_id]
    return list_response(items, S.snapshot)


# ===========================================================================
# Disclosures
# ===========================================================================
@app.route("/accounts/<account_id>/disclosures", methods=["POST"])
def issue_disclosure(account_id):
    user_id, role = auth()
    require_role(role, ["ComplianceOfficer"])
    acct = V.get_account_or_404(account_id)
    body = get_body()
    V.require_fields(body, ["product_kind", "apr_bps", "admin_fee_cents"])
    product_kind = body["product_kind"]
    if product_kind not in ("LOAN", "SECURED_CARD"):
        raise err(E.ERR_INVALID_REQUEST, "Unknown product_kind")
    apr_bps = V.require_int(body, "apr_bps")
    admin_fee_cents = V.require_int(body, "admin_fee_cents")
    if apr_bps < 0 or admin_fee_cents < 0:
        raise err(E.ERR_INVALID_REQUEST, "apr_bps and admin_fee_cents must be >= 0")
    # APR cap check (priority 9) (PRD §3.1)
    cap = STATE_APR_CAP_BPS[acct["state_code"]]
    if apr_bps > cap:
        raise err(E.ERR_APR_CAP_EXCEEDED, "Disclosed APR exceeds state cap")
    # supersede prior ISSUED for same (account, product_kind) (PRD §3.1)
    for d in store.disclosures.values():
        if (
            d["account_id"] == account_id
            and d["product_kind"] == product_kind
            and d["status"] == "ISSUED"
        ):
            d["status"] = "SUPERSEDED"
            touch(d)
    disc = {
        "id": store.new_id(),
        "account_id": account_id,
        "product_kind": product_kind,
        "apr_bps": apr_bps,
        "admin_fee_cents": admin_fee_cents,
        "status": "ISSUED",
        "signed_by_compliance_user_id": user_id,
        "acknowledged_at": None,
    }
    stamp_create(disc)
    store.disclosures[disc["id"]] = disc
    return ok_object(S.disclosure(disc), 201)


@app.route("/accounts/<account_id>/disclosures", methods=["GET"])
def list_disclosures(account_id):
    user_id, role = auth()
    require_role(role, ["Borrower", "LoanServicer", "ComplianceOfficer", "PlatformAdmin"])
    acct = V.get_account_or_404(account_id)
    V.require_ownership(role, user_id, acct["id"])
    items = [d for d in store.disclosures.values() if d["account_id"] == account_id]
    pk = request.args.get("product_kind")
    st = request.args.get("status")
    if pk is not None:
        items = [d for d in items if d["product_kind"] == pk]
    if st is not None:
        items = [d for d in items if d["status"] == st]
    return list_response(items, S.disclosure)


@app.route("/disclosures/<disclosure_id>", methods=["GET"])
def get_disclosure(disclosure_id):
    user_id, role = auth()
    require_role(role, ["Borrower", "LoanServicer", "ComplianceOfficer", "PlatformAdmin"])
    disc = V.get_disclosure_or_404(disclosure_id)
    V.require_ownership(role, user_id, disc["account_id"])
    return ok_object(S.disclosure(disc))


@app.route("/disclosures/<disclosure_id>/acknowledge", methods=["POST"])
def acknowledge_disclosure(disclosure_id):
    user_id, role = auth()
    require_role(role, ["Borrower"])
    disc = V.get_disclosure_or_404(disclosure_id)
    V.require_ownership(role, user_id, disc["account_id"])
    acct = store.accounts[disc["account_id"]]
    # posture gate (priority 5): acknowledgement barred when FROZEN/BLOCKED for
    # account-standing reasons (PRD §3.1). FROZEN/CLOSED block acknowledgement.
    if acct["status"] in ("FROZEN", "CLOSED"):
        raise err(E.ERR_ACCOUNT_NOT_ELIGIBLE, "Account not eligible for acknowledgement")
    if disc["status"] != "ISSUED":
        raise err(E.ERR_INVALID_STATE, "Only ISSUED disclosures can be acknowledged")
    disc["status"] = "ACKNOWLEDGED"
    disc["acknowledged_at"] = store.now_iso()
    touch(disc)
    acct["disclosure_status"] = "ACKNOWLEDGED"
    svc.recompute_posture(acct)
    touch(acct)
    return ok_object(S.disclosure(disc))


# ===========================================================================
# Loans
# ===========================================================================
def _validate_loan_create_body(body):
    V.require_fields(body, ["account_id", "disclosure_id", "principal_cents", "term_months"])


@app.route("/loans", methods=["POST"])
def create_loan():
    user_id, role = auth()
    require_role(role, ["Borrower", "LoanServicer"])
    body = get_body()
    _validate_loan_create_body(body)
    account_id = body["account_id"]
    disclosure_id = body["disclosure_id"]
    # existence (priority 4) left-to-right
    acct = V.get_account_or_404(account_id)
    # ownership (priority 3) for Borrower
    V.require_ownership(role, user_id, acct["id"])
    disc = V.get_disclosure_or_404(disclosure_id)
    # eligibility (priority 5)
    if acct["posture"] != "ELIGIBLE":
        raise err(E.ERR_ACCOUNT_NOT_ELIGIBLE, "Account posture is not ELIGIBLE")
    # disclosure ack + kind (priority 8)
    if disc["status"] != "ACKNOWLEDGED" or disc["product_kind"] != "LOAN":
        raise err(E.ERR_DISCLOSURE_NOT_ACKNOWLEDGED, "Pinned disclosure not acknowledged LOAN")
    # range checks (priority 15)
    principal = V.require_int(body, "principal_cents")
    term = V.require_int(body, "term_months")
    if principal < MIN_PRINCIPAL_CENTS or principal > MAX_PRINCIPAL_CENTS:
        raise err(E.ERR_INVALID_REQUEST, "principal_cents out of bounds")
    if term not in SUPPORTED_TERMS:
        raise err(E.ERR_INVALID_REQUEST, "term_months must be 12 or 24")
    loan = {
        "id": store.new_id(),
        "account_id": account_id,
        "disclosure_id": disclosure_id,
        "principal_cents": principal,
        "term_months": term,
        "apr_bps": None,
        "monthly_payment_cents": None,
        "funded_at": None,
        "principal_paid_cents": 0,
        "interest_paid_cents": 0,
        "outstanding_principal_cents": 0,
        "lifecycle_status": "PENDING",
        "delinquency_status": "CURRENT",
        "on_time_streak": 0,
        "missed_count": 0,
        "funded_by_servicer_user_id": None,
        # internal ledger
        "outstanding_late_fee_cents": 0,
        "total_late_fees_assessed": 0,
    }
    stamp_create(loan)
    store.loans[loan["id"]] = loan
    return ok_object(S.loan(loan), 201)


@app.route("/loans/<loan_id>", methods=["GET"])
def get_loan(loan_id):
    user_id, role = auth()
    require_role(role, ["Borrower", "LoanServicer", "ComplianceOfficer", "PlatformAdmin"])
    loan = V.get_loan_or_404(loan_id)
    V.require_ownership(role, user_id, loan["account_id"])
    return ok_object(S.loan(loan))


@app.route("/loans", methods=["GET"])
def list_loans():
    user_id, role = auth()
    require_role(role, ["Borrower", "LoanServicer", "ComplianceOfficer", "PlatformAdmin"])
    items = list(store.loans.values())
    if role == "Borrower":
        items = [l for l in items if l["account_id"] == user_id]
    for key in ("account_id", "disclosure_id", "lifecycle_status", "delinquency_status"):
        val = request.args.get(key)
        if val is not None:
            items = [l for l in items if l[key] == val]
    return list_response(items, S.loan)


@app.route("/loans/<loan_id>/fund", methods=["POST"])
def fund_loan(loan_id):
    user_id, role = auth()
    require_role(role, ["LoanServicer"])
    loan = V.get_loan_or_404(loan_id)
    acct = store.accounts[loan["account_id"]]
    # eligibility (priority 5)
    if acct["posture"] != "ELIGIBLE":
        raise err(E.ERR_ACCOUNT_NOT_ELIGIBLE, "Account posture is not ELIGIBLE")
    # state guard (priority 6)
    if loan["lifecycle_status"] != "PENDING":
        raise err(E.ERR_INVALID_STATE, "Loan is not PENDING")
    # disclosure check (priority 8)
    disc = store.disclosures.get(loan["disclosure_id"])
    if disc is None or disc["status"] != "ACKNOWLEDGED" or disc["product_kind"] != "LOAN":
        raise err(E.ERR_DISCLOSURE_NOT_ACKNOWLEDGED, "Pinned disclosure not acknowledged LOAN")
    now = store.now()
    loan["funded_at"] = fmt_iso(now)
    loan["apr_bps"] = disc["apr_bps"]
    loan["funded_by_servicer_user_id"] = user_id
    loan["outstanding_principal_cents"] = loan["principal_cents"]
    mp = calc.compute_amortized_payment(loan["principal_cents"], loan["apr_bps"], loan["term_months"])
    loan["monthly_payment_cents"] = mp
    rows = calc.build_amortization_split(
        loan["principal_cents"], loan["apr_bps"], loan["term_months"], mp
    )
    for r in rows:
        sched = {
            "id": store.new_id(),
            "loan_id": loan["id"],
            "period_index": r["period_index"],
            "due_date": fmt_iso(add_months(now, r["period_index"])),
            "amount_due_cents": r["amount_due_cents"],
            "principal_component_cents": r["principal_component_cents"],
            "interest_component_cents": r["interest_component_cents"],
            "amount_paid_cents": 0,
            "status": "SCHEDULED",
            "_interest_paid_cents": 0,
            "_principal_paid_cents": 0,
        }
        stamp_create(sched)
        store.schedules[sched["id"]] = sched
    loan["lifecycle_status"] = "ACTIVE"
    touch(loan)
    return ok_object(S.loan(loan))


@app.route("/loans/<loan_id>/cancel", methods=["POST"])
def cancel_loan(loan_id):
    user_id, role = auth()
    require_role(role, ["Borrower"])
    loan = V.get_loan_or_404(loan_id)
    V.require_ownership(role, user_id, loan["account_id"])
    if loan["lifecycle_status"] != "PENDING":
        raise err(E.ERR_INVALID_STATE, "Only PENDING loans can be cancelled")
    loan["lifecycle_status"] = "CANCELLED"
    touch(loan)
    return ok_object(S.loan(loan))


@app.route("/loans/<loan_id>/graduate", methods=["POST"])
def graduate_loan(loan_id):
    user_id, role = auth()
    require_role(role, ["LoanServicer"])
    loan = V.get_loan_or_404(loan_id)
    # state guard (priority 6): must be PAID_OFF
    if loan["lifecycle_status"] != "PAID_OFF":
        # not PAID_OFF -> graduation eligibility (priority 11)
        if loan["lifecycle_status"] in ("GRADUATED", "DEFAULTED", "CANCELLED"):
            raise err(E.ERR_INVALID_STATE, "Loan is in a terminal state")
        raise err(E.ERR_GRADUATION_NOT_ELIGIBLE, "Loan is not PAID_OFF")
    # graduation eligibility (priority 11)
    if loan["delinquency_status"] != "CURRENT" or loan["on_time_streak"] < GRADUATION_MIN_STREAK:
        raise err(E.ERR_GRADUATION_NOT_ELIGIBLE, "Graduation conditions not met")
    loan["lifecycle_status"] = "GRADUATED"
    touch(loan)
    # flag linked card with balance 0 (PRD §3.6)
    for card in store.secured_cards.values():
        if card["account_id"] == loan["account_id"] and card["balance_cents"] == 0:
            if not card["graduation_eligible"]:
                card["graduation_eligible"] = True
                touch(card)
    # emit final bureau report (PRD §3.6)
    svc.graduate_emit_final_report(loan)
    return ok_object(S.loan(loan))


@app.route("/loans/<loan_id>/schedule", methods=["GET"])
def list_schedule(loan_id):
    user_id, role = auth()
    require_role(role, ["Borrower", "LoanServicer", "ComplianceOfficer", "PlatformAdmin"])
    loan = V.get_loan_or_404(loan_id)
    V.require_ownership(role, user_id, loan["account_id"])
    items = [s for s in store.schedules.values() if s["loan_id"] == loan_id]
    st = request.args.get("status")
    if st is not None:
        items = [s for s in items if s["status"] == st]
    # schedule ordered by period_index (then created_at)
    items = sorted(items, key=lambda s: s["period_index"])
    page, limit, offset, total = paginate(items)
    return ok_array([S.schedule(e) for e in page], limit, offset, total)


@app.route("/loans/<loan_id>/payments", methods=["GET"])
def list_loan_payments(loan_id):
    user_id, role = auth()
    require_role(role, ["Borrower", "LoanServicer", "ComplianceOfficer", "PlatformAdmin"])
    loan = V.get_loan_or_404(loan_id)
    V.require_ownership(role, user_id, loan["account_id"])
    items = [p for p in store.payments.values() if p["loan_id"] == loan_id]
    src = request.args.get("source")
    st = request.args.get("status")
    if src is not None:
        items = [p for p in items if p["source"] == src]
    if st is not None:
        items = [p for p in items if p["status"] == st]
    return list_response(items, S.payment)


@app.route("/loans/<loan_id>/bureau-reports", methods=["GET"])
def list_loan_bureau_reports(loan_id):
    user_id, role = auth()
    require_role(role, ["Borrower", "LoanServicer", "ComplianceOfficer", "PlatformAdmin"])
    loan = V.get_loan_or_404(loan_id)
    V.require_ownership(role, user_id, loan["account_id"])
    items = [
        r for r in store.bureau_reports.values()
        if r["loan_id"] == loan_id and r["tradeline_kind"] == "LOAN"
    ]
    cl = request.args.get("cycle_label")
    if cl is not None:
        items = [r for r in items if r["cycle_label"] == cl]
    return list_response(items, S.bureau)


@app.route("/loans/<loan_id>/payoff-quote", methods=["POST"])
def create_payoff_quote(loan_id):
    user_id, role = auth()
    require_role(role, ["Borrower", "LoanServicer"])
    loan = V.get_loan_or_404(loan_id)
    V.require_ownership(role, user_id, loan["account_id"])
    now = store.now()
    days_since_last_due = _days_since_last_due(loan, now)
    res = calc.compute_payoff(loan, svc.loan_schedules(loan_id), days_since_last_due)
    quote = {
        "id": store.new_id(),
        "loan_id": loan_id,
        "quote_as_of": fmt_iso(now),
        "payoff_amount_cents": res["payoff_amount_cents"],
        "scheduled_remaining_cents": res["scheduled_remaining_cents"],
        "interest_savings_cents": res["interest_savings_cents"],
        "status": "ACTIVE",
    }
    stamp_create(quote)
    store.payoff_quotes[quote["id"]] = quote
    return ok_object(S.quote(quote), 201)


def _days_since_last_due(loan, now):
    """Days since the most recent due_date that is <= now; if none has passed yet,
    measure from funded_at (per-diem 0 at funding). (PRD §3.8)"""
    if not loan.get("funded_at"):
        return 0
    schedules = svc.loan_schedules(loan["id"])
    passed = [parse_iso(s["due_date"]) for s in schedules if parse_iso(s["due_date"]) <= now]
    if passed:
        last = max(passed)
    else:
        last = parse_iso(loan["funded_at"])
    days = (now - last).days
    return max(0, days)


@app.route("/loans/<loan_id>/payoff-quotes", methods=["GET"])
def list_payoff_quotes(loan_id):
    user_id, role = auth()
    require_role(role, ["Borrower", "LoanServicer"])
    loan = V.get_loan_or_404(loan_id)
    V.require_ownership(role, user_id, loan["account_id"])
    items = [q for q in store.payoff_quotes.values() if q["loan_id"] == loan_id]
    st = request.args.get("status")
    if st is not None:
        items = [q for q in items if q["status"] == st]
    return list_response(items, S.quote)


@app.route("/loans/<loan_id>/early-payoff", methods=["POST"])
def early_payoff(loan_id):
    user_id, role = auth()
    require_role(role, ["Borrower"])
    loan = V.get_loan_or_404(loan_id)
    V.require_ownership(role, user_id, loan["account_id"])
    body = get_body()
    V.require_fields(body, ["quote_id"])
    quote = V.get_quote_or_404(body["quote_id"])
    if quote["loan_id"] != loan_id:
        raise err(E.ERR_NOT_FOUND, "Quote does not belong to this loan")
    now = store.now()
    expiry = parse_iso(quote["quote_as_of"]) + timedelta(hours=QUOTE_TTL_HOURS)
    # quote freshness (priority 7)
    if quote["status"] != "ACTIVE" or now > expiry:
        if quote["status"] == "ACTIVE" and now > expiry:
            quote["status"] = "EXPIRED"
            touch(quote)
        raise err(E.ERR_QUOTE_EXPIRED, "Payoff quote is expired or not active")
    # state guard (priority 6)
    if loan["lifecycle_status"] != "ACTIVE":
        raise err(E.ERR_INVALID_STATE, "Loan is not ACTIVE")
    quote["status"] = "CONSUMED"
    touch(quote)
    payment = svc.apply_payment(loan, quote["payoff_amount_cents"], "MANUAL", now)
    touch(loan)
    store.payments[payment["id"]] = payment
    return ok_object(S.loan(loan))


# ===========================================================================
# Payments
# ===========================================================================
@app.route("/payments", methods=["POST"])
def post_payment():
    user_id, role = auth()
    require_role(role, ["Borrower", "LoanServicer"])
    body = get_body()
    # need the FK to do existence (priority 4) before remaining body checks
    V.require_fields(body, ["loan_id"])
    loan = V.get_loan_or_404(body["loan_id"])
    V.require_ownership(role, user_id, loan["account_id"])
    # remaining required fields (priority 17 body well-formedness)
    V.require_fields(body, ["amount_cents", "expected_loan_version"])
    # state guard (priority 6): loan must be ACTIVE to post payments
    if loan["lifecycle_status"] != "ACTIVE":
        raise err(E.ERR_INVALID_STATE, "Loan is not ACTIVE")
    # range checks (priority 15): amount >= 1
    amount = V.require_int(body, "amount_cents")
    if amount < 1:
        raise err(E.ERR_INVALID_REQUEST, "amount_cents must be >= 1")
    source = body.get("source", "MANUAL")
    if source not in ("MANUAL", "AUTOPAY"):
        raise err(E.ERR_INVALID_REQUEST, "Unknown source")
    # OCC (priority 18)
    expected = V.require_int(body, "expected_loan_version")
    if expected != loan["version"]:
        raise err(E.ERR_STALE_VERSION, "expected_loan_version does not match")
    now = store.now()
    payment = svc.apply_payment(loan, amount, source, now)
    touch(loan)  # OCC: posting bumps loan version
    store.payments[payment["id"]] = payment
    return ok_object(S.payment(payment), 201)


@app.route("/payments/<payment_id>", methods=["GET"])
def get_payment(payment_id):
    user_id, role = auth()
    require_role(role, ["Borrower", "LoanServicer", "ComplianceOfficer", "PlatformAdmin"])
    payment = V.get_payment_or_404(payment_id)
    loan = store.loans.get(payment["loan_id"])
    if loan is not None:
        V.require_ownership(role, user_id, loan["account_id"])
    return ok_object(S.payment(payment))


# ===========================================================================
# Secured cards
# ===========================================================================
@app.route("/secured-cards", methods=["POST"])
def create_card():
    user_id, role = auth()
    require_role(role, ["Borrower", "LoanServicer"])
    body = get_body()
    V.require_fields(body, ["account_id", "disclosure_id"])
    acct = V.get_account_or_404(body["account_id"])
    V.require_ownership(role, user_id, acct["id"])
    disc = V.get_disclosure_or_404(body["disclosure_id"])
    if acct["posture"] != "ELIGIBLE":
        raise err(E.ERR_ACCOUNT_NOT_ELIGIBLE, "Account posture is not ELIGIBLE")
    if disc["status"] != "ACKNOWLEDGED" or disc["product_kind"] != "SECURED_CARD":
        raise err(E.ERR_DISCLOSURE_NOT_ACKNOWLEDGED, "Pinned disclosure not acknowledged SECURED_CARD")
    card = {
        "id": store.new_id(),
        "account_id": acct["id"],
        "disclosure_id": disc["id"],
        "deposit_cents": 0,
        "credit_limit_cents": 0,
        "balance_cents": 0,
        "status": "PENDING",
        "graduation_eligible": False,
        "_suspended_by_freeze": False,
    }
    stamp_create(card)
    store.secured_cards[card["id"]] = card
    return ok_object(S.card(card), 201)


@app.route("/secured-cards/<card_id>", methods=["GET"])
def get_card(card_id):
    user_id, role = auth()
    require_role(role, ["Borrower", "LoanServicer", "ComplianceOfficer", "PlatformAdmin"])
    card = V.get_card_or_404(card_id)
    V.require_ownership(role, user_id, card["account_id"])
    return ok_object(S.card(card))


@app.route("/secured-cards", methods=["GET"])
def list_cards():
    user_id, role = auth()
    require_role(role, ["Borrower", "LoanServicer", "ComplianceOfficer", "PlatformAdmin"])
    items = list(store.secured_cards.values())
    if role == "Borrower":
        items = [c for c in items if c["account_id"] == user_id]
    for key in ("account_id", "disclosure_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [c for c in items if c[key] == val]
    return list_response(items, S.card)


@app.route("/secured-cards/<card_id>/deposits", methods=["POST"])
def post_deposit(card_id):
    user_id, role = auth()
    require_role(role, ["Borrower"])
    card = V.get_card_or_404(card_id)
    V.require_ownership(role, user_id, card["account_id"])
    acct = store.accounts[card["account_id"]]
    body = get_body()
    V.require_fields(body, ["amount_cents", "expected_card_version"])
    # eligibility (priority 5)
    if acct["posture"] != "ELIGIBLE":
        raise err(E.ERR_ACCOUNT_NOT_ELIGIBLE, "Account posture is not ELIGIBLE")
    # state guard (priority 6): deposits valid while PENDING (first) or FUNDED (more).
    if card["status"] not in ("PENDING", "FUNDED"):
        raise err(E.ERR_INVALID_STATE, "Card cannot accept deposits in current state")
    amount = V.require_int(body, "amount_cents")
    # deposit cap (priority 14)
    new_total = card["deposit_cents"] + amount
    if new_total > MAX_CARD_DEPOSIT_CENTS:
        raise err(E.ERR_DEPOSIT_CAP_EXCEEDED, "Total deposits would exceed cap")
    # range check (priority 15): each increment >= MIN_CARD_DEPOSIT_CENTS
    if amount < MIN_CARD_DEPOSIT_CENTS:
        raise err(E.ERR_INVALID_REQUEST, "Deposit increment below minimum")
    # OCC (priority 18)
    expected = V.require_int(body, "expected_card_version")
    if expected != card["version"]:
        raise err(E.ERR_STALE_VERSION, "expected_card_version does not match")
    deposit = {
        "id": store.new_id(),
        "secured_card_id": card_id,
        "amount_cents": amount,
        "status": "POSTED",
        "released_at": None,
    }
    stamp_create(deposit)
    store.card_deposits[deposit["id"]] = deposit
    # recompute deposit_cents/credit_limit (PRD §3.9)
    card["deposit_cents"] = sum(
        d["amount_cents"] for d in store.card_deposits.values()
        if d["secured_card_id"] == card_id and d["status"] == "POSTED"
    )
    card["credit_limit_cents"] = card["deposit_cents"]
    # first POSTED deposit (total >= min) moves PENDING -> FUNDED
    if card["status"] == "PENDING" and card["deposit_cents"] >= MIN_CARD_DEPOSIT_CENTS:
        card["status"] = "FUNDED"
    touch(card)  # OCC: deposit bumps card version
    return ok_object(S.deposit(deposit), 201)


@app.route("/secured-cards/<card_id>/deposits", methods=["GET"])
def list_deposits(card_id):
    user_id, role = auth()
    require_role(role, ["Borrower", "LoanServicer", "ComplianceOfficer", "PlatformAdmin"])
    card = V.get_card_or_404(card_id)
    V.require_ownership(role, user_id, card["account_id"])
    items = [d for d in store.card_deposits.values() if d["secured_card_id"] == card_id]
    st = request.args.get("status")
    if st is not None:
        items = [d for d in items if d["status"] == st]
    return list_response(items, S.deposit)


@app.route("/secured-cards/<card_id>/activate", methods=["POST"])
def activate_card(card_id):
    user_id, role = auth()
    require_role(role, ["Borrower"])
    card = V.get_card_or_404(card_id)
    V.require_ownership(role, user_id, card["account_id"])
    acct = store.accounts[card["account_id"]]
    if acct["posture"] != "ELIGIBLE":
        raise err(E.ERR_ACCOUNT_NOT_ELIGIBLE, "Account posture is not ELIGIBLE")
    if card["status"] != "FUNDED":
        raise err(E.ERR_INVALID_STATE, "Card is not FUNDED")
    card["status"] = "ACTIVE"
    touch(card)
    return ok_object(S.card(card))


@app.route("/secured-cards/<card_id>/charges", methods=["POST"])
def charge_card(card_id):
    user_id, role = auth()
    require_role(role, ["Borrower", "LoanServicer"])
    card = V.get_card_or_404(card_id)
    V.require_ownership(role, user_id, card["account_id"])
    body = get_body()
    V.require_fields(body, ["amount_cents"])
    amount = V.require_int(body, "amount_cents")
    if amount < 1:
        raise err(E.ERR_INVALID_REQUEST, "amount_cents must be >= 1")
    if card["status"] != "ACTIVE":
        raise err(E.ERR_INVALID_STATE, "Card is not ACTIVE")
    # credit limit ceiling (priority 13)
    if card["balance_cents"] + amount > card["credit_limit_cents"]:
        raise err(E.ERR_CREDIT_LIMIT_EXCEEDED, "Charge exceeds credit limit")
    card["balance_cents"] += amount
    touch(card)
    return ok_object(S.card(card))


@app.route("/secured-cards/<card_id>/suspend", methods=["POST"])
def suspend_card(card_id):
    user_id, role = auth()
    require_role(role, ["LoanServicer"])
    card = V.get_card_or_404(card_id)
    get_body()
    if card["status"] != "ACTIVE":
        raise err(E.ERR_INVALID_STATE, "Card is not ACTIVE")
    card["status"] = "SUSPENDED"
    card["_suspended_by_freeze"] = False
    touch(card)
    return ok_object(S.card(card))


@app.route("/secured-cards/<card_id>/resume", methods=["POST"])
def resume_card(card_id):
    user_id, role = auth()
    require_role(role, ["LoanServicer"])
    card = V.get_card_or_404(card_id)
    acct = store.accounts[card["account_id"]]
    if card["status"] != "SUSPENDED":
        raise err(E.ERR_INVALID_STATE, "Card is not SUSPENDED")
    if acct["posture"] != "ELIGIBLE":
        raise err(E.ERR_ACCOUNT_NOT_ELIGIBLE, "Account posture is not ELIGIBLE")
    card["status"] = "ACTIVE"
    card["_suspended_by_freeze"] = False
    touch(card)
    return ok_object(S.card(card))


@app.route("/secured-cards/<card_id>/release-deposit", methods=["POST"])
def release_deposit(card_id):
    user_id, role = auth()
    require_role(role, ["ComplianceOfficer"])
    card = V.get_card_or_404(card_id)
    # state guard (priority 6): ACTIVE, or SUSPENDED with zero balance
    if card["status"] not in ("ACTIVE", "SUSPENDED"):
        raise err(E.ERR_INVALID_STATE, "Card cannot release deposit from current state")
    # SoD (priority 10) precedes releasability (priority 12)
    link = svc.linked_loan_for_card(card)
    if link is not None and link.get("funded_by_servicer_user_id") == user_id:
        raise err(E.ERR_SOD_CONFLICT, "Releasing officer funded the linked loan")
    # releasability (priority 12)
    if not card["graduation_eligible"] or card["balance_cents"] != 0:
        raise err(E.ERR_DEPOSIT_NOT_RELEASABLE, "Deposit not releasable")
    # SUSPENDED requires zero balance per machine (already checked balance==0 above)
    # cascade: POSTED deposits -> RELEASED; credit wallet; zero line; CLOSE card.
    now_iso = store.now_iso()
    acct = store.accounts[card["account_id"]]
    released_total = card["deposit_cents"]
    for d in store.card_deposits.values():
        if d["secured_card_id"] == card_id and d["status"] == "POSTED":
            d["status"] = "RELEASED"
            d["released_at"] = now_iso
            touch(d)
    acct["wallet_cents"] += released_total
    touch(acct)
    card["credit_limit_cents"] = 0
    card["deposit_cents"] = 0
    card["status"] = "CLOSED"
    touch(card)
    return ok_object(S.card(card))


@app.route("/secured-cards/<card_id>/bureau-reports", methods=["GET"])
def list_card_bureau_reports(card_id):
    user_id, role = auth()
    require_role(role, ["Borrower", "LoanServicer", "ComplianceOfficer", "PlatformAdmin"])
    card = V.get_card_or_404(card_id)
    V.require_ownership(role, user_id, card["account_id"])
    link = svc.linked_loan_for_card(card)
    items = []
    if link is not None:
        items = [
            r for r in store.bureau_reports.values()
            if r["loan_id"] == link["id"] and r["tradeline_kind"] == "SECURED_CARD"
        ]
    cl = request.args.get("cycle_label")
    if cl is not None:
        items = [r for r in items if r["cycle_label"] == cl]
    return list_response(items, S.bureau)


# ===========================================================================
# Autopay enrollments
# ===========================================================================
@app.route("/autopay-enrollments", methods=["POST"])
def create_autopay():
    user_id, role = auth()
    require_role(role, ["Borrower", "LoanServicer"])
    body = get_body()
    V.require_fields(body, ["loan_id", "day_of_month"])
    loan = V.get_loan_or_404(body["loan_id"])
    V.require_ownership(role, user_id, loan["account_id"])
    day = V.require_int(body, "day_of_month")
    if day < 1 or day > 28:
        raise err(E.ERR_INVALID_REQUEST, "day_of_month must be in [1,28]")
    funding_wallet = body.get("funding_wallet", False)
    if not isinstance(funding_wallet, bool):
        raise err(E.ERR_INVALID_REQUEST, "funding_wallet must be a boolean")
    enr = {
        "id": store.new_id(),
        "loan_id": loan["id"],
        "day_of_month": day,
        "funding_wallet": funding_wallet,
        "status": "ACTIVE",
    }
    stamp_create(enr)
    store.autopay_enrollments[enr["id"]] = enr
    return ok_object(S.autopay(enr), 201)


@app.route("/autopay-enrollments", methods=["GET"])
def list_autopay():
    user_id, role = auth()
    require_role(role, ["Borrower", "LoanServicer", "ComplianceOfficer", "PlatformAdmin"])
    items = list(store.autopay_enrollments.values())
    if role == "Borrower":
        items = [
            e for e in items
            if store.loans.get(e["loan_id"], {}).get("account_id") == user_id
        ]
    lid = request.args.get("loan_id")
    st = request.args.get("status")
    if lid is not None:
        items = [e for e in items if e["loan_id"] == lid]
    if st is not None:
        items = [e for e in items if e["status"] == st]
    return list_response(items, S.autopay)


@app.route("/autopay-enrollments/<enr_id>", methods=["GET"])
def get_autopay(enr_id):
    user_id, role = auth()
    require_role(role, ["Borrower", "LoanServicer", "ComplianceOfficer", "PlatformAdmin"])
    enr = V.get_enrollment_or_404(enr_id)
    loan = store.loans.get(enr["loan_id"])
    if loan is not None:
        V.require_ownership(role, user_id, loan["account_id"])
    return ok_object(S.autopay(enr))


@app.route("/autopay-enrollments/<enr_id>", methods=["PATCH"])
def patch_autopay(enr_id):
    user_id, role = auth()
    require_role(role, ["Borrower", "LoanServicer"])
    enr = V.get_enrollment_or_404(enr_id)
    loan = store.loans.get(enr["loan_id"])
    if loan is not None:
        V.require_ownership(role, user_id, loan["account_id"])
    body = get_body()
    V.require_fields(body, ["status"])
    new_status = body["status"]
    if new_status not in ("ACTIVE", "PAUSED", "CANCELLED"):
        raise err(E.ERR_INVALID_REQUEST, "Unknown status")
    enr["status"] = new_status
    touch(enr)
    return ok_object(S.autopay(enr))


# ===========================================================================
# Clock + batch sweeps (PlatformAdmin)
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    user_id, role = auth()
    require_role(role, ["PlatformAdmin"])
    body = get_body()
    V.require_fields(body, ["to_iso8601"])
    try:
        store.clock.set(body["to_iso8601"])
    except (ValueError, TypeError):
        raise err(E.ERR_INVALID_REQUEST, "Invalid to_iso8601")
    return ok_empty()


@app.route("/_clock/run-autopay", methods=["POST"])
def run_autopay_route():
    user_id, role = auth()
    require_role(role, ["PlatformAdmin"])
    svc.run_autopay()
    return ok_empty()


@app.route("/_clock/run-delinquency-sweep", methods=["POST"])
def run_delinquency_route():
    user_id, role = auth()
    require_role(role, ["PlatformAdmin"])
    svc.run_delinquency_sweep()
    return ok_empty()


@app.route("/_clock/run-bureau-sweep", methods=["POST"])
def run_bureau_route():
    user_id, role = auth()
    require_role(role, ["PlatformAdmin"])
    svc.run_bureau_sweep()
    return ok_empty()


@app.route("/", methods=["GET"])
def health():
    return ok_empty()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
