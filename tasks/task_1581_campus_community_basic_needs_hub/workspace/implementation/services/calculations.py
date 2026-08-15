"""Calculation rules (scaffold §1.3 / PRD §3) — exact formulas, pinned rounding."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import db
from util import CLOCK, parse_datetime, parse_date

# --- eligibility_band constants ---
POVERTY_MONTHLY_CENTS = {1: 125500, 2: 169300, 3: 213100, 4: 256900,
                         5: 300700, 6: 344500, 7: 388300, 8: 432100}
POVERTY_ADDL_PERSON_CENTS = 43800
FULL_BAND_MAX_RATIO = Decimal("1.30")
PARTIAL_BAND_MAX_RATIO = Decimal("2.00")

# --- snap_benefit_estimate constants ---
SNAP_STD_DED_CENTS = 19800
SNAP_SHELTER_CAP_CENTS = 67200
SNAP_MAX_ALLOTMENT_CENTS = {1: 29200, 2: 53600, 3: 76800, 4: 97500,
                            5: 115800, 6: 139000, 7: 153600, 8: 175600}

# --- screening_score constants ---
HOUSING_POINTS = {"STABLE": 0, "COST_BURDENED": 60, "UNSTABLE": 85, "HOMELESS": 100}
SCREENING_WEIGHTS = {
    "SNAP": (Decimal("0.6"), Decimal("0.3"), Decimal("0.1")),
    "CHILDCARE": (Decimal("0.5"), Decimal("0.1"), Decimal("0.4")),
    "HOUSING": (Decimal("0.4"), Decimal("0.1"), Decimal("0.5")),
}
LIKELY_MIN = 70
POSSIBLY_MIN = 40

# --- pantry_points constants ---
WEEKLY_POINTS_BASE = 30
WEEKLY_POINTS_PER_DEPENDENT = 10
WEEKLY_POINTS_CAP = 60

# --- visit_frequency_check constants ---
MAX_VISITS_PER_168H = 2
WINDOW_HOURS = 168

# --- grant_award_sizing constants ---
PER_AWARD_CAP_CENTS = 150000
LIFETIME_CAP_CENTS = 300000

# --- shelter_stay_windows constants ---
MAX_STAY_NIGHTS = 14
BOOKING_HORIZON_DAYS = 13
NO_SHOW_GRACE_DAYS = 1
PET_SANITATION_BUFFER_DAYS = 1

NO_SHOW_WINDOW_HOURS = 2160  # 90 days


# ---------------------------------------------------------------------------
# eligibility_band (submit-time; frozen on the assessment)
# ---------------------------------------------------------------------------

def compute_eligibility(household_size: int, monthly_income_cents: int, housing_status: str):
    """Returns (income_ratio Decimal 4dp round_half_up, eligibility_band)."""
    hh = household_size
    threshold = POVERTY_MONTHLY_CENTS[min(hh, 8)] + max(0, hh - 8) * POVERTY_ADDL_PERSON_CENTS
    ratio = (Decimal(monthly_income_cents) / Decimal(threshold)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP)
    if housing_status == "HOMELESS":
        band = "FULL"  # unconditional floor override
    elif ratio <= FULL_BAND_MAX_RATIO:
        band = "FULL"
    elif ratio <= PARTIAL_BAND_MAX_RATIO:
        band = "PARTIAL"
    else:
        band = "INELIGIBLE"
    return ratio, band


# ---------------------------------------------------------------------------
# snap_benefit_estimate (pinned per-step rounding; each step rounds before the
# next step reads it)
# ---------------------------------------------------------------------------

def compute_snap_estimate(assessment) -> int:
    earned = assessment["earned_income_cents"]
    monthly = assessment["monthly_income_cents"]
    shelter = assessment["shelter_cost_cents"]
    hh = assessment["household_size"]
    # (1) earned deduction: 20% of earned income, round half-up to whole cents
    # round_half_up(earned/5) = floor((2*earned + 5) / 10)
    earned_deduction = (2 * earned + 5) // 10 if earned >= 0 else 0
    # (2) adjusted income, floored at 0
    adjusted = max(0, monthly - earned_deduction - SNAP_STD_DED_CENTS)
    # (3) excess shelter: shelter - floor(adjusted / 2), floored at 0
    excess_shelter = max(0, shelter - adjusted // 2)
    # (4) capped shelter
    capped_shelter = min(excess_shelter, SNAP_SHELTER_CAP_CENTS)
    # (5) net income, floored at 0
    net_income = max(0, adjusted - capped_shelter)
    # (6) thirty percent share, ceil to whole cents
    thirty_pct_share = (net_income * 3 + 9) // 10
    # (7) estimate, floored at 0
    return max(0, SNAP_MAX_ALLOTMENT_CENTS[min(hh, 8)] - thirty_pct_share)


# ---------------------------------------------------------------------------
# screening_score (weighted blend with hard gates; integer round_half_up)
# ---------------------------------------------------------------------------

def compute_screening_score(program: str, assessment):
    """Returns (score:int 0..100, result_band)."""
    ratio = assessment.get("_ratio")
    if ratio is None:
        ratio = Decimal(0)
    income_pts = Decimal(100) * max(Decimal(0), Decimal(1) - ratio / Decimal(2))
    food_pts = Decimal(100 * assessment["food_insecurity_score"]) / Decimal(6)
    housing_pts = Decimal(HOUSING_POINTS[assessment["housing_status"]])

    if program == "CHILDCARE" and assessment["dependents_under_18"] == 0:
        score = 0  # hard gate
    elif program == "SNAP" and assessment["receives_snap"]:
        score = 0  # already receiving -> nothing to screen
    else:
        w_income, w_food, w_housing = SCREENING_WEIGHTS[program]
        raw = w_income * income_pts + w_food * food_pts + w_housing * housing_pts
        score = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        if program == "HOUSING" and assessment["housing_status"] == "STABLE":
            score = min(39, score)  # ceiling gate
    score = max(0, min(100, score))
    if score >= LIKELY_MIN:
        band = "LIKELY_ELIGIBLE"
    elif score >= POSSIBLY_MIN:
        band = "POSSIBLY_ELIGIBLE"
    else:
        band = "NOT_ELIGIBLE"
    return score, band


# ---------------------------------------------------------------------------
# risk_tier (reads the client's single VERIFIED assessment, null-safe)
# ---------------------------------------------------------------------------

def compute_risk_tier(assessment):
    if assessment is None:
        return None
    hs = assessment["housing_status"]
    food = assessment["food_insecurity_score"]
    ratio = assessment.get("_ratio")
    if hs in ("UNSTABLE", "HOMELESS") or food >= 5:
        return "CRISIS"
    if hs == "COST_BURDENED" or food >= 3 or (ratio is not None and ratio <= FULL_BAND_MAX_RATIO):
        return "ELEVATED"
    return "STABLE"


# ---------------------------------------------------------------------------
# pantry_points (weekly budget and spent aggregates)
# ---------------------------------------------------------------------------

def compute_allotment(household_size_effective) -> int:
    if household_size_effective is None:
        return 0
    return min(WEEKLY_POINTS_BASE + WEEKLY_POINTS_PER_DEPENDENT * (household_size_effective - 1),
               WEEKLY_POINTS_CAP)


def current_week_start():
    from util import week_start_of
    return week_start_of(CLOCK.now())


def points_settled(client_id) -> int:
    """Sum of points_spent over COMPLETED visits in the current week window."""
    ws = current_week_start()
    total = 0
    for v in db["pantry_visits"].values():
        if v["client_id"] != client_id or v["status"] != "COMPLETED":
            continue
        if parse_datetime(v["week_start"]) == ws:
            total += v["points_spent"]
    return total


def open_visit(client_id):
    for v in db["pantry_visits"].values():
        if v["client_id"] == client_id and v["status"] == "CHECKED_IN":
            return v
    return None


def points_reserved(client_id) -> int:
    """Settled + the open visit's provisional points."""
    settled = points_settled(client_id)
    v = open_visit(client_id)
    return settled + (v["provisional_points"] if v else 0)


# ---------------------------------------------------------------------------
# visit_frequency_check (rolling 168h, strict window edge)
# ---------------------------------------------------------------------------

def visits_in_window(client_id) -> int:
    now = CLOCK.now()
    edge = now - timedelta(hours=WINDOW_HOURS)
    count = 0
    for v in db["pantry_visits"].values():
        if v["client_id"] != client_id or v["status"] not in ("CHECKED_IN", "COMPLETED"):
            continue
        # strict: a visit exactly 168h old does NOT count
        if parse_datetime(v["visit_date"]) > edge:
            count += 1
    return count


# ---------------------------------------------------------------------------
# grant_award_sizing (pre-approval snapshot; min over four caps)
# ---------------------------------------------------------------------------

def size_award(application, fund, client_lifetime_cents) -> int:
    remaining_pre = fund["allocated_cents"] - fund["committed_cents"] - fund["disbursed_cents"]
    lifetime_room = LIFETIME_CAP_CENTS - client_lifetime_cents
    return min(application["requested_cents"], PER_AWARD_CAP_CENTS, remaining_pre, lifetime_room)


# ---------------------------------------------------------------------------
# fund_remaining (two bases)
# ---------------------------------------------------------------------------

def fund_counters(fund_id):
    committed = 0
    disbursed = 0
    for g in db["grant_applications"].values():
        if g["fund_id"] != fund_id:
            continue
        if g["status"] == "APPROVED":
            committed += g["approved_cents"]
        elif g["status"] == "DISBURSED":
            disbursed += g["approved_cents"]
    return committed, disbursed


# ---------------------------------------------------------------------------
# referral_capacity_check (weekly capacity with CRISIS overflow)
# ---------------------------------------------------------------------------

def referral_admits(agency, risk_tier) -> bool:
    active = agency["active_referral_count"]
    capacity = agency["weekly_capacity"]
    if active < capacity:
        return True
    # CRISIS overflow: admit while active < floor(capacity * 1.2)
    if risk_tier == "CRISIS" and active < (capacity * 6) // 5:
        return True
    return False


# ---------------------------------------------------------------------------
# counselor_assignment (deterministic total order: load, then creation order)
# ---------------------------------------------------------------------------

def counselor_case_load(staff_id) -> int:
    count = 0
    for s in db["screenings"].values():
        if s["counselor_id"] == staff_id and s["status"] in (
                "STARTED", "SCREENED", "APPLICATION_ASSISTED", "SUBMITTED"):
            count += 1
    return count


def select_counselor():
    candidates = [s for s in db["staff"].values()
                  if s["staff_role"] == "BENEFITS_COUNSELOR" and s["status"] == "ACTIVE"]
    if not candidates:
        return None
    candidates.sort(key=lambda s: (counselor_case_load(s["id"]), s["_seq"]))
    return candidates[0]


# ---------------------------------------------------------------------------
# shelter_stay_windows (bed half-open + PET buffer; client closed night-set)
# ---------------------------------------------------------------------------

def stay_window_dates(check_in: str, planned_nights: int, pet_friendly: bool):
    ci = parse_date(check_in)
    co = ci + timedelta(days=planned_nights)
    buf = co + timedelta(days=PET_SANITATION_BUFFER_DAYS) if pet_friendly else co
    return co.isoformat(), buf.isoformat()


def bed_conflict(bed_id, new_check_in: str, new_buffer_until: str, exclude_id=None) -> bool:
    new_ci = parse_date(new_check_in)
    new_buf = parse_date(new_buffer_until)
    for s in db["shelter_stays"].values():
        if s["bed_id"] != bed_id or s["status"] not in ("RESERVED", "OCCUPIED"):
            continue
        if exclude_id and s["id"] == exclude_id:
            continue
        s_ci = parse_date(s["check_in_date"])
        s_buf = parse_date(s["buffer_until_exclusive"])
        # half-open [check_in, buffer_until) intersection
        if new_ci < s_buf and s_ci < new_buf:
            return True
    return False


def client_stay_overlap(client_id, new_check_in: str, new_check_out: str, exclude_id=None) -> bool:
    new_first = parse_date(new_check_in)
    new_last = parse_date(new_check_out) - timedelta(days=1)
    for s in db["shelter_stays"].values():
        if s["client_id"] != client_id or s["status"] not in ("RESERVED", "OCCUPIED"):
            continue
        if exclude_id and s["id"] == exclude_id:
            continue
        s_first = parse_date(s["check_in_date"])
        s_last = parse_date(s["check_out_exclusive"]) - timedelta(days=1)
        # closed night-set intersection
        if new_first <= s_last and s_first <= new_last:
            return True
    return False


# ---------------------------------------------------------------------------
# client standing: no-shows / restriction / lifetime grants
# ---------------------------------------------------------------------------

def no_show_count_90d(client_id) -> int:
    now = CLOCK.now()
    edge = now - timedelta(hours=NO_SHOW_WINDOW_HOURS)
    count = 0
    for s in db["shelter_stays"].values():
        if s["client_id"] != client_id or s["status"] != "NO_SHOW":
            continue
        marked = s.get("no_show_marked_at")
        if marked and edge <= parse_datetime(marked) <= now:
            count += 1
    return count


def lifetime_grant_cents(client_id) -> int:
    total = 0
    for g in db["grant_applications"].values():
        if g["client_id"] == client_id and g["status"] == "DISBURSED":
            total += g["approved_cents"]
    return total
