"""Domain services: computed fields, serializers, calculations, cascades.

All structural rules trace to SCAFFOLD.yaml §1.1-§1.3 and PRD §3:
- match_computation (§1.3, PRD §3.4)
- shopper_match_usage (§1.3)
- token_denomination_split (§1.3, PRD §3.4)
- reimbursement_amount provisional/final (§1.3, PRD §3.6)
- program_liability forward/realized (§1.3, PRD §3.8)
- market_day_reconciliation (§1.3, PRD §3.2)
- settlement_sweep (§1.3, PRD §3.8)
"""

from datetime import timezone

from db import STORE, touch
from logical_clock import _parse_iso, format_iso

# ---------------------------------------------------------------------------
# Constants (SCAFFOLD §1.3 constants blocks)
# ---------------------------------------------------------------------------

MATCH_PARAMS = {
    "SNAP": {"ratio_num": 1, "ratio_den": 1, "daily_cap": 2000, "season_cap": 20000},
    "WIC": {"ratio_num": 1, "ratio_den": 2, "daily_cap": 1000, "season_cap": 10000},
    "SENIOR": {"ratio_num": 1, "ratio_den": 1, "daily_cap": 1500, "season_cap": 15000},
}
BASE_DENOMINATIONS = [500, 100]
MATCH_DENOMINATIONS = [100]
FEE_BPS = 250
RECONCILE_TOLERANCE_CENTS = 500
SUBMISSION_WINDOW_DAYS = 7
RESUBMIT_GRACE_HOURS = 72

NON_TERMINAL_SUBMISSION_STATUSES = {"SUBMITTED", "VERIFIED", "DISPUTED", "APPROVED"}


# ---------------------------------------------------------------------------
# FK navigation helpers
# ---------------------------------------------------------------------------

def market_of_batch(batch):
    return STORE["markets"].get(batch["market_id"])


def program_id_of_market(market):
    return market["program_id"] if market else None


def market_day_of_issuance(issuance):
    return STORE["market_days"].get(issuance["market_day_id"])


def program_id_of_market_day(day):
    market = STORE["markets"].get(day["market_id"]) if day else None
    return market["program_id"] if market else None


def program_id_of_issuance(issuance):
    return program_id_of_market_day(market_day_of_issuance(issuance))


def program_id_of_token(token):
    issuance = STORE["issuances"].get(token["issuance_id"])
    return program_id_of_issuance(issuance) if issuance else None


def program_id_of_submission(sub):
    vendor = STORE["vendors"].get(sub["vendor_id"])
    if not vendor:
        return None
    market = STORE["markets"].get(vendor["market_id"])
    return market["program_id"] if market else None


def tokens_of_issuance(issuance_id):
    return [t for t in STORE["tokens"].values() if t["issuance_id"] == issuance_id]


def tokens_of_batch(batch_id):
    return [t for t in STORE["tokens"].values() if t["token_batch_id"] == batch_id]


def tokens_of_submission(submission_id):
    out = [t for t in STORE["tokens"].values() if t.get("submission_id") == submission_id]
    out.sort(key=lambda t: t["serial_number"])
    return out


def issuances_of_shopper(shopper_id):
    return [i for i in STORE["issuances"].values() if i["shopper_id"] == shopper_id]


def submissions_of_vendor(vendor_id):
    return [s for s in STORE["submissions"].values() if s["vendor_id"] == vendor_id]


def market_day_token_pool(day):
    """Tokens minted by this day's ACTIVE issuances (reconciliation input set)."""
    out = []
    for issuance in STORE["issuances"].values():
        if issuance["market_day_id"] == day["id"] and issuance["status"] == "ACTIVE":
            out.extend(tokens_of_issuance(issuance["id"]))
    return out


# ---------------------------------------------------------------------------
# Computed fields (SCAFFOLD §1.1 source: computed / §1.3)
# ---------------------------------------------------------------------------

def program_pool_remaining(program):
    spent = 0
    for issuance in STORE["issuances"].values():
        if issuance["status"] != "ACTIVE":
            continue
        if program_id_of_issuance(issuance) == program["id"]:
            spent += issuance["match_cents"]
    return program["match_pool_budget_cents"] - spent


def program_liabilities(program):
    forward = 0
    realized = 0
    for token in STORE["tokens"].values():
        if program_id_of_token(token) != program["id"]:
            continue
        if token["status"] in ("ISSUED", "REDEEMED", "FLAGGED"):
            forward += token["denomination_cents"]
        if token["status"] in ("REDEEMED", "SETTLED"):
            realized += token["denomination_cents"]
    return forward, realized


def program_paid_out(program):
    total = 0
    for sub in STORE["submissions"].values():
        if sub["status"] == "PAID" and program_id_of_submission(sub) == program["id"]:
            total += sub.get("paid_amount_cents") or 0
    return total


def vendor_payable(vendor):
    approved = 0
    paid = 0
    for sub in submissions_of_vendor(vendor["id"]):
        if sub["status"] in ("APPROVED", "PAID"):
            approved += sub.get("approved_amount_cents") or 0
        if sub["status"] == "PAID":
            paid += sub.get("paid_amount_cents") or 0
    return approved - paid


def shopper_season_match_used(shopper):
    total = 0
    for issuance in issuances_of_shopper(shopper["id"]):
        if issuance["status"] == "ACTIVE":
            total += issuance["match_cents"]
    return total


def shopper_day_match_used(shopper_id, date_str):
    """Match used on the calendar date of a MarketDay (SCAFFOLD shopper_match_usage)."""
    total = 0
    for issuance in issuances_of_shopper(shopper_id):
        if issuance["status"] != "ACTIVE":
            continue
        day = STORE["market_days"].get(issuance["market_day_id"])
        if day and day["date"] == date_str:
            total += issuance["match_cents"]
    return total


def market_day_totals(day):
    """(issued, voided, redeemed, variance) over tokens of ACTIVE issuances."""
    issued = voided = redeemed = 0
    for token in market_day_token_pool(day):
        denom = token["denomination_cents"]
        issued += denom
        if token["status"] == "VOIDED":
            voided += denom
        elif token["status"] in ("REDEEMED", "SETTLED"):
            redeemed += denom
    return issued, voided, redeemed, issued - voided - redeemed


def batch_next_serial(batch):
    minted = len(tokens_of_batch(batch["id"]))
    return batch["serial_start"] + minted


# ---------------------------------------------------------------------------
# Serializers (SCAFFOLD §1.1 field lists + PRD §2.5 common fields)
# ---------------------------------------------------------------------------

def _common(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def serialize_program(p):
    forward, realized = program_liabilities(p)
    out = {
        "name": p["name"],
        "season_start": p["season_start"],
        "season_end": p["season_end"],
        "match_pool_budget_cents": p["match_pool_budget_cents"],
        "match_pool_remaining_cents": program_pool_remaining(p),
        "liability_forward_cents": forward,
        "liability_realized_cents": realized,
        "paid_out_cents": program_paid_out(p),
    }
    out.update(_common(p))
    return out


def serialize_market(m):
    out = {"program_id": m["program_id"], "name": m["name"], "city": m["city"]}
    out.update(_common(m))
    return out


def serialize_vendor(v):
    out = {
        "market_id": v["market_id"],
        "legal_name": v["legal_name"],
        "stall_number": v["stall_number"],
        "status": v["status"],
        "payable_cents": vendor_payable(v),
    }
    out.update(_common(v))
    return out


def serialize_shopper(s):
    out = {
        "program_id": s["program_id"],
        "external_benefit_ref": s["external_benefit_ref"],
        "benefit_type": s["benefit_type"],
        "status": s["status"],
        "season_match_used_cents": shopper_season_match_used(s),
    }
    out.update(_common(s))
    return out


def serialize_market_day(d):
    issued, voided, redeemed, variance = market_day_totals(d)
    out = {
        "market_id": d["market_id"],
        "date": d["date"],
        "opens_at": d["opens_at"],
        "closes_at": d["closes_at"],
        "status": d["status"],
        "issued_value_cents": issued,
        "voided_value_cents": voided,
        "redeemed_value_cents": redeemed,
        "variance_cents": variance,
    }
    out.update(_common(d))
    return out


def serialize_token_batch(b):
    out = {
        "market_id": b["market_id"],
        "kind": b["kind"],
        "denomination_cents": b["denomination_cents"],
        "serial_start": b["serial_start"],
        "serial_end": b["serial_end"],
        "status": b["status"],
        "next_serial": batch_next_serial(b),
    }
    out.update(_common(b))
    return out


def serialize_issuance(i):
    out = {
        "shopper_id": i["shopper_id"],
        "market_day_id": i["market_day_id"],
        "benefit_charged_cents": i["benefit_charged_cents"],
        "base_value_cents": i["base_value_cents"],
        "match_cents": i["match_cents"],
        "status": i["status"],
    }
    out.update(_common(i))
    return out


def serialize_token(t):
    out = {
        "serial_number": t["serial_number"],
        "kind": t["kind"],
        "denomination_cents": t["denomination_cents"],
        "issuance_id": t["issuance_id"],
        "token_batch_id": t["token_batch_id"],
        "status": t["status"],
        "redeemed_vendor_id": t.get("redeemed_vendor_id"),
        "submission_id": t.get("submission_id"),
    }
    out.update(_common(t))
    return out


def serialize_submission(s):
    out = {
        "vendor_id": s["vendor_id"],
        "market_day_id": s["market_day_id"],
        "token_ids": [t["id"] for t in tokens_of_submission(s["id"])],
        "status": s["status"],
        "provisional_amount_cents": s.get("provisional_amount_cents"),
        "approved_amount_cents": s.get("approved_amount_cents"),
        "paid_amount_cents": s.get("paid_amount_cents"),
        "approved_at": s.get("approved_at"),
        "disputed_at": s.get("disputed_at"),
    }
    out.update(_common(s))
    return out


def serialize_fraud_case(c):
    out = {
        "vendor_id": c.get("vendor_id"),
        "shopper_id": c.get("shopper_id"),
        "token_id": c.get("token_id"),
        "reason": c["reason"],
        "origin": c["origin"],
        "status": c["status"],
    }
    out.update(_common(c))
    return out


def serialize_settlement_run(r):
    out = {
        "program_id": r["program_id"],
        "cutoff_at": r["cutoff_at"],
        "swept_submission_ids": list(r["swept_submission_ids"]),
        "total_paid_cents": r["total_paid_cents"],
        "vendor_payment_count": r["vendor_payment_count"],
    }
    out.update(_common(r))
    return out


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------

def compute_match_cents(shopper, program, day, benefit_charged_cents):
    """SCAFFOLD match_computation: pinned, non-commutative evaluation order."""
    params = MATCH_PARAMS[shopper["benefit_type"]]
    raw_match = (benefit_charged_cents * params["ratio_num"]) // params["ratio_den"]
    day_remaining = params["daily_cap"] - shopper_day_match_used(shopper["id"], day["date"])
    season_remaining = params["season_cap"] - shopper_season_match_used(shopper)
    pool_remaining = program_pool_remaining(program)
    capped = min(raw_match, day_remaining, season_remaining, pool_remaining)
    if capped <= 0:
        return 0
    return (capped // 100) * 100


def denomination_plan(benefit_charged_cents, match_cents):
    """SCAFFOLD token_denomination_split: greedy largest-first.

    Returns {(kind, denomination_cents): count}.
    """
    plan = {}
    n500 = benefit_charged_cents // 500
    rem = benefit_charged_cents - 500 * n500
    n100 = rem // 100
    if n500:
        plan[("BASE", 500)] = plan.get(("BASE", 500), 0) + n500
    if n100:
        plan[("BASE", 100)] = plan.get(("BASE", 100), 0) + n100
    n_match = match_cents // 100
    if n_match:
        plan[("MATCH", 100)] = plan.get(("MATCH", 100), 0) + n_match
    return plan


def batch_pool(market_id, kind, denomination):
    """ACTIVE batches of the market for (kind, denomination), selector order:
    serial_start ASC, created_at ASC, insertion seq tie-break (never id)."""
    pool = [
        b for b in STORE["token_batches"].values()
        if b["market_id"] == market_id
        and b["kind"] == kind
        and b["denomination_cents"] == denomination
        and b["status"] == "ACTIVE"
    ]
    pool.sort(key=lambda b: (b["serial_start"], b["created_at"], b["_seq"]))
    return pool


def batch_remaining_serials(batch):
    return batch["serial_end"] - batch["serial_start"] + 1 - len(tokens_of_batch(batch["id"]))


def provisional_line_amount(denomination_cents):
    """Per-line round-half-up withholding (reimbursement_amount provisional)."""
    num = denomination_cents * (10000 - FEE_BPS)
    return (num + 5000) // 10000


def compute_provisional_amount(tokens):
    return sum(provisional_line_amount(t["denomination_cents"]) for t in tokens)


def compute_approved_amount(tokens):
    """Aggregate variant: sum first, withhold once, round half up once."""
    face = sum(t["denomination_cents"] for t in tokens if t["status"] == "REDEEMED")
    return (face * (10000 - FEE_BPS) + 5000) // 10000


# ---------------------------------------------------------------------------
# Cascades / side effects
# ---------------------------------------------------------------------------

def day_of_token(token):
    issuance = STORE["issuances"].get(token["issuance_id"])
    if issuance:
        return STORE["market_days"].get(issuance["market_day_id"])
    return None


def _maybe_flip(day, variance_before):
    """Automatic CLOSED <-> VARIANCE_FLAGGED transition, fired only when this
    recompute shows the variance CROSSING the reconciliation tolerance
    (PRD §3.1 'crosses ... in either direction'; §3.6 'push a CLOSED day over
    the tolerance'). A day already out of tolerance does not flip on a
    recompute that leaves variance unchanged."""
    if variance_before is None:
        return
    if day["status"] not in ("CLOSED", "VARIANCE_FLAGGED"):
        return
    _, _, _, after = market_day_totals(day)
    if day["status"] == "CLOSED" and abs(variance_before) <= RECONCILE_TOLERANCE_CENTS < abs(after):
        day["status"] = "VARIANCE_FLAGGED"
    elif day["status"] == "VARIANCE_FLAGGED" and abs(variance_before) > RECONCILE_TOLERANCE_CENTS >= abs(after):
        day["status"] = "CLOSED"


def _day_variance_if_closed_family(day):
    if day is not None and day["status"] in ("CLOSED", "VARIANCE_FLAGGED"):
        return market_day_totals(day)[3]
    return None


def change_token_status(token, new_status, detach=False):
    """Single-token status mutation with full ledger side effects: token
    version bump, issuing-day totals recompute (with crossing auto-flip) and
    the day's own version bump."""
    day = day_of_token(token)
    before = _day_variance_if_closed_family(day)
    token["status"] = new_status
    if detach:
        token["submission_id"] = None
    touch(token)
    if day is not None:
        _maybe_flip(day, before)
        touch(day)


def bulk_change_tokens(tokens, new_status_for, detach=False):
    """Multi-token cascade (batch recall, reject quarantine, settlement of
    approved claims). Each token bumps its own version; each affected market
    day recomputes (crossing auto-flip evaluated on the operation's net
    before/after) and bumps its version exactly once per cascade (SCAFFOLD
    recall side effect: 'Each affected Token.version and MarketDay.version
    increments by 1')."""
    tokens = list(tokens)
    days = {}
    befores = {}
    for token in tokens:
        day = day_of_token(token)
        if day is not None and day["id"] not in days:
            days[day["id"]] = day
            befores[day["id"]] = _day_variance_if_closed_family(day)
    for token in tokens:
        new_status = new_status_for(token)
        if new_status is not None:
            token["status"] = new_status
        if detach:
            token["submission_id"] = None
        touch(token)
    for day_id, day in days.items():
        _maybe_flip(day, befores.get(day_id))
        touch(day)


def touch_day_and_autoflip(day):
    """Plain day touch (kept for call sites where no token status changed)."""
    touch(day)


def touch_token_day(token):
    day = day_of_token(token)
    if day is not None:
        touch(day)


def flag_token(token):
    """Token -> FLAGGED from REDEEMED (double-spend defense)."""
    change_token_status(token, "FLAGGED")


def open_auto_double_spend_case(token, attempting_vendor_id):
    """AUTO_DOUBLE_SPEND FraudCase (Token state machine, SCAFFOLD §1.2)."""
    from db import stamp_new
    case = stamp_new({
        "vendor_id": None,
        "shopper_id": None,
        "token_id": token["id"],
        "reason": f"Double-spend attempt by vendor {attempting_vendor_id}",
        "origin": "AUTO_DOUBLE_SPEND",
        "status": "OPEN",
    })
    STORE["fraud_cases"][case["id"]] = case
    return case


def reject_submission_quarantine(sub):
    """Shared token-quarantine cascade for REJECTED transitions (PRD §3.6):
    every attached token with status REDEEMED -> FLAGGED and is detached;
    other attached tokens are detached; affected days recompute (with
    crossing auto-flip) and bump their version once per cascade."""
    attached = tokens_of_submission(sub["id"])
    bulk_change_tokens(
        attached,
        lambda t: "FLAGGED" if t["status"] == "REDEEMED" else None,
        detach=True,
    )
    sub["status"] = "REJECTED"
    touch(sub)


def date_to_utc_start(date_str):
    """YYYY-MM-DD -> aware UTC datetime at 00:00:00 (season window compare)."""
    return _parse_iso(date_str + "T00:00:00Z")


def iso(dt):
    return format_iso(dt.astimezone(timezone.utc))
