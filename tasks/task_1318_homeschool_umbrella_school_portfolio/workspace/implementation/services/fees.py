"""Family fee ledger (family_fee_status), coop fee calculation, refund waterfall."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import clock
import db
from services import core

FEES_GRACE_DAYS = 30
EARLY_BIRD_DAYS = 30
EARLY_BIRD_PCT = 10
SIBLING_PCT = 15
DISCOUNT_CAP_PCT = 25
ADMIN_FEE_CENTS = 2500
PARTIAL_WINDOW_DAYS = 14
PARTIAL_REFUND_PCT = 50


def round_half_up_int(dec):
    return int(Decimal(dec).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def refresh_fee_status(family):
    """Recompute derived fee_status from current balance/aging."""
    if family["fee_balance_cents"] > 0 and family["oldest_unpaid_charge_at"] is not None:
        oldest = clock.parse(family["oldest_unpaid_charge_at"])
        if clock.now() > oldest + timedelta(days=FEES_GRACE_DAYS):
            family["fee_status"] = "OVERDUE"
        else:
            family["fee_status"] = "CURRENT"
    else:
        family["fee_status"] = "CURRENT"


def charge_family(family, amount_cents):
    prev = family["fee_balance_cents"]
    family["fee_balance_cents"] = prev + amount_cents
    if prev == 0 and family["fee_balance_cents"] > 0:
        family["oldest_unpaid_charge_at"] = clock.now_iso()
    if family["fee_balance_cents"] == 0:
        family["oldest_unpaid_charge_at"] = None
    refresh_fee_status(family)
    core.touch(family)


def credit_family(family, amount_cents):
    prev = family["fee_balance_cents"]
    family["fee_balance_cents"] = prev - amount_cents
    if family["fee_balance_cents"] == 0:
        family["oldest_unpaid_charge_at"] = None
    refresh_fee_status(family)
    core.touch(family)


def _parse_date(d):
    y, m, dd = (int(x) for x in d.split("-"))
    from datetime import date
    return date(y, m, dd)


def compute_discount_pct(coop_class, family_id, academic_year_id, created_at_iso,
                          created_seq=None):
    """early_bird 10 + sibling 15, capped at 25."""
    created_dt = clock.parse(created_at_iso)
    start_dt = clock.parse(_parse_date(coop_class["start_date"]).isoformat() + "T00:00:00Z")
    early_bird = created_dt <= start_dt - timedelta(days=EARLY_BIRD_DAYS)

    # "created before this one": compare by creation timestamp, with ties broken by
    # the internal insertion sequence (identifiers are never consulted).
    sibling = False
    new_key = (created_at_iso, created_seq if created_seq is not None else 1 << 62)
    for ce in db.coop_enrollments.values():
        if ce["status"] not in ("CONFIRMED", "COMPLETED"):
            continue
        ce_key = (ce["created_at"], ce.get("_seq", 0))
        if ce_key >= new_key:
            continue
        other_en = db.enrollments.get(ce["enrollment_id"])
        if not other_en or other_en["academic_year_id"] != academic_year_id:
            continue
        other_st = db.students.get(other_en["student_id"])
        if other_st and other_st["family_id"] == family_id:
            sibling = True
            break

    pct = (EARLY_BIRD_PCT if early_bird else 0) + (SIBLING_PCT if sibling else 0)
    return min(pct, DISCOUNT_CAP_PCT)


def compute_fee_cents(coop_class, discount_pct):
    discounted_base = round_half_up_int(
        Decimal(coop_class["fee_base_cents"]) * Decimal(100 - discount_pct) / Decimal(100)
    )
    return discounted_base + coop_class["materials_fee_cents"]


def compute_refund(coop_enrollment, coop_class, drop_reason):
    """coop_refund_waterfall; returns refund_cents integer."""
    fee_cents = coop_enrollment["fee_cents"]
    if drop_reason in ("SCHOOL_CANCEL", "SCHOOL_STANDING"):
        return fee_cents
    # PARENT_INITIATED
    start_date = _parse_date(coop_class["start_date"])
    from datetime import datetime, timezone
    start_dt = datetime(start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc)
    now = clock.now()
    if now < start_dt:
        return max(fee_cents - ADMIN_FEE_CENTS, 0)
    if now < start_dt + timedelta(days=PARTIAL_WINDOW_DAYS):
        return round_half_up_int(
            Decimal(fee_cents - coop_class["materials_fee_cents"]) * Decimal(PARTIAL_REFUND_PCT) / Decimal(100)
        )
    return 0
