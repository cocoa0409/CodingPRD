"""Shared domain helpers: computed statuses, ledger math, overlap semantics,
serializers, and request-body validation utilities.

Validation priority order (PRD §2.9) is enforced by each route calling the
checks below in priority sequence; helpers here never raise on their own
unless named check_*.
"""

from datetime import timedelta, date
from decimal import Decimal

from errors import fail
from store import store, now, today
from util import (
    fmt_ts, parse_dt, parse_date, round_half_up_cents, money_mul_div,
    pct_of, ceil_div, whole_minutes,
)

# Calculation constants (SCAFFOLD §1.3)
CERT_VALIDITY_MONTHS = 12
OPERATING_OVERHEAD_CENTS = 120000
MAX_RATE_INCREASE_PCT = Decimal("0.10")
RATE_DEVIATION_FLAG_PCT = Decimal("0.05")
EARLY_CHECKIN_MINUTES = 15

BOOKING_TERMINAL = {"COMPLETED", "CANCELLED", "NO_SHOW", "PREEMPTED", "REJECTED"}


# ---------------------------------------------------------------------------
# Body access / format validation (priority 21)
# ---------------------------------------------------------------------------

class Body:
    """Thin wrapper over the request JSON object."""

    def __init__(self, raw):
        self.raw = raw if isinstance(raw, dict) else None

    def get(self, key, default=None):
        if self.raw is None:
            return default
        return self.raw.get(key, default)

    def has(self, key):
        return self.raw is not None and key in self.raw


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def validate_body(body, allowed, required, checkers):
    """Priority-21 field validation.
    allowed: iterable of permitted keys (unknown keys rejected).
    required: iterable of keys that must be present and non-null.
    checkers: dict key -> fn(value) -> bool (False => malformed).
    """
    if body.raw is None:
        if required:
            fail("ERR_INVALID_REQUEST", "Request body must be a JSON object with required fields")
        body.raw = {}
    for key in body.raw:
        if key not in allowed:
            fail("ERR_INVALID_REQUEST", "Unknown or system-managed field in request body: %s" % key)
    for key in required:
        if key not in body.raw or body.raw[key] is None:
            fail("ERR_INVALID_REQUEST", "Missing required field: %s" % key)
    for key, chk in checkers.items():
        if key in body.raw and body.raw[key] is not None:
            if not chk(body.raw[key]):
                fail("ERR_INVALID_REQUEST", "Field %s is malformed" % key)


def non_empty_str(v):
    return isinstance(v, str) and len(v.strip()) > 0


def email_ok(v):
    return isinstance(v, str) and len(v.strip()) > 0 and "@" in v and "." in v


def dt_ok(v):
    return parse_dt(v) is not None


def date_ok(v):
    return parse_date(v) is not None


# ---------------------------------------------------------------------------
# Computed statuses (PRD §2.4 / §2.10)
# ---------------------------------------------------------------------------

def training_effective_status(rec):
    if rec["status"] == "CERTIFIED" and rec.get("expires_at_dt") is not None:
        if rec["expires_at_dt"] <= now():
            return "EXPIRED"
    return rec["status"]


def grant_ledger(grant):
    enc = sum(
        b["encumbered_cents"] for b in store.bookings.values()
        if b.get("grant_id") == grant["id"] and b["status"] in ("APPROVED", "IN_PROGRESS")
    )
    used = sum(
        e["net_amount_cents"] for e in store.entries.values()
        if e.get("grant_id") == grant["id"]
        and e["kind"] in ("USAGE", "PENALTY")
        and e["status"] in ("PENDING", "BILLED", "PAID", "DISPUTED")
    )
    available = grant["budget_total_cents"] - enc - used
    return enc, used, available


def grant_status(grant):
    if grant.get("_closed"):
        return "CLOSED"
    if grant["_end_date"] < today():
        return "EXPIRED"
    _, _, available = grant_ledger(grant)
    if available <= 0:
        return "EXHAUSTED"
    return "ACTIVE"


def award_status(award):
    if award.get("_revoked"):
        return "REVOKED"
    if award["_valid_until"] <= now():
        return "EXPIRED"
    if award["remaining_amount_cents"] <= 0:
        return "EXHAUSTED"
    return "ACTIVE"


def contract_status(contract):
    if contract.get("_terminated"):
        return "TERMINATED"
    if contract["_coverage_end"] < today():
        return "EXPIRED"
    return "ACTIVE"


# ---------------------------------------------------------------------------
# Overlap semantics (PRD §3.2)
# ---------------------------------------------------------------------------

def buffered_interval(booking, instrument):
    """Half-open [start_at, end_at + booking_buffer_minutes)."""
    return (booking["_start_at"],
            booking["_end_at"] + timedelta(minutes=instrument["booking_buffer_minutes"]))


def half_open_conflict(s1, e1, s2, e2):
    return s1 < e2 and s2 < e1


def closed_conflict(s1, e1, s2, e2):
    """Closed-interval intersection: touching endpoints collide."""
    return s1 <= e2 and s2 <= e1


def booking_blocks(other, incoming_start, incoming_end, instrument):
    """Would APPROVED/IN_PROGRESS booking `other` conflict with an incoming
    [start, end) window on the same instrument (buffered half-open)?"""
    if other["status"] not in ("APPROVED", "IN_PROGRESS"):
        return False
    os_, oe = buffered_interval(other, instrument)
    is_, ie = incoming_start, incoming_end + timedelta(minutes=instrument["booking_buffer_minutes"])
    return half_open_conflict(os_, oe, is_, ie)


def downtime_conflicts(event, start_at, end_at):
    """Booking [start_at, end_at) vs downtime [start, end] closed-interval."""
    return closed_conflict(start_at, end_at, event["_start_at"], event["_end_at"])


def confirmed_downtime_conflict(instrument_id, start_at, end_at, exclude_event_id=None):
    for ev in store.downtime_events.values():
        if ev["instrument_id"] != instrument_id or ev["status"] != "CONFIRMED":
            continue
        if exclude_event_id and ev["id"] == exclude_event_id:
            continue
        if downtime_conflicts(ev, start_at, end_at):
            return True
    return False


def event_contains_now(ev):
    return ev["_start_at"] <= now() <= ev["_end_at"]


# ---------------------------------------------------------------------------
# Training checks
# ---------------------------------------------------------------------------

def find_training(user_id, instrument_id):
    """The (single) non-REVOKED training record for the pair, if any."""
    for rec in store.training_records.values():
        if rec["user_id"] == user_id and rec["instrument_id"] == instrument_id and rec["status"] != "REVOKED":
            return rec
    return None


def check_training(user_id, instrument, booking_end_at):
    """Priorities 12 & 13."""
    if not instrument.get("requires_training", True):
        return
    rec = find_training(user_id, instrument["id"])
    if rec is None or training_effective_status(rec) != "CERTIFIED":
        fail("ERR_TRAINING_REQUIRED", "No CERTIFIED training record for this user and instrument")
    if rec["expires_at_dt"] is None or not (rec["expires_at_dt"] > booking_end_at):
        fail("ERR_TRAINING_EXPIRED", "Certification does not cover the whole session")


# ---------------------------------------------------------------------------
# Rate sets / break-even / derived rates
# ---------------------------------------------------------------------------

def effective_rate_set_for_fy(fy):
    for rs in store.rate_sets.values():
        if rs["fiscal_year"] == fy and rs["status"] == "EFFECTIVE":
            return rs
    return None


def rate_line_for(rate_set, instrument_id):
    if not rate_set:
        return None
    for line in rate_set["lines"]:
        if line["instrument_id"] == instrument_id:
            return line
    return None


def fy_window(fy):
    return date(fy, 1, 1), date(fy, 12, 31)


def contract_intersects_fy(contract, fy):
    s, e = fy_window(fy)
    return contract["_coverage_start"] <= e and contract["_coverage_end"] >= s


def projected_cost_cents(instrument_id, fy):
    total = sum(
        c["annual_cost_cents"] for c in store.contracts.values()
        if c["instrument_id"] == instrument_id and contract_intersects_fy(c, fy)
    )
    return total + OPERATING_OVERHEAD_CENTS


def projected_revenue_cents(line):
    d = Decimal(int(line["internal_rate_cents_per_hour"])) * Decimal(str(line["projected_billable_hours"]))
    return round_half_up_cents(d)


def break_even_verdict(line, fy):
    revenue = projected_revenue_cents(line)
    cost = projected_cost_cents(line["instrument_id"], fy)
    return ("PASS" if revenue >= cost else "DEFICIT"), revenue, cost


def suggested_internal_rate(instrument_id, fy, carryforward_in_cents, projected_hours):
    adjusted = Decimal(projected_cost_cents(instrument_id, fy)) - Decimal(int(carryforward_in_cents))
    d = adjusted / Decimal(str(projected_hours))
    return round_half_up_cents(d)


def live_line_verdicts(rs):
    """line_verdicts mirrors `lines`; verdict comes from the stored review
    once submitted (WAIVED possible), else a live projected computation."""
    out = []
    for i, line in enumerate(rs["lines"]):
        verdict = None
        if rs.get("_verdicts") is not None and i < len(rs["_verdicts"]):
            verdict = rs["_verdicts"][i]
        if verdict is None:
            verdict, _, _ = break_even_verdict(line, rs["fiscal_year"])
        flags = rs.get("_line_flags") or []
        flagged = flags[i] if i < len(flags) else False
        elem = dict(line)
        elem["break_even_verdict"] = verdict
        elem["flagged_for_review"] = bool(flagged)
        out.append(elem)
    return out


# ---------------------------------------------------------------------------
# Subsidy waterfall (calculation subsidy_offset_waterfall)
# ---------------------------------------------------------------------------

def subsidy_candidates(user_id, at):
    cands = []
    for a in store.awards.values():
        if a["user_id"] != user_id:
            continue
        if award_status(a) != "ACTIVE":
            continue
        if not (a["_valid_from"] <= at < a["_valid_until"]):
            continue
        cands.append(a)
    cands.sort(key=lambda a: (a["_valid_until"], a["created_at"], a["_seq"]))
    return cands


def run_waterfall(user_id, amount_cents, at):
    """Returns (offset, draws) without mutating; draws = [(award, take)]."""
    remaining = amount_cents
    draws = []
    for a in subsidy_candidates(user_id, at):
        if remaining <= 0:
            break
        take = min(a["remaining_amount_cents"], remaining)
        if take > 0:
            draws.append((a, take))
            remaining -= take
    return amount_cents - remaining, draws


def commit_draws(draws):
    from util import touch
    for award, take in draws:
        award["remaining_amount_cents"] -= take
        touch(award)


def user_has_priority_award(user_id):
    for a in store.awards.values():
        if a["user_id"] == user_id and a.get("conveys_priority") and award_status(a) == "ACTIVE":
            return True
    return False


# ---------------------------------------------------------------------------
# Batches / entries
# ---------------------------------------------------------------------------

def open_batch():
    for b in store.batches.values():
        if b["status"] == "OPEN":
            return b
    return None


def batch_live_totals(batch):
    entries = [e for e in store.entries.values() if e["batch_id"] == batch["id"]]
    return (
        len(entries),
        sum(e["amount_cents"] for e in entries),
        sum(e["subsidy_offset_cents"] for e in entries),
        sum(e["net_amount_cents"] for e in entries),
    )


def create_entry(batch_id, kind, amount, offset, status, user_id, instrument_id,
                 grant_id=None, booking_id=None, usage_log_id=None,
                 is_external=False, draws=None):
    from util import new_entity
    entry = new_entity({
        "batch_id": batch_id,
        "usage_log_id": usage_log_id,
        "booking_id": booking_id,
        "grant_id": grant_id,
        "user_id": user_id,
        "instrument_id": instrument_id,
        "kind": kind,
        "is_external": bool(is_external),
        "amount_cents": int(amount),
        "subsidy_offset_cents": int(offset),
        "net_amount_cents": int(amount) - int(offset),
        "status": status,
        "dispute_reason": None,
        "_draws": [(a["id"], t) for a, t in (draws or [])],
    })
    store.entries[entry["id"]] = entry
    return entry


# ---------------------------------------------------------------------------
# Booking helpers
# ---------------------------------------------------------------------------

def provisional_estimate(start_at, end_at, rate_cents_per_hour):
    scheduled = whole_minutes(end_at - start_at)
    return money_mul_div(scheduled, rate_cents_per_hour, 60)


def release_encumbrance(booking):
    booking["encumbered_cents"] = 0


def system_cancel(booking, reason):
    """Involuntary cancellation cascade (downtime / suspension / retirement)."""
    from util import touch
    booking["status"] = "CANCELLED"
    booking["cancellation_reason"] = reason
    booking["penalty_waived"] = True
    booking["penalty_cents"] = 0
    release_encumbrance(booking)
    touch(booking)


def system_reject(booking):
    from util import touch
    booking["status"] = "REJECTED"
    touch(booking)


def post_penalty_entry_if_any(booking):
    """Post a PENALTY entry to the OPEN batch when penalty_cents > 0.
    Caller must already have verified an OPEN batch exists."""
    if booking["penalty_cents"] <= 0:
        return None
    batch = open_batch()
    if batch is None:
        fail("ERR_BATCH_NOT_OPEN", "No OPEN recharge batch for the penalty entry")
    user = store.users.get(booking["user_id"])
    is_external = bool(user and user["affiliation"] == "EXTERNAL")
    return create_entry(
        batch_id=batch["id"],
        kind="PENALTY",
        amount=booking["penalty_cents"],
        offset=0,
        status="PENDING",
        user_id=booking["user_id"],
        instrument_id=booking["instrument_id"],
        grant_id=None if is_external else booking.get("grant_id"),
        booking_id=booking["id"],
        usage_log_id=None,
        is_external=is_external,
    )


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def _public(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def ser_user(u):
    return _public(u)


def ser_instrument(i):
    return _public(i)


def ser_training(rec):
    out = _public(rec)
    out["status"] = training_effective_status(rec)
    return out


def ser_grant(g):
    out = _public(g)
    enc, used, available = grant_ledger(g)
    out["budget_encumbered_cents"] = enc
    out["budget_used_cents"] = used
    out["budget_available_cents"] = available
    out["status"] = grant_status(g)
    return out


def ser_rate_set(rs):
    out = _public(rs)
    out["line_verdicts"] = live_line_verdicts(rs)
    return out


def ser_booking(b):
    return _public(b)


def ser_usage_log(u):
    return _public(u)


def ser_batch(b):
    out = _public(b)
    if b["status"] == "OPEN":
        ec, gross, offset, net = batch_live_totals(b)
    else:
        ec = b["_frozen_entry_count"]
        gross = b["_frozen_gross"]
        offset = b["_frozen_offset"]
        net = b["_frozen_net"]
    out["entry_count"] = ec
    out["gross_amount_cents"] = gross
    out["subsidy_offset_cents"] = offset
    out["net_amount_cents"] = net
    return out


def ser_entry(e):
    return _public(e)


def ser_application(a):
    return _public(a)


def ser_award(a):
    out = _public(a)
    out["status"] = award_status(a)
    return out


def ser_contract(c):
    out = _public(c)
    out["status"] = contract_status(c)
    return out


def ser_downtime(ev):
    return _public(ev)


def ser_publication(p):
    return _public(p)


def ser_fiscal_year(fy):
    return _public(fy)


# ---------------------------------------------------------------------------
# Misc domain checks
# ---------------------------------------------------------------------------

def grant_authorized(grant, user_id):
    return user_id == grant["pi_user_id"] or user_id in (grant.get("authorized_user_ids") or [])


def fiscal_year_of(dt):
    """FY label N covers calendar dates N-01-01 .. N-12-31."""
    return dt.year
