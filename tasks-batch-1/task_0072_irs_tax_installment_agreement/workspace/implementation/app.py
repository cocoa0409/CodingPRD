import os

from flask import Flask, request

import calc
import domain
from auth import authorize
from common import (
    iso, make_record, touch, parse_dt,
    require_str, require_int, require_enum, optional_bool,
)
from db import store, clock
from errors import (
    ApiError, err,
    ERR_RESOURCE_NOT_FOUND, ERR_FK_MISMATCH, ERR_DUPLICATE_TIN,
    ERR_INVALID_STATE, ERR_SEGREGATION_OF_DUTIES, ERR_CONFLICTING_RESOLUTION,
    ERR_PAYOFF_SHAPE_INVALID, ERR_SHORT_TERM_TOO_LONG, ERR_AGREEMENT_WINDOW_OVERLAP,
    ERR_OVERLAPPING_SUSPENSION, ERR_OFFER_BELOW_RCP, ERR_LIEN_RELEASE_BLOCKED,
    ERR_NOTHING_TO_SWEEP, ERR_STALE_ACCOUNT_VERSION, ERR_INVALID_REQUEST,
)
from response import success, array, error

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

@app.errorhandler(ApiError)
def handle_api_error(e):
    return error(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error("ERR_RESOURCE_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return error("ERR_RESOURCE_NOT_FOUND", "Method not allowed", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error(e.error_id, e.message, e.http_status)
    return error("ERR_INVALID_REQUEST", str(e), 400)


def get_body():
    if request.content_length and not (request.is_json or request.data):
        raise err(ERR_INVALID_REQUEST, "Body must be JSON")
    try:
        body = request.get_json(silent=True)
    except Exception:
        raise err(ERR_INVALID_REQUEST, "Malformed JSON body")
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise err(ERR_INVALID_REQUEST, "Body must be a JSON object")
    return body


# ---------------------------------------------------------------------------
# Pagination helpers
# ---------------------------------------------------------------------------

def parse_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except ValueError:
            raise err(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except ValueError:
            raise err(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise err(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def paginate(items, serializer):
    limit, offset = parse_pagination()
    items = sorted(items, key=lambda r: (r["_created_dt"], r["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return array([serializer(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Lookups with not-found
# ---------------------------------------------------------------------------

def get_account(account_id):
    a = store.tax_accounts.get(account_id)
    if a is None:
        raise err(ERR_RESOURCE_NOT_FOUND, "TaxAccount not found")
    return a


def get_period(period_id):
    p = store.tax_periods.get(period_id)
    if p is None:
        raise err(ERR_RESOURCE_NOT_FOUND, "TaxPeriod not found")
    return p


# ===========================================================================
# TaxAccount
# ===========================================================================

@app.route("/collections/tax-accounts", methods=["POST"])
def create_account():
    authorize({"RevenueOfficer"})
    body = get_body()
    taxpayer_name = require_str(body, "taxpayer_name")
    tin = require_str(body, "tin")
    filing_status = require_enum(body, "filing_status", {"INDIVIDUAL", "BUSINESS"})
    mdi = require_int(body, "monthly_disposable_income_cents", minimum=0)
    if not (isinstance(tin, str) and len(tin) == 9 and tin.isdigit()):
        raise err(ERR_INVALID_REQUEST, "tin must be 9 digits")
    # uniqueness
    for a in store.tax_accounts.values():
        if a["tin"] == tin:
            raise err(ERR_DUPLICATE_TIN, "tin already in use")
    rec = make_record(versioned=True)
    rec["taxpayer_name"] = taxpayer_name
    rec["tin"] = tin
    rec["filing_status"] = filing_status
    rec["monthly_disposable_income_cents"] = mdi
    rec["collection_status"] = "ACTIVE_COLLECTION"
    rec["total_balance_cents"] = 0
    rec["csed_protection_count"] = 0
    store.tax_accounts[rec["id"]] = rec
    return success(domain.ser_account(rec), status=201)


@app.route("/collections/tax-accounts/<account_id>", methods=["GET"])
def fetch_account(account_id):
    authorize({"RevenueOfficer", "CaseReviewer"})
    a = get_account(account_id)
    return success(domain.ser_account(a))


@app.route("/collections/tax-accounts", methods=["GET"])
def list_accounts():
    authorize({"RevenueOfficer", "CaseReviewer"})
    items = list(store.tax_accounts.values())
    cs = request.args.get("collection_status")
    if cs is not None:
        items = [a for a in items if a["collection_status"] == cs]
    return paginate(items, domain.ser_account)


@app.route("/collections/tax-accounts/<account_id>/recompute", methods=["POST"])
def recompute_account(account_id):
    authorize({"RevenueOfficer"})
    a = get_account(account_id)
    for p in domain.periods_of(account_id):
        if p["period_status"] in ("ASSESSED", "IN_COLLECTION"):
            domain.recompute_period_financials(p, account_id)
            touch(p)
    domain.reconcile_account(a)
    domain.append_event(account_id, "RECOMPUTE")
    return success(domain.ser_account(a))


@app.route("/collections/tax-accounts/<account_id>/sweep-expired-csed", methods=["POST"])
def sweep_expired_csed(account_id):
    authorize({"RevenueOfficer"})
    a = get_account(account_id)
    now = clock.now()
    swept = []
    for p in domain.periods_of(account_id):
        if (p["period_status"] == "IN_COLLECTION"
                and p["csed_date"] is not None and p["csed_date"] <= now
                and p["balance_due_cents"] > 0):
            swept.append(p)
    if not swept:
        raise err(ERR_NOTHING_TO_SWEEP, "No expired period with positive balance")
    for p in swept:
        p["period_status"] = "WRITTEN_OFF"
        p["balance_due_cents"] = 0
        touch(p)
    domain.reconcile_account(a)
    return success(domain.ser_account(a))


# ===========================================================================
# TaxPeriod
# ===========================================================================

@app.route("/collections/tax-periods", methods=["POST"])
def create_period():
    authorize({"RevenueOfficer"})
    body = get_body()
    account_id = require_str(body, "tax_account_id")
    tax_year = require_int(body, "tax_year", minimum=2000, maximum=2099)
    assessed = require_int(body, "assessed_tax_cents", exclusive_min=0)
    assessment_date = parse_dt(require_str(body, "assessment_date"), "assessment_date")
    a = get_account(account_id)
    rec = make_record(versioned=True)
    rec["tax_account_id"] = account_id
    rec["tax_year"] = tax_year
    rec["assessed_tax_cents"] = assessed
    rec["assessment_date"] = assessment_date
    rec["penalty_accrued_cents"] = 0
    rec["interest_accrued_cents"] = 0
    rec["paid_to_principal_cents"] = 0
    rec["balance_due_cents"] = assessed
    rec["period_status"] = "ASSESSED"
    rec["csed_date"] = None
    store.tax_periods[rec["id"]] = rec
    domain.recompute_csed_date(rec)
    domain.reconcile_account(a)
    return success(domain.ser_period(rec), status=201)


@app.route("/collections/tax-periods/<period_id>", methods=["GET"])
def fetch_period(period_id):
    authorize({"RevenueOfficer", "CaseReviewer"})
    p = get_period(period_id)
    return success(domain.ser_period(p))


@app.route("/collections/tax-periods", methods=["GET"])
def list_periods():
    authorize({"RevenueOfficer", "CaseReviewer"})
    items = list(store.tax_periods.values())
    acct = request.args.get("tax_account_id")
    if acct is not None:
        items = [p for p in items if p["tax_account_id"] == acct]
    return paginate(items, domain.ser_period)


# ===========================================================================
# CsedSuspension
# ===========================================================================

@app.route("/collections/csed-suspensions", methods=["POST"])
def create_suspension():
    authorize({"RevenueOfficer"})
    body = get_body()
    period_id = require_str(body, "tax_period_id")
    reason = require_enum(body, "reason",
                          {"AGREEMENT_PENDING", "OIC_EVALUATION", "MANUAL"})
    start_at = parse_dt(require_str(body, "start_at"), "start_at")
    p = get_period(period_id)
    # overlap with any open interval on the same period
    for s in domain.open_suspensions_of_period(period_id):
        raise err(ERR_OVERLAPPING_SUSPENSION, "Overlaps an open suspension interval")
    a = store.tax_accounts.get(p["tax_account_id"])
    rec = make_record(versioned=True)
    rec["tax_period_id"] = period_id
    rec["reason"] = reason
    rec["start_at"] = start_at
    rec["end_at"] = None
    rec["days_counted"] = 0
    store.csed_suspensions[rec["id"]] = rec
    if a is not None:
        a["csed_protection_count"] += 1
        touch(a)
    return success(domain.ser_suspension(rec), status=201)


@app.route("/collections/csed-suspensions/<susp_id>/close", methods=["POST"])
def close_suspension_endpoint(susp_id):
    authorize({"RevenueOfficer"})
    body = get_body()
    s = store.csed_suspensions.get(susp_id)
    if s is None:
        raise err(ERR_RESOURCE_NOT_FOUND, "CsedSuspension not found")
    if s["end_at"] is not None:
        raise err(ERR_INVALID_STATE, "Suspension is already closed")
    end_at = parse_dt(require_str(body, "end_at"), "end_at")
    if end_at < s["start_at"]:
        raise err(ERR_INVALID_REQUEST, "end_at must be >= start_at")
    p = store.tax_periods.get(s["tax_period_id"])
    a = store.tax_accounts.get(p["tax_account_id"]) if p else None
    s["end_at"] = end_at
    days = (end_at - s["start_at"]).days
    s["days_counted"] = days
    touch(s)
    if a is not None:
        a["csed_protection_count"] = max(0, a["csed_protection_count"] - 1)
        domain.append_event(a["id"], "CSED_SUSPEND_END",
                            period_id=s["tax_period_id"], suspension_days=days)
        if p is not None:
            domain.recompute_csed_date(p)
            touch(p)
        touch(a)
    return success(domain.ser_suspension(s))


@app.route("/collections/csed-suspensions/<susp_id>", methods=["GET"])
def fetch_suspension(susp_id):
    authorize({"RevenueOfficer", "CaseReviewer"})
    s = store.csed_suspensions.get(susp_id)
    if s is None:
        raise err(ERR_RESOURCE_NOT_FOUND, "CsedSuspension not found")
    return success(domain.ser_suspension(s))


@app.route("/collections/csed-suspensions", methods=["GET"])
def list_suspensions():
    authorize({"RevenueOfficer", "CaseReviewer"})
    items = list(store.csed_suspensions.values())
    period_id = request.args.get("tax_period_id")
    if period_id is not None:
        items = [s for s in items if s["tax_period_id"] == period_id]
    return paginate(items, domain.ser_suspension)


# ===========================================================================
# InstallmentAgreement
# ===========================================================================

@app.route("/collections/installment-agreements", methods=["POST"])
def create_agreement():
    authorize({"RevenueOfficer"})
    body = get_body()
    account_id = require_str(body, "tax_account_id")
    agreement_type = require_enum(body, "agreement_type",
                                  {"SHORT_TERM", "LONG_TERM", "PPIA"})
    payment_method = require_enum(body, "payment_method",
                                  {"DIRECT_DEBIT", "MANUAL"})
    monthly = require_int(body, "monthly_payment_cents", exclusive_min=0)
    term_months = require_int(body, "term_months", minimum=1)
    active_from = parse_dt(require_str(body, "active_from"), "active_from")
    active_to = parse_dt(require_str(body, "active_to"), "active_to")
    low_income = optional_bool(body, "low_income_flag", False)
    get_account(account_id)
    rec = make_record(versioned=True)
    rec["tax_account_id"] = account_id
    rec["agreement_type"] = agreement_type
    rec["payment_method"] = payment_method
    rec["monthly_payment_cents"] = monthly
    rec["term_months"] = term_months
    rec["active_from"] = active_from
    rec["active_to"] = active_to
    rec["low_income_flag"] = low_income
    rec["setup_fee_cents"] = 0
    rec["status"] = "PROPOSED"
    rec["approved_by_user_id"] = None
    rec["missed_debit_count"] = 0
    store.installment_agreements[rec["id"]] = rec
    return success(domain.ser_agreement(rec), status=201)


@app.route("/collections/installment-agreements/<agr_id>", methods=["GET"])
def fetch_agreement(agr_id):
    authorize({"RevenueOfficer", "CaseReviewer"})
    g = store.installment_agreements.get(agr_id)
    if g is None:
        raise err(ERR_RESOURCE_NOT_FOUND, "InstallmentAgreement not found")
    return success(domain.ser_agreement(g))


@app.route("/collections/installment-agreements", methods=["GET"])
def list_agreements():
    authorize({"RevenueOfficer", "CaseReviewer"})
    items = list(store.installment_agreements.values())
    acct = request.args.get("tax_account_id")
    if acct is not None:
        items = [g for g in items if g["tax_account_id"] == acct]
    return paginate(items, domain.ser_agreement)


def _windows_within_buffer(a_from, a_to, b_from, b_to, buffer_days):
    """True if the two closed intervals are NOT separated by >= buffer_days
    (i.e. they touch, overlap, or fall within the buffer gap)."""
    # gap is positive when disjoint; require gap >= buffer on whichever side disjoint.
    if a_to < b_from:
        gap = (b_from - a_to).days
        return gap < buffer_days
    if b_to < a_from:
        gap = (a_from - b_to).days
        return gap < buffer_days
    # overlapping or touching
    return True


@app.route("/collections/installment-agreements/<agr_id>/approve", methods=["POST"])
def approve_agreement(agr_id):
    authorize({"RevenueOfficer"})
    body = get_body()
    user_id = request.headers.get("X-User-ID")
    g = store.installment_agreements.get(agr_id)
    if g is None:
        raise err(ERR_RESOURCE_NOT_FOUND, "InstallmentAgreement not found")
    account = get_account(g["tax_account_id"])
    expected_version = require_int(body, "expected_tax_account_version", minimum=0)

    # 1. state
    if g["status"] != "PROPOSED":
        raise err(ERR_INVALID_STATE, "Agreement is not PROPOSED")
    # 2. conflicting resolution
    for other in domain.agreements_of(account["id"]):
        if other["id"] != g["id"] and other["status"] in ("APPROVED", "REINSTATED"):
            raise err(ERR_CONFLICTING_RESOLUTION, "Another active agreement exists")
    for o in domain.offers_of(account["id"]):
        if o["status"] in ("SUBMITTED", "EVALUATING", "ACCEPTED"):
            raise err(ERR_CONFLICTING_RESOLUTION, "An open or accepted offer exists")
    # 3. window overlap (buffer)
    for other in domain.agreements_of(account["id"]):
        if other["id"] == g["id"]:
            continue
        if other["status"] in ("APPROVED", "REINSTATED", "DEFAULTED"):
            if _windows_within_buffer(g["active_from"], g["active_to"],
                                      other["active_from"], other["active_to"],
                                      calc.AGREEMENT_BUFFER_DAYS):
                raise err(ERR_AGREEMENT_WINDOW_OVERLAP,
                          "Agreement window within buffer of another")
    # 4. payoff shape
    product = g["monthly_payment_cents"] * g["term_months"]
    total = account["total_balance_cents"]
    if g["agreement_type"] in ("SHORT_TERM", "LONG_TERM"):
        if product < total:
            raise err(ERR_PAYOFF_SHAPE_INVALID, "Schedule does not fully retire balance")
    else:  # PPIA
        if product >= total:
            raise err(ERR_PAYOFF_SHAPE_INVALID, "PPIA must be partial by design")
    # 5. short-term length
    if g["agreement_type"] == "SHORT_TERM" and g["term_months"] > calc.SHORT_TERM_MAX_MONTHS:
        raise err(ERR_SHORT_TERM_TOO_LONG, "SHORT_TERM term_months > 6")
    # 6. OCC
    if expected_version != account["version"]:
        raise err(ERR_STALE_ACCOUNT_VERSION, "Stale account version")

    # ---- cascade ----
    g["setup_fee_cents"] = calc.setup_fee_cents(
        g["low_income_flag"], g["agreement_type"], g["payment_method"])
    g["approved_by_user_id"] = user_id
    g["status"] = "APPROVED"
    # transition ASSESSED -> IN_COLLECTION and open suspensions
    for p in domain.periods_of(account["id"]):
        if p["period_status"] == "ASSESSED":
            p["period_status"] = "IN_COLLECTION"
            domain.open_suspension(p, "AGREEMENT_PENDING", account)
            touch(p)
    # DDIA penalty re-accrual going forward
    if g["payment_method"] == "DIRECT_DEBIT":
        for p in domain.periods_of(account["id"]):
            if p["period_status"] in ("ASSESSED", "IN_COLLECTION"):
                domain.recompute_period_financials(p, account["id"])
                touch(p)
    touch(g)
    domain.reconcile_account(account)
    return success(domain.ser_agreement(g))


@app.route("/collections/installment-agreements/<agr_id>/reject", methods=["POST"])
def reject_agreement(agr_id):
    authorize({"RevenueOfficer"})
    g = store.installment_agreements.get(agr_id)
    if g is None:
        raise err(ERR_RESOURCE_NOT_FOUND, "InstallmentAgreement not found")
    if g["status"] != "PROPOSED":
        raise err(ERR_INVALID_STATE, "Agreement is not PROPOSED")
    account = store.tax_accounts.get(g["tax_account_id"])
    g["status"] = "REJECTED"
    touch(g)
    if account is not None:
        domain.reconcile_account(account)
    return success(domain.ser_agreement(g))


@app.route("/collections/installment-agreements/<agr_id>/record-missed-debit",
           methods=["POST"])
def record_missed_debit(agr_id):
    authorize({"RevenueOfficer"})
    g = store.installment_agreements.get(agr_id)
    if g is None:
        raise err(ERR_RESOURCE_NOT_FOUND, "InstallmentAgreement not found")
    if g["status"] not in ("APPROVED", "REINSTATED"):
        raise err(ERR_INVALID_STATE, "Agreement is not active")
    if g["payment_method"] != "DIRECT_DEBIT":
        raise err(ERR_INVALID_STATE, "Agreement is not DIRECT_DEBIT")
    account = store.tax_accounts.get(g["tax_account_id"])
    g["missed_debit_count"] += 1
    domain.append_event(account["id"], "MISSED_DEBIT")
    if g["missed_debit_count"] >= calc.MISSED_DEBIT_DEFAULT_THRESHOLD:
        # default cascade
        g["status"] = "DEFAULTED"
        domain.close_all_open_suspensions(account)
        # standard-rate re-accrual going forward
        for p in domain.periods_of(account["id"]):
            if p["period_status"] in ("ASSESSED", "IN_COLLECTION"):
                domain.recompute_period_financials(p, account["id"])
                touch(p)
        touch(g)
        domain.reconcile_account(account)
    else:
        # below threshold: stays in force as REINSTATED
        g["status"] = "REINSTATED"
        touch(g)
        domain.reconcile_account(account)
    return success(domain.ser_agreement(g))


# ===========================================================================
# Payment
# ===========================================================================

def allocate_payment(account, amount, target_period_id):
    remaining = amount
    if target_period_id is not None:
        targets = [store.tax_periods[target_period_id]]
    else:
        candidates = [p for p in domain.periods_of(account["id"])
                      if p["period_status"] in ("ASSESSED", "IN_COLLECTION")]
        targets = sorted(candidates, key=lambda p: (p["assessment_date"], p["_created_dt"], p["_seq"]))
    for p in targets:
        if remaining <= 0:
            break
        applied = min(remaining, p["balance_due_cents"])
        if applied <= 0:
            continue
        pen_int = p["penalty_accrued_cents"] + p["interest_accrued_cents"]
        principal_portion = max(0, applied - pen_int)
        p["balance_due_cents"] -= applied
        p["paid_to_principal_cents"] += principal_portion
        remaining -= applied
        if p["period_status"] == "ASSESSED":
            p["period_status"] = "IN_COLLECTION"
        domain.maybe_satisfy_period(p)
        touch(p)


@app.route("/collections/payments", methods=["POST"])
def create_payment():
    authorize({"RevenueOfficer"})
    body = get_body()
    account_id = require_str(body, "tax_account_id")
    amount = require_int(body, "amount_cents", exclusive_min=0)
    payment_source = require_enum(body, "payment_source",
                                  {"DDIA_DEBIT", "MANUAL", "OIC_LUMP_SUM"})
    period_id = None
    if body.get("tax_period_id") is not None:
        period_id = require_str(body, "tax_period_id")
    account = get_account(account_id)
    if period_id is not None:
        p = get_period(period_id)
        if p["tax_account_id"] != account_id:
            raise err(ERR_FK_MISMATCH, "tax_period_id does not belong to account")

    rec = make_record(versioned=False)
    rec["tax_account_id"] = account_id
    rec["tax_period_id"] = period_id
    rec["amount_cents"] = amount
    rec["payment_source"] = payment_source
    from datetime import datetime, timezone
    rec["posted_at"] = datetime.now(timezone.utc)
    store.payments[rec["id"]] = rec

    allocate_payment(account, amount, period_id)
    domain.reconcile_account(account)
    domain.maybe_autoclose_agreements(account)
    domain.reconcile_account_no_touch(account)
    return success(domain.ser_payment(rec), status=201)


@app.route("/collections/payments/<payment_id>", methods=["GET"])
def fetch_payment(payment_id):
    authorize({"RevenueOfficer", "CaseReviewer"})
    p = store.payments.get(payment_id)
    if p is None:
        raise err(ERR_RESOURCE_NOT_FOUND, "Payment not found")
    return success(domain.ser_payment(p))


@app.route("/collections/payments", methods=["GET"])
def list_payments():
    authorize({"RevenueOfficer", "CaseReviewer"})
    items = list(store.payments.values())
    acct = request.args.get("tax_account_id")
    period_id = request.args.get("tax_period_id")
    if acct is not None:
        items = [p for p in items if p["tax_account_id"] == acct]
    if period_id is not None:
        items = [p for p in items if p["tax_period_id"] == period_id]
    return paginate(items, domain.ser_payment)


# ===========================================================================
# OfferInCompromise
# ===========================================================================

@app.route("/collections/offers", methods=["POST"])
def create_offer():
    user_id, _ = authorize({"RevenueOfficer"})
    body = get_body()
    account_id = require_str(body, "tax_account_id")
    offer_amount = require_int(body, "offer_amount_cents", exclusive_min=0)
    nre = require_int(body, "net_realizable_equity_cents", minimum=0)
    get_account(account_id)
    rec = make_record(versioned=True)
    rec["tax_account_id"] = account_id
    rec["offer_amount_cents"] = offer_amount
    rec["net_realizable_equity_cents"] = nre
    rec["rcp_cents"] = None
    rec["status"] = "SUBMITTED"
    rec["submitted_by_user_id"] = user_id
    rec["accepted_by_user_id"] = None
    store.offers[rec["id"]] = rec
    return success(domain.ser_offer(rec), status=201)


@app.route("/collections/offers/<offer_id>", methods=["GET"])
def fetch_offer(offer_id):
    authorize({"RevenueOfficer", "CaseReviewer"})
    o = store.offers.get(offer_id)
    if o is None:
        raise err(ERR_RESOURCE_NOT_FOUND, "OfferInCompromise not found")
    return success(domain.ser_offer(o))


@app.route("/collections/offers", methods=["GET"])
def list_offers():
    authorize({"RevenueOfficer", "CaseReviewer"})
    items = list(store.offers.values())
    acct = request.args.get("tax_account_id")
    if acct is not None:
        items = [o for o in items if o["tax_account_id"] == acct]
    return paginate(items, domain.ser_offer)


@app.route("/collections/offers/<offer_id>/begin-evaluation", methods=["POST"])
def begin_evaluation(offer_id):
    authorize({"CaseReviewer"})
    o = store.offers.get(offer_id)
    if o is None:
        raise err(ERR_RESOURCE_NOT_FOUND, "OfferInCompromise not found")
    if o["status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, "Offer is not SUBMITTED")
    account = store.tax_accounts.get(o["tax_account_id"])
    now = clock.now()
    # remaining months = floor(min csed_date - now in days / 30) across ASSESSED/IN_COLLECTION
    candidate_periods = [p for p in domain.periods_of(account["id"])
                         if p["period_status"] in ("ASSESSED", "IN_COLLECTION")]
    if candidate_periods:
        min_days = min(((p["csed_date"] - now).days) for p in candidate_periods)
        remaining_months = min_days // 30
    else:
        remaining_months = 0
    multiplier = calc.rcp_multiplier(remaining_months)
    future_income = account["monthly_disposable_income_cents"] * multiplier
    o["rcp_cents"] = o["net_realizable_equity_cents"] + future_income
    o["status"] = "EVALUATING"
    # open CSED suspensions on ASSESSED/IN_COLLECTION periods
    for p in candidate_periods:
        domain.open_suspension(p, "OIC_EVALUATION", account)
        touch(p)
    touch(o)
    domain.reconcile_account(account)
    return success(domain.ser_offer(o))


@app.route("/collections/offers/<offer_id>/accept", methods=["POST"])
def accept_offer(offer_id):
    user_id, _ = authorize({"CaseReviewer"})
    body = get_body()
    o = store.offers.get(offer_id)
    if o is None:
        raise err(ERR_RESOURCE_NOT_FOUND, "OfferInCompromise not found")
    account = store.tax_accounts.get(o["tax_account_id"])
    expected_version = require_int(body, "expected_tax_account_version", minimum=0)
    if o["status"] != "EVALUATING":
        raise err(ERR_INVALID_STATE, "Offer is not EVALUATING")
    if user_id == o["submitted_by_user_id"]:
        raise err(ERR_SEGREGATION_OF_DUTIES, "Accepter must differ from submitter")
    if o["offer_amount_cents"] < o["rcp_cents"]:
        raise err(ERR_OFFER_BELOW_RCP, "Offer below RCP")
    if expected_version != account["version"]:
        raise err(ERR_STALE_ACCOUNT_VERSION, "Stale account version")

    # cascade
    o["accepted_by_user_id"] = user_id
    o["status"] = "ACCEPTED"
    # create OIC_LUMP_SUM payment allocated oldest-first
    from datetime import datetime, timezone
    pay = make_record(versioned=False)
    pay["tax_account_id"] = account["id"]
    pay["tax_period_id"] = None
    pay["amount_cents"] = o["offer_amount_cents"]
    pay["payment_source"] = "OIC_LUMP_SUM"
    pay["posted_at"] = datetime.now(timezone.utc)
    store.payments[pay["id"]] = pay
    allocate_payment(account, o["offer_amount_cents"], None)
    # set every non-SATISFIED period to ABATED with zero balance
    for p in domain.periods_of(account["id"]):
        if p["period_status"] != "SATISFIED":
            p["period_status"] = "ABATED"
            p["balance_due_cents"] = 0
            touch(p)
    domain.close_all_open_suspensions(account)
    domain.append_event(account["id"], "OIC_DECISION")
    touch(o)
    domain.reconcile_account(account)
    domain.maybe_autoclose_agreements(account)
    domain.reconcile_account_no_touch(account)
    return success(domain.ser_offer(o))


@app.route("/collections/offers/<offer_id>/reject", methods=["POST"])
def reject_offer(offer_id):
    authorize({"CaseReviewer"})
    o = store.offers.get(offer_id)
    if o is None:
        raise err(ERR_RESOURCE_NOT_FOUND, "OfferInCompromise not found")
    if o["status"] != "EVALUATING":
        raise err(ERR_INVALID_STATE, "Offer is not EVALUATING")
    account = store.tax_accounts.get(o["tax_account_id"])
    o["status"] = "REJECTED"
    domain.close_all_open_suspensions(account)
    domain.append_event(account["id"], "OIC_DECISION")
    touch(o)
    domain.reconcile_account(account)
    return success(domain.ser_offer(o))


# ===========================================================================
# FederalTaxLien
# ===========================================================================

@app.route("/collections/liens", methods=["POST"])
def create_lien():
    authorize({"RevenueOfficer"})
    body = get_body()
    account_id = require_str(body, "tax_account_id")
    filed_amount = require_int(body, "filed_amount_cents", exclusive_min=0)
    get_account(account_id)
    rec = make_record(versioned=True)
    rec["tax_account_id"] = account_id
    rec["filed_amount_cents"] = filed_amount
    rec["status"] = "FILED"
    rec["released_at"] = None
    store.liens[rec["id"]] = rec
    return success(domain.ser_lien(rec), status=201)


@app.route("/collections/liens/<lien_id>", methods=["GET"])
def fetch_lien(lien_id):
    authorize({"RevenueOfficer", "CaseReviewer"})
    l = store.liens.get(lien_id)
    if l is None:
        raise err(ERR_RESOURCE_NOT_FOUND, "FederalTaxLien not found")
    return success(domain.ser_lien(l))


@app.route("/collections/liens", methods=["GET"])
def list_liens():
    authorize({"RevenueOfficer", "CaseReviewer"})
    items = list(store.liens.values())
    acct = request.args.get("tax_account_id")
    if acct is not None:
        items = [l for l in items if l["tax_account_id"] == acct]
    return paginate(items, domain.ser_lien)


@app.route("/collections/liens/<lien_id>/request-release", methods=["POST"])
def request_release(lien_id):
    authorize({"RevenueOfficer"})
    l = store.liens.get(lien_id)
    if l is None:
        raise err(ERR_RESOURCE_NOT_FOUND, "FederalTaxLien not found")
    if l["status"] != "FILED":
        raise err(ERR_INVALID_STATE, "Lien is not FILED")
    l["status"] = "RELEASE_PENDING"
    touch(l)
    return success(domain.ser_lien(l))


@app.route("/collections/liens/<lien_id>/approve-release", methods=["POST"])
def approve_release(lien_id):
    authorize({"CaseReviewer"})
    l = store.liens.get(lien_id)
    if l is None:
        raise err(ERR_RESOURCE_NOT_FOUND, "FederalTaxLien not found")
    if l["status"] != "RELEASE_PENDING":
        raise err(ERR_INVALID_STATE, "Lien is not RELEASE_PENDING")
    account = store.tax_accounts.get(l["tax_account_id"])
    guard = account["total_balance_cents"] == 0
    if not guard:
        for g in domain.agreements_of(account["id"]):
            if (g["status"] in ("APPROVED", "REINSTATED")
                    and g["payment_method"] == "DIRECT_DEBIT"):
                guard = True
                break
    if not guard:
        raise err(ERR_LIEN_RELEASE_BLOCKED, "Balance > 0 and no active DDIA agreement")
    from datetime import datetime, timezone
    l["released_at"] = datetime.now(timezone.utc)
    l["status"] = "RELEASED"
    touch(l)
    return success(domain.ser_lien(l))


@app.route("/collections/liens/<lien_id>/withdraw", methods=["POST"])
def withdraw_lien(lien_id):
    authorize({"CaseReviewer"})
    l = store.liens.get(lien_id)
    if l is None:
        raise err(ERR_RESOURCE_NOT_FOUND, "FederalTaxLien not found")
    if l["status"] != "FILED":
        raise err(ERR_INVALID_STATE, "Lien is not FILED")
    l["status"] = "WITHDRAWN"
    touch(l)
    return success(domain.ser_lien(l))


# ===========================================================================
# CncDetermination
# ===========================================================================

@app.route("/collections/cnc-determinations", methods=["POST"])
def create_cnc():
    authorize({"RevenueOfficer"})
    body = get_body()
    account_id = require_str(body, "tax_account_id")
    hardship = require_enum(body, "hardship_reason",
                            {"NO_DISPOSABLE_INCOME", "HARDSHIP", "UNABLE_TO_LOCATE"})
    account = get_account(account_id)
    rec = make_record(versioned=True)
    rec["tax_account_id"] = account_id
    rec["hardship_reason"] = hardship
    rec["status"] = "ACTIVE"
    store.cnc_determinations[rec["id"]] = rec
    domain.reconcile_account(account)
    return success(domain.ser_cnc(rec), status=201)


@app.route("/collections/cnc-determinations/<cnc_id>", methods=["GET"])
def fetch_cnc(cnc_id):
    authorize({"RevenueOfficer", "CaseReviewer"})
    c = store.cnc_determinations.get(cnc_id)
    if c is None:
        raise err(ERR_RESOURCE_NOT_FOUND, "CncDetermination not found")
    return success(domain.ser_cnc(c))


@app.route("/collections/cnc-determinations", methods=["GET"])
def list_cnc():
    authorize({"RevenueOfficer", "CaseReviewer"})
    items = list(store.cnc_determinations.values())
    acct = request.args.get("tax_account_id")
    if acct is not None:
        items = [c for c in items if c["tax_account_id"] == acct]
    return paginate(items, domain.ser_cnc)


@app.route("/collections/cnc-determinations/<cnc_id>/revoke", methods=["POST"])
def revoke_cnc(cnc_id):
    authorize({"RevenueOfficer"})
    c = store.cnc_determinations.get(cnc_id)
    if c is None:
        raise err(ERR_RESOURCE_NOT_FOUND, "CncDetermination not found")
    if c["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "CNC is not ACTIVE")
    account = store.tax_accounts.get(c["tax_account_id"])
    c["status"] = "REVOKED"
    touch(c)
    if account is not None:
        domain.reconcile_account(account)
    return success(domain.ser_cnc(c))


# ===========================================================================
# AccountEvent
# ===========================================================================

@app.route("/collections/account-events", methods=["POST"])
def create_event():
    authorize({"RevenueOfficer"})
    body = get_body()
    account_id = require_str(body, "tax_account_id")
    event_type = require_enum(body, "event_type",
                              {"CSED_SUSPEND_START", "CSED_SUSPEND_END",
                               "AGREEMENT_DEFAULT", "RECOMPUTE", "MISSED_DEBIT",
                               "OIC_DECISION"})
    period_id = None
    if body.get("tax_period_id") is not None:
        period_id = require_str(body, "tax_period_id")
    get_account(account_id)
    if period_id is not None:
        p = get_period(period_id)
        if p["tax_account_id"] != account_id:
            raise err(ERR_FK_MISMATCH, "tax_period_id does not belong to account")
    rec = domain.append_event(account_id, event_type, period_id=period_id)
    return success(domain.ser_event(rec), status=201)


@app.route("/collections/account-events/<event_id>", methods=["GET"])
def fetch_event(event_id):
    authorize({"RevenueOfficer", "CaseReviewer"})
    e = store.account_events.get(event_id)
    if e is None:
        raise err(ERR_RESOURCE_NOT_FOUND, "AccountEvent not found")
    return success(domain.ser_event(e))


@app.route("/collections/account-events", methods=["GET"])
def list_events():
    authorize({"RevenueOfficer", "CaseReviewer"})
    items = list(store.account_events.values())
    acct = request.args.get("tax_account_id")
    period_id = request.args.get("tax_period_id")
    if acct is not None:
        items = [e for e in items if e["tax_account_id"] == acct]
    if period_id is not None:
        items = [e for e in items if e["tax_period_id"] == period_id]
    return paginate(items, domain.ser_event)


# ===========================================================================
# Test clock
# ===========================================================================

@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authorize({"RevenueOfficer"})
    body = get_body()
    target = parse_dt(require_str(body, "to_iso8601"), "to_iso8601")
    clock.set(target)
    return success({"current_utc": iso(target)})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
