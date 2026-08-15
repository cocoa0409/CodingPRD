"""EstimatedPayment endpoints: schedule generation, manual quarter creation,
list, get, record-payment, reverse-payment.

Validation priority highlights (SCAFFOLD §1.4):
  - record-payment on a PAID quarter is ERR_PAYMENT_ALREADY_SETTLED (priority 4
    state), which beats the ERR_OVERPAYMENT amount check (priority 10);
  - manual-quarter interval rules: quarter_index uniqueness and closed-interval
    non-overlap are priority 7 (409), exact contiguity gaps are ERR_QUARTER_GAP
    (422), and a malformed period/due date range is priority 8 (422).
"""
from flask import Blueprint

from db import db, new_record, touch
from errors import (
    raise_error,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE_TRANSITION,
    ERR_PAYMENT_ALREADY_SETTLED,
    ERR_DUPLICATE_QUARTER,
    ERR_QUARTER_OVERLAP,
    ERR_QUARTER_GAP,
    ERR_DATE_RANGE_INVALID,
    ERR_INVALID_AMOUNT,
    ERR_OVERPAYMENT,
)
from middleware import authorized, READER_ROLES
from response import success_object, success_list
from routes.common import get_or_404, apply_filters, paginate
from serializers import serialize
from services.calc import (
    compute_annual_estimate,
    compute_quarterly_amounts,
    payments_of_pair,
)
from util import is_date_str, parse_date, add_months, add_days, fmt_date
from validate import body_json, present_int, req_int, req_enum, req_date

bp = Blueprint("payments", __name__)

METHODS = ("PRIOR_YEAR_SAFE_HARBOR", "CURRENT_YEAR_ANNUALIZED")


def _resolve_fks(data):
    year = None
    tax_year_id = data.get("tax_year_id")
    if isinstance(tax_year_id, str):
        year = get_or_404(db.tax_years, tax_year_id, "TaxYear")
    jur_probe = data.get("jurisdiction_id")
    if isinstance(jur_probe, str):
        get_or_404(db.jurisdictions, jur_probe, "Jurisdiction")
    return year


@bp.route("/tax/estimated-payments/generate-schedule", methods=["POST"])
def generate_schedule():
    authorized(("TaxManager",))
    data = body_json()

    # Priority 3 (existence).
    year = _resolve_fks(data)

    # Priority 7 (uniqueness): generation requires zero existing payments for the pair.
    tax_year_id = data.get("tax_year_id")
    jurisdiction_id = data.get("jurisdiction_id")
    if isinstance(tax_year_id, str) and isinstance(jurisdiction_id, str):
        if payments_of_pair(tax_year_id, jurisdiction_id):
            raise_error(ERR_DUPLICATE_QUARTER,
                        "estimated payments already exist for this (tax_year_id, jurisdiction_id) pair")

    # Priority 11 (structural).
    from validate import req_str
    tax_year_id = req_str(data, "tax_year_id")
    jurisdiction_id = req_str(data, "jurisdiction_id")
    method = req_enum(data, "method", METHODS)
    if year is None:
        raise_error(ERR_NOT_FOUND, f"TaxYear '{tax_year_id}' does not exist")
    jurisdiction = get_or_404(db.jurisdictions, jurisdiction_id, "Jurisdiction")

    # The four quarters tile the fiscal year in 3-month closed intervals from
    # period_start_date; due_date = period_end_date + 15 days.
    annual = compute_annual_estimate(year, jurisdiction, method)
    amounts = compute_quarterly_amounts(annual)
    period_start = parse_date(year["period_start_date"])

    created = []
    for n in range(1, 5):
        q_start = add_months(period_start, 3 * (n - 1))
        q_end = add_days(add_months(q_start, 3), -1)
        due = add_days(q_end, 15)
        p = new_record({
            "tax_year_id": tax_year_id,
            "jurisdiction_id": jurisdiction_id,
            "quarter_index": n,
            "period_start_date": fmt_date(q_start),
            "period_end_date": fmt_date(q_end),
            "due_date": fmt_date(due),
            "method": method,
            "base_scheduled_amount_cents": amounts[n - 1],
            "scheduled_amount_cents": amounts[n - 1],
            "paid_amount_cents": 0,
            "penalty_cents": 0,
            "status": "SCHEDULED",
        })
        db.payments[p["id"]] = p
        created.append(p)

    # Array envelope without pagination meta (a creation endpoint, not a list read).
    from response import _meta
    from flask import jsonify
    envelope = {
        "meta": _meta(),
        "response_type": "array",
        "data": [serialize(p) for p in created],
    }
    return jsonify(envelope), 201


@bp.route("/tax/estimated-payments", methods=["POST"])
def create_payment():
    authorized(("TaxManager",))
    data = body_json()

    # Priority 3 (existence).
    year = _resolve_fks(data)

    tax_year_id = data.get("tax_year_id")
    jurisdiction_id = data.get("jurisdiction_id")
    pair_known = isinstance(tax_year_id, str) and isinstance(jurisdiction_id, str)
    existing = payments_of_pair(tax_year_id, jurisdiction_id) if pair_known else []

    quarter_probe = present_int(data, "quarter_index")
    ps_raw, pe_raw = data.get("period_start_date"), data.get("period_end_date")
    dates_ok = is_date_str(ps_raw) and is_date_str(pe_raw)

    # Priority 7 (uniqueness / interval rules), in scaffold listing order:
    # duplicate quarter -> closed-interval overlap -> exact contiguity.
    if pair_known and quarter_probe is not None:
        if any(p["quarter_index"] == quarter_probe for p in existing):
            raise_error(ERR_DUPLICATE_QUARTER,
                        f"quarter_index {quarter_probe} already exists for this pair")
    if pair_known and dates_ok:
        start, end = parse_date(ps_raw), parse_date(pe_raw)
        for p in existing:
            # Closed-interval semantics: start == existing end collides.
            if start <= parse_date(p["period_end_date"]) and parse_date(p["period_start_date"]) <= end:
                raise_error(ERR_QUARTER_OVERLAP,
                            "quarter interval overlaps an existing quarter of the pair")
        if quarter_probe is not None:
            if quarter_probe == 1:
                if year is not None and start != parse_date(year["period_start_date"]):
                    raise_error(ERR_QUARTER_GAP,
                                "quarter 1 must start on the TaxYear's period_start_date")
            elif quarter_probe in (2, 3, 4):
                if not existing:
                    raise_error(ERR_QUARTER_GAP,
                                "quarters must be exactly contiguous: earlier quarters are missing")
                max_end = max(parse_date(p["period_end_date"]) for p in existing)
                if start != add_days(max_end, 1):
                    raise_error(ERR_QUARTER_GAP,
                                "quarter must start the day after the highest existing period_end_date")

    # Priority 8 (date-range sanity): the interval must be well formed and the
    # due date must fall within the quarter's horizon (generated schedules place
    # it at period_end + 15 days, so it may follow — never precede — the start).
    if dates_ok:
        if parse_date(pe_raw) < parse_date(ps_raw):
            raise_error(ERR_DATE_RANGE_INVALID,
                        "period_end_date must not precede period_start_date")
        due_raw = data.get("due_date")
        if is_date_str(due_raw) and parse_date(due_raw) < parse_date(ps_raw):
            raise_error(ERR_DATE_RANGE_INVALID,
                        "due_date lies outside the quarter interval")

    # Priority 10 (amount sanity): scheduled amount must be nonnegative.
    sched_probe = present_int(data, "scheduled_amount_cents")
    if sched_probe is not None and sched_probe < 0:
        raise_error(ERR_INVALID_AMOUNT, "scheduled_amount_cents must be >= 0")

    # Priority 11 (structural).
    from validate import req_str
    tax_year_id = req_str(data, "tax_year_id")
    jurisdiction_id = req_str(data, "jurisdiction_id")
    quarter_index = req_int(data, "quarter_index")
    if quarter_index not in (1, 2, 3, 4):
        from errors import ERR_INVALID_REQUEST
        raise_error(ERR_INVALID_REQUEST, "quarter_index must be within 1..4")
    period_start = req_date(data, "period_start_date")
    period_end = req_date(data, "period_end_date")
    due_date = req_date(data, "due_date")
    method = req_enum(data, "method", METHODS)
    scheduled = req_int(data, "scheduled_amount_cents")
    if year is None:
        raise_error(ERR_NOT_FOUND, f"TaxYear '{tax_year_id}' does not exist")
    get_or_404(db.jurisdictions, jurisdiction_id, "Jurisdiction")

    p = new_record({
        "tax_year_id": tax_year_id,
        "jurisdiction_id": jurisdiction_id,
        "quarter_index": quarter_index,
        "period_start_date": period_start,
        "period_end_date": period_end,
        "due_date": due_date,
        "method": method,
        "base_scheduled_amount_cents": scheduled,  # immutable anchor
        "scheduled_amount_cents": scheduled,
        "paid_amount_cents": 0,
        "penalty_cents": 0,
        "status": "SCHEDULED",
    })
    db.payments[p["id"]] = p
    return success_object(serialize(p), status=201)


@bp.route("/tax/estimated-payments", methods=["GET"])
def list_payments():
    authorized(READER_ROLES)
    recs = apply_filters(db.payments.values(), {
        "tax_year_id": "tax_year_id",
        "jurisdiction_id": "jurisdiction_id",
        "status": "status",
        "method": "method",
    })
    page, total, limit, offset = paginate(recs)
    return success_list([serialize(r) for r in page], total, limit, offset)


@bp.route("/tax/estimated-payments/<paymentId>", methods=["GET"])
def get_payment(paymentId):
    authorized(READER_ROLES)
    return success_object(serialize(get_or_404(db.payments, paymentId, "EstimatedPayment")))


@bp.route("/tax/estimated-payments/<paymentId>/record-payment", methods=["POST"])
def record_payment(paymentId):
    authorized(("TaxAccountant",))
    p = get_or_404(db.payments, paymentId, "EstimatedPayment")

    # Priority 4 (state): the already-settled error is distinct and beats the
    # amount checks (priority 10).
    if p["status"] == "PAID":
        raise_error(ERR_PAYMENT_ALREADY_SETTLED,
                    "the quarter is already PAID")

    data = body_json()

    # Priority 10 (amount sanity): positive amount, never an overpayment.
    amt_probe = present_int(data, "amount_cents")
    if amt_probe is not None:
        if amt_probe <= 0:
            raise_error(ERR_INVALID_AMOUNT, "amount_cents must be > 0")
        if p["paid_amount_cents"] + amt_probe > p["scheduled_amount_cents"]:
            raise_error(ERR_OVERPAYMENT,
                        "payment would push paid_amount_cents above scheduled_amount_cents")

    # Priority 11 (structural).
    amount = req_int(data, "amount_cents")

    new_paid = p["paid_amount_cents"] + amount
    if new_paid == p["scheduled_amount_cents"]:
        p["status"] = "PAID"
    elif p["status"] == "LATE":
        # The only declared record-payment transition from LATE is exact completion.
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    "a LATE quarter accepts only the exact remaining balance")
    else:
        p["status"] = "PARTIALLY_PAID"
    p["paid_amount_cents"] = new_paid
    touch(p)
    return success_object(serialize(p))


@bp.route("/tax/estimated-payments/<paymentId>/reverse-payment", methods=["POST"])
def reverse_payment(paymentId):
    authorized(("TaxManager",))
    p = get_or_404(db.payments, paymentId, "EstimatedPayment")

    # Priority 4 (state): no reversal is defined from SCHEDULED.
    if p["status"] == "SCHEDULED":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    "reverse-payment is not defined from status SCHEDULED")

    data = body_json()

    # Priority 10 (amount sanity): bounds depend on the current state.
    amt_probe = present_int(data, "amount_cents")
    if amt_probe is not None:
        if amt_probe <= 0:
            raise_error(ERR_INVALID_AMOUNT, "amount_cents must be > 0")
        if amt_probe > p["paid_amount_cents"]:
            raise_error(ERR_INVALID_AMOUNT,
                        "reversal exceeds the paid balance")
        if p["status"] == "PAID" and amt_probe == p["paid_amount_cents"]:
            raise_error(ERR_INVALID_AMOUNT,
                        "reversal from PAID must be strictly less than the paid balance")

    # Priority 11 (structural).
    amount = req_int(data, "amount_cents")

    p["paid_amount_cents"] -= amount
    if p["status"] == "PARTIALLY_PAID":
        if p["paid_amount_cents"] == 0:
            p["status"] = "SCHEDULED"
    elif p["status"] == "PAID":
        p["status"] = "PARTIALLY_PAID"
    elif p["status"] == "LATE":
        # Penalty is never refunded; at zero paid the quarter stays LATE until
        # the next sweep re-evaluates it.
        if p["paid_amount_cents"] > 0:
            p["status"] = "PARTIALLY_PAID"
    touch(p)
    return success_object(serialize(p))
