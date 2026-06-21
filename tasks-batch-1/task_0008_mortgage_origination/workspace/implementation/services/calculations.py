"""Calculation rules per SCAFFOLD §1.3 and PRD §3.

All money is integer cents; all ratios use Decimal with explicit ROUND_HALF_UP.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import db


DEFAULT_UNDERWRITING_RATE_BPS = 700
ROUNDING_DTI_PLACES = 4
ROUNDING_LTV_PLACES = 4
ROUNDING_APR_PERCENT_PLACES = 3
APR_NEWTON_TOLERANCE = Decimal("1e-8")
APR_MAX_ITERATIONS = 50
EXT_FEE_TIER_BPS = {7: 5, 15: 10, 30: 25}
LE_WAITING_DAYS = 7
CD_WAITING_DAYS = 3
APR_TOLERANCE_BPS = Decimal("12.5")


# --------------------------- Helpers ---------------------------
def _quant(places: int) -> Decimal:
    if places == 0:
        return Decimal("1")
    return Decimal("1").scaleb(-places)  # 10**-places


def round_half_up_decimal(value: Decimal, places: int) -> Decimal:
    return value.quantize(_quant(places), rounding=ROUND_HALF_UP)


def round_half_up_int(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _monthly_payment_cents(principal_cents: int, monthly_rate: Decimal, n_months: int) -> int:
    """Standard amortization formula: P * r / (1 - (1+r)^-n), rounded half-up to cents.

    monthly_rate is a Decimal already (rate_bps / 10000 / 12).
    """
    if monthly_rate == 0:
        # Degenerate: zero rate → flat division.
        return round_half_up_int(Decimal(principal_cents) / Decimal(n_months))
    one_plus_r = Decimal(1) + monthly_rate
    # (1+r)^-n via Decimal power. Decimal supports ** with Decimal/int.
    factor = one_plus_r ** (-n_months)
    denom = Decimal(1) - factor
    numerator = Decimal(principal_cents) * monthly_rate
    raw = numerator / denom
    return round_half_up_int(raw)


# --------------------------- DTI ---------------------------
def compute_dti(loan_app: dict[str, Any], applicant: dict[str, Any]) -> tuple[Decimal, Decimal]:
    """Compute (front_end_dti, back_end_dti) per §1.3 dti_ratio.

    Uses Applicant.annual_income_cents only — never a verified value.
    Uses the application's ACTIVE RateLock's rate when present, else 7.00% default.
    """
    annual_income_cents = int(applicant["annual_income_cents"])
    monthly_income_cents = annual_income_cents // 12  # floor to integer cents
    if monthly_income_cents <= 0:
        # Avoid division by zero — surface as huge ratio so callers naturally reject.
        # Per spec there is no explicit error for this; treat as ratio that fails any cap.
        return Decimal("999999.9999"), Decimal("999999.9999")

    # Find an ACTIVE rate lock on the application (lazy expiry treated as EXPIRED).
    rate_bps = _active_lock_rate_bps(loan_app["id"])
    if rate_bps is None:
        rate_bps = DEFAULT_UNDERWRITING_RATE_BPS
    monthly_rate = Decimal(rate_bps) / Decimal(10_000) / Decimal(12)

    pi_cents = _monthly_payment_cents(
        int(loan_app["requested_loan_amount_cents"]),
        monthly_rate,
        int(loan_app["loan_term_months"]),
    )
    housing_payment_cents = pi_cents

    front_raw = Decimal(housing_payment_cents) / Decimal(monthly_income_cents)
    back_raw = Decimal(housing_payment_cents + int(applicant["monthly_debt_cents"])) / Decimal(
        monthly_income_cents
    )
    front = round_half_up_decimal(front_raw, ROUNDING_DTI_PLACES)
    back = round_half_up_decimal(back_raw, ROUNDING_DTI_PLACES)
    return front, back


def _active_lock_rate_bps(application_id: str) -> int | None:
    """Return locked_rate_bps of the application's ACTIVE (and not lazily-expired) lock."""
    lock = _active_lock(application_id)
    if lock is None:
        return None
    return int(lock["locked_rate_bps"])


def _active_lock(application_id: str) -> dict[str, Any] | None:
    """Return the application's ACTIVE rate lock if any, treating lazily-past-expiry as EXPIRED."""
    now = db.utcnow()
    for lk in db.rate_locks.values():
        if lk["application_id"] != application_id:
            continue
        if lk["status"] != "ACTIVE":
            continue
        # Lazy expiry check.
        expires = db.parse_ts(lk["expires_at"])
        if now >= expires:
            continue
        return lk
    return None


# --------------------------- LTV ---------------------------
def compute_ltv_provisional(loan_app: dict[str, Any]) -> Decimal:
    requested = Decimal(int(loan_app["requested_loan_amount_cents"]))
    pv = Decimal(int(loan_app["property_value_cents"]))
    if pv == 0:
        return Decimal("999999.9999")
    return round_half_up_decimal(requested / pv, ROUNDING_LTV_PLACES)


def compute_ltv_final(loan_app: dict[str, Any], appraised_value_cents: int) -> Decimal:
    requested = Decimal(int(loan_app["requested_loan_amount_cents"]))
    denom_cents = min(int(loan_app["property_value_cents"]), int(appraised_value_cents))
    if denom_cents <= 0:
        return Decimal("999999.9999")
    return round_half_up_decimal(requested / Decimal(denom_cents), ROUNDING_LTV_PLACES)


# --------------------------- APR ---------------------------
def compute_apr_percent(loan_app: dict[str, Any], *, variant: str) -> Decimal | None:
    """Compute provisional or final APR percent (3-decimal, round_half_up).

    variant: "provisional" | "final".
    Requires an ACTIVE rate lock on the application; returns None if none exists.
    """
    lock = _active_lock(loan_app["id"])
    if lock is None:
        return None
    requested_cents = int(loan_app["requested_loan_amount_cents"])
    n = int(loan_app["loan_term_months"])
    locked_rate_bps = int(lock["locked_rate_bps"])
    monthly_rate = Decimal(locked_rate_bps) / Decimal(10_000) / Decimal(12)

    prepaid = 0
    if variant == "final":
        prepaid = int(lock.get("extension_fee_cents", 0))
    effective_principal_cents = requested_cents - prepaid

    monthly_payment_cents = _monthly_payment_cents(requested_cents, monthly_rate, n)

    # Newton-Raphson on f(apr) = sum_{k=1..n} pmt/(1+apr/12)^k - eff_principal.
    apr = Decimal(locked_rate_bps) / Decimal(10_000)  # seed = nominal annual rate as decimal
    pmt = Decimal(monthly_payment_cents)
    eff = Decimal(effective_principal_cents)
    for _ in range(APR_MAX_ITERATIONS):
        r = apr / Decimal(12)
        one_plus_r = Decimal(1) + r
        # f and f' computed via closed forms for geometric series.
        if r == 0:
            f = pmt * Decimal(n) - eff
            # df/d(apr) when r=0 — use derivative formula approximation.
            # Sum_{k=1..n} k * pmt = pmt * n(n+1)/2 with respect to r;
            # d r / d apr = 1/12.
            f_prime = -pmt * Decimal(n) * Decimal(n + 1) / Decimal(2) / Decimal(12)
        else:
            # Annuity factor: a = (1 - (1+r)^-n) / r
            factor_neg_n = one_plus_r ** (-n)
            a = (Decimal(1) - factor_neg_n) / r
            f = pmt * a - eff
            # da/dr = ( n*(1+r)^(-n-1) * r - (1 - (1+r)^-n) ) / r^2
            factor_neg_n_minus_1 = one_plus_r ** (-(n + 1))
            da_dr = (Decimal(n) * factor_neg_n_minus_1 * r - (Decimal(1) - factor_neg_n)) / (r * r)
            # df/dapr = pmt * da/dr * d r / d apr = pmt * da/dr * (1/12)
            f_prime = pmt * da_dr / Decimal(12)
        if f_prime == 0:
            break
        step = f / f_prime
        apr = apr - step
        if abs(step) < APR_NEWTON_TOLERANCE:
            break

    apr_4dp = round_half_up_decimal(apr, 4)
    apr_pct = apr_4dp * Decimal(100)
    return round_half_up_decimal(apr_pct, ROUNDING_APR_PERCENT_PLACES)


# --------------------------- Rate-lock extension fees ---------------------------
def per_extension_fee_cents(requested_loan_amount_cents: int, extend_days: int) -> int:
    tier_bps = EXT_FEE_TIER_BPS[extend_days]
    raw = Decimal(requested_loan_amount_cents) * Decimal(tier_bps) / Decimal(10_000)
    return round_half_up_int(raw)


# --------------------------- TRID timeline ---------------------------
def trid_earliest_consummation(application_id: str) -> str | None:
    """Recompute earliest_consummation_at per §1.3 trid_timeline_calc.

    Returns ISO 8601 UTC string or None.
    """
    le_first = None
    cd_last = None
    for d in db.disclosures.values():
        if d["application_id"] != application_id:
            continue
        # Per PRD §3.7: "Only DELIVERED disclosures count (drafts and
        # superseded rows do not)". Acknowledgement is a downstream state of a
        # DELIVERED disclosure and must still participate — otherwise an
        # ACKNOWLEDGED CD (required for CLEAR_TO_CLOSE) would not contribute
        # to its own timeline. SUPERSEDED rows do not participate.
        if d["status"] not in ("DELIVERED", "ACKNOWLEDGED"):
            continue
        if d.get("delivered_at") is None:
            continue
        if d["disclosure_type"] == "LOAN_ESTIMATE":
            # Earliest by delivered_at, then created_at, then _seq.
            key = (d["delivered_at"], d["created_at"], d.get("_seq", 0))
            if le_first is None:
                le_first = d
            else:
                cur = (le_first["delivered_at"], le_first["created_at"], le_first.get("_seq", 0))
                if key < cur:
                    le_first = d
        elif d["disclosure_type"] == "CLOSING_DISCLOSURE":
            # Latest by delivered_at, then created_at, then _seq.
            key = (d["delivered_at"], d["created_at"], d.get("_seq", 0))
            if cd_last is None:
                cd_last = d
            else:
                cur = (cd_last["delivered_at"], cd_last["created_at"], cd_last.get("_seq", 0))
                if key > cur:
                    cd_last = d

    if le_first is None or cd_last is None:
        return None

    le_floor = db.parse_ts(le_first["delivered_at"]) + timedelta(days=LE_WAITING_DAYS)
    cd_floor = db.parse_ts(cd_last["delivered_at"]) + timedelta(days=CD_WAITING_DAYS)
    earliest = max(le_floor, cd_floor)
    return db.fmt_ts(earliest)


# --------------------------- CD redisclose check ---------------------------
def cd_redisclose_check(
    application_id: str, new_apr_pct: Decimal, current_id: str | None = None
) -> bool:
    """Compare new APR vs the immediately prior DELIVERED-or-SUPERSEDED CD.

    Returns True iff delta > 12.5 bps. Boundary exactly 12.5 = False.
    current_id, if given, excludes the disclosure being delivered (which has
    already been flipped to DELIVERED by the caller).
    """
    prior = None
    for d in db.disclosures.values():
        if current_id is not None and d["id"] == current_id:
            continue
        if d["application_id"] != application_id:
            continue
        if d["disclosure_type"] != "CLOSING_DISCLOSURE":
            continue
        # Scaffold §1.3 cd_redisclose_check: prior is the immediately-prior
        # DELIVERED-or-SUPERSEDED CD. ACKNOWLEDGED is a downstream state of
        # DELIVERED so we include it too — the comparison set is "any CD that
        # has been delivered" (anything with a delivered_at), regardless of
        # whether it was later acknowledged or superseded.
        if d["status"] not in ("DELIVERED", "ACKNOWLEDGED", "SUPERSEDED"):
            continue
        if d.get("delivered_at") is None:
            continue
        # Latest by delivered_at, then created_at, then _seq.
        # BUT: never compare against the new disclosure being delivered itself
        # (the caller passes new_apr_pct, and this CD's apr_at_issuance may
        # already be set when called from deliver). We exclude by id later.
        key = (d["delivered_at"], d["created_at"], d.get("_seq", 0))
        if prior is None:
            prior = d
        else:
            cur = (prior["delivered_at"], prior["created_at"], prior.get("_seq", 0))
            if key > cur:
                prior = d

    if prior is None:
        return False
    prior_apr = Decimal(str(prior["apr_at_issuance"]))
    delta_pct = (new_apr_pct - prior_apr).copy_abs()
    # APR is in percent; bps = percent * 100.
    delta_bps = delta_pct * Decimal(100)
    return delta_bps > APR_TOLERANCE_BPS
