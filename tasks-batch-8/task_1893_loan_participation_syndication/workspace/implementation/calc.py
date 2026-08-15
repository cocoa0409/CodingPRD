"""Calculation rules (PRD section 3; SCAFFOLD table 3).

All money is integer cents, all rates/shares integer basis points; every
division floors. Remainders are distributed one unit at a time in pinned
orders.
"""
from datetime import date, timedelta

import errors
from store import db, touch, today, date_of_ts, parse_date

SHARE_SCALE = 10000
LATE_FUNDING_DAILY_BPS = 15
FUNDING_WINDOW_DAYS = 5
BUYBACK_PENALTY_BPS = 500
FEE_DENOM = 360
SOLICITATION_BUFFER_HOURS = 24
UNANIMOUS_THRESHOLD_BPS = 10000

ACTIVE_PARTICIPANT_STATUSES = ("COMMITTED", "FUNDED")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def facility_participants(facility_id):
    return [p for p in db["participants"].values() if p["facility_id"] == facility_id]


def facility_draws(facility_id):
    return [d for d in db["draws"].values() if d["facility_id"] == facility_id]


def draw_order(draws):
    """Oldest-first: accrual_start_date ASC, then created_at ASC, then seq."""
    return sorted(
        draws,
        key=lambda d: (d["accrual_start_date"], d["created_at"], d["_seq"]),
    )


# ---------------------------------------------------------------------------
# participant_share_bps
# ---------------------------------------------------------------------------

def recompute_shares(facility):
    parts = facility_participants(facility["id"])
    eligible = [p for p in parts if p["status"] in ACTIVE_PARTICIPANT_STATUSES]
    base = facility["committed_cents"]
    for p in parts:
        if p["status"] not in ACTIVE_PARTICIPANT_STATUSES and p["share_bps"] != 0:
            p["share_bps"] = 0
            touch(p)
    if not eligible:
        return
    if base == 0:
        for p in eligible:
            if p["share_bps"] != 0:
                p["share_bps"] = 0
                touch(p)
        return
    shares = {p["id"]: (SHARE_SCALE * p["commitment_cents"]) // base for p in eligible}
    remainder = SHARE_SCALE - sum(shares.values())
    order = sorted(
        eligible,
        key=lambda p: (-p["commitment_cents"], p["created_at"], p["participant_name"], p["_seq"]),
    )
    i = 0
    while remainder > 0:
        shares[order[i % len(order)]["id"]] += 1
        remainder -= 1
        i += 1
    for p in eligible:
        if p["share_bps"] != shares[p["id"]]:
            p["share_bps"] = shares[p["id"]]
            touch(p)


# ---------------------------------------------------------------------------
# committed_recompute (+ pre-funding facility status bubbles)
# ---------------------------------------------------------------------------

def recompute_committed(facility):
    total = sum(
        p["commitment_cents"]
        for p in facility_participants(facility["id"])
        if p["status"] in ACTIVE_PARTICIPANT_STATUSES
    )
    facility["committed_cents"] = total
    has_live_draw = any(
        d["status"] != "CANCELLED" for d in facility_draws(facility["id"])
    )
    if not has_live_draw:
        st = facility["status"]
        if st == "STRUCTURING" and total > 0:
            facility["status"] = "SYNDICATING"
            st = "SYNDICATING"
        if st == "SYNDICATING" and total == facility["total_commitment_cents"]:
            facility["status"] = "COMMITTED"
        elif st == "COMMITTED" and total < facility["total_commitment_cents"]:
            facility["status"] = "SYNDICATING"
    touch(facility)


# ---------------------------------------------------------------------------
# interest accrual (day-count variants, segmentation, default re-rating)
# ---------------------------------------------------------------------------

def _day_count(basis, start, end):
    """(days, denominator) for a half-open [start, end) segment."""
    if basis == "BASIS_30_360":
        days = (
            360 * (end.year - start.year)
            + 30 * (end.month - start.month)
            + (min(end.day, 30) - min(start.day, 30))
        )
        return days, 360
    days = (end - start).days
    return days, (360 if basis == "ACT_360" else 365)


def _default_windows(facility):
    """Addon windows from this facility's default cases.

    DECLARED/ACCELERATED: [declared_date, open). CURED: [declared, resolved).
    WAIVED cases contribute no window (addon removed retroactively).
    """
    windows = []
    for c in db["default_cases"].values():
        if c["facility_id"] != facility["id"]:
            continue
        declared = date_of_ts(c["declared_at"])
        if c["status"] in ("DECLARED", "ACCELERATED"):
            windows.append((declared, None))
        elif c["status"] == "CURED":
            windows.append((declared, date_of_ts(c["resolved_at"])))
    return windows


def _rate_at(facility, day):
    """Base rate effective on `day` (prospective RATE_CHANGE history).

    _rate_history holds (effective_date_or_None, rate_bps); the None entry is
    the original rate effective from the beginning of time.
    """
    hist = facility.get("_rate_history") or []
    best_key = None
    rate = facility["interest_rate_bps"]
    for eff, r in hist:
        if eff is None or eff <= day:
            key = eff or date.min
            if best_key is None or key > best_key:
                best_key = key
                rate = r
    return rate


def window_interest(facility, outstanding_cents, start, end):
    """Interest over [start, end), split at rate-change and default boundaries.

    Floor is applied per segment, then segments are summed.
    """
    if end <= start or outstanding_cents <= 0:
        return 0
    points = {start, end}
    for eff, _r in (facility.get("_rate_history") or []):
        if eff is not None and start < eff < end:
            points.add(eff)
    windows = _default_windows(facility)
    for ws, we in windows:
        we_eff = we if we is not None else end
        lo, hi = max(start, ws), min(end, we_eff)
        if lo < hi:
            points.add(lo)
            points.add(hi)
    ordered = sorted(points)
    total = 0
    basis = facility["day_count_basis"]
    for a, b in zip(ordered, ordered[1:]):
        if a >= b:
            continue
        rate = _rate_at(facility, a)
        in_default = any(ws <= a and (we is None or b <= we) for ws, we in windows)
        if in_default:
            rate += facility["default_interest_addon_bps"]
        days, denom = _day_count(basis, a, b)
        if days > 0:
            total += (outstanding_cents * rate * days) // (denom * 10000)
    return total


def draw_accrued_unpaid(draw):
    return sum(e["interest"] for e in draw["_ledger"]) - draw["_net_distributed"]


def facility_accrued(facility):
    return sum(
        draw_accrued_unpaid(d)
        for d in facility_draws(facility["id"])
        if d["status"] == "SETTLED"
    )


def facility_outstanding(facility):
    return sum(d["outstanding_cents"] for d in facility_draws(facility["id"]))


def sync_facility_aggregates(facility):
    facility["accrued_interest_cents"] = facility_accrued(facility)
    facility["outstanding_principal_cents"] = facility_outstanding(facility)
    facility["funded_principal_cents"] = sum(
        s["due_cents"]
        for s in db["settlements"].values()
        if s["facility_id"] == facility["id"] and s["status"] in ("CONFIRMED", "LATE_CONFIRMED")
    )
    touch(facility)


def materialize_draw(facility, draw, as_of):
    """Append one accrual-ledger entry for [as_of_date, as_of) and advance."""
    current = parse_date(draw["accrual_as_of_date"])
    if as_of <= current:
        return
    if draw["status"] != "SETTLED":
        return
    interest = window_interest(facility, draw["outstanding_cents"], current, as_of)
    draw["_ledger"].append(
        {"from": current.isoformat(), "to": as_of.isoformat(),
         "outstanding": draw["outstanding_cents"], "interest": interest}
    )
    draw["accrual_as_of_date"] = as_of.isoformat()
    draw["accrued_unpaid_interest_cents"] = draw_accrued_unpaid(draw)
    touch(draw)


def materialize_facility(facility, as_of):
    """Materialize every SETTLED draw to as_of and reconcile the facility."""
    for d in facility_draws(facility["id"]):
        if d["status"] == "SETTLED":
            materialize_draw(facility, d, as_of)
    facility["accrued_interest_cents"] = facility_accrued(facility)
    touch(facility)


def rerate_retroactive_base(facility):
    """WAIVE path: replay every draw's ledger with the waived case's window
    removed (i.e. against current windows, where WAIVED cases contribute
    nothing). Rate-change history is preserved (prospective-only rate
    changes stay prospective)."""
    for d in facility_draws(facility["id"]):
        if d["status"] != "SETTLED":
            continue
        for e in d["_ledger"]:
            e["interest"] = window_interest(
                facility, e["outstanding"], parse_date(e["from"]), parse_date(e["to"])
            )
        d["accrued_unpaid_interest_cents"] = draw_accrued_unpaid(d)
        touch(d)
    facility["accrued_interest_cents"] = facility_accrued(facility)
    touch(facility)


def prospective_accrued(facility, as_of):
    """Accrued interest the facility would show after materializing to as_of,
    without mutating anything (used to validate the waterfall)."""
    total = 0
    for d in facility_draws(facility["id"]):
        if d["status"] != "SETTLED":
            continue
        current = parse_date(d["accrual_as_of_date"])
        add = 0
        if as_of > current:
            add = window_interest(facility, d["outstanding_cents"], current, as_of)
        total += draw_accrued_unpaid(d) + add
    return total


# ---------------------------------------------------------------------------
# servicing_fee_accrual
# ---------------------------------------------------------------------------

def servicing_fee(facility, payment):
    outstanding = facility["outstanding_principal_cents"]  # pre-run, pinned
    baseline = facility["last_distribution_value_date"]
    if baseline is None:
        settled = [d for d in facility_draws(facility["id"]) if d["status"] == "SETTLED"]
        if not settled:
            return 0
        first = min(settled, key=lambda d: (d["settled_at"], d["created_at"], d["_seq"]))
        baseline = date_of_ts(first["settled_at"]).isoformat()
    fee_days = (parse_date(payment["value_date"]) - parse_date(baseline)).days
    if fee_days < 0:
        fee_days = 0
    raw = (outstanding * facility["servicing_fee_bps"] * fee_days) // (FEE_DENOM * 10000)
    return min(raw, payment["amount_cents"])


# ---------------------------------------------------------------------------
# waterfall_distribution
# ---------------------------------------------------------------------------

def _remainder_order(participants):
    return sorted(
        participants,
        key=lambda p: (
            -p["share_bps"],
            -p["commitment_cents"],
            p["created_at"],
            p["participant_name"],
            p["_seq"],
        ),
    )


def split_pool(pool, participants):
    """floor(pool * share/10000) per participant, remainder cents distributed
    one at a time in the pinned order, cycling if the remainder reaches the
    participant count."""
    allocs = {p["id"]: (pool * p["share_bps"]) // SHARE_SCALE for p in participants}
    if not participants:
        return allocs
    remainder = pool - sum(allocs.values())
    order = _remainder_order(participants)
    i = 0
    while remainder > 0:
        allocs[order[i % len(order)]["id"]] += 1
        remainder -= 1
        i += 1
    return allocs


# ---------------------------------------------------------------------------
# late_funding_penalty
# ---------------------------------------------------------------------------

def late_funding_penalty(due_cents, days_late):
    return (due_cents * LATE_FUNDING_DAILY_BPS * days_late) // 10000


# ---------------------------------------------------------------------------
# consent_tally / default_vote_tally (adjusted bases net of exits)
# ---------------------------------------------------------------------------

def _exit_reduction_since(facility_id, since_dt):
    total = 0
    for p in facility_participants(facility_id):
        ex = p.get("_exit")
        if ex and ex["at"] >= since_dt:
            total += ex["reduction"]
    return total


def recompute_mod_tally(mod):
    facility = db["facilities"][mod["facility_id"]]
    adj = mod["voting_base_cents"] or 0
    if mod.get("voting_open_at"):
        from store import _parse_dt

        adj -= _exit_reduction_since(facility["id"], _parse_dt(mod["voting_open_at"]))
    approving = 0
    cast = 0
    for v in db["consent_votes"].values():
        if v["modification_id"] != mod["id"] or v["status"] not in ("CAST", "RECAST"):
            continue
        p = db["participants"].get(v["participant_id"])
        if p is None or p["status"] != "FUNDED":
            continue
        cast += p["commitment_cents"]
        if v["vote"] == "APPROVE":
            approving += p["commitment_cents"]
    mod["approving_commitment_cents"] = approving
    mod["cast_commitment_cents"] = cast
    mod["approving_share_bps"] = (10000 * approving) // adj if adj > 0 else 0
    mod["cast_share_bps"] = (10000 * cast) // adj if adj > 0 else 0
    touch(mod)


def recompute_default_tally(case):
    facility = db["facilities"][case["facility_id"]]
    adj = case["voting_base_cents"] or 0
    from store import _parse_dt

    adj -= _exit_reduction_since(facility["id"], _parse_dt(case["declared_at"]))
    accelerate = 0
    waive = 0
    for v in db["default_votes"].values():
        if v["default_case_id"] != case["id"] or v["status"] not in ("CAST", "RECAST"):
            continue
        p = db["participants"].get(v["participant_id"])
        if p is None:
            continue
        if v["vote"] == "ACCELERATE":
            accelerate += p["commitment_cents"]
        elif v["vote"] == "WAIVE":
            waive += p["commitment_cents"]
    case["accelerate_commitment_cents"] = accelerate
    case["waive_commitment_cents"] = waive
    case["accelerate_share_bps"] = (10000 * accelerate) // adj if adj > 0 else 0
    case["waive_share_bps"] = (10000 * waive) // adj if adj > 0 else 0
    touch(case)


# ---------------------------------------------------------------------------
# buyback_price
# ---------------------------------------------------------------------------

def buyback_price(participant, facility):
    outstanding_share = participant["funded_cents"] - participant["cumulative_principal_cents"]
    accrued_share = (participant["share_bps"] * facility["accrued_interest_cents"]) // 10000
    penalty = 0
    return outstanding_share, accrued_share, penalty


# ---------------------------------------------------------------------------
# principal_reduction_allocation (oldest draw first)
# ---------------------------------------------------------------------------

def apply_principal_reduction(facility, pool):
    """Reduce draw outstanding oldest-first; returns {draw_id: cents}."""
    applied = {}
    remaining = pool
    draws = draw_order(
        [d for d in facility_draws(facility["id"]) if d["status"] == "SETTLED" and d["outstanding_cents"] > 0]
    )
    for d in draws:
        if remaining <= 0:
            break
        take = min(remaining, d["outstanding_cents"])
        d["outstanding_cents"] -= take
        applied[d["id"]] = take
        remaining -= take
        touch(d)
    return applied


def apply_interest_reduction(facility, pool):
    """Reduce draws' accrued unpaid interest oldest-first; returns per-draw map."""
    applied = {}
    remaining = pool
    draws = draw_order(
        [d for d in facility_draws(facility["id"]) if d["status"] == "SETTLED"]
    )
    for d in draws:
        if remaining <= 0:
            break
        take = min(remaining, draw_accrued_unpaid(d))
        if take <= 0:
            continue
        d["_net_distributed"] += take
        d["accrued_unpaid_interest_cents"] = draw_accrued_unpaid(d)
        applied[d["id"]] = take
        remaining -= take
        touch(d)
    return applied
