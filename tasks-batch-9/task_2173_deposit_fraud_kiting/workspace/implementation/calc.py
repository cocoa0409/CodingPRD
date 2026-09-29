"""Calculation rules, derived aggregates and shared cascade helpers."""
from datetime import timedelta
from decimal import Decimal

from core import bps, db, now, round_half_up, touch

# --- new_account_risk_score ------------------------------------------------
KYC_TIER_POINTS = {"TIER_1": 0, "TIER_2": 15, "TIER_3": 35}
FUNDING_POINTS = {"VERIFIED": 0, "PENDING": 20, "NONE": 30}
CHANNEL_POINTS = {"BRANCH": 0, "ONLINE": 12, "MOBILE": 18}
WATCHLIST_POINTS = 40
LINK_POINTS_PER_RISK_LINK = 5
LINK_POINTS_CAP = 25
LINK_CONFIDENCE_MIN_BPS = 6000
RISK_BAND_HIGH_MIN = 60
RISK_BAND_ELEVATED_MIN = 35
RISK_LINK_TYPES = {"SHARED_DEVICE", "SHARED_ADDRESS", "SHARED_PHONE"}

# --- ato_indicator_score ---------------------------------------------------
INDICATOR_WEIGHTS = {
    "NEW_DEVICE": 15,
    "GEO_VELOCITY": 25,
    "CREDENTIAL_STUFFING": 30,
    "PROFILE_CHANGE": 20,
    "DORMANT_REACTIVATION": 18,
    "PAYEE_ADDED": 12,
}
ATO_STEP_UP_MIN = 40
ATO_LOCK_MIN = 75
STEP_UP_MAX_FAILURES = 3

# --- check_hold_schedule ---------------------------------------------------
IMMEDIATE_AVAIL_CENTS = 22500
LARGE_DEPOSIT_CENTS = 552500
NEW_ACCOUNT_DAYS = 30
HOLD_DAYS = {
    "STANDARD": 2,
    "EXCEPTION_RISK": 5,
    "EXCEPTION_LARGE_DEPOSIT": 7,
    "EXCEPTION_NEW_ACCOUNT": 9,
    "EXCEPTION_FRAUD": 0,
}

# --- hold_override_loss_exposure -------------------------------------------
RETURN_RATE_BPS = {"CHECK": 275, "ACH": 120, "CASH": 0}
RISK_MULT_BPS = {"STANDARD": 10000, "ELEVATED": 12500, "HIGH": 16000}
SUPERVISOR_APPROVAL_LIMIT_CENTS = 500000

# --- kiting_cycle_score ----------------------------------------------------
CYCLE_MAX_DEPTH = 4
CYCLE_BASE = {2: 40, 3: 55, 4: 60}
VELOCITY_WEIGHT = 6
UNCOLLECTED_WEIGHT = 30
KITING_OPEN_THRESHOLD = 70
QUALIFYING_STATUSES = {
    "STRICT": {"PENDING"},
    "INCLUSIVE": {"PENDING", "CLEARED", "RETURNED"},
}

# --- charge_off_pricing ----------------------------------------------------
RECOVERY_FEE_TIER_1_MAX_CENTS = 100000
RECOVERY_FEE_TIER_1_BPS = 500
RECOVERY_FEE_TIER_2_MAX_CENTS = 500000
RECOVERY_FEE_TIER_2_BPS = 350
RECOVERY_FEE_TIER_3_BPS = 200
RECOVERY_REFERRAL_MIN_CENTS = 25000

# --- global constants ------------------------------------------------------
FUNDING_MAX_TOTAL_ATTEMPTS = 5
MULE_CLOSURE_NOTICE_DAYS = 10
PRESERVATION_BUFFER_DAYS = 3

ACCOUNT_TRACKED_FIELDS = (
    "lifecycle_status",
    "access_posture",
    "risk_score",
    "risk_score_basis",
    "risk_band",
    "ato_indicator_codes",
    "ato_score",
    "step_up_failure_count",
    "ledger_balance_cents",
    "available_balance_cents",
    "charged_off_amount_cents",
    "closure_scheduled_at",
    "closure_reason",
)


def snapshot_account(acct):
    snap = {}
    for f in ACCOUNT_TRACKED_FIELDS:
        v = acct.get(f)
        snap[f] = list(v) if isinstance(v, list) else v
    return snap


def bump_if_dirty(acct, snap):
    for f in ACCOUNT_TRACKED_FIELDS:
        v = acct.get(f)
        old = snap.get(f)
        if isinstance(v, list) or isinstance(old, list):
            if list(v or []) != list(old or []):
                touch(acct)
                return True
        elif v != old:
            touch(acct)
            return True
    return False


# --------------------------------------------------------------------------
# Derived aggregates
# --------------------------------------------------------------------------
def account_items(account_id):
    return [i for i in db.deposit_items.values() if i["account_id"] == account_id]


def holds_of_item(item_id):
    return [h for h in db.check_holds.values() if h["deposit_item_id"] == item_id]


def account_of_hold(hold):
    item = db.deposit_items.get(hold["deposit_item_id"])
    if item is None:
        return None
    return item["account_id"]


def active_holds_for_account(account_id):
    out = []
    for h in db.check_holds.values():
        if h["status"] != "ACTIVE":
            continue
        if account_of_hold(h) == account_id:
            out.append(h)
    return sorted(
        out,
        key=lambda h: (
            h["created_at"],
            db.deposit_items[h["deposit_item_id"]]["created_at"],
            h["_seq"],
        ),
    )


def held_amount_cents(account_id):
    return sum(h["held_amount_cents"] for h in active_holds_for_account(account_id))


def case_account_set(case):
    ids = [case["primary_account_id"]]
    for aid in case.get("cycle_account_ids") or []:
        if aid not in ids:
            ids.append(aid)
    return ids


def compute_case_exposure(case):
    total = 0
    for aid in case_account_set(case):
        if aid in db.accounts:
            total += held_amount_cents(aid)
    return total


def recompute_case_exposure(case):
    """Recompute and bump version when the figure actually moved."""
    new_value = compute_case_exposure(case)
    if case.get("exposure_at_risk_cents") != new_value:
        case["exposure_at_risk_cents"] = new_value
        touch(case)


def recompute_cases_for_account(account_id):
    for case in db.fraud_cases.values():
        if case["status"] not in ("OPENED", "INVESTIGATING"):
            continue
        if account_id in case_account_set(case):
            recompute_case_exposure(case)


# --------------------------------------------------------------------------
# Customer computed fields
# --------------------------------------------------------------------------
PRESERVATION_STATUSES = ("RECEIVED", "UNDER_LEGAL_REVIEW", "PRODUCED")


def preservation_hold_active(customer_id):
    clock = now()
    for s in db.subpoenas.values():
        if s["customer_id"] != customer_id:
            continue
        if s["status"] not in PRESERVATION_STATUSES:
            continue
        if clock < s["preservation_end_at"]:
            return True
    return False


def open_fraud_case_count(customer_id):
    count = 0
    for case in db.fraud_cases.values():
        if case["status"] not in ("OPENED", "INVESTIGATING"):
            continue
        acct = db.accounts.get(case["primary_account_id"])
        if acct is not None and acct["customer_id"] == customer_id:
            count += 1
    return count


# --------------------------------------------------------------------------
# new_account_risk_score
# --------------------------------------------------------------------------
def _risk_band(score):
    if score >= RISK_BAND_HIGH_MIN:
        return "HIGH"
    if score >= RISK_BAND_ELEVATED_MIN:
        return "ELEVATED"
    return "STANDARD"


def _funding_state(account_id):
    sources = [f for f in db.funding_sources.values() if f["account_id"] == account_id]
    if any(f["verification_status"] == "VERIFIED" for f in sources):
        return "VERIFIED"
    if any(
        f["verification_status"] in ("DECLARED", "MICRO_DEPOSIT_SENT", "FAILED_ATTEMPT")
        for f in sources
    ):
        return "PENDING"
    return "NONE"


def _risk_link_count(account_id):
    count = 0
    for link in db.account_links.values():
        if link["from_account_id"] != account_id and link["to_account_id"] != account_id:
            continue
        if link["link_type"] not in RISK_LINK_TYPES:
            continue
        if link["confidence_bps"] >= LINK_CONFIDENCE_MIN_BPS:
            count += 1
    return count


def apply_risk_score(acct, variant):
    customer = db.customers.get(acct["customer_id"])
    kyc = customer["kyc_tier"] if customer else "TIER_2"
    watchlist = bool(customer["watchlist_hit"]) if customer else False

    if variant == "PROVISIONAL_AT_OPEN":
        funding_state = "NONE"
        risk_link_count = 0
    else:
        funding_state = _funding_state(acct["id"])
        risk_link_count = _risk_link_count(acct["id"])

    link_points = min(LINK_POINTS_CAP, LINK_POINTS_PER_RISK_LINK * risk_link_count)
    raw = (
        KYC_TIER_POINTS[kyc]
        + FUNDING_POINTS[funding_state]
        + CHANNEL_POINTS[acct["open_channel"]]
        + (WATCHLIST_POINTS if watchlist else 0)
        + link_points
    )
    score = min(100, max(0, raw))
    acct["risk_score"] = score
    acct["risk_band"] = _risk_band(score)
    acct["risk_score_basis"] = variant
    return score


def refresh_risk(acct):
    apply_risk_score(acct, "REFRESHED")


# --------------------------------------------------------------------------
# ato_indicator_score
# --------------------------------------------------------------------------
def ato_score_for(codes):
    return min(100, sum(INDICATOR_WEIGHTS[c] for c in codes))


# --------------------------------------------------------------------------
# check_hold_schedule
# --------------------------------------------------------------------------
def account_age_days(acct, clock):
    delta = clock - acct["opened_at"]
    return int(delta.total_seconds() // 86400)


def choose_hold_type(item, acct, clock):
    if item["item_type"] == "ACH":
        return "STANDARD"
    if account_age_days(acct, clock) < NEW_ACCOUNT_DAYS:
        return "EXCEPTION_NEW_ACCOUNT"
    if item["amount_cents"] > LARGE_DEPOSIT_CENTS:
        return "EXCEPTION_LARGE_DEPOSIT"
    if acct["risk_band"] == "HIGH":
        return "EXCEPTION_RISK"
    return "STANDARD"


# --------------------------------------------------------------------------
# hold_override_loss_exposure
# --------------------------------------------------------------------------
def price_exposure(review):
    hold = db.check_holds.get(review["check_hold_id"])
    account_id = account_of_hold(hold) if hold else None
    scope = active_holds_for_account(account_id) if account_id else []
    total = 0
    for h in scope:
        item = db.deposit_items[h["deposit_item_id"]]
        rate = RETURN_RATE_BPS[item["item_type"]]
        total += bps(h["held_amount_cents"], rate)
    review["loss_exposure_cents"] = total
    acct = db.accounts.get(account_id)
    band = acct["risk_band"] if acct else "STANDARD"
    review["adjusted_exposure_cents"] = bps(total, RISK_MULT_BPS[band])


# --------------------------------------------------------------------------
# kiting_cycle_score
# --------------------------------------------------------------------------
def kiting_scan(account_id, mode, window_start, window_end):
    qualifying = QUALIFYING_STATUSES[mode]
    edges = []
    for item in db.deposit_items.values():
        if item["item_type"] != "CHECK":
            continue
        if not item.get("drawee_account_id"):
            continue
        if not (window_start <= item["deposit_at"] < window_end):
            continue
        if item["status"] not in qualifying:
            continue
        edges.append(item)

    adjacency = {}
    for item in edges:
        adjacency.setdefault(item["drawee_account_id"], set()).add(item["account_id"])

    candidates = []

    def dfs(path, visited):
        current = path[-1]
        for nxt in sorted(adjacency.get(current, ())):
            if nxt == account_id:
                if len(path) >= 2:
                    candidates.append(list(path))
                continue
            if nxt in visited:
                continue
            if len(path) + 1 > CYCLE_MAX_DEPTH:
                continue
            path.append(nxt)
            visited.add(nxt)
            dfs(path, visited)
            path.pop()
            visited.discard(nxt)

    dfs([account_id], {account_id})

    chosen = None
    if candidates:
        def sort_key(cycle):
            stamps = sorted(
                db.accounts[a]["created_at"] for a in cycle if a in db.accounts
            )
            return (len(cycle), stamps)

        best = None
        best_key = None
        for cycle in candidates:
            key = sort_key(cycle)
            if best_key is None or key < best_key:
                best_key = key
                best = cycle
        chosen = best

    if not chosen:
        cycle_length = 0
        cycle_account_ids = []
        qualifying_item_count = 0
        deposited_cents = 0
        uncollected_cents = 0
    else:
        cycle_length = len(chosen)
        cycle_account_ids = list(chosen)
        edge_pairs = set()
        for idx in range(len(chosen)):
            tail = chosen[idx]
            head = chosen[(idx + 1) % len(chosen)]
            # directed edge tail -> head means drawee=tail, account=head
            edge_pairs.add((tail, head))
        matched = [
            i
            for i in edges
            if (i["drawee_account_id"], i["account_id"]) in edge_pairs
        ]
        qualifying_item_count = len(matched)
        deposited_cents = sum(i["amount_cents"] for i in matched)
        uncollected_cents = sum(held_amount_cents(a) for a in cycle_account_ids)

    if deposited_cents == 0:
        ratio_bps = 0
    else:
        ratio_bps = int((10000 * uncollected_cents) // deposited_cents)

    raw = (
        (CYCLE_BASE[cycle_length] if cycle_length > 0 else 0)
        + VELOCITY_WEIGHT * qualifying_item_count
        + round_half_up(Decimal(UNCOLLECTED_WEIGHT * ratio_bps) / Decimal(10000))
    )
    score = min(100, raw)
    return {
        "kiting_score": score,
        "cycle_length": cycle_length,
        "cycle_account_ids": cycle_account_ids,
        "qualifying_item_count": qualifying_item_count,
        "deposited_cents": deposited_cents,
        "uncollected_cents": uncollected_cents,
        "uncollected_ratio_bps": ratio_bps,
        "detected": score >= KITING_OPEN_THRESHOLD,
    }


# --------------------------------------------------------------------------
# charge_off_pricing
# --------------------------------------------------------------------------
def fee_rate_for(base_net_cents):
    if base_net_cents <= RECOVERY_FEE_TIER_1_MAX_CENTS:
        return RECOVERY_FEE_TIER_1_BPS
    if base_net_cents <= RECOVERY_FEE_TIER_2_MAX_CENTS:
        return RECOVERY_FEE_TIER_2_BPS
    return RECOVERY_FEE_TIER_3_BPS


def outstanding_loss(co):
    return (
        co["net_charge_off_cents"]
        - co["principal_recovered_cents"]
        - co["fee_recovered_cents"]
    )


# --------------------------------------------------------------------------
# bsa_aggregate_amount
# --------------------------------------------------------------------------
def bsa_aggregate_amount(case):
    account_ids = set(case_account_set(case))
    total = 0
    for item in db.deposit_items.values():
        if item["account_id"] in account_ids and item["status"] in ("PENDING", "RETURNED"):
            total += item["amount_cents"]
    return total


# --------------------------------------------------------------------------
# Shared cascades
# --------------------------------------------------------------------------
def supersede_reviews_for_hold(hold_id, exclude_id=None):
    for r in db.override_reviews.values():
        if r["check_hold_id"] != hold_id:
            continue
        if exclude_id is not None and r["id"] == exclude_id:
            continue
        if r["status"] in ("DRAFT", "SUBMITTED", "RETURNED_FOR_INFO", "APPROVED"):
            r["status"] = "SUPERSEDED"
            touch(r)


def days(n):
    return timedelta(days=n)
