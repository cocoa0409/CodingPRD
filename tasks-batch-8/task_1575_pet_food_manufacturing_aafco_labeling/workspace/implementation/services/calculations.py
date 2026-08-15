"""Calculation services: ME, AAFCO check, GA composite, deviation, yield, fees,
complaint risk, lot codes. All rounding is round-half-up per PRD section 2.6."""

from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta

from db import store, iso_format
import errors


def _d(x):
    """Coerce to Decimal via string to avoid binary float artifacts."""
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def round_half_up(value, places: int) -> Decimal:
    q = Decimal(1).scaleb(-places)
    return _d(value).quantize(q, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# me_calculation
# ---------------------------------------------------------------------------
ASH_PCT_ASSUMED = Decimal("7.0")
PROTEIN_GE = Decimal("5.7")
FAT_GE = Decimal("9.4")
CARB_GE = Decimal("4.1")
DIGEST_BASE = Decimal("87.8")
DIGEST_FIBER_COEF_FORMULATION = Decimal("0.88")
DIGEST_FIBER_COEF_LAB = Decimal("0.44")


def compute_me(protein_pct, fat_pct, fiber_pct, moisture_pct, profile_basis):
    """Modified Atwater. Returns Decimal at 1 decimal place."""
    p = _d(protein_pct)
    f = _d(fat_pct)
    fib = _d(fiber_pct)
    m = _d(moisture_pct)
    carb = Decimal("100") - p - f - fib - m - ASH_PCT_ASSUMED
    ge = p * PROTEIN_GE + f * FAT_GE + carb * CARB_GE
    coef = DIGEST_FIBER_COEF_LAB if profile_basis == "LAB_ANALYSIS" else DIGEST_FIBER_COEF_FORMULATION
    denom = max(Decimal("100") - m, Decimal("1.0"))
    pct_digest = DIGEST_BASE - coef * fib * (Decimal("100") / denom)
    me = ge * (pct_digest / Decimal("100")) * Decimal("10")
    return round_half_up(me, 1)


# ---------------------------------------------------------------------------
# aafco_profile_check
# ---------------------------------------------------------------------------
AAFCO_MIN = {
    ("DOG", "ADULT"): {"protein": Decimal("18.0"), "fat": Decimal("5.5"),
                       "calcium": Decimal("0.6"), "phosphorus": Decimal("0.5")},
    ("DOG", "GROWTH"): {"protein": Decimal("22.5"), "fat": Decimal("8.5"),
                        "calcium": Decimal("1.0"), "phosphorus": Decimal("0.8")},
    ("CAT", "ADULT"): {"protein": Decimal("26.0"), "fat": Decimal("9.0"),
                       "calcium": Decimal("0.6"), "phosphorus": Decimal("0.5")},
    ("CAT", "GROWTH"): {"protein": Decimal("30.0"), "fat": Decimal("9.0"),
                        "calcium": Decimal("1.0"), "phosphorus": Decimal("0.8")},
}
ME_NORMALIZATION_REF = Decimal("4000")


def _aafco_stage_group(life_stage: str) -> str:
    if life_stage == "ADULT_MAINTENANCE":
        return "ADULT"
    # GROWTH, GESTATION_LACTATION, ALL_LIFE_STAGES -> growth floors
    return "GROWTH"


def compute_aafco_compliance(species, life_stage, me_kcal_per_kg,
                             protein_pct, fat_pct, calcium_pct, phosphorus_pct):
    """Return 'COMPLIANT' or 'DEFICIENT'. Comparisons at 2dp, round_half_up before compare."""
    stage_group = _aafco_stage_group(life_stage)
    floors = AAFCO_MIN[(species, stage_group)]
    me = _d(me_kcal_per_kg)
    scale = Decimal("1")
    if me > ME_NORMALIZATION_REF:
        scale = me / ME_NORMALIZATION_REF
    values = {
        "protein": protein_pct,
        "fat": fat_pct,
        "calcium": calcium_pct,
        "phosphorus": phosphorus_pct,
    }
    for nutrient in ("protein", "fat", "calcium", "phosphorus"):
        floor = round_half_up(floors[nutrient] * scale, 2)
        actual = round_half_up(values[nutrient], 2)
        if actual < floor:
            return "DEFICIENT"
    return "COMPLIANT"


# ---------------------------------------------------------------------------
# ga_composite_calculation + ga_deviation_index
# ---------------------------------------------------------------------------
SAMPLE_TYPE_ORDER = {"FIRST": 0, "MIDDLE": 1, "LAST": 2, "COMPOSITE": 3}
WEIGHTS = {"FIRST": Decimal("1"), "MIDDLE": Decimal("1"), "LAST": Decimal("1"),
           "COMPOSITE": Decimal("1.25")}


def compute_per_sample_verdict(sample, nutrient_profile):
    """WITHIN_LABEL or LABEL_VIOLATION per PRD 3.6."""
    if nutrient_profile is None:
        return "PENDING"
    p_ok = _d(sample["measured_protein_pct"]) >= _d(nutrient_profile["crude_protein_min_pct"])
    f_ok = _d(sample["measured_fat_pct"]) >= _d(nutrient_profile["crude_fat_min_pct"])
    fib_ok = _d(sample["measured_fiber_pct"]) <= _d(nutrient_profile["crude_fiber_max_pct"])
    m_ok = _d(sample["measured_moisture_pct"]) <= _d(nutrient_profile["moisture_max_pct"])
    return "WITHIN_LABEL" if (p_ok and f_ok and fib_ok and m_ok) else "LABEL_VIOLATION"


def compute_ga_composite(samples):
    """Pinned rounding: round3 each weighted contribution, sum, divide by unrounded
    weight sum, round2 the quotient. samples: list of dicts with measured_* fields.
    Returns dict of 4 composites as Decimals at 2dp."""
    fields = [
        ("measured_protein_pct", "composite_protein_pct"),
        ("measured_fat_pct", "composite_fat_pct"),
        ("measured_fiber_pct", "composite_fiber_pct"),
        ("measured_moisture_pct", "composite_moisture_pct"),
    ]
    total_weight = sum(WEIGHTS[s["sample_type"]] for s in samples)
    out = {}
    for measured_key, out_key in fields:
        contributions = []
        for s in samples:
            w = WEIGHTS[s["sample_type"]]
            contrib = round_half_up(_d(s[measured_key]) * w, 3)
            contributions.append(contrib)
        composite = round_half_up(sum(contributions) / total_weight, 2)
        out[out_key] = composite
    return out


def compute_deviation_index(composites, nutrient_profile):
    """3*protein_deficit + 2*fat_deficit + 1.5*fiber_excess + 1*moisture_excess.
    Returns (deviation_index Decimal at 2dp, label_compliance str)."""
    protein_deficit = max(Decimal("0"),
                          _d(nutrient_profile["crude_protein_min_pct"]) - composites["composite_protein_pct"])
    fat_deficit = max(Decimal("0"),
                      _d(nutrient_profile["crude_fat_min_pct"]) - composites["composite_fat_pct"])
    fiber_excess = max(Decimal("0"),
                       composites["composite_fiber_pct"] - _d(nutrient_profile["crude_fiber_max_pct"]))
    moisture_excess = max(Decimal("0"),
                          composites["composite_moisture_pct"] - _d(nutrient_profile["moisture_max_pct"]))
    idx = (Decimal("3.0") * protein_deficit
           + Decimal("2.0") * fat_deficit
           + Decimal("1.5") * fiber_excess
           + Decimal("1.0") * moisture_excess)
    idx = round_half_up(idx, 2)
    compliance = "MISBRANDED" if idx > 0 else "COMPLIANT"
    return idx, compliance


# ---------------------------------------------------------------------------
# yield_variance_calculation
# ---------------------------------------------------------------------------
YIELD_HOLD_THRESHOLD_PCT = Decimal("5.00")


def compute_yield_variance(planned_kg, actual_kg):
    """round2((actual - planned) / planned * 100)."""
    p = _d(planned_kg)
    a = _d(actual_kg)
    return round_half_up((a - p) / p * Decimal("100"), 2)


# ---------------------------------------------------------------------------
# registration_fee_schedule
# ---------------------------------------------------------------------------
DEFAULT_BASE_FEE_CENTS = 5000
STATE_BASE_FEE_CENTS = {"CA": 7500, "TX": 6000, "NY": 8000}
T2_MIN_TONS = Decimal("5")
T3_MIN_TONS = Decimal("50")
T2_MULTIPLIER = Decimal("1.5")
T3_MULTIPLIER = Decimal("2.0")


def compute_registration_fee(state_code: str, tonnage_tier) -> int:
    """Return integer cents, round_half_up on multiplication."""
    base = STATE_BASE_FEE_CENTS.get(state_code, DEFAULT_BASE_FEE_CENTS)
    tons = _d(tonnage_tier)
    if tons >= T3_MIN_TONS:
        mult = T3_MULTIPLIER
    elif tons >= T2_MIN_TONS:
        mult = T2_MULTIPLIER
    else:
        mult = Decimal("1")
    fee = round_half_up(_d(base) * mult, 0)
    return int(fee)


# ---------------------------------------------------------------------------
# complaint_risk_score
# ---------------------------------------------------------------------------
SEV_W = {"MINOR": Decimal("5"), "SERIOUS": Decimal("20"),
         "LIFE_THREATENING": Decimal("45"), "DEATH": Decimal("60")}
CAT_W = {"PALATABILITY": Decimal("2"), "PACKAGING": Decimal("3"),
         "LABEL_DEFECT": Decimal("8"), "FOREIGN_MATERIAL": Decimal("12"),
         "ILLNESS": Decimal("15")}
AE_BONUS = Decimal("10")
ESCALATION_THRESHOLD = Decimal("60.0")
REGISTRATION_HOLD_THRESHOLD = Decimal("70.0")
ROLLUP_WINDOW_DAYS = 90
DECAY_WINDOW_DAYS = 30
DECAYED_SHARE = Decimal("0.25")


def compute_triage_score(severity, category, adverse_event_flag, provisional=False):
    """Provisional omits AE bonus; final includes it when flag is true."""
    s = SEV_W[severity] + CAT_W[category]
    if not provisional and adverse_event_flag:
        s += AE_BONUS
    return round_half_up(s, 2)


def compute_brand_complaint_score(brand_owner_id):
    """Weighted mean over trailing 90-day window ending at logical clock.
    Cases in TRIAGED contribute at half weight; INVESTIGATING at full weight.
    Cases closed (RESOLVED / CLOSED_NO_ACTION) within the last 30 days contribute
    DECAYED_SHARE of their final score."""
    now = store.now()
    window_start = now - timedelta(days=ROLLUP_WINDOW_DAYS)
    decay_start = now - timedelta(days=DECAY_WINDOW_DAYS)
    weighted_sum = Decimal("0")
    weight_total = Decimal("0")
    for case in store.complaint_cases.values():
        if case["brand_owner_id"] != brand_owner_id:
            continue
        score = case.get("triage_score")
        if score is None:
            continue
        score = _d(score)
        status = case["status"]
        # Use updated_at as the timestamp of last status change for windowing
        ref_ts = case.get("_status_changed_at_dt") or case.get("_created_at_dt")
        if status in ("TRIAGED", "INVESTIGATING"):
            if ref_ts and ref_ts >= window_start:
                w = Decimal("0.5") if status == "TRIAGED" else Decimal("1")
                weighted_sum += score * w
                weight_total += w
        elif status in ("RESOLVED", "CLOSED_NO_ACTION"):
            if ref_ts and ref_ts >= decay_start:
                w = DECAYED_SHARE
                weighted_sum += score * w
                weight_total += w
    if weight_total == 0:
        return Decimal("0.00")
    return round_half_up(weighted_sum / weight_total, 2)


# ---------------------------------------------------------------------------
# lot_code_sequencer
# ---------------------------------------------------------------------------
def mint_lot_code(batch):
    """lot_code = YYYYMMDD-{line_id}-{seq:03d}; seq is 1-based position among lots
    for same (production_date, line_id), ordered by created_at ASC."""
    sched = batch.get("_scheduled_start_dt")
    date_str = sched.strftime("%Y%m%d")
    line_id = batch["line_id"]
    # Count existing lots for same (date, line)
    existing = []
    for lot in store.batch_lot_codes.values():
        parent = store.production_batches.get(lot["batch_id"])
        if parent is None:
            continue
        p_sched = parent.get("_scheduled_start_dt")
        if p_sched and p_sched.strftime("%Y%m%d") == date_str and parent["line_id"] == line_id:
            existing.append(lot)
    seq = len(existing) + 1
    return f"{date_str}-{line_id}-{seq:03d}"


# ---------------------------------------------------------------------------
# Common-field helper
# ---------------------------------------------------------------------------
def stamp_new(entity: dict):
    """Set id, created_at, updated_at, version, and internal datetime fields."""
    now = store.now()
    entity["id"] = store.new_id()
    entity["created_at"] = iso_format(now)
    entity["updated_at"] = entity["created_at"]
    entity["version"] = 1
    entity["_created_at_dt"] = now
    entity["_updated_at_dt"] = now
    entity["_status_changed_at_dt"] = now
    return entity


def touch(entity: dict, status_changed=False):
    """Refresh updated_at and increment version."""
    now = store.now()
    entity["updated_at"] = iso_format(now)
    entity["_updated_at_dt"] = now
    entity["version"] = int(entity.get("version", 1)) + 1
    if status_changed:
        entity["_status_changed_at_dt"] = now
    return entity


def public_view(entity: dict):
    """Strip internal underscore-prefixed fields."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def public_list(entities):
    return [public_view(e) for e in entities]


def to_number(x):
    """Serialize Decimal to int/float for JSON output."""
    if isinstance(x, Decimal):
        # Preserve decimal places: use float when fractional
        if x == x.to_integral_value():
            return int(x)
        return float(x)
    return x


def serialize(entity: dict):
    """Public view with Decimals converted to JSON-safe numbers."""
    out = {}
    for k, v in public_view(entity).items():
        if isinstance(v, Decimal):
            out[k] = to_number(v)
        else:
            out[k] = v
    return out


def serialize_list(entities):
    return [serialize(e) for e in entities]
