"""Business logic: aggregates, allocation waterfall, progress ratios, entry
posting, auto-completion, rollforward, disclosure assembly."""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

from clock import CLOCK, now_ts
from db import STORE, make_rec, mark, sort_created
from errors import ApiError, ERR_PERIOD_CLOSED

ENTRY_COUNTED = ("POSTED", "LOCKED")

# ---------------------------------------------------------------------------
# Derived aggregates (recomputed from the append-only ledger on every read)
# ---------------------------------------------------------------------------


def pobs_of(contract_id):
    return sort_created(p for p in STORE.pobs.values() if p["contract_id"] == contract_id)


def live_pobs(contract_id):
    return [p for p in pobs_of(contract_id) if p["status"] != "CANCELLED"]


def pob_costs(pob_id):
    return sum(c["amount_cents"] for c in STORE.cost_entries.values() if c["pob_id"] == pob_id)


def pob_recognized(pob_id):
    return sum(e["amount_cents"] for e in STORE.entries.values()
               if e["pob_id"] == pob_id and e["status"] in ENTRY_COUNTED)


def contract_recognized(contract_id):
    return sum(e["amount_cents"] for e in STORE.entries.values()
               if e["contract_id"] == contract_id and e["status"] in ENTRY_COUNTED)


def contract_billed(contract_id):
    # Every invoice is created ISSUED; a VOIDED invoice no longer contributes.
    return sum(i["amount_cents"] for i in STORE.invoices.values()
               if i["contract_id"] == contract_id and i["status"] == "ISSUED")


def allocated_total(contract_id):
    return sum(p["allocated_amount_cents"] for p in live_pobs(contract_id))


def balances(contract):
    billed = contract_billed(contract["id"])
    recognized = contract_recognized(contract["id"])
    return billed, recognized, max(0, billed - recognized), max(0, recognized - billed)


def period_contains(period, d):
    return date.fromisoformat(period["start_date"]) <= d < date.fromisoformat(period["end_date"])


def period_for_date(d):
    for p in STORE.periods.values():
        if period_contains(p, d):
            return p
    return None


def open_period_for(d):
    """Period covering date d whose status is OPEN or REOPENED, else None."""
    p = period_for_date(d)
    if p is not None and p["status"] in ("OPEN", "REOPENED"):
        return p
    return None


def require_open_period(d, message="Posting date falls in a CLOSED period or in no accounting period"):
    p = open_period_for(d)
    if p is None:
        raise ApiError(ERR_PERIOD_CLOSED, 409, message)
    return p


def period_recognized_total(period):
    return sum(e["amount_cents"] for e in STORE.entries.values()
               if e["status"] in ENTRY_COUNTED and period_contains(period, date.fromisoformat(e["posting_date"])))


# ---------------------------------------------------------------------------
# Over-time progress
# ---------------------------------------------------------------------------


def pob_ratio(pob):
    """Unrounded progress ratio, clamped to [0, 1]. POINT_IN_TIME -> 0."""
    pat = pob["recognition_pattern"]
    if pat == "OVER_TIME_INPUT_COST":
        est = pob.get("estimated_total_cost_cents")
        if not est:
            return Decimal(0)
        r = Decimal(pob_costs(pob["id"])) / Decimal(est)
    elif pat == "OVER_TIME_STRAIGHT_LINE":
        start = date.fromisoformat(pob["service_start_date"])
        end = date.fromisoformat(pob["service_end_date"])
        total_days = (end - start).days
        if total_days <= 0:
            return Decimal(0)
        elapsed = (min(CLOCK.today(), end) - start).days
        if elapsed < 0:
            elapsed = 0
        r = Decimal(elapsed) / Decimal(total_days)
    else:
        return Decimal(0)
    if r > 1:
        r = Decimal(1)
    if r < 0:
        r = Decimal(0)
    return r


def recognition_target(pob, ratio=None):
    """round_half_up(allocated * ratio); the ratio itself is never rounded."""
    if ratio is None:
        ratio = pob_ratio(pob)
    return int((Decimal(pob["allocated_amount_cents"]) * ratio).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def progress_pct(pob):
    r = pob_ratio(pob)
    return float(r.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Entry posting, POB lifecycle, contract auto-completion
# ---------------------------------------------------------------------------


def post_entry(contract, pob, entry_type, origin, amount_cents, posting_date, reversed_entry_id=None):
    rec = make_rec(STORE.entries, {
        "contract_id": contract["id"],
        "pob_id": pob["id"],
        "accounting_period_id": period_for_date(posting_date)["id"],
        "reversed_entry_id": reversed_entry_id,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "posting_date": posting_date.isoformat(),
        "origin": origin,
        "status": "POSTED",
    }, lean=True)
    if entry_type in ("RECOGNITION", "CATCH_UP_ADJUSTMENT") and pob["status"] == "PENDING":
        pob["status"] = "IN_PROGRESS"
        mark(pob)
    return rec


def maybe_satisfy_overtime(pob):
    """Over-time POBs flip to SATISFIED when the ratio reaches exactly 1.0
    (evaluated after a cost entry or a recognize run)."""
    if pob["status"] in ("PENDING", "IN_PROGRESS") and pob_ratio(pob) == Decimal(1):
        pob["status"] = "SATISFIED"
        pob["satisfied_at"] = now_ts()
        mark(pob)
        return True
    return False


def evaluate_auto_completion(contract):
    """ACTIVE -> COMPLETED when every non-CANCELLED POB is SATISFIED and
    billed == recognized. System transition: does not bump Contract.version."""
    if contract["status"] != "ACTIVE":
        return
    pool = live_pobs(contract["id"])
    billed, recognized, _, _ = balances(contract)
    if all(p["status"] == "SATISFIED" for p in pool) and billed == recognized:
        contract["status"] = "COMPLETED"
        contract["completed_at"] = now_ts()
        mark(contract, bump=False)


# ---------------------------------------------------------------------------
# SSP allocation waterfall (round per line, residual to greatest-SSP POB)
# ---------------------------------------------------------------------------


def compute_allocation(pool, total_cents):
    """pool pre-sorted by (created_at, seq). Returns {pob_id: amount}."""
    total_ssp = sum(p["ssp_cents"] for p in pool)
    if not pool or total_ssp == 0:
        return {}
    out = {}
    for p in pool:
        raw = Decimal(total_cents * p["ssp_cents"]) / Decimal(total_ssp)
        out[p["id"]] = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    residual = total_cents - sum(out.values())
    if residual != 0:
        target = max(pool, key=lambda p: p["ssp_cents"])  # ties: earliest created_at
        out[target["id"]] += residual
    return out


def run_full_allocation(contract, transaction_price):
    pool = live_pobs(contract["id"])
    alloc = compute_allocation(pool, transaction_price)
    for p in pool:
        if p["allocated_amount_cents"] != alloc[p["id"]]:
            p["allocated_amount_cents"] = alloc[p["id"]]
            mark(p)
    return alloc


# ---------------------------------------------------------------------------
# Catch-up evaluation (modification CUMULATIVE_CATCH_UP / estimate approval)
# ---------------------------------------------------------------------------


def plan_catch_ups(contract, new_fixed, new_vc):
    """Prospectively compute the post-approval allocation and catch-up entries
    without mutating anything. Returns (pool_allocs, catch_ups) where catch_ups
    is a list of (pob, signed_amount)."""
    new_tx = new_fixed + new_vc
    pool = live_pobs(contract["id"])
    alloc = compute_allocation(pool, new_tx)
    catch_ups = []
    for p in pool:
        if p["recognition_pattern"] in ("OVER_TIME_INPUT_COST", "OVER_TIME_STRAIGHT_LINE"):
            ratio = pob_ratio(p)
            target = int((Decimal(alloc[p["id"]]) * ratio).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            delta = target - pob_recognized(p["id"])
            if delta != 0:
                catch_ups.append((p, delta))
    return alloc, catch_ups


def check_over_recognition(contract, alloc):
    for p in live_pobs(contract["id"]):
        if alloc[p["id"]] < pob_recognized(p["id"]):
            return True
    return False
