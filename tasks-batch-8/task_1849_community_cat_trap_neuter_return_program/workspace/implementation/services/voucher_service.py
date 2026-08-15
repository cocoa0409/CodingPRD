"""Voucher fiscal rules (PRD §2.8, calculations voucher_monthly_issuance_cap
and voucher_reimbursement_amount, and the §3.8 expiry sweep).

Monthly issuance cap: at most 30,000 cents per caretaker per issued_month,
across both funding sources; the consumed envelope sums face_value_cents over
vouchers in ISSUED, COMMITTED or REDEEMED. VOIDED and EXPIRED vouchers free
their value back. Only a strict excess is rejected.

Reimbursement: base = min(face_value_cents, clinic.voucher_reimbursement_cents).
MUNICIPAL_GRANT reimburses the full base with zero caretaker share;
DONATION_FUND reimburses floor(base * 0.80) and the caretaker is invoiced the
remainder, so reimbursement + share == base exactly. A mortality voids the
voucher and settles nothing.

Expiry: ISSUED vouchers whose issued_month is at least 3 calendar months
before the current logical month become EXPIRED.
"""

from db import db
from util import now_dt

MONTHLY_CAP_CENTS = 30000
LIVE_STATUSES = {"ISSUED", "COMMITTED", "REDEEMED"}
DONATION_COVERAGE_NUM = 80   # 0.80 as exact integer arithmetic
DONATION_COVERAGE_DEN = 100
VOUCHER_TTL_MONTHS = 3


def current_month():
    return now_dt().strftime("%Y-%m")


def month_diff(issued_month, reference=None):
    """Whole calendar months from issued_month (YYYY-MM) to the reference
    month (defaults to the current logical month)."""
    iy, im = (int(p) for p in issued_month.split("-"))
    ref = reference or now_dt()
    return (ref.year * 12 + ref.month) - (iy * 12 + im)


def issued_total_for_month(caretaker_id, month):
    return sum(v["face_value_cents"] for v in db.vouchers.values()
               if v["caretaker_id"] == caretaker_id
               and v["issued_month"] == month
               and v["status"] in LIVE_STATUSES)


def cap_headroom(caretaker_id, month):
    return MONTHLY_CAP_CENTS - issued_total_for_month(caretaker_id, month)


def settle_reimbursement(voucher, clinic):
    """Record the reimbursement split on a voucher being redeemed."""
    base = min(voucher["face_value_cents"], clinic["voucher_reimbursement_cents"])
    if voucher["funding_source"] == "MUNICIPAL_GRANT":
        reimbursement, share = base, 0
    else:  # DONATION_FUND
        reimbursement = (base * DONATION_COVERAGE_NUM) // DONATION_COVERAGE_DEN
        share = base - reimbursement
    voucher["reimbursement_cents"] = reimbursement
    voucher["caretaker_share_cents"] = share


def expirable_vouchers():
    return [v for v in db.vouchers.values()
            if v["status"] == "ISSUED" and month_diff(v["issued_month"]) >= VOUCHER_TTL_MONTHS]
