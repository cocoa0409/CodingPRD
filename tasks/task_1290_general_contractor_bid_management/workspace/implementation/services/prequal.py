"""Prequalification scoring + lazy expiry + subcontractor status derivation."""
from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta

from db import DB, CLOCK, touch

W_FINANCIAL = Decimal("0.40")
W_SAFETY = Decimal("0.35")
W_BONDING = Decimal("0.25")
REVENUE_REFERENCE_CENTS = Decimal("5000000000")
BONDING_REFERENCE_CENTS = Decimal("2000000000")
EMR_FLOOR = Decimal("0.70")
EMR_CEILING = Decimal("1.20")
EMR_HARD_FAIL = Decimal("1.25")
PREQUAL_PASS_THRESHOLD = Decimal("70")

TWO_PLACES = Decimal("0.01")


def _round2(value: Decimal) -> Decimal:
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def _component(value_cents: Decimal, ref_cents: Decimal) -> Decimal:
    ratio = (value_cents / ref_cents) * Decimal("100")
    if ratio > Decimal("100"):
        ratio = Decimal("100")
    return _round2(ratio)


def _safety_component(emr: Decimal) -> Decimal:
    if emr <= EMR_FLOOR:
        return Decimal("100.00")
    if emr >= EMR_CEILING:
        return Decimal("0.00")
    return _round2(Decimal("100") - (emr - EMR_FLOOR) * Decimal("200"))


def prequal_score(revenue_cents: int, emr, bonding_capacity_cents: int, variant: str) -> float:
    """Compute the prequal score. Components rounded 2dp half-up BEFORE weighting;
    weighted total rounded 2dp half-up. Verified variant applies the EMR hard fail."""
    emr_d = Decimal(str(emr))
    if variant == "verified" and emr_d >= EMR_HARD_FAIL:
        return 0.00
    financial = _component(Decimal(revenue_cents), REVENUE_REFERENCE_CENTS)
    safety = _safety_component(emr_d)
    bonding = _component(Decimal(bonding_capacity_cents), BONDING_REFERENCE_CENTS)
    total = _round2(W_FINANCIAL * financial + W_SAFETY * safety + W_BONDING * bonding)
    return float(total)


def apply_lazy_expiry(app_row) -> bool:
    """APPROVED -> EXPIRED when now >= expires_at. Returns True if it flipped."""
    if app_row.get("status") == "APPROVED" and app_row.get("expires_at"):
        expires = app_row["_expires_at_dt"]
        if CLOCK.now() >= expires:
            app_row["status"] = "EXPIRED"
            touch(app_row)
            return True
    return False


def live_application_exists(subcontractor_id: str, exclude_id: str = None) -> bool:
    """True when another application is SUBMITTED, or APPROVED with expires_at > now."""
    for app in DB.prequal_applications.values():
        if app["subcontractor_id"] != subcontractor_id:
            continue
        if exclude_id and app["id"] == exclude_id:
            continue
        apply_lazy_expiry(app)
        if app["status"] == "SUBMITTED":
            return True
        if app["status"] == "APPROVED" and app["_expires_at_dt"] > CLOCK.now():
            return True
    return False


def has_approved_prequal(subcontractor_id: str) -> bool:
    """True when the subcontractor holds an APPROVED application with expires_at > now
    (lazy expiry applied first)."""
    for app in DB.prequal_applications.values():
        if app["subcontractor_id"] != subcontractor_id:
            continue
        apply_lazy_expiry(app)
        if app["status"] == "APPROVED" and app["_expires_at_dt"] > CLOCK.now():
            return True
    return False


def recompute_subcontractor_status(subcontractor_id: str) -> None:
    """Precedence walk ignoring EXPIRED: APPROVED (non-expired) > SUBMITTED > REJECTED > NONE."""
    sub = DB.subcontractors.get(subcontractor_id)
    if sub is None:
        return
    approved = False
    submitted = False
    rejected = False
    for app in DB.prequal_applications.values():
        if app["subcontractor_id"] != subcontractor_id:
            continue
        apply_lazy_expiry(app)
        st = app["status"]
        if st == "EXPIRED":
            continue
        if st == "APPROVED" and app["_expires_at_dt"] > CLOCK.now():
            approved = True
        elif st == "SUBMITTED":
            submitted = True
        elif st == "REJECTED":
            rejected = True
    if approved:
        new_status = "APPROVED"
    elif submitted:
        new_status = "SUBMITTED"
    elif rejected:
        new_status = "REJECTED"
    else:
        new_status = "NONE"
    if sub["current_prequal_status"] != new_status:
        sub["current_prequal_status"] = new_status
        touch(sub)


def expires_at_from(approved_at_dt):
    return approved_at_dt + timedelta(days=365)
