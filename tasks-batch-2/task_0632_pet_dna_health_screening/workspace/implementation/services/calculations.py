"""Deterministic calculations (SCAFFOLD §1.3 / PRD §3.3, §3.4, §3.6, §3.7)."""
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

# --- genotyping_qc_score constants (SCAFFOLD §1.3) ---
W_CALL = Decimal("0.6")
W_CONTAM = Decimal("0.3")
W_HET = Decimal("0.1")
HET_TARGET = Decimal("0.35")
CALL_GATE = Decimal("0.85")
QC_QNS_FLOOR = Decimal("60.00")

# --- breed_ancestry constant ---
TARGET_SUM = Decimal("100.00")

# --- subscription proration constants ---
PREMIUM_ANNUAL_FEE_CENTS = 19900
FLOOR_CENTS = 0

# --- kinship constants ---
TOTAL_AUTOSOMAL_CM = Decimal("2500.0")
PHASE_FACTOR = Decimal("0.98")


def _round_half_up_2(d):
    return Decimal(d).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _clamp(value, lo, hi):
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


def compute_qc_score_and_outcome(call_rate, het_rate, contamination):
    """Returns (qc_score: float 2dp, outcome: str). PRD §3.3.

    het_consistency = clamp(1 - abs(het_rate - HET_TARGET)/HET_TARGET, 0, 1)
    raw = 100 * (W_CALL*call_rate + W_CONTAM*(1-contamination) + W_HET*het_consistency)
    qc_score = round_half_up(raw, 2)
    Outcome gate (fixed order):
      1. call_rate < CALL_GATE  -> FAILED
      2. qc_score < QC_QNS_FLOOR -> QNS
      3. else -> PASS
    """
    cr = Decimal(str(call_rate))
    hr = Decimal(str(het_rate))
    cn = Decimal(str(contamination))

    het_consistency = _clamp(
        Decimal("1") - (abs(hr - HET_TARGET) / HET_TARGET),
        Decimal("0"),
        Decimal("1"),
    )
    raw = Decimal("100") * (
        W_CALL * cr + W_CONTAM * (Decimal("1") - cn) + W_HET * het_consistency
    )
    qc_score = _round_half_up_2(raw)

    if cr < CALL_GATE:
        outcome = "FAILED"
    elif qc_score < QC_QNS_FLOOR:
        outcome = "QNS"
    else:
        outcome = "PASS"

    return float(qc_score), outcome


def compute_breed_composition(breed_segments):
    """PRD §3.4. breed_segments: list of {breed, match_cm}.

    total_cm = sum(match_cm); each pct = round_half_up(match_cm/total*100, 2)
    in request array order. remainder = round_half_up(100 - sum(pcts), 2)
    assigned to the single segment with the largest match_cm (tie -> earliest
    array index). Empty array -> []."""
    if not breed_segments:
        return []

    decs = [Decimal(str(seg["match_cm"])) for seg in breed_segments]
    total = sum(decs)
    if total == 0:
        # Avoid division by zero; treat as no composition.
        return []

    pcts = [_round_half_up_2(d / total * Decimal("100")) for d in decs]
    remainder = _round_half_up_2(TARGET_SUM - sum(pcts))

    # Largest match_cm wins the remainder; tie-break earliest array index.
    largest_idx = 0
    largest_cm = decs[0]
    for i in range(1, len(decs)):
        if decs[i] > largest_cm:
            largest_cm = decs[i]
            largest_idx = i
    pcts[largest_idx] = pcts[largest_idx] + remainder

    return [
        {"breed": breed_segments[i]["breed"], "pct": float(pcts[i])}
        for i in range(len(breed_segments))
    ]


def compute_relationship_pct(shared_cm, confirmed=False):
    """PRD §3.6.
    ESTIMATED: round_half_up(shared_cm / 2500.0 * 100, 2)
    CONFIRMED: round_half_up(shared_cm * 0.98 / 2500.0 * 100, 2)
    """
    cm = Decimal(str(shared_cm))
    if confirmed:
        raw = cm * PHASE_FACTOR / TOTAL_AUTOSOMAL_CM * Decimal("100")
    else:
        raw = cm / TOTAL_AUTOSOMAL_CM * Decimal("100")
    return float(_round_half_up_2(raw))


def compute_upgrade_charge(basic_sub, elapsed_days):
    """PRD §3.7 successor proration.

    remaining_days = basic.term_days - elapsed_days
    unused_credit_cents = floor(basic.annual_fee_cents * remaining_days / basic.term_days)
    last_charge_cents = PREMIUM_ANNUAL_FEE_CENTS - unused_credit_cents (floor at 0)
    """
    term_days = basic_sub["term_days"]
    remaining_days = term_days - elapsed_days
    # remaining_days lies between 0 and term_days.
    if remaining_days < 0:
        remaining_days = 0
    if remaining_days > term_days:
        remaining_days = term_days

    numerator = Decimal(basic_sub["annual_fee_cents"]) * Decimal(remaining_days)
    unused_credit = int(
        (numerator / Decimal(term_days)).to_integral_value(rounding=ROUND_FLOOR)
    )
    charge = PREMIUM_ANNUAL_FEE_CENTS - unused_credit
    if charge < FLOOR_CENTS:
        charge = FLOOR_CENTS
    return charge
