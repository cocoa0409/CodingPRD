"""Core shared services: record lifecycle, serializers, calculations, cascades."""
from datetime import datetime, timedelta, timezone

from db import db
from util import (
    new_id, now_ts, fmt_dt, fmt_date_midnight, parse_date_value, parse_dt,
    round_half_up_int, add_years, next_seq, CLOCK,
)

ACTIVE_LEASE_STATES = ("ACTIVE", "EXPIRING", "HOLDOVER")
NONTERMINAL_OPTION_STATES = ("AVAILABLE", "WINDOW_OPEN", "NOTICE_SENT")
OPEN_NEGOTIATION_STATES = ("PROPOSED", "COUNTERED", "AGREED")
TIER_OFFSETS = ((90, "T90"), (60, "T60"), (30, "T30"), (7, "T7"), (0, "T0"))
# Firing tie-break severity: T0 > T7 > T30 > T60 > T90 (§1.3 reminder_cascade_schedule)
TIER_RANK = {"T0": 0, "T7": 1, "T30": 2, "T60": 3, "T90": 4}
LEAD_DAYS_REQUIRED = 270


# ---------------------------------------------------------------------------
# Record lifecycle
# ---------------------------------------------------------------------------

def new_record(collection, fields, common=True):
    rec = dict(fields)
    rec["id"] = new_id()
    rec["_seq"] = next_seq()
    ts = now_ts()
    rec["created_at"] = ts
    if common:
        rec["updated_at"] = ts
        rec["version"] = 1
    db[collection][rec["id"]] = rec
    return rec


def touch(rec, bump=True):
    """Full mutation: refresh updated_at and (by default) advance version."""
    rec["updated_at"] = now_ts()
    if bump:
        rec["version"] = rec.get("version", 1) + 1


def refresh(rec):
    """Status mutation that does NOT advance version.

    Option status transitions (WINDOW_OPEN / NOTICE_SENT / IN_ARBITRATION /
    EXERCISED / LAPSED / WITHDRAWN / SUPERSEDED) deliberately leave
    Option.version alone: §1.2.1 pins Option.version advancement to assessment
    submission (supersede) only, and the version token is captured at creation.
    """
    rec["updated_at"] = now_ts()


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def public(rec):
    if rec is None:
        return None
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def serialize_portfolio(p):
    out = public(p)
    lad = compute_ladder(p["id"])
    out["total_active_square_feet"] = lad["total_active_square_feet"]
    out["posture"] = lad["posture"]
    out["posture_year"] = lad["posture_year"]
    return out


def serialize_lease(l):
    return public(l)


def serialize_clock_event(e):
    return public(e)


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def lease_options(lease_id):
    return [o for o in db["options"].values() if o["lease_id"] == lease_id]


def lease_amendments(lease_id):
    return [a for a in db["amendments"].values() if a["lease_id"] == lease_id]


def option_notices(option_id):
    return sorted(
        [n for n in db["notices"].values() if n["option_id"] == option_id],
        key=lambda n: n["_seq"],
    )


def option_assessments(option_id):
    return sorted(
        [m for m in db["assessments"].values() if m["option_id"] == option_id],
        key=lambda m: m["_seq"],
    )


def assessment_case(assessment_id):
    for c in db["arbitrations"].values():
        if c["assessment_id"] == assessment_id:
            return c
    return None


# ---------------------------------------------------------------------------
# Ledger (PRD §2.9) — append-only, common_fields: false
# ---------------------------------------------------------------------------

def post_ledger(lease_id, entry_kind, amount_cents, effective_date,
                source_option_id=None, source_assessment_id=None):
    return new_record("ledger", {
        "lease_id": lease_id,
        "entry_kind": entry_kind,
        "amount_cents": amount_cents,
        "effective_date": fmt_date_midnight(effective_date),
        "source_option_id": source_option_id,
        "source_assessment_id": source_assessment_id,
    }, common=False)


# ---------------------------------------------------------------------------
# Calculations (§1.3)
# ---------------------------------------------------------------------------

def compute_ladder(portfolio_id, overrides=None):
    """portfolio_expiration_ladder. overrides: {lease_id: {"status":..,"expiration_date": date}}
    simulates a post-mutation view for the enforce_ladder advisory gate."""
    overrides = overrides or {}
    cap = db["portfolios"][portfolio_id]["laddering_max_pct_per_year"]
    active = []
    for l in db["leases"].values():
        if l["portfolio_id"] != portfolio_id:
            continue
        ov = overrides.get(l["id"], {})
        st = ov.get("status", l["status"])
        exp = ov.get("expiration_date", parse_date_value(l["expiration_date"]))
        if st in ACTIVE_LEASE_STATES:
            active.append((exp, l["rentable_square_feet"]))
    total = sum(rsf for _, rsf in active)
    if total == 0:
        return {"years": [], "posture": "LADDER_OK", "posture_year": None,
                "total_active_square_feet": 0}
    clock_year = CLOCK.today().year
    max_year = max(exp.year for exp, _ in active)
    years = []
    posture = "LADDER_OK"
    posture_year = None
    for Y in range(clock_year, max_year + 1):
        rsf_y = sum(rsf for exp, rsf in active if exp.year == Y)
        pct = round_half_up_int(100 * rsf_y, total)
        years.append({"year": Y, "expiring_rsf": rsf_y, "exposure_pct": pct})
        if pct > cap and posture_year is None:  # strict > — equality does not trip
            posture = "LADDER_STRESSED"
            posture_year = Y
    return {"years": years, "posture": posture, "posture_year": posture_year,
            "total_active_square_feet": total}


def compute_holdover_accrual(lease, clock_date):
    """holdover_rent_accrual — pinned per-day-tier rounding, then multiply, then sum."""
    if not lease.get("holdover_entered_at"):
        return 0
    entered = parse_date_value(lease["holdover_entered_at"])
    days_held = (clock_date - entered).days  # entered exclusive .. clock date inclusive
    if days_held <= 0:
        return 0
    daily_base = (lease["base_rent_cents_per_rsf_year"] * lease["rentable_square_feet"]) // 365
    t1_daily = round_half_up_int(daily_base * lease["holdover_tier1_pct"], 100)
    t2_daily = round_half_up_int(daily_base * lease["holdover_tier2_pct"], 100)
    t1_days = lease["holdover_tier1_days"]
    return min(days_held, t1_days) * t1_daily + max(0, days_held - t1_days) * t2_daily


def compute_fair_market_rent(method, comparables, base, adjustments):
    if method == "COMPARABLE_AVERAGE":
        return round_half_up_int(sum(comparables), len(comparables))
    # PSF_REGRESSION: base + signed adjustments, floored at 1 cent, no rounding step
    return max(1, base + sum(adjustments or []))


# ---------------------------------------------------------------------------
# Reminder cascade (§3.4)
# ---------------------------------------------------------------------------

def spawn_reminder_cascade(option):
    """On AVAILABLE -> WINDOW_OPEN: five PENDING reminders per active contact."""
    lease = db["leases"].get(option["lease_id"])
    portfolio_id = lease["portfolio_id"] if lease else None
    close = parse_date_value(option["notice_window_close_date"])
    contacts = sorted(
        [c for c in db["contacts"].values()
         if c["portfolio_id"] == portfolio_id and c.get("is_active", True)],
        key=lambda c: c["_seq"],
    )
    for contact in contacts:
        for days, tier in TIER_OFFSETS:
            raw = close - timedelta(days=days)
            # weekend roll-FORWARD: Saturday +2, Sunday +1
            if raw.weekday() == 5:
                raw += timedelta(days=2)
            elif raw.weekday() == 6:
                raw += timedelta(days=1)
            sched = datetime(raw.year, raw.month, raw.day, 9, 0, 0, tzinfo=timezone.utc)
            new_record("reminders", {
                "option_id": option["id"],
                "contact_id": contact["id"],
                "tier": tier,
                "scheduled_for": fmt_dt(sched),
                "status": "PENDING",
                "sent_at": None,
            })


def cancel_pending_reminders_for_option(option_id):
    for r in db["reminders"].values():
        if r["option_id"] == option_id and r["status"] == "PENDING":
            r["status"] = "CANCELED"
            touch(r)


def cancel_pending_reminders_for_contact(contact_id):
    for r in db["reminders"].values():
        if r["contact_id"] == contact_id and r["status"] == "PENDING":
            r["status"] = "CANCELED"
            touch(r)


# ---------------------------------------------------------------------------
# Option / lease transitions
# ---------------------------------------------------------------------------

def lapse_option(option, now):
    """-> LAPSED: stamp, cancel PENDING reminders, post penalty when > 0."""
    option["status"] = "LAPSED"
    option["lapsed_at"] = fmt_dt(now)
    refresh(option)
    cancel_pending_reminders_for_option(option["id"])
    penalty = option.get("missed_option_penalty_cents") or 0
    if penalty > 0:
        post_ledger(option["lease_id"], "MISSED_OPTION_PENALTY", penalty,
                    now.date(), source_option_id=option["id"])


def supersede_nonterminal_options(lease_id, except_option_id=None):
    """Parent lease reached a terminal state: AVAILABLE/WINDOW_OPEN/NOTICE_SENT
    options -> SUPERSEDED (no penalty — supersession is not a lapse)."""
    for o in db["options"].values():
        if o["lease_id"] != lease_id or o["id"] == except_option_id:
            continue
        if o["status"] in NONTERMINAL_OPTION_STATES:
            o["status"] = "SUPERSEDED"
            refresh(o)
            cancel_pending_reminders_for_option(o["id"])


def transition_lease_renewed(lease, option):
    lease["status"] = "RENEWED"
    touch(lease)
    if option is not None:
        # Successor lease auto-created in DRAFT (option-driven path only)
        target = parse_date_value(option["target_commencement_date"])
        ext = option.get("extension_years") or 0
        new_record("leases", {
            "portfolio_id": lease["portfolio_id"],
            "premises_label": lease["premises_label"],
            "rentable_square_feet": lease["rentable_square_feet"],
            "base_rent_cents_per_rsf_year": option["determined_rent_cents_per_rsf_year"],
            "commencement_date": fmt_date_midnight(target),
            "expiration_date": fmt_date_midnight(add_years(target, ext)),
            "holdover_tier1_pct": lease["holdover_tier1_pct"],
            "holdover_tier2_pct": lease["holdover_tier2_pct"],
            "holdover_tier1_days": lease["holdover_tier1_days"],
            "status": "DRAFT",
            "holdover_entered_at": None,
            "accrued_holdover_rent_cents": 0,
            "active_amendment_id": None,
            "_vacate_requested": False,
        })
    supersede_nonterminal_options(lease["id"],
                                  except_option_id=option["id"] if option else None)


def transition_lease_terminated(lease, option):
    lease["status"] = "TERMINATED"
    touch(lease)
    supersede_nonterminal_options(lease["id"],
                                  except_option_id=option["id"] if option else None)


def try_complete_exercise(option, now):
    """Option NOTICE_SENT -> EXERCISED once the acknowledgment and the pricing
    gate (FINAL assessment for FAIR_MARKET) have both cleared; then the
    lease-level cascade when the target date has been reached."""
    if option["status"] != "NOTICE_SENT":
        return
    acked = [n for n in option_notices(option["id"]) if n["status"] == "ACKNOWLEDGED"]
    if not acked:
        return
    if option["rate_determination"] == "FAIR_MARKET":
        finals = [m for m in option_assessments(option["id"]) if m["status"] == "FINAL"]
        if not finals:
            return
        rent = finals[-1]["determined_rent_cents"]
    else:
        rent = option["fixed_rent_cents_per_rsf_year"]
    option["status"] = "EXERCISED"
    option["exercised_at"] = fmt_dt(now)
    option["determined_rent_cents_per_rsf_year"] = rent
    refresh(option)
    cancel_pending_reminders_for_option(option["id"])
    fee = option.get("exercise_fee_cents") or 0
    if fee > 0:
        post_ledger(option["lease_id"], "OPTION_FEE", fee, now.date(),
                    source_option_id=option["id"])
    # lease-level cascade (hop 2) — only from ACTIVE/EXPIRING and only when the
    # target date has been reached; EXPANSION/ROFR complete at the option level
    lease = db["leases"].get(option["lease_id"])
    if lease is None or lease["status"] not in ("ACTIVE", "EXPIRING"):
        return
    target = parse_date_value(option["target_commencement_date"])
    if target > now.date():
        return
    if option["option_type"] == "RENEWAL":
        transition_lease_renewed(lease, option)
    elif option["option_type"] == "TERMINATION":
        transition_lease_terminated(lease, option)


# ---------------------------------------------------------------------------
# Negotiation timeline compliance (§3.7 calculation)
# ---------------------------------------------------------------------------

def compute_compliance(portfolio_id):
    clock_date = CLOCK.today()
    items = []
    leases = sorted(
        [l for l in db["leases"].values() if l["portfolio_id"] == portfolio_id],
        key=lambda l: l["_seq"],
    )
    for lease in leases:
        exp = parse_date_value(lease["expiration_date"])
        deadline = exp - timedelta(days=LEAD_DAYS_REQUIRED)
        amendments = sorted(lease_amendments(lease["id"]), key=lambda a: a["_seq"])
        amend_items = []
        for a in amendments:
            opened = a.get("negotiation_opened_at")
            executed = a.get("executed_at")
            neg = None
            if opened:
                neg = "ON_TIME" if parse_dt(opened).date() <= deadline else "LATE"
            exe = None
            if executed:
                exe = ("EXECUTION_COMPLIANT" if parse_dt(executed).date() < exp
                       else "EXECUTION_NON_COMPLIANT")
            amend_items.append({
                "amendment_id": a["id"],
                "status": a["status"],
                "negotiation_opened_at": opened,
                "executed_at": executed,
                "negotiation_compliance": neg,
                "execution_compliance": exe,
            })
        opened_any = [a for a in amendments if a.get("negotiation_opened_at")]
        if opened_any:
            earliest = min(parse_dt(a["negotiation_opened_at"]).date() for a in opened_any)
            compliance = "ON_TIME" if earliest <= deadline else "LATE"
        elif clock_date > deadline and lease["status"] in ("ACTIVE", "EXPIRING"):
            compliance = "NEGOTIATION_MISSING"
        else:
            compliance = None
        executed_any = [a for a in amendments if a["status"] == "EXECUTED" and a.get("executed_at")]
        if executed_any:
            latest = max(parse_dt(a["executed_at"]).date() for a in executed_any)
            execution = ("EXECUTION_COMPLIANT" if latest < exp
                         else "EXECUTION_NON_COMPLIANT")
        else:
            execution = None
        items.append({
            "lease_id": lease["id"],
            "lease_status": lease["status"],
            "expiration_date": lease["expiration_date"],
            "initiation_deadline": fmt_date_midnight(deadline),
            "compliance": compliance,
            "negotiation_compliance": compliance,
            "execution_compliance": execution,
            "amendments": amend_items,
        })
    return items
