"""Core business services: program/ledger, cascades, calculations."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
from errors import (
    err_invalid_state, err_posture_gate, err_voucher_not_issuable,
    err_no_provider_available, err_stale_version, err_invalid_request,
)
from services.util import (
    dec2, hours_val, round_half_up_int, quarter_bounds, fiscal_year_bounds,
    add_months, overlaps,
)


# ---------------- program budget helpers ----------------
def program_unencumbered(program):
    return (
        program["total_budget_cents"]
        - program["encumbered_cents"]
        - program["settled_cents"]
    )


def ledger_entry(program, entry_type, amount_cents, ref_type, ref_id, note=""):
    """Append a BudgetLedgerEntry (common_fields=false: only id, created_at)."""
    entry = {
        "id": db.new_id(),
        "created_at": db.now(),
        "program_id": program["id"],
        "entry_type": entry_type,
        "amount_cents": int(amount_cents),
        "ref_type": ref_type,
        "ref_id": ref_id,
        "note": note,
        # Internal tiebreak: the logical clock doesn't advance between ledger
        # appends in a single request, so we keep an insertion sequence to
        # make "newest first" deterministic. Not exposed by the serializer.
        "_seq": db.next_ledger_seq(),
    }
    db.ledger[entry["id"]] = entry
    return entry


def encumber(program, amount_cents, ref_type, ref_id, note=""):
    program["encumbered_cents"] += int(amount_cents)
    ledger_entry(program, "ENCUMBER", amount_cents, ref_type, ref_id, note)


def release(program, amount_cents, ref_type, ref_id, note=""):
    program["encumbered_cents"] -= int(amount_cents)
    ledger_entry(program, "RELEASE", amount_cents, ref_type, ref_id, note)


def settle(program, amount_cents, ref_type, ref_id, note=""):
    program["encumbered_cents"] -= int(amount_cents)
    program["settled_cents"] += int(amount_cents)
    ledger_entry(program, "SETTLE", amount_cents, ref_type, ref_id, note)


# ---------------- posture gates ----------------
def gate_enrollment(program):
    """Enrollment gate: caregiver/provider create + application APPROVE."""
    if program["posture"] != "ENROLLMENT_OPEN":
        raise err_posture_gate()


def gate_operational(program):
    """Operational gate: vouchers, bookings, visits, claims actions."""
    if program["posture"] in ("PROGRAM_SUSPENDED", "CLOSED"):
        raise err_posture_gate()


def program_of(entity):
    """Resolve the program that owns a child entity."""
    pid = entity.get("program_id")
    if pid is None:
        # Allocation always has program_id; for entities that only carry
        # caregiver/voucher refs, resolve transitively.
        return None
    return db.programs.get(pid)


# ---------------- allocation helpers ----------------
def allocation_current_quarter(program):
    return quarter_bounds(program["_fiscal_year_start"], db.now())


def find_open_allocation_for_quarter(caregiver_id, period_start):
    for a in db.allocations.values():
        if (
            a["caregiver_id"] == caregiver_id
            and a["period_start"] == period_start
            and a["status"] == "OPEN"
        ):
            return a
    return None


def create_allocation(program, caregiver_id, granted_hours, period_start, period_end):
    base = db.new_common()
    alloc = {
        **base,
        "caregiver_id": caregiver_id,
        "program_id": program["id"],
        "period_start": period_start,
        "period_end": period_end,
        "granted_hours": hours_val(granted_hours),
        "available_hours": hours_val(granted_hours),
        "reserved_hours": 0.0,
        "consumed_hours": 0.0,
        "expired_hours": 0.0,
        "revoked_hours": 0.0,
        "status": "OPEN",
    }
    db.allocations[alloc["id"]] = alloc
    return alloc


# ---------------- voucher helpers ----------------
def voucher_remaining_provisional_cents(voucher, program):
    """Remaining provisional encumbrance still held for the voucher.
    Provisional is authorized_hours * standard_rate (integer cents, half-up).
    After redemption the encumbrance is released in full at VERIFY, so
    remaining = full provisional only when status is ISSUED/COMMITTED (or
    emergency equivalents)."""
    if voucher["is_emergency"]:
        amt = (
            Decimal(str(voucher["authorized_hours"]))
            * Decimal(str(program["standard_rate_cents_per_hour"]))
            * Decimal(str(program["emergency_multiplier"]))
        )
    else:
        amt = (
            Decimal(str(voucher["authorized_hours"]))
            * Decimal(str(program["standard_rate_cents_per_hour"]))
        )
    return round_half_up_int(amt)


def revoke_voucher(voucher, reason_note=""):
    """ISSUED -> REVOKED cascade (per §3.4 / suspension §3.8)."""
    program = db.programs[voucher["program_id"]]
    forfeited = hours_val(voucher["authorized_hours"] - voucher["consumed_hours"])
    voucher["forfeited_hours"] = forfeited
    voucher["committed_hours"] = 0.0
    voucher["status"] = "REVOKED"
    db.touch(voucher)
    alloc_id = voucher.get("allocation_id")
    if alloc_id is not None:
        alloc = db.allocations[alloc_id]
        alloc["reserved_hours"] = hours_val(alloc["reserved_hours"] - forfeited)
        alloc["revoked_hours"] = hours_val(alloc["revoked_hours"] + forfeited)
        db.touch(alloc)
    # RELEASE remaining provisional encumbrance
    amt = voucher_remaining_provisional_cents(voucher, program)
    release(program, amt, "voucher", voucher["id"], reason_note or "voucher revoked")
    db.touch(program)


def expire_voucher(voucher):
    """ISSUED -> EXPIRED ops-run cascade (per state machine)."""
    program = db.programs[voucher["program_id"]]
    forfeited = hours_val(voucher["authorized_hours"] - voucher["consumed_hours"])
    voucher["forfeited_hours"] = forfeited
    voucher["status"] = "EXPIRED"
    db.touch(voucher)
    alloc_id = voucher.get("allocation_id")
    if alloc_id is not None:
        alloc = db.allocations[alloc_id]
        alloc["reserved_hours"] = hours_val(alloc["reserved_hours"] - forfeited)
        alloc["expired_hours"] = hours_val(alloc["expired_hours"] + forfeited)
        db.touch(alloc)
    amt = voucher_remaining_provisional_cents(voucher, program)
    release(program, amt, "voucher", voucher["id"], "voucher expired")
    db.touch(program)


# ---------------- window overlap ----------------
def window_overlap_count(window, exclude_booking_id=None, interval=None):
    """Maximum overlap of non-cancelled bookings against this window.
    Per spec: count overlapping non-cancelled bookings at any instant;
    we compute the max overlap across the window's bookings.
    If `interval` is given (start_at, end_at), only bookings overlapping that
    interval are counted (used when judging whether a *new* booking can be
    added without breaching capacity)."""
    bookings = [
        b for b in db.bookings.values()
        if b.get("window_id") == window["id"]
        and b["status"] in ("PENDING_CONFIRMATION", "CONFIRMED", "IN_SERVICE")
        and b["id"] != exclude_booking_id
    ]
    if interval is not None:
        s, e = interval
        bookings = [b for b in bookings if b["start_at"] < e and b["end_at"] > s]
    if not bookings:
        return 0
    # max simultaneous overlap using sweep
    points = []
    for b in bookings:
        points.append((b["start_at"], 1))
        points.append((b["end_at"], -1))
    # half-open: end at t removes before start at t adds
    points.sort(key=lambda p: (p[0], p[1]))
    cur = 0
    mx = 0
    for _, d in points:
        cur += d
        if cur > mx:
            mx = cur
    return mx


def maybe_mark_window_full(window):
    cnt = window_overlap_count(window)
    if window["status"] == "OPEN" and cnt >= window["capacity"]:
        window["status"] = "FULLY_BOOKED"
        db.touch(window)


def maybe_reopen_window(window):
    if window["status"] == "FULLY_BOOKED":
        cnt = window_overlap_count(window)
        if cnt < window["capacity"]:
            window["status"] = "OPEN"
            db.touch(window)


# ---------------- booking helpers ----------------
def booking_duration_hours(booking):
    return (booking["end_at"] - booking["start_at"]).total_seconds() / 3600.0


def release_booking(booking):
    """Release voucher commitment and window capacity (shared by cancel/no-show)."""
    voucher = db.vouchers[booking["voucher_id"]]
    dur = Decimal(str(booking["committed_minutes"])) / Decimal("60")
    voucher["committed_hours"] = hours_val(
        Decimal(str(voucher["committed_hours"])) - dur
    )
    # if all bookings of voucher are CANCELLED or NO_SHOW -> ISSUED
    remaining = [
        b for b in db.bookings.values()
        if b["voucher_id"] == voucher["id"]
        and b["id"] != booking["id"]
        and b["status"] not in ("CANCELLED", "NO_SHOW")
    ]
    if voucher["status"] == "COMMITTED" and not remaining:
        voucher["status"] = "ISSUED"
        voucher["committed_hours"] = 0.0
    db.touch(voucher)
    if booking.get("window_id"):
        window = db.windows.get(booking["window_id"])
        if window is not None:
            maybe_reopen_window(window)


# ---------------- caregiver suspension cascade ----------------
def cascade_caregiver_suspension(caregiver):
    for alloc in list(db.allocations.values()):
        if alloc["caregiver_id"] != caregiver["id"]:
            continue
        if alloc["status"] != "OPEN":
            continue
        alloc["status"] = "FROZEN"
        db.touch(alloc)
        # ISSUED vouchers -> REVOKED
        for voucher in list(db.vouchers.values()):
            if voucher.get("allocation_id") != alloc["id"]:
                continue
            if voucher["status"] == "ISSUED":
                revoke_voucher(voucher, "caregiver suspension")
        # COMMITTED vouchers: cancel bookings first, then revoke
        for voucher in list(db.vouchers.values()):
            if voucher.get("allocation_id") != alloc["id"]:
                continue
            if voucher["status"] != "COMMITTED":
                continue
            for b in list(db.bookings.values()):
                if b["voucher_id"] != voucher["id"]:
                    continue
                if b["status"] in ("PENDING_CONFIRMATION", "CONFIRMED"):
                    b["status"] = "CANCELLED"
                    b["cancel_reason"] = "SYSTEM_SUSPENSION"
                    db.touch(b)
                    if b.get("window_id"):
                        w = db.windows.get(b["window_id"])
                        if w is not None:
                            maybe_reopen_window(w)
            revoke_voucher(voucher, "caregiver suspension")


def cascade_caregiver_reinstatement(caregiver):
    for alloc in db.allocations.values():
        if alloc["caregiver_id"] == caregiver["id"] and alloc["status"] == "FROZEN":
            alloc["status"] = "OPEN"
            db.touch(alloc)


def cascade_caregiver_disenrollment(caregiver):
    for alloc in list(db.allocations.values()):
        if alloc["caregiver_id"] != caregiver["id"]:
            continue
        if alloc["status"] != "OPEN":
            continue
        # ISSUED vouchers revoked with same bucket/ledger effects
        for voucher in list(db.vouchers.values()):
            if voucher.get("allocation_id") == alloc["id"] and voucher["status"] == "ISSUED":
                revoke_voucher(voucher, "caregiver disenrollment")
        alloc["status"] = "CLOSED"
        db.touch(alloc)


# ---------------- calculations ----------------
def compute_verified_minutes(check_in_at, check_out_at):
    elapsed = (check_out_at - check_in_at).total_seconds() / 60.0
    elapsed_minutes = int(elapsed)  # whole minutes
    q = Decimal(elapsed_minutes) / Decimal(15)
    return int(15 * int(q.quantize(Decimal("1"), rounding=ROUND_HALF_UP)))


def compute_payable_minutes(verified_minutes, committed_minutes, max_overage_pct):
    cap = int(
        (Decimal(committed_minutes) * Decimal(str(max_overage_pct))).to_integral_value(
            rounding="ROUND_FLOOR"
        )
    )
    return min(verified_minutes, cap)


def compute_provisional_cents(committed_minutes, standard_rate_cents_per_hour):
    amt = Decimal(committed_minutes) * Decimal(standard_rate_cents_per_hour) / Decimal(60)
    return round_half_up_int(amt)


def compute_claim_amount(program, provider, booking, visit):
    base_minutes = visit["payable_minutes"]
    ci = visit["check_in_at"]
    # (2) day multiplier
    weekday = ci.weekday()  # Mon=0 .. Sun=6 (UTC because ci is UTC-aware)
    if weekday >= 5:
        day_mult = Decimal(str(program["weekend_multiplier"]))
    elif ci.hour >= program["evening_start_hour"]:
        day_mult = Decimal(str(program["evening_multiplier"]))
    else:
        day_mult = Decimal("1.0")
    # (3) credential multiplier
    cred_mult = (
        Decimal(str(program["credential_premium_multiplier"]))
        if provider["credential_level"] == "ENHANCED"
        else Decimal("1.0")
    )
    # (4) emergency multiplier
    emerg_mult = (
        Decimal(str(program["emergency_multiplier"]))
        if booking.get("is_emergency")
        else Decimal("1.0")
    )
    amt = (
        Decimal(base_minutes)
        * Decimal(program["standard_rate_cents_per_hour"])
        * day_mult
        * cred_mult
        * emerg_mult
        / Decimal(60)
    )
    return round_half_up_int(amt)


# ---------------- selectors ----------------
def rank_providers(candidates):
    """quality_score_weighted DESC NULLS LAST, then provider.created_at ASC."""
    def key(p):
        qs = p.get("quality_score_weighted")
        # nulls last: use flag
        return (
            0 if qs is not None else 1,
            -(qs if qs is not None else 0),
            p["created_at"],
            p["id"],
        )
    return sorted(candidates, key=key)


def emergency_dispatch_selector(needed_start, needed_end):
    pool = []
    for p in db.providers.values():
        if p["credential_status"] != "ACTIVE":
            continue
        if not p.get("accepts_emergency"):
            continue
        conflict = False
        for b in db.bookings.values():
            if b["provider_id"] != p["id"]:
                continue
            if b["status"] not in ("CONFIRMED", "IN_SERVICE"):
                continue
            if overlaps(b["start_at"], b["end_at"], needed_start, needed_end):
                conflict = True
                break
        if not conflict:
            pool.append(p)
    if not pool:
        raise err_no_provider_available()
    return rank_providers(pool)[0]


def auto_match_selector(start_at, end_at):
    """Return (provider, window) or raise ERR_NO_PROVIDER_AVAILABLE."""
    pool = []
    for p in db.providers.values():
        if p["credential_status"] != "ACTIVE":
            continue
        eligible_windows = []
        for w in db.windows.values():
            if w["provider_id"] != p["id"]:
                continue
            if w["status"] not in ("OPEN", "FULLY_BOOKED"):
                continue
            if not (w["start_at"] <= start_at and end_at <= w["end_at"]):
                continue
            if window_overlap_count(w, interval=(start_at, end_at)) >= w["capacity"]:
                continue
            eligible_windows.append(w)
        if eligible_windows:
            # earliest start_at, tie window.created_at
            eligible_windows.sort(key=lambda w: (w["start_at"], w["created_at"], w["id"]))
            pool.append((p, eligible_windows[0]))
    if not pool:
        raise err_no_provider_available()
    ranked = rank_providers([p for p, _ in pool])
    chosen = ranked[0]
    for p, w in pool:
        if p["id"] == chosen["id"]:
            return p, w
    # unreachable
    return pool[0]


# ---------------- quality scores ----------------
def recompute_quality_scores(provider):
    provider_surveys = [
        s for s in db.surveys.values() if s["provider_id"] == provider["id"]
    ]
    if not provider_surveys:
        provider["quality_score_simple"] = None
        provider["quality_score_weighted"] = None
        return
    n = len(provider_surveys)
    simple = sum(s["rating"] for s in provider_surveys) / n
    provider["quality_score_simple"] = float(
        Decimal(str(simple)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    )
    now = db.now()
    wsum = Decimal("0")
    rsum = Decimal("0")
    for s in provider_surveys:
        days = (now - s["created_at"]).total_seconds() / 86400.0
        whole_days = int(days)
        w = Decimal("0.5") ** (Decimal(whole_days) / Decimal(30))
        wsum += w
        rsum += w * Decimal(s["rating"])
    weighted = rsum / wsum
    provider["quality_score_weighted"] = float(
        weighted.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    )
