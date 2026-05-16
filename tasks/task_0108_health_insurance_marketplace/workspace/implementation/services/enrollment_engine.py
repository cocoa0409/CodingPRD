"""Enrollment premium computation, invoice issuance, payment rollup."""

from datetime import date, timedelta
from decimal import Decimal

from db import db, stamp_created, bump_version
from clock import clock
from .calculations import (
    age_adjusted_premium_for_member,
    household_members_for,
)
from .dates import (
    parse_iso_date,
    iso_date_str,
    yyyy_mm,
    parse_yyyy_mm,
    first_of_month,
    first_day_of_next_month,
    last_day_of_month,
    add_days,
)
from .money import half_up_int


def get_plan_variant(variant_id: str):
    return db.plan_variants.get(variant_id)


def get_plan(plan_id: str):
    return db.plans.get(plan_id)


def compute_monthly_premium(enrollment_or_inputs: dict, app: dict, plan: dict, coverage_start: date):
    """Compute (gross, aptc_applied, net) for given inputs. Returns tuple of cents."""
    members = household_members_for(app["id"])
    gross = 0
    for m in members:
        if not m["include_in_household"]:
            continue
        gross += age_adjusted_premium_for_member(m, plan, coverage_start)

    aptc_est = app.get("aptc_estimated_cents") or 0
    monthly_aptc = half_up_int(Decimal(aptc_est) / Decimal(12))
    if monthly_aptc < 0:
        monthly_aptc = 0
    if monthly_aptc > gross:
        monthly_aptc = gross

    net = gross - monthly_aptc
    return gross, monthly_aptc, net


def recompute_enrollment_premium(enrollment: dict) -> None:
    """Recompute the enrollment's premium fields in place."""
    app = db.applications.get(enrollment["application_id"])
    variant = db.plan_variants.get(enrollment["plan_variant_id"])
    if not app or not variant:
        return
    plan = db.plans.get(variant["plan_id"])
    if not plan:
        return
    coverage_start = parse_iso_date(enrollment["coverage_start_date"])
    gross, aptc, net = compute_monthly_premium(enrollment, app, plan, coverage_start)
    enrollment["monthly_premium_gross_cents"] = gross
    enrollment["monthly_aptc_applied_cents"] = aptc
    enrollment["monthly_net_premium_cents"] = net
    bump_version(enrollment)


def issue_premium_invoice(enrollment: dict, billing_month_str: str) -> dict:
    """Create and persist a new PremiumInvoice for an enrollment."""
    inv = {
        "id": None,  # filled by stamp_created
        "enrollment_id": enrollment["id"],
        "billing_month": billing_month_str,
        "gross_amount_cents": enrollment["monthly_premium_gross_cents"],
        "aptc_amount_cents": enrollment["monthly_aptc_applied_cents"],
        "net_amount_cents": enrollment["monthly_net_premium_cents"],
        "due_date": iso_date_str(parse_yyyy_mm(billing_month_str)),
        "status": "ISSUED",
        "paid_at": None,
    }
    stamp_created(inv, versioned=False)
    db.premium_invoices[inv["id"]] = inv
    return inv


def ensure_monthly_invoices_issued(enrollment: dict) -> None:
    """Issue any missing monthly PremiumInvoices up to the current clock
    month.

    PRD §3.7: "Every billing month the enrollment issues a
    PremiumInvoice whose enrollment_id foreign-key points back to its
    parent enrollment." We materialise one invoice per (enrollment,
    billing_month) pair from the coverage_start_date forward, skipping
    months that already have an invoice and capping at the current
    logical-clock month. TERMINATED enrollments do not accrue new
    invoices.
    """
    if enrollment["coverage_status"] == "TERMINATED":
        return
    coverage_start_str = enrollment.get("coverage_start_date")
    if not coverage_start_str:
        return
    coverage_start = parse_iso_date(coverage_start_str)
    now = clock.now().date()
    # If coverage hasn't started yet, only the binder for the
    # coverage_start month is needed (and is created at enrollment).
    cursor = first_of_month(coverage_start)
    end = first_of_month(now)
    existing_months = {
        inv["billing_month"]
        for inv in db.premium_invoices.values()
        if inv["enrollment_id"] == enrollment["id"]
    }
    while cursor <= end:
        bm = yyyy_mm(cursor)
        if bm not in existing_months:
            issue_premium_invoice(enrollment, bm)
            existing_months.add(bm)
        # advance one calendar month
        cursor = first_day_of_next_month(cursor)


def invoices_for_enrollment(enrollment_id: str) -> list:
    items = [
        inv for inv in db.premium_invoices.values()
        if inv["enrollment_id"] == enrollment_id
    ]
    # Sort by (billing_month ASC, id ASC)
    items.sort(key=lambda x: (x["billing_month"], x["id"]))
    return items


def rollup_payment_status(enrollment: dict) -> None:
    """Per the calculations.payment_status_rollup algorithm. Mutates enrollment in place."""
    if enrollment["coverage_status"] == "TERMINATED":
        # don't recompute payment status on terminated enrollments
        return

    now = clock.now().date()
    # Treat invoices as the canonical input (excluding VOIDED)
    invoices = [
        inv for inv in invoices_for_enrollment(enrollment["id"])
        if inv["status"] != "VOIDED"
    ]

    # Special-case binder: if still AWAITING_BINDER (no payment received), keep that
    if enrollment["payment_status"] == "AWAITING_BINDER":
        # If any invoice is PAID/WAIVED, flip to CURRENT
        any_paid = any(inv["status"] in ("PAID", "WAIVED") for inv in invoices)
        if any_paid:
            enrollment["payment_status"] = "CURRENT"
        else:
            return

    # Find the oldest invoice still ISSUED whose due_date <= now
    oldest_unpaid = None
    for inv in invoices:
        if inv["status"] != "ISSUED":
            continue
        due = parse_iso_date(inv["due_date"])
        if due > now:
            continue
        if oldest_unpaid is None:
            oldest_unpaid = inv

    if oldest_unpaid is None:
        new_status = "CURRENT"
    else:
        # Anchor: first day of oldest_unpaid + 30 days = first day of billing_month + 30 days
        billing_first = parse_yyyy_mm(oldest_unpaid["billing_month"])
        anchor = add_days(billing_first, 30)
        days_overdue = (now - anchor).days
        if days_overdue <= 0:
            new_status = "CURRENT"
        elif days_overdue <= 30:
            new_status = "DELINQUENT_M1"
        elif days_overdue <= 60:
            new_status = "DELINQUENT_M2"
        else:
            new_status = "DELINQUENT_M3"

    if new_status != enrollment.get("payment_status"):
        enrollment["payment_status"] = new_status
        bump_version(enrollment)


def maybe_update_coverage_status(enrollment: dict) -> None:
    """Drive coverage_status transitions from payment_status."""
    if enrollment["coverage_status"] == "TERMINATED":
        return

    payment_status = enrollment["payment_status"]
    coverage_status = enrollment["coverage_status"]

    # PENDING_PAYMENT -> ACTIVE: binder paid and coverage_start_date reached
    if coverage_status == "PENDING_PAYMENT" and payment_status == "CURRENT":
        coverage_start = parse_iso_date(enrollment["coverage_start_date"])
        if clock.now().date() >= coverage_start:
            enrollment["coverage_status"] = "ACTIVE"
            bump_version(enrollment)
            return

    # ACTIVE -> GRACE_PERIOD: any DELINQUENT_M* puts the enrollment in
    # the grace bucket (PRD §3.7 lockstep). M2/M3 are reached when an
    # invoice was still unpaid through the M1 boundary, so the move
    # from ACTIVE to GRACE_PERIOD must fire on M1 *or later*.
    if coverage_status == "ACTIVE" and payment_status in (
        "DELINQUENT_M1", "DELINQUENT_M2", "DELINQUENT_M3",
    ):
        enrollment["coverage_status"] = "GRACE_PERIOD"
        bump_version(enrollment)
        # Fall through to the GRACE_PERIOD -> TERMINATED check below in
        # case M3 + 90-day threshold has already elapsed.
        coverage_status = "GRACE_PERIOD"

    # GRACE_PERIOD -> ACTIVE: all open invoices paid; payment_status=CURRENT
    if coverage_status == "GRACE_PERIOD" and payment_status == "CURRENT":
        enrollment["coverage_status"] = "ACTIVE"
        bump_version(enrollment)
        return

    # GRACE_PERIOD -> TERMINATED on day 91 of non-payment
    if coverage_status == "GRACE_PERIOD" and payment_status == "DELINQUENT_M3":
        # Check 90-day threshold: last PAID due_date + 90 days <= now
        invoices = invoices_for_enrollment(enrollment["id"])
        paid_invoices = [
            inv for inv in invoices
            if inv["status"] in ("PAID", "WAIVED")
        ]
        if paid_invoices:
            last_paid = paid_invoices[-1]
            last_paid_due = parse_iso_date(last_paid["due_date"])
            threshold = add_days(last_paid_due, 90)
            if clock.now().date() >= threshold:
                _terminate_for_nonpayment(enrollment, last_paid)
                return


def _terminate_for_nonpayment(enrollment: dict, last_paid_invoice: dict) -> None:
    enrollment["coverage_status"] = "TERMINATED"
    enrollment["terminated_reason"] = "NON_PAYMENT"
    last_paid_month_first = parse_yyyy_mm(last_paid_invoice["billing_month"])
    enrollment["coverage_end_date"] = iso_date_str(last_day_of_month(last_paid_month_first))
    bump_version(enrollment)


def derive_coverage_start(app: dict) -> str:
    """Derive coverage_start_date: governing SEP effective_date or Jan 1 of coverage_year."""
    governing_sep = governing_sep_for_application(app)
    if governing_sep is not None:
        return governing_sep["effective_date"]
    return iso_date_str(date(app["coverage_year"], 1, 1))


def governing_sep_for_application(app: dict):
    """Return the earliest VERIFIED open SEP for the application, or None."""
    now_date = clock.now().date()
    seps = [
        s for s in db.sep_events.values()
        if s["application_id"] == app["id"]
        and s["status"] == "VERIFIED"
    ]
    open_seps = []
    for s in seps:
        if not s.get("window_opens_on") or not s.get("window_closes_on"):
            continue
        wc = parse_iso_date(s["window_closes_on"])
        if wc < now_date:
            continue
        open_seps.append(s)
    if not open_seps:
        return None
    # Tie-break: earliest reported_at ascending
    open_seps.sort(key=lambda s: s["reported_at"])
    return open_seps[0]
