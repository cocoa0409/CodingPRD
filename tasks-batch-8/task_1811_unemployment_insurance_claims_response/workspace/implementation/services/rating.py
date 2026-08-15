"""experience_rating_projection (§1.3 / PRD §3.7) plus model snapshot hashing
and input-invalidation helpers.

Pinned rounding order: the ratio is an exact Fraction and is never rounded
before the tier lookup; the rate is integer basis points; liability is
computed from the integer rate and floored to whole cents."""
import hashlib
from fractions import Fraction

from db import STORE
from services.core import touch

RATE_TABLE = [
    (Fraction(-5, 100), 60),
    (Fraction(0, 1), 120),
    (Fraction(2, 100), 180),
    (Fraction(4, 100), 270),
    (Fraction(6, 100), 360),
    (Fraction(8, 100), 450),
    (Fraction(1, 1), 540),
]
WATCH_SURCHARGE_BPS = 20
SANCTION_SURCHARGE_BPS = 50
RATE_CAP_BPS = 540


def benefit_charges(employer_id):
    """Sum of charge line amounts on the employer's claims with status
    PENDING or SUSTAINED (REVERSED and WAIVED excluded)."""
    total = 0
    for line in STORE.charge_lines.values():
        if line["status"] not in ("PENDING", "SUSTAINED"):
            continue
        claim = STORE.claims.get(line["claim_id"])
        if claim is not None and claim["employer_id"] == employer_id:
            total += line["amount_cents"]
    return total


def _ratio(emp, variant, charges):
    payroll = emp["taxable_payroll_cents"]
    numerator = emp["reserve_balance_cents"] if variant == "RESERVE_RATIO" else charges
    if payroll == 0:
        # Degenerate denominator: zero numerator tiers as a zero ratio, any
        # nonzero numerator lands in the top band.
        return Fraction(0, 1) if numerator == 0 else Fraction(10 ** 9, 1)
    return Fraction(numerator, payroll)


def project(emp, variant):
    """Returns (projected_rate_bps, projected_liability_cents)."""
    charges = benefit_charges(emp["id"])
    ratio = _ratio(emp, variant, charges)
    base_rate = RATE_CAP_BPS  # ratios above the final ceiling fall in the top band
    for max_ratio, rate_bps in RATE_TABLE:
        if ratio <= max_ratio:
            base_rate = rate_bps
            break
    posture = emp["compliance_posture"]
    if posture == "SANCTIONED":
        base_rate += SANCTION_SURCHARGE_BPS
    elif posture == "WATCH":
        base_rate += WATCH_SURCHARGE_BPS
    rate = min(RATE_CAP_BPS, base_rate)
    liability = (rate * emp["taxable_payroll_cents"]) // 10000  # floor
    return rate, liability


def snapshot_hash(emp, variant):
    """Hash of the charged inputs at computation time; recompute at finalize
    and compare to detect stale inputs (ERR_MODEL_INPUT_STALE)."""
    charges = benefit_charges(emp["id"])
    material = "|".join([
        variant,
        str(charges),
        str(emp["reserve_balance_cents"]),
        str(emp["taxable_payroll_cents"]),
        emp["compliance_posture"],
    ])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def refresh_current_rate(emp):
    """The projection's output refreshes employer.current_tax_rate_bps under
    the employer's own merit_rating_method. Re-evaluation is a mutation of
    the employer aggregate (§2.4), so it bumps the employer version."""
    rate, _liability = project(emp, emp["merit_rating_method"])
    emp["current_tax_rate_bps"] = rate
    touch(emp)


def supersede_models(employer_id, include_finalized=False):
    """Derived-input invalidation: DRAFT models leave DRAFT for SUPERSEDED
    when a source charge/payroll input changes; FINALIZED models are
    superseded only by a later OFFICIAL finalize or a charge reconciliation /
    reversal event (include_finalized=True)."""
    for m in STORE.rating_models.values():
        if m["employer_id"] != employer_id:
            continue
        if m["status"] == "DRAFT" or (include_finalized and m["status"] == "FINALIZED"):
            m["status"] = "SUPERSEDED"
            touch(m)
