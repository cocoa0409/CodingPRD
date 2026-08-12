"""Calculation rules per SCAFFOLD §1.3. All money is integer cents; half-up rounding via Decimal."""
from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta

import db

# Constants
PRO_PRICE_FLOOR_CENTS = 4000
PRO_CAPACITY_FLOOR = 500
BREACH_FLOOR_CENTS = 500000
LATE_FEE_CAP_MULTIPLE_OF_DEPOSIT = 2
FULL_REFUND_DAYS = 30
PARTIAL_REFUND_DAYS = 7


def _rh(dec):
    """Round half-up to integer cents."""
    return int(Decimal(dec).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def tier_multiplier(house_seating_capacity):
    if house_seating_capacity <= 199:
        return Decimal("1.00")
    if house_seating_capacity <= 399:
        return Decimal("1.25")
    if house_seating_capacity <= 799:
        return Decimal("1.60")
    return Decimal("2.00")


def class_multiplier(classification):
    return Decimal("1.00") if classification == "AMATEUR" else Decimal("1.50")


def per_performance_royalty(title, classification, house_seating_capacity, gross_cents, performance_count):
    """per_perf_royalty = per_perf_flat + per_perf_pct (each rounded half-up at its own step)."""
    tm = tier_multiplier(house_seating_capacity)
    cm = class_multiplier(classification)
    basis = title["royalty_basis"]
    if basis in ("PER_PERFORMANCE", "HYBRID"):
        per_perf_flat = _rh(Decimal(title["base_flat_fee_cents"]) * tm * cm)
    else:
        per_perf_flat = 0
    if basis in ("GROSS_PERCENT", "HYBRID"):
        # round_half_up(gross_cents * gross_percent_bp / 10000 / performance_count)
        per_perf_pct = _rh(
            Decimal(gross_cents) * Decimal(title["gross_percent_bp"]) / Decimal(10000) / Decimal(performance_count)
        )
    else:
        per_perf_pct = 0
    return per_perf_flat + per_perf_pct


def quoted_royalty_total(title, application):
    """QUOTED variant: over projected figures."""
    per_perf = per_performance_royalty(
        title,
        application["determined_classification"],
        application["venue_seating_capacity"],
        application["projected_gross_cents"],
        application["performance_count"],
    )
    return per_perf * application["performance_count"]


def settled_single_performance_royalty(title, agreement, performance):
    """SETTLED single: divisor 1; gross = reported_gross_cents."""
    return per_performance_royalty(
        title,
        agreement["classification"],
        agreement["house_seating_capacity"],
        performance["reported_gross_cents"],
        1,
    )


def settled_aggregate_royalty(title, agreement, held_performances):
    """SETTLED aggregate: sum over HELD performances of per-performance royalty."""
    total = 0
    for p in held_performances:
        total += settled_single_performance_royalty(title, agreement, p)
    return total


def compute_classification(application, organization):
    if organization["org_kind"] == "PROFESSIONAL_COMPANY":
        return "PROFESSIONAL"
    if application["performers_compensated"]:
        return "PROFESSIONAL"
    if (not application["admission_charged"]) and organization["org_kind"] == "SCHOOL":
        return "AMATEUR"
    if application["ticket_top_price_cents"] >= PRO_PRICE_FLOOR_CENTS:
        return "PROFESSIONAL"
    if application["venue_seating_capacity"] >= PRO_CAPACITY_FLOOR:
        return "PROFESSIONAL"
    return "AMATEUR"


def overdue_fine_cents(rental, title, evaluation_clock):
    """overdue_fine_rule — raw first, then cap at 2x deposit."""
    delta = evaluation_clock - rental["due_date"]
    days = int(delta.total_seconds() // 86400)
    if days < 0:
        days = 0
    if title["restricted_material"]:
        daily = title["restricted_late_fee_per_day_cents"]
    else:
        daily = title["late_fee_per_day_cents"]
    raw = days * daily
    capped = min(raw, rental["deposit_cents"] * LATE_FEE_CAP_MULTIPLE_OF_DEPOSIT)
    return capped


def deposit_settlement(rental, damage_lines, accrued_late_fee_cents):
    """deposit_settlement_rule — per-line rounding BEFORE summation (pinned).

    Returns (deposit_status, refund_cents, total_deduction_cents).
    """
    total_damage = 0
    for d in damage_lines or []:
        amt = Decimal(int(d.get("amount_cents", 0)))
        frac = Decimal(str(d.get("damage_fraction", 0)))
        total_damage += _rh(amt * frac)
    total_deduction = total_damage + accrued_late_fee_cents
    if total_deduction == 0:
        return "RETURNED", rental["deposit_cents"], 0
    if total_deduction < rental["deposit_cents"]:
        return "PARTIALLY_FORFEITED", rental["deposit_cents"] - total_deduction, total_deduction
    return "FORFEITED", 0, total_deduction


def recording_royalty(title, grant_kind, distribution_scope):
    base = Decimal(title["recording_royalty_flat_cents"])
    if grant_kind == "CAST_RECORDING_AUDIO":
        mult = Decimal("1.00")
    elif grant_kind == "ARCHIVAL_VIDEO":
        mult = Decimal("0.50")
    else:  # STREAMING_VIDEO
        mult = Decimal("2.00")
    if distribution_scope == "PUBLIC_FREE":
        mult = mult * Decimal("1.50")
    elif distribution_scope == "PAYWALL":
        mult = mult * Decimal("1.25")
    return _rh(base * mult)


def breach_fine_amount(fine_kind, quoted_royalty_total_cents):
    if fine_kind == "UNAUTHORIZED_ALTERATION":
        return max(BREACH_FLOOR_CENTS, 2 * quoted_royalty_total_cents)
    # UNAUTHORIZED_RECORDING
    return max(BREACH_FLOOR_CENTS, 3 * quoted_royalty_total_cents)


def cancellation_refund(agreement, payments, current_clock):
    """cancellation_refund_rule — pool rounded once, allocated oldest-first.

    Returns total refund cents; mutates each payment's refunded_cents.
    """
    delta = agreement["window_start"] - current_clock
    days = int(delta.total_seconds() // 86400)
    if days >= FULL_REFUND_DAYS:
        frac = Decimal("1.00")
    elif days >= PARTIAL_REFUND_DAYS:
        frac = Decimal("0.50")
    else:
        frac = Decimal("0.00")
    total_paid = sum(p["amount_cents"] for p in payments)
    pool = _rh(Decimal(total_paid) * frac)
    # chronological order, ties by insertion order (seq)
    ordered = sorted(payments, key=lambda p: (p["created_at"], p.get("_seq", 0)))
    remaining = pool
    for p in ordered:
        alloc = min(p["amount_cents"], remaining)
        p["refunded_cents"] = alloc
        remaining -= alloc
    return pool


def compute_availability(title_id, territory_code, classification, window_start, window_end):
    """availability_rule. Returns (available, blocking_restriction_ids, blocking_agreement_ids)."""
    blocking_restrictions = []
    for r in db.restrictions.values():
        if r["title_id"] != title_id:
            continue
        if r["territory_code"] != territory_code:
            continue
        if not r["active"]:
            continue
        if r["blocks_classification"] not in (classification, "BOTH"):
            continue
        # closed interval overlap: r.start <= req.end AND r.end >= req.start
        if r["window_start"] <= window_end and r["window_end"] >= window_start:
            blocking_restrictions.append(r["id"])

    blocking_agreements = []
    for g in db.agreements.values():
        if g["title_id"] != title_id:
            continue
        if g["territory_code"] != territory_code:
            continue
        if g["license_status"] != "ACTIVE":
            continue
        if not g.get("has_exclusive_run"):
            continue
        # half-open at end: g.start < req.end AND req.start < g.end
        if g["window_start"] < window_end and window_start < g["window_end"]:
            blocking_agreements.append(g["id"])

    available = (len(blocking_restrictions) == 0) and (len(blocking_agreements) == 0)
    return available, blocking_restrictions, blocking_agreements
