"""Calculation rules (SCAFFOLD §1.3 / PRD §2.6, §3.7).

All money is integer cents with round-half-up rounding; tonnage conversions use
exactly 2,000 lbs per short ton as an exact decimal; diversion rates carry two
decimal places rounded half-up.
"""

import calendar
from decimal import Decimal, ROUND_HALF_UP

from util import DIVERTED_ROUTES

TON_LBS = 2000
MAJOR_FLOOR = Decimal("5")
CRITICAL_FLOOR = Decimal("10")

CENT = Decimal("1")
PCT_2DP = Decimal("0.01")

CERT_THRESHOLDS = {
    "BRONZE": Decimal("50.0"),
    "SILVER": Decimal("70.0"),
    "GOLD": Decimal("85.0"),
    "ZERO_WASTE": Decimal("90.0"),
}


def dec(v):
    return Decimal(str(v))


def round_cents(d):
    return int(d.quantize(CENT, rounding=ROUND_HALF_UP))


def rate_pct(diverted, total):
    """round_half_up(diverted * 100 / total, 2); exactly 0.00 when total is 0."""
    if total == 0:
        return 0.0
    val = (Decimal(diverted) * 100 / Decimal(total)).quantize(
        PCT_2DP, rounding=ROUND_HALF_UP)
    return float(val)


def severity_of(pct):
    p = dec(pct)
    if p < MAJOR_FLOOR:
        return "MINOR"
    if p < CRITICAL_FLOOR:
        return "MAJOR"
    return "CRITICAL"


def per_ticket_estimate(ticket, contract, pct):
    """Per-ticket rebate estimate in cents for a diverted ticket.

    pct is the contamination percentage to use (already resolved; None -> 0).
    LANDFILL / ENERGY_RECOVERY accrue zero.
    """
    if ticket["disposal_route"] not in DIVERTED_ROUTES:
        return 0
    p = dec(pct) if pct is not None else Decimal("0")
    tons = Decimal(ticket["net_weight_lbs"]) / Decimal(TON_LBS)
    if p < MAJOR_FLOOR:
        qf = Decimal("1")
    elif p < CRITICAL_FLOOR:
        qf = Decimal("0.75")
    else:
        qf = Decimal("0.5")
    rebate_part = round_cents(tons * dec(contract["rebate_per_ton_cents"]) * qf)
    if p >= CRITICAL_FLOOR:
        penalty_part = round_cents(
            tons * dec(contract["contamination_penalty_per_ton_cents"]))
    else:
        penalty_part = 0
    return rebate_part - penalty_part


def _window_tickets(store, period):
    ws, we = period["period_start"], period["period_end"]
    return [t for t in store.tickets.values()
            if t["site_id"] == period["site_id"] and ws <= t["ticket_date"] < we]


def validated_diverted_tickets(store, period):
    return [t for t in _window_tickets(store, period)
            if t["validation_status"] == "VALIDATED"
            and t["disposal_route"] in DIVERTED_ROUTES]


def compute_live_period(store, period):
    """Live scorecard figures for an OPEN period (certified + provisional)."""
    tickets = _window_tickets(store, period)
    validated = [t for t in tickets if t["validation_status"] == "VALIDATED"]
    provisional = [t for t in tickets
                   if t["validation_status"] in ("PENDING", "VALIDATED")]

    total_v = sum(t["net_weight_lbs"] for t in validated)
    div_v = sum(t["net_weight_lbs"] for t in validated
                if t["disposal_route"] in DIVERTED_ROUTES)
    total_p = sum(t["net_weight_lbs"] for t in provisional)
    div_p = sum(t["net_weight_lbs"] for t in provisional
                if t["disposal_route"] in DIVERTED_ROUTES)

    rebate = 0
    for t in validated:
        if t["disposal_route"] not in DIVERTED_ROUTES:
            continue
        contract = store.contracts.get(t["contract_id"])
        if contract is None:
            continue
        rebate += per_ticket_estimate(t, contract, t.get("contamination_pct"))

    ws, we = period["period_start"], period["period_end"]
    event_count = sum(
        1 for e in store.events.values()
        if e["site_id"] == period["site_id"]
        and e["status"] != "DISMISSED"
        and ws <= e["event_date"] < we)

    return {
        "total_waste_lbs_validated": total_v,
        "diverted_lbs_validated": div_v,
        "diversion_rate_certified_pct": rate_pct(div_v, total_v),
        "total_waste_lbs_provisional": total_p,
        "diverted_lbs_provisional": div_p,
        "diversion_rate_provisional_pct": rate_pct(div_p, total_p),
        "rebate_estimate_cents": rebate,
        "contamination_event_count": event_count,
    }


def audit_adjusted_settlement(store, period):
    """rebate_settled_cents at close: audit contamination overrides ticket pct.

    For each material stream with a covering audit (same site, audit_date in the
    period window, stream reported in stream_findings) the audit's pct replaces
    every in-window VALIDATED ticket's own pct for that stream. Multiple
    covering audits: greatest audit_date wins, tie-break greatest created_at.
    """
    ws, we = period["period_start"], period["period_end"]
    best = {}  # stream -> (sort_key, pct)
    for a in store.audits.values():
        if a["site_id"] != period["site_id"]:
            continue
        if not (ws <= a["audit_date"] < we):
            continue
        for f in a["stream_findings"]:
            s = f["material_stream"]
            key = (a["audit_date"], a["created_at"], a["_seq"])
            if s not in best or key > best[s][0]:
                best[s] = (key, f["contamination_pct"])

    total = 0
    for t in validated_diverted_tickets(store, period):
        contract = store.contracts.get(t["contract_id"])
        if contract is None:
            continue
        stream = t["material_stream"]
        pct = best[stream][1] if stream in best else t.get("contamination_pct")
        total += per_ticket_estimate(t, contract, pct)
    return total


def cost_avoidance(store, period, site):
    """cost_avoided_cents at close; per-ticket rounding first, then sum."""
    fee = dec(site["landfill_tip_fee_per_ton_cents"])
    total = 0
    for t in validated_diverted_tickets(store, period):
        per = (Decimal(t["net_weight_lbs"]) / Decimal(TON_LBS)) * fee
        total += round_cents(per)
    return total


def derive_standing(store, site_id):
    """program_standing over non-terminal events (OPEN/TRAINING_*)."""
    non_terminal = [e for e in store.events.values()
                    if e["site_id"] == site_id
                    and e["status"] in ("OPEN", "TRAINING_ASSIGNED",
                                        "TRAINING_COMPLETED")]
    if any(e["severity"] == "CRITICAL" for e in non_terminal):
        return "PROBATION"
    if len(non_terminal) >= 2:
        return "WATCH"
    return "GOOD_STANDING"


def derive_tier(store, site_id):
    """certification_tier from APPROVED, non-LAPSED, non-SUPERSEDED applications."""
    from db import parse_iso_dt
    apps = [a for a in store.applications.values()
            if a["site_id"] == site_id and a["status"] == "APPROVED"]
    if not apps:
        return "NONE"
    best = max(apps, key=lambda a: (parse_iso_dt(a["decided_at"]), a["_seq"]))
    return best["level_requested"]


def add_months(dt, months):
    """Add calendar months to a datetime, clamping the day of month."""
    y = dt.year + (dt.month - 1 + months) // 12
    m = (dt.month - 1 + months) % 12 + 1
    d = min(dt.day, calendar.monthrange(y, m)[1])
    return dt.replace(year=y, month=m, day=d)
