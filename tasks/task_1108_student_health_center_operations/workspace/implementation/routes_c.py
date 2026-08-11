"""Routes part C: billing (invoice generation/issue, payments, voids),
after-hours referrals, health-fee pools."""
from datetime import timedelta

from flask import Blueprint, request

from store import db, clock, new_entity, bump
from helpers import (
    ApiError, require_auth, get_body, envelope_ok, list_response,
    req_present, req_string, req_int, req_enum, err_invalid_request,
    err_not_found, parse_date,
)
from serializers import (
    ser_invoice, ser_payment, ser_referral, ser_pool,
)
from services import (
    open_pool, compute_line_subsidies, debit_pool, final_payer_split,
    rederive_invoice_balance_status, is_after_hours, has_oncall_coverage,
)

bp_c = Blueprint("routes_c", __name__)

PAYMENT_METHODS = {"CARD", "CASH", "EXTERNAL_REMITTANCE"}
SERVICE_CATEGORIES = {"CONSULT", "PHARMACY", "LAB", "TRAVEL_VACCINE", "SPORTS_FEE"}


def get_or_404(table, entity_id):
    e = db[table].get(entity_id)
    if e is None:
        raise err_not_found("Resource not found: %s" % entity_id)
    return e


def arg(name):
    return request.args.get(name)


# ==========================================================================
# Billing
# ==========================================================================

@bp_c.route("/shc/encounters/<eid>/invoice", methods=["POST"])
def generate_invoice(eid):
    require_auth({"BillingOfficer"})
    body = get_body()
    raw_lines = req_present(body, "lines")
    if not isinstance(raw_lines, list) or not raw_lines:
        raise err_invalid_request("lines must be a non-empty list")
    lines = []
    for i, raw in enumerate(raw_lines):
        if not isinstance(raw, dict):
            raise err_invalid_request("lines[%d] must be an object" % i)
        category = raw.get("service_category")
        if category not in SERVICE_CATEGORIES:
            raise err_invalid_request(
                "lines[%d].service_category must be one of %s"
                % (i, sorted(SERVICE_CATEGORIES)))
        charge = raw.get("charge_cents")
        if not isinstance(charge, int) or isinstance(charge, bool) or charge <= 0:
            raise err_invalid_request("lines[%d].charge_cents must be an integer > 0" % i)
        lines.append({"service_category": category, "charge_cents": charge})
    enc = get_or_404("encounters", eid)
    if enc["status"] != "OPEN":
        raise ApiError("ERR_ENCOUNTER_NOT_OPEN", 409,
                       "invoice generation requires an OPEN encounter")
    if enc["fee_covered"]:
        raise ApiError("ERR_INVOICE_NOT_ALLOWED", 409,
                       "fee-covered encounters carry no invoice")
    if any(i["encounter_id"] == eid for i in db["invoices"].values()):
        raise ApiError("ERR_INVOICE_EXISTS", 409,
                       "an invoice already exists for the encounter")
    applied, charge_total, subsidy, pool = compute_line_subsidies(enc, lines)
    inv = new_entity()
    inv.update({
        "encounter_id": eid,
        "student_id": enc["student_id"],
        "status": "DRAFT",
        "variant": "PROVISIONAL",
        "lines": lines,
        "charge_total_cents": charge_total,
        "subsidy_cents": subsidy,
        # PROVISIONAL payer split: patient pays everything.
        "insurer_pays_cents": 0,
        "patient_responsibility_cents": charge_total,
        "balance_cents": charge_total,
        "due_date": None,
        "issued_at": None,
    })
    db["invoices"][inv["id"]] = inv
    # Pool waterfall: single debit after the invoice is built.
    debit_pool(pool, subsidy)
    return envelope_ok(ser_invoice(inv), status=201)


@bp_c.route("/shc/invoices", methods=["GET"])
def list_invoices():
    require_auth()
    items = db["invoices"].values()
    if arg("student_id") is not None:
        items = [i for i in items if i["student_id"] == arg("student_id")]
    if arg("encounter_id") is not None:
        items = [i for i in items if i["encounter_id"] == arg("encounter_id")]
    if arg("status") is not None:
        items = [i for i in items if i["status"] == arg("status")]
    return list_response(items, ser_invoice)


@bp_c.route("/shc/invoices/<iid>", methods=["GET"])
def get_invoice(iid):
    require_auth()
    return envelope_ok(ser_invoice(get_or_404("invoices", iid)))


@bp_c.route("/shc/invoices/<iid>/issue", methods=["POST"])
def issue_invoice(iid):
    require_auth({"BillingOfficer"})
    get_body()
    inv = get_or_404("invoices", iid)
    if inv["status"] != "DRAFT":
        raise ApiError("ERR_INVOICE_NOT_DRAFT", 409, "issue requires status DRAFT")
    final_payer_split(inv)
    now = clock.now()
    inv["status"] = "ISSUED"
    inv["variant"] = "FINAL"
    inv["issued_at"] = now
    inv["due_date"] = now.date() + timedelta(days=30)
    inv["balance_cents"] = inv["patient_responsibility_cents"]
    bump(inv)
    return envelope_ok(ser_invoice(inv))


@bp_c.route("/shc/invoices/<iid>/payments", methods=["POST"])
def post_payment(iid):
    require_auth({"BillingOfficer"})
    body = get_body()
    amount_cents = req_int(body, "amount_cents")
    method = req_enum(body, "method", PAYMENT_METHODS)
    inv = get_or_404("invoices", iid)
    if inv["status"] not in ("ISSUED", "PARTIALLY_PAID", "OVERDUE"):
        raise ApiError("ERR_INVOICE_NOT_PAYABLE", 409,
                       "payment requires status ISSUED, PARTIALLY_PAID, or OVERDUE")
    if amount_cents <= 0:
        raise ApiError("ERR_INVALID_QUANTITY", 422, "amount_cents must be > 0")
    if amount_cents > inv["balance_cents"]:
        raise ApiError("ERR_OVERPAYMENT", 422,
                       "payment amount exceeds the invoice balance")
    payment = new_entity()
    payment.update({
        "invoice_id": iid,
        "amount_cents": amount_cents,
        "method": method,
        "status": "POSTED",
        "voided_at": None,
    })
    db["payments"][payment["id"]] = payment
    rederive_invoice_balance_status(inv)
    return envelope_ok(ser_payment(payment), status=201)


@bp_c.route("/shc/payments/<pid>/void", methods=["POST"])
def void_payment(pid):
    require_auth({"BillingOfficer"})
    get_body()
    payment = get_or_404("payments", pid)
    if payment["status"] != "POSTED":
        raise ApiError("ERR_PAYMENT_NOT_VOIDABLE", 409,
                       "void requires status POSTED")
    payment["status"] = "VOIDED"
    payment["voided_at"] = clock.now()
    bump(payment)
    inv = db["invoices"][payment["invoice_id"]]
    rederive_invoice_balance_status(inv)
    return envelope_ok(ser_payment(payment))


@bp_c.route("/shc/invoices/<iid>/payments", methods=["GET"])
def list_invoice_payments(iid):
    require_auth()
    get_or_404("invoices", iid)
    items = [p for p in db["payments"].values() if p["invoice_id"] == iid]
    return list_response(items, ser_payment)


# ==========================================================================
# After-hours referrals
# ==========================================================================

@bp_c.route("/shc/encounters/<eid>/referrals", methods=["POST"])
def create_referral(eid):
    uid, _ = require_auth({"Clinician"})
    body = get_body()
    hospital_name = req_string(body, "hospital_name")
    reason = req_string(body, "reason")
    enc = get_or_404("encounters", eid)
    if enc["status"] != "OPEN":
        raise ApiError("ERR_ENCOUNTER_NOT_OPEN", 409,
                       "child creation requires an OPEN encounter")
    now = clock.now()
    after_hours = is_after_hours(now)
    if after_hours and not has_oncall_coverage(now):
        raise ApiError("ERR_NO_ONCALL_COVERAGE", 409,
                       "after-hours referral requires a covering on-call shift")
    ref = new_entity()
    ref.update({
        "encounter_id": eid,
        "hospital_name": hospital_name,
        "reason": reason,
        "status": "INITIATED",
        "after_hours": after_hours,
        "created_by_user_id": uid,
    })
    db["referrals"][ref["id"]] = ref
    return envelope_ok(ser_referral(ref), status=201)


@bp_c.route("/shc/referrals/<rid>/accept", methods=["POST"])
def accept_referral(rid):
    require_auth({"Clinician"})
    get_body()
    ref = get_or_404("referrals", rid)
    if ref["status"] != "INITIATED":
        raise ApiError("ERR_REFERRAL_NOT_INITIATED", 409,
                       "accept requires status INITIATED")
    ref["status"] = "ACCEPTED"
    bump(ref)
    return envelope_ok(ser_referral(ref))


@bp_c.route("/shc/encounters/<eid>/referrals", methods=["GET"])
def list_encounter_referrals(eid):
    require_auth()
    get_or_404("encounters", eid)
    items = [r for r in db["referrals"].values() if r["encounter_id"] == eid]
    return list_response(items, ser_referral)


# ==========================================================================
# Health fee pools
# ==========================================================================

@bp_c.route("/shc/health-fee-pools", methods=["POST"])
def create_pool():
    require_auth({"HealthAdmin"})
    body = get_body()
    term_code = req_string(body, "term_code")
    budget_cents = req_int(body, "budget_cents")
    term_end_date = parse_date(req_present(body, "term_end_date"), "term_end_date")
    if budget_cents <= 0:
        raise err_invalid_request("budget_cents must be an integer > 0")
    if open_pool() is not None:
        raise ApiError("ERR_DUPLICATE_POOL_TERM", 409,
                       "another HealthFeePool with status OPEN already exists")
    pool = new_entity()
    pool.update({
        "term_code": term_code,
        "budget_cents": budget_cents,
        "spent_cents": 0,
        "term_end_date": term_end_date,
        "status": "OPEN",
        "exhausted": False,
    })
    db["pools"][pool["id"]] = pool
    return envelope_ok(ser_pool(pool), status=201)


@bp_c.route("/shc/health-fee-pools", methods=["GET"])
def list_pools():
    require_auth()
    items = db["pools"].values()
    if arg("term_code") is not None:
        items = [p for p in items if p["term_code"] == arg("term_code")]
    return list_response(items, ser_pool)
