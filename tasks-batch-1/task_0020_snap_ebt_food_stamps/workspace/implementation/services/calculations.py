"""SNAP/EBT calculations (per PRD §3.4 and §3.9, scaffold §1.3)."""

from datetime import timedelta

from db import db, parse_iso


# --- Constants from scaffold §1.3 ---

EARNED_INCOME_DEDUCTION_PCT_NUM = 20  # 20% — integer math via /100
STANDARD_DEDUCTION_BY_SIZE = {
    1: 19800, 2: 19800, 3: 19800,
    4: 21300, 5: 24900, 6: 28500,
}
SUA = 6700  # Standard Utility Allowance

NET_INCOME_LIMIT_BY_SIZE = {
    1: 117500, 2: 158900, 3: 200300,
    4: 241700, 5: 283100, 6: 324500,
}
NET_INCOME_LIMIT_EACH_ADDL = 41400

BENEFIT_REDUCTION_PCT_NUM = 30  # 30%
MAX_ALLOTMENT_BY_SIZE = {
    1: 29100, 2: 53500, 3: 76600,
    4: 97300, 5: 115500, 6: 138600,
}
EXTRA_PER_PERSON = 21100
MIN_ALLOTMENT_1_2 = 2300

VELOCITY_THRESHOLD_CENTS = 80000
VELOCITY_COUNT_PENALTY_CENTS = 5000
MIN_TX_FOR_FLAG = 4


# --- Net monthly income calculation ---

def _active_members(household_id: str):
    return [m for m in db.members.values()
            if m["household_id"] == household_id and m["status"] == "ACTIVE"]


def compute_gross_size(household_id: str):
    actives = _active_members(household_id)
    gross = sum(
        int(m.get("monthly_earned_income_cents", 0) or 0)
        + int(m.get("monthly_unearned_income_cents", 0) or 0)
        for m in actives
    )
    return gross, len(actives)


def _standard_deduction_for_size(size: int) -> int:
    # Per PRD: size 1-3 -> $198; 4 -> $213; 5 -> $249; 6 or larger -> $285.
    if size <= 1:
        return STANDARD_DEDUCTION_BY_SIZE[1]
    capped = min(size, 6)
    return STANDARD_DEDUCTION_BY_SIZE[capped]


def net_monthly_income(household: dict, variant: str = "BENEFIT_CALC") -> int:
    """Return the household's net monthly income in cents.

    BENEFIT_CALC:  includes SUA when heap_recipient is true.
    LIMIT_CHECK:   omits SUA even when heap_recipient is true.
    """
    hh_id = household["id"]
    gross, size = compute_gross_size(hh_id)
    actives = _active_members(hh_id)
    earned = sum(int(m.get("monthly_earned_income_cents", 0) or 0) for m in actives)

    # 20% earned-income deduction — truncated toward zero (i.e. floor for non-negative).
    earned_income_deduction = (earned * EARNED_INCOME_DEDUCTION_PCT_NUM) // 100

    # Standard deduction: use the size-tier table (clamped to >=1 for lookup, capped at 6).
    sized = max(size, 1)
    standard_deduction = _standard_deduction_for_size(sized)

    if variant == "LIMIT_CHECK":
        utility_allowance = 0
    else:
        utility_allowance = SUA if household.get("heap_recipient", False) else 0

    total_deductions = earned_income_deduction + standard_deduction + utility_allowance
    net = max(0, gross - total_deductions)
    return net


def net_income_limit_for_size(size: int) -> int:
    """NET_INCOME_LIMIT_BY_SIZE[1..6] + +41400 per person beyond 6.
    Size 0 households (no active members) treated as size 1 for limit purposes.
    """
    effective = max(size, 1)
    if effective <= 6:
        return NET_INCOME_LIMIT_BY_SIZE[effective]
    extra = effective - 6
    return NET_INCOME_LIMIT_BY_SIZE[6] + extra * NET_INCOME_LIMIT_EACH_ADDL


# --- Monthly allotment calculation ---

def _max_allotment_for_size(size: int) -> int:
    effective = max(size, 1)
    if effective <= 6:
        return MAX_ALLOTMENT_BY_SIZE[effective]
    extra = effective - 6
    return MAX_ALLOTMENT_BY_SIZE[6] + extra * EXTRA_PER_PERSON


def _find_active_proclamation(state_code: str, benefit_month: str):
    for proc in db.emergency_proclamations.values():
        if (proc["state_code"] == state_code
                and proc["benefit_month"] == benefit_month
                and proc["status"] == "ACTIVE"):
            return proc
    return None


def compute_monthly_allotment(household: dict, benefit_month: str):
    """Compute (standard_allotment_cents, emergency_supplement_cents, issued_total_cents)."""
    size = int(household.get("size", 0) or 0)
    hh_size = max(1, size)
    max_allotment = _max_allotment_for_size(hh_size)

    net = int(household.get("net_income_cents", 0) or 0)
    # 30% of net income, truncated toward zero (floor for non-negative).
    thirty_pct_net = (net * BENEFIT_REDUCTION_PCT_NUM) // 100

    floor_for_size = MIN_ALLOTMENT_1_2 if hh_size <= 2 else 0
    standard = max(floor_for_size, max_allotment - thirty_pct_net)

    proc = _find_active_proclamation(household["state_code"], benefit_month)
    if proc is None:
        emergency = 0
    else:
        gap = max_allotment - standard
        emergency = max(int(proc.get("min_supplement_cents", 9500)), gap)

    total = standard + emergency
    return standard, emergency, total


# --- Fraud velocity score ---

def fraud_velocity_should_flag(household_id: str) -> bool:
    """Evaluate the 24-hour SETTLED-purchase velocity for the household at SystemClock.current_utc.

    Returns True iff (score >= VELOCITY_THRESHOLD_CENTS) AND (count >= MIN_TX_FOR_FLAG).
    The trigger row's status/settled_at MUST already be written before calling.
    """
    now_dt = db.current_utc_dt()
    window_start = now_dt - timedelta(hours=24)

    settled = []
    for tx in db.purchase_transactions.values():
        if tx["household_id"] != household_id:
            continue
        if tx["status"] != "SETTLED":
            continue
        settled_at = tx.get("settled_at")
        if not settled_at:
            continue
        sdt = parse_iso(settled_at)
        if sdt < window_start or sdt > now_dt:
            continue
        settled.append(tx)

    # Sort by settled_at ASC, created_at ASC. Never on id.
    settled.sort(key=lambda t: (parse_iso(t["settled_at"]), parse_iso(t["created_at"])))

    total_24h = sum(int(t.get("total_cents", 0) or 0) for t in settled)
    count_24h = len(settled)
    score = total_24h + (count_24h * VELOCITY_COUNT_PENALTY_CENTS)
    return (score >= VELOCITY_THRESHOLD_CENTS) and (count_24h >= MIN_TX_FOR_FLAG)
