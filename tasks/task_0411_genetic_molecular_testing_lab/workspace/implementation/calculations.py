"""Calculation rules (PRD Section 3.7, 3.10, 3.4, 3.8, 3.12)."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

# ---- patient_responsibility constants (PRD 3.7) ----
COINSURANCE_RATE = {
    "MEDICARE": Decimal("0.20"),
    "COMMERCIAL": Decimal("0.10"),
    "SELF_PAY": Decimal("1.00"),
}
ASSISTANCE_CAP_CENTS = 50000          # $500.00 estimate cap
ASSISTANCE_CAP_CENTS_FINAL = 60000    # $600.00 final cap
INCIDENTAL_SURCHARGE_CENTS = 7500     # $75.00

# ---- pathogenicity scoring constants (PRD 3.10) ----
PATHOGENICITY_POINTS = {
    "BENIGN": 0,
    "LIKELY_BENIGN": 1,
    "VUS": 2,
    "LIKELY_PATHOGENIC": 4,
    "PATHOGENIC": 8,
}
INCIDENTAL_WEIGHT = 2
MAX_PER_GENE_PTS = 8

# ---- QNS minimums (PRD 3.4) ----
QNS_MIN_NG = {
    "BLOOD": 50,
    "SALIVA": 30,
    "TISSUE": 100,
}

# ---- incidental findings policy (PRD 3.8) ----
ADULT_AGE_YEARS = 18


def _round_half_up_cents(value):
    """Round a Decimal to whole integer cents, half-up."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _gross_capped(base_cents, payer):
    """Compute gross (single rounding) then clamp to ASSISTANCE_CAP_CENTS."""
    rate = COINSURANCE_RATE[payer]
    gross = _round_half_up_cents(Decimal(int(base_cents)) * rate)
    capped = min(gross, ASSISTANCE_CAP_CENTS)
    return capped


def patient_responsibility_estimate(base_cents, payer):
    """ESTIMATE variant (PRD 3.7): gross -> cap. No incidental surcharge."""
    return _gross_capped(base_cents, payer)


def patient_responsibility_final(base_cents, payer, incidental_disclosed):
    """FINAL variant (PRD 3.7): gross -> $500 cap -> +surcharge (if disclosed)
    -> re-clamp to $600 final cap. Evaluation order pinned."""
    capped = _gross_capped(base_cents, payer)
    surcharge = INCIDENTAL_SURCHARGE_CENTS if incidental_disclosed else 0
    return min(capped + surcharge, ASSISTANCE_CAP_CENTS_FINAL)


def qns_sufficient(specimen_type, quantity_ng):
    """PRD 3.4: sufficient IFF quantity_ng >= QNS_MIN_NG[type] (inclusive)."""
    minimum = QNS_MIN_NG[specimen_type]
    return quantity_ng >= minimum


def patient_age_years(patient_dob, clock_iso):
    """Whole years between patient_dob (YYYY-MM-DD) and the lab clock (PRD 3.8).

    age = floor((clock - dob) days / 365.2425).
    """
    try:
        dob = datetime.strptime(patient_dob, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None
    s = clock_iso
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    now = datetime.fromisoformat(s)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    delta_days = (now - dob).total_seconds() / 86400.0
    import math
    return math.floor(delta_days / 365.2425)


def incidental_admitted(variant, consent_opt_in, gene_is_acmg_reportable, age_years):
    """PRD 3.8 incidental-findings policy for a single incidental variant.

    Applies only to incidental variants whose classification is
    LIKELY_PATHOGENIC or PATHOGENIC. Returns True if the finding is admitted.
    """
    classification = variant.get("classification")
    if classification not in ("LIKELY_PATHOGENIC", "PATHOGENIC"):
        return False
    if not consent_opt_in:
        return False
    is_minor = age_years is not None and age_years < ADULT_AGE_YEARS
    if not is_minor:
        return True
    # Minor: admit only PATHOGENIC ACMG findings.
    return gene_is_acmg_reportable and classification == "PATHOGENIC"


def pathogenicity_risk_index(classified_variants, gene_count):
    """PRD 3.10: sum weighted points (created_at ASC), normalize, round once.

    classified_variants: list of variant dicts with classification not in
    {UNCLASSIFIED, RECLASSIFIED}, already ordered by (created_at, id).
    """
    raw = 0
    for v in classified_variants:
        pts = PATHOGENICITY_POINTS.get(v.get("classification"), 0)
        if v.get("is_incidental"):
            pts = pts * INCIDENTAL_WEIGHT
        raw += pts
    denom = max(gene_count, 1) * MAX_PER_GENE_PTS
    ratio = Decimal(raw) / Decimal(denom)
    if ratio > Decimal(1):
        ratio = Decimal(1)
    index = _round_half_up_cents(ratio * Decimal(100))
    return index


# ---- interval overlap geometries (PRD 3.12) ----
def _to_dt(iso):
    s = iso
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def sequencer_runs_conflict(new_start, new_end, existing_start, existing_end, buffer_minutes):
    """PRD 3.12: closed interval + turnaround buffer.

    clear IFF (new_end + B <= existing_start) OR (existing_end + B <= new_start).
    conflict = NOT clear.
    """
    ns, ne = _to_dt(new_start), _to_dt(new_end)
    es, ee = _to_dt(existing_start), _to_dt(existing_end)
    from datetime import timedelta
    b = timedelta(minutes=buffer_minutes)
    clear = (ne + b <= es) or (ee + b <= ns)
    return not clear


def counselor_slots_conflict(new_start, new_end, existing_start, existing_end):
    """PRD 3.12: half-open interval, no buffer.

    conflict IFF (new_start < existing_end) AND (existing_start < new_end).
    Adjacency (new_start == existing_end) is NOT a conflict.
    """
    ns, ne = _to_dt(new_start), _to_dt(new_end)
    es, ee = _to_dt(existing_start), _to_dt(existing_end)
    return (ns < ee) and (es < ne)
