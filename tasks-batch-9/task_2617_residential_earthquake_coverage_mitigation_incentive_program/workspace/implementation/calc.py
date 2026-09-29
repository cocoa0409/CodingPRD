"""The eight calculations of PRD section 3, plus the two ledger waterfalls.

Every chain of multipliers is evaluated in exact decimal arithmetic, in the
order the PRD states, and rounded exactly once, half up, at the point the PRD
names.  Where a calculation rounds twice, the second rounding consumes the
already-rounded first result.
"""

from decimal import Decimal

import store
from errors import ApiError
from store import dec, round_half_up

# --- programme constants (PRD 3.3 - 3.8) ---------------------------------
OFFER_VALID_DAYS = 60
QUOTE_VALID_DAYS = 30
TERM_DAYS = 365
RENEWAL_WINDOW_DAYS = 45
MORATORIUM_DAYS = 60
MAX_REVIEW_ROUNDS = 3
MAX_REOPENS = 2
PROBATION_FAIL_THRESHOLD = 3
MAX_OPEN_PROJECTS_PER_CONTRACTOR = 3
INSPECTION_MIN_MINUTES = 30
INSPECTION_MAX_MINUTES = 240
INSPECTION_BUFFER_MINUTES = 60
DECLARATION_MIN_MAGNITUDE = Decimal("5.0")
PRE_CODE_YEAR = 1979

BASE_RATE_PER_1000 = {"TIER_1": dec(180), "TIER_2": dec(320), "TIER_3": dec(520)}
SOIL_FACTOR = {
    "ROCK": dec("0.85"),
    "STIFF": dec("1.00"),
    "SOFT": dec("1.25"),
    "LIQUEFACTION": dec("1.55"),
}
STRUCTURE_FACTOR = {
    "WOOD_FRAME_SLAB": dec("1.00"),
    "WOOD_FRAME_CRIPPLE_WALL": dec("1.30"),
    "MASONRY_URM": dec("1.85"),
    "MOBILE_HOME": dec("1.45"),
}
DEDUCTIBLE_FACTOR = {
    5: dec("1.35"),
    10: dec("1.00"),
    15: dec("0.86"),
    20: dec("0.75"),
    25: dec("0.66"),
}
AGE_FACTOR_PRE_CODE = dec("1.20")
AGE_FACTOR_MODERN = dec("1.00")
HIGH_LIMIT_THRESHOLD_CENTS = 75000000
HIGH_LIMIT_FACTOR = dec("1.15")
EXPOSURE_UNIT_CENTS = dec(100000)
PREMIUM_FLOOR_CENTS = dec(18000)
PREMIUM_CEILING_CENTS = dec(4000000)

RETROFIT_FACTOR_DEEP = dec("0.75")
RETROFIT_FACTOR_VERIFIED = dec("0.90")
RETROFIT_FACTOR_SELF_DECLARED = dec("0.95")
RETROFIT_FACTOR_NONE = dec("1.00")

SCOPE_DISCOUNT_CRIPPLE_WALL = dec("0.25")
SCOPE_DISCOUNT_MOBILE_HOME = dec("0.20")
SCOPE_DISCOUNT_OTHER = dec("0.10")
GRANT_OFFSET_PCT = dec("0.05")
MIN_EFFECTIVE_DISCOUNT_PCT = dec("0.05")
PRORATION_DAYS = dec(365)

COSMETIC_ALLOWANCE_PCT = dec("0.10")

SCOPE_COST_CAP_CENTS = {
    "WOOD_FRAME_CRIPPLE_WALL": 1000000,
    "MOBILE_HOME": 600000,
    "WOOD_FRAME_SLAB": 0,
    "MASONRY_URM": 0,
}
MATCH_PCT = {"TIER_LOW": dec("1.00"), "TIER_MID": dec("0.75"), "TIER_ANY": dec("0.50")}
MAX_GRANT_CENTS = 300000
TIER_POOL_PCT = {"TIER_LOW": dec("0.60"), "TIER_MID": dec("0.40"), "TIER_ANY": dec("0.25")}
BUCKET_CONSUMING_STATUSES = ("FUNDS_RESERVED", "VERIFIED_COMPLETE")

TAKE_UP_BP_SCALE = dec(10000)
TAKE_UP_MIN_CONSIDERED = 4
TAKE_UP_REVIEW_THRESHOLD_BP = 2500
UNDOCUMENTED_SANCTION_THRESHOLD = 3

LOADING_BAND_ONE_CENTS = 10000000000
LOADING_BAND_TWO_CENTS = 50000000000
LOADING_RATE_ONE = dec("0.02")
LOADING_RATE_TWO = dec("0.035")
LOADING_RATE_THREE = dec("0.05")

GROSS_CONTRIBUTING_CLAIM_STATUSES = ("FINAL_ADJUSTED", "CLOSED")


# --- 1. hazard_base_premium (PRD 3.3) ------------------------------------

def retrofit_factor(dwelling, variant):
    """The one place where the two rating variants diverge.

    The renewal variant first downgrades a SELF_DECLARED posture to NONE, so
    only an inspection-verified retrofit survives into a renewal rating.
    """
    posture = dwelling["retrofit_status"]
    if variant == "RENEWAL_TIME" and posture == "SELF_DECLARED":
        posture = "NONE"
    if posture == "VERIFIED":
        if (dwelling["structure_type"] == "WOOD_FRAME_CRIPPLE_WALL"
                and dwelling["verified_retrofit_scope"] == "CRIPPLE_WALL_BRACING"):
            return RETROFIT_FACTOR_DEEP
        return RETROFIT_FACTOR_VERIFIED
    if posture == "SELF_DECLARED":
        return RETROFIT_FACTOR_SELF_DECLARED
    return RETROFIT_FACTOR_NONE


def hazard_base_premium(dwelling, deductible_pct, variant):
    """base_premium_cents under the QUOTE_TIME or RENEWAL_TIME variant."""
    exposure_units = dec(dwelling["dwelling_limit_cents"]) / EXPOSURE_UNIT_CENTS
    rate = BASE_RATE_PER_1000[dwelling["county_hazard_tier"]]
    soil = SOIL_FACTOR[dwelling["soil_class"]]
    structure = STRUCTURE_FACTOR[dwelling["structure_type"]]
    age = AGE_FACTOR_PRE_CODE if dwelling["year_built"] <= PRE_CODE_YEAR else AGE_FACTOR_MODERN
    retrofit = retrofit_factor(dwelling, variant)
    deductible = DEDUCTIBLE_FACTOR[deductible_pct]
    high_limit = (HIGH_LIMIT_FACTOR
                  if dwelling["dwelling_limit_cents"] >= HIGH_LIMIT_THRESHOLD_CENTS
                  else dec("1.00"))
    raw = rate * exposure_units * soil * structure * age * retrofit * deductible * high_limit
    # Clamp the unrounded product, then round exactly once, half up.
    if raw < PREMIUM_FLOOR_CENTS:
        raw = PREMIUM_FLOOR_CENTS
    elif raw > PREMIUM_CEILING_CENTS:
        raw = PREMIUM_CEILING_CENTS
    return round_half_up(raw)


# --- 2. mitigation_discount_application (PRD 3.6) ------------------------

def mitigation_discount(policy, dwelling, grant):
    """(mitigation_discount_cents, prorated_credit_cents).

    Two roundings: the prorated credit consumes the already-rounded discount.
    """
    scope = dwelling["verified_retrofit_scope"]
    structure = dwelling["structure_type"]
    if scope == "CRIPPLE_WALL_BRACING" and structure == "WOOD_FRAME_CRIPPLE_WALL":
        scope_pct = SCOPE_DISCOUNT_CRIPPLE_WALL
    elif scope == "EARTHQUAKE_BRACING_SYSTEM" and structure == "MOBILE_HOME":
        scope_pct = SCOPE_DISCOUNT_MOBILE_HOME
    else:
        scope_pct = SCOPE_DISCOUNT_OTHER
    offset = GRANT_OFFSET_PCT if (grant and grant["approved_amount_cents"] > 0) else dec(0)
    effective = scope_pct - offset
    if effective < MIN_EFFECTIVE_DISCOUNT_PCT:
        effective = MIN_EFFECTIVE_DISCOUNT_PCT
    discount = round_half_up(dec(policy["base_premium_cents"]) * effective)
    remaining_days = store.whole_days_between(store.dt_of(policy, "expires_at"),
                                              store.clock_now())
    capped_days = remaining_days if remaining_days < 365 else 365
    credit = round_half_up(dec(discount) * dec(capped_days) / PRORATION_DAYS)
    return discount, credit


# --- 3. claim_settlement (PRD 3.8) ---------------------------------------

def deductible_applied(policy):
    """From the term snapshot, never the live dwelling limit."""
    return round_half_up(dec(policy["rated_dwelling_limit_cents"])
                         * dec(policy["deductible_pct"]) / dec(100))


def settle_provisional(claim, policy):
    """Cosmetic damage excluded; the deductible hits Coverage A alone."""
    limit = policy["rated_dwelling_limit_cents"]
    deductible = deductible_applied(policy)
    dwelling_basis = min(claim["structural_damage_cents"], limit)
    dwelling_part = dwelling_basis - deductible
    if dwelling_part < 0:
        dwelling_part = 0
    contents_part = min(claim["contents_damage_cents"], policy["contents_sublimit_cents"])
    lou_part = min(claim["loss_of_use_cents"], policy["loss_of_use_sublimit_cents"])
    payable = dwelling_part + contents_part + lou_part
    return {
        "deductible_applied_cents": deductible,
        "dwelling_part_cents": dwelling_part,
        "contents_part_cents": contents_part,
        "loss_of_use_part_cents": lou_part,
        "provisional_payable_cents": payable,
        "payable_cents": payable,
    }


def settle_final(claim, policy):
    """Cosmetic admitted to a tenth of structural; the deductible hits the
    combined Coverage A + C basis, and the split has a pinned order: contents
    first (rounded), then dwelling as the residual."""
    limit = policy["rated_dwelling_limit_cents"]
    deductible = deductible_applied(policy)
    cosmetic_cap = round_half_up(COSMETIC_ALLOWANCE_PCT * dec(claim["structural_damage_cents"]))
    cosmetic_allowed = min(claim["cosmetic_damage_cents"], cosmetic_cap)
    dwelling_basis = min(claim["structural_damage_cents"] + cosmetic_allowed, limit)
    contents_basis = min(claim["contents_damage_cents"], policy["contents_sublimit_cents"])
    combined = dwelling_basis + contents_basis
    after_deductible = combined - deductible
    if after_deductible < 0:
        after_deductible = 0
    if combined == 0:
        contents_part = 0
    else:
        contents_part = round_half_up(dec(after_deductible) * dec(contents_basis) / dec(combined))
    dwelling_part = after_deductible - contents_part
    lou_part = min(claim["loss_of_use_cents"], policy["loss_of_use_sublimit_cents"])
    payable = dwelling_part + contents_part + lou_part
    return {
        "deductible_applied_cents": deductible,
        "dwelling_part_cents": dwelling_part,
        "contents_part_cents": contents_part,
        "loss_of_use_part_cents": lou_part,
        "final_payable_cents": payable,
        "payable_cents": payable,
    }


# --- 4. grant_award_amount (PRD 3.5) -------------------------------------

def structure_is_grant_eligible(dwelling):
    return SCOPE_COST_CAP_CENTS.get(dwelling["structure_type"], 0) > 0


def grant_award_amount(grant, dwelling):
    cap = SCOPE_COST_CAP_CENTS.get(dwelling["structure_type"], 0)
    eligible = min(grant["project_cost_estimate_cents"], cap)
    awarded = round_half_up(dec(eligible) * MATCH_PCT[grant["income_tier"]])
    if awarded > MAX_GRANT_CENTS:
        awarded = MAX_GRANT_CENTS
    return awarded


# --- 5. grant_pool_waterfall (PRD 3.5) -----------------------------------

def bucket_cap(cycle, tier):
    return round_half_up(dec(cycle["total_pool_cents"]) * TIER_POOL_PCT[tier])


def bucket_used(cycle, tier):
    total = 0
    for grant in store.DB["grants"].values():
        if grant["grant_cycle_id"] != cycle["id"]:
            continue
        if grant["funded_from_bucket"] != tier:
            continue
        if grant["status"] not in BUCKET_CONSUMING_STATUSES:
            continue
        total += grant["approved_amount_cents"]
    return total


def resolve_bucket(cycle, grant):
    """Steps one and two of the sub-pool waterfall; step three is the caller's
    pool ceiling check, which is deliberately evaluated afterwards."""
    award = grant["approved_amount_cents"]
    own_tier = grant["income_tier"]
    if bucket_used(cycle, own_tier) + award <= bucket_cap(cycle, own_tier):
        return own_tier
    if own_tier != "TIER_ANY":
        if bucket_used(cycle, "TIER_ANY") + award <= bucket_cap(cycle, "TIER_ANY"):
            return "TIER_ANY"
    raise ApiError("ERR_GRANT_TIER_CAP_EXHAUSTED")


def recompute_uncommitted(cycle):
    cycle["uncommitted_cents"] = (cycle["total_pool_cents"]
                                  - cycle["reserved_cents"]
                                  - cycle["disbursed_cents"])


# --- 6. event_loss_waterfall (PRD 3.7) -----------------------------------

def participating_layers(event):
    layers = [row for row in store.DB["layers"].values()
              if row["treaty_year"] == event["treaty_year"] and row["status"] == "ACTIVE"]
    layers.sort(key=lambda row: (row["layer_index"], row["created_at"], row["_seq"]))
    return layers


def has_active_layer(treaty_year):
    for row in store.DB["layers"].values():
        if row["treaty_year"] == treaty_year and row["status"] == "ACTIVE":
            return True
    return False


def run_loss_waterfall(event):
    """Recompute the whole waterfall from scratch over the current gross.

    Lapsed layers are excluded but attachment points are absolute, so a lapsed
    lower layer leaves a permanent hole that lands in uncovered_cents.
    """
    gross = event["aggregate_incurred_cents"]
    retained = min(gross, event["retention_cents"])
    ceded_total = 0
    for layer in participating_layers(event):
        top = layer["attachment_point_cents"] + layer["limit_cents"]
        exposure = min(gross, top) - layer["attachment_point_cents"]
        if exposure < 0:
            exposure = 0
        ceded = round_half_up(dec(exposure) * dec(layer["ceded_pct"]))
        if layer["ceded_cents"] != ceded:
            layer["ceded_cents"] = ceded
            store.touch(layer)
        ceded_total += ceded
    uncovered = gross - retained - ceded_total
    if uncovered < 0:
        uncovered = 0
    event["retained_cents"] = retained
    event["ceded_total_cents"] = ceded_total
    event["uncovered_cents"] = uncovered
    return uncovered


def recompute_gross(event):
    """The gross is the sum of final_payable_cents over the event's claims in
    FINAL_ADJUSTED or CLOSED; it is maintained incrementally by the claim
    cascades, so this helper exists only for symmetry checks."""
    total = 0
    for claim in store.DB["claims"].values():
        if claim["event_id"] != event["id"]:
            continue
        if claim["adjustment_status"] in GROSS_CONTRIBUTING_CLAIM_STATUSES:
            total += claim["final_payable_cents"]
    return total


# --- 7. post_event_assessment (PRD 3.8) ----------------------------------

def loading_rate(shortfall_cents):
    """Keyed on the bare shortfall, never on the grossed-up total."""
    if shortfall_cents < LOADING_BAND_ONE_CENTS:
        return LOADING_RATE_ONE
    if shortfall_cents < LOADING_BAND_TWO_CENTS:
        return LOADING_RATE_TWO
    return LOADING_RATE_THREE


def assessable_insurers():
    """A WITHDRAWN carrier remains assessable; a SANCTIONED one is excluded."""
    rows = []
    for insurer in store.DB["insurers"].values():
        if insurer["compliance_status"] not in ("COMPLIANT", "UNDER_REVIEW"):
            continue
        if dec(insurer["market_share_pct"]) <= 0:
            continue
        rows.append(insurer)
    rows.sort(key=lambda row: (-dec(row["market_share_pct"]), row["created_at"], row["_seq"]))
    return rows


def levy_assessment(event):
    """Pin the shortfall, add the loading and spread the total across the
    assessable insurers in market-share order, the last rank absorbing the
    residual so the parts sum to the whole exactly."""
    shortfall = event["uncovered_cents"]
    loading = round_half_up(dec(shortfall) * loading_rate(shortfall))
    total = shortfall + loading
    insurers = assessable_insurers()
    if not insurers:
        raise ApiError("ERR_NO_ASSESSABLE_INSURERS")
    denominator = sum((dec(row["market_share_pct"]) for row in insurers), dec(0))
    allocations = []
    running = 0
    last_index = len(insurers) - 1
    for index, insurer in enumerate(insurers):
        rank = index + 1
        if index < last_index:
            assessed = round_half_up(dec(total) * dec(insurer["market_share_pct"]) / denominator)
            absorbs = False
        else:
            assessed = total - running
            absorbs = True
        running += assessed
        allocation = store.insert("allocations", {
            "event_id": event["id"],
            "insurer_id": insurer["id"],
            "market_share_pct_snapshot": insurer["market_share_pct"],
            "assessed_cents": assessed,
            "allocation_rank": rank,
            "absorbs_remainder": absorbs,
        }, audited=False)
        allocations.append(allocation)
        insurer["assessment_balance_cents"] += assessed
        store.touch(insurer)
    event["assessment_shortfall_cents"] = shortfall
    event["admin_loading_cents"] = loading
    event["assessment_total_cents"] = total
    return allocations


# --- 8. take_up_rate_evaluation (PRD 3.1) --------------------------------

CONSIDERED_OFFER_STATUSES = ("ACCEPTED", "DECLINED", "EXPIRED")


def take_up_evaluation(insurer, window_start, window_end):
    """Score take-up over the half-open window and apply the consequence."""
    considered = 0
    accepted = 0
    undocumented = 0
    for offer in store.DB["offers"].values():
        if offer["insurer_id"] != insurer["id"]:
            continue
        if offer["status"] not in CONSIDERED_OFFER_STATUSES:
            continue
        offered_at = store.dt_of(offer, "offered_at")
        if offered_at is None or offered_at < window_start or offered_at >= window_end:
            continue
        considered += 1
        if offer["status"] == "ACCEPTED":
            accepted += 1
        elif offer["status"] == "DECLINED" and not offer["decline_documented"]:
            undocumented += 1
    if considered == 0:
        rate_bp = 0
    else:
        rate_bp = round_half_up(TAKE_UP_BP_SCALE * dec(accepted) / dec(considered))
    insurer["last_take_up_rate_bp"] = rate_bp
    insurer["offers_recorded_count"] = considered
    insurer["undocumented_decline_count"] = undocumented
    # Both consequences are evaluated on every run; sanction wins.
    if undocumented >= UNDOCUMENTED_SANCTION_THRESHOLD:
        if insurer["compliance_status"] in ("COMPLIANT", "UNDER_REVIEW"):
            insurer["compliance_status"] = "SANCTIONED"
    elif (considered >= TAKE_UP_MIN_CONSIDERED
            and rate_bp < TAKE_UP_REVIEW_THRESHOLD_BP
            and insurer["compliance_status"] == "COMPLIANT"):
        insurer["compliance_status"] = "UNDER_REVIEW"
    store.touch(insurer)
    return rate_bp
